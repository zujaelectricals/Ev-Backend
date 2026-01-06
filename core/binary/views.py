from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import BinaryNode, BinaryPair, BinaryEarning
from .serializers import BinaryNodeSerializer, BinaryPairSerializer, BinaryEarningSerializer
from .utils import check_and_create_pair


class BinaryNodeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Binary Node viewing
    """
    queryset = BinaryNode.objects.all()
    serializer_class = BinaryNodeSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return BinaryNode.objects.all()
        return BinaryNode.objects.filter(user=user)
    
    @action(detail=False, methods=['get'])
    def my_tree(self, request):
        """Get current user's binary tree info"""
        try:
            node = BinaryNode.objects.get(user=request.user)
            serializer = self.get_serializer(node)
            return Response(serializer.data)
        except BinaryNode.DoesNotExist:
            return Response({'message': 'No binary node found'}, status=status.HTTP_404_NOT_FOUND)


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

