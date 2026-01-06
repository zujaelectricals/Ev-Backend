from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet, KYCViewSet, NomineeViewSet

router = DefaultRouter()
router.register(r'', UserViewSet, basename='user')
router.register(r'kyc', KYCViewSet, basename='kyc')
router.register(r'nominee', NomineeViewSet, basename='nominee')

urlpatterns = [
    path('', include(router.urls)),
]

