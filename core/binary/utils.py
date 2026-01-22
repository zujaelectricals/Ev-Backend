from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from .models import BinaryNode, BinaryPair, BinaryEarning, BinaryCarryForward
from core.wallet.utils import add_wallet_balance
from core.settings.models import PlatformSettings


def create_binary_node(user, parent=None, side=None):
    """
    Create binary node for user
    
    Note: The UniqueConstraint on (parent, side) prevents duplicate nodes.
    If a duplicate is attempted, IntegrityError will be raised.
    """
    # Check if node already exists for this user
    existing_node = BinaryNode.objects.filter(user=user).first()
    if existing_node:
        # If node exists but parent/side is different, update it
        if existing_node.parent != parent or existing_node.side != side:
            existing_node.parent = parent
            existing_node.side = side
            existing_node.level = parent.level + 1 if parent else 0
            existing_node.save(update_fields=['parent', 'side', 'level'])
            node = existing_node
        else:
            # Node already exists with same parent/side
            node = existing_node
    else:
        # Create new node
        node = BinaryNode.objects.create(
            user=user,
            parent=parent,
            side=side,
            level=parent.level + 1 if parent else 0,
        )
    
    if parent:
        parent.update_counts()
        # Update direct_children_count for parent (only direct children, not all descendants)
        parent.direct_children_count = BinaryNode.objects.filter(parent=parent).count()
        parent.save(update_fields=['direct_children_count'])
        
        # Update counts for all ancestors recursively
        # This ensures ancestor counts are accurate for activation checks
        current = parent.parent
        while current:
            current.update_counts()
            current = current.parent
    
    return node


def get_all_ancestors(user_node):
    """
    Get all ancestor nodes by traversing up the binary tree
    
    Args:
        user_node: BinaryNode to start from
    
    Returns:
        list: List of all ancestor BinaryNode objects (parent, grandparent, etc.)
              Empty list if user_node has no parent (root node)
    """
    ancestors = []
    current = user_node.parent
    
    while current:
        ancestors.append(current)
        current = current.parent
    
    return ancestors


def get_total_descendants_count(node):
    """
    Get total descendants count for a node (recursively calculated, not from stored counts)
    This ensures accurate counts even if stored left_count/right_count are stale
    
    Args:
        node: BinaryNode to get count for
    
    Returns:
        int: Total number of descendants (all levels) in the tree
    """
    # Use the recursive method from the model to get accurate counts
    # This counts all descendants, not just direct children
    left_count = node.get_all_descendants_count('left')
    right_count = node.get_all_descendants_count('right')
    return left_count + right_count


def has_successful_payment(user):
    """
    Check if user has at least one successful payment (completed payment)
    
    Args:
        user: User to check
    
    Returns:
        bool: True if user has at least one completed payment, False otherwise
    """
    from core.booking.models import Payment
    return Payment.objects.filter(
        user=user,
        status='completed'
    ).exists()


def process_direct_user_commission(referrer, new_user):
    """
    Process referral bonus (DIRECT_USER_COMMISSION) when a new user is added to the binary tree
    Pays ₹1000 commission to ALL ancestors (not just direct parent) if they have < 3 total descendants
    Binary commission activates when any ancestor has 3+ total descendants
    
    IMPORTANT RULES:
    - Commission is only paid if user has at least one successful payment
    - Commission (referral bonus) MUST STOP completely after binary_commission_activated = True
    - After activation, earnings come ONLY from binary pair matching
    
    Args:
        referrer: User who referred the new user (may not be direct parent)
        new_user: User who was just added to the tree
    
    Returns:
        bool: True if at least one commission was paid, False otherwise
    """
    # Check if user has successful payment - commission only paid if payment is completed
    if not has_successful_payment(new_user):
        return False
    
    try:
        new_user_node = BinaryNode.objects.get(user=new_user)
    except BinaryNode.DoesNotExist:
        return False
    
    # Get settings
    platform_settings = PlatformSettings.get_settings()
    activation_count = platform_settings.binary_commission_activation_count
    commission_amount = platform_settings.direct_user_commission_amount
    tds_percentage = platform_settings.binary_commission_tds_percentage
    
    # Get all ancestors by traversing up the tree
    ancestors = get_all_ancestors(new_user_node)
    
    if not ancestors:
        # No ancestors (root node), no commission to pay
        return False
    
    from core.wallet.models import WalletTransaction
    
    commissions_paid = False
    
    # Process commission for each ancestor
    # Use transaction to ensure atomicity and prevent race conditions
    with transaction.atomic():
        for ancestor_node in ancestors:
            # Lock the row to prevent concurrent modifications
            # This ensures we get the latest binary_commission_activated flag
            locked_node = BinaryNode.objects.select_for_update().get(id=ancestor_node.id)
            ancestor_user = locked_node.user
            
            # EXPLICIT CHECK: If binary commission is already activated, skip ALL commission processing
            # Referral bonus (DIRECT_USER_COMMISSION) MUST STOP completely after activation
            if locked_node.binary_commission_activated:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(
                    f"Commission blocked for {ancestor_user.username}: "
                    f"Binary commission already activated. Referral bonus stopped."
                )
                continue  # Skip this ancestor completely - no commission payment
            
            # Calculate total descendants using recursive counting FIRST (before updating stored counts)
            # This gives us the accurate count including the new user that was just added
            total_descendants = get_total_descendants_count(locked_node)
            
            # Count before this user was added (subtract 1 because new_user is already in the tree)
            count_before_addition = total_descendants - 1
            
            # Update stored counts AFTER calculation to keep them in sync for future operations
            # This is important when users are added deep in the tree
            locked_node.update_counts()
            locked_node.refresh_from_db()
            
            # Check if commission should be paid (before activation)
            # IMPORTANT: Once binary commission is activated, no more direct user commissions are paid
            # Only pairs will generate commission after activation
            # Commission is paid if count_before_addition < activation_count (i.e., before reaching 3)
            if count_before_addition < activation_count:
                # Check if commission already paid for this user by this ancestor (prevent duplicates)
                commission_already_paid = WalletTransaction.objects.filter(
                    user=ancestor_user,
                    transaction_type='DIRECT_USER_COMMISSION',
                    reference_id=new_user.id,
                    reference_type='user'
                ).exists()
                
                if not commission_already_paid:
                    # Final safety check: Re-check flag with locked node (already locked above)
                    # This prevents race conditions when multiple users are processed simultaneously
                    # IMPORTANT: We allow payment if count_before_addition < activation_count
                    # This means the 3rd user (count_before_addition=2, total_descendants=3) will get commission
                    # Activation happens AFTER payment in the code below
                    if locked_node.binary_commission_activated:
                        # Binary commission already activated, skip payment
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.info(
                            f"Commission blocked for {ancestor_user.username} (final check): "
                            f"Binary commission already activated"
                        )
                        continue
                    
                    # Calculate TDS (always applied on all direct user commissions)
                    tds_amount = commission_amount * (tds_percentage / Decimal('100'))
                    net_amount = commission_amount - tds_amount
                    
                    # Pay commission (net amount after TDS)
                    try:
                        add_wallet_balance(
                            user=ancestor_user,
                            amount=float(net_amount),
                            transaction_type='DIRECT_USER_COMMISSION',
                            description=f"User commission for {new_user.username} (₹{commission_amount} - ₹{tds_amount} TDS = ₹{net_amount})",
                            reference_id=new_user.id,
                            reference_type='user'
                        )
                        
                        # Deduct TDS from booking balance
                        deduct_from_booking_balance(
                            user=ancestor_user,
                            deduction_amount=tds_amount,
                            deduction_type='TDS_DEDUCTION',
                            description=f"TDS ({tds_percentage}%) on user commission for {new_user.username}",
                            reference_id=new_user.id,
                            reference_type='user'
                        )
                        
                        commissions_paid = True
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.error(
                            f"Error processing user commission for ancestor {ancestor_user.username} "
                            f"for new user {new_user.username}: {e}"
                        )
            
            # Check if this addition activates binary commission for this ancestor
            # Activation based on total descendants (not just direct children)
            if total_descendants >= activation_count and not locked_node.binary_commission_activated:
                locked_node.binary_commission_activated = True
                # Use new_user_node's created_at to ensure the 3rd member (D) is included in pairing
                # This ensures D.created_at == activation_timestamp, so D is included with >= comparison
                locked_node.activation_timestamp = new_user_node.created_at
                locked_node.save(update_fields=['binary_commission_activated', 'activation_timestamp'])
    
    return commissions_paid


def deduct_from_booking_balance(user, deduction_amount, deduction_type='EXTRA_DEDUCTION', description='', reference_id=None, reference_type='booking'):
    """
    Deduct amount from user's oldest active booking with remaining amount
    Used for both TDS_DEDUCTION and EXTRA_DEDUCTION
    
    Args:
        user: User whose payment should be deducted
        deduction_amount: Amount to deduct (Decimal)
        deduction_type: 'TDS_DEDUCTION' (for both direct commissions and binary pairs) or 'EXTRA_DEDUCTION' (for 6th+ pairs)
        description: Description for transaction
        reference_id: Optional reference ID (e.g., pair.id for binary pairs, booking.id for bookings)
        reference_type: Optional reference type (e.g., 'binary_pair' for pairs, 'booking' for bookings)
    
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
                reference_id=reference_id,
                reference_type=reference_type
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
                reference_id=reference_id if reference_id else booking.id,
                reference_type=reference_type if reference_id else 'booking'
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error creating {deduction_type} transaction: {e}")
    
    return True


def handle_referral_based_placement(user, referring_user, referrer_node):
    """
    Handle placement when user joins using a specific parent's referral code (Rule 3)
    
    If referring_user is a specific parent (not root):
    - Check referrer's left child first (if available → place on LEFT)
    - If left occupied, check right child (if available → place on RIGHT)
    - If both occupied, continue with standard algorithm
    
    Args:
        user: User to place
        referring_user: User who issued the referral code used (may be specific parent)
        referrer_node: BinaryNode of the referring_user
    
    Returns:
        BinaryNode: Created node or None if placement fails
    """
    # Check which sides are available (not just count total children)
    left_child_exists = BinaryNode.objects.filter(parent=referrer_node, side='left').exists()
    right_child_exists = BinaryNode.objects.filter(parent=referrer_node, side='right').exists()
    
    # Rule 1: If left is empty → place on LEFT
    if not left_child_exists:
        return create_binary_node(user, parent=referrer_node, side='left')
    
    # Rule 2: If right is empty → place on RIGHT
    elif not right_child_exists:
        return create_binary_node(user, parent=referrer_node, side='right')
    
    # Rule 3: Both slots full → Continue with standard algorithm
    # This will be handled by the main placement logic
    return None


def add_to_binary_tree(user, referrer, side=None, referring_user=None):
    """
    Add user to binary tree under referrer with smart placement
    
    Placement rules:
    1. First 2 users: LEFT then RIGHT
    2. From 3rd onward: Follow left-chain (or configured default side)
    3. Referral override: If using specific parent's code, place in that parent's tree
    
    Args:
        user: User to place
        referrer: User who owns the tree (root referrer)
        side: Optional explicit side ('left' or 'right') - if provided, used directly
        referring_user: User who issued the referral code used (for referral-based placement)
    
    Returns:
        BinaryNode: Created node or None if placement fails
    """
    if not referrer:
        return None
    
    referrer_node, _ = BinaryNode.objects.get_or_create(user=referrer)
    
    # If explicit side is provided, use it (user-controlled positioning)
    if side and side in ['left', 'right']:
        # Check database directly (not cached count) to avoid race conditions
        existing_on_side = BinaryNode.objects.filter(parent=referrer_node, side=side).exists()
        if not existing_on_side:
            try:
                return create_binary_node(user, parent=referrer_node, side=side)
            except Exception as e:
                # Handle UniqueConstraint violation (race condition)
                # If constraint violation, the side was occupied by another request
                # Fall through to automatic placement
                from django.db import IntegrityError
                if isinstance(e, IntegrityError) or 'unique_parent_side' in str(e):
                    pass  # Continue with automatic placement
                else:
                    raise
        # Side requested but not available, continue with automatic placement
    
    # Rule 3: Referral-based placement (specific parent referral)
    if referring_user and referring_user != referrer:
        # Check if referring_user is in referrer's tree
        try:
            referring_node = BinaryNode.objects.get(user=referring_user)
            # Check if referring_node is in referrer's tree
            if is_node_in_tree(referring_node, referrer):
                # Try referral-based placement in referring_user's tree
                referral_node = handle_referral_based_placement(user, referring_user, referring_node)
                if referral_node:
                    return referral_node
                # Both slots full, continue with standard placement from root
        except BinaryNode.DoesNotExist:
            pass  # referring_user doesn't have a node, continue with standard placement
    
    # Standard placement: Use left-priority algorithm with settings preference
    # Get default placement side from settings
    platform_settings = PlatformSettings.get_settings()
    preferred_side = platform_settings.binary_tree_default_placement_side or 'left'
    
    # Use the side-priority algorithm
    node = find_next_available_position_by_side(user, referrer_node, preferred_side)
    
    # Note: Direct user commission is now paid only when payment is confirmed
    # See payment_completed task in core.booking.tasks
    
    return node


def find_next_available_position(user, start_node):
    """
    Find next available position using left-priority algorithm (legacy function)
    This function is kept for backward compatibility but calls the new algorithm
    """
    # Get default placement side from settings
    platform_settings = PlatformSettings.get_settings()
    preferred_side = platform_settings.binary_tree_default_placement_side or 'left'
    return find_next_available_position_by_side(user, start_node, preferred_side)


def find_next_available_position_by_side(user, start_node, preferred_side='left'):
    """
    Find next available position in binary tree using side-priority algorithm
    
    Rules:
    1. First user → preferred_side (default: LEFT)
    2. Second user → opposite_side (default: RIGHT)
    3. From 3rd onward → Follow preferred_side chain (default: left chain)
    
    Args:
        user: User to place
        start_node: BinaryNode to start placement from
        preferred_side: 'left' or 'right' (default: 'left')
    
    Returns:
        BinaryNode: Created node or None if placement fails
    """
    # Check which sides are actually available (not just count total children)
    left_child_exists = BinaryNode.objects.filter(parent=start_node, side='left').exists()
    right_child_exists = BinaryNode.objects.filter(parent=start_node, side='right').exists()
    
    # Rule 1: If preferred_side is empty → place on preferred_side
    if preferred_side == 'left' and not left_child_exists:
        return create_binary_node(user, parent=start_node, side='left')
    elif preferred_side == 'right' and not right_child_exists:
        return create_binary_node(user, parent=start_node, side='right')
    
    # Rule 2: If opposite_side is empty → place on opposite_side
    opposite_side = 'right' if preferred_side == 'left' else 'left'
    if opposite_side == 'left' and not left_child_exists:
        return create_binary_node(user, parent=start_node, side='left')
    elif opposite_side == 'right' and not right_child_exists:
        return create_binary_node(user, parent=start_node, side='right')
    
    # Rule 3: Both slots full → Follow preferred_side chain
    current = start_node
    while current:
        child_on_side = BinaryNode.objects.filter(
            parent=current,
            side=preferred_side
        ).first()
        
        if not child_on_side:
            # Found available position
            return create_binary_node(user, parent=current, side=preferred_side)
        
        # Continue down the chain
        current = child_on_side
    
    return None


def get_binary_pairs_after_activation_count(user):
    """
    Count total binary pair commissions earned after binary commission activation
    Only counts pairs that were actually paid (not blocked)
    
    IMPORTANT: Counts pairs with status 'matched' OR 'processed' to prevent race conditions.
    Pairs are created with status 'matched' and later updated to 'processed' by Celery task.
    If we only count 'processed', pairs still in 'matched' status won't be counted, allowing
    more pairs to be created than allowed.
    
    Args:
        user: User to count pairs for
    
    Returns:
        int: Number of binary pairs that were paid (or will be paid) after activation
    """
    return BinaryPair.objects.filter(
        user=user,
        pair_number_after_activation__isnull=False,
        commission_blocked=False,
        status__in=['matched', 'processed']  # Count both matched and processed pairs to prevent race conditions
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
    Uses actual BinaryPair records to count matched users
    
    Args:
        node: BinaryNode to calculate for
        pairs_today: Number of pairs created today (for reference, but we use actual data)
    
    Returns:
        tuple: (left_remaining, right_remaining)
    """
    # Get all pairs created today for this user
    today = timezone.now().date()
    pairs_today_list = BinaryPair.objects.filter(
        user=node.user,
        pair_number_after_activation__isnull=False,
        pair_date=today
    )
    
    # Count actual users matched from each side today
    left_users_matched = set()
    right_users_matched = set()
    for pair in pairs_today_list:
        if pair.left_user:
            left_users_matched.add(pair.left_user.id)
        if pair.right_user:
            right_users_matched.add(pair.right_user.id)
    
    # Get all descendant nodes on each side
    left_descendants = get_all_descendant_nodes(node, 'left')
    right_descendants = get_all_descendant_nodes(node, 'right')
    
    # Count unmatched on each side (users not in matched sets)
    left_unmatched_count = len([n for n in left_descendants if n.user.id not in left_users_matched])
    right_unmatched_count = len([n for n in right_descendants if n.user.id not in right_users_matched])
    
    return left_unmatched_count, right_unmatched_count


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
    # Note: remaining_count is a property, so we filter by actual fields: initial_member_count > matched_count
    from django.db.models import F
    return BinaryCarryForward.objects.filter(
        user=user,
        is_active=True
    ).filter(
        initial_member_count__gt=F('matched_count')
    ).order_by('carried_forward_date', 'created_at').first()


def get_all_descendant_nodes(node, side):
    """
    Get all descendant BinaryNode objects on a specific side recursively
    
    Args:
        node: BinaryNode to start from
        side: 'left' or 'right'
    
    Returns:
        list: List of all descendant BinaryNode objects on the specified side
    """
    descendants = []
    # Get direct children on this side
    direct_children = BinaryNode.objects.filter(parent=node, side=side).select_related('user')
    descendants.extend(direct_children)
    
    # Recursively get descendants of each direct child
    for child in direct_children:
        descendants.extend(get_all_descendant_nodes(child, 'left'))
        descendants.extend(get_all_descendant_nodes(child, 'right'))
    
    return descendants


def get_unmatched_users_for_pairing(node):
    """
    Get one unmatched user from left side and one from right side
    STRICT RULE: Pair = 1 left-leg member + 1 right-leg member
    Two members on same leg (LL or RR) → NOT a pair
    
    Uses BinaryPair records to determine which users are already matched
    
    IMPORTANT: Only includes members created at or after activation (excludes pre-activation members)
    - Members created before activation (1st and 2nd) are excluded
    - Member that triggered activation (3rd) is included
    - Members created after activation are included
    
    Args:
        node: BinaryNode to get unmatched users for
    
    Returns:
        tuple: (left_node, right_node) or (None, None) if no pair possible
    """
    # Check if binary commission is activated
    if not node.binary_commission_activated:
        return (None, None)
    
    # Get activation timestamp
    activation_time = node.activation_timestamp
    if not activation_time:
        # If no activation timestamp, return None (shouldn't happen if activated)
        return (None, None)
    
    # 1. Get all BinaryPair records for this node's user
    pairs = BinaryPair.objects.filter(user=node.user)
    
    # 2. Extract all left_user and right_user IDs that have been matched
    matched_user_ids = set()
    for pair in pairs:
        if pair.left_user:
            matched_user_ids.add(pair.left_user.id)
        if pair.right_user:
            matched_user_ids.add(pair.right_user.id)
    
    # 3. Get all descendant nodes on LEFT side (where side='left' relative to this node)
    left_descendants = get_all_descendant_nodes(node, 'left')
    
    # 4. Get all descendant nodes on RIGHT side (where side='right' relative to this node)
    right_descendants = get_all_descendant_nodes(node, 'right')
    
    # 5. Filter: Only include nodes created at or after activation
    # Exclude nodes that existed before activation (B, C in the example)
    # Include D (3rd member that triggered activation) and all subsequent members
    left_post_activation = [
        n for n in left_descendants 
        if n.created_at >= activation_time and n.user.id not in matched_user_ids
    ]
    right_post_activation = [
        n for n in right_descendants 
        if n.created_at >= activation_time and n.user.id not in matched_user_ids
    ]
    
    # 6. Return first unmatched node from LEFT and first unmatched node from RIGHT
    # 7. If either side has no unmatched users, return (None, None)
    left_node = left_post_activation[0] if left_post_activation else None
    right_node = right_post_activation[0] if right_post_activation else None
    
    return (left_node, right_node)


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
    
    # Get settings
    platform_settings = PlatformSettings.get_settings()
    activation_count = platform_settings.binary_commission_activation_count
    
    # Update stored counts first to ensure accuracy
    node.update_counts()
    node.refresh_from_db()
    
    # Calculate total descendants using recursive counting
    total_descendants = get_total_descendants_count(node)
    
    # Retroactive activation: If user has 3+ descendants but isn't activated, activate now
    # This handles cases where activation didn't trigger when users were added (e.g., before recursive counting fix)
    if total_descendants >= activation_count and not node.binary_commission_activated:
        # Find the 3rd member (the one that should have triggered activation)
        # Get all descendants sorted by creation date
        all_descendants = []
        all_descendants.extend(get_all_descendant_nodes(node, 'left'))
        all_descendants.extend(get_all_descendant_nodes(node, 'right'))
        all_descendants.sort(key=lambda n: n.created_at)
        
        # The 3rd member (index 2) should be the activation trigger
        if len(all_descendants) >= activation_count:
            third_member_node = all_descendants[activation_count - 1]  # Index 2 for 3rd member
            node.binary_commission_activated = True
            node.activation_timestamp = third_member_node.created_at
            node.save(update_fields=['binary_commission_activated', 'activation_timestamp'])
    
    # Check if binary commission is activated
    # STRICT RULE: Pair matching is BLOCKED before activation
    if not node.binary_commission_activated:
        return None
    
    # Check if we have both left and right using recursive counting (not stored counts)
    # STRICT RULE: Pair = 1 left-leg member + 1 right-leg member (must have both)
    left_count = node.get_all_descendants_count('left')
    right_count = node.get_all_descendants_count('right')
    if left_count == 0 or right_count == 0:
        return None
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
    
    # Get unmatched users for pairing
    # STRICT RULE: Must have one from left AND one from right (no same-leg pairing)
    # get_unmatched_users_for_pairing ensures left_node is from left subtree and right_node is from right subtree
    left_node, right_node = get_unmatched_users_for_pairing(node)
    
    # Strict validation: If either is None, no pair possible - must have BOTH left AND right
    # This enforces the rule: Pair = 1 left-leg member + 1 right-leg member
    # Two members on same leg (LL or RR) → NOT a pair
    if left_node is None or right_node is None:
        return None
    
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
        
        # Deduct TDS and extra deduction from booking balance if commission is not blocked
        if not commission_blocked:
            # Deduct TDS from booking balance (for all pairs)
            if tds_amount > 0:
                deduct_from_booking_balance(
                    user=user,
                    deduction_amount=tds_amount,
                    deduction_type='TDS_DEDUCTION',
                    description=f"TDS ({tds_percentage}%) on binary pair commission (Pair #{pair_number_after_activation})",
                    reference_id=pair.id,
                    reference_type='binary_pair'
                )
            
            # Deduct extra amount from booking balance (for 6th+ pairs only)
            if extra_deduction > 0:
                deduct_from_booking_balance(
                    user=user,
                    deduction_amount=extra_deduction,
                    deduction_type='EXTRA_DEDUCTION',
                    description=f"Extra deduction ({extra_deduction_percentage}%) on binary pair commission (Pair #{pair_number_after_activation})",
                    reference_id=pair.id,
                    reference_type='binary_pair'
                )
            
            # Trigger wallet update via Celery (will credit net amount)
            # Use on_commit to ensure task is queued only after transaction commits
            # This prevents "pair not found" errors if transaction rolls back
            from core.binary.tasks import pair_matched
            from django.db import transaction as db_transaction
            
            # Queue task after transaction commits to ensure pair exists in database
            db_transaction.on_commit(lambda: pair_matched.delay(pair.id))
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

