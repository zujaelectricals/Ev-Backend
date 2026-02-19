from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from .models import User, KYC, Nominee, DistributorApplication


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        'username', 'full_name', 'email', 'mobile', 'role',
        'referred_by_value', 'is_distributor', 'is_active_buyer', 'is_staff', 'date_joined'
    )
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

    @admin.display(description='Full name')
    def full_name(self, obj):
        return obj.get_full_name()

    @admin.display(description='Referred by', ordering='referred_by__username')
    def referred_by_value(self, obj):
        return obj.referred_by or '-'


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


@admin.register(DistributorApplication)
class DistributorApplicationAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'company_name', 'submitted_at', 'reviewed_at', 'reviewed_by')
    list_filter = ('status', 'submitted_at', 'reviewed_at')
    search_fields = ('user__username', 'user__email', 'company_name', 'business_registration_number', 'tax_id')
    readonly_fields = ('submitted_at', 'reviewed_at')
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'status')
        }),
        ('Business Information', {
            'fields': ('company_name', 'business_registration_number', 'tax_id', 'years_in_business')
        }),
        ('Experience', {
            'fields': ('previous_distribution_experience', 'product_interest')
        }),
        ('References', {
            'fields': ('reference_name', 'reference_contact', 'reference_relationship')
        }),
        ('Documents', {
            'fields': ('business_license', 'tax_documents')
        }),
        ('Review Information', {
            'fields': ('submitted_at', 'reviewed_at', 'reviewed_by', 'rejection_reason')
        }),
    )
    
    actions = ['approve_selected', 'reject_selected']
    
    @admin.action(description='Approve selected distributor applications')
    def approve_selected(self, request, queryset):
        """Approve selected applications and set users as distributors"""
        approved_count = 0
        for application in queryset.filter(status='pending'):
            application.status = 'approved'
            application.reviewed_by = request.user
            application.reviewed_at = timezone.now()
            application.rejection_reason = ''
            application.save()
            
            # Set user as distributor
            user = application.user
            user.is_distributor = True
            user.save(update_fields=['is_distributor'])
            approved_count += 1
        
        self.message_user(request, f"{approved_count} distributor application(s) approved.")
    
    @admin.action(description='Reject selected distributor applications')
    def reject_selected(self, request, queryset):
        """Reject selected applications"""
        rejected_count = queryset.filter(status='pending').update(
            status='rejected',
            reviewed_by=request.user,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f"{rejected_count} distributor application(s) rejected.")

