from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.db import transaction, models

from .models import (
    ComplianceDocument, TDSRecord, DistributorDocument, DistributorDocumentAcceptance,
    AsaTerms, PaymentTerms, UserAsaAcceptance, UserPaymentAcceptance
)
from .serializers import (
    ComplianceDocumentSerializer, TDSRecordSerializer,
    DistributorDocumentSerializer, DistributorDocumentListSerializer,
    DistributorDocumentAcceptanceSerializer,
    AcceptDocumentSerializer, VerifyAcceptanceOTPSerializer,
    AsaTermsSerializer, AsaTermsListSerializer,
    InitiateAsaAcceptanceSerializer, VerifyAsaAcceptanceSerializer,
    UserAsaAcceptanceSerializer,
    PaymentTermsSerializer, PaymentTermsListSerializer,
    InitiatePaymentTermsSerializer, VerifyPaymentTermsSerializer,
    AcceptPaymentTermsSerializer, UserPaymentAcceptanceSerializer
)
from .utils import (
    get_client_ip, create_user_info_snapshot, create_timeline_data,
    generate_asa_agreement_pdf, generate_payment_terms_receipt_pdf
)
from core.auth.utils import send_otp_dual_channel
from django.http import FileResponse
import logging

logger = logging.getLogger(__name__)


class ComplianceDocumentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Compliance Document management
    """
    queryset = ComplianceDocument.objects.all()
    serializer_class = ComplianceDocumentSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return ComplianceDocument.objects.all()
        return ComplianceDocument.objects.filter(user=user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class TDSRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for TDS Record viewing
    """
    queryset = TDSRecord.objects.all()
    serializer_class = TDSRecordSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return TDSRecord.objects.all()
        return TDSRecord.objects.filter(user=user)


class DistributorDocumentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Distributor Document management
    - List/Retrieve: All authenticated users can view active documents
    - Create/Update/Delete: Admin/staff only
    """
    queryset = DistributorDocument.objects.all()
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        """Use different serializers for admin vs regular users"""
        if self.action in ['list', 'retrieve']:
            # Regular users see read-only version
            if not (self.request.user.is_superuser or self.request.user.role in ['admin', 'staff']):
                return DistributorDocumentListSerializer
        return DistributorDocumentSerializer
    
    def get_queryset(self):
        """Filter active documents for regular users"""
        user = self.request.user
        queryset = DistributorDocument.objects.all()
        
        # Regular users only see active documents
        if not (user.is_superuser or user.role in ['admin', 'staff']):
            now = timezone.now()
            queryset = queryset.filter(
                is_active=True,
                effective_from__lte=now
            ).filter(
                models.Q(effective_until__isnull=True) | models.Q(effective_until__gte=now)
            )
        
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """Set created_by to current user"""
        serializer.save(created_by=self.request.user)
    
    def perform_destroy(self, instance):
        """Permanently delete the distributor document"""
        instance.delete()
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def accept(self, request, pk=None):
        """
        Initiate document acceptance - sends OTP to user
        POST /api/compliance/distributor-documents/{id}/accept/
        """
        document = self.get_object()
        
        # Check if document is active
        if not document.is_active:
            return Response(
                {'error': 'This document is not active and cannot be accepted.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if document is effective
        now = timezone.now()
        if document.effective_from > now:
            return Response(
                {'error': 'This document is not yet effective.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if document.effective_until and document.effective_until < now:
            return Response(
                {'error': 'This document has expired.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Use user's email or mobile for OTP
        user = request.user
        identifier = user.email or user.mobile
        if not identifier:
            return Response(
                {'error': 'User must have email or mobile number to accept documents.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        otp_type = 'email' if user.email else 'mobile'
        
        # Send universal OTP
        otp_serializer = SendUniversalOTPSerializer(data={
            'identifier': identifier,
            'otp_type': otp_type
        })
        
        if otp_serializer.is_valid():
            result = otp_serializer.save()
            return Response({
                'message': 'OTP sent successfully. Please verify OTP to complete acceptance.',
                'otp_sent': result,
                'document_id': document.id,
                'document_version': document.version
            }, status=status.HTTP_200_OK)
        else:
            return Response(otp_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated], url_path='verify-acceptance')
    def verify_acceptance(self, request, pk=None):
        """
        Verify OTP and complete document acceptance
        POST /api/compliance/distributor-documents/{id}/verify-acceptance/
        """
        document = self.get_object()
        user = request.user
        
        # Add document_id to request data
        data = request.data.copy()
        data['document_id'] = document.id
        
        serializer = VerifyAcceptanceOTPSerializer(data=data)
        
        if serializer.is_valid():
            validated_data = serializer.validated_data
            verified_user = validated_data['user']
            verified_document = validated_data['document']
            otp_identifier = validated_data['otp_identifier']
            
            # Ensure the user in request matches the verified user
            if verified_user.id != user.id:
                return Response(
                    {'error': 'OTP verification failed. User mismatch.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Capture IP address and user agent
            ip_address = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            
            # Create user info snapshot
            user_info_snapshot = create_user_info_snapshot(user)
            
            # Create timeline data
            timeline_data = create_timeline_data(user, verified_document, ip_address, user_agent)
            
            # Create acceptance record
            with transaction.atomic():
                acceptance = DistributorDocumentAcceptance.objects.create(
                    user=user,
                    document=verified_document,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    otp_verified=True,
                    otp_identifier=otp_identifier,
                    accepted_version=verified_document.version,
                    timeline_data=timeline_data,
                    user_info_snapshot=user_info_snapshot
                )
            
            # Return acceptance details
            acceptance_serializer = DistributorDocumentAcceptanceSerializer(acceptance)
            return Response({
                'message': 'Document accepted successfully.',
                'acceptance': acceptance_serializer.data
            }, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DistributorDocumentAcceptanceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for viewing document acceptance history
    - Users see their own acceptances
    - Admins see all acceptances
    """
    queryset = DistributorDocumentAcceptance.objects.all()
    serializer_class = DistributorDocumentAcceptanceSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role in ['admin', 'staff']:
            return DistributorDocumentAcceptance.objects.all()
        return DistributorDocumentAcceptance.objects.filter(user=user)


# ============================================================================
# ASA Terms ViewSets
# ============================================================================

class AsaTermsViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ASA Terms management
    - List/Retrieve: All authenticated users can view active terms
    - Create/Update/Delete: Admin/staff only
    """
    queryset = AsaTerms.objects.all()
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        """Use different serializers for admin vs regular users"""
        if self.action in ['list', 'retrieve']:
            # Regular users see read-only version
            if not (self.request.user.is_superuser or self.request.user.role in ['admin', 'staff']):
                return AsaTermsListSerializer
        return AsaTermsSerializer
    
    def get_queryset(self):
        """Filter active terms for regular users"""
        user = self.request.user
        queryset = AsaTerms.objects.all()
        
        # Regular users only see active terms
        if not (user.is_superuser or user.role in ['admin', 'staff']):
            now = timezone.now()
            queryset = queryset.filter(
                is_active=True,
                effective_from__lte=now
            )
        
        return queryset.order_by('-effective_from', '-created_at')
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def active(self, request):
        """
        Get the currently active ASA Terms
        GET /api/terms/asa/active/
        """
        now = timezone.now()
        active_terms = AsaTerms.objects.filter(
            is_active=True,
            effective_from__lte=now
        ).first()
        
        if not active_terms:
            return Response(
                {'error': 'No active ASA Terms found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(active_terms, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated], url_path='accept/initiate')
    def initiate_acceptance(self, request, pk=None):
        """
        Initiate ASA Terms acceptance - sends OTP to user (email + SMS)
        POST /api/terms/asa/{id}/accept/initiate/
        """
        asa_terms = self.get_object()
        user = request.user
        
        # Check if terms is active
        if not asa_terms.is_active:
            return Response(
                {'error': 'This ASA Terms version is not active and cannot be accepted.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if terms is effective
        now = timezone.now()
        if asa_terms.effective_from > now:
            return Response(
                {'error': 'This ASA Terms version is not yet effective.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate checkboxes
        serializer = InitiateAsaAcceptanceSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user has email or mobile
        if not user.email and not user.mobile:
            return Response(
                {'error': 'User must have email or mobile number to accept ASA Terms.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Send OTP via dual channel (email + SMS)
        try:
            otp_result = send_otp_dual_channel(user)
            return Response({
                'message': 'OTP sent successfully. Please verify OTP to complete acceptance.',
                'otp_sent': {
                    'email': otp_result['email']['success'],
                    'sms': otp_result['sms']['success'],
                },
                'terms_id': asa_terms.id,
                'terms_version': asa_terms.version
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Failed to send OTP for ASA Terms acceptance: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to send OTP. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated], url_path='accept/verify')
    def verify_acceptance(self, request, pk=None):
        """
        Verify OTP and complete ASA Terms acceptance
        POST /api/terms/asa/{id}/accept/verify/
        """
        asa_terms = self.get_object()
        user = request.user
        
        # Add terms_id to request data
        data = request.data.copy()
        data['terms_id'] = asa_terms.id
        
        serializer = VerifyAsaAcceptanceSerializer(data=data)
        
        if serializer.is_valid():
            validated_data = serializer.validated_data
            verified_user = validated_data['user']
            verified_terms = validated_data['asa_terms']
            otp_identifier = validated_data['otp_identifier']
            
            # Ensure the user in request matches the verified user
            if verified_user.id != user.id:
                return Response(
                    {'error': 'OTP verification failed. User mismatch.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Capture IP address and user agent
            ip_address = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            
            # Create acceptance record and generate PDF
            try:
                with transaction.atomic():
                    # Create acceptance record first (without PDF)
                    acceptance = UserAsaAcceptance.objects.create(
                        user=user,
                        terms_version=verified_terms.version,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        otp_verified=True,
                        otp_identifier=otp_identifier,
                        pdf_hash=''  # Temporary, will be updated
                    )
                    
                    # Generate PDF
                    pdf_file, pdf_hash = generate_asa_agreement_pdf(user, verified_terms, acceptance)
                    
                    # Update acceptance with PDF and hash
                    acceptance.agreement_pdf_url = pdf_file
                    acceptance.pdf_hash = pdf_hash
                    acceptance.save()
                
                # Return acceptance details
                acceptance_serializer = UserAsaAcceptanceSerializer(acceptance)
                return Response({
                    'message': 'ASA Terms accepted successfully.',
                    'acceptance': acceptance_serializer.data
                }, status=status.HTTP_201_CREATED)
            except Exception as e:
                logger.error(f"Failed to create ASA acceptance: {str(e)}", exc_info=True)
                return Response(
                    {'error': 'Failed to complete acceptance. Please try again.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated], url_path='agreement/(?P<acceptance_id>[^/.]+)/download')
    def download_agreement(self, request, acceptance_id=None):
        """
        Download ASA Agreement PDF
        GET /api/terms/asa/agreement/{acceptance_id}/download/
        """
        try:
            acceptance = UserAsaAcceptance.objects.get(id=acceptance_id)
            
            # Check permissions
            user = request.user
            if not (user.is_superuser or user.role in ['admin', 'staff']) and acceptance.user != user:
                return Response(
                    {'error': 'You do not have permission to access this agreement.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if not acceptance.agreement_pdf_url:
                return Response(
                    {'error': 'Agreement PDF not found.'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Return PDF file
            return FileResponse(
                acceptance.agreement_pdf_url.open('rb'),
                content_type='application/pdf',
                filename=f"asa_agreement_{acceptance.id}.pdf"
            )
        except UserAsaAcceptance.DoesNotExist:
            return Response(
                {'error': 'Acceptance record not found.'},
                status=status.HTTP_404_NOT_FOUND
            )


class UserAsaAcceptanceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for viewing ASA acceptance history
    - Users see their own acceptances
    - Admins see all acceptances
    """
    queryset = UserAsaAcceptance.objects.all()
    serializer_class = UserAsaAcceptanceSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role in ['admin', 'staff']:
            return UserAsaAcceptance.objects.all()
        return UserAsaAcceptance.objects.filter(user=user)


# ============================================================================
# Payment Terms ViewSets
# ============================================================================

class PaymentTermsViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Payment Terms management
    - List/Retrieve: All authenticated users can view active terms
    - Create/Update/Delete: Admin/staff only
    """
    queryset = PaymentTerms.objects.all()
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        """Use different serializers for admin vs regular users"""
        if self.action in ['list', 'retrieve']:
            # Regular users see read-only version
            if not (self.request.user.is_superuser or self.request.user.role in ['admin', 'staff']):
                return PaymentTermsListSerializer
        return PaymentTermsSerializer
    
    def get_queryset(self):
        """Filter active terms for regular users"""
        user = self.request.user
        queryset = PaymentTerms.objects.all()
        
        # Regular users only see active terms
        if not (user.is_superuser or user.role in ['admin', 'staff']):
            now = timezone.now()
            queryset = queryset.filter(
                is_active=True,
                effective_from__lte=now
            )
        
        return queryset.order_by('-effective_from', '-created_at')
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def active(self, request):
        """
        Get the currently active Payment Terms
        GET /api/terms/payment/active/
        """
        now = timezone.now()
        active_terms = PaymentTerms.objects.filter(
            is_active=True,
            effective_from__lte=now
        ).first()
        
        if not active_terms:
            return Response(
                {'error': 'No active Payment Terms found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(active_terms, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated], url_path='accept/initiate')
    def initiate_acceptance(self, request, pk=None):
        """
        Initiate Payment Terms acceptance - sends OTP to user (email + SMS)
        POST /api/compliance/terms/payment/{id}/accept/initiate/
        """
        payment_terms = self.get_object()
        user = request.user
        
        # Check if terms is active
        if not payment_terms.is_active:
            return Response(
                {'error': 'This Payment Terms version is not active and cannot be accepted.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if terms is effective
        now = timezone.now()
        if payment_terms.effective_from > now:
            return Response(
                {'error': 'This Payment Terms version is not yet effective.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate request
        serializer = InitiatePaymentTermsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user has email or mobile
        if not user.email and not user.mobile:
            return Response(
                {'error': 'User must have email or mobile number to accept Payment Terms.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Send OTP via dual channel (email + SMS)
        try:
            otp_result = send_otp_dual_channel(user)
            return Response({
                'message': 'OTP sent successfully. Please verify OTP to complete acceptance.',
                'otp_sent': {
                    'email': otp_result['email']['success'],
                    'sms': otp_result['sms']['success'],
                },
                'terms_id': payment_terms.id,
                'terms_version': payment_terms.version
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Failed to send OTP for Payment Terms acceptance: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to send OTP. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated], url_path='accept/verify')
    def verify_acceptance(self, request, pk=None):
        """
        Verify OTP and complete Payment Terms acceptance
        POST /api/compliance/terms/payment/{id}/accept/verify/
        """
        payment_terms = self.get_object()
        user = request.user
        
        # Add terms_id to request data
        data = request.data.copy()
        data['terms_id'] = payment_terms.id
        
        serializer = VerifyPaymentTermsSerializer(data=data)
        
        if serializer.is_valid():
            validated_data = serializer.validated_data
            verified_user = validated_data['user']
            verified_terms = validated_data['payment_terms']
            otp_identifier = validated_data['otp_identifier']
            generate_pdf = validated_data.get('generate_pdf', False)
            
            # Ensure the user in request matches the verified user
            if verified_user.id != user.id:
                return Response(
                    {'error': 'OTP verification failed. User mismatch.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Capture IP address and user agent
            ip_address = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            
            # Create acceptance record
            try:
                with transaction.atomic():
                    acceptance = UserPaymentAcceptance.objects.create(
                        user=user,
                        payment_terms_version=verified_terms.version,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        otp_verified=True,
                        otp_identifier=otp_identifier
                    )
                    
                    # Generate PDF if requested
                    if generate_pdf:
                        try:
                            pdf_file = generate_payment_terms_receipt_pdf(user, verified_terms, acceptance)
                            acceptance.receipt_pdf_url = pdf_file
                            acceptance.save()
                            # Verify file was saved
                            if not acceptance.receipt_pdf_url:
                                logger.error(f"PDF file was not saved for acceptance {acceptance.id}")
                        except Exception as pdf_error:
                            logger.error(f"Failed to generate payment terms PDF: {str(pdf_error)}", exc_info=True)
                            # Don't fail the acceptance if PDF generation fails, but log the error
                
                # Return acceptance details
                acceptance_serializer = UserPaymentAcceptanceSerializer(acceptance, context={'request': request})
                return Response({
                    'message': 'Payment Terms accepted successfully.',
                    'acceptance': acceptance_serializer.data
                }, status=status.HTTP_201_CREATED)
            except Exception as e:
                logger.error(f"Failed to create Payment Terms acceptance: {str(e)}", exc_info=True)
                return Response(
                    {'error': 'Failed to complete acceptance. Please try again.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated], url_path='receipt/(?P<acceptance_id>[^/.]+)')
    def download_receipt(self, request, acceptance_id=None):
        """
        Download Payment Terms Receipt PDF
        GET /api/terms/payment/receipt/{acceptance_id}/
        """
        try:
            acceptance = UserPaymentAcceptance.objects.get(id=acceptance_id)
            
            # Check permissions
            user = request.user
            if not (user.is_superuser or user.role in ['admin', 'staff']) and acceptance.user != user:
                return Response(
                    {'error': 'You do not have permission to access this receipt.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if not acceptance.receipt_pdf_url:
                return Response(
                    {'error': 'Receipt PDF not found.'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Return PDF file
            return FileResponse(
                acceptance.receipt_pdf_url.open('rb'),
                content_type='application/pdf',
                filename=f"payment_terms_receipt_{acceptance.id}.pdf"
            )
        except UserPaymentAcceptance.DoesNotExist:
            return Response(
                {'error': 'Acceptance record not found.'},
                status=status.HTTP_404_NOT_FOUND
            )


class UserPaymentAcceptanceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for viewing Payment acceptance history
    - Users see their own acceptances
    - Admins see all acceptances
    """
    queryset = UserPaymentAcceptance.objects.all()
    serializer_class = UserPaymentAcceptanceSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role in ['admin', 'staff']:
            return UserPaymentAcceptance.objects.all()
        return UserPaymentAcceptance.objects.filter(user=user)

