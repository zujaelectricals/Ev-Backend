from celery import shared_task
from .utils import add_wallet_balance


@shared_task
def wallet_update(user_id, amount, transaction_type, description='', reference_id=None, reference_type=''):
    """
    Celery task for wallet updates
    """
    from core.users.models import User
    
    try:
        user = User.objects.get(id=user_id)
        add_wallet_balance(
            user=user,
            amount=amount,
            transaction_type=transaction_type,
            description=description,
            reference_id=reference_id,
            reference_type=reference_type
        )
    except User.DoesNotExist:
        print(f"User {user_id} not found")
    except Exception as e:
        print(f"Error in wallet_update task: {e}")

