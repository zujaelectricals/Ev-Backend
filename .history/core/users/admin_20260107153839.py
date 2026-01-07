from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, KYC, Nominee


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'mobile', 'role', 'is_distributor', 'is_active_buyer', 'is_staff', 'date_joined')
    list_filter = ('role', 'is_distributor', 'is_active_buyer', 'is_staff', 'is_superuser')
    search_fields = ('username', 'email', 'mobile', 'first_name', 'last_name')
    ordering = ('-date_joined',)
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'mobile')}),
        ('Permissions', {'fields': ('role', 'is_distributor', 'is_active_buyer', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Referral', {'fields': ('referral_code', 'referred_by')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )


@admin.register(KYC)
class KYCAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'pan_number', 'submitted_at', 'reviewed_at')
    list_filter = ('status', 'submitted_at')
    search_fields = ('user__username', 'user__email', 'pan_number', 'aadhaar_number')
    readonly_fields = ('submitted_at', 'reviewed_at')


@admin.register(Nominee)
class NomineeAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'relationship', 'mobile', 'kyc_status', 'kyc_submitted_at', 'created_at')
    list_filter = ('relationship', 'kyc_status', 'created_at')
    search_fields = ('user__username', 'full_name', 'mobile', 'email')
    readonly_fields = ('kyc_submitted_at', 'kyc_verified_at')

    actions = ['mark_kyc_verified', 'mark_kyc_rejected']

    @admin.action(description='Mark selected nominees as KYC Verified')
    def mark_kyc_verified(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(kyc_status='verified', kyc_verified_at=timezone.now(), kyc_verified_by=request.user)
        self.message_user(request, f"{updated} nominee(s) marked as verified.")

    @admin.action(description='Mark selected nominees as KYC Rejected')
    def mark_kyc_rejected(self, request, queryset):
        updated = queryset.update(kyc_status='rejected', kyc_verified_by=request.user)
        self.message_user(request, f"{updated} nominee(s) marked as rejected.")

