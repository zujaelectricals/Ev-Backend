from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser, BasePermission
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from django.contrib.auth import get_user_model
from .serializers import (
    SendOTPSerializer, VerifyOTPSerializer, RefreshTokenSerializer,
    SignupSerializer, VerifySignupOTPSerializer,
    CreateAdminSerializer, CreateStaffSerializer,
    SendAdminOTPSerializer, VerifyAdminOTPSerializer,
    SendUniversalOTPSerializer, VerifyUniversalOTPSerializer
)
from .throttles import OTPRateThrottle, OTPIdentifierThrottle

User = get_user_model()


class IsSuperuser(BasePermission):
    """
    Permission check for superuser only
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_superuser


class CustomTokenRefreshView(TokenRefreshView):
    """
    Custom token refresh view that blacklists the old refresh token
    before generating new tokens, ensuring old tokens cannot be reused.
    """
    def post(self, request, *args, **kwargs):
        # Get the old refresh token from the request
        old_refresh_token = request.data.get('refresh')
        
        if not old_refresh_token:
            return Response(
                {'detail': 'Refresh token is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate and extract user from old token before blacklisting
        try:
            old_token = RefreshToken(old_refresh_token)
            user_id = old_token.get('user_id')
            
            # Get the user
            try:
                user = User.objects.get(pk=user_id)
            except User.DoesNotExist:
                return Response(
                    {'detail': 'User not found.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check if token is already blacklisted before attempting to blacklist
            # The RefreshToken constructor should catch this, but we handle it explicitly
            try:
                # Blacklist the old refresh token
                old_token.blacklist()
            except TokenError as e:
                # Token might already be blacklisted
                error_msg = str(e)
                if 'blacklisted' in error_msg.lower():
                    return Response(
                        {'detail': 'This refresh token has already been used. Please login again to get a new token.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                raise  # Re-raise if it's a different TokenError
            
        except TokenError as e:
            error_msg = str(e)
            if 'blacklisted' in error_msg.lower():
                return Response(
                    {'detail': 'This refresh token has already been used. Please login again to get a new token.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            return Response(
                {'detail': f'Invalid token: {error_msg}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'detail': f'Invalid token: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate new tokens for the user
        new_refresh = RefreshToken.for_user(user)
        
        return Response({
            'refresh': str(new_refresh),
            'access': str(new_refresh.access_token),
        }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([OTPRateThrottle, OTPIdentifierThrottle])
def send_otp(request):
    """
    Send OTP to email or mobile
    Rate limited to 5 requests per minute per IP and per identifier
    """
    serializer = SendOTPSerializer(data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        return Response(result, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([OTPRateThrottle, OTPIdentifierThrottle])
def verify_otp_login(request):
    """
    Verify OTP and login user (returns JWT tokens)
    Rate limited to 5 requests per minute per IP and per identifier
    Only for existing users with role='user'
    """
    serializer = VerifyOTPSerializer(data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        user_data = {
            'id': result['user'].id,
            'username': result['user'].username,
            'email': result['user'].email,
            'mobile': result['user'].mobile,
            'role': result['user'].role,
            'is_active_buyer': result['user'].is_active_buyer,
            'is_distributor': result['user'].is_distributor,
        }
        return Response({
            'user': user_data,
            'tokens': result['tokens']
        }, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([OTPRateThrottle, OTPIdentifierThrottle])
def send_admin_otp(request):
    """
    Send OTP to admin/staff users only
    Rate limited to 5 requests per minute per IP and per identifier
    """
    serializer = SendAdminOTPSerializer(data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        return Response(result, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([OTPRateThrottle, OTPIdentifierThrottle])
def verify_admin_otp_login(request):
    """
    Verify OTP and login admin/staff users (returns JWT tokens)
    Rate limited to 5 requests per minute per IP and per identifier
    Only for existing users with role='admin' or 'staff'
    """
    serializer = VerifyAdminOTPSerializer(data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        user_data = {
            'id': result['user'].id,
            'username': result['user'].username,
            'email': result['user'].email,
            'mobile': result['user'].mobile,
            'role': result['user'].role,
            'is_active_buyer': result['user'].is_active_buyer,
            'is_distributor': result['user'].is_distributor,
        }
        return Response({
            'user': user_data,
            'tokens': result['tokens']
        }, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """
    Logout user (blacklist refresh token)
    """
    try:
        refresh_token = request.data.get('refresh')
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
        return Response({'message': 'Successfully logged out'}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([OTPRateThrottle, OTPIdentifierThrottle])
def signup(request):
    """
    User signup - Submit details and receive OTP
    Rate limited to 5 requests per minute per IP and per identifier
    """
    serializer = SignupSerializer(data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        return Response(result, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([OTPRateThrottle, OTPIdentifierThrottle])
def verify_signup_otp(request):
    """
    Verify signup OTP and create user account
    Rate limited to 5 requests per minute per IP and per identifier
    """
    serializer = VerifySignupOTPSerializer(data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        user_data = {
            'id': result['user'].id,
            'username': result['user'].username,
            'email': result['user'].email,
            'mobile': result['user'].mobile,
            'first_name': result['user'].first_name,
            'last_name': result['user'].last_name,
            'role': result['user'].role,
            'is_active_buyer': result['user'].is_active_buyer,
            'is_distributor': result['user'].is_distributor,
        }
        return Response({
            'user': user_data,
            'tokens': result['tokens']
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsSuperuser])
def create_admin(request):
    """
    Create admin user (superuser only)
    """
    serializer = CreateAdminSerializer(data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        user_data = {
            'id': result['user'].id,
            'username': result['user'].username,
            'email': result['user'].email,
            'mobile': result['user'].mobile,
            'first_name': result['user'].first_name,
            'last_name': result['user'].last_name,
            'role': result['user'].role,
        }
        return Response({
            'user': user_data,
            'message': result['message']
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def create_staff(request):
    """
    Create staff user (admin or superuser)
    """
    serializer = CreateStaffSerializer(data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        user_data = {
            'id': result['user'].id,
            'username': result['user'].username,
            'email': result['user'].email,
            'mobile': result['user'].mobile,
            'first_name': result['user'].first_name,
            'last_name': result['user'].last_name,
            'role': result['user'].role,
        }
        return Response({
            'user': user_data,
            'message': result['message']
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([OTPRateThrottle, OTPIdentifierThrottle])
def send_universal_otp(request):
    """
    Send OTP to any existing user (all roles: admin, staff, user)
    Rate limited to 5 requests per minute per IP and per identifier
    """
    serializer = SendUniversalOTPSerializer(data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        return Response(result, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([OTPRateThrottle, OTPIdentifierThrottle])
def verify_universal_otp(request):
    """
    Verify OTP for any existing user (all roles: admin, staff, user)
    Rate limited to 5 requests per minute per IP and per identifier
    Returns success/failure only - does not issue JWT tokens
    """
    serializer = VerifyUniversalOTPSerializer(data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        return Response(result, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

