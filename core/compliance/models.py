from django.db import models
from django.utils import timezone
from core.users.models import User


class ComplianceDocument(models.Model):
    """
    Compliance documents and records
    """
    DOCUMENT_TYPE_CHOICES = [
        ('tds_certificate', 'TDS Certificate'),
        ('pan_card', 'PAN Card'),
        ('aadhaar', 'Aadhaar'),
        ('bank_statement', 'Bank Statement'),
        ('other', 'Other'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='compliance_documents')
    
    document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPE_CHOICES)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    file = models.FileField(upload_to='compliance/documents/')
    
    uploaded_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_documents')
    
    is_verified = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'compliance_documents'
        verbose_name = 'Compliance Document'
        verbose_name_plural = 'Compliance Documents'
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"{self.document_type} - {self.user.username}"


class TDSRecord(models.Model):
    """
    TDS records for tax compliance
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tds_records')
    
    financial_year = models.CharField(max_length=10)  # e.g., "2023-24"
    total_payout = models.DecimalField(max_digits=12, decimal_places=2)
    tds_deducted = models.DecimalField(max_digits=12, decimal_places=2)
    
    certificate_number = models.CharField(max_length=100, blank=True)
    certificate_file = models.FileField(upload_to='compliance/tds/', null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'tds_records'
        verbose_name = 'TDS Record'
        verbose_name_plural = 'TDS Records'
        ordering = ['-financial_year', '-created_at']
    
    def __str__(self):
        return f"TDS - {self.user.username} ({self.financial_year})"

