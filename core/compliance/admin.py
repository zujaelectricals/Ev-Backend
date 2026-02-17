from django.contrib import admin
from .models import (
    ComplianceDocument, TDSRecord,
    DistributorDocument, DistributorDocumentAcceptance
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

