from django.urls import path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from rest_framework import status
from rest_framework.response import Response
from .models import PlatformSettings
from .serializers import PlatformSettingsSerializer


@api_view(['GET', 'PATCH', 'PUT', 'OPTIONS'])
@permission_classes([IsAuthenticated])
def settings_endpoint(request):
    """
    Handle requests to /api/settings/ for singleton pattern.
    GET: Retrieve settings (all authenticated users)
    PATCH/PUT: Update settings (admin only)
    """
    settings = PlatformSettings.get_settings()
    
    if request.method == 'GET':
        serializer = PlatformSettingsSerializer(settings)
        return Response(serializer.data)
    
    elif request.method in ['PATCH', 'PUT']:
        # Check if user is admin or superuser
        if not (request.user.is_superuser or request.user.role == 'admin'):
            raise PermissionDenied('Only admin or superuser can update platform settings.')
        
        serializer = PlatformSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data)
    
    else:
        return Response(
            {'detail': f'Method "{request.method}" not allowed.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

urlpatterns = [
    path('', settings_endpoint, name='settings'),
]

