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
    list_display = ('user', 'full_name', 'relationship', 'mobile', 'created_at')
    list_filter = ('relationship', 'created_at')
    search_fields = ('user__username', 'full_name', 'mobile', 'email')

