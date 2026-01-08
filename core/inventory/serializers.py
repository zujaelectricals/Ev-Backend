from rest_framework import serializers
import json
from django.db import models as django_models
from .models import Vehicle, VehicleImage


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
        help_text='List of image IDs to link to this vehicle (images must be uploaded first)'
    )
    
    class Meta:
        model = Vehicle
        fields = (
            'id', 'name', 'model_code', 'vehicle_color', 'battery_variant',
            'price', 'status', 'description', 'features', 'specifications',
            'images', 'image_ids', 'primary_image_url', 'created_at', 'updated_at'
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
        
        return data
    
    def create(self, validated_data):
        """Create vehicle and link existing images by IDs"""
        image_ids = validated_data.pop('image_ids', [])
        
        # Ensure features and specifications have default values if None
        if 'features' not in validated_data or validated_data.get('features') is None:
            validated_data['features'] = []
        if 'specifications' not in validated_data or validated_data.get('specifications') is None:
            validated_data['specifications'] = {}
        # Ensure vehicle_color has default value if None
        if 'vehicle_color' not in validated_data or validated_data.get('vehicle_color') is None:
            validated_data['vehicle_color'] = ["white"]
        
        # Create vehicle
        vehicle = Vehicle.objects.create(**validated_data)
        
        # Link images to vehicle if image_ids provided
        if image_ids:
            # Get existing unlinked images
            images = VehicleImage.objects.filter(
                id__in=image_ids,
                vehicle__isnull=True
            ).order_by('id')  # Preserve order based on IDs
            
            # Link images to vehicle and set order
            for index, image in enumerate(images):
                image.vehicle = vehicle
                image.order = index
                # Set first image as primary if no primary exists
                if index == 0 and not vehicle.images.filter(is_primary=True).exists():
                    image.is_primary = True
                image.save()
        
        return vehicle
    
    def update(self, instance, validated_data):
        """Update vehicle and handle image linking"""
        image_ids = validated_data.pop('image_ids', None)
        
        # Ensure features and specifications have default values if None
        if 'features' in validated_data and validated_data.get('features') is None:
            validated_data['features'] = []
        if 'specifications' in validated_data and validated_data.get('specifications') is None:
            validated_data['specifications'] = {}
        # Ensure vehicle_color has default value if None
        if 'vehicle_color' in validated_data and validated_data.get('vehicle_color') is None:
            validated_data['vehicle_color'] = ["white"]
        
        # Update vehicle fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Handle image linking if image_ids provided
        if image_ids is not None:
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
        
        return instance


class VehicleListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for vehicle listing"""
    primary_image_url = serializers.SerializerMethodField()
    image_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Vehicle
        fields = (
            'id', 'name', 'model_code', 'vehicle_color', 'battery_variant',
            'price', 'status', 'features', 'specifications',
            'primary_image_url', 'image_count', 'created_at'
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

