from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ComplianceDocumentViewSet, TDSRecordViewSet,
    DistributorDocumentViewSet, DistributorDocumentAcceptanceViewSet
)

router = DefaultRouter()
router.register(r'documents', ComplianceDocumentViewSet, basename='compliance-document')
router.register(r'tds', TDSRecordViewSet, basename='tds-record')
router.register(r'distributor-documents', DistributorDocumentViewSet, basename='distributor-document')
router.register(r'distributor-document-acceptances', DistributorDocumentAcceptanceViewSet, basename='distributor-document-acceptance')

urlpatterns = [
    path('', include(router.urls)),
]

