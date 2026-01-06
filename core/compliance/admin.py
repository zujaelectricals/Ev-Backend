from django.contrib import admin
from .models import ComplianceDocument, TDSRecord


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

