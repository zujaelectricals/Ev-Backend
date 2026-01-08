from django.db import models
import random
import string


def default_vehicle_color():
    """Return default vehicle color array"""
    return ["white"]


class Vehicle(models.Model):
    """
    EV Vehicle inventory model
    """
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('out_of_stock', 'Out of Stock'),
        ('discontinued', 'Discontinued'),
    ]
    
    name = models.CharField(max_length=200)
    model_code = models.CharField(max_length=100, unique=True, blank=True)
    # Vehicle colors - Array of available colors (e.g., ["white", "red", "blue"])
    # Default color is white
    vehicle_color = models.JSONField(
        default=default_vehicle_color,
        blank=True,
        null=False,  # Don't allow NULL, use default list as default
        help_text='List of available vehicle colors (default: ["white"])'
    )
    battery_variant = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    
    # Additional vehicle details
    description = models.TextField(blank=True)
    
    # Features - List of feature names (e.g., ["USB Charging Port", "Parking Mode", "Reverse Gear"])
    # Optional field - can be empty list or omitted entirely
    # No limit on number of features - add as many as needed
    features = models.JSONField(
        default=list,
        blank=True,
        null=False,  # Don't allow NULL, use empty list as default
        help_text='List of vehicle features (optional, unlimited items)'
    )
    
    # Specifications - Dictionary of specification key-value pairs
    # e.g., {"Battery": "60V × 50AH", "Motor Power": "48V/60V/72V 1000W", "Max Speed": "25 km/h"}
    # Optional field - can be empty dict or omitted entirely
    # No limit on number of specifications - add any key-value pairs as needed
    specifications = models.JSONField(
        default=dict,
        blank=True,
        null=False,  # Don't allow NULL, use empty dict as default
        help_text='Dictionary of vehicle specifications - any key-value pairs (optional, unlimited items)'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'vehicles'
        verbose_name = 'Vehicle'
        verbose_name_plural = 'Vehicles'
        ordering = ['-created_at']
    
    def generate_model_code(self):
        """Generate unique model code in format EV-XXXXXX"""
        max_attempts = 100
        for _ in range(max_attempts):
            # Generate 6 random alphanumeric characters (uppercase letters and digits)
            random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            code = f"EV-{random_chars}"
            
            # Check if code already exists (excluding current instance if updating)
            query = Vehicle.objects.filter(model_code=code)
            if self.pk:
                query = query.exclude(pk=self.pk)
            
            if not query.exists():
                return code
        
        # Fallback if all attempts fail (highly unlikely)
        raise ValueError("Could not generate unique model code after multiple attempts")
    
    def save(self, *args, **kwargs):
        """Override save to auto-generate model_code for new vehicles"""
        # Only generate model_code if it's not set and this is a new instance
        if not self.model_code and not self.pk:
            self.model_code = self.generate_model_code()
        super().save(*args, **kwargs)
    
    def __str__(self):
        # Handle vehicle_color as array - join colors or show first color
        if isinstance(self.vehicle_color, list) and len(self.vehicle_color) > 0:
            colors_display = ", ".join(self.vehicle_color) if len(self.vehicle_color) > 1 else self.vehicle_color[0]
        else:
            colors_display = "white"  # Fallback to default
        return f"{self.name} - {self.model_code} ({colors_display})"


class VehicleImage(models.Model):
    """
    Vehicle images - allows multiple images per vehicle
    Can also be uploaded independently (vehicle=None) and linked later
    """
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, null=True, blank=True, related_name='images')
    image = models.ImageField(upload_to='vehicles/images/')
    is_primary = models.BooleanField(default=False, help_text='Set as primary/featured image')
    alt_text = models.CharField(max_length=200, blank=True, help_text='Alternative text for image')
    order = models.IntegerField(default=0, help_text='Display order')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'vehicle_images'
        verbose_name = 'Vehicle Image'
        verbose_name_plural = 'Vehicle Images'
        ordering = ['order', '-is_primary', 'created_at']
    
    def __str__(self):
        if self.vehicle:
            return f"Image for {self.vehicle.name} - {self.image.name}"
        return f"Unlinked Image - {self.image.name}"
    
    def save(self, *args, **kwargs):
        # Ensure only one primary image per vehicle (if vehicle exists)
        if self.is_primary and self.vehicle:
            VehicleImage.objects.filter(vehicle=self.vehicle, is_primary=True).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

