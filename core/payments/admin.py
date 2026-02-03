from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import Payment, WebhookEvent


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'payment_id', 'user', 'amount_display', 'status_display', 'refund_info', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at', 'updated_at')
    search_fields = ('order_id', 'payment_id', 'user__username', 'user__email')
    readonly_fields = ('order_id', 'payment_id', 'created_at', 'updated_at', 'raw_payload', 'refund_details_display')
    date_hierarchy = 'created_at'
    list_per_page = 50
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('user', 'order_id', 'payment_id', 'amount', 'status')
        }),
        ('Entity Linking', {
            'fields': ('content_type', 'object_id')
        }),
        ('Refund Information', {
            'fields': ('refund_details_display',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('raw_payload', 'created_at', 'updated_at')
        }),
    )
    
    def amount_display(self, obj):
        """Display amount in rupees"""
        return f"₹{obj.amount_in_rupees:.2f}"
    amount_display.short_description = 'Amount'
    amount_display.admin_order_field = 'amount'
    
    def status_display(self, obj):
        """Display status with color coding"""
        colors = {
            'CREATED': '#808080',  # Gray
            'SUCCESS': '#28a745',  # Green
            'FAILED': '#dc3545',   # Red
            'REFUNDED': '#ffc107', # Yellow/Orange
        }
        color = colors.get(obj.status, '#000000')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'
    
    def refund_info(self, obj):
        """Display refund information if status is REFUNDED"""
        if obj.status == 'REFUNDED' and obj.raw_payload:
            try:
                refund_data = obj.raw_payload.get('payload', {}).get('refund', {})
                if refund_data:
                    refund_entity = refund_data.get('entity', refund_data)
                    refund_id = refund_entity.get('id', 'N/A')
                    refund_amount = refund_entity.get('amount', 0)
                    refund_status = refund_entity.get('status', 'N/A')
                    
                    # Format amount separately to avoid SafeString formatting issues
                    amount_str = f"{refund_amount / 100:.2f}"
                    
                    return format_html(
                        '<div style="font-size: 11px;">'
                        '<strong>Refund ID:</strong> {}<br>'
                        '<strong>Amount:</strong> ₹{}<br>'
                        '<strong>Status:</strong> {}'
                        '</div>',
                        refund_id,
                        amount_str,
                        refund_status
                    )
            except (KeyError, AttributeError, TypeError):
                pass
        return '-'
    refund_info.short_description = 'Refund Details'
    
    def refund_details_display(self, obj):
        """Display detailed refund information in the detail view"""
        if obj.status == 'REFUNDED' and obj.raw_payload:
            try:
                refund_data = obj.raw_payload.get('payload', {}).get('refund', {})
                if refund_data:
                    refund_entity = refund_data.get('entity', refund_data)
                    refund_id = refund_entity.get('id', 'N/A')
                    refund_amount = refund_entity.get('amount', 0)
                    refund_status = refund_entity.get('status', 'N/A')
                    refund_created = refund_entity.get('created_at', 'N/A')
                    refund_notes = refund_entity.get('notes', {})
                    
                    html = f'''
                    <div style="background: #f8f9fa; padding: 15px; border-radius: 5px;">
                        <h3>Refund Information</h3>
                        <table style="width: 100%;">
                            <tr><td><strong>Refund ID:</strong></td><td>{refund_id}</td></tr>
                            <tr><td><strong>Refund Amount:</strong></td><td>₹{refund_amount / 100:.2f}</td></tr>
                            <tr><td><strong>Refund Status:</strong></td><td>{refund_status}</td></tr>
                            <tr><td><strong>Created At:</strong></td><td>{refund_created}</td></tr>
                    '''
                    
                    if refund_notes:
                        html += '<tr><td><strong>Notes:</strong></td><td><ul>'
                        for key, value in refund_notes.items():
                            html += f'<li><strong>{key}:</strong> {value}</li>'
                        html += '</ul></td></tr>'
                    
                    html += '</table></div>'
                    return mark_safe(html)
            except (KeyError, AttributeError, TypeError) as e:
                return f'Error parsing refund data: {str(e)}'
        return 'No refund information available'
    refund_details_display.short_description = 'Refund Details'


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'event_type', 'processed_display', 'processed_at', 'created_at')
    list_filter = ('event_type', 'processed', 'created_at', 'processed_at')
    search_fields = ('event_id', 'event_type', 'error_message')
    readonly_fields = ('event_id', 'event_type', 'payload_display', 'processed', 'processed_at', 'error_message', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    list_per_page = 50
    
    fieldsets = (
        ('Event Information', {
            'fields': ('event_id', 'event_type', 'processed', 'processed_at')
        }),
        ('Payload', {
            'fields': ('payload_display',),
            'classes': ('collapse',)
        }),
        ('Error Information', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def processed_display(self, obj):
        """Display processed status with color coding"""
        if obj.processed:
            color = '#28a745'  # Green
            icon = '✅'
        else:
            color = '#dc3545'  # Red
            icon = '❌'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {}</span>',
            color,
            icon,
            'Processed' if obj.processed else 'Pending'
        )
    processed_display.short_description = 'Status'
    processed_display.admin_order_field = 'processed'
    
    def payload_display(self, obj):
        """Display formatted JSON payload"""
        import json
        try:
            formatted_json = json.dumps(obj.payload, indent=2, ensure_ascii=False)
            return format_html(
                '<pre style="background: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto;">{}</pre>',
                formatted_json
            )
        except Exception as e:
            return f'Error formatting payload: {str(e)}'
    payload_display.short_description = 'Payload (JSON)'
    
    def has_add_permission(self, request):
        """Prevent manual creation of webhook events"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Allow deletion for cleanup purposes"""
        return request.user.is_superuser

