from rest_framework import viewsets, status, parsers
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Sum, F
from django.db import connection
from django.conf import settings
from .models import Vehicle, VehicleImage, VehicleStock
from .serializers import (
    VehicleSerializer, VehicleListSerializer, VehicleImageSerializer, 
    ImageUploadSerializer, VehicleGroupedSerializer, VehicleVariantSerializer,
    VehicleStockSerializer
)
from .utils import get_or_create_vehicle_stock


class VehicleGroupedPagination(PageNumberPagination):
    """Custom pagination for grouped vehicle list"""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'
    
    def paginate_queryset(self, queryset, request, view=None):
        """Paginate queryset (or list) and update page_size from request"""
        # Get page_size from request query params
        page_size = self.get_page_size(request)
        if page_size:
            self.page_size = page_size
        return super().paginate_queryset(queryset, request, view)
    
    def get_paginated_response(self, data):
        """Return paginated response with count of vehicle groups (not individual vehicles)"""
        # Get the actual page size used (from the paginator, which respects query params)
        actual_page_size = self.page.paginator.per_page
        return Response({
            'count': self.page.paginator.count,  # Count of vehicle groups
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'page_size': actual_page_size,
            'current_page': self.page.number,
            'total_pages': self.page.paginator.num_pages,
            'results': data
        })


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


class IsAdminOrPublicReadOnly(BasePermission):
    """
    Custom permission class:
    - Read operations (GET): All users (authenticated and unauthenticated)
    - Write operations (POST, PUT, PATCH, DELETE): Only admin/superuser
    """
    def has_permission(self, request, view):
        # Allow read operations for all users (including unauthenticated)
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return True
        
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
    - All users (authenticated and unauthenticated) can view vehicles (list, retrieve)
    - Only admin/superuser can create, update, delete vehicles
    - Only admin/superuser can manage images
    - Non-admin users only see vehicles with available stock
    """
    queryset = Vehicle.objects.all()
    permission_classes = [IsAdminOrPublicReadOnly]
    parser_classes = [parsers.JSONParser]  # JSON only - images uploaded separately
    pagination_class = VehicleGroupedPagination
    
    def check_admin_permission(self):
        """Check if user is admin or superuser"""
        user = self.request.user
        if not (user.is_superuser or user.role == 'admin'):
            raise PermissionDenied("Only admin users can perform this action.")
    
    def get_serializer_class(self):
        """Use different serializers for list vs detail"""
        if self.action == 'list':
            return VehicleGroupedSerializer
        return VehicleSerializer
    
    def get_queryset(self):
        """Filter vehicles based on query params and user permissions"""
        queryset = Vehicle.objects.all().prefetch_related('images', 'stock')
        
        # Check if user is admin
        is_admin = (
            self.request.user and
            self.request.user.is_authenticated and
            (self.request.user.is_superuser or self.request.user.role == 'admin')
        )
        
        # Filter by stock availability for non-admin users
        # Only show vehicles with available stock (available_quantity > 0)
        # Vehicles without stock records are excluded (not considered "in stock")
        if not is_admin:
            queryset = queryset.filter(stock__available_quantity__gt=0).distinct()
        
        # Filter by name (exact match or contains)
        name = self.request.query_params.get('name', None)
        if name:
            queryset = queryset.filter(name__icontains=name)
        
        # Filter by model_code (exact match or contains)
        model_code = self.request.query_params.get('model_code', None)
        if model_code:
            queryset = queryset.filter(model_code__icontains=model_code)
        
        # Filter by status
        status_param = self.request.query_params.get('status', None)
        if status_param:
            queryset = queryset.filter(status=status_param)
        
        # Filter by color (if vehicle_color array contains the color)
        # Store filter for Python-based filtering (works across all databases)
        color = self.request.query_params.get('color', None)
        if color:
            self._color_filter = color
            # Try database-level filtering for PostgreSQL
            vendor = connection.vendor
            if vendor == 'postgresql':
                queryset = queryset.filter(vehicle_color__contains=[color])
        
        # Filter by battery variant (if battery_variant array contains the variant)
        # Store filter for Python-based filtering (works across all databases)
        battery = self.request.query_params.get('battery', None)
        if battery:
            self._battery_filter = battery
            # Try database-level filtering for PostgreSQL
            vendor = connection.vendor
            if vendor == 'postgresql':
                queryset = queryset.filter(battery_variant__contains=[battery])
        
        # Filter by price range
        min_price = self.request.query_params.get('min_price', None)
        max_price = self.request.query_params.get('max_price', None)
        if min_price:
            try:
                queryset = queryset.filter(price__gte=float(min_price))
            except (ValueError, TypeError):
                pass
        if max_price:
            try:
                queryset = queryset.filter(price__lte=float(max_price))
            except (ValueError, TypeError):
                pass
        
        # Search query (searches across multiple fields)
        search = self.request.query_params.get('search', None)
        if search:
            # Build search query - avoid JSON field lookups for non-PostgreSQL databases
            vendor = connection.vendor
            search_queries = Q(name__icontains=search) | Q(model_code__icontains=search) | Q(description__icontains=search)
            
            # Only use JSON field lookup for PostgreSQL
            if vendor == 'postgresql':
                search_queries |= Q(features__icontains=search)
            # For non-PostgreSQL, features search is skipped (would require Python filtering which is inefficient)
            
            queryset = queryset.filter(search_queries)
        
        # Order by created_at (newest first) by default
        queryset = queryset.order_by('-created_at')
        
        return queryset
    
    def list(self, request, *args, **kwargs):
        """List vehicles grouped by name"""
        queryset = self.filter_queryset(self.get_queryset())
        
        # Ensure images and stock are prefetched
        queryset = queryset.prefetch_related('images', 'stock')
        
        # Convert queryset to list to preserve prefetch
        vehicles_list = list(queryset)
        
        # Apply Python-based filtering for color and battery (for non-PostgreSQL databases)
        # This works across all database backends
        color_filter = getattr(self, '_color_filter', None)
        battery_filter = getattr(self, '_battery_filter', None)
        
        if color_filter or battery_filter:
            filtered_vehicles = []
            for vehicle in vehicles_list:
                # Filter by color if specified
                if color_filter:
                    vehicle_colors = vehicle.vehicle_color if isinstance(vehicle.vehicle_color, list) else []
                    if color_filter.lower() not in [c.lower() for c in vehicle_colors]:
                        continue
                
                # Filter by battery if specified
                if battery_filter:
                    vehicle_batteries = vehicle.battery_variant if isinstance(vehicle.battery_variant, list) else []
                    if battery_filter.lower() not in [b.lower() for b in vehicle_batteries]:
                        continue
                
                filtered_vehicles.append(vehicle)
            vehicles_list = filtered_vehicles
        
        # Group vehicles by name
        from collections import defaultdict
        grouped_vehicles = defaultdict(list)
        
        for vehicle in vehicles_list:
            grouped_vehicles[vehicle.name].append(vehicle)
        
        # Convert to list of dictionaries for serializer
        grouped_data = []
        for name, vehicles in grouped_vehicles.items():
            # Sort variants within each group by creation date (newest first)
            sorted_variants = sorted(vehicles, key=lambda v: v.created_at, reverse=True)
            grouped_data.append({
                'name': name,
                'variants': sorted_variants
            })
        
        # Sort groups by name
        grouped_data.sort(key=lambda x: x['name'])
        
        # Serialize grouped data with request context
        serializer = self.get_serializer(grouped_data, many=True, context={'request': request})
        
        # Return paginated response if pagination is enabled
        page = self.paginate_queryset(grouped_data)
        if page is not None:
            serializer = self.get_serializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        
        return Response(serializer.data)
    
    def create(self, request, *args, **kwargs):
        """Create vehicles with JSON - Admin only. Creates multiple vehicles for each color-battery combination."""
        # Permission is checked by IsAdminOrReadOnly permission class
        # Additional check for safety
        if not (request.user.is_superuser or request.user.role == 'admin'):
            raise PermissionDenied("Only admin users can create vehicles.")
        
        # Get serializer and validate data
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Create vehicles (serializer will create multiple vehicles)
        serializer.save()
        
        # Get all created vehicles from serializer
        created_vehicles = getattr(serializer, '_created_vehicles', [])
        
        if not created_vehicles:
            return Response(
                {'error': 'No vehicles were created.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Serialize all created vehicles
        response_serializer = VehicleSerializer(created_vehicles, many=True, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
    
    def perform_create(self, serializer):
        """Create vehicle - images handled by serializer"""
        # This is called by super().create(), but we override create() directly
        # So this method may not be called, but keeping it for compatibility
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


class VehicleStockViewSet(viewsets.ModelViewSet):
    """
    ViewSet for VehicleStock management
    - Read operations (GET): All users (authenticated and unauthenticated)
    - Write operations (POST, PUT, PATCH, DELETE): Only admin/superuser
    - Non-admin users only see vehicles with available stock (available_quantity > 0)
    """
    queryset = VehicleStock.objects.all()
    serializer_class = VehicleStockSerializer
    permission_classes = [IsAdminOrPublicReadOnly]
    
    def get_queryset(self):
        """Filter stocks based on query params and user permissions"""
        queryset = VehicleStock.objects.all().select_related('vehicle').prefetch_related('vehicle__images')
        
        # Check if user is admin
        is_admin = (
            self.request.user and
            self.request.user.is_authenticated and
            (self.request.user.is_superuser or self.request.user.role == 'admin')
        )
        
        # Filter by stock availability for non-admin users
        # Only show vehicles with available stock (available_quantity > 0)
        if not is_admin:
            queryset = queryset.filter(available_quantity__gt=0)
        
        # Filter by vehicle ID
        vehicle_id = self.request.query_params.get('vehicle_id')
        if vehicle_id:
            try:
                queryset = queryset.filter(vehicle_id=int(vehicle_id))
            except (ValueError, TypeError):
                pass
        
        # Filter by vehicle model_code
        model_code = self.request.query_params.get('model_code')
        if model_code:
            queryset = queryset.filter(vehicle__model_code__icontains=model_code)
        
        # Filter by vehicle name
        vehicle_name = self.request.query_params.get('vehicle_name')
        if vehicle_name:
            queryset = queryset.filter(vehicle__name__icontains=vehicle_name)
        
        # Filter by available quantity
        min_available = self.request.query_params.get('min_available')
        max_available = self.request.query_params.get('max_available')
        if min_available:
            try:
                queryset = queryset.filter(available_quantity__gte=int(min_available))
            except (ValueError, TypeError):
                pass
        if max_available:
            try:
                queryset = queryset.filter(available_quantity__lte=int(max_available))
            except (ValueError, TypeError):
                pass
        
        return queryset.order_by('-updated_at')
    
    def list(self, request, *args, **kwargs):
        """
        List vehicle stock with dashboard summary data.
        Returns paginated results plus summary metrics.
        """
        # Get filtered queryset (before pagination)
        queryset = self.filter_queryset(self.get_queryset())
        
        # Calculate aggregates from the full filtered queryset
        aggregates = queryset.aggregate(
            total_stock=Sum('total_quantity'),
            inventory_value=Sum(F('vehicle__price') * F('total_quantity'))
        )
        
        total_stock = aggregates['total_stock'] or 0
        inventory_value = aggregates['inventory_value'] or 0
        
        # Get low stock threshold percentage from settings
        threshold_percent = getattr(settings, 'LOW_STOCK_THRESHOLD_PERCENT', 20)
        
        # Calculate low stock and out of stock items
        low_stock_items = []
        low_stock_count = 0
        out_of_stock_count = 0
        
        for stock in queryset:
            if stock.vehicle is None:
                continue
                
            total_qty = stock.total_quantity
            available_qty = stock.available_quantity
            
            # Calculate reorder level (threshold)
            reorder_level = int(total_qty * (threshold_percent / 100))
            
            # Determine status
            if available_qty == 0:
                status = "out_of_stock"
                out_of_stock_count += 1
            elif available_qty <= reorder_level and total_qty > 0:
                status = "low_stock"
                low_stock_count += 1
            else:
                continue  # Skip items that don't need alerts
            
            low_stock_items.append({
                'vehicle_id': stock.vehicle.id,
                'vehicle_name': stock.vehicle.name,
                'vehicle_model_code': stock.vehicle.model_code or '',
                'available_quantity': available_qty,
                'total_quantity': total_qty,
                'reorder_level': reorder_level,
                'status': status
            })
        
        # Sort low stock items by available_quantity (lowest first)
        low_stock_items.sort(key=lambda x: x['available_quantity'])
        
        # Group stock by vehicle name and calculate totals per model
        model_stock_trends = queryset.values('vehicle__name').annotate(
            model_total=Sum('total_quantity')
        ).order_by('vehicle__name')
        
        # Build stock_trend array with one entry per model
        stock_trend = [
            {
                'label': item['vehicle__name'],
                'total_stock': item['model_total']
            }
            for item in model_stock_trends
            if item['vehicle__name']  # Filter out None values
        ]
        
        # Build summary
        summary = {
            'total_stock': total_stock,
            'inventory_value': float(inventory_value),
            'low_stock_threshold_percent': threshold_percent,
            'low_stock_alerts_count': low_stock_count,
            'out_of_stock_count': out_of_stock_count,
            'low_stock_items': low_stock_items,
            'stock_trend': stock_trend
        }
        
        # Get paginated results using standard DRF pagination
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated_response = self.get_paginated_response(serializer.data)
            # Add summary to paginated response
            paginated_response.data['summary'] = summary
            return paginated_response
        
        # If no pagination, return all results with summary
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'count': queryset.count(),
            'next': None,
            'previous': None,
            'results': serializer.data,
            'summary': summary
        })
    
    def get_object(self):
        """
        Override to support lookup by both VehicleStock ID and Vehicle ID.
        If the ID matches a Vehicle ID, return that vehicle's stock.
        Otherwise, try to find a VehicleStock with that ID.
        For non-admin users, only return vehicles with available stock.
        """
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs[lookup_url_kwarg]
        
        # Check if user is admin
        is_admin = (
            self.request.user and
            self.request.user.is_authenticated and
            (self.request.user.is_superuser or self.request.user.role == 'admin')
        )
        
        # First, try to find by Vehicle ID
        try:
            vehicle = Vehicle.objects.prefetch_related('images').get(id=lookup_value)
            # Get or create stock for this vehicle
            stock = get_or_create_vehicle_stock(vehicle)
            
            # For non-admin users, check if stock is available
            if not is_admin and stock.available_quantity <= 0:
                raise NotFound("Vehicle stock not found or not available.")
            
            return stock
        except Vehicle.DoesNotExist:
            pass
        except (ValueError, TypeError):
            # Invalid ID format, continue to try VehicleStock lookup
            pass
        
        # If not found by Vehicle ID, try VehicleStock ID
        try:
            stock = super().get_object()
            
            # For non-admin users, check if stock is available
            if not is_admin and stock.available_quantity <= 0:
                raise NotFound("Vehicle stock not found or not available.")
            
            return stock
        except VehicleStock.DoesNotExist:
            # Raise 404 with a helpful message
            raise NotFound("Vehicle stock not found. The ID may be a Vehicle ID that doesn't have stock, or an invalid VehicleStock ID.")
    
    def perform_create(self, serializer):
        """Create stock - only admin/superuser allowed"""
        if not (self.request.user.is_superuser or self.request.user.role == 'admin'):
            raise PermissionDenied("Only admin users can create stock records.")
        serializer.save()
    
    def perform_update(self, serializer):
        """Update stock - only admin/superuser allowed"""
        if not (self.request.user.is_superuser or self.request.user.role == 'admin'):
            raise PermissionDenied("Only admin users can update stock records.")
        serializer.save()
    
    def perform_destroy(self, instance):
        """Delete stock - only admin/superuser allowed"""
        if not (self.request.user.is_superuser or self.request.user.role == 'admin'):
            raise PermissionDenied("Only admin users can delete stock records.")
        instance.delete()
    
    @action(detail=False, methods=['get', 'post'], url_path='by-vehicle/(?P<vehicle_id>[^/.]+)')
    def by_vehicle(self, request, vehicle_id=None):
        """
        Get or update stock for a specific vehicle by vehicle ID
        GET /api/inventory/stock/by-vehicle/{vehicle_id}/ - Get stock (all users, but only shows vehicles with available stock for non-admin users)
        POST /api/inventory/stock/by-vehicle/{vehicle_id}/ - Update stock (admin only)
        """
        try:
            vehicle = Vehicle.objects.prefetch_related('images').get(id=vehicle_id)
        except Vehicle.DoesNotExist:
            return Response(
                {'error': 'Vehicle not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get or create stock
        stock = get_or_create_vehicle_stock(vehicle)
        
        # Check if user is admin
        is_admin = (
            request.user and
            request.user.is_authenticated and
            (request.user.is_superuser or request.user.role == 'admin')
        )
        
        # Handle POST request (update)
        if request.method == 'POST':
            if not is_admin:
                raise PermissionDenied("Only admin users can update stock.")
            
            # Update stock
            serializer = self.get_serializer(stock, data=request.data, partial=True, context={'request': request})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        # Handle GET request (retrieve)
        # For non-admin users, only show vehicles with available stock
        if not is_admin and stock.available_quantity <= 0:
            return Response(
                {'error': 'Vehicle stock not found or not available'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(stock, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
