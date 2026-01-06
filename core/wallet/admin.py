from django.contrib import admin
from .models import Wallet, WalletTransaction


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'total_earned', 'total_withdrawn', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'user__email', 'user__mobile')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'transaction_type', 'amount', 'balance_after', 'created_at')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('user__username', 'description', 'reference_id')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'

