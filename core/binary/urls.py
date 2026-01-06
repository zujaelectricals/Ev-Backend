from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BinaryNodeViewSet, BinaryPairViewSet, BinaryEarningViewSet

router = DefaultRouter()
router.register(r'nodes', BinaryNodeViewSet, basename='binary-node')
router.register(r'pairs', BinaryPairViewSet, basename='binary-pair')
router.register(r'earnings', BinaryEarningViewSet, basename='binary-earning')

urlpatterns = [
    path('', include(router.urls)),
]

