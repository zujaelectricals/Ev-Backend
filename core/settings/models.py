from django.db import models
from django.utils import timezone
from core.users.models import User


class PlatformSettings(models.Model):
    """
    Singleton model for platform-wide settings.
    Only one instance should exist in the database.
    """
    booking_reservation_timeout_minutes = models.IntegerField(
        null=True,
        blank=True,
        help_text="Booking reservation timeout in minutes. Set to null for never expires. Default: 1440 (24 hours)"
    )
    
    # Binary Commission Settings
    direct_user_commission_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1000,
        help_text="Commission amount per direct user added before binary commission activation (default: ₹1000)"
    )
    binary_commission_activation_count = models.IntegerField(
        default=3,
        help_text="Number of direct users needed to activate binary commission (default: 3)"
    )
    binary_pair_commission_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=2000,
        help_text="Commission amount per binary pair after activation (default: ₹2000)"
    )
    binary_tds_threshold_pairs = models.IntegerField(
        default=5,
        help_text="Number of pairs after activation before extra deduction starts (default: 5)"
    )
    binary_commission_tds_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=20,
        help_text="TDS percentage on ALL binary commissions - direct user and pairs (default: 20%)"
    )
    binary_extra_deduction_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=20,
        help_text="Extra deduction percentage on binary pair commission for 6th+ pairs (default: 20%)"
    )
    binary_daily_pair_limit = models.IntegerField(
        default=10,
        help_text="Maximum binary pairs per day after activation (default: 10 pairs = ₹20,000)"
    )
    max_earnings_before_active_buyer = models.IntegerField(
        default=5,
        help_text="Maximum number of binary pairs non-Active Buyer distributors can earn commission for before becoming Active Buyer (default: 5 pairs). 6th+ pairs are blocked until user becomes Active Buyer."
    )
    binary_commission_initial_bonus = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Initial bonus amount credited to user's wallet and total_earnings when binary commission is activated (3 persons). TDS is deducted from this amount, but TDS is NOT deducted from booking balance."
    )
    binary_tree_default_placement_side = models.CharField(
        max_length=5,
        choices=[('left', 'Left'), ('right', 'Right')],
        default='left',
        help_text="Default placement side for binary tree (left or right). Controls which side chain is followed after first 2 users."
    )
    activation_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=5000,
        help_text="Minimum payment amount per booking required for seniors to earn commission. If payment is less than this amount, no commission is credited, but user is still counted in descendants calculation. On cancellation, this amount is withheld for future point redemption. (default: ₹5000)"
    )
    
    # Distributor Application Settings
    distributor_application_auto_approve = models.BooleanField(
        default=True,
        help_text="If True, distributor applications are automatically approved upon submission. If False, applications require admin/staff approval."
    )
    
    # Payout Settings
    payout_approval_needed = models.BooleanField(
        default=True,
        help_text="If True, payout requests require admin approval before processing. If False, payouts are automatically processed upon creation."
    )
    payout_tds_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="TDS percentage applied on payout withdrawals (default: 0, meaning no payout TDS)"
    )
    
    # Company Referral Code
    company_referral_code = models.CharField(
        max_length=20,
        default='COMPANY',
        help_text="Static referral code representing the company (used for first booking in the system). Default: 'COMPANY'"
    )
    
    # Company Contact Information (for receipts and documents)
    company_name = models.CharField(
        max_length=200,
        default='ZUJA ELECTRICAL INNOVATION (P) LTD',
        help_text="Company name for receipts and documents"
    )
    company_email = models.EmailField(
        default='inquire@dialight.mail',
        help_text="Company email for receipts and documents"
    )
    company_phone = models.CharField(
        max_length=20,
        default='+91 7356360777',
        help_text="Company phone number for receipts and documents"
    )
    company_address = models.TextField(
        default='Kuttiyadiyil, Arrattuvazhy, Alappuzha North, Ambalapuzha A, Alappuzha – 688007, Kerala, India',
        help_text="Company address for receipts and documents"
    )
    
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_settings',
        help_text="User who last updated these settings"
    )
    
    class Meta:
        db_table = 'platform_settings'
        verbose_name = 'Platform Settings'
        verbose_name_plural = 'Platform Settings'
    
    def __str__(self):
        timeout = f"{self.booking_reservation_timeout_minutes} minutes" if self.booking_reservation_timeout_minutes else "Never expires"
        return f"Platform Settings (Timeout: {timeout})"
    
    @classmethod
    def get_settings(cls):
        """
        Get or create the singleton settings instance.
        Returns the single PlatformSettings instance.
        """
        settings, created = cls.objects.get_or_create(
            pk=1,
            defaults={
                'booking_reservation_timeout_minutes': 1440,  # 24 hours in minutes
                'direct_user_commission_amount': 1000,
                'binary_commission_activation_count': 3,
                'binary_pair_commission_amount': 2000,
                'binary_tds_threshold_pairs': 5,
                'binary_commission_tds_percentage': 20,
                'binary_extra_deduction_percentage': 20,
                'binary_daily_pair_limit': 10,
                'max_earnings_before_active_buyer': 5,
                'binary_commission_initial_bonus': 0,
                'binary_tree_default_placement_side': 'left',
                'activation_amount': 5000,
                'distributor_application_auto_approve': True,
                'payout_approval_needed': True,
                'payout_tds_percentage': 0,
                'company_referral_code': 'COMPANY',
                'company_name': 'ZUJA ELECTRICAL INNOVATION (P) LTD',
                'company_email': 'zujaelectric@gmail.com',
                'company_phone': '+91 7356360777',
                'company_address': 'Kuttiyadiyil, Arrattuvazhy, Alappuzha North, Ambalapuzha A, Alappuzha – 688007, Kerala, India',
            }
        )
        return settings
    
    def save(self, *args, **kwargs):
        """
        Override save to ensure only one instance exists.
        Always save with pk=1 to maintain singleton pattern.
        """
        self.pk = 1
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        """
        Prevent deletion of the settings instance.
        """
        raise Exception("Cannot delete PlatformSettings. It is a singleton.")

