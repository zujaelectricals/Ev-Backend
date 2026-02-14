from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.db import transaction, models

from .models import ComplianceDocument, TDSRecord, DistributorDocument, DistributorDocumentAcceptance
from .serializers import (
    ComplianceDocumentSerializer, TDSRecordSerializer,
    DistributorDocumentSerializer, DistributorDocumentListSerializer,
    DistributorDocumentAcceptanceSerializer,
    AcceptDocumentSerializer, VerifyAcceptanceOTPSerializer
)
from .utils import get_client_ip, create_user_info_snapshot, create_timeline_data
from core.auth.serializers import SendUniversalOTPSerializer


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
        """Soft delete by setting is_active=False"""
        instance.is_active = False
        instance.save()
    
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
        
        # Check if user already accepted this version
        user = request.user
        existing_acceptance = DistributorDocumentAcceptance.objects.filter(
            user=user,
            document=document,
            accepted_version=document.version
        ).exists()
        
        if existing_acceptance:
            return Response(
                {'error': f'You have already accepted this document (version {document.version}).'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Use user's email or mobile for OTP
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

