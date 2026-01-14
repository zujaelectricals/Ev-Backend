from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import VehicleViewSet, upload_images, VehicleStockViewSet

router = DefaultRouter()
router.register(r'vehicles', VehicleViewSet, basename='vehicle')
router.register(r'stock', VehicleStockViewSet, basename='vehicle-stock')

urlpatterns = [
    # Image upload endpoint - must be before router to avoid conflicts
    path('images/upload/', upload_images, name='image-upload'),
    path('', include(router.urls)),
]

