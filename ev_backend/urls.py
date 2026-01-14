"""
URL configuration for ev_backend project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('core.auth.urls')),
    path('api/users/', include('core.users.urls')),
    path('api/inventory/', include('core.inventory.urls')),
    path('api/booking/', include('core.booking.urls')),
    path('api/wallet/', include('core.wallet.urls')),
    path('api/binary/', include('core.binary.urls')),
    path('api/payout/', include('core.payout.urls')),
    path('api/notifications/', include('core.notification.urls')),
    path('api/compliance/', include('core.compliance.urls')),
    path('api/reports/', include('core.reports.urls')),
    path('api/settings/', include('core.settings.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

