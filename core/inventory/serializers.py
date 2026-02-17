from rest_framework import serializers
import json
import logging
import traceback
from django.db import models as django_models
from .models import Vehicle, VehicleImage, VehicleStock

logger = logging.getLogger(__name__)


class VehicleImageSerializer(serializers.ModelSerializer):
    """Serializer for vehicle images"""
    image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = VehicleImage
        fields = ('id', 'image', 'image_url', 'is_primary', 'alt_text', 'order', 'vehicle', 'created_at')
        read_only_fields = ('created_at', 'updated_at', 'vehicle')
    
    def get_image_url(self, obj):
        """Return full URL for the image"""
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class ImageUploadSerializer(serializers.ModelSerializer):
    """Serializer for independent image uploads (without vehicle association)"""
    image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = VehicleImage
        fields = ('id', 'image_url', 'created_at')
        read_only_fields = ('id', 'created_at')
    
    def get_image_url(self, obj):
        """Return full URL for the image"""
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class CustomFileField(serializers.FileField):
    """Custom FileField that gracefully handles text values (file paths)"""
    def to_internal_value(self, data):
        # If data is a string (text path from form-data), return None
        # We'll handle actual files from request.FILES in the serializer
        if isinstance(data, str):
            # This is a text path, not a file - return None to skip validation
            return None
        # If it's an actual file object, validate normally
        try:
            return super().to_internal_value(data)
        except:
            # If validation fails, return None (we'll handle files from FILES)
            return None


class VehicleSerializer(serializers.ModelSerializer):
    """Serializer for Vehicle with image support via image IDs"""
    images = VehicleImageSerializer(many=True, read_only=True)
    primary_image_url = serializers.SerializerMethodField()
    image_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
        allow_empty=True,
        help_text='List of image IDs to link to this vehicle (images must be uploaded first). Fallback if color_images not provided.'
    )
    color_images = serializers.DictField(
        child=serializers.ListField(child=serializers.IntegerField()),
        required=False,
        write_only=True,
        allow_empty=True,
        help_text='Dictionary mapping color names to image IDs (e.g., {"white": [1, 2, 3], "red": [4, 5]}). Images will be linked to vehicles matching the color.'
    )
    initial_quantity = serializers.IntegerField(
        required=False,
        write_only=True,
        default=0,
        min_value=0,
        help_text='Initial stock quantity for this vehicle. Applies to each variant created. Defaults to 0 if not provided.'
    )
    battery_pricing = serializers.DictField(
        child=serializers.DecimalField(max_digits=10, decimal_places=2),
        required=False,
        write_only=True,
        allow_empty=True,
        help_text='Dictionary mapping battery variant names to prices (e.g., {"40kWh": 65000, "75kWh": 75000}). If not provided, all variants use the base price field.'
    )
    stock_quantity = serializers.IntegerField(
        required=False,
        write_only=True,
        min_value=0,
        help_text='Update stock quantity for this vehicle. Only used during vehicle update. Creates or updates VehicleStock record. (Alias: use initial_quantity for consistency with create)'
    )
    stock_total_quantity = serializers.SerializerMethodField()
    stock_available_quantity = serializers.SerializerMethodField()
    stock_reserved_quantity = serializers.SerializerMethodField()
    is_already_booked = serializers.SerializerMethodField()
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._created_vehicles = []  # Store all created vehicles
    
    class Meta:
        model = Vehicle
        fields = (
            'id', 'name', 'model_code', 'vehicle_color', 'battery_variant',
            'price', 'status', 'description', 'features', 'specifications',
            'images', 'image_ids', 'color_images', 'primary_image_url', 'initial_quantity', 'battery_pricing', 'stock_quantity',
            'stock_total_quantity', 'stock_available_quantity', 'stock_reserved_quantity',
            'is_already_booked', 'created_at', 'updated_at'
        )
        read_only_fields = ('created_at', 'updated_at', 'model_code')
        extra_kwargs = {
            'features': {'required': False, 'allow_null': True},
            'specifications': {'required': False, 'allow_null': True},
        }
    
    def get_primary_image_url(self, obj):
        """Return URL of primary image if exists"""
        primary_image = obj.images.filter(is_primary=True).first()
        if primary_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(primary_image.image.url)
            return primary_image.image.url
        # If no primary, return first image
        first_image = obj.images.first()
        if first_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(first_image.image.url)
            return first_image.image.url
        return None
    
    def get_stock_total_quantity(self, obj):
        """Return total stock quantity"""
        try:
            return obj.stock.total_quantity if hasattr(obj, 'stock') else 0
        except VehicleStock.DoesNotExist:
            return 0
    
    def get_stock_available_quantity(self, obj):
        """Return available stock quantity"""
        try:
            return obj.stock.available_quantity if hasattr(obj, 'stock') else 0
        except VehicleStock.DoesNotExist:
            return 0
    
    def get_stock_reserved_quantity(self, obj):
        """Return reserved stock quantity"""
        try:
            if hasattr(obj, 'stock'):
                reserved = obj.stock.total_quantity - obj.stock.available_quantity
                return max(0, reserved)
            return 0
        except VehicleStock.DoesNotExist:
            return 0
    
    def get_is_already_booked(self, obj):
        """Check if the current user has already booked this specific vehicle variant"""
        request = self.context.get('request')
        
        # If user is not authenticated, return False
        if not request or not request.user or not request.user.is_authenticated:
            return False
        
        # Import Booking model here to avoid circular imports
        from core.booking.models import Booking
        
        # Get vehicle colors and battery variants as lists
        vehicle_colors = obj.vehicle_color if isinstance(obj.vehicle_color, list) else []
        vehicle_batteries = obj.battery_variant if isinstance(obj.battery_variant, list) else []
        
        # Check if user has any active bookings for this vehicle variant
        # A booking matches if:
        # 1. vehicle_model matches
        # 2. vehicle_color matches one of the vehicle's colors (case-insensitive)
        # 3. battery_variant matches one of the vehicle's batteries (case-insensitive)
        # 4. status is 'active', 'completed', or 'delivered' (payment verified)
        # Note: 'pending' status is excluded - booking must have verified payment to be considered booked
        bookings = Booking.objects.filter(
            user=request.user,
            vehicle_model=obj,
            status__in=['active', 'completed', 'delivered']
        )
        
        # Check each booking to see if color and battery match
        for booking in bookings:
            booking_color = (booking.vehicle_color or '').strip() if booking.vehicle_color else None
            booking_battery = (booking.battery_variant or '').strip() if booking.battery_variant else None
            
            # Check if booking color matches any vehicle color (case-insensitive)
            color_matches = False
            if booking_color:
                booking_color_lower = booking_color.lower()
                for vehicle_color in vehicle_colors:
                    if isinstance(vehicle_color, str) and vehicle_color.strip().lower() == booking_color_lower:
                        color_matches = True
                        break
            # If booking has no color specified, we can't match it to a specific variant
            # Skip this booking as it's ambiguous
            
            # Check if booking battery matches any vehicle battery (case-insensitive)
            battery_matches = False
            if booking_battery:
                booking_battery_lower = booking_battery.lower()
                for vehicle_battery in vehicle_batteries:
                    if isinstance(vehicle_battery, str) and vehicle_battery.strip().lower() == booking_battery_lower:
                        battery_matches = True
                        break
            # If booking has no battery specified, we can't match it to a specific variant
            # Skip this booking as it's ambiguous
            
            # If both color and battery match, this variant is booked
            if color_matches and battery_matches:
                return True
        
        return False
    
    
    def validate_features(self, value):
        """Validate that features is a list of strings - optional field, unlimited items"""
        # If value is None or not provided, return empty list
        if value is None:
            return []
        
        # Handle JSON string from form-data
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise serializers.ValidationError('Features must be a valid JSON array string.')
        
        if not isinstance(value, list):
            raise serializers.ValidationError('Features must be a list of feature names.')
        
        # No limit on number of features - add as many as needed
        for feature in value:
            if not isinstance(feature, str):
                raise serializers.ValidationError('All features must be strings.')
        
        return value
    
    def validate_specifications(self, value):
        """Validate that specifications is a dictionary - optional field, unlimited key-value pairs"""
        # If value is None or not provided, return empty dict
        if value is None:
            return {}
        
        # Handle JSON string from form-data
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise serializers.ValidationError('Specifications must be a valid JSON object string.')
        
        if not isinstance(value, dict):
            raise serializers.ValidationError('Specifications must be a dictionary of key-value pairs.')
        
        # No limit on number of specifications - add any key-value pairs as needed
        # All values are stored as-is (can be strings, numbers, etc.)
        return value
    
    def validate_vehicle_color(self, value):
        """Validate that vehicle_color is a list of strings - default is ["white"]"""
        # If value is None or not provided, return default
        if value is None:
            return ["white"]
        
        # Handle JSON string from form-data
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise serializers.ValidationError('Vehicle color must be a valid JSON array string.')
        
        if not isinstance(value, list):
            raise serializers.ValidationError('Vehicle color must be a list of color names.')
        
        # Validate all items are strings
        for color in value:
            if not isinstance(color, str):
                raise serializers.ValidationError('All vehicle colors must be strings.')
            if not color.strip():
                raise serializers.ValidationError('Vehicle colors cannot be empty strings.')
        
        # If empty list, return default
        if len(value) == 0:
            return ["white"]
        
        return value
    
    def validate_battery_variant(self, value):
        """Validate that battery_variant is a list of strings"""
        # If value is None or not provided, return empty list
        if value is None:
            return []
        
        # Handle JSON string from form-data
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise serializers.ValidationError('Battery variant must be a valid JSON array string.')
        
        if not isinstance(value, list):
            raise serializers.ValidationError('Battery variant must be a list of battery configurations.')
        
        # Validate all items are strings
        for battery in value:
            if not isinstance(battery, str):
                raise serializers.ValidationError('All battery variants must be strings.')
            if not battery.strip():
                raise serializers.ValidationError('Battery variants cannot be empty strings.')
        
        return value
    
    def validate_image_ids(self, value):
        """Validate that image_ids reference existing images that can be linked"""
        if value is not None and len(value) > 0:
            # Get the instance (vehicle) if this is an update
            instance = getattr(self, 'instance', None)
            
            if instance:
                # For updates: allow images that are unlinked OR already linked to this vehicle
                valid_images = VehicleImage.objects.filter(
                    id__in=value
                ).filter(
                    django_models.Q(vehicle__isnull=True) | django_models.Q(vehicle=instance)
                ).values_list('id', flat=True)
            else:
                # For creates: only allow unlinked images
                valid_images = VehicleImage.objects.filter(
                    id__in=value,
                    vehicle__isnull=True
                ).values_list('id', flat=True)
            
            valid_ids = set(valid_images)
            requested_ids = set(value)
            
            # Check for invalid IDs (don't exist or linked to different vehicle)
            invalid_ids = requested_ids - valid_ids
            if invalid_ids:
                # Check if they exist but are linked to another vehicle
                existing_but_linked = VehicleImage.objects.filter(
                    id__in=invalid_ids
                ).exclude(vehicle__isnull=True)
                
                if instance:
                    existing_but_linked = existing_but_linked.exclude(vehicle=instance)
                
                if existing_but_linked.exists():
                    raise serializers.ValidationError(
                        f'Image IDs {list(invalid_ids)} are already linked to another vehicle. '
                        'Please upload new images using /api/inventory/images/upload/'
                    )
                else:
                    raise serializers.ValidationError(
                        f'Image IDs {list(invalid_ids)} do not exist. '
                        'Please upload images first using /api/inventory/images/upload/'
                    )
        return value
    
    def validate_color_images(self, value):
        """Validate that color_images maps colors to valid image IDs"""
        if value is None:
            return {}
        
        # Handle JSON string from form-data
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise serializers.ValidationError('Color images must be a valid JSON object string.')
        
        if not isinstance(value, dict):
            raise serializers.ValidationError('Color images must be a dictionary mapping color names to image ID arrays.')
        
        # Validate each color's image IDs
        all_image_ids = set()
        for color, image_ids in value.items():
            if not isinstance(color, str):
                raise serializers.ValidationError('Color names in color_images must be strings.')
            if not isinstance(image_ids, list):
                raise serializers.ValidationError(f'Image IDs for color "{color}" must be an array.')
            for img_id in image_ids:
                if not isinstance(img_id, int):
                    raise serializers.ValidationError(f'Image IDs must be integers. Found: {type(img_id).__name__}')
                all_image_ids.add(img_id)
        
        # Validate that all referenced images exist and are unlinked
        if all_image_ids:
            instance = getattr(self, 'instance', None)
            if instance:
                # For updates: allow images that are unlinked OR already linked to this vehicle
                valid_images = VehicleImage.objects.filter(
                    id__in=all_image_ids
                ).filter(
                    django_models.Q(vehicle__isnull=True) | django_models.Q(vehicle=instance)
                ).values_list('id', flat=True)
            else:
                # For creates: only allow unlinked images
                valid_images = VehicleImage.objects.filter(
                    id__in=all_image_ids,
                    vehicle__isnull=True
                ).values_list('id', flat=True)
            
            valid_ids = set(valid_images)
            invalid_ids = all_image_ids - valid_ids
            
            if invalid_ids:
                existing_but_linked = VehicleImage.objects.filter(
                    id__in=invalid_ids
                ).exclude(vehicle__isnull=True)
                
                if instance:
                    existing_but_linked = existing_but_linked.exclude(vehicle=instance)
                
                if existing_but_linked.exists():
                    raise serializers.ValidationError(
                        f'Image IDs {list(invalid_ids)} in color_images are already linked to another vehicle. '
                        'Please upload new images using /api/inventory/images/upload/'
                    )
                else:
                    raise serializers.ValidationError(
                        f'Image IDs {list(invalid_ids)} in color_images do not exist. '
                        'Please upload images first using /api/inventory/images/upload/'
                    )
        
        return value
    
    def validate(self, data):
        """Validate vehicle data"""
        # Ensure features and specifications have default values if not provided
        if 'features' not in data or data.get('features') is None:
            data['features'] = []
        if 'specifications' not in data or data.get('specifications') is None:
            data['specifications'] = {}
        # Ensure vehicle_color has default value if not provided
        if 'vehicle_color' not in data or data.get('vehicle_color') is None:
            data['vehicle_color'] = ["white"]
        # Ensure battery_variant has default value if not provided
        if 'battery_variant' not in data or data.get('battery_variant') is None:
            data['battery_variant'] = []
        
        # For create operations, ensure at least one color and one battery variant
        if self.instance is None:  # Creating new vehicle
            if not data.get('vehicle_color') or len(data.get('vehicle_color', [])) == 0:
                raise serializers.ValidationError({
                    'vehicle_color': 'At least one vehicle color is required.'
                })
            if not data.get('battery_variant') or len(data.get('battery_variant', [])) == 0:
                raise serializers.ValidationError({
                    'battery_variant': 'At least one battery variant is required.'
                })
        
        # Validate battery_pricing if provided
        battery_pricing = data.get('battery_pricing')
        base_price = data.get('price')
        battery_variants = data.get('battery_variant', [])
        if not isinstance(battery_variants, list):
            battery_variants = []
        
        if battery_pricing is not None:
            # Check that all keys in battery_pricing exist in battery_variant array
            invalid_keys = []
            for battery_key in battery_pricing.keys():
                if battery_key not in battery_variants:
                    invalid_keys.append(battery_key)
            
            if invalid_keys:
                raise serializers.ValidationError({
                    'battery_pricing': f'Battery variants {invalid_keys} in battery_pricing are not in battery_variant array.'
                })
            
            # Validate all prices are non-negative
            invalid_prices = []
            for battery_key, price in battery_pricing.items():
                try:
                    price_decimal = float(price)
                    if price_decimal < 0:
                        invalid_prices.append(battery_key)
                except (ValueError, TypeError):
                    invalid_prices.append(battery_key)
            
            if invalid_prices:
                raise serializers.ValidationError({
                    'battery_pricing': f'Invalid prices for battery variants {invalid_prices}. Prices must be non-negative numbers.'
                })
            
            # If battery_pricing is provided but doesn't cover all batteries, base_price is required as fallback
            if self.instance is None:  # Only for create operations
                missing_batteries = [b for b in battery_variants if b not in battery_pricing]
                if missing_batteries and base_price is None:
                    raise serializers.ValidationError({
                        'price': f'Base price is required as fallback for battery variants {missing_batteries} that are not in battery_pricing.'
                    })
        
        # If battery_pricing is not provided, base_price is required for all variants
        if self.instance is None and battery_pricing is None and base_price is None:
            raise serializers.ValidationError({
                'price': 'Price is required when battery_pricing is not provided.'
            })
        
        return data
    
    def create(self, validated_data):
        """Create multiple vehicles - one for each battery variant. If color_images provided, create per color-battery combination."""
        from django.db import transaction
        
        image_ids = validated_data.pop('image_ids', [])
        color_images = validated_data.pop('color_images', {})
        initial_quantity = validated_data.pop('initial_quantity', 0)
        battery_pricing = validated_data.pop('battery_pricing', None)
        base_price = validated_data.get('price')
        
        # Ensure features and specifications have default values if None
        if 'features' not in validated_data or validated_data.get('features') is None:
            validated_data['features'] = []
        if 'specifications' not in validated_data or validated_data.get('specifications') is None:
            validated_data['specifications'] = {}
        # Ensure vehicle_color has default value if None
        if 'vehicle_color' not in validated_data or validated_data.get('vehicle_color') is None:
            validated_data['vehicle_color'] = ["white"]
        # Ensure battery_variant has default value if None
        if 'battery_variant' not in validated_data or validated_data.get('battery_variant') is None:
            validated_data['battery_variant'] = []
        
        # Get colors and battery variants
        colors = validated_data.pop('vehicle_color', ["white"])
        batteries = validated_data.pop('battery_variant', [])
        
        # Helper function to get price for a battery variant
        def get_price_for_battery(battery):
            """Get price for a specific battery variant"""
            if battery_pricing and battery in battery_pricing:
                return battery_pricing[battery]
            return base_price
        
        # Validate we have at least one color and one battery
        if not colors or len(colors) == 0:
            colors = ["white"]
        if not batteries or len(batteries) == 0:
            raise serializers.ValidationError({
                'battery_variant': 'At least one battery variant is required.'
            })
        
        # If color_images provided, validate all colors in color_images are in vehicle_color
        if color_images:
            color_images_colors = set(color_images.keys())
            vehicle_colors = set(colors)
            invalid_colors = color_images_colors - vehicle_colors
            if invalid_colors:
                raise serializers.ValidationError({
                    'color_images': f'Colors {list(invalid_colors)} in color_images are not in vehicle_color array.'
                })
        
        # Get images to link (fallback for backward compatibility)
        images_to_link = []
        if image_ids and not color_images:
            images_to_link = list(VehicleImage.objects.filter(
                id__in=image_ids,
                vehicle__isnull=True
            ).order_by('id'))
        
        # Create vehicles
        created_vehicles = []
        
        with transaction.atomic():
            # If color_images provided, create one vehicle per color-battery combination
            # Otherwise, create one vehicle per battery with all colors
            if color_images:
                # First, collect all unlinked images by color
                # Multiple vehicles can share the same images - each gets its own VehicleImage record
                # No conflicts will occur as VehicleImage has no unique constraints on the image field
                color_images_map = {}
                for color, image_ids in color_images.items():
                    if color in colors and image_ids:
                        # Get the original unlinked images for this color
                        # These images will be duplicated for each vehicle of this color
                        original_images_query = VehicleImage.objects.filter(
                            id__in=image_ids,
                            vehicle__isnull=True
                        ).order_by('id')
                        # Store as list of tuples: (original_vehicle_image_object, alt_text)
                        # We'll create new VehicleImage instances for each vehicle, all referencing the same image file
                        image_data = []
                        for img in original_images_query:
                            if img.image:  # Ensure image exists
                                # Store the original VehicleImage object - we'll use its image file for duplicates
                                # Multiple VehicleImage instances can safely reference the same image file
                                image_data.append((img, img.alt_text or ''))
                        color_images_map[color] = image_data
                
                # Create per color-battery combination
                for color in colors:
                    for battery in batteries:
                        vehicle_data = validated_data.copy()
                        vehicle_data['vehicle_color'] = [color]  # Single color per vehicle
                        vehicle_data['battery_variant'] = [battery]  # Single battery per vehicle
                        # Set price based on battery_pricing or use base price
                        vehicle_data['price'] = get_price_for_battery(battery)
                        
                        vehicle = Vehicle.objects.create(**vehicle_data)
                        created_vehicles.append(vehicle)
                        
                        # Create VehicleStock with initial quantity
                        VehicleStock.objects.create(
                            vehicle=vehicle,
                            total_quantity=initial_quantity,
                            available_quantity=initial_quantity
                        )
                        
                        # Link images for this color if specified in color_images
                        # Duplicate image records for each vehicle of the same color
                        if color in color_images_map and color_images_map[color]:
                            image_data_list = color_images_map[color]
                            
                            for index, (original_image_obj, alt_text) in enumerate(image_data_list):
                                # Create a duplicate VehicleImage instance for this vehicle
                                # Multiple vehicles can share the same image file - no conflicts will occur
                                # Each VehicleImage instance is separate, but they can reference the same underlying file
                                try:
                                    # Access the image file from the original VehicleImage object
                                    # Django ImageField allows multiple instances to reference the same file path
                                    # This is safe and efficient - no file copying occurs, just database records
                                    new_image = VehicleImage.objects.create(
                                        vehicle=vehicle,
                                        image=original_image_obj.image,  # Same image file, different VehicleImage record
                                        is_primary=(index == 0),  # First image is primary for this vehicle
                                        alt_text=alt_text,
                                        order=index
                                    )
                                    # Note: Multiple vehicles can have the same image file without conflicts
                                    # Each VehicleImage is a separate database record linked to a different vehicle
                                except Exception as e:
                                    # Log error but continue - images might fail but vehicles should still be created
                                    logger.error(f"Error creating image for vehicle {vehicle.id}, color {color}, battery {battery}: {str(e)}")
                                    logger.error(traceback.format_exc())
                                    continue
            else:
                # Create per battery only (backward compatibility - all colors in each vehicle)
                for battery in batteries:
                    vehicle_data = validated_data.copy()
                    vehicle_data['vehicle_color'] = colors  # Keep all colors
                    vehicle_data['battery_variant'] = [battery]  # Single battery per vehicle
                    # Set price based on battery_pricing or use base price
                    vehicle_data['price'] = get_price_for_battery(battery)
                    
                    vehicle = Vehicle.objects.create(**vehicle_data)
                    created_vehicles.append(vehicle)
                    
                    # Create VehicleStock with initial quantity
                    VehicleStock.objects.create(
                        vehicle=vehicle,
                        total_quantity=initial_quantity,
                        available_quantity=initial_quantity
                    )
                
                # Link images to first vehicle only (fallback)
                if images_to_link and created_vehicles:
                    first_vehicle = created_vehicles[0]
                    for index, image in enumerate(images_to_link):
                        image.vehicle = first_vehicle
                        image.order = index
                        # Set first image as primary if no primary exists
                        if index == 0 and not first_vehicle.images.filter(is_primary=True).exists():
                            image.is_primary = True
                        image.save()
        
        # Store all created vehicles for access in view
        self._created_vehicles = created_vehicles
        
        # Return first vehicle (ModelSerializer expects single instance)
        # View will handle returning all vehicles
        return created_vehicles[0] if created_vehicles else None
    
    def update(self, instance, validated_data):
        """Update vehicle and handle image linking"""
        image_ids = validated_data.pop('image_ids', None)
        color_images = validated_data.pop('color_images', None)
        # Support both initial_quantity and stock_quantity for consistency
        initial_quantity = validated_data.pop('initial_quantity', None)
        stock_quantity = validated_data.pop('stock_quantity', None)
        # battery_pricing is only used during create for per-variant pricing,
        # it is a write-only helper and not a model field, so remove it here
        # to avoid trying to set it directly on the Vehicle instance
        validated_data.pop('battery_pricing', None)
        # Use initial_quantity if provided, otherwise use stock_quantity (backward compatibility)
        quantity_to_update = initial_quantity if initial_quantity is not None else stock_quantity
        
        # Ensure features and specifications have default values if None
        if 'features' in validated_data and validated_data.get('features') is None:
            validated_data['features'] = []
        if 'specifications' in validated_data and validated_data.get('specifications') is None:
            validated_data['specifications'] = {}
        # Ensure vehicle_color has default value if None
        if 'vehicle_color' in validated_data and validated_data.get('vehicle_color') is None:
            validated_data['vehicle_color'] = ["white"]
        
        # Get the updated vehicle_color for validation (use new value if provided, otherwise current)
        updated_vehicle_color = validated_data.get('vehicle_color', instance.vehicle_color)
        if updated_vehicle_color is None:
            updated_vehicle_color = ["white"]  # Default
        
        # Handle image linking - color_images takes precedence over image_ids (like in create)
        # Validate BEFORE updating vehicle fields so we can check against the NEW vehicle_color
        if color_images is not None:
            # If color_images contains colors not in vehicle_color, automatically add them
            vehicle_colors = set(updated_vehicle_color)
            color_images_colors = set(color_images.keys())
            missing_colors = color_images_colors - vehicle_colors
            
            if missing_colors:
                # Automatically add missing colors to vehicle_color
                updated_vehicle_color = list(vehicle_colors | missing_colors)
                validated_data['vehicle_color'] = updated_vehicle_color
                vehicle_colors = set(updated_vehicle_color)
            
            # Validate all image IDs exist and are unlinked
            all_image_ids = []
            for img_ids in color_images.values():
                all_image_ids.extend(img_ids)
            
            if all_image_ids:
                existing_images = VehicleImage.objects.filter(id__in=all_image_ids)
                existing_image_ids = set(existing_images.values_list('id', flat=True))
                invalid_ids = set(all_image_ids) - existing_image_ids
                
                if invalid_ids:
                    raise serializers.ValidationError({
                        'color_images': f'Image IDs {list(invalid_ids)} do not exist. Please upload images first using /api/inventory/images/upload/'
                    })
                
                # Check if any images are already linked to another vehicle
                linked_images = existing_images.exclude(vehicle__isnull=True).exclude(vehicle=instance)
                if linked_images.exists():
                    linked_ids = list(linked_images.values_list('id', flat=True))
                    raise serializers.ValidationError({
                        'color_images': f'Image IDs {linked_ids} are already linked to another vehicle. Please upload new images using /api/inventory/images/upload/'
                    })
            
            # Remove all existing images for this vehicle
            instance.images.all().update(vehicle=None)
            
            # Link images based on color mapping
            # Since this is a single vehicle, we'll link images for all colors that match
            existing_count = 0
            for color, img_ids in color_images.items():
                if color in vehicle_colors and img_ids:
                    # Get unlinked images for this color
                    images_to_link = VehicleImage.objects.filter(
                        id__in=img_ids,
                        vehicle__isnull=True
                    ).order_by('id')
                    
                    for index, image in enumerate(images_to_link):
                        image.vehicle = instance
                        image.order = existing_count + index
                        # Set first image as primary if no primary exists
                        if existing_count == 0 and index == 0:
                            image.is_primary = True
                        image.save()
                    existing_count += images_to_link.count()
        elif image_ids is not None:
            # Get current images linked to this vehicle
            current_image_ids = set(instance.images.values_list('id', flat=True))
            requested_image_ids = set(image_ids)
            
            # Find images to add (in image_ids but not currently linked)
            images_to_add = requested_image_ids - current_image_ids
            
            # Find images to remove (currently linked but not in image_ids)
            images_to_remove = current_image_ids - requested_image_ids
            
            # Remove images that are no longer in image_ids
            if images_to_remove:
                instance.images.filter(id__in=images_to_remove).update(vehicle=None)
            
            # Add new images (unlinked images from image_ids)
            if images_to_add:
                new_images = VehicleImage.objects.filter(
                    id__in=images_to_add,
                    vehicle__isnull=True
                )
                
                if new_images.exists():
                    existing_count = instance.images.count()
                    for index, image in enumerate(new_images):
                        image.vehicle = instance
                        image.order = existing_count + index
                        # Set first new image as primary if no primary exists
                        if existing_count == 0 and index == 0:
                            image.is_primary = True
                        image.save()
            
            # Reorder all images to match image_ids order (including existing ones)
            if image_ids:
                for order, image_id in enumerate(image_ids):
                    # Only update order for images that belong to this vehicle
                    VehicleImage.objects.filter(
                        id=image_id, 
                        vehicle=instance
                    ).update(order=order)
        
        # Apply remaining validated fields to the Vehicle instance
        # (e.g., name, price, status, description, features, specifications,
        #  vehicle_color, battery_variant, etc.)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Handle stock quantity update if requested
        if quantity_to_update is not None:
            # Ensure non-negative quantity (serializer field already enforces this,
            # but guard defensively here as well)
            if quantity_to_update < 0:
                quantity_to_update = 0

            # Get or create VehicleStock for this vehicle
            stock, created = VehicleStock.objects.get_or_create(
                vehicle=instance,
                defaults={
                    'total_quantity': quantity_to_update,
                    'available_quantity': quantity_to_update,
                },
            )

            if not created:
                # Compute reserved quantity based on current stock
                reserved = max(0, stock.total_quantity - stock.available_quantity)

                # Update totals following the documented rules:
                # - If new quantity < reserved: available = 0
                # - Else: available = new_quantity - reserved
                stock.total_quantity = quantity_to_update
                if quantity_to_update < reserved:
                    stock.available_quantity = 0
                else:
                    stock.available_quantity = quantity_to_update - reserved

                stock.save(update_fields=['total_quantity', 'available_quantity', 'updated_at'])
        
        return instance


class VehicleListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for vehicle listing"""
    primary_image_url = serializers.SerializerMethodField()
    image_count = serializers.SerializerMethodField()
    stock_total_quantity = serializers.SerializerMethodField()
    stock_available_quantity = serializers.SerializerMethodField()
    stock_reserved_quantity = serializers.SerializerMethodField()
    
    class Meta:
        model = Vehicle
        fields = (
            'id', 'name', 'model_code', 'vehicle_color', 'battery_variant',
            'price', 'status', 'features', 'specifications',
            'primary_image_url', 'image_count',
            'stock_total_quantity', 'stock_available_quantity', 'stock_reserved_quantity',
            'created_at'
        )
        read_only_fields = ('model_code',)
    
    def get_primary_image_url(self, obj):
        """Return URL of primary image if exists"""
        primary_image = obj.images.filter(is_primary=True).first()
        if primary_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(primary_image.image.url)
            return primary_image.image.url
        first_image = obj.images.first()
        if first_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(first_image.image.url)
            return first_image.image.url
        return None
    
    def get_image_count(self, obj):
        """Return total number of images"""
        return obj.images.count()
    
    def get_stock_total_quantity(self, obj):
        """Return total stock quantity"""
        try:
            return obj.stock.total_quantity if hasattr(obj, 'stock') else 0
        except VehicleStock.DoesNotExist:
            return 0
    
    def get_stock_available_quantity(self, obj):
        """Return available stock quantity"""
        try:
            return obj.stock.available_quantity if hasattr(obj, 'stock') else 0
        except VehicleStock.DoesNotExist:
            return 0
    
    def get_stock_reserved_quantity(self, obj):
        """Return reserved stock quantity"""
        try:
            if hasattr(obj, 'stock'):
                reserved = obj.stock.total_quantity - obj.stock.available_quantity
                return max(0, reserved)
            return 0
        except VehicleStock.DoesNotExist:
            return 0


class VehicleVariantSerializer(serializers.ModelSerializer):
    """Serializer for individual vehicle variant in grouped response"""
    primary_image_url = serializers.SerializerMethodField()
    image_count = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    stock_total_quantity = serializers.SerializerMethodField()
    stock_available_quantity = serializers.SerializerMethodField()
    stock_reserved_quantity = serializers.SerializerMethodField()
    is_already_booked = serializers.SerializerMethodField()
    
    class Meta:
        model = Vehicle
        fields = (
            'id', 'model_code', 'vehicle_color', 'battery_variant',
            'price', 'status', 'primary_image_url', 'image_count', 'images',
            'stock_total_quantity', 'stock_available_quantity', 'stock_reserved_quantity',
            'is_already_booked', 'created_at'
        )
        read_only_fields = ('model_code',)
    
    def get_primary_image_url(self, obj):
        """Return URL of primary image if exists"""
        primary_image = obj.images.filter(is_primary=True).first()
        if primary_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(primary_image.image.url)
            return primary_image.image.url
        first_image = obj.images.first()
        if first_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(first_image.image.url)
            return first_image.image.url
        return None
    
    def get_image_count(self, obj):
        """Return total number of images"""
        return obj.images.count()
    
    def get_stock_total_quantity(self, obj):
        """Return total stock quantity"""
        try:
            return obj.stock.total_quantity if hasattr(obj, 'stock') else 0
        except VehicleStock.DoesNotExist:
            return 0
    
    def get_stock_available_quantity(self, obj):
        """Return available stock quantity"""
        try:
            return obj.stock.available_quantity if hasattr(obj, 'stock') else 0
        except VehicleStock.DoesNotExist:
            return 0
    
    def get_stock_reserved_quantity(self, obj):
        """Return reserved stock quantity"""
        try:
            if hasattr(obj, 'stock'):
                reserved = obj.stock.total_quantity - obj.stock.available_quantity
                return max(0, reserved)
            return 0
        except VehicleStock.DoesNotExist:
            return 0
    
    def get_images(self, obj):
        """Return all images for this variant"""
        # Access images through the relationship
        # Use prefetched images if available, otherwise query
        try:
            if hasattr(obj, '_prefetched_objects_cache') and 'images' in obj._prefetched_objects_cache:
                images = obj._prefetched_objects_cache['images']
            else:
                # Query images directly
                images = list(obj.images.all().order_by('order', '-is_primary', 'created_at'))
        except Exception:
            # Fallback if relationship access fails
            images = []
        
        request = self.context.get('request')
        result = []
        for img in images:
            if img and hasattr(img, 'image') and img.image:  # Only include images that have a file
                try:
                    image_url = img.image.url
                    if request:
                        image_url = request.build_absolute_uri(image_url)
                    result.append({
                        'id': img.id,
                        'image_url': image_url,
                        'is_primary': img.is_primary,
                        'alt_text': img.alt_text or '',
                        'order': img.order
                    })
                except Exception:
                    # Skip images that can't be serialized
                    continue
        return result
    
    def get_is_already_booked(self, obj):
        """Check if the current user has already booked this specific vehicle variant"""
        request = self.context.get('request')
        
        # If user is not authenticated, return False
        if not request or not request.user or not request.user.is_authenticated:
            return False
        
        # Import Booking model here to avoid circular imports
        from core.booking.models import Booking
        
        # Get vehicle colors and battery variants as lists
        vehicle_colors = obj.vehicle_color if isinstance(obj.vehicle_color, list) else []
        vehicle_batteries = obj.battery_variant if isinstance(obj.battery_variant, list) else []
        
        # Check if user has any active bookings for this vehicle variant
        # A booking matches if:
        # 1. vehicle_model matches
        # 2. vehicle_color matches one of the vehicle's colors (case-insensitive)
        # 3. battery_variant matches one of the vehicle's batteries (case-insensitive)
        # 4. status is 'active', 'completed', or 'delivered' (payment verified)
        # Note: 'pending' status is excluded - booking must have verified payment to be considered booked
        bookings = Booking.objects.filter(
            user=request.user,
            vehicle_model=obj,
            status__in=['active', 'completed', 'delivered']
        )
        
        # Check each booking to see if color and battery match
        for booking in bookings:
            booking_color = (booking.vehicle_color or '').strip() if booking.vehicle_color else None
            booking_battery = (booking.battery_variant or '').strip() if booking.battery_variant else None
            
            # Check if booking color matches any vehicle color (case-insensitive)
            color_matches = False
            if booking_color:
                booking_color_lower = booking_color.lower()
                for vehicle_color in vehicle_colors:
                    if isinstance(vehicle_color, str) and vehicle_color.strip().lower() == booking_color_lower:
                        color_matches = True
                        break
            # If booking has no color specified, we can't match it to a specific variant
            # Skip this booking as it's ambiguous
            
            # Check if booking battery matches any vehicle battery (case-insensitive)
            battery_matches = False
            if booking_battery:
                booking_battery_lower = booking_battery.lower()
                for vehicle_battery in vehicle_batteries:
                    if isinstance(vehicle_battery, str) and vehicle_battery.strip().lower() == booking_battery_lower:
                        battery_matches = True
                        break
            # If booking has no battery specified, we can't match it to a specific variant
            # Skip this booking as it's ambiguous
            
            # If both color and battery match, this variant is booked
            if color_matches and battery_matches:
                return True
        
        return False


class VehicleGroupedSerializer(serializers.Serializer):
    """Serializer for grouped vehicles by name"""
    name = serializers.CharField()
    colors_available = serializers.SerializerMethodField()
    battery_capacities_available = serializers.SerializerMethodField()
    price_range = serializers.SerializerMethodField()
    total_variants = serializers.SerializerMethodField()
    status_summary = serializers.SerializerMethodField()
    features = serializers.SerializerMethodField()
    specifications = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    variants = serializers.SerializerMethodField()
    
    def get_colors_available(self, obj):
        """Get all unique colors available across all variants"""
        colors_set = set()
        for vehicle in obj['variants']:
            if isinstance(vehicle.vehicle_color, list):
                colors_set.update(vehicle.vehicle_color)
        return sorted(list(colors_set))
    
    def get_battery_capacities_available(self, obj):
        """Get all unique battery capacities available across all variants"""
        batteries_set = set()
        for vehicle in obj['variants']:
            if isinstance(vehicle.battery_variant, list):
                batteries_set.update(vehicle.battery_variant)
        return sorted(list(batteries_set))
    
    def get_price_range(self, obj):
        """Get price range (min and max) across all variants"""
        prices = [float(vehicle.price) for vehicle in obj['variants'] if vehicle.price]
        if prices:
            return {
                'min': min(prices),
                'max': max(prices)
            }
        return {'min': None, 'max': None}
    
    def get_total_variants(self, obj):
        """Get total number of variants for this vehicle"""
        return len(obj['variants'])
    
    def get_status_summary(self, obj):
        """Get status summary across all variants"""
        status_counts = {}
        for vehicle in obj['variants']:
            status = vehicle.status or 'available'
            status_counts[status] = status_counts.get(status, 0) + 1
        return status_counts
    
    def get_features(self, obj):
        """Get aggregated features from all variants (unique features)"""
        features_set = set()
        for vehicle in obj['variants']:
            if isinstance(vehicle.features, list):
                features_set.update(vehicle.features)
        return sorted(list(features_set))
    
    def get_specifications(self, obj):
        """Get aggregated specifications from all variants (merge all specs)"""
        merged_specs = {}
        for vehicle in obj['variants']:
            if isinstance(vehicle.specifications, dict):
                # Merge specifications, keeping all unique keys
                merged_specs.update(vehicle.specifications)
        return merged_specs
    
    def get_description(self, obj):
        """Get description from first variant (or aggregated if needed)"""
        for vehicle in obj['variants']:
            if vehicle.description:
                return vehicle.description
        return None
    
    def get_variants(self, obj):
        """Serialize vehicle variants"""
        return VehicleVariantSerializer(obj['variants'], many=True, context=self.context).data


class VehicleStockSerializer(serializers.ModelSerializer):
    """Serializer for VehicleStock with enriched vehicle details"""
    vehicle_name = serializers.CharField(source='vehicle.name', read_only=True)
    vehicle_model_code = serializers.CharField(source='vehicle.model_code', read_only=True)
    reserved_quantity = serializers.SerializerMethodField()
    
    # Vehicle details
    vehicle_colors = serializers.SerializerMethodField()
    battery_variants = serializers.SerializerMethodField()
    features = serializers.SerializerMethodField()
    specifications = serializers.SerializerMethodField()
    description = serializers.CharField(source='vehicle.description', read_only=True)
    price = serializers.DecimalField(source='vehicle.price', max_digits=10, decimal_places=2, read_only=True)
    status = serializers.CharField(source='vehicle.status', read_only=True)
    primary_image_url = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    other_variants = serializers.SerializerMethodField()
    
    class Meta:
        model = VehicleStock
        fields = (
            'id', 'vehicle', 'vehicle_name', 'vehicle_model_code',
            'vehicle_colors', 'battery_variants', 'features', 'specifications',
            'description', 'price', 'status',
            'primary_image_url', 'images',
            'other_variants',
            'total_quantity', 'available_quantity', 'reserved_quantity',
            'created_at', 'updated_at'
        )
        read_only_fields = ('available_quantity', 'created_at', 'updated_at', 'reserved_quantity')
    
    def get_reserved_quantity(self, obj):
        """Calculate reserved quantity (always non-negative)"""
        reserved = obj.total_quantity - obj.available_quantity
        # Return 0 if calculation results in negative (data inconsistency)
        return max(0, reserved)
    
    def get_vehicle_colors(self, obj):
        """Get vehicle colors as an array"""
        if hasattr(obj, 'vehicle') and obj.vehicle:
            colors = obj.vehicle.vehicle_color
            if isinstance(colors, list):
                return colors
            return []
        return []
    
    def get_battery_variants(self, obj):
        """Get battery variants as an array"""
        if hasattr(obj, 'vehicle') and obj.vehicle:
            batteries = obj.vehicle.battery_variant
            if isinstance(batteries, list):
                return batteries
            return []
        return []
    
    def get_features(self, obj):
        """Get vehicle features as an array"""
        if hasattr(obj, 'vehicle') and obj.vehicle:
            features = obj.vehicle.features
            if isinstance(features, list):
                return features
            return []
        return []
    
    def get_specifications(self, obj):
        """Get vehicle specifications as a dictionary"""
        if hasattr(obj, 'vehicle') and obj.vehicle:
            specs = obj.vehicle.specifications
            if isinstance(specs, dict):
                return specs
            return {}
        return {}
    
    def get_primary_image_url(self, obj):
        """Return URL of primary image if exists"""
        if hasattr(obj, 'vehicle') and obj.vehicle:
            primary_image = obj.vehicle.images.filter(is_primary=True).first()
            if primary_image:
                request = self.context.get('request')
                if request:
                    return request.build_absolute_uri(primary_image.image.url)
                return primary_image.image.url
            # If no primary, return first image
            first_image = obj.vehicle.images.first()
            if first_image:
                request = self.context.get('request')
                if request:
                    return request.build_absolute_uri(first_image.image.url)
                return first_image.image.url
        return None
    
    def get_images(self, obj):
        """Return all images for this vehicle"""
        if not hasattr(obj, 'vehicle') or not obj.vehicle:
            return []
        
        # Access images through the relationship
        try:
            if hasattr(obj.vehicle, '_prefetched_objects_cache') and 'images' in obj.vehicle._prefetched_objects_cache:
                images = obj.vehicle._prefetched_objects_cache['images']
            else:
                # Query images directly
                images = list(obj.vehicle.images.all().order_by('order', '-is_primary', 'created_at'))
        except Exception:
            # Fallback if relationship access fails
            images = []
        
        request = self.context.get('request')
        result = []
        for img in images:
            if img and hasattr(img, 'image') and img.image:  # Only include images that have a file
                try:
                    image_url = img.image.url
                    if request:
                        image_url = request.build_absolute_uri(image_url)
                    result.append({
                        'id': img.id,
                        'image_url': image_url,
                        'is_primary': img.is_primary,
                        'alt_text': img.alt_text or '',
                        'order': img.order
                    })
                except Exception:
                    # Skip images that can't be serialized
                    continue
        return result
    
    def get_other_variants(self, obj):
        """Get all other variants of the same vehicle name"""
        if not hasattr(obj, 'vehicle') or not obj.vehicle:
            return []
        
        vehicle_name = obj.vehicle.name
        current_vehicle_id = obj.vehicle.id
        
        # Get all other vehicles with the same name, excluding current vehicle
        other_vehicles = Vehicle.objects.filter(
            name=vehicle_name
        ).exclude(
            id=current_vehicle_id
        ).prefetch_related('images', 'stock').order_by('-created_at')
        
        # Serialize using VehicleVariantSerializer
        variant_serializer = VehicleVariantSerializer(
            other_vehicles, 
            many=True, 
            context=self.context
        )
        return variant_serializer.data
    
    def validate_total_quantity(self, value):
        """Validate total_quantity"""
        if value < 0:
            raise serializers.ValidationError("Total quantity cannot be negative")
        
        # If updating, ensure total_quantity is not less than reserved quantity
        if self.instance:
            reserved = self.instance.total_quantity - self.instance.available_quantity
            if value < reserved:
                raise serializers.ValidationError(
                    f"Total quantity cannot be less than reserved quantity ({reserved})"
                )
            # Update available_quantity if total_quantity is increased
            if value > self.instance.total_quantity:
                # Increase available_quantity by the difference
                diff = value - self.instance.total_quantity
                self.instance.available_quantity += diff
        
        return value
    
    def update(self, instance, validated_data):
        """Update stock and adjust available_quantity if needed"""
        total_quantity = validated_data.get('total_quantity', instance.total_quantity)
        
        # Calculate current reserved quantity (can be negative if data is inconsistent)
        current_reserved = instance.total_quantity - instance.available_quantity
        
        # If total_quantity is being increased, increase available_quantity
        if total_quantity > instance.total_quantity:
            diff = total_quantity - instance.total_quantity
            instance.available_quantity += diff
        # If total_quantity is being decreased, decrease available_quantity (but not below reserved)
        elif total_quantity < instance.total_quantity:
            # Ensure reserved quantity is non-negative
            reserved = max(0, current_reserved)
            # Set available_quantity = total_quantity - reserved (but ensure it's not negative)
            instance.available_quantity = max(0, total_quantity - reserved)
            # Ensure available_quantity doesn't exceed total_quantity
            if instance.available_quantity > total_quantity:
                instance.available_quantity = total_quantity
        
        instance.total_quantity = total_quantity
        
        # Final safety check: ensure available_quantity doesn't exceed total_quantity
        if instance.available_quantity > instance.total_quantity:
            instance.available_quantity = instance.total_quantity
        
        instance.save()
        return instance

