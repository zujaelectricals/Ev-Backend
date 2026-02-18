from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from datetime import timedelta, datetime
import json
import logging
from .models import Payout, PayoutTransaction, PayoutWebhookLog
from .serializers import PayoutSerializer, PayoutTransactionSerializer
from .utils import process_payout, complete_payout, auto_fill_emi_from_payout
from .utils.signature import verify_payout_webhook_signature
from .tasks import process_payout_success, process_payout_failure
from core.wallet.utils import get_or_create_wallet
from core.settings.models import PlatformSettings

logger = logging.getLogger(__name__)


class PayoutPagination(PageNumberPagination):
    """Custom pagination for payout list with page_size support"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'


class PayoutViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Payout management
    """
    queryset = Payout.objects.all()
    serializer_class = PayoutSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = PayoutPagination
    
    def get_queryset(self):
        user = self.request.user
        queryset = Payout.objects.select_related('user', 'wallet')
        
        if user.is_superuser or user.role == 'admin':
            queryset = queryset.all()
        else:
            queryset = queryset.filter(user=user)
        
        # Filter by status
        status_param = self.request.query_params.get('status', None)
        if status_param:
            status_param = status_param.strip()
            queryset = queryset.filter(status=status_param)
        
        # Date filtering
        date_from = self.request.query_params.get('date_from', None)
        date_to = self.request.query_params.get('date_to', None)
        period = self.request.query_params.get('period', None)
        
        # Preset period takes precedence over date range
        if period:
            period = period.strip().lower()
            now = timezone.now()
            
            if period == 'last_7_days':
                date_from = (now - timedelta(days=7)).date()
                date_to = now.date()
            elif period == 'last_30_days':
                date_from = (now - timedelta(days=30)).date()
                date_to = now.date()
            elif period == 'last_90_days':
                date_from = (now - timedelta(days=90)).date()
                date_to = now.date()
            elif period == 'last_year':
                date_from = (now - timedelta(days=365)).date()
                date_to = now.date()
            elif period == 'all_time':
                # No date filter
                date_from = None
                date_to = None
        
        # Apply date filters
        if date_from:
            try:
                if isinstance(date_from, str):
                    date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__gte=timezone.make_aware(
                    datetime.combine(date_from, datetime.min.time())
                ))
            except ValueError:
                pass  # Invalid date format, ignore
        
        if date_to:
            try:
                if isinstance(date_to, str):
                    date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__lte=timezone.make_aware(
                    datetime.combine(date_to, datetime.max.time())
                ))
            except ValueError:
                pass  # Invalid date format, ignore
        
        return queryset.order_by('-created_at')
    
    def _get_wallet_summary(self, user):
        """Get wallet summary for user"""
        wallet = get_or_create_wallet(user)
        return {
            'current_balance': str(wallet.balance),
            'total_earned': str(wallet.total_earned),
            'total_withdrawn': str(wallet.total_withdrawn)
        }
    
    def _get_user_bank_details(self, user):
        """Get bank details from user's KYC document"""
        bank_details = []
        
        # Check if user has KYC with bank details
        try:
            kyc = user.kyc
            if kyc and kyc.bank_name and kyc.account_number:
                bank_details.append({
                    'bank_name': kyc.bank_name,
                    'account_number': kyc.account_number,
                    'ifsc_code': kyc.ifsc_code or '',
                    'account_holder_name': kyc.account_holder_name or ''
                })
        except Exception:
            # User doesn't have KYC or KYC doesn't have bank details
            pass
        
        return bank_details
    
    def _get_withdrawal_history(self, user, filters=None):
        """Get withdrawal history (completed payouts only)"""
        queryset = Payout.objects.filter(
            user=user,
            status='completed'
        ).select_related('user', 'wallet').order_by('-completed_at')
        
        # Track if date filter was actually applied
        date_filter_applied = False
        
        # Apply date filters if provided
        if filters:
            date_from = filters.get('date_from')
            date_to = filters.get('date_to')
            period = filters.get('period')
            
            # Preset period takes precedence
            if period:
                period = period.strip().lower()
                now = timezone.now()
                
                if period == 'last_7_days':
                    date_from = (now - timedelta(days=7)).date()
                    date_to = now.date()
                    date_filter_applied = True
                elif period == 'last_30_days':
                    date_from = (now - timedelta(days=30)).date()
                    date_to = now.date()
                    date_filter_applied = True
                elif period == 'last_90_days':
                    date_from = (now - timedelta(days=90)).date()
                    date_to = now.date()
                    date_filter_applied = True
                elif period == 'last_year':
                    date_from = (now - timedelta(days=365)).date()
                    date_to = now.date()
                    date_filter_applied = True
                elif period == 'all_time':
                    date_from = None
                    date_to = None
                    # all_time means no date filter
                    date_filter_applied = False
            
            if date_from:
                try:
                    if isinstance(date_from, str):
                        date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                    queryset = queryset.filter(completed_at__gte=timezone.make_aware(
                        datetime.combine(date_from, datetime.min.time())
                    ))
                    date_filter_applied = True
                except ValueError:
                    pass
            
            if date_to:
                try:
                    if isinstance(date_to, str):
                        date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                    queryset = queryset.filter(completed_at__lte=timezone.make_aware(
                        datetime.combine(date_to, datetime.max.time())
                    ))
                    date_filter_applied = True
                except ValueError:
                    pass
        
        # Limit to last 50 if no date filter was applied
        if not date_filter_applied:
            queryset = queryset[:50]
        
        return queryset
    
    def list(self, request, *args, **kwargs):
        """List payouts with comprehensive response including wallet summary and withdrawal history"""
        # Get filtered queryset
        queryset = self.filter_queryset(self.get_queryset())
        
        # Get paginated results
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated_response = self.get_paginated_response(serializer.data)
            
            # Extract pagination data
            try:
                page_num = int(request.query_params.get('page', 1))
            except (ValueError, TypeError):
                page_num = 1
            
            pagination_data = {
                'count': paginated_response.data['count'],
                'page': page_num,
                'page_size': len(page),
                'total_pages': paginated_response.data.get('total_pages', 1),
                'next': paginated_response.data.get('next'),
                'previous': paginated_response.data.get('previous'),
                'results': paginated_response.data['results']
            }
        else:
            # No pagination
            serializer = self.get_serializer(queryset, many=True)
            pagination_data = {
                'count': len(serializer.data),
                'page': 1,
                'page_size': len(serializer.data),
                'total_pages': 1,
                'next': None,
                'previous': None,
                'results': serializer.data
            }
        
        # Get wallet summary
        wallet_summary = self._get_wallet_summary(request.user)
        
        # Get withdrawal history filters
        withdrawal_filters = {
            'date_from': request.query_params.get('date_from'),
            'date_to': request.query_params.get('date_to'),
            'period': request.query_params.get('period')
        }
        
        # Get withdrawal history
        withdrawal_queryset = self._get_withdrawal_history(request.user, withdrawal_filters)
        withdrawal_serializer = self.get_serializer(withdrawal_queryset, many=True)
        
        # Get bank details from user's KYC
        bank_details = self._get_user_bank_details(request.user)
        
        # Build comprehensive response
        response_data = {
            'wallet_summary': wallet_summary,
            'bank_details': bank_details,
            'withdrawal_history': withdrawal_serializer.data,
            'payouts': pagination_data
        }
        
        return Response(response_data)
    
    def perform_create(self, serializer):
        user = self.request.user
        
        # Check KYC approval requirement
        if not hasattr(user, 'kyc') or user.kyc.status != 'approved':
            raise serializers.ValidationError("User must have approved KYC to request payout.")
        
        wallet = get_or_create_wallet(user)
        
        # Validate wallet balance
        requested_amount = serializer.validated_data['requested_amount']
        if wallet.balance < requested_amount:
            raise serializers.ValidationError("Insufficient wallet balance")
        
        # Create temporary payout instance to calculate TDS before saving
        temp_payout = Payout(user=user, wallet=wallet, requested_amount=requested_amount)
        temp_payout.calculate_tds()
        
        # Check if EMI auto-fill is requested
        emi_auto_filled = self.request.data.get('emi_auto_filled', False)
        if emi_auto_filled:
            emi_used, remaining = auto_fill_emi_from_payout(user, requested_amount)
            temp_payout.emi_amount = emi_used
            temp_payout.net_amount = remaining
            temp_payout.emi_auto_filled = True
        
        # Save payout with calculated TDS and net_amount
        payout = serializer.save(
            user=user,
            wallet=wallet,
            tds_amount=temp_payout.tds_amount,
            net_amount=temp_payout.net_amount,
            emi_amount=temp_payout.emi_amount,
            emi_auto_filled=temp_payout.emi_auto_filled
        )
        
        # Check payout_approval_needed setting
        platform_settings = PlatformSettings.get_settings()
        if not platform_settings.payout_approval_needed:
            # Auto-process payout if approval is not needed
            try:
                process_payout(payout)
            except Exception as e:
                # process_payout() already marks payout as 'failed' on error
                # Refresh from DB to get updated status
                payout.refresh_from_db()
                # Raise ValidationError to return HTTP 400 (not 201) on failure
                raise serializers.ValidationError(f"Failed to auto-process payout: {str(e)}")
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def process(self, request, pk=None):
        """
        Process payout (admin only)
        
        This endpoint:
        1. Validates payout is in 'pending' status
        2. Deducts amount from user's wallet
        3. Handles EMI auto-fill if enabled
        4. Sets status to 'processing' and records processed_at timestamp
        
        NOTE: Payment gateway integration will be added here in the future.
        After wallet deduction, the payment gateway API will be called to initiate transfer.
        
        Request Body (optional):
        {
            "notes": "Additional notes for processing"
        }
        """
        if not (request.user.is_superuser or request.user.role == 'admin'):
            return Response(
                {'error': 'Permission denied'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        payout = self.get_object()
        
        if payout.status != 'pending':
            return Response(
                {'error': f'Payout cannot be processed. Current status: {payout.status}. Expected: pending'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            process_payout(payout)
            
            # Update notes if provided
            notes = request.data.get('notes', '')
            if notes:
                payout.notes = notes
                payout.save(update_fields=['notes'])
            
            serializer = self.get_serializer(payout)
            return Response({
                'message': 'Payout processed successfully. Amount deducted from wallet.',
                'payout': serializer.data
            }, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': f'Failed to process payout: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def complete(self, request, pk=None):
        """
        Mark payout as completed (admin only)
        
        This endpoint should be called:
        - Manually by admin after verifying bank transfer was successful
        - Automatically by payment gateway webhook when transfer succeeds (future)
        - After synchronous payment gateway API returns success (future)
        
        Request Body:
        {
            "transaction_id": "TXN123456789",  // Optional: Transaction ID from payment gateway
            "notes": "Payment confirmed via bank statement"  // Optional: Additional notes
        }
        """
        if not (request.user.is_superuser or request.user.role == 'admin'):
            return Response(
                {'error': 'Permission denied'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        payout = self.get_object()
        
        if payout.status != 'processing':
            return Response(
                {'error': f'Payout cannot be completed. Current status: {payout.status}. Expected: processing'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            transaction_id = request.data.get('transaction_id', '')
            notes = request.data.get('notes', '')
            
            complete_payout(
                payout=payout,
                transaction_id=transaction_id if transaction_id else None,
                notes=notes if notes else None
            )
            
            serializer = self.get_serializer(payout)
            return Response({
                'message': 'Payout marked as completed successfully.',
                'payout': serializer.data
            }, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': f'Failed to complete payout: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


    # TODO: Future Payment Gateway Webhook Endpoint
    # @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    # def webhook(self, request):
    #     """
    #     Payment Gateway Webhook Handler (Future Implementation)
    #     
    #     This endpoint will be called by the payment gateway when:
    #     - Payout transfer succeeds
    #     - Payout transfer fails
    #     - Payout transfer status changes
    #     
    #     Expected Request Body (example):
    #     {
    #         "event": "payout.success" | "payout.failed" | "payout.pending",
    #         "payout_id": "internal_payout_id_or_reference",
    #         "gateway_transaction_id": "TXN123456789",
    #         "amount": "9500.00",
    #         "status": "success" | "failed" | "pending",
    #         "timestamp": "2026-01-06T14:00:00Z",
    #         "signature": "webhook_signature_for_verification"
    #     }
    #     
    #     Implementation Steps:
    #     1. Verify webhook signature for security
    #     2. Find payout by payout_id or gateway_transaction_id
    #     3. If event == "payout.success":
    #        - Call complete_payout(payout, transaction_id=gateway_transaction_id)
    #     4. If event == "payout.failed":
    #        - Set payout.status = 'rejected'
    #        - Refund amount to user's wallet
    #        - Store failure reason
    #     5. Return 200 OK to acknowledge webhook receipt
    #     """
    #     pass


class PayoutTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Payout Transaction viewing
    """
    queryset = PayoutTransaction.objects.all()
    serializer_class = PayoutTransactionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return PayoutTransaction.objects.all()
        return PayoutTransaction.objects.filter(user=user)


@csrf_exempt
def webhook(request):
    """
    Handle RazorpayX payout webhook events.
    
    POST /api/payouts/webhook/
    CSRF exempt for webhook endpoint
    
    Handles events:
    - payout.processed: Payout successfully completed
    - payout.failed: Payout failed
    - fund_account.verified: Fund account verified (logged for future use)
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        # Read raw body (required for signature verification)
        body = request.body
        
        # Extract signature from header
        header_signature = request.META.get('HTTP_X_RAZORPAY_SIGNATURE', '')
        
        if not header_signature:
            logger.warning("Payout webhook request missing X-Razorpay-Signature header")
            return JsonResponse({'error': 'Missing signature'}, status=400)
        
        # Verify webhook signature
        is_valid = verify_payout_webhook_signature(body, header_signature)
        
        if not is_valid:
            logger.warning("Invalid payout webhook signature")
            return JsonResponse({'error': 'Invalid signature'}, status=400)
        
        # Parse JSON body
        try:
            payload = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in payout webhook body: {e}")
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        
        event_type = payload.get('event')
        event_id = payload.get('event_id') or payload.get('id', 'unknown')
        
        logger.info(f"Received payout webhook event: {event_type} (event_id: {event_id})")
        
        # Check idempotency - see if event was already processed
        webhook_log = None
        try:
            webhook_log = PayoutWebhookLog.objects.get(event_id=event_id)
            if webhook_log.status == 'processed':
                logger.info(f"Payout webhook event {event_id} already processed, skipping")
                return JsonResponse({'status': 'success', 'message': 'Event already processed'}, status=200)
        except PayoutWebhookLog.DoesNotExist:
            # Create new webhook log entry
            webhook_log = PayoutWebhookLog.objects.create(
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                status='received'
            )
        
        # Route events to appropriate handlers
        try:
            if event_type == 'payout.processed':
                # Extract payout ID from payload
                payout_data = payload.get('payload', {}).get('payout', {})
                razorpay_payout_id = payout_data.get('id')
                
                if not razorpay_payout_id:
                    error_msg = "Missing payout ID in payout.processed event"
                    logger.error(error_msg)
                    webhook_log.status = 'failed'
                    webhook_log.error_message = error_msg
                    webhook_log.save()
                    return JsonResponse({'error': error_msg}, status=400)
                
                # Enqueue Celery task for async processing
                process_payout_success.delay(razorpay_payout_id, payload)
                
                # Update webhook log
                webhook_log.status = 'processed'
                webhook_log.processed_at = timezone.now()
                webhook_log.save()
                
                logger.info(f"Enqueued payout success task for Razorpay payout ID: {razorpay_payout_id}")
                
            elif event_type == 'payout.failed':
                # Extract payout ID from payload
                payout_data = payload.get('payload', {}).get('payout', {})
                razorpay_payout_id = payout_data.get('id')
                
                if not razorpay_payout_id:
                    error_msg = "Missing payout ID in payout.failed event"
                    logger.error(error_msg)
                    webhook_log.status = 'failed'
                    webhook_log.error_message = error_msg
                    webhook_log.save()
                    return JsonResponse({'error': error_msg}, status=400)
                
                # Enqueue Celery task for async processing
                process_payout_failure.delay(razorpay_payout_id, payload)
                
                # Update webhook log
                webhook_log.status = 'processed'
                webhook_log.processed_at = timezone.now()
                webhook_log.save()
                
                logger.info(f"Enqueued payout failure task for Razorpay payout ID: {razorpay_payout_id}")
                
            elif event_type == 'fund_account.verified':
                # Log event for future implementation
                logger.info(f"Fund account verified event received: {payload}")
                webhook_log.status = 'processed'
                webhook_log.processed_at = timezone.now()
                webhook_log.save()
                
            else:
                logger.warning(f"Unknown payout webhook event type: {event_type}")
                webhook_log.status = 'failed'
                webhook_log.error_message = f"Unknown event type: {event_type}"
                webhook_log.save()
        
        except Exception as e:
            logger.error(f"Error processing payout webhook event {event_id}: {e}", exc_info=True)
            webhook_log.status = 'failed'
            webhook_log.error_message = str(e)
            webhook_log.save()
        
        # Always return 200 OK to prevent Razorpay from retrying
        return JsonResponse({'status': 'success'}, status=200)
    
    except Exception as e:
        logger.error(f"Error processing payout webhook: {e}", exc_info=True)
        # Still return 200 to prevent retries
        return JsonResponse({'status': 'error', 'message': str(e)}, status=200)

