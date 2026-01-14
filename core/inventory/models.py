from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
import random
import string
import re


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
    # Battery variants - Array of available battery configurations (e.g., ["40kWh", "60kWh"])
    # Default is empty list
    battery_variant = models.JSONField(
        default=list,
        blank=True,
        null=False,  # Don't allow NULL, use empty list as default
        help_text='List of battery variants (e.g., ["40kWh", "60kWh"])'
    )
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
    
    @staticmethod
    def _get_color_code(color):
        """Convert color name to 3-letter uppercase code"""
        color = color.lower().strip()
        # Common color mappings
        color_map = {
            'white': 'WHT',
            'red': 'RED',
            'blue': 'BLU',
            'black': 'BLK',
            'gray': 'GRY',
            'grey': 'GRY',
            'green': 'GRN',
            'yellow': 'YLW',
            'orange': 'ORG',
            'purple': 'PUR',
            'pink': 'PNK',
            'silver': 'SLV',
            'gold': 'GLD',
            'brown': 'BRN',
        }
        # Return mapped code or first 3 uppercase letters
        if color in color_map:
            return color_map[color]
        # Fallback: use first 3 letters, uppercase, pad if needed
        code = color[:3].upper()
        if len(code) < 3:
            code = code.ljust(3, 'X')
        return code
    
    @staticmethod
    def _get_battery_code(battery):
        """Convert battery variant to code (e.g., '40kWh' -> '40K')"""
        battery = str(battery).strip()
        # Extract numbers from battery string
        numbers = re.findall(r'\d+', battery)
        if numbers:
            # Take first number and add 'K'
            return f"{numbers[0]}K"
        # Fallback: use first 3 characters, uppercase
        code = battery[:3].upper()
        if len(code) < 3:
            code = code.ljust(3, 'X')
        return code
    
    def generate_model_code(self, color=None, battery_variant=None):
        """Generate unique model code in format EV-{COLOR}-{BATTERY}-{RANDOM}"""
        # Get color and battery from instance if not provided
        if color is None:
            if isinstance(self.vehicle_color, list) and len(self.vehicle_color) > 0:
                color = self.vehicle_color[0]
            else:
                color = "white"
        
        if battery_variant is None:
            if isinstance(self.battery_variant, list) and len(self.battery_variant) > 0:
                battery_variant = self.battery_variant[0]
            else:
                battery_variant = "40kWh"  # Default fallback
        
        color_code = self._get_color_code(color)
        battery_code = self._get_battery_code(battery_variant)
        
        max_attempts = 100
        for _ in range(max_attempts):
            # Generate 6 random alphanumeric characters (uppercase letters and digits)
            random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            code = f"EV-{color_code}-{battery_code}-{random_chars}"
            
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
            # Get first color and battery for model code generation
            color = None
            battery = None
            if isinstance(self.vehicle_color, list) and len(self.vehicle_color) > 0:
                color = self.vehicle_color[0]
            if isinstance(self.battery_variant, list) and len(self.battery_variant) > 0:
                battery = self.battery_variant[0]
            self.model_code = self.generate_model_code(color=color, battery_variant=battery)
        super().save(*args, **kwargs)
    
    def __str__(self):
        # Handle vehicle_color as array - show first color
        if isinstance(self.vehicle_color, list) and len(self.vehicle_color) > 0:
            colors_display = self.vehicle_color[0]
        else:
            colors_display = "white"  # Fallback to default
        
        # Handle battery_variant as array - show first battery
        if isinstance(self.battery_variant, list) and len(self.battery_variant) > 0:
            battery_display = self.battery_variant[0]
        else:
            battery_display = "N/A"
        
        return f"{self.name} - {self.model_code} ({colors_display}, {battery_display})"


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


class VehicleStock(models.Model):
    """
    Vehicle stock inventory tracking
    Tracks total and available quantity for each vehicle
    """
    vehicle = models.OneToOneField(
        Vehicle, 
        on_delete=models.CASCADE, 
        related_name='stock',
        unique=True
    )
    total_quantity = models.IntegerField(default=0, help_text='Total quantity of this vehicle')
    available_quantity = models.IntegerField(default=0, help_text='Available quantity (not reserved)')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'vehicle_stock'
        verbose_name = 'Vehicle Stock'
        verbose_name_plural = 'Vehicle Stocks'
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"{self.vehicle.name} - Available: {self.available_quantity}/{self.total_quantity}"
    
    def reserve(self, quantity=1):
        """
        Reserve quantity from available stock
        Returns True if successful, False if insufficient stock
        """
        if self.available_quantity < quantity:
            return False
        
        self.available_quantity -= quantity
        self.save(update_fields=['available_quantity', 'updated_at'])
        return True
    
    def release(self, quantity=1):
        """
        Release quantity back to available stock
        """
        if self.available_quantity + quantity > self.total_quantity:
            # Don't exceed total_quantity
            self.available_quantity = self.total_quantity
        else:
            self.available_quantity += quantity
        
        self.save(update_fields=['available_quantity', 'updated_at'])
    
    def complete(self, quantity=1):
        """
        Mark reservation as completed (quantity already reserved, no change needed)
        This is called when payment is confirmed - stock remains reserved
        """
        # No change to available_quantity as it's already reserved
        # This method exists for consistency with the flow
        pass


class StockReservation(models.Model):
    """
    Stock reservation for bookings
    Tracks reserved stock that will be released if payment is not completed
    """
    STATUS_CHOICES = [
        ('reserved', 'Reserved'),
        ('released', 'Released'),
        ('completed', 'Completed'),
    ]
    
    booking = models.OneToOneField(
        'booking.Booking',
        on_delete=models.CASCADE,
        related_name='stock_reservation',
        unique=True
    )
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name='reservations'
    )
    vehicle_stock = models.ForeignKey(
        VehicleStock,
        on_delete=models.CASCADE,
        related_name='reservations'
    )
    quantity = models.IntegerField(default=1, help_text='Quantity reserved')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='reserved',
        help_text='Reservation status'
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When reservation expires (null = never expires)'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'stock_reservations'
        verbose_name = 'Stock Reservation'
        verbose_name_plural = 'Stock Reservations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'expires_at']),
        ]
    
    def __str__(self):
        return f"Reservation for {self.booking.booking_number} - {self.status}"
    
    def is_expired(self):
        """Check if reservation has expired"""
        if self.expires_at is None:
            return False  # Never expires
        return timezone.now() > self.expires_at
    
    def release(self):
        """
        Release the reserved stock back to available inventory
        """
        if self.status == 'released':
            return  # Already released
        
        self.vehicle_stock.release(quantity=self.quantity)
        self.status = 'released'
        self.save(update_fields=['status', 'updated_at'])
    
    def complete(self):
        """
        Mark reservation as completed (payment confirmed)
        Stock remains reserved and is not released
        """
        if self.status == 'completed':
            return  # Already completed
        
        self.status = 'completed'
        self.save(update_fields=['status', 'updated_at'])

