"""
Utility functions for inventory reservation management
"""
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
from .models import VehicleStock, StockReservation, Vehicle


def get_booking_reservation_timeout_hours():
    """
    Get booking reservation timeout in hours from database settings.
    Falls back to environment variable if database setting is not available.
    
    Returns:
        int or None: Timeout in hours, or None if never expires
    """
    try:
        from core.settings.models import PlatformSettings
        platform_settings = PlatformSettings.get_settings()
        timeout_minutes = platform_settings.booking_reservation_timeout_minutes
        
        if timeout_minutes is None:
            return None  # Never expires
        
        # Convert minutes to hours
        return timeout_minutes / 60.0
    except Exception:
        # Fallback to environment variable if database is not available
        return getattr(settings, 'BOOKING_RESERVATION_TIMEOUT_HOURS', None)


def get_or_create_vehicle_stock(vehicle):
    """
    Get or create VehicleStock for a vehicle
    If stock doesn't exist, creates with default values
    """
    stock, created = VehicleStock.objects.get_or_create(
        vehicle=vehicle,
        defaults={
            'total_quantity': 0,
            'available_quantity': 0,
        }
    )
    return stock


def create_reservation(booking, vehicle, quantity=1):
    """
    Create a stock reservation for a booking
    
    Args:
        booking: Booking instance
        vehicle: Vehicle instance
        quantity: Quantity to reserve (default: 1)
    
    Returns:
        StockReservation instance
    
    Raises:
        ValueError: If insufficient stock available
    """
    # Get or create vehicle stock
    vehicle_stock = get_or_create_vehicle_stock(vehicle)
    
    # Check if sufficient stock is available
    if vehicle_stock.available_quantity < quantity:
        raise ValueError(f"Insufficient stock. Available: {vehicle_stock.available_quantity}, Required: {quantity}")
    
    # Calculate expires_at based on settings (from database, fallback to env var)
    expires_at = None
    timeout_hours = get_booking_reservation_timeout_hours()
    if timeout_hours is not None:
        expires_at = timezone.now() + timedelta(hours=timeout_hours)
    
    # Reserve stock
    if not vehicle_stock.reserve(quantity=quantity):
        raise ValueError(f"Failed to reserve stock. Available: {vehicle_stock.available_quantity}, Required: {quantity}")
    
    # Create reservation
    reservation = StockReservation.objects.create(
        booking=booking,
        vehicle=vehicle,
        vehicle_stock=vehicle_stock,
        quantity=quantity,
        status='reserved',
        expires_at=expires_at
    )
    
    return reservation


def release_reservation(reservation):
    """
    Release a stock reservation and restore available quantity
    
    Args:
        reservation: StockReservation instance
    """
    if reservation.status == 'released':
        return  # Already released
    
    reservation.release()


def complete_reservation(reservation):
    """
    Mark a reservation as completed (payment confirmed)
    Stock remains reserved and is not released
    
    Args:
        reservation: StockReservation instance
    """
    if reservation.status == 'completed':
        return  # Already completed
    
    reservation.complete()

