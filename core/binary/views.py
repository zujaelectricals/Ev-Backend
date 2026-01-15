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
        """Get full binary tree structure with all children"""
        try:
            # Optimize query with select_related for user and wallet
            node = BinaryNode.objects.select_related(
                'user', 'user__wallet', 'parent', 'parent__user'
            ).get(user=request.user)
            max_depth = int(request.query_params.get('max_depth', 5))
            
            serializer = BinaryTreeNodeSerializer(
                node,
                max_depth=max_depth,
                current_depth=0
            )
            return Response(serializer.data)
        except BinaryNode.DoesNotExist:
            return Response(
                {'message': 'No binary node found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except ValueError:
            return Response(
                {'error': 'Invalid max_depth parameter'},
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
        
        # Place the user
        try:
            from .utils import place_user_manually
            node = place_user_manually(
                user=target_user,
                parent_node=parent_node,
                side=side,
                allow_replacement=allow_replacement
            )
            serializer = BinaryNodeSerializer(node)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'])
    def move_user(self, request):
        """
        Move an existing user to a new position in the binary tree
        Only the tree owner can move users in their tree
        """
        node_id = request.data.get('node_id')
        new_parent_node_id = request.data.get('new_parent_node_id')
        new_side = request.data.get('new_side')
        
        # Validate required fields
        if not node_id or not new_parent_node_id or not new_side:
            return Response(
                {'error': 'node_id, new_parent_node_id, and new_side are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if new_side not in ['left', 'right']:
            return Response(
                {'error': "new_side must be 'left' or 'right'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            node = BinaryNode.objects.get(id=node_id)
            new_parent = BinaryNode.objects.get(id=new_parent_node_id)
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
        
        # Check if new_parent is in the same tree
        if not self._is_tree_owner(request.user, new_parent):
            raise PermissionDenied(
                "New parent must be in your binary tree"
            )
        
        # Validate no cycles
        try:
            self._validate_no_cycles(node, new_parent)
        except ValidationError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Move the node
        try:
            from .utils import move_binary_node
            moved_node = move_binary_node(node, new_parent, new_side)
            serializer = BinaryNodeSerializer(moved_node)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response(
                {'error': str(e)},
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
                available_positions.append({
                    'node_id': node.id,
                    'user_id': node.user.id,
                    'user_email': node.user.email,
                    'user_username': node.user.username,
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
        ).distinct()
        
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

