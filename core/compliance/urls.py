from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ComplianceDocumentViewSet, TDSRecordViewSet,
    DistributorDocumentViewSet, DistributorDocumentAcceptanceViewSet,
    AsaTermsViewSet, UserAsaAcceptanceViewSet,
    PaymentTermsViewSet, UserPaymentAcceptanceViewSet
)

router = DefaultRouter()
router.register(r'documents', ComplianceDocumentViewSet, basename='compliance-document')
router.register(r'tds', TDSRecordViewSet, basename='tds-record')
router.register(r'distributor-documents', DistributorDocumentViewSet, basename='distributor-document')
router.register(r'distributor-document-acceptances', DistributorDocumentAcceptanceViewSet, basename='distributor-document-acceptance')

# Terms Acceptance routes
router.register(r'terms/asa', AsaTermsViewSet, basename='asa-terms')
router.register(r'terms/asa/acceptances', UserAsaAcceptanceViewSet, basename='asa-acceptance')
router.register(r'terms/payment', PaymentTermsViewSet, basename='payment-terms')
router.register(r'terms/payment/acceptances', UserPaymentAcceptanceViewSet, basename='payment-acceptance')

urlpatterns = [
    path('', include(router.urls)),
]

