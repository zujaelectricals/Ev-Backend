from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import Vehicle, VehicleImage


class VehicleImageInline(admin.TabularInline):
    """Inline admin for vehicle images"""
    model = VehicleImage
    extra = 1
    fields = ('image', 'image_preview', 'is_primary', 'alt_text', 'order')
    readonly_fields = ('image_preview', 'created_at', 'updated_at')
    
    def image_preview(self, obj):
        """Display image preview in inline"""
        if obj and obj.pk and obj.image:
            return format_html(
                '<img src="{}" style="max-width: 80px; max-height: 80px; object-fit: cover; border-radius: 4px;" />',
                obj.image.url
            )
        return 'No image'
    image_preview.short_description = 'Preview'


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    """Admin interface for Vehicle model"""
    list_display = (
        'id', 'name', 'model_code', 'vehicle_color_display', 'battery_variant', 
        'price_display', 'status', 'image_count', 'primary_image_preview', 'created_at'
    )
    list_filter = ('status', 'battery_variant', 'created_at', 'updated_at')
    search_fields = ('name', 'model_code', 'description', 'battery_variant')
    readonly_fields = ('created_at', 'updated_at', 'features_display', 'specifications_display')
    inlines = [VehicleImageInline]
    list_per_page = 25
    list_editable = ('status',)  # Allow quick status changes
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'model_code', 'vehicle_color', 'battery_variant', 'price', 'status')
        }),
        ('Details', {
            'fields': ('description', 'features', 'specifications')
        }),
        ('Features & Specifications Preview', {
            'fields': ('features_display', 'specifications_display'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def vehicle_color_display(self, obj):
        """Display vehicle colors in a readable format"""
        if obj.vehicle_color and isinstance(obj.vehicle_color, list) and len(obj.vehicle_color) > 0:
            colors = ", ".join(obj.vehicle_color)
            return format_html('<span style="font-weight: 500;">{}</span>', colors)
        return format_html('<span style="color: #999;">white</span>')
    vehicle_color_display.short_description = 'Colors'
    vehicle_color_display.admin_order_field = 'vehicle_color'
    
    def price_display(self, obj):
        """Display price with currency symbol"""
        return f"₹{obj.price:,.2f}"
    price_display.short_description = 'Price'
    price_display.admin_order_field = 'price'
    
    def image_count(self, obj):
        """Display count of images"""
        count = obj.images.count()
        if count > 0:
            return format_html('<span style="color: green; font-weight: bold;">{}</span>', count)
        return format_html('<span style="color: red;">{}</span>', count)
    image_count.short_description = 'Images'
    image_count.admin_order_field = 'images__count'
    
    def primary_image_preview(self, obj):
        """Display primary image thumbnail in list view"""
        primary_image = obj.images.filter(is_primary=True).first()
        if not primary_image:
            primary_image = obj.images.first()
        
        if primary_image and primary_image.image:
            return format_html(
                '<img src="{}" style="max-width: 60px; max-height: 60px; object-fit: cover; border-radius: 4px; border: 1px solid #ddd;" />',
                primary_image.image.url
            )
        return format_html('<span style="color: #999;">No image</span>')
    primary_image_preview.short_description = 'Image'
    
    def features_display(self, obj):
        """Display features in a readable format"""
        if obj.features and len(obj.features) > 0:
            features_html = '<ul style="margin: 0; padding-left: 20px;">'
            for feature in obj.features:
                features_html += f'<li>{feature}</li>'
            features_html += '</ul>'
            return mark_safe(features_html)
        return mark_safe('<span style="color: #999;">No features added</span>')
    features_display.short_description = 'Features Preview'
    
    def specifications_display(self, obj):
        """Display specifications in a readable format"""
        if obj.specifications and len(obj.specifications) > 0:
            specs_html = '<table style="width: 100%; border-collapse: collapse;">'
            for key, value in obj.specifications.items():
                specs_html += f'<tr><td style="padding: 5px; font-weight: bold; border-bottom: 1px solid #eee;">{key}:</td><td style="padding: 5px; border-bottom: 1px solid #eee;">{value}</td></tr>'
            specs_html += '</table>'
            return mark_safe(specs_html)
        return mark_safe('<span style="color: #999;">No specifications added</span>')
    specifications_display.short_description = 'Specifications Preview'
    
    class Media:
        css = {
            'all': ('admin/css/custom_admin.css',)
        }


@admin.register(VehicleImage)
class VehicleImageAdmin(admin.ModelAdmin):
    """Admin interface for VehicleImage model"""
    list_display = ('id', 'vehicle', 'image_preview', 'is_primary', 'alt_text', 'order', 'created_at')
    list_filter = ('is_primary', 'created_at', 'updated_at', 'vehicle__status')
    search_fields = ('vehicle__name', 'vehicle__model_code', 'alt_text', 'image')
    readonly_fields = ('created_at', 'updated_at', 'image_preview', 'image_url')
    list_per_page = 25
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Image Information', {
            'fields': ('vehicle', 'image', 'image_preview', 'image_url', 'is_primary', 'alt_text', 'order')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def image_preview(self, obj):
        """Display image preview in admin"""
        if obj and obj.image:
            return format_html(
                '<img src="{}" style="max-width: 300px; max-height: 300px; object-fit: contain; border: 1px solid #ddd; border-radius: 4px; padding: 5px;" />',
                obj.image.url
            )
        return format_html('<span style="color: #999;">No image</span>')
    image_preview.short_description = 'Preview'
    
    def image_url(self, obj):
        """Display image URL"""
        if obj and obj.image:
            return format_html(
                '<a href="{}" target="_blank">{}</a>',
                obj.image.url,
                obj.image.url
            )
        return '-'
    image_url.short_description = 'Image URL'
    
    def get_queryset(self, request):
        """Optimize queryset with select_related"""
        qs = super().get_queryset(request)
        return qs.select_related('vehicle')

