from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from django.utils import timezone
from .models import PlatformSettings
from .serializers import PlatformSettingsSerializer


class PlatformSettingsViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Platform Settings management.
    - GET: All authenticated users can read
    - PATCH: Only admin/superuser can update
    """
    queryset = PlatformSettings.objects.all()
    serializer_class = PlatformSettingsSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch', 'options', 'head']
    
    def get_object(self):
        """
        Return the singleton settings instance.
        """
        return PlatformSettings.get_settings()
    
    def list(self, request, *args, **kwargs):
        """
        Return the singleton settings instance as a list with one item.
        Also handles PATCH requests for singleton pattern.
        """
        # Handle PATCH/PUT on list endpoint (singleton pattern)
        if request.method in ['PATCH', 'PUT']:
            return self.update(request, *args, **kwargs)
        
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
    
    def retrieve(self, request, *args, **kwargs):
        """
        Return the singleton settings instance.
        """
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
    
    def update(self, request, *args, **kwargs):
        """
        Update settings. Only admin/superuser can update.
        """
        # Check if user is admin or superuser
        if not (request.user.is_superuser or request.user.role == 'admin'):
            raise PermissionDenied('Only admin or superuser can update platform settings.')
        
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        # Set updated_by to current user
        serializer.save(updated_by=request.user)
        
        return Response(serializer.data)
    
    def partial_update(self, request, *args, **kwargs):
        """
        Partial update settings. Only admin/superuser can update.
        """
        return self.update(request, *args, **kwargs)
    
    def create(self, request, *args, **kwargs):
        """
        Prevent creation - settings instance already exists as singleton.
        """
        return Response(
            {'error': 'Platform settings already exist. Use PATCH to update.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )
    
    def destroy(self, request, *args, **kwargs):
        """
        Prevent deletion - settings instance cannot be deleted.
        """
        return Response(
            {'error': 'Cannot delete platform settings. It is a singleton.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

