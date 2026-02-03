"""
Unit tests for RazorpayX payout webhook
"""
import json
import hmac
import hashlib
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch, MagicMock
from decimal import Decimal
from core.payout.models import Payout, PayoutWebhookLog
from core.payout.utils.signature import verify_payout_webhook_signature
from core.users.models import User
from core.wallet.models import Wallet
from django.conf import settings


class PayoutWebhookSignatureTest(TestCase):
    """Test signature verification"""
    
    def setUp(self):
        self.secret = "test_webhook_secret"
        settings.RAZORPAY_PAYOUT_WEBHOOK_SECRET = self.secret
        self.body = b'{"event":"payout.processed","payload":{"payout":{"id":"pout_test123"}}}'
    
    def test_valid_signature(self):
        """Test that valid signature is verified correctly"""
        # Generate valid signature
        signature = hmac.new(
            self.secret.encode('utf-8'),
            self.body,
            hashlib.sha256
        ).hexdigest()
        
        result = verify_payout_webhook_signature(self.body, signature)
        self.assertTrue(result)
    
    def test_invalid_signature(self):
        """Test that invalid signature is rejected"""
        invalid_signature = "invalid_signature"
        result = verify_payout_webhook_signature(self.body, invalid_signature)
        self.assertFalse(result)
    
    def test_missing_secret(self):
        """Test that missing secret returns False"""
        settings.RAZORPAY_PAYOUT_WEBHOOK_SECRET = ''
        signature = "test_signature"
        result = verify_payout_webhook_signature(self.body, signature)
        self.assertFalse(result)


class PayoutWebhookViewTest(TestCase):
    """Test webhook view"""
    
    def setUp(self):
        self.client = Client()
        self.secret = "test_webhook_secret"
        settings.RAZORPAY_PAYOUT_WEBHOOK_SECRET = self.secret
        
        # Create test user and wallet
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.wallet = Wallet.objects.create(user=self.user, balance=Decimal('10000.00'))
    
    def _generate_signature(self, body):
        """Generate valid signature for test"""
        return hmac.new(
            self.secret.encode('utf-8'),
            body,
            hashlib.sha256
        ).hexdigest()
    
    def test_webhook_missing_signature(self):
        """Test webhook rejects request without signature"""
        payload = {'event': 'payout.processed'}
        response = self.client.post(
            '/api/payout/webhook/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('error', data)
    
    def test_webhook_invalid_signature(self):
        """Test webhook rejects request with invalid signature"""
        payload = {'event': 'payout.processed'}
        body = json.dumps(payload).encode('utf-8')
        response = self.client.post(
            '/api/payout/webhook/',
            data=body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='invalid_signature'
        )
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('error', data)
    
    def test_webhook_invalid_json(self):
        """Test webhook rejects invalid JSON"""
        body = b'invalid json'
        signature = self._generate_signature(body)
        response = self.client.post(
            '/api/payout/webhook/',
            data=body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature
        )
        self.assertEqual(response.status_code, 400)
    
    @patch('core.payout.views.process_payout_success.delay')
    def test_payout_processed_event(self, mock_task):
        """Test payout.processed event processing"""
        # Create a payout in processing status
        payout = Payout.objects.create(
            user=self.user,
            wallet=self.wallet,
            requested_amount=Decimal('5000.00'),
            net_amount=Decimal('4750.00'),
            tds_amount=Decimal('250.00'),
            bank_name='Test Bank',
            account_number='1234567890',
            ifsc_code='TEST0001234',
            account_holder_name='Test User',
            status='processing',
            transaction_id='pout_test123'
        )
        
        payload = {
            'event': 'payout.processed',
            'event_id': 'evt_test123',
            'payload': {
                'payout': {
                    'id': 'pout_test123'
                }
            }
        }
        body = json.dumps(payload).encode('utf-8')
        signature = self._generate_signature(body)
        
        response = self.client.post(
            '/api/payout/webhook/',
            data=body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'success')
        
        # Verify task was enqueued
        mock_task.assert_called_once_with('pout_test123', payload)
        
        # Verify webhook log was created
        webhook_log = PayoutWebhookLog.objects.get(event_id='evt_test123')
        self.assertEqual(webhook_log.event_type, 'payout.processed')
        self.assertEqual(webhook_log.status, 'processed')
    
    @patch('core.payout.views.process_payout_failure.delay')
    def test_payout_failed_event(self, mock_task):
        """Test payout.failed event processing"""
        # Create a payout in processing status
        payout = Payout.objects.create(
            user=self.user,
            wallet=self.wallet,
            requested_amount=Decimal('5000.00'),
            net_amount=Decimal('4750.00'),
            tds_amount=Decimal('250.00'),
            bank_name='Test Bank',
            account_number='1234567890',
            ifsc_code='TEST0001234',
            account_holder_name='Test User',
            status='processing',
            transaction_id='pout_test456'
        )
        
        payload = {
            'event': 'payout.failed',
            'event_id': 'evt_test456',
            'payload': {
                'payout': {
                    'id': 'pout_test456',
                    'failure_reason': 'Insufficient balance'
                }
            }
        }
        body = json.dumps(payload).encode('utf-8')
        signature = self._generate_signature(body)
        
        response = self.client.post(
            '/api/payout/webhook/',
            data=body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'success')
        
        # Verify task was enqueued
        mock_task.assert_called_once_with('pout_test456', payload)
        
        # Verify webhook log was created
        webhook_log = PayoutWebhookLog.objects.get(event_id='evt_test456')
        self.assertEqual(webhook_log.event_type, 'payout.failed')
        self.assertEqual(webhook_log.status, 'processed')
    
    def test_duplicate_webhook_handling(self):
        """Test that duplicate webhooks are handled idempotently"""
        payload = {
            'event': 'payout.processed',
            'event_id': 'evt_duplicate',
            'payload': {
                'payout': {
                    'id': 'pout_test789'
                }
            }
        }
        body = json.dumps(payload).encode('utf-8')
        signature = self._generate_signature(body)
        
        # Create webhook log as already processed
        PayoutWebhookLog.objects.create(
            event_id='evt_duplicate',
            event_type='payout.processed',
            payload=payload,
            status='processed',
            processed_at=timezone.now()
        )
        
        response = self.client.post(
            '/api/payout/webhook/',
            data=body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'success')
        self.assertIn('already processed', data.get('message', ''))
    
    def test_payout_not_found(self):
        """Test webhook with payout ID that doesn't exist"""
        payload = {
            'event': 'payout.processed',
            'event_id': 'evt_notfound',
            'payload': {
                'payout': {
                    'id': 'pout_nonexistent'
                }
            }
        }
        body = json.dumps(payload).encode('utf-8')
        signature = self._generate_signature(body)
        
        response = self.client.post(
            '/api/payout/webhook/',
            data=body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature
        )
        
        # Should still return 200 (webhook received)
        self.assertEqual(response.status_code, 200)
        
        # Webhook log should be created
        webhook_log = PayoutWebhookLog.objects.get(event_id='evt_notfound')
        self.assertEqual(webhook_log.status, 'processed')
    
    def test_unknown_event_type(self):
        """Test webhook with unknown event type"""
        payload = {
            'event': 'unknown.event',
            'event_id': 'evt_unknown',
            'payload': {}
        }
        body = json.dumps(payload).encode('utf-8')
        signature = self._generate_signature(body)
        
        response = self.client.post(
            '/api/payout/webhook/',
            data=body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature
        )
        
        # Should still return 200
        self.assertEqual(response.status_code, 200)
        
        # Webhook log should be marked as failed
        webhook_log = PayoutWebhookLog.objects.get(event_id='evt_unknown')
        self.assertEqual(webhook_log.status, 'failed')
        self.assertIn('Unknown event type', webhook_log.error_message)

