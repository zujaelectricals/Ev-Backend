from django.db import models
from django.conf import settings
from django.utils import timezone


class GalleryItem(models.Model):
    """
    Gallery model for displaying company members organized by levels/positions
    """
    title = models.CharField(max_length=200, help_text='Member name or title')
    image = models.ImageField(upload_to='gallery/images/', help_text='Member photo')
    caption = models.TextField(blank=True, help_text='Description or bio')
    level = models.CharField(
        max_length=100,
        help_text='Member level/position category (any text)'
    )
    order = models.IntegerField(
        default=0,
        help_text='Display order within level (lower numbers appear first)'
    )
    status = models.BooleanField(
        default=True,
        help_text='Active/Inactive status'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gallery_items',
        help_text='Admin/staff who added this item'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'gallery_items'
        verbose_name = 'Gallery Item'
        verbose_name_plural = 'Gallery Items'
        ordering = ['level', 'order', 'created_at']
        indexes = [
            models.Index(fields=['level', 'order']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.level}"

