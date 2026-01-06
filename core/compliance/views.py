from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from .models import ComplianceDocument, TDSRecord
from .serializers import ComplianceDocumentSerializer, TDSRecordSerializer


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

