"""
Celery tasks for inventory management
"""
from celery import shared_task
from django.utils import timezone
from .models import StockReservation
from .utils import release_reservation
import logging

logger = logging.getLogger(__name__)


@shared_task
def release_expired_reservations():
    """
    Periodic task to automatically release expired stock reservations
    Runs every 10 minutes (configured in Celery beat schedule)
    
    Finds all reservations where:
    - status = 'reserved'
    - expires_at IS NOT NULL
    - expires_at < current_time
    
    Releases the stock and updates reservation status to 'released'
    """
    try:
        # Find expired reservations
        expired_reservations = StockReservation.objects.filter(
            status='reserved',
            expires_at__isnull=False,
            expires_at__lt=timezone.now()
        )
        
        count = 0
        for reservation in expired_reservations:
            try:
                # Release the reservation
                release_reservation(reservation)
                
                # Optionally update booking status to 'expired'
                booking = reservation.booking
                if booking.status == 'pending':
                    booking.status = 'expired'
                    booking.save(update_fields=['status'])
                
                count += 1
                logger.info(
                    f"Released expired reservation for booking {booking.booking_number} "
                    f"(expired at {reservation.expires_at})"
                )
            except Exception as e:
                logger.error(
                    f"Error releasing reservation {reservation.id} for booking {booking.booking_number}: {e}"
                )
        
        if count > 0:
            logger.info(f"Released {count} expired reservation(s)")
        
        return {'released_count': count}
        
    except Exception as e:
        logger.error(f"Error in release_expired_reservations task: {e}")
        return {'error': str(e)}

