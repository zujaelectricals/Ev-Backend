from django.urls import path
from .views import (
    send_otp, verify_otp_login, logout,
    signup, verify_signup_otp,
    create_admin, create_staff,
    send_admin_otp, verify_admin_otp_login,
    CustomTokenRefreshView
)

urlpatterns = [
    path('send-otp/', send_otp, name='send-otp'),
    path('verify-otp/', verify_otp_login, name='verify-otp'),
    path('send-admin-otp/', send_admin_otp, name='send-admin-otp'),
    path('verify-admin-otp/', verify_admin_otp_login, name='verify-admin-otp'),
    path('refresh/', CustomTokenRefreshView.as_view(), name='token-refresh'),
    path('logout/', logout, name='logout'),
    path('signup/', signup, name='signup'),
    path('verify-signup-otp/', verify_signup_otp, name='verify-signup-otp'),
    path('create-admin/', create_admin, name='create-admin'),
    path('create-staff/', create_staff, name='create-staff'),
]

