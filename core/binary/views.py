from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.pagination import PageNumberPagination
from django.db import transaction
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from decimal import Decimal
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
        
        # If node is the owner node itself, return True
        if node.id == owner_node.id:
            return True
        
        # Use recursive CTE to get all ancestors efficiently in a single query
        # This avoids N+1 query problem and prevents timeouts
        from django.db import connection
        
        try:
            with connection.cursor() as cursor:
                # Use recursive CTE to get all ancestors up to a maximum depth
                # Maximum depth of 100 levels to prevent infinite loops
                cursor.execute("""
                    WITH RECURSIVE ancestors AS (
                        SELECT id, parent_id, 0 as depth
                        FROM binary_nodes WHERE id = %s
                        UNION ALL
                        SELECT bn.id, bn.parent_id, a.depth + 1
                        FROM binary_nodes bn
                        INNER JOIN ancestors a ON bn.id = a.parent_id
                        WHERE a.depth < 100 AND a.parent_id IS NOT NULL
                    )
                    SELECT id FROM ancestors WHERE id = %s
                """, [node.id, owner_node.id])
                
                result = cursor.fetchone()
                return result is not None
        except Exception as e:
            # Fallback to simple traversal with depth limit if CTE fails
            # This handles edge cases and database compatibility
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"CTE query failed in _is_tree_owner, using fallback: {str(e)}")
            
            # Fallback: traverse with depth limit and proper error handling
            current = node
            max_depth = 100
            depth = 0
            
            while current and depth < max_depth:
                if current.id == owner_node.id:
                    return True
                try:
                    # Use select_related if possible, but we need to fetch fresh
                    # to avoid stale data issues
                    if current.parent_id:
                        current = BinaryNode.objects.select_related('parent').get(id=current.parent_id)
                    else:
                        current = None
                except BinaryNode.DoesNotExist:
                    current = None
                except Exception as e:
                    logger.error(f"Error accessing parent in _is_tree_owner: {str(e)}")
                    return False
                depth += 1
            
            return False
    
    def _is_ancestor(self, ancestor_user, descendant_node):
        """
        Check if ancestor_user is an ancestor of the node (i.e., if the node is a descendant of ancestor_user)
        This is the reverse of _is_tree_owner - checks if ancestor_user's node is in the ancestor chain of descendant_node
        """
        try:
            ancestor_node = BinaryNode.objects.get(user=ancestor_user)
        except BinaryNode.DoesNotExist:
            return False
        
        # If the descendant node is the ancestor node itself, return False (not an ancestor, it's the same node)
        if descendant_node.id == ancestor_node.id:
            return False
        
        # Use recursive CTE to check if ancestor_node is in the ancestor chain of descendant_node
        from django.db import connection
        
        try:
            with connection.cursor() as cursor:
                # Get all ancestors of descendant_node and check if ancestor_node is among them
                cursor.execute("""
                    WITH RECURSIVE ancestors AS (
                        SELECT id, parent_id, 0 as depth
                        FROM binary_nodes WHERE id = %s
                        UNION ALL
                        SELECT bn.id, bn.parent_id, a.depth + 1
                        FROM binary_nodes bn
                        INNER JOIN ancestors a ON bn.id = a.parent_id
                        WHERE a.depth < 100 AND a.parent_id IS NOT NULL
                    )
                    SELECT id FROM ancestors WHERE id = %s
                """, [descendant_node.id, ancestor_node.id])
                
                result = cursor.fetchone()
                return result is not None
        except Exception as e:
            # Fallback to simple traversal with depth limit if CTE fails
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"CTE query failed in _is_ancestor, using fallback: {str(e)}")
            
            # Fallback: traverse up from descendant_node to see if we reach ancestor_node
            current = descendant_node
            max_depth = 100
            depth = 0
            
            while current and depth < max_depth:
                if current.parent_id == ancestor_node.id:
                    return True
                try:
                    if current.parent_id:
                        current = BinaryNode.objects.select_related('parent').get(id=current.parent_id)
                    else:
                        current = None
                except BinaryNode.DoesNotExist:
                    current = None
                except Exception as e:
                    logger.error(f"Error accessing parent in _is_ancestor: {str(e)}")
                    return False
                depth += 1
            
            return False
    
    def _can_place_user(self, referrer, target_user):
        """Check if target_user can be placed in referrer's tree"""
        from .utils import can_user_be_placed
        return can_user_be_placed(referrer, target_user)
    
    def _validate_no_cycles(self, node, new_parent):
        """Validate that moving node to new_parent won't create a cycle"""
        if node == new_parent:
            raise ValidationError("Cannot move node to itself")
        
        # Check if new_parent is a descendant of node using efficient query
        # Use recursive CTE to get all ancestors of new_parent and check if node is in that set
        from django.db import connection
        
        try:
            with connection.cursor() as cursor:
                # Use recursive CTE to get all ancestors of new_parent
                cursor.execute("""
                    WITH RECURSIVE ancestors AS (
                        SELECT id, parent_id, 0 as depth
                        FROM binary_nodes WHERE id = %s
                        UNION ALL
                        SELECT bn.id, bn.parent_id, a.depth + 1
                        FROM binary_nodes bn
                        INNER JOIN ancestors a ON bn.id = a.parent_id
                        WHERE a.depth < 100 AND a.parent_id IS NOT NULL
                    )
                    SELECT id FROM ancestors WHERE id = %s
                """, [new_parent.id, node.id])
                
                result = cursor.fetchone()
                if result:
                    raise ValidationError("Cannot move node to its own descendant (would create cycle)")
        except ValidationError:
            raise
        except Exception as e:
            # Fallback to simple traversal with depth limit if CTE fails
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"CTE query failed in _validate_no_cycles, using fallback: {str(e)}")
            
            current = new_parent
            max_depth = 100
            depth = 0
            
            while current and depth < max_depth:
                if current.id == node.id:
                    raise ValidationError("Cannot move node to its own descendant (would create cycle)")
                try:
                    if current.parent_id:
                        current = BinaryNode.objects.select_related('parent').get(id=current.parent_id)
                    else:
                        current = None
                except BinaryNode.DoesNotExist:
                    current = None
                except Exception as e:
                    logger.error(f"Error accessing parent in _validate_no_cycles: {str(e)}")
                    # If we can't verify, err on the side of caution and allow the operation
                    # (This prevents blocking valid operations due to transient DB issues)
                    break
                depth += 1
        
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
    
    def _get_all_descendant_node_ids(self, node):
        """
        Get all descendant node IDs using a single recursive CTE query for efficiency.
        Returns a set of node IDs that are descendants of the given node.
        """
        from django.db import connection
        
        with connection.cursor() as cursor:
            # Use recursive CTE to get all descendants efficiently
            cursor.execute("""
                WITH RECURSIVE descendants AS (
                    SELECT id FROM binary_nodes WHERE parent_id = %s
                    UNION ALL
                    SELECT bn.id FROM binary_nodes bn
                    INNER JOIN descendants d ON bn.parent_id = d.id
                )
                SELECT id FROM descendants
            """, [node.id])
            return set(row[0] for row in cursor.fetchall())
    
    def _search_tree_members(self, user_node, search_query):
        """
        Search for users in the tree by fullname (first_name + last_name).
        Uses optimized database query to find matching users efficiently.
        
        Args:
            user_node: The root BinaryNode of the user's tree
            search_query: Search string to match against fullname
            
        Returns:
            List of matching user details with their tree position
        """
        from core.users.models import User
        from django.db.models import Value, CharField
        from django.db.models.functions import Concat, Lower
        
        # Get all descendant node IDs efficiently using CTE
        descendant_ids = self._get_all_descendant_node_ids(user_node)
        
        if not descendant_ids:
            return []
        
        # Search users by fullname (case-insensitive) within the tree
        # Using annotate to create a searchable fullname field
        search_lower = search_query.lower().strip()
        
        matching_nodes = BinaryNode.objects.filter(
            id__in=descendant_ids
        ).select_related(
            'user', 'user__wallet', 'parent', 'parent__user'
        ).annotate(
            full_name_lower=Lower(Concat(
                'user__first_name',
                Value(' '),
                'user__last_name',
                output_field=CharField()
            ))
        ).filter(
            Q(full_name_lower__icontains=search_lower) |
            Q(user__first_name__icontains=search_lower) |
            Q(user__last_name__icontains=search_lower) |
            Q(user__username__icontains=search_lower) |
            Q(user__email__icontains=search_lower)
        )[:50]  # Limit to 50 results for performance
        
        # Build search results
        search_results = []
        for node in matching_nodes:
            if not node.user:
                continue
            
            # Determine which side of the tree this node is on (relative to user_node)
            tree_side = self._get_tree_side(user_node, node)
            
            search_results.append({
                'node_id': node.id,
                'user_id': node.user.id,
                'user_email': node.user.email,
                'user_username': node.user.username,
                'user_full_name': node.user.get_full_name() or node.user.username,
                'user_mobile': node.user.mobile,
                'user_first_name': node.user.first_name,
                'user_last_name': node.user.last_name,
                'user_city': node.user.city,
                'user_state': node.user.state,
                'is_distributor': node.user.is_distributor,
                'is_active_buyer': node.user.is_active_buyer,
                'referral_code': node.user.referral_code,
                'date_joined': node.user.date_joined,
                'parent_id': node.parent.id if node.parent else None,
                'parent_name': node.parent.user.get_full_name() if node.parent and node.parent.user else None,
                'side': node.side,
                'tree_side': tree_side,  # Which side of the root tree (left/right)
                'level': node.level,
                'left_count': node.left_count,
                'right_count': node.right_count,
                'total_descendants': node.left_count + node.right_count,
                'binary_commission_activated': node.binary_commission_activated,
                'created_at': node.created_at,
            })
        
        return search_results
    
    def _get_tree_side(self, root_node, target_node):
        """
        Determine which side (left/right) of the root tree the target node is on.
        Traverses up from target_node until reaching a direct child of root_node.
        Uses efficient query to avoid N+1 problem.
        """
        # If target_node is direct child of root_node, return its side
        if target_node.parent_id == root_node.id:
            return target_node.side
        
        # Use recursive CTE to find the direct child of root_node in the ancestor chain
        from django.db import connection
        
        try:
            with connection.cursor() as cursor:
                # Find the direct child of root_node in the ancestor chain of target_node
                cursor.execute("""
                    WITH RECURSIVE ancestors AS (
                        SELECT id, parent_id, side, 0 as depth
                        FROM binary_nodes WHERE id = %s
                        UNION ALL
                        SELECT bn.id, bn.parent_id, bn.side, a.depth + 1
                        FROM binary_nodes bn
                        INNER JOIN ancestors a ON bn.id = a.parent_id
                        WHERE a.depth < 100 AND a.parent_id IS NOT NULL
                    )
                    SELECT side FROM ancestors WHERE parent_id = %s LIMIT 1
                """, [target_node.id, root_node.id])
                
                result = cursor.fetchone()
                if result:
                    return result[0]
        except Exception as e:
            # Fallback to simple traversal with depth limit
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"CTE query failed in _get_tree_side, using fallback: {str(e)}")
            
            current = target_node
            max_depth = 100
            depth = 0
            
            while current and current.parent and depth < max_depth:
                if current.parent_id == root_node.id:
                    return current.side
                try:
                    if current.parent_id:
                        current = BinaryNode.objects.select_related('parent').get(id=current.parent_id)
                    else:
                        current = None
                except BinaryNode.DoesNotExist:
                    current = None
                except Exception as e:
                    logger.error(f"Error accessing parent in _get_tree_side: {str(e)}")
                    return None
                depth += 1
        
        return None
    
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
            # Skip if user is the referrer themselves
            if user.id == referrer.id:
                continue
            
            # Check if user is the referrer's parent (via User.referred_by)
            # This check works regardless of whether BinaryNodes exist
            # A parent cannot be placed as a child of their own child
            if referrer.referred_by and referrer.referred_by.id == user.id:
                continue
            
            try:
                # Use select_related to prefetch parent relationship
                # This helps with the fallback case in _is_tree_owner
                user_node = BinaryNode.objects.select_related('parent').get(user=user)
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
                # Parent check already done above, so safe to add to pending
                pending_users.append({
                    'user_id': user.id,
                    'user_email': user.email,
                    'user_username': user.username,
                    'user_full_name': user.get_full_name(),
                    'has_node': False,
                    'node_id': None,
                    'in_tree': False
                })
        
        # Check for search parameter
        search_query = request.query_params.get('search', '').strip()
        
        # Try to get binary node and tree structure
        try:
            from django.db.models import Prefetch
            
            # Optimize query with select_related and prefetch_related for direct children
            # Prefetch left and right children with their related data
            left_children_prefetch = Prefetch(
                'children',
                queryset=BinaryNode.objects.select_related(
                    'user', 'user__wallet', 'parent', 'parent__user'
                ).filter(side='left'),
                to_attr='left_children_list'
            )
            right_children_prefetch = Prefetch(
                'children',
                queryset=BinaryNode.objects.select_related(
                    'user', 'user__wallet', 'parent', 'parent__user'
                ).filter(side='right'),
                to_attr='right_children_list'
            )
            
            node = BinaryNode.objects.select_related(
                'user', 'user__wallet', 'parent', 'parent__user'
            ).prefetch_related(
                left_children_prefetch,
                right_children_prefetch
            ).get(user=request.user)
            
            # For tree_structure endpoint, we only want direct children (no nested recursion)
            # Set max_depth to 1 to only show direct children
            max_depth = 1
            
            # Parse side filter (left, right, both)
            side_filter = request.query_params.get('side', 'both').lower()
            if side_filter not in ['left', 'right', 'both']:
                side_filter = 'both'
            
            serializer = BinaryTreeNodeSerializer(
                node,
                max_depth=max_depth,
                min_depth=0,
                current_depth=0,
                side_filter=side_filter,
                page=None,  # No pagination for direct children
                page_size=None,
                request=request
            )
            
            # Include pending_users in the response
            response_data = serializer.data
            response_data['pending_users'] = pending_users
            
            # Add search results if search query provided
            if search_query:
                search_results = self._search_tree_members(node, search_query)
                response_data['search_results'] = search_results
                response_data['search_query'] = search_query
                response_data['search_count'] = len(search_results)
            
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
    
    @action(detail=False, methods=['get'])
    def node_children(self, request):
        """
        Get direct left and right children of a specific node (for lazy loading)
        Query parameter: node_id (required)
        Returns only direct children with no nested recursion
        """
        node_id = request.query_params.get('node_id')
        
        if not node_id:
            return Response(
                {'error': 'node_id query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            node_id = int(node_id)
        except (ValueError, TypeError):
            return Response(
                {'error': 'node_id must be a valid integer'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from django.db.models import Prefetch
            
            # Check if user has permission to view this node
            # User can view nodes in their own tree
            try:
                user_node = BinaryNode.objects.get(user=request.user)
            except BinaryNode.DoesNotExist:
                return Response(
                    {'error': 'No binary node found for current user'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Get the requested node
            try:
                target_node = BinaryNode.objects.get(id=node_id)
            except BinaryNode.DoesNotExist:
                return Response(
                    {'error': 'Node not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Check if target node is in user's tree (user must own the tree containing this node)
            if not self._is_tree_owner(request.user, target_node):
                # Allow if user is admin/superuser
                if not (request.user.is_superuser or request.user.role == 'admin'):
                    raise PermissionDenied(
                        "You can only view nodes in your own binary tree"
                    )
            
            # Optimize query with prefetch_related for direct children
            left_children_prefetch = Prefetch(
                'children',
                queryset=BinaryNode.objects.select_related(
                    'user', 'user__wallet', 'parent', 'parent__user'
                ).filter(side='left'),
                to_attr='left_children_list'
            )
            right_children_prefetch = Prefetch(
                'children',
                queryset=BinaryNode.objects.select_related(
                    'user', 'user__wallet', 'parent', 'parent__user'
                ).filter(side='right'),
                to_attr='right_children_list'
            )
            
            node = BinaryNode.objects.select_related(
                'user', 'user__wallet', 'parent', 'parent__user'
            ).prefetch_related(
                left_children_prefetch,
                right_children_prefetch
            ).get(id=node_id)
            
            # Parse side filter (left, right, both)
            side_filter = request.query_params.get('side', 'both').lower()
            if side_filter not in ['left', 'right', 'both']:
                side_filter = 'both'
            
            # Serialize with max_depth=1 to only show direct children
            serializer = BinaryTreeNodeSerializer(
                node,
                max_depth=1,
                min_depth=0,
                current_depth=0,
                side_filter=side_filter,
                page=None,
                page_size=None,
                request=request
            )
            
            # Return only left_child and right_child in response
            response_data = {
                'node_id': node.id,
                'left_child': serializer.data.get('left_child'),
                'right_child': serializer.data.get('right_child')
            }
            
            return Response(response_data)
        except PermissionDenied:
            raise
        except BinaryNode.DoesNotExist:
            return Response(
                {'error': 'Node not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in node_children endpoint: {str(e)}")
            return Response(
                {'error': f'An error occurred: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def place_user(self, request):
        """
        Manually place a user in a specific position in the binary tree
        Only the tree owner (referrer) can place users
        Automatically places on the specified side of the authenticated user's node,
        or traverses down the same-side subtree if the position is occupied.
        """
        target_user_id = request.data.get('target_user_id')
        side = request.data.get('side')
        allow_replacement = request.data.get('allow_replacement', False)
        
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
        
        # Get or create authenticated user's BinaryNode
        # If user doesn't have a node, create one (they become the root of their own tree)
        owner_node, created = BinaryNode.objects.get_or_create(user=request.user)
        
        # Check if target_user is eligible to be placed
        if not self._can_place_user(request.user, target_user):
            return Response(
                {'error': 'This user did not use your referral code and cannot be placed in your tree'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Find the next available position on the specified side
        try:
            from .utils import find_next_available_on_side, place_user_manually, process_direct_user_commission
            parent_node = find_next_available_on_side(owner_node, side)
            
            if not parent_node:
                return Response(
                    {'error': f'No available position found on the {side} side of your tree'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Place the user
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
        
        # Get referrer's node if it exists (to check for ancestors)
        try:
            referrer_node = BinaryNode.objects.get(user=referrer)
        except BinaryNode.DoesNotExist:
            referrer_node = None
        
        pending_users = []
        for user in all_referred_users:
            # Skip if user is the referrer themselves
            if user.id == referrer.id:
                continue
            
            # Check if user is the referrer's parent (via User.referred_by)
            # This check works regardless of whether BinaryNodes exist
            # A parent cannot be placed as a child of their own child
            if referrer.referred_by and referrer.referred_by.id == user.id:
                continue
            
            try:
                # Use select_related to prefetch parent relationship
                # This helps with the fallback case in _is_tree_owner
                user_node = BinaryNode.objects.select_related('parent').get(user=user)
                
                # Check if user is an ancestor of the referrer (parent, grandparent, etc.)
                # If so, exclude them - a parent cannot be placed as a child
                # This check works when both users have BinaryNodes
                if referrer_node and self._is_ancestor(user, referrer_node):
                    continue
                
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
                # Parent check already done above, so safe to add to pending
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
        # Get target_user_id from request body first, then fall back to query parameter
        target_user_id = request.data.get('target_user_id')
        if not target_user_id:
            # Check query parameters as alternative source
            user_id_param = request.query_params.get('user_id')
            if user_id_param:
                try:
                    target_user_id = int(user_id_param)
                except (ValueError, TypeError):
                    return Response(
                        {'error': 'Invalid user_id query parameter. Must be a valid integer.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
        
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
                # Ensure target_user_id is an integer
                if not isinstance(target_user_id, int):
                    target_user_id = int(target_user_id)
                
                all_referred_users = all_referred_users.filter(id=target_user_id)
                if not all_referred_users.exists():
                    return Response(
                        {'error': f'User {target_user_id} not found or did not use your referral code'},
                        status=status.HTTP_404_NOT_FOUND
                    )
            except (ValueError, TypeError):
                return Response(
                    {'error': 'Invalid target_user_id. Must be a valid integer.'},
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
                # Check if user is already in referrer's tree
                try:
                    # Use select_related to prefetch parent relationship
                    # This helps with the fallback case in _is_tree_owner
                    user_node = BinaryNode.objects.select_related('parent').get(user=user)
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
    
    @action(detail=False, methods=['get'])
    def team_members(self, request):
        """
        Get direct team members (children) for a distributor member
        Returns basic details: full_name, email, phone, total_paid, and side
        Supports pagination and side filtering
        Only accessible to users with is_distributor=True
        """
        # Check if user is a distributor
        if not request.user.is_distributor:
            raise PermissionDenied("This endpoint is only available for distributors.")
        
        # Get distributor's binary node
        try:
            distributor_node = BinaryNode.objects.select_related('user').get(user=request.user)
        except BinaryNode.DoesNotExist:
            return Response({
                'error': 'Binary node not found. Please ensure you have a binary tree structure.'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get query parameters
        side_filter = request.query_params.get('side', '').lower()
        page = request.query_params.get('page', '1')
        page_size = request.query_params.get('page_size', '20')
        
        # Validate side filter
        if side_filter and side_filter not in ['left', 'right']:
            return Response(
                {'error': "side must be 'left' or 'right'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate pagination parameters
        try:
            page = int(page)
            if page < 1:
                page = 1
        except (ValueError, TypeError):
            return Response(
                {'error': 'page must be a valid integer'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            page_size = int(page_size)
            if page_size < 1:
                page_size = 20
            if page_size > 100:
                page_size = 100
        except (ValueError, TypeError):
            return Response(
                {'error': 'page_size must be a valid integer'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get direct children only (not all descendants)
        from core.booking.models import Booking
        queryset = BinaryNode.objects.filter(parent=distributor_node).select_related('user')
        
        # Filter by side if provided
        if side_filter:
            queryset = queryset.filter(side=side_filter)
        
        # Annotate with total_paid from bookings for each user
        # Use Coalesce to handle None values (when user has no bookings)
        queryset = queryset.annotate(
            total_paid=Coalesce(Sum('user__bookings__total_paid'), Decimal('0'))
        )
        
        # Order by side (left first) and then by user id for consistency
        queryset = queryset.order_by('side', 'user__id')
        
        # Get total count before pagination
        total_count = queryset.count()
        
        # Calculate pagination
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        total_pages = (total_count + page_size - 1) // page_size  # Ceiling division
        
        # Get paginated results
        paginated_queryset = queryset[start_index:end_index]
        
        # Build response data
        results = []
        for node in paginated_queryset:
            user = node.user
            full_name = user.get_full_name() or user.username or ''
            
            # total_paid is guaranteed to be Decimal('0') or greater due to Coalesce
            total_paid = node.total_paid
            
            results.append({
                'full_name': full_name,
                'email': user.email or '',
                'phone': user.mobile or '',
                'total_paid': str(total_paid),
                'side': node.side or ''
            })
        
        # Build pagination URLs
        base_url = request.build_absolute_uri(request.path)
        query_params = request.GET.copy()
        
        next_url = None
        if page < total_pages:
            query_params['page'] = page + 1
            next_url = f"{base_url}?{query_params.urlencode()}"
        
        previous_url = None
        if page > 1:
            query_params['page'] = page - 1
            previous_url = f"{base_url}?{query_params.urlencode()}"
        
        response_data = {
            'count': total_count,
            'next': next_url,
            'previous': previous_url,
            'page': page,
            'page_size': page_size,
            'results': results
        }
        
        return Response(response_data, status=status.HTTP_200_OK)


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

