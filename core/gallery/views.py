from rest_framework import viewsets, status
from rest_framework.permissions import AllowAny, IsAuthenticated, BasePermission
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from django.db.models import Q
from .models import GalleryItem
from .serializers import GalleryItemSerializer


class IsAdminOrStaffOrPublicReadOnly(BasePermission):
    """
    Custom permission class:
    - Read operations (GET, HEAD, OPTIONS): All users (authenticated and unauthenticated)
    - Write operations (POST, PUT, PATCH, DELETE): Only admin/staff/superuser
    """
    def has_permission(self, request, view):
        # Allow read operations for all users (including unauthenticated)
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return True
        
        # Write operations require admin, staff, or superuser
        return (
            request.user and
            request.user.is_authenticated and
            (request.user.is_superuser or request.user.role in ['admin', 'staff'])
        )


class GalleryItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Gallery Item management
    
    Permissions:
    - All users (authenticated and unauthenticated) can view gallery items (list, retrieve)
    - Only admin/staff/superuser can create, update, delete gallery items
    """
    queryset = GalleryItem.objects.all()
    serializer_class = GalleryItemSerializer
    permission_classes = [IsAdminOrStaffOrPublicReadOnly]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']
    
    def get_queryset(self):
        """
        Filter queryset based on user permissions and query params
        - Public users: Only see active items (status=True)
        - Admin/Staff: Can see all items (can filter by status via query param)
        - Support filtering by level via query param
        """
        queryset = GalleryItem.objects.select_related('created_by').all()
        
        # Check if user is admin/staff
        user = self.request.user
        is_admin_or_staff = (
            user and
            user.is_authenticated and
            (user.is_superuser or getattr(user, 'role', None) in ['admin', 'staff'])
        )
        
        # If not admin/staff, only show active items
        if not is_admin_or_staff:
            queryset = queryset.filter(status=True)
        
        # Filter by level if provided
        level = self.request.query_params.get('level', None)
        if level:
            queryset = queryset.filter(level=level)
        
        # Filter by status if provided (for admin/staff)
        status_param = self.request.query_params.get('status', None)
        if status_param is not None and is_admin_or_staff:
            status_bool = status_param.lower() in ['true', '1', 'yes']
            queryset = queryset.filter(status=status_bool)
        
        return queryset.order_by('level', 'order', 'created_at')
    
    def perform_create(self, serializer):
        """Set created_by to the current user"""
        serializer.save(created_by=self.request.user)
    
    def perform_update(self, serializer):
        """Allow update - permission already checked by permission class"""
        serializer.save()
    
    def perform_destroy(self, instance):
        """Allow delete - permission already checked by permission class"""
        instance.delete()

