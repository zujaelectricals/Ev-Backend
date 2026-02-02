from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import GalleryItemViewSet

router = DefaultRouter()
router.register(r'gallery-items', GalleryItemViewSet, basename='gallery-item')

urlpatterns = [
    path('', include(router.urls)),
]

