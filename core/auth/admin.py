from django.contrib import admin
from .models import OTP


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ('identifier', 'otp_type', 'is_used', 'created_at', 'expires_at')
    list_filter = ('otp_type', 'is_used', 'created_at')
    search_fields = ('identifier', 'otp_code')
    readonly_fields = ('created_at', 'expires_at')

