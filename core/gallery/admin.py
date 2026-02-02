from django.contrib import admin
from django.utils.html import format_html
from .models import GalleryItem


@admin.register(GalleryItem)
class GalleryItemAdmin(admin.ModelAdmin):
    """Admin interface for Gallery Item model"""
    list_display = (
        'id', 'title', 'level', 'order', 'status', 'image_preview',
        'created_by', 'created_at'
    )
    list_filter = ('level', 'status', 'created_at', 'updated_at')
    search_fields = ('title', 'caption')
    readonly_fields = ('created_at', 'updated_at', 'image_preview', 'image_url')
    list_per_page = 25
    list_editable = ('status', 'order')  # Allow quick status and order changes
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'image', 'image_preview', 'image_url', 'caption')
        }),
        ('Organization', {
            'fields': ('level', 'order', 'status')
        }),
        ('Metadata', {
            'fields': ('created_by',)
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
                '<img src="{}" style="max-width: 100px; max-height: 100px; object-fit: cover; border-radius: 4px; border: 1px solid #ddd;" />',
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
        return qs.select_related('created_by')
    
    def save_model(self, request, obj, form, change):
        """Set created_by if not set (for new objects)"""
        if not change:  # New object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

