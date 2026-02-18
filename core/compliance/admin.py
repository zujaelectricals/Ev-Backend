from django.contrib import admin
from .models import (
    ComplianceDocument, TDSRecord,
    DistributorDocument, DistributorDocumentAcceptance,
    AsaTerms, PaymentTerms, UserAsaAcceptance, UserPaymentAcceptance
)


@admin.register(ComplianceDocument)
class ComplianceDocumentAdmin(admin.ModelAdmin):
    list_display = ('user', 'document_type', 'title', 'is_verified', 'uploaded_at')
    list_filter = ('document_type', 'is_verified', 'uploaded_at')
    search_fields = ('user__username', 'title')
    readonly_fields = ('uploaded_at', 'verified_at')


@admin.register(TDSRecord)
class TDSRecordAdmin(admin.ModelAdmin):
    list_display = ('user', 'financial_year', 'total_payout', 'tds_deducted', 'created_at')
    list_filter = ('financial_year', 'created_at')
    search_fields = ('user__username', 'certificate_number')
    readonly_fields = ('created_at',)


@admin.register(DistributorDocument)
class DistributorDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'document_type', 'version', 'is_active', 'is_required', 'created_by', 'created_at', 'effective_from')
    list_filter = ('document_type', 'is_active', 'is_required', 'created_at', 'effective_from')
    search_fields = ('title', 'content', 'created_by__username')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Document Information', {
            'fields': ('title', 'document_type', 'content', 'file', 'version')
        }),
        ('Status', {
            'fields': ('is_active', 'is_required')
        }),
        ('Effective Dates', {
            'fields': ('effective_from', 'effective_until')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )


@admin.register(DistributorDocumentAcceptance)
class DistributorDocumentAcceptanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'document', 'accepted_version', 'accepted_at', 'ip_address', 'otp_verified')
    list_filter = ('otp_verified', 'accepted_at', 'document__document_type')
    search_fields = ('user__username', 'user__email', 'document__title', 'ip_address')
    readonly_fields = (
        'user', 'document', 'accepted_at', 'ip_address', 'user_agent',
        'otp_verified', 'otp_identifier', 'accepted_version',
        'timeline_data', 'user_info_snapshot'
    )
    fieldsets = (
        ('Acceptance Information', {
            'fields': ('user', 'document', 'accepted_version', 'accepted_at')
        }),
        ('Verification', {
            'fields': ('otp_verified', 'otp_identifier')
        }),
        ('Network Information', {
            'fields': ('ip_address', 'user_agent')
        }),
        ('Audit Data', {
            'fields': ('user_info_snapshot', 'timeline_data'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent manual creation - acceptances must be created via API"""
        # Allow superusers to bypass this restriction
        return request.user.is_superuser
    
    def has_change_permission(self, request, obj=None):
        """Prevent editing - acceptances are immutable audit records"""
        # Allow superusers to bypass this restriction
        return request.user.is_superuser


@admin.register(AsaTerms)
class AsaTermsAdmin(admin.ModelAdmin):
    list_display = ('title', 'version', 'is_active', 'effective_from', 'created_at')
    list_filter = ('is_active', 'effective_from', 'created_at')
    search_fields = ('title', 'version', 'full_text')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Terms Information', {
            'fields': ('title', 'version', 'full_text')
        }),
        ('Status', {
            'fields': ('is_active', 'effective_from')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        """Make version read-only if editing existing terms"""
        readonly = list(self.readonly_fields)
        if obj:  # Editing existing object
            readonly.append('version')
        return readonly


@admin.register(PaymentTerms)
class PaymentTermsAdmin(admin.ModelAdmin):
    list_display = ('title', 'version', 'is_active', 'effective_from', 'created_at')
    list_filter = ('is_active', 'effective_from', 'created_at')
    search_fields = ('title', 'version', 'full_text')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Terms Information', {
            'fields': ('title', 'version', 'full_text')
        }),
        ('Status', {
            'fields': ('is_active', 'effective_from')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(UserAsaAcceptance)
class UserAsaAcceptanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'terms_version', 'accepted_at', 'ip_address', 'otp_verified', 'pdf_hash')
    list_filter = ('otp_verified', 'accepted_at', 'terms_version')
    search_fields = ('user__username', 'user__email', 'terms_version', 'ip_address', 'pdf_hash')
    readonly_fields = (
        'user', 'terms_version', 'accepted_at', 'ip_address', 'user_agent',
        'otp_verified', 'otp_identifier', 'agreement_pdf_url', 'pdf_hash',
        'created_at'
    )
    fieldsets = (
        ('Acceptance Information', {
            'fields': ('user', 'terms_version', 'accepted_at')
        }),
        ('Verification', {
            'fields': ('otp_verified', 'otp_identifier')
        }),
        ('Network Information', {
            'fields': ('ip_address', 'user_agent')
        }),
        ('Document', {
            'fields': ('agreement_pdf_url', 'pdf_hash')
        }),
        ('Metadata', {
            'fields': ('created_at',)
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent manual creation - acceptances must be created via API"""
        return request.user.is_superuser
    
    def has_change_permission(self, request, obj=None):
        """Prevent editing - acceptances are immutable audit records"""
        return request.user.is_superuser


@admin.register(UserPaymentAcceptance)
class UserPaymentAcceptanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'payment_terms_version', 'accepted_at', 'ip_address', 'otp_verified', 'has_receipt')
    list_filter = ('otp_verified', 'accepted_at', 'payment_terms_version')
    search_fields = ('user__username', 'user__email', 'payment_terms_version', 'ip_address')
    readonly_fields = (
        'user', 'payment_terms_version', 'accepted_at', 'ip_address', 'user_agent',
        'otp_verified', 'otp_identifier', 'receipt_pdf_url', 'created_at'
    )
    fieldsets = (
        ('Acceptance Information', {
            'fields': ('user', 'payment_terms_version', 'accepted_at')
        }),
        ('Verification', {
            'fields': ('otp_verified', 'otp_identifier')
        }),
        ('Network Information', {
            'fields': ('ip_address', 'user_agent')
        }),
        ('Document', {
            'fields': ('receipt_pdf_url',)
        }),
        ('Metadata', {
            'fields': ('created_at',)
        }),
    )
    
    def has_receipt(self, obj):
        """Check if receipt PDF exists"""
        return bool(obj.receipt_pdf_url)
    has_receipt.boolean = True
    has_receipt.short_description = 'Has Receipt PDF'
    
    def has_add_permission(self, request):
        """Prevent manual creation - acceptances must be created via API"""
        return request.user.is_superuser
    
    def has_change_permission(self, request, obj=None):
        """Prevent editing - acceptances are immutable audit records"""
        return request.user.is_superuser

