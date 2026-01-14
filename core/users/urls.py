from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet, KYCViewSet, NomineeViewSet, DistributorApplicationViewSet

router = DefaultRouter()
# Register more specific routes first
router.register(r'distributor-application', DistributorApplicationViewSet, basename='distributor-application')
router.register(r'kyc', KYCViewSet, basename='kyc')
router.register(r'nominee', NomineeViewSet, basename='nominee')
router.register(r'', UserViewSet, basename='user')

urlpatterns = [
    path('', include(router.urls)),
]

