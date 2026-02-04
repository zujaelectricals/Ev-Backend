from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from .models import BinaryNode, BinaryPair, BinaryEarning
from .serializers import (
    BinaryNodeSerializer, BinaryPairSerializer, BinaryEarningSerializer,
    BinaryTreeNodeSerializer
)
from .utils import check_and_create_pair


class BinaryNodeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Binary Node viewing and manual placement
    """
    queryset = BinaryNode.objects.all()
    serializer_class = BinaryNodeSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return BinaryNode.objects.all()
        return BinaryNode.objects.filter(user=user)
    
    def _is_tree_owner(self, user, node):
        """Check if user owns the tree containing this node"""
        try:
            owner_node = BinaryNode.objects.get(user=user)
        except BinaryNode.DoesNotExist:
            return False
        
        # Traverse up from node to root
        current = node
        while current:
            if current == owner_node:
                return True
            current = current.parent
        
        return False
    
    def _can_place_user(self, referrer, target_user):
        """Check if target_user can be placed in referrer's tree"""
        from .utils import can_user_be_placed
        return can_user_be_placed(referrer, target_user)
    
    def _validate_no_cycles(self, node, new_parent):
        """Validate that moving node to new_parent won't create a cycle"""
        if node == new_parent:
            raise ValidationError("Cannot move node to itself")
        
        # Check if new_parent is a descendant of node
        current = new_parent
        while current:
            if current == node:
                raise ValidationError("Cannot move node to its own descendant (would create cycle)")
            current = current.parent
        
        return True
    
    @action(detail=False, methods=['get'])
    def my_tree(self, request):
        """Get current user's binary tree info"""
        try:
            node = BinaryNode.objects.get(user=request.user)
            serializer = self.get_serializer(node)
            return Response(serializer.data)
        except BinaryNode.DoesNotExist:
            return Response({'message': 'No binary node found'}, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=False, methods=['get'])
    def tree_structure(self, request):
        """Get full binary tree structure with all children and pending users"""
        # Get pending users (this works even if referrer has no binary node)
        referrer = request.user
        
        # Get users who have referred_by = referrer
        from core.users.models import User
        referred_users = User.objects.filter(referred_by=referrer)
        
        # Also check bookings with referrer's code
        from core.booking.models import Booking
        booking_users = User.objects.filter(
            bookings__referred_by=referrer
        )
        
        # Combine both sets
        all_referred_users = (referred_users | booking_users).distinct()
        
        pending_users = []
        for user in all_referred_users:
            try:
                user_node = BinaryNode.objects.get(user=user)
                # Check if user is in referrer's tree
                is_in_tree = self._is_tree_owner(referrer, user_node)
                if not is_in_tree:
                    pending_users.append({
                        'user_id': user.id,
                        'user_email': user.email,
                        'user_username': user.username,
                        'user_full_name': user.get_full_name(),
                        'has_node': True,
                        'node_id': user_node.id,
                        'in_tree': False
                    })
                # If in tree, don't include (already placed)
            except BinaryNode.DoesNotExist:
                # User doesn't have a node yet
                pending_users.append({
                    'user_id': user.id,
                    'user_email': user.email,
                    'user_username': user.username,
                    'user_full_name': user.get_full_name(),
                    'has_node': False,
                    'node_id': None,
                    'in_tree': False
                })
        
        # Try to get binary node and tree structure
        try:
            # Optimize query with select_related for user and wallet
            node = BinaryNode.objects.select_related(
                'user', 'user__wallet', 'parent', 'parent__user'
            ).get(user=request.user)
            
            # Parse query parameters with defaults
            try:
                max_depth = int(request.query_params.get('max_depth', 5))
            except (ValueError, TypeError):
                max_depth = 5
            
            try:
                min_depth = int(request.query_params.get('min_depth', 0))
            except (ValueError, TypeError):
                min_depth = 0
            
            # Parse side filter (left, right, both)
            side_filter = request.query_params.get('side', 'both').lower()
            if side_filter not in ['left', 'right', 'both']:
                side_filter = 'both'
            
            # Parse pagination parameters (optional - if not provided, returns all members for backward compatibility)
            page = request.query_params.get('page')
            page_size = request.query_params.get('page_size')
            
            if page:
                try:
                    page = int(page)
                except (ValueError, TypeError):
                    page = None
            
            if page_size:
                try:
                    page_size = int(page_size)
                    # Enforce max page_size of 100
                    if page_size > 100:
                        page_size = 100
                    if page_size < 1:
                        page_size = None
                    # If page_size is provided but page is not, default to page 1
                    elif page is None:
                        page = 1
                except (ValueError, TypeError):
                    page_size = None
            
            # Validate depth parameters
            if min_depth < 0:
                min_depth = 0
            if max_depth < 1:
                max_depth = 5
            if min_depth > max_depth:
                min_depth = 0
            
            # When pagination is enabled, limit max_depth to prevent fetching thousands of descendants
            # Batch queries are efficient, but fetching 10,000+ nodes still takes time
            # We use stored counts for accurate pagination metadata, so we don't need ALL descendants
            effective_max_depth = max_depth
            if page is not None and page_size is not None:
                # Limit to reasonable depth (10 levels) when pagination is enabled
                # This prevents fetching thousands of nodes while still showing deep trees
                # Count uses stored counts, so pagination metadata is accurate regardless
                effective_max_depth = min(max_depth, 10)
            
            serializer = BinaryTreeNodeSerializer(
                node,
                max_depth=effective_max_depth,
                min_depth=min_depth,
                current_depth=0,
                side_filter=side_filter,
                page=page,
                page_size=page_size,
                request=request
            )
            
            # Include pending_users in the response
            response_data = serializer.data
            response_data['pending_users'] = pending_users
            
            return Response(response_data)
        except BinaryNode.DoesNotExist:
            # No binary node found, but still return pending users
            return Response({
                'message': 'No binary node found',
                'pending_users': pending_users
            }, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response(
                {'error': f'Invalid parameter: {str(e)}', 'pending_users': pending_users},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'])
    def place_user(self, request):
        """
        Manually place a user in a specific position in the binary tree
        Only the tree owner (referrer) can place users
        """
        target_user_id = request.data.get('target_user_id')
        parent_node_id = request.data.get('parent_node_id')
        side = request.data.get('side')
        allow_replacement = request.data.get('allow_replacement', False)
        
        # Validate required fields
        if not target_user_id or not parent_node_id or not side:
            return Response(
                {'error': 'target_user_id, parent_node_id, and side are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if side not in ['left', 'right']:
            return Response(
                {'error': "side must be 'left' or 'right'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from core.users.models import User
            target_user = User.objects.get(id=target_user_id)
            parent_node = BinaryNode.objects.get(id=parent_node_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'Target user not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except BinaryNode.DoesNotExist:
            return Response(
                {'error': 'Parent node not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if current user owns the tree containing parent_node
        if not self._is_tree_owner(request.user, parent_node):
            raise PermissionDenied(
                "You can only place users in your own binary tree"
            )
        
        # Check if target_user is eligible to be placed
        if not self._can_place_user(request.user, target_user):
            return Response(
                {'error': 'This user did not use your referral code and cannot be placed in your tree'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if user has successful payment before allowing placement
        from core.booking.models import Payment
        has_payment = Payment.objects.filter(
            user=target_user,
            status='completed'
        ).exists()
        
        if not has_payment:
            return Response(
                {'error': 'User must have at least one successful payment before placement'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Place the user
        try:
            from .utils import place_user_manually, process_direct_user_commission
            node = place_user_manually(
                user=target_user,
                parent_node=parent_node,
                side=side,
                allow_replacement=allow_replacement
            )
            
            # Process commission after placement (commission only paid if payment was completed)
            commission_paid = process_direct_user_commission(request.user, target_user)
            
            serializer = BinaryNodeSerializer(node)
            response_data = serializer.data
            response_data['commission_paid'] = commission_paid
            return Response(response_data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'])
    def move_user(self, request):
        """
        Move a direct child to a new side (left or right) under the same parent
        Only allows moving direct children (not descendants)
        Only the tree owner can move users in their tree
        """
        node_id = request.data.get('node_id')
        new_side = request.data.get('new_side')
        
        # Validate required fields
        if not node_id or not new_side:
            return Response(
                {'error': 'node_id and new_side are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if new_side not in ['left', 'right']:
            return Response(
                {'error': "new_side must be 'left' or 'right'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            node = BinaryNode.objects.get(id=node_id)
        except BinaryNode.DoesNotExist:
            return Response(
                {'error': 'Node not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if current user owns the tree containing the node
        if not self._is_tree_owner(request.user, node):
            raise PermissionDenied(
                "You can only move users in your own binary tree"
            )
        
        # Only allow moving direct children (parent must be current user's node)
        try:
            owner_node = BinaryNode.objects.get(user=request.user)
        except BinaryNode.DoesNotExist:
            return Response(
                {'error': 'No binary node found for current user'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if node is a direct child of owner
        if node.parent != owner_node:
            return Response(
                {'error': 'You can only move your direct children. This user is not a direct child.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if trying to move to the same side
        if node.side == new_side:
            return Response(
                {'error': f'User is already on the {new_side} side'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if new side is available (exclude the node being moved)
        existing_on_new_side = BinaryNode.objects.filter(
            parent=owner_node, 
            side=new_side
        ).exclude(id=node.id).first()
        
        if existing_on_new_side:
            return Response(
                {'error': f'{new_side.capitalize()} side is already occupied'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Move the node to new side
        try:
            with transaction.atomic():
                old_side = node.side
                node.side = new_side
                node.save(update_fields=['side'])
                
                # Recalculate parent's counts properly (don't swap, recalculate from actual data)
                owner_node.update_counts()
                
                serializer = BinaryNodeSerializer(node)
                return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': f'Error moving user: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'])
    def available_positions(self, request):
        """
        List available positions in the current user's binary tree
        Returns nodes that have available left or right slots
        """
        try:
            owner_node = BinaryNode.objects.get(user=request.user)
        except BinaryNode.DoesNotExist:
            return Response(
                {'message': 'No binary node found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get all nodes in the tree (descendants of owner)
        all_nodes = [owner_node]
        queue = [owner_node]
        
        while queue:
            current = queue.pop(0)
            children = BinaryNode.objects.filter(parent=current)
            for child in children:
                all_nodes.append(child)
                queue.append(child)
        
        # Find nodes with available positions
        available_positions = []
        for node in all_nodes:
            left_available = not BinaryNode.objects.filter(parent=node, side='left').exists()
            right_available = not BinaryNode.objects.filter(parent=node, side='right').exists()
            
            if left_available or right_available:
                # Get referral code that was used by this user (if any)
                referral_code_used = None
                if node.user and node.user.referred_by:
                    referral_code_used = node.user.referred_by.referral_code
                
                available_positions.append({
                    'node_id': node.id,
                    'user_id': node.user.id,
                    'user_email': node.user.email,
                    'user_username': node.user.username,
                    'user_full_name': node.user.get_full_name() if node.user else None,
                    'referral_code': node.user.referral_code if node.user else None,
                    'referral_code_used': referral_code_used,
                    'level': node.level,
                    'left_available': left_available,
                    'right_available': right_available,
                    'left_count': node.left_count,
                    'right_count': node.right_count,
                })
        
        return Response({
            'count': len(available_positions),
            'available_positions': available_positions
        })
    
    @action(detail=False, methods=['get'])
    def pending_users(self, request):
        """
        List users who used referrer's code but are not yet placed in the tree
        or are placed but not in referrer's tree
        """
        referrer = request.user
        
        # Get users who have referred_by = referrer
        from core.users.models import User
        referred_users = User.objects.filter(referred_by=referrer)
        
        # Also check bookings with referrer's code
        from core.booking.models import Booking
        booking_users = User.objects.filter(
            bookings__referred_by=referrer
        )
        
        # Combine both sets
        all_referred_users = (referred_users | booking_users).distinct()
        
        pending_users = []
        for user in all_referred_users:
            try:
                user_node = BinaryNode.objects.get(user=user)
                # Check if user is in referrer's tree
                is_in_tree = self._is_tree_owner(referrer, user_node)
                if not is_in_tree:
                    pending_users.append({
                        'user_id': user.id,
                        'user_email': user.email,
                        'user_username': user.username,
                        'user_full_name': user.get_full_name(),
                        'has_node': True,
                        'node_id': user_node.id,
                        'in_tree': False
                    })
                # If in tree, don't include (already placed)
            except BinaryNode.DoesNotExist:
                # User doesn't have a node yet
                pending_users.append({
                    'user_id': user.id,
                    'user_email': user.email,
                    'user_username': user.username,
                    'user_full_name': user.get_full_name(),
                    'has_node': False,
                    'node_id': None,
                    'in_tree': False
                })
        
        return Response({
            'count': len(pending_users),
            'pending_users': pending_users
        })
    
    @action(detail=False, methods=['post'])
    def auto_place_pending(self, request):
        """
        Automatically place pending users in the binary tree using left-priority algorithm
        Can place all pending users or a specific user
        """
        referrer = request.user
        target_user_id = request.data.get('target_user_id')
        referring_user_id = request.data.get('referring_user_id')
        
        # Get users who have referred_by = referrer
        from core.users.models import User
        from core.booking.models import Booking
        from .utils import add_to_binary_tree
        
        referred_users = User.objects.filter(referred_by=referrer)
        booking_users = User.objects.filter(
            bookings__referred_by=referrer
        )
        
        # Combine both sets
        all_referred_users = (referred_users | booking_users).distinct()
        
        # Filter to specific user if target_user_id provided
        if target_user_id:
            try:
                all_referred_users = all_referred_users.filter(id=target_user_id)
                if not all_referred_users.exists():
                    return Response(
                        {'error': f'User {target_user_id} not found or did not use your referral code'},
                        status=status.HTTP_404_NOT_FOUND
                    )
            except ValueError:
                return Response(
                    {'error': 'Invalid target_user_id'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # If no pending users found
        if not all_referred_users.exists():
            return Response({
                'placed_count': 0,
                'failed_count': 0,
                'placed_users': [],
                'failed_users': [],
                'message': 'No pending users found'
            })
        
        placed_users = []
        failed_users = []
        
        for user in all_referred_users:
            try:
                # IMPORTANT: Check if user has successful payment before allowing placement
                from core.booking.models import Payment
                has_payment = Payment.objects.filter(
                    user=user,
                    status='completed'
                ).exists()
                
                if not has_payment:
                    failed_users.append({
                        'user_id': user.id,
                        'user_email': user.email,
                        'user_full_name': user.get_full_name() or user.username,
                        'error': 'User must have at least one successful payment before placement'
                    })
                    continue
                
                # Check if user is already in referrer's tree
                try:
                    user_node = BinaryNode.objects.get(user=user)
                    is_in_tree = self._is_tree_owner(referrer, user_node)
                    if is_in_tree:
                        # User already in tree, skip
                        continue
                except BinaryNode.DoesNotExist:
                    # User doesn't have a node, will create one
                    pass
                
                # Determine actual referrer (from user.referred_by or booking.referred_by)
                actual_referrer = referring_user_id
                if not actual_referrer:
                    # Try to get from user.referred_by first
                    if user.referred_by:
                        actual_referrer = user.referred_by.id
                    else:
                        # Get from first booking
                        booking = Booking.objects.filter(user=user, referred_by=referrer).first()
                        if booking and booking.referred_by:
                            actual_referrer = booking.referred_by.id
                    
                    # If still no referrer, use the main referrer (request.user)
                    if not actual_referrer:
                        actual_referrer = referrer.id
                
                # Convert to User object if needed
                if isinstance(actual_referrer, int):
                    actual_referrer_user = User.objects.get(id=actual_referrer)
                else:
                    actual_referrer_user = actual_referrer
                
                # If user already has a node but not in referrer's tree, we need to handle it
                # For now, we'll try to place it - add_to_binary_tree will create if not exists
                # or we can move it manually if needed
                user_node = BinaryNode.objects.filter(user=user).first()
                if user_node and not self._is_tree_owner(referrer, user_node):
                    # User has a node but not in referrer's tree
                    # We'll place them in referrer's tree (the node will be moved/re-parented)
                    # Note: This might require additional logic for moving existing nodes
                    # For now, we'll use add_to_binary_tree which should handle creation
                    pass
                
                # Place user in binary tree using automatic placement algorithm
                node = add_to_binary_tree(
                    user=user,
                    referrer=referrer,
                    side=None,  # Let algorithm determine side automatically
                    referring_user=actual_referrer_user if actual_referrer_user != referrer else referrer
                )
                
                if node:
                    # Process commission after placement (commission only paid if payment was completed)
                    from .utils import process_direct_user_commission
                    commission_paid = process_direct_user_commission(referrer, user)
                    
                    placed_users.append({
                        'user_id': user.id,
                        'user_email': user.email,
                        'user_full_name': user.get_full_name() or user.username,
                        'node_id': node.id,
                        'parent_node_id': node.parent.id if node.parent else None,
                        'parent_email': node.parent.user.email if node.parent else None,
                        'side': node.side,
                        'level': node.level,
                        'commission_paid': commission_paid
                    })
                else:
                    failed_users.append({
                        'user_id': user.id,
                        'user_email': user.email,
                        'user_full_name': user.get_full_name() or user.username,
                        'error': 'Failed to place user in binary tree'
                    })
            except Exception as e:
                # Log error and add to failed list
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error placing user {user.id} in binary tree: {str(e)}")
                failed_users.append({
                    'user_id': user.id,
                    'user_email': user.email,
                    'user_full_name': user.get_full_name() or user.username,
                    'error': str(e)
                })
        
        response_data = {
            'placed_count': len(placed_users),
            'failed_count': len(failed_users),
            'placed_users': placed_users,
            'failed_users': failed_users
        }
        
        if len(placed_users) == 0 and len(failed_users) == 0:
            response_data['message'] = 'No eligible pending users found to place'
        
        return Response(response_data, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['post'])
    def swap_direct_children(self, request):
        """
        Swap left and right direct children of current user's node
        Only tree owner can swap their direct children
        Preserves all descendant nodes (they move with their parent)
        """
        try:
            owner_node = BinaryNode.objects.get(user=request.user)
        except BinaryNode.DoesNotExist:
            return Response(
                {'error': 'No binary node found for current user'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get direct children
        left_child = BinaryNode.objects.filter(parent=owner_node, side='left').first()
        right_child = BinaryNode.objects.filter(parent=owner_node, side='right').first()
        
        # Both children must exist to swap
        if not left_child or not right_child:
            return Response(
                {'error': 'Both left and right children must exist to swap'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Swap sides
        try:
            with transaction.atomic():
                # Update left child to right
                left_child.side = 'right'
                left_child.save(update_fields=['side'])
                
                # Update right child to left
                right_child.side = 'left'
                right_child.save(update_fields=['side'])
                
                # Update counts (swap left_count and right_count)
                owner_node.left_count, owner_node.right_count = owner_node.right_count, owner_node.left_count
                owner_node.save(update_fields=['left_count', 'right_count'])
                
                # Return updated tree structure
                serializer = BinaryNodeSerializer(owner_node)
                return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': f'Error swapping children: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'])
    def choose_side_for_direct_referral(self, request):
        """
        Pre-select side for an upcoming direct referral
        Parent can choose left/right for their direct referrals
        Only works for users who haven't been placed yet
        """
        target_user_id = request.data.get('target_user_id')
        side = request.data.get('side')
        
        # Validate required fields
        if not target_user_id or not side:
            return Response(
                {'error': 'target_user_id and side are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if side not in ['left', 'right']:
            return Response(
                {'error': "side must be 'left' or 'right'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from core.users.models import User
            target_user = User.objects.get(id=target_user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'Target user not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if user is eligible to be placed (used referrer's code)
        if not self._can_place_user(request.user, target_user):
            return Response(
                {'error': 'This user did not use your referral code'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if user already has a node
        try:
            existing_node = BinaryNode.objects.get(user=target_user)
            # If node exists and is already in referrer's tree, return error
            if self._is_tree_owner(request.user, existing_node):
                return Response(
                    {'error': 'User is already placed in your tree'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except BinaryNode.DoesNotExist:
            pass  # User doesn't have a node yet, that's fine
        
        try:
            owner_node = BinaryNode.objects.get(user=request.user)
        except BinaryNode.DoesNotExist:
            return Response(
                {'error': 'No binary node found for current user'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if the requested side is available (use direct database check, not cached count)
        existing_on_side = BinaryNode.objects.filter(parent=owner_node, side=side).exists()
        if existing_on_side:
            return Response(
                {'error': f'{side.capitalize()} side is already occupied'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Place user on the chosen side
        try:
            from .utils import place_user_manually
            node = place_user_manually(
                user=target_user,
                parent_node=owner_node,
                side=side,
                allow_replacement=False
            )
            serializer = BinaryNodeSerializer(node)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class BinaryPairViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Binary Pair viewing
    """
    queryset = BinaryPair.objects.all()
    serializer_class = BinaryPairSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return BinaryPair.objects.all()
        return BinaryPair.objects.filter(user=user)
    
    @action(detail=False, methods=['post'])
    def check_pairs(self, request):
        """Manually trigger pair checking"""
        pair = check_and_create_pair(request.user)
        if pair:
            serializer = self.get_serializer(pair)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response({'message': 'No pairs available'}, status=status.HTTP_200_OK)


class BinaryEarningViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Binary Earning viewing
    """
    queryset = BinaryEarning.objects.all()
    serializer_class = BinaryEarningSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return BinaryEarning.objects.all()
        return BinaryEarning.objects.filter(user=user)

