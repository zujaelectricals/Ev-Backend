from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model with email/mobile as username
    """
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('staff', 'Staff'),
        ('user', 'User'),
    ]
    
    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ]
    
    email = models.EmailField(unique=True, null=True, blank=True)
    mobile = models.CharField(max_length=15, unique=True, null=True, blank=True)
    username = models.CharField(max_length=150, unique=True)
    
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    
    # Additional user details
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    
    # Address fields
    address_line1 = models.TextField(blank=True)
    address_line2 = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    country = models.CharField(max_length=100, default='India')
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')
    is_distributor = models.BooleanField(default=False)
    is_active_buyer = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)
    
    # Referral fields
    referral_code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    referred_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='referrals')
    
    objects = UserManager()
    
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = []
    
    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
    
    def __str__(self):
        return self.username or self.email or self.mobile
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
    
    def update_active_buyer_status(self):
        """Update Active Buyer status based on total paid amount"""
        from core.booking.models import Booking
        total_paid = Booking.objects.filter(
            user=self,
            status__in=['confirmed', 'completed']
        ).aggregate(total=models.Sum('total_paid'))['total'] or 0
        
        was_active = self.is_active_buyer
        self.is_active_buyer = total_paid >= 5000  # ACTIVE_BUYER_THRESHOLD
        
        if not was_active and self.is_active_buyer:
            # User just became Active Buyer - trigger any necessary actions
            pass
        
        self.save(update_fields=['is_active_buyer'])
        return self.is_active_buyer


class KYC(models.Model):
    """
    KYC (Know Your Customer) information
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='kyc')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Personal Details
    pan_number = models.CharField(max_length=10, unique=True, null=True, blank=True)
    aadhaar_number = models.CharField(max_length=12, unique=True, null=True, blank=True)
    
    # Address
    address_line1 = models.TextField()
    address_line2 = models.TextField(blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=10)
    country = models.CharField(max_length=100, default='India')
    
    # Documents
    pan_document = models.ImageField(upload_to='kyc/pan/', null=True, blank=True)
    aadhaar_front = models.ImageField(upload_to='kyc/aadhaar/', null=True, blank=True)
    aadhaar_back = models.ImageField(upload_to='kyc/aadhaar/', null=True, blank=True)
    
    # Bank Details
    bank_name = models.CharField(max_length=200, null=True, blank=True)
    account_number = models.CharField(max_length=50, null=True, blank=True)
    ifsc_code = models.CharField(max_length=11, null=True, blank=True)
    account_holder_name = models.CharField(max_length=200, null=True, blank=True)
    
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='kyc_reviews')
    rejection_reason = models.TextField(blank=True)
    
    class Meta:
        db_table = 'kyc'
        verbose_name = 'KYC'
        verbose_name_plural = 'KYCs'
    
    def __str__(self):
        return f"KYC - {self.user.username}"


class Nominee(models.Model):
    """
    Nominee information for user
    """
    RELATIONSHIP_CHOICES = [
        ('spouse', 'Spouse'),
        ('son', 'Son'),
        ('daughter', 'Daughter'),
        ('father', 'Father'),
        ('mother', 'Mother'),
        ('brother', 'Brother'),
        ('sister', 'Sister'),
        ('other', 'Other'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='nominee')
    
    full_name = models.CharField(max_length=200)
    relationship = models.CharField(max_length=20, choices=RELATIONSHIP_CHOICES)
    date_of_birth = models.DateField()
    mobile = models.CharField(max_length=15)
    email = models.EmailField(blank=True)
    
    # Address
    address_line1 = models.TextField()
    address_line2 = models.TextField(blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=10)
    
    # Documents
    id_proof_type = models.CharField(max_length=50, null=True, blank=True)
    id_proof_number = models.CharField(max_length=50, null=True, blank=True)
    id_proof_document = models.ImageField(upload_to='nominee/id_proof/', null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'nominees'
        verbose_name = 'Nominee'
        verbose_name_plural = 'Nominees'
    
    def __str__(self):
        return f"Nominee - {self.full_name} ({self.user.username})"

