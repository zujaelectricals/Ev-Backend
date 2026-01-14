from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import User, KYC, Nominee, DistributorApplication
from .serializers import UserSerializer, UserProfileSerializer, KYCSerializer, NomineeSerializer, DistributorApplicationSerializer


class UserViewSet(viewsets.ModelViewSet):
    """
    ViewSet for User management
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return User.objects.all()
        elif user.role == 'staff':
            return User.objects.all()  # Staff can see all users to edit normal users
        return User.objects.filter(id=user.id)
    
    def perform_update(self, serializer):
        """Hierarchical permission system for profile updates:
        - Admin/Superuser: Can edit any profile
        - Staff: Can edit their own profile or normal users' profiles (but not admin/staff)
        - Normal users: Can only edit their own profile
        
        How it works:
        - When calling PUT/PATCH /api/users/{id}/, the {id} is the database primary key (unique ID)
        - Django REST Framework retrieves the User object with that ID from the database
        - serializer.instance contains the User object being updated (retrieved by ID from URL)
        - instance.role is a field on the User model that identifies if it's 'admin', 'staff', or 'user'
        - user (self.request.user) is the authenticated user making the request
        - Permission is checked by comparing the requesting user's role with the target user's role
        
        Example:
        - PUT /api/users/5/ with admin token
        - DRF retrieves User with id=5 (could be admin, staff, or user - doesn't matter for admin)
        - Admin can edit any user, so update proceeds
        """
        user = self.request.user  # The authenticated user making the request
        instance = serializer.instance  # The User object being updated (retrieved by ID from URL)
        
        # Admin/Superuser: Can edit anyone (no role check needed for target user)
        if user.is_superuser or user.role == 'admin':
            serializer.save()
        # Staff: Can edit themselves or normal users (but not admin/staff)
        elif user.role == 'staff':
            if instance.id == user.id:
                serializer.save()  # Can edit own profile
            elif instance.role == 'user':
                # instance.role identifies the target user as a normal user
                serializer.save()  # Can edit normal users
            else:
                # instance.role is 'admin' or 'staff' - staff cannot edit these
                raise PermissionDenied("Staff can only edit their own profile or normal users' profiles.")
        # Normal users: Can only edit themselves
        elif instance.id == user.id:
            serializer.save()
        else:
            raise PermissionDenied("You can only update your own profile.")
    
    def perform_partial_update(self, serializer):
        """Hierarchical permission system - delegates to perform_update()"""
        self.perform_update(serializer)

    def perform_deletion(self, serializer):
        """Hierarchical permission system for user deletion:
        - Admin/Superuser: Can delete any user
        - Staff: Can delete their own profile or normal users' profiles (but not admin/staff)
        - Normal users: Can only delete themselves
        """
        user = self.request.user
        instance = serializer.instance
        if user.is_superuser or user.role == 'admin':
            instance.delete()
        elif user.role == 'staff':
            if instance.id == user.id:
                instance.delete()
            elif instance.role == 'user':
                instance.delete()
            else:
                raise PermissionDenied("Staff can only delete their own profile or normal users' profiles.")
        elif instance.id == user.id:
            instance.delete()
        else:
            raise PermissionDenied("You can only delete your own profile.")
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def profile(self, request):
        """Get current user's profile"""
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)
    
    @action(detail=False, methods=['put', 'patch'], permission_classes=[IsAuthenticated])
    def update_profile(self, request):
        """Update current user's profile"""
        serializer = UserProfileSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def admins(self, request):
        """List admin users. Only superuser can access this endpoint."""
        user = request.user
        
        # Only superuser can list admins
        if not user.is_superuser:
            raise PermissionDenied("Only superuser can list admin users.")
        
        admins = User.objects.filter(role='admin').order_by('id')
        page = self.paginate_queryset(admins)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(admins, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def staff(self, request):
        """List staff users. Superuser and admin can access this endpoint."""
        user = request.user
        
        # Superuser and admin can list staff
        if not (user.is_superuser or user.role == 'admin'):
            raise PermissionDenied("Only superuser and admin can list staff users.")
        
        staff_users = User.objects.filter(role='staff').order_by('id')
        page = self.paginate_queryset(staff_users)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(staff_users, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def normal(self, request):
        """List normal users. Superuser, admin, and staff can access this endpoint."""
        user = request.user
        
        # Superuser, admin, and staff can list normal users
        if not (user.is_superuser or user.role == 'admin' or user.role == 'staff'):
            raise PermissionDenied("Only superuser, admin, and staff can list normal users.")
        
        normal_users = User.objects.filter(role='user').order_by('id')
        page = self.paginate_queryset(normal_users)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(normal_hUserV, many=True)
        return Response(serializer.data)


class KYCViewSet(viewsets.ModelViewSet):
    """
    ViewSet for KYC management
    """
    queryset = KYC.objects.all()
    serializer_class = KYCSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']
    
    def get_queryset(self):
        """
        Hierarchical permission system for KYC access:
        - Admin/Superuser: Can view all KYC records (admin, staff, and normal users)
        - Staff: Can view their own KYC + normal users' KYC (but NOT admin/staff KYC)
        - Normal Users: Can only view their own KYC record
        """
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return KYC.objects.all()
        elif user.role == 'staff':
            # Staff can see their own KYC and normal users' KYC
            return KYC.objects.filter(
                Q(user=user) | Q(user__role='user')
            )
        else:
            # Normal users can only see their own KYC
            return KYC.objects.filter(user=user)
    
    def create(self, request, *args, **kwargs):
        """Create or update KYC (since it's OneToOneField, update if exists)"""
        user = request.user
        try:
            # Check if KYC already exists for this user
            kyc = KYC.objects.get(user=user)
            # If exists, update it
            serializer = self.get_serializer(kyc, data=request.data, partial=False)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        except KYC.DoesNotExist:
            # If doesn't exist, create new one
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(user=user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def approve(self, request, pk=None):
        """Approve KYC"""
        kyc = self.get_object()
        kyc.status = 'approved'
        kyc.reviewed_by = request.user
        kyc.reviewed_at = timezone.now()
        kyc.save()
        return Response({'status': 'approved'})
    
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def reject(self, request, pk=None):
        """Reject KYC"""
        kyc = self.get_object()
        kyc.status = 'rejected'
        kyc.reviewed_by = request.user
        kyc.reviewed_at = timezone.now()
        kyc.rejection_reason = request.data.get('reason', '')
        kyc.save()
        return Response({'status': 'rejected'})
    
    @action(detail=False, methods=['get'], permission_classes=[IsAdminUser])
    def list_all(self, request):
        """
        List all KYC documents with filtering (Admin only)
        Supports filtering by status, date ranges, user_id, user_role, and ordering
        """
        queryset = KYC.objects.all().select_related('user', 'reviewed_by')
        
        # Filter by status
        status = request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        # Filter by submission date range
        submitted_date_from = request.query_params.get('submitted_date_from')
        submitted_date_to = request.query_params.get('submitted_date_to')
        if submitted_date_from:
            # Use date lookup to handle date string properly with DateTimeField
            queryset = queryset.filter(submitted_at__date__gte=submitted_date_from)
        if submitted_date_to:
            queryset = queryset.filter(submitted_at__date__lte=submitted_date_to)
        
        # Filter by review date range
        reviewed_date_from = request.query_params.get('reviewed_date_from')
        reviewed_date_to = request.query_params.get('reviewed_date_to')
        if reviewed_date_from:
            queryset = queryset.filter(reviewed_at__date__gte=reviewed_date_from)
        if reviewed_date_to:
            queryset = queryset.filter(reviewed_at__date__lte=reviewed_date_to)
        
        # Filter by user ID
        user_id = request.query_params.get('user_id')
        if user_id:
            try:
                queryset = queryset.filter(user_id=int(user_id))
            except (ValueError, TypeError):
                pass  # Invalid user_id, ignore filter
        
        # Filter by user role
        user_role = request.query_params.get('user_role')
        if user_role:
            queryset = queryset.filter(user__role=user_role)
        
        # Ordering
        ordering = request.query_params.get('ordering', '-submitted_at')
        if ordering:
            queryset = queryset.order_by(ordering)
        
        # Pagination
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class NomineeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Nominee management
    """
    queryset = Nominee.objects.all()
    serializer_class = NomineeSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return Nominee.objects.all()
        return Nominee.objects.filter(user=user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def approve(self, request, pk=None):
        """Approve nominee KYC (Admin only)"""
        nominee = self.get_object()
        nominee.kyc_status = 'verified'
        nominee.kyc_verified_by = request.user
        from django.utils import timezone
        nominee.kyc_verified_at = timezone.now()
        nominee.save()
        return Response({'status': 'verified'})

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def reject(self, request, pk=None):
        """Reject nominee KYC (Admin only)"""
        nominee = self.get_object()
        nominee.kyc_status = 'rejected'
        nominee.kyc_verified_by = request.user
        nominee.kyc_rejection_reason = request.data.get('reason', '')
        nominee.save()
        return Response({'status': 'rejected'})


class DistributorApplicationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Distributor Application management
    """
    queryset = DistributorApplication.objects.all()
    serializer_class = DistributorApplicationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options']
    
    def get_queryset(self):
        """
        Permission-based queryset:
        - Admin/Superuser: Can view all applications
        - Staff: Can view all applications
        - Normal Users: Can only view their own application
        """
        user = self.request.user
        if user.is_superuser or user.role in ['admin', 'staff']:
            return DistributorApplication.objects.all().select_related('user', 'reviewed_by')
        else:
            return DistributorApplication.objects.filter(user=user).select_related('user', 'reviewed_by')
    
    def list(self, request, *args, **kwargs):
        """List distributor applications (user sees own, admin/staff see all)"""
        queryset = self.filter_queryset(self.get_queryset())
        
        # For normal users, return their application if it exists
        if not (request.user.is_superuser or request.user.role in ['admin', 'staff']):
            # Normal users can only see their own application
            application = queryset.first()
            if application:
                serializer = self.get_serializer(application)
                return Response(serializer.data)
            else:
                return Response({'detail': 'No application found.'}, status=status.HTTP_404_NOT_FOUND)
        
        # For admin/staff, return paginated list
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    def create(self, request, *args, **kwargs):
        """Create distributor application with eligibility validation"""
        user = request.user
        
        # Check eligibility
        if not user.is_active_buyer:
            return Response(
                {'non_field_errors': ['User must be an Active Buyer to apply for distributor program. Total paid amount must be at least ₹5000.']},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not hasattr(user, 'kyc') or user.kyc.status != 'approved':
            return Response(
                {'non_field_errors': ['User must have approved KYC to apply for distributor program.']},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if hasattr(user, 'distributor_application'):
            return Response(
                {'non_field_errors': ['Application already exists. You can only submit one distributor application.']},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def approve(self, request, pk=None):
        """Approve distributor application (Admin/Staff only)"""
        application = self.get_object()
        
        if application.status == 'approved':
            return Response(
                {'error': 'Application is already approved'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        application.status = 'approved'
        application.reviewed_by = request.user
        application.reviewed_at = timezone.now()
        application.rejection_reason = ''  # Clear rejection reason if any
        application.save()
        
        # Set user as distributor
        user = application.user
        user.is_distributor = True
        user.save(update_fields=['is_distributor'])
        
        return Response({
            'status': 'approved',
            'message': f'Application approved. User {user.username} is now a distributor.'
        })
    
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def reject(self, request, pk=None):
        """Reject distributor application (Admin/Staff only)"""
        application = self.get_object()
        
        if application.status == 'rejected':
            return Response(
                {'error': 'Application is already rejected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        application.status = 'rejected'
        application.reviewed_by = request.user
        application.reviewed_at = timezone.now()
        application.rejection_reason = request.data.get('reason', '')
        application.save()
        
        return Response({
            'status': 'rejected',
            'message': 'Application rejected.'
        })
    
    @action(detail=False, methods=['get'], permission_classes=[IsAdminUser])
    def list_all(self, request):
        """
        List all distributor applications with filtering (Admin only)
        Supports filtering by status, date ranges, user_id, and ordering
        """
        queryset = DistributorApplication.objects.all().select_related('user', 'reviewed_by')
        
        # Filter by status
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by submission date range
        submitted_date_from = request.query_params.get('submitted_date_from')
        submitted_date_to = request.query_params.get('submitted_date_to')
        if submitted_date_from:
            queryset = queryset.filter(submitted_at__date__gte=submitted_date_from)
        if submitted_date_to:
            queryset = queryset.filter(submitted_at__date__lte=submitted_date_to)
        
        # Filter by review date range
        reviewed_date_from = request.query_params.get('reviewed_date_from')
        reviewed_date_to = request.query_params.get('reviewed_date_to')
        if reviewed_date_from:
            queryset = queryset.filter(reviewed_at__date__gte=reviewed_date_from)
        if reviewed_date_to:
            queryset = queryset.filter(reviewed_at__date__lte=reviewed_date_to)
        
        # Filter by user ID
        user_id = request.query_params.get('user_id')
        if user_id:
            try:
                queryset = queryset.filter(user_id=int(user_id))
            except (ValueError, TypeError):
                pass  # Invalid user_id, ignore filter
        
        # Ordering
        ordering = request.query_params.get('ordering', '-submitted_at')
        if ordering:
            queryset = queryset.order_by(ordering)
        
        # Pagination
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

