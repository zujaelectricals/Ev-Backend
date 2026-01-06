from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.shortcuts import get_object_or_404
from .models import User, KYC, Nominee
from .serializers import UserSerializer, UserProfileSerializer, KYCSerializer, NomineeSerializer


class UserViewSet(viewsets.ModelViewSet):
    """
    ViewSet for User management
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return User.objects.all()
        return User.objects.filter(id=user.id)
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def profile(self, request):
        """Get current user's profile"""
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)
    
    @action(detail=False, methods=['put', 'patch'], permission_classes=[IsAuthenticated])
    def update_profile(self, request):
        """Update current user's profile"""
        serializer = UserProfileSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class KYCViewSet(viewsets.ModelViewSet):
    """
    ViewSet for KYC management
    """
    queryset = KYC.objects.all()
    serializer_class = KYCSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return KYC.objects.all()
        return KYC.objects.filter(user=user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def approve(self, request, pk=None):
        """Approve KYC"""
        kyc = self.get_object()
        kyc.status = 'approved'
        kyc.reviewed_by = request.user
        kyc.save()
        return Response({'status': 'approved'})
    
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def reject(self, request, pk=None):
        """Reject KYC"""
        kyc = self.get_object()
        kyc.status = 'rejected'
        kyc.reviewed_by = request.user
        kyc.rejection_reason = request.data.get('reason', '')
        kyc.save()
        return Response({'status': 'rejected'})


class NomineeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Nominee management
    """
    queryset = Nominee.objects.all()
    serializer_class = NomineeSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return Nominee.objects.all()
        return Nominee.objects.filter(user=user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

