from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ComplianceDocumentViewSet, TDSRecordViewSet

router = DefaultRouter()
router.register(r'documents', ComplianceDocumentViewSet, basename='compliance-document')
router.register(r'tds', TDSRecordViewSet, basename='tds-record')

urlpatterns = [
    path('', include(router.urls)),
]

