from django.contrib import admin
from .models import Payout, PayoutTransaction


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ('user', 'requested_amount', 'tds_amount', 'net_amount', 'status', 
                   'emi_auto_filled', 'emi_amount', 'created_at')
    list_filter = ('status', 'emi_auto_filled', 'created_at')
    search_fields = ('user__username', 'transaction_id', 'account_number')
    readonly_fields = ('created_at', 'processed_at', 'completed_at')
    date_hierarchy = 'created_at'


@admin.register(PayoutTransaction)
class PayoutTransactionAdmin(admin.ModelAdmin):
    list_display = ('payout', 'user', 'amount', 'transaction_type', 'created_at')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('user__username', 'payout__id')
    readonly_fields = ('created_at',)

