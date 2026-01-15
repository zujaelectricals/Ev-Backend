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
    Only distributors can create pairs and earn
    """
    # Business Rule: Only distributors can create pairs and earn
    if not user.is_distributor:
        return None
    
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


def place_user_manually(user, parent_node, side, allow_replacement=False):
    """
    Manually place a user in a specific position in the binary tree
    
    Args:
        user: User to place
        parent_node: BinaryNode to place under
        side: 'left' or 'right'
        allow_replacement: If True, replace existing node if position is occupied
    
    Returns:
        BinaryNode: The created or updated node
    
    Raises:
        ValueError: If position is invalid or occupied (when allow_replacement=False)
    """
    if side not in ['left', 'right']:
        raise ValueError(f"Invalid side: {side}. Must be 'left' or 'right'")
    
    # Check if position is available
    existing_node = BinaryNode.objects.filter(parent=parent_node, side=side).first()
    
    if existing_node:
        if not allow_replacement:
            raise ValueError(f"Position {side} under parent node {parent_node.id} is already occupied")
        # If allowing replacement, we need to handle the existing node
        # For now, we'll raise an error - replacement logic can be added later
        raise ValueError("Replacement of existing nodes is not yet supported")
    
    # Check if user already has a node
    existing_user_node = BinaryNode.objects.filter(user=user).first()
    
    if existing_user_node:
        # Move existing node to new position
        return move_binary_node(existing_user_node, parent_node, side)
    else:
        # Create new node
        return create_binary_node(user, parent=parent_node, side=side)


def move_binary_node(node, new_parent, new_side):
    """
    Move an existing binary node to a new position
    
    Args:
        node: BinaryNode to move
        new_parent: New parent BinaryNode
        new_side: New side ('left' or 'right')
    
    Returns:
        BinaryNode: The moved node
    
    Raises:
        ValueError: If move is invalid (cycle, position occupied, etc.)
    """
    if new_side not in ['left', 'right']:
        raise ValueError(f"Invalid side: {new_side}. Must be 'left' or 'right'")
    
    # Prevent moving node to itself or its descendants
    if node == new_parent:
        raise ValueError("Cannot move node to itself")
    
    # Check for cycles: new_parent cannot be a descendant of node
    current = new_parent
    while current:
        if current == node:
            raise ValueError("Cannot move node to its own descendant (would create cycle)")
        current = current.parent
    
    # Check if target position is available
    existing_node = BinaryNode.objects.filter(parent=new_parent, side=new_side).first()
    if existing_node and existing_node != node:
        raise ValueError(f"Position {new_side} under parent node {new_parent.id} is already occupied")
    
    # Store old parent for count updates
    old_parent = node.parent
    old_side = node.side
    
    with transaction.atomic():
        # Update node position
        node.parent = new_parent
        node.side = new_side
        node.level = new_parent.level + 1 if new_parent else 0
        node.save()
        
        # Update old parent's counts
        if old_parent:
            old_parent.update_counts()
        
        # Update new parent's counts
        if new_parent:
            new_parent.update_counts()
        
        # Update levels of all descendants
        update_descendant_levels(node)
    
    return node


def update_descendant_levels(node):
    """
    Recursively update levels of all descendant nodes after a move
    """
    children = BinaryNode.objects.filter(parent=node)
    for child in children:
        child.level = node.level + 1
        child.save(update_fields=['level'])
        update_descendant_levels(child)


def is_node_in_tree(node, tree_owner):
    """
    Check if a node belongs to the tree owned by tree_owner
    
    Args:
        node: BinaryNode to check
        tree_owner: User who owns the tree
    
    Returns:
        bool: True if node is in tree_owner's tree
    """
    try:
        owner_node = BinaryNode.objects.get(user=tree_owner)
    except BinaryNode.DoesNotExist:
        return False
    
    # Traverse up from node to root
    current = node
    while current:
        if current == owner_node:
            return True
        current = current.parent
    
    return False


def can_user_be_placed(referrer, target_user):
    """
    Check if a user can be placed in referrer's tree
    
    Args:
        referrer: User who owns the tree
        target_user: User to be placed
    
    Returns:
        bool: True if user can be placed
    """
    # Check if target_user used referrer's referral code
    # Check user.referred_by
    if target_user.referred_by == referrer:
        return True
    
    # Check bookings with referrer's code
    from core.booking.models import Booking
    has_booking_with_referrer = Booking.objects.filter(
        user=target_user,
        referred_by=referrer
    ).exists()
    
    return has_booking_with_referrer

