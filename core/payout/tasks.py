from celery import shared_task
from .models import Payout
from .utils import auto_fill_emi_from_payout


@shared_task
def emi_autofill(user_id, amount):
    """
    Celery task for EMI auto-fill
    """
    from core.users.models import User
    
    try:
        user = User.objects.get(id=user_id)
        emi_used, remaining = auto_fill_emi_from_payout(user, amount)
        return {
            'emi_used': float(emi_used),
            'remaining': float(remaining)
        }
    except User.DoesNotExist:
        print(f"User {user_id} not found")
        return None
    except Exception as e:
        print(f"Error in emi_autofill task: {e}")
        return None

