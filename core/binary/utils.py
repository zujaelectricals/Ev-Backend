from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from .models import BinaryNode, BinaryPair, BinaryEarning
from core.wallet.utils import add_wallet_balance


def create_binary_node(user, parent=None, side=None):
    """Create binary node for user"""
    node, created = BinaryNode.objects.get_or_create(
        user=user,
        defaults={
            'parent': parent,
            'side': side,
            'level': parent.level + 1 if parent else 0,
        }
    )
    
    if parent:
        parent.update_counts()
    
    return node


def add_to_binary_tree(user, referrer, side):
    """
    Add user to binary tree under referrer
    """
    if not referrer:
        return None
    
    referrer_node, _ = BinaryNode.objects.get_or_create(user=referrer)
    
    # Check if side is available
    if side == 'left' and referrer_node.left_count == 0:
        node = create_binary_node(user, parent=referrer_node, side='left')
    elif side == 'right' and referrer_node.right_count == 0:
        node = create_binary_node(user, parent=referrer_node, side='right')
    else:
        # Find next available position in the tree
        node = find_next_available_position(user, referrer_node)
    
    return node


def find_next_available_position(user, start_node):
    """
    Find next available position in binary tree (level-order insertion)
    """
    from collections import deque
    
    queue = deque([start_node])
    
    while queue:
        current = queue.popleft()
        
        # Check left child
        left_child = BinaryNode.objects.filter(parent=current, side='left').first()
        if not left_child:
            return create_binary_node(user, parent=current, side='left')
        
        # Check right child
        right_child = BinaryNode.objects.filter(parent=current, side='right').first()
        if not right_child:
            return create_binary_node(user, parent=current, side='right')
        
        # Add children to queue
        queue.append(left_child)
        queue.append(right_child)
    
    return None


def check_and_create_pair(user):
    """
    Check if user has matching left/right pairs and create binary pair
    """
    try:
        node = BinaryNode.objects.get(user=user)
    except BinaryNode.DoesNotExist:
        return None
    
    # Check if we have both left and right
    if node.left_count == 0 or node.right_count == 0:
        return None
    
    # Check monthly limit
    now = timezone.now()
    pairs_this_month = BinaryPair.objects.filter(
        user=user,
        pair_month=now.month,
        pair_year=now.year
    ).count()
    
    if pairs_this_month >= settings.MAX_BINARY_PAIRS_PER_MONTH:
        return None
    
    # Get one left and one right user
    left_node = BinaryNode.objects.filter(parent=node, side='left').first()
    right_node = BinaryNode.objects.filter(parent=node, side='right').first()
    
    if not left_node or not right_node:
        return None
    
    # Create binary pair
    with transaction.atomic():
        pair = BinaryPair.objects.create(
            user=user,
            left_user=left_node.user,
            right_user=right_node.user,
            pair_amount=Decimal('1000'),  # Default pair amount (adjust as needed)
            earning_amount=Decimal('500'),  # Default earning (adjust as needed)
            status='matched',
            matched_at=timezone.now(),
            pair_month=now.month,
            pair_year=now.year
        )
        
        # Count previous pairs for this user
        previous_pairs_count = BinaryPair.objects.filter(user=user).count()
        pair_number = previous_pairs_count + 1
        
        # Create earning record
        earning = BinaryEarning.objects.create(
            user=user,
            binary_pair=pair,
            amount=pair.earning_amount,
            pair_number=pair_number,
            net_amount=pair.earning_amount
        )
        
        # Trigger wallet update via Celery
        from core.binary.tasks import pair_matched
        pair_matched.delay(pair.id)
        
        # Update node counts (remove matched pair)
        node.left_count -= 1
        node.right_count -= 1
        node.save(update_fields=['left_count', 'right_count'])
        
        return pair
    
    return None

