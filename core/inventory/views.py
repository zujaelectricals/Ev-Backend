from rest_framework import viewsets, status, parsers
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.exceptions import PermissionDenied
from django.db.models import Q
from .models import Vehicle, VehicleImage
from .serializers import VehicleSerializer, VehicleListSerializer, VehicleImageSerializer, ImageUploadSerializer


class IsAdminOrReadOnly(BasePermission):
    """
    Custom permission class:
    - Read operations (GET): All authenticated users
    - Write operations (POST, PUT, PATCH, DELETE): Only admin/superuser
    """
    def has_permission(self, request, view):
        # Allow read operations for all authenticated users
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return request.user and request.user.is_authenticated
        
        # Write operations require admin or superuser
        return (
            request.user and
            request.user.is_authenticated and
            (request.user.is_superuser or request.user.role == 'admin')
        )


class VehicleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Vehicle management with JSON API
    Images are uploaded separately and linked via image_ids
    
    Permissions:
    - All authenticated users can view vehicles (list, retrieve)
    - Only admin/superuser can create, update, delete vehicles
    - Only admin/superuser can manage images
    """
    queryset = Vehicle.objects.all()
    permission_classes = [IsAdminOrReadOnly]
    parser_classes = [parsers.JSONParser]  # JSON only - images uploaded separately
    
    def check_admin_permission(self):
        """Check if user is admin or superuser"""
        user = self.request.user
        if not (user.is_superuser or user.role == 'admin'):
            raise PermissionDenied("Only admin users can perform this action.")
    
    def get_serializer_class(self):
        """Use different serializers for list vs detail"""
        if self.action == 'list':
            return VehicleListSerializer
        return VehicleSerializer
    
    def get_queryset(self):
        """Filter vehicles based on user role and query params"""
        queryset = Vehicle.objects.all()
        
        # Filter by status
        status_param = self.request.query_params.get('status', None)
        if status_param:
            queryset = queryset.filter(status=status_param)
        
        # Filter by search query
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(model_code__icontains=search) |
                Q(description__icontains=search)
            )
        
        return queryset
    
    def create(self, request, *args, **kwargs):
        """Create vehicle with JSON - Admin only"""
        # Permission is checked by IsAdminOrReadOnly permission class
        # Additional check for safety
        if not (request.user.is_superuser or request.user.role == 'admin'):
            raise PermissionDenied("Only admin users can create vehicles.")
        
        # Use JSON parser only - images are linked via image_ids
        return super().create(request, *args, **kwargs)
    
    def perform_create(self, serializer):
        """Create vehicle - images handled by serializer"""
        serializer.save()
    
    def perform_update(self, serializer):
        """Update vehicle - only admin/superuser allowed"""
        self.check_admin_permission()
        serializer.save()
    
    def perform_destroy(self, instance):
        """Delete vehicle - only admin/superuser allowed"""
        self.check_admin_permission()
        super().perform_destroy(instance)
    
    @action(detail=True, methods=['post'], url_path='add-images')
    def add_images(self, request, pk=None):
        """Add additional images to an existing vehicle - only admin/superuser allowed"""
        self.check_admin_permission()
        vehicle = self.get_object()
        images_data = []
        
        # Extract images from request.FILES
        for key in request.FILES:
            if key.startswith('images') or key == 'images':
                file = request.FILES[key]
                images_data.append(file)
        
        if 'images_data' in request.FILES:
            images_data.extend(request.FILES.getlist('images_data'))
        
        if not images_data:
            return Response(
                {'error': 'No images provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create image records
        existing_count = vehicle.images.count()
        created_images = []
        for index, image_file in enumerate(images_data):
            image_obj = VehicleImage.objects.create(
                vehicle=vehicle,
                image=image_file,
                order=existing_count + index
            )
            created_images.append(image_obj)
        
        serializer = VehicleImageSerializer(created_images, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['delete'], url_path='remove-image/(?P<image_id>[^/.]+)')
    def remove_image(self, request, pk=None, image_id=None):
        """Remove a specific image from vehicle - only admin/superuser allowed"""
        self.check_admin_permission()
        vehicle = self.get_object()
        try:
            image = vehicle.images.get(id=image_id)
            image.delete()
            return Response({'message': 'Image deleted successfully'}, status=status.HTTP_204_NO_CONTENT)
        except VehicleImage.DoesNotExist:
            return Response(
                {'error': 'Image not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['patch'], url_path='set-primary-image/(?P<image_id>[^/.]+)')
    def set_primary_image(self, request, pk=None, image_id=None):
        """Set a specific image as primary - only admin/superuser allowed"""
        self.check_admin_permission()
        vehicle = self.get_object()
        try:
            image = vehicle.images.get(id=image_id)
            image.is_primary = True
            image.save()
            serializer = VehicleImageSerializer(image, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        except VehicleImage.DoesNotExist:
            return Response(
                {'error': 'Image not found'},
                status=status.HTTP_404_NOT_FOUND
            )


@api_view(['POST'])
@permission_classes([IsAdminOrReadOnly])
def upload_images(request):
    """
    Upload images independently (without vehicle association)
    Returns image IDs and URLs that can be used in vehicle creation
    
    POST /api/inventory/images/upload/
    Content-Type: multipart/form-data
    
    Body:
    - images[]: file1.jpg
    - images[]: file2.jpg
    """
    # Check admin permission
    if not (request.user.is_superuser or request.user.role == 'admin'):
        raise PermissionDenied("Only admin users can upload images.")
    
    # Extract images from request.FILES
    images_data = []
    
    # Check for images[] format
    if 'images' in request.FILES:
        images_data.extend(request.FILES.getlist('images'))
    
    # Check for images_data[] format
    if 'images_data' in request.FILES:
        images_data.extend(request.FILES.getlist('images_data'))
    
    # Check for individual image files
    for key in request.FILES:
        if isinstance(key, str):
            if (key.startswith('images[') and key.endswith(']')) or \
               (key.startswith('images_data[') and key.endswith(']')):
                images_data.append(request.FILES[key])
    
    if not images_data:
        return Response(
            {'error': 'No images provided. Please upload at least one image file.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Create VehicleImage records without vehicle association
    created_images = []
    for index, image_file in enumerate(images_data):
        # Validate it's actually a file
        if not hasattr(image_file, 'read') or not hasattr(image_file, 'name'):
            continue
        
        image_obj = VehicleImage.objects.create(
            vehicle=None,  # Unlinked image
            image=image_file,
            order=index
        )
        created_images.append(image_obj)
    
    if not created_images:
        return Response(
            {'error': 'No valid image files were uploaded.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Serialize and return
    serializer = ImageUploadSerializer(created_images, many=True, context={'request': request})
    return Response(serializer.data, status=status.HTTP_201_CREATED)
