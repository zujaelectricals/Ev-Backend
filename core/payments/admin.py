from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'payment_id', 'user', 'amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('order_id', 'payment_id', 'user__username', 'user__email')
    readonly_fields = ('order_id', 'payment_id', 'created_at', 'updated_at', 'raw_payload')
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('user', 'order_id', 'payment_id', 'amount', 'status')
        }),
        ('Entity Linking', {
            'fields': ('content_type', 'object_id')
        }),
        ('Metadata', {
            'fields': ('raw_payload', 'created_at', 'updated_at')
        }),
    )

