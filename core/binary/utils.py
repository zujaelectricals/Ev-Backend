from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from .models import BinaryNode, BinaryPair, BinaryEarning, BinaryCarryForward
from core.wallet.utils import add_wallet_balance
from core.settings.models import PlatformSettings


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
        # Update direct_children_count for parent (only direct children, not all descendants)
        parent.direct_children_count = BinaryNode.objects.filter(parent=parent).count()
        parent.save(update_fields=['direct_children_count'])
    
    return node


def process_direct_user_commission(referrer, new_user):
    """
    Process direct user commission when a new user is added as direct child
    Only pays commission if referrer has less than activation_count direct children
    
    Args:
        referrer: User who referred the new user
        new_user: User who was just added to the tree
    
    Returns:
        bool: True if commission was paid, False otherwise
    """
    try:
        referrer_node = BinaryNode.objects.get(user=referrer)
    except BinaryNode.DoesNotExist:
        return False
    
    # Get settings
    platform_settings = PlatformSettings.get_settings()
    activation_count = platform_settings.binary_commission_activation_count
    commission_amount = platform_settings.direct_user_commission_amount
    tds_percentage = platform_settings.binary_commission_tds_percentage
    
    # Check if referrer has less than activation_count direct children
    # Only pay if this is a direct child (parent is referrer_node)
    new_user_node = BinaryNode.objects.filter(user=new_user, parent=referrer_node).first()
    if not new_user_node:
        return False
    
    # Check count BEFORE this user was added (current count - 1)
    # Since direct_children_count was already updated in create_binary_node,
    # we need to check if the count BEFORE adding was less than activation_count
    count_before_addition = referrer_node.direct_children_count - 1
    
    # Check if we should pay commission (before activation)
    if count_before_addition < activation_count:
        # Calculate TDS (always applied on all direct user commissions)
        tds_amount = commission_amount * (tds_percentage / Decimal('100'))
        net_amount = commission_amount - tds_amount
        
        # Pay commission (net amount after TDS)
        try:
            add_wallet_balance(
                user=referrer,
                amount=float(net_amount),
                transaction_type='DIRECT_USER_COMMISSION',
                description=f"Direct user commission for {new_user.username} (₹{commission_amount} - ₹{tds_amount} TDS = ₹{net_amount})",
                reference_id=new_user.id,
                reference_type='user'
            )
            
            # Deduct TDS from booking balance
            deduct_from_booking_balance(
                user=referrer,
                deduction_amount=tds_amount,
                deduction_type='TDS_DEDUCTION',
                description=f"TDS ({tds_percentage}%) on direct user commission for {new_user.username}"
            )
            
            # Check if this addition activates binary commission
            if referrer_node.direct_children_count >= activation_count:
                referrer_node.binary_commission_activated = True
                referrer_node.save(update_fields=['binary_commission_activated'])
            
            return True
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error processing direct user commission: {e}")
            return False
    
    return False


def deduct_from_booking_balance(user, deduction_amount, deduction_type='TDS_DEDUCTION', description=''):
    """
    Deduct amount from user's oldest active booking with remaining amount
    Handles both TDS and extra deduction for 6th+ pairs
    
    Args:
        user: User whose payment should be deducted
        deduction_amount: Amount to deduct (Decimal)
        deduction_type: 'TDS_DEDUCTION' or 'EXTRA_DEDUCTION'
        description: Description for transaction
    
    Returns:
        bool: True if deduction was successful, False otherwise
    """
    from core.booking.models import Booking
    from core.wallet.utils import add_wallet_balance
    
    # Find oldest active booking with remaining amount > 0
    booking = Booking.objects.filter(
        user=user,
        status__in=['pending', 'active'],
        remaining_amount__gt=0
    ).order_by('created_at').first()
    
    if not booking:
        # No active booking found, but still record the deduction transaction
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"{deduction_type} of ₹{deduction_amount} for user {user.username} "
            f"but no active booking with remaining amount found"
        )
        # Still create a deduction transaction
        try:
            add_wallet_balance(
                user=user,
                amount=-float(deduction_amount),  # Negative amount for deduction
                transaction_type=deduction_type,
                description=description or f"{deduction_type} (no active booking to deduct from)",
                reference_id=None,
                reference_type='booking'
            )
        except Exception as e:
            logger.error(f"Error creating {deduction_type} transaction: {e}")
        return False
    
    # Deduct from booking
    with transaction.atomic():
        deduction_decimal = Decimal(str(deduction_amount))
        actual_deduction = min(deduction_decimal, booking.remaining_amount)
        
        # Update booking
        booking.total_paid += actual_deduction
        booking.remaining_amount = booking.total_amount - booking.total_paid
        
        # Update booking status if fully paid
        if booking.remaining_amount <= 0:
            booking.status = 'completed'
            booking.completed_at = timezone.now()
        
        booking.save()
        
        # Create deduction transaction
        try:
            add_wallet_balance(
                user=user,
                amount=-float(actual_deduction),  # Negative amount for deduction
                transaction_type=deduction_type,
                description=description or f"{deduction_type} from booking {booking.booking_number}",
                reference_id=booking.id,
                reference_type='booking'
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error creating {deduction_type} transaction: {e}")
    
    return True


def add_to_binary_tree(user, referrer, side):
    """
    Add user to binary tree under referrer
    Processes direct user commission if applicable
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
    
    # Note: Direct user commission is now paid only when payment is confirmed
    # See payment_completed task in core.booking.tasks
    
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


def get_binary_pairs_after_activation_count(user):
    """
    Count total binary pair commissions earned after binary commission activation
    Only counts pairs that were actually paid (not blocked)
    
    Args:
        user: User to count pairs for
    
    Returns:
        int: Number of binary pairs that were paid after activation
    """
    return BinaryPair.objects.filter(
        user=user,
        pair_number_after_activation__isnull=False,
        commission_blocked=False,
        status='processed'  # Only count pairs that were processed (paid)
    ).count()


def get_daily_pairs_count(user, date=None):
    """
    Count pairs created on specific date after binary commission activation
    
    Args:
        user: User to count pairs for
        date: Date to count pairs for (default: today)
    
    Returns:
        int: Number of pairs created on the date
    """
    if date is None:
        date = timezone.now().date()
    
    return BinaryPair.objects.filter(
        user=user,
        pair_number_after_activation__isnull=False,
        pair_date=date
    ).count()


def get_remaining_unmatched_counts(node, pairs_today):
    """
    Calculate remaining unmatched members on each side after pairs used today
    
    Args:
        node: BinaryNode to calculate for
        pairs_today: Number of pairs created today
    
    Returns:
        tuple: (left_remaining, right_remaining)
    """
    # Calculate how many members used from each side
    # For simplicity, assume equal distribution (10 pairs = 10 from left + 10 from right)
    # In practice, pairs are matched 1:1 from left and right
    members_used_per_side = pairs_today
    
    left_remaining = max(0, node.left_count - members_used_per_side)
    right_remaining = max(0, node.right_count - members_used_per_side)
    
    return left_remaining, right_remaining


def get_long_short_legs(left_remaining, right_remaining):
    """
    Identify which side is long leg (more remaining) and short leg (fewer remaining)
    
    Args:
        left_remaining: Remaining unmatched members on left side
        right_remaining: Remaining unmatched members on right side
    
    Returns:
        tuple: (long_side, short_side, long_count, short_count)
               If equal, returns (None, None, 0, 0)
    """
    if left_remaining > right_remaining:
        return ('left', 'right', left_remaining, right_remaining)
    elif right_remaining > left_remaining:
        return ('right', 'left', right_remaining, left_remaining)
    else:
        # Equal counts - no carry forward needed
        return (None, None, 0, 0)


def get_active_carry_forward(user, short_side, date=None):
    """
    Get active carry-forward for matching with new members on short side
    
    Args:
        user: User to check for carry-forward
        short_side: Side that was ignored (needs to match with carried-forward)
        date: Date to check (default: today)
    
    Returns:
        BinaryCarryForward instance or None
    """
    if date is None:
        date = timezone.now().date()
    
    # Get active carry-forward where opposite side was carried forward
    # If short_side is 'left', we need carry-forward from 'right' (long leg)
    # If short_side is 'right', we need carry-forward from 'left' (long leg)
    return BinaryCarryForward.objects.filter(
        user=user,
        is_active=True,
        remaining_count__gt=0
    ).order_by('carried_forward_date', 'created_at').first()


def carry_forward_long_leg(user, date, long_side, long_count):
    """
    Create carry-forward record for long leg members
    
    Args:
        user: User whose members are carried forward
        date: Date when carry-forward occurs
        long_side: Side with long leg ('left' or 'right')
        long_count: Number of members to carry forward
    
    Returns:
        BinaryCarryForward instance
    """
    carry_forward = BinaryCarryForward.objects.create(
        user=user,
        carried_forward_date=date,
        side=long_side,
        initial_member_count=long_count,
        matched_count=0,
        is_active=True
    )
    return carry_forward


def check_and_create_pair(user):
    """
    Check if user has matching left/right pairs and create binary pair
    Only distributors can create pairs and earn
    Uses new commission structure with TDS deduction
    """
    # Business Rule: Only distributors can create pairs and earn
    if not user.is_distributor:
        return None
    
    try:
        node = BinaryNode.objects.get(user=user)
    except BinaryNode.DoesNotExist:
        return None
    
    # Check if binary commission is activated
    if not node.binary_commission_activated:
        return None
    
    # Check if we have both left and right
    if node.left_count == 0 or node.right_count == 0:
        return None
    
    # Get settings
    platform_settings = PlatformSettings.get_settings()
    commission_amount = platform_settings.binary_pair_commission_amount
    tds_threshold = platform_settings.binary_tds_threshold_pairs
    tds_percentage = platform_settings.binary_commission_tds_percentage
    extra_deduction_percentage = platform_settings.binary_extra_deduction_percentage
    daily_limit = platform_settings.binary_daily_pair_limit
    
    now = timezone.now()
    today = now.date()
    
    # Check daily limit (count pairs created TODAY after activation)
    pairs_today = get_daily_pairs_count(user, today)
    
    # Check for active carry-forward first
    active_carry_forward = None
    use_carry_forward = False
    
    if pairs_today >= daily_limit:
        # Daily limit reached - check for carry-forward logic
        # Calculate remaining unmatched members
        left_remaining, right_remaining = get_remaining_unmatched_counts(node, pairs_today)
        
        # Identify long/short legs
        long_side, short_side, long_count, short_count = get_long_short_legs(left_remaining, right_remaining)
        
        if long_side and long_count > 0:
            # Create carry-forward for long leg
            carry_forward_long_leg(user, today, long_side, long_count)
            # No more pairs can be created today
            return None
    else:
        # Check if there's active carry-forward to match with
        # If we're checking pairs, we might have carry-forward from previous day
        # that needs to be matched first
        active_carry_forward = get_active_carry_forward(user, None, today)
        if active_carry_forward and active_carry_forward.remaining_count > 0:
            use_carry_forward = True
    
    # Count pairs after activation (total, not just today)
    pairs_after_activation = BinaryPair.objects.filter(
        user=user,
        pair_number_after_activation__isnull=False
    ).count()
    
    # This will be the next pair number after activation
    pair_number_after_activation = pairs_after_activation + 1
    
    # Check if commission should be blocked for non-Active Buyer distributors
    # Non-Active Buyer distributors can only earn commission for first 5 pairs
    commission_blocked = False
    blocked_reason = ''
    
    if not user.is_active_buyer:
        # Count binary pairs that were actually paid (not blocked)
        paid_pairs_count = get_binary_pairs_after_activation_count(user)
        
        # If 6th+ pair and not Active Buyer, block commission
        if paid_pairs_count >= 5:
            commission_blocked = True
            blocked_reason = f"Not Active Buyer, 6th+ pair (already earned {paid_pairs_count} pairs). Commission will resume when user becomes Active Buyer."
    
    # Calculate TDS (always applied on all pairs, but only if commission is not blocked)
    tds_amount = Decimal('0')
    extra_deduction = Decimal('0')
    net_amount = commission_amount
    
    if not commission_blocked:
        # Calculate TDS (always applied on all pairs)
        tds_amount = commission_amount * (tds_percentage / Decimal('100'))
        net_amount = commission_amount - tds_amount
        
        # Calculate extra deduction for 6th+ pairs
        if pair_number_after_activation > tds_threshold:
            extra_deduction = commission_amount * (extra_deduction_percentage / Decimal('100'))
            net_amount = net_amount - extra_deduction
    
    # Create binary pair
    with transaction.atomic():
        pair = BinaryPair.objects.create(
            user=user,
            left_user=left_node.user,
            right_user=right_node.user,
            pair_amount=commission_amount,
            earning_amount=net_amount if not commission_blocked else Decimal('0'),  # Net amount after TDS and extra deduction (0 if blocked)
            status='matched',
            matched_at=now,
            pair_month=now.month,
            pair_year=now.year,
            pair_date=today,
            pair_number_after_activation=pair_number_after_activation,
            is_carry_forward_pair=use_carry_forward,
            carry_forward=active_carry_forward if use_carry_forward else None,
            extra_deduction_applied=extra_deduction if not commission_blocked else Decimal('0'),
            commission_blocked=commission_blocked,
            blocked_reason=blocked_reason
        )
        
        # Update carry-forward matched count if used
        if use_carry_forward and active_carry_forward:
            active_carry_forward.matched_count += 1
            active_carry_forward.matched_at = now
            # Mark as inactive if all members matched
            if active_carry_forward.remaining_count <= 0:
                active_carry_forward.is_active = False
            active_carry_forward.save(update_fields=['matched_count', 'matched_at', 'is_active'])
        
        # Count previous pairs for this user (for display purposes)
        previous_pairs_count = BinaryPair.objects.filter(user=user).count()
        pair_number = previous_pairs_count + 1
        
        # Create earning record
        earning = BinaryEarning.objects.create(
            user=user,
            binary_pair=pair,
            amount=commission_amount,  # Gross amount
            pair_number=pair_number,
            net_amount=net_amount if not commission_blocked else Decimal('0')  # Net amount after TDS and extra deduction (0 if blocked)
        )
        
        # Only deduct TDS and extra deduction if commission is not blocked
        if not commission_blocked:
            # Deduct TDS from booking balance (always applied on all pairs)
            if tds_amount > 0:
                deduct_from_booking_balance(
                    user=user,
                    deduction_amount=tds_amount,
                    deduction_type='TDS_DEDUCTION',
                    description=f"TDS ({tds_percentage}%) on binary pair commission (Pair #{pair_number_after_activation})"
                )
            
            # Deduct extra amount from booking balance (for 6th+ pairs)
            if extra_deduction > 0:
                deduct_from_booking_balance(
                    user=user,
                    deduction_amount=extra_deduction,
                    deduction_type='EXTRA_DEDUCTION',
                    description=f"Extra deduction ({extra_deduction_percentage}%) on binary pair commission (Pair #{pair_number_after_activation})"
                )
            
            # Trigger wallet update via Celery (will credit net amount)
            from core.binary.tasks import pair_matched
            pair_matched.delay(pair.id)
        else:
            # Log that commission was blocked
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Binary pair commission blocked for user {user.username}: {blocked_reason}. "
                f"Pair #{pair_number_after_activation} created but no commission paid."
            )
        
        # Update node counts (remove matched pair - counts will be recalculated recursively)
        node.update_counts()
        
        # If daily limit reached after this pair, create carry-forward
        pairs_today_after = get_daily_pairs_count(user, today)
        if pairs_today_after >= daily_limit:
            # Calculate remaining after today's pairs
            left_remaining, right_remaining = get_remaining_unmatched_counts(node, pairs_today_after)
            long_side, short_side, long_count, short_count = get_long_short_legs(left_remaining, right_remaining)
            
            if long_side and long_count > 0:
                # Create carry-forward for long leg
                carry_forward_long_leg(user, today, long_side, long_count)
        
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

