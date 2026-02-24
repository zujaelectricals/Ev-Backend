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
    # Custom route to allow PUT/PATCH directly on /api/users/nominee/
    # This must come before the router URLs to take precedence
    path('nominee/', NomineeViewSet.as_view({'put': 'update_nominee', 'patch': 'update_nominee', 'get': 'list', 'post': 'create'}), name='nominee-list'),
    # Custom route for admin to get user documents
    path('documents/', UserViewSet.as_view({'get': 'get_user_documents'}), name='user-documents'),
    path('', include(router.urls)),
]

