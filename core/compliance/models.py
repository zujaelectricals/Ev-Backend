from django.db import models
from django.utils import timezone
from core.users.models import User


class DistributorDocument(models.Model):
    """
    Distributor documents that users need to accept (Terms & Conditions, Legal Agreements, Policies, etc.)
    """
    DOCUMENT_TYPE_CHOICES = [
        ('terms_conditions', 'Terms & Conditions'),
        ('legal_agreement', 'Legal Agreement'),
        ('policy', 'Policy'),
        ('payment_terms', 'Payment Terms'),
        ('distributor_terms', 'Distributor Terms'),
        ('other', 'Other'),
    ]
    
    title = models.CharField(max_length=200)
    document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPE_CHOICES, default='other')
    content = models.TextField(help_text="Document content/text")
    file = models.FileField(upload_to='compliance/distributor_documents/', null=True, blank=True, help_text="Optional PDF/document file attachment")
    version = models.CharField(max_length=20, default='1.0', help_text="Document version (e.g., '1.0', '2.0')")
    
    is_active = models.BooleanField(default=True, help_text="Whether document is currently active")
    is_required = models.BooleanField(default=False, help_text="Whether acceptance is mandatory")
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_distributor_documents')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    effective_from = models.DateTimeField(default=timezone.now, help_text="When document becomes effective")
    effective_until = models.DateTimeField(null=True, blank=True, help_text="When document expires (optional)")
    
    class Meta:
        db_table = 'distributor_documents'
        verbose_name = 'Distributor Document'
        verbose_name_plural = 'Distributor Documents'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', 'document_type']),
            models.Index(fields=['effective_from', 'effective_until']),
        ]
    
    def __str__(self):
        return f"{self.title} (v{self.version})"


class DistributorDocumentAcceptance(models.Model):
    """
    Records of users accepting distributor documents with OTP verification
    Stores IP address, timestamp, user info snapshot, and timeline for legal compliance
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='distributor_document_acceptances')
    document = models.ForeignKey(DistributorDocument, on_delete=models.CASCADE, related_name='acceptances')
    
    accepted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.CharField(max_length=45, help_text="User's IP address at acceptance")
    user_agent = models.TextField(blank=True, null=True, help_text="Browser/user agent info")
    
    otp_verified = models.BooleanField(default=False, help_text="Whether OTP was verified")
    otp_identifier = models.CharField(max_length=255, blank=True, help_text="Email/mobile used for OTP")
    accepted_version = models.CharField(max_length=20, help_text="Document version at acceptance")
    
    timeline_data = models.JSONField(default=dict, blank=True, null=True, help_text="Additional metadata/timeline info")
    user_info_snapshot = models.JSONField(default=dict, blank=True, null=True, help_text="Snapshot of user info at acceptance")
    
    class Meta:
        db_table = 'distributor_document_acceptances'
        verbose_name = 'Distributor Document Acceptance'
        verbose_name_plural = 'Distributor Document Acceptances'
        ordering = ['-accepted_at']
        indexes = [
            models.Index(fields=['user', 'document']),
            models.Index(fields=['accepted_at']),
            models.Index(fields=['ip_address']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.document.title} (v{self.accepted_version})"


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


class AsaTerms(models.Model):
    """
    Master ASA (Sales Channel Associate) Terms table
    Only ONE active version can exist at a time
    """
    version = models.CharField(max_length=20, help_text="Version identifier (e.g., 'v1.0', 'v1.1')")
    title = models.CharField(max_length=200, help_text="Title of the ASA Terms")
    full_text = models.TextField(help_text="Full text content of the terms (HTML or Markdown supported)")
    effective_from = models.DateTimeField(default=timezone.now, help_text="When these terms become effective")
    is_active = models.BooleanField(default=True, help_text="Whether this version is currently active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'asa_terms'
        verbose_name = 'ASA Terms'
        verbose_name_plural = 'ASA Terms'
        ordering = ['-effective_from', '-created_at']
        indexes = [
            models.Index(fields=['is_active', 'effective_from']),
        ]
        constraints = [
            # Ensure only one active ASA terms version at a time
            models.UniqueConstraint(
                fields=['is_active'],
                condition=models.Q(is_active=True),
                name='unique_active_asa_terms'
            )
        ]
    
    def __str__(self):
        return f"{self.title} (v{self.version})"


class PaymentTerms(models.Model):
    """
    Master Payment Terms table
    Multiple versions can exist for audit purposes
    """
    version = models.CharField(max_length=20, help_text="Version identifier (e.g., 'v1.0', 'v1.1')")
    title = models.CharField(max_length=200, help_text="Title of the Payment Terms")
    full_text = models.TextField(help_text="Full text content of the terms (HTML or Markdown supported)")
    effective_from = models.DateTimeField(default=timezone.now, help_text="When these terms become effective")
    is_active = models.BooleanField(default=True, help_text="Whether this version is currently active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'payment_terms'
        verbose_name = 'Payment Terms'
        verbose_name_plural = 'Payment Terms'
        ordering = ['-effective_from', '-created_at']
        indexes = [
            models.Index(fields=['is_active', 'effective_from']),
        ]
    
    def __str__(self):
        return f"{self.title} (v{self.version})"


class UserAsaAcceptance(models.Model):
    """
    Records of users accepting ASA Terms with OTP verification
    User can accept an ASA version ONLY ONCE
    PDF is ALWAYS REQUIRED and generated on backend
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='asa_acceptances')
    terms_version = models.CharField(max_length=20, help_text="ASA Terms version that was accepted")
    
    accepted_at = models.DateTimeField(auto_now_add=True, help_text="Server timestamp in IST when accepted")
    ip_address = models.CharField(max_length=45, help_text="User's IP address at acceptance")
    user_agent = models.TextField(blank=True, null=True, help_text="Browser/user agent info")
    
    otp_verified = models.BooleanField(default=False, help_text="Whether OTP was verified (always True for valid acceptances)")
    otp_identifier = models.CharField(max_length=255, blank=True, help_text="Email/mobile used for OTP verification")
    
    agreement_pdf_url = models.FileField(
        upload_to='compliance/asa_agreements/',
        help_text="Generated agreement PDF (backend-generated only)"
    )
    pdf_hash = models.CharField(
        max_length=64,
        help_text="SHA256 hash of the PDF for integrity verification"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'user_asa_acceptances'
        verbose_name = 'User ASA Acceptance'
        verbose_name_plural = 'User ASA Acceptances'
        ordering = ['-accepted_at']
        indexes = [
            models.Index(fields=['user', 'terms_version']),
            models.Index(fields=['accepted_at']),
            models.Index(fields=['ip_address']),
        ]
        # User can accept an ASA version ONLY ONCE
        unique_together = [['user', 'terms_version']]
    
    def __str__(self):
        return f"{self.user.username} - ASA Terms v{self.terms_version} ({self.accepted_at})"


class UserPaymentAcceptance(models.Model):
    """
    Records of users accepting Payment Terms
    OTP is required for FIRST acceptance or high-risk transactions
    PDF is OPTIONAL but recommended for first acceptance
    User can accept multiple times
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_acceptances')
    payment_terms_version = models.CharField(max_length=20, help_text="Payment Terms version that was accepted")
    
    accepted_at = models.DateTimeField(auto_now_add=True, help_text="Server timestamp in IST when accepted")
    ip_address = models.CharField(max_length=45, help_text="User's IP address at acceptance")
    user_agent = models.TextField(blank=True, null=True, help_text="Browser/user agent info")
    
    otp_verified = models.BooleanField(default=False, help_text="Whether OTP was verified")
    otp_identifier = models.CharField(max_length=255, blank=True, help_text="Email/mobile used for OTP verification")
    
    receipt_pdf_url = models.FileField(
        upload_to='compliance/payment_receipts/',
        null=True,
        blank=True,
        help_text="Optional receipt/consent PDF (backend-generated only)"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'user_payment_acceptances'
        verbose_name = 'User Payment Acceptance'
        verbose_name_plural = 'User Payment Acceptances'
        ordering = ['-accepted_at']
        indexes = [
            models.Index(fields=['user', 'payment_terms_version']),
            models.Index(fields=['accepted_at']),
            models.Index(fields=['ip_address']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - Payment Terms v{self.payment_terms_version} ({self.accepted_at})"

