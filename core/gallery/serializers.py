from rest_framework import serializers
from .models import GalleryItem


class GalleryItemSerializer(serializers.ModelSerializer):
    """Serializer for Gallery Items with image URL handling"""
    image_url = serializers.SerializerMethodField()
    created_by_username = serializers.SerializerMethodField()
    
    class Meta:
        model = GalleryItem
        fields = (
            'id', 'title', 'image', 'image_url', 'caption', 'level',
            'order', 'status', 'created_by', 'created_by_username',
            'created_at', 'updated_at'
        )
        read_only_fields = ('created_at', 'updated_at', 'created_by', 'created_by_username')
    
    def get_image_url(self, obj):
        """Return full URL for the image"""
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None
    
    def get_created_by_username(self, obj):
        """Return username of the user who created this item"""
        if obj.created_by:
            return obj.created_by.username
        return None
    
    def validate_image(self, value):
        """Validate that the uploaded file is an image"""
        if value:
            # Check file content type
            content_type = getattr(value, 'content_type', None)
            valid_image_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
            
            if content_type:
                if content_type not in valid_image_types:
                    raise serializers.ValidationError(
                        'Image must be a JPEG, PNG, GIF, or WEBP file.'
                    )
            else:
                # Fallback: check file extension if content_type is not available
                file_name = getattr(value, 'name', '')
                if file_name:
                    ext = file_name.lower().split('.')[-1]
                    valid_extensions = ['jpg', 'jpeg', 'png', 'gif', 'webp']
                    if ext not in valid_extensions:
                        raise serializers.ValidationError(
                            'Image must be a JPEG, PNG, GIF, or WEBP file.'
                        )
        
        return value

