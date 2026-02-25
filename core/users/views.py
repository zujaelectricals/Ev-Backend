from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from datetime import datetime
from rest_framework.exceptions import ValidationError
from .models import User, KYC, Nominee, DistributorApplication
from .serializers import UserSerializer, UserProfileSerializer, KYCSerializer, NomineeSerializer, DistributorApplicationSerializer, UnifiedKYCSerializer
from core.settings.models import PlatformSettings


class DistributorApplicationPagination(PageNumberPagination):
    """Custom pagination for distributor application list with page_size support"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'


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
        try:
            # Refresh user from database to ensure all fields are loaded
            # Use select_related for ForeignKey (referred_by) and OneToOneField (binary_node, nominee)
            user = User.objects.select_related('referred_by', 'binary_node', 'nominee').get(pk=request.user.pk)
        except User.DoesNotExist:
            return Response(
                {'detail': 'User not found', 'code': 'user_not_found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # The serializer will handle OneToOneField reverse relationships (kyc) safely
        serializer = UserProfileSerializer(user, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=False, methods=['put', 'patch'], permission_classes=[IsAuthenticated])
    def update_profile(self, request):
        """Update current user's profile"""
        # Get fresh user instance from database
        user = User.objects.select_related('referred_by').get(pk=request.user.pk)
        serializer = UserProfileSerializer(user, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            # Refresh user from database to ensure all fields are loaded
            user.refresh_from_db()
            # Return updated data with fresh serializer instance
            serializer = UserProfileSerializer(user, context={'request': request})
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
        """List normal users. Superuser, admin, and staff can access this endpoint.
        Supports filtering by is_distributor, date_joined, search (name), and ordering.
        """
        user = request.user
        
        # Superuser, admin, and staff can list normal users
        if not (user.is_superuser or user.role == 'admin' or user.role == 'staff'):
            raise PermissionDenied("Only superuser, admin, and staff can list normal users.")
        
        # Use select_related to optimize KYC queries and avoid N+1 problem
        queryset = User.objects.select_related('kyc').filter(role='user')
        
        # Filter by is_distributor
        is_distributor_param = request.query_params.get('is_distributor')
        if is_distributor_param:
            if is_distributor_param.lower() == 'true':
                queryset = queryset.filter(is_distributor=True)
            elif is_distributor_param.lower() == 'false':
                queryset = queryset.filter(is_distributor=False)
        
        # Filter by date_joined range
        date_joined_from = request.query_params.get('date_joined_from')
        date_joined_to = request.query_params.get('date_joined_to')
        if date_joined_from:
            try:
                queryset = queryset.filter(date_joined__date__gte=date_joined_from)
            except (ValueError, TypeError):
                pass  # Invalid date format, ignore filter
        if date_joined_to:
            try:
                queryset = queryset.filter(date_joined__date__lte=date_joined_to)
            except (ValueError, TypeError):
                pass  # Invalid date format, ignore filter
        
        # Search by user name (first_name, last_name, username, email)
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(username__icontains=search) |
                Q(email__icontains=search)
            )
        
        # Ordering - validate ordering fields to prevent SQL injection
        ordering = request.query_params.get('ordering', 'id')
        if ordering:
            # Allow only safe ordering fields
            allowed_ordering_fields = [
                'id', '-id',
                'date_joined', '-date_joined',
                'username', '-username',
                'email', '-email',
                'first_name', '-first_name',
                'last_name', '-last_name'
            ]
            if ordering in allowed_ordering_fields:
                queryset = queryset.order_by(ordering)
            else:
                # Default to id if invalid ordering
                queryset = queryset.order_by('id')
        else:
            queryset = queryset.order_by('id')
        
        # Pagination
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated], url_path='documents')
    def get_user_documents(self, request):
        """
        Get all document URLs for a specific user (Admin only)
        Query parameter: user_id (required)
        Returns: asa_document_acceptance_url, payment_receipt_urls, payment_terms_acceptance_document_url
        """
        # Check if user is admin or superuser
        if not (request.user.is_superuser or request.user.role == 'admin'):
            raise PermissionDenied("Only admin users can access this endpoint.")
        
        # Get user_id from query parameters
        user_id = request.query_params.get('user_id')
        if not user_id:
            return Response(
                {'error': 'user_id query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get the target user
        try:
            target_user = User.objects.get(id=user_id)
        except (User.DoesNotExist, ValueError):
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Use UserProfileSerializer to get document URLs
        serializer = UserProfileSerializer(target_user, context={'request': request})
        
        # Extract only the document URLs
        documents = {
            'user_id': target_user.id,
            'user_email': target_user.email,
            'user_full_name': target_user.get_full_name(),
            'asa_document_acceptance_url': serializer.data.get('asa_document_acceptance_url'),
            'payment_receipt_urls': serializer.data.get('payment_receipt_urls', []),
            'payment_terms_acceptance_document_url': serializer.data.get('payment_terms_acceptance_document_url'),
        }
        
        return Response(documents)


class KYCViewSet(viewsets.ModelViewSet):
    """
    ViewSet for KYC management
    """
    queryset = KYC.objects.select_related('user', 'reviewed_by').all()
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
            return KYC.objects.select_related('user', 'reviewed_by').all()
        elif user.role == 'staff':
            # Staff can see their own KYC and normal users' KYC
            return KYC.objects.select_related('user', 'reviewed_by').filter(
                Q(user=user) | Q(user__role='user')
            )
        else:
            # Normal users can only see their own KYC
            return KYC.objects.select_related('user', 'reviewed_by').filter(user=user)
    
    def create(self, request, *args, **kwargs):
        """Create or update KYC (since it's OneToOneField, update if exists)"""
        user = request.user
        kyc = KYC.objects.filter(user=user).first()
        if kyc:
            # If exists, update it
            serializer = self.get_serializer(kyc, data=request.data, partial=False)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        # If doesn't exist, create new one
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser], url_path='update-status')
    def update_status(self, request, pk=None):
        """Update KYC status - approve or reject (Admin only)"""
        kyc = self.get_object()
        new_status = request.data.get('status')
        
        # Validate status
        if new_status not in ['approved', 'rejected']:
            return Response(
                {'error': "Invalid status. Must be 'approved' or 'rejected'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if already in the requested status
        if kyc.status == new_status:
            status_message = 'approved' if new_status == 'approved' else 'rejected'
            return Response(
                {'error': f'KYC is already {status_message}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update KYC status
        kyc.status = new_status
        kyc.reviewed_by = request.user
        kyc.reviewed_at = timezone.now()
        
        if new_status == 'approved':
            # Clear rejection reason if approving
            kyc.rejection_reason = ''
        else:  # rejected
            # Set rejection reason if provided
            kyc.rejection_reason = request.data.get('reason', '')
        
        kyc.save()
        return Response({'status': new_status})
    
    @action(detail=False, methods=['get'], permission_classes=[IsAdminUser])
    def list_all(self, request):
        """
        List all KYC documents (both User KYC and Nominee KYC) with filtering (Admin only)
        Supports filtering by status, date ranges, user_id, user_role, kyc_type, and ordering
        """
        # Get User KYC queryset
        kyc_queryset = KYC.objects.all().select_related('user', 'reviewed_by')
        
        # Get Nominee queryset (only those with KYC submitted)
        nominee_queryset = Nominee.objects.filter(
            kyc_submitted_at__isnull=False
        ).select_related('user', 'kyc_verified_by')
        
        # Filter by status
        status_param = request.query_params.get('status')
        if status_param:
            # Map status for KYC (approved) vs Nominee (verified)
            if status_param == 'approved':
                kyc_queryset = kyc_queryset.filter(status='approved')
                nominee_queryset = nominee_queryset.filter(kyc_status='verified')
            elif status_param == 'pending':
                kyc_queryset = kyc_queryset.filter(status='pending')
                nominee_queryset = nominee_queryset.filter(kyc_status='pending')
            elif status_param == 'rejected':
                kyc_queryset = kyc_queryset.filter(status='rejected')
                nominee_queryset = nominee_queryset.filter(kyc_status='rejected')
        
        # Filter by submission date range
        submitted_date_from = request.query_params.get('submitted_date_from')
        submitted_date_to = request.query_params.get('submitted_date_to')
        if submitted_date_from:
            kyc_queryset = kyc_queryset.filter(submitted_at__date__gte=submitted_date_from)
            nominee_queryset = nominee_queryset.filter(kyc_submitted_at__date__gte=submitted_date_from)
        if submitted_date_to:
            kyc_queryset = kyc_queryset.filter(submitted_at__date__lte=submitted_date_to)
            nominee_queryset = nominee_queryset.filter(kyc_submitted_at__date__lte=submitted_date_to)
        
        # Filter by review date range
        reviewed_date_from = request.query_params.get('reviewed_date_from')
        reviewed_date_to = request.query_params.get('reviewed_date_to')
        if reviewed_date_from:
            kyc_queryset = kyc_queryset.filter(reviewed_at__date__gte=reviewed_date_from)
            nominee_queryset = nominee_queryset.filter(kyc_verified_at__date__gte=reviewed_date_from)
        if reviewed_date_to:
            kyc_queryset = kyc_queryset.filter(reviewed_at__date__lte=reviewed_date_to)
            nominee_queryset = nominee_queryset.filter(kyc_verified_at__date__lte=reviewed_date_to)
        
        # Filter by user ID
        user_id = request.query_params.get('user_id')
        if user_id:
            try:
                user_id_int = int(user_id)
                kyc_queryset = kyc_queryset.filter(user_id=user_id_int)
                nominee_queryset = nominee_queryset.filter(user_id=user_id_int)
            except (ValueError, TypeError):
                pass  # Invalid user_id, ignore filter
        
        # Filter by user role
        user_role = request.query_params.get('user_role')
        if user_role:
            kyc_queryset = kyc_queryset.filter(user__role=user_role)
            nominee_queryset = nominee_queryset.filter(user__role=user_role)
        
        # Filter by kyc_type (user or nominee)
        kyc_type = request.query_params.get('kyc_type')
        if kyc_type == 'user':
            nominee_queryset = Nominee.objects.none()
        elif kyc_type == 'nominee':
            kyc_queryset = KYC.objects.none()
        
        # Convert to unified format
        unified_data = []
        
        # Add User KYC records
        for kyc in kyc_queryset:
            unified_data.append(UnifiedKYCSerializer.from_kyc(kyc, request))
        
        # Add Nominee KYC records
        for nominee in nominee_queryset:
            unified_data.append(UnifiedKYCSerializer.from_nominee(nominee, request))
        
        # Ordering
        ordering = request.query_params.get('ordering', '-submitted_at')
        if ordering:
            reverse = ordering.startswith('-')
            field = ordering.lstrip('-')
            
            # Map field names for sorting
            # Use a very old datetime for None values to sort them last
            min_datetime = timezone.make_aware(datetime.min)
            if field == 'submitted_at':
                unified_data.sort(
                    key=lambda x: x['submitted_at'] if x['submitted_at'] else min_datetime,
                    reverse=reverse
                )
            elif field == 'reviewed_at':
                unified_data.sort(
                    key=lambda x: x['reviewed_at'] if x['reviewed_at'] else min_datetime,
                    reverse=reverse
                )
            elif field == 'status':
                unified_data.sort(key=lambda x: x['status'], reverse=reverse)
            else:
                # Default to submitted_at
                unified_data.sort(
                    key=lambda x: x['submitted_at'] if x['submitted_at'] else min_datetime,
                    reverse=True
                )
        else:
            # Default ordering by submitted_at descending
            min_datetime = timezone.make_aware(datetime.min)
            unified_data.sort(
                key=lambda x: x['submitted_at'] if x['submitted_at'] else min_datetime,
                reverse=True
            )
        
        # Pagination
        page = self.paginate_queryset(unified_data)
        if page is not None:
            serializer = UnifiedKYCSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = UnifiedKYCSerializer(unified_data, many=True)
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
    
    def create(self, request, *args, **kwargs):
        """Create or update nominee. If nominee exists for user, update it instead of creating duplicate."""
        user = request.user
        nominee = Nominee.objects.filter(user=user).first()
        
        if nominee:
            # Nominee exists, update it
            serializer = self.get_serializer(nominee, data=request.data, partial=False)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            # Nominee doesn't exist, create it
            return super().create(request, *args, **kwargs)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['put', 'patch'], permission_classes=[IsAuthenticated])
    def update_nominee(self, request):
        """Update current user's nominee information (create if doesn't exist)"""
        user = request.user
        nominee, created = Nominee.objects.get_or_create(user=user)
        
        # Use partial=True for PATCH, False for PUT
        partial = request.method == 'PATCH'
        serializer = NomineeSerializer(nominee, data=request.data, partial=partial)
        
        if serializer.is_valid():
            serializer.save()
            # Refresh from database to ensure all fields are loaded
            nominee.refresh_from_db()
            # Return updated data with fresh serializer instance
            serializer = NomineeSerializer(nominee)
            status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            return Response(serializer.data, status=status_code)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser], url_path='approve')
    def approve(self, request, pk=None):
        """Approve nominee KYC (Admin only) - Convenience endpoint"""
        nominee = self.get_object()
        
        # Check if already verified
        if nominee.kyc_status == 'verified':
            return Response(
                {'error': 'Nominee KYC is already verified'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update nominee KYC status to verified
        nominee.kyc_status = 'verified'
        nominee.kyc_verified_by = request.user
        nominee.kyc_verified_at = timezone.now()
        nominee.kyc_rejection_reason = ''
        
        nominee.save()
        return Response({'status': 'verified', 'message': 'Nominee KYC approved successfully'})
    
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser], url_path='update-kyc-status')
    def update_kyc_status(self, request, pk=None):
        """Update nominee KYC status - verify or reject (Admin only)"""
        nominee = self.get_object()
        new_status = request.data.get('status')
        
        # Validate status
        if new_status not in ['verified', 'rejected']:
            return Response(
                {'error': "Invalid status. Must be 'verified' or 'rejected'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if already in the requested status
        if nominee.kyc_status == new_status:
            status_message = 'verified' if new_status == 'verified' else 'rejected'
            return Response(
                {'error': f'Nominee KYC is already {status_message}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update nominee KYC status
        nominee.kyc_status = new_status
        nominee.kyc_verified_by = request.user
        nominee.kyc_verified_at = timezone.now()
        
        if new_status == 'verified':
            # Clear rejection reason if verifying
            nominee.kyc_rejection_reason = ''
        else:  # rejected
            # Set rejection reason if provided
            nominee.kyc_rejection_reason = request.data.get('reason', '')
        
        nominee.save()
        return Response({'status': new_status})


class DistributorApplicationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Distributor Application management
    """
    queryset = DistributorApplication.objects.select_related('user', 'reviewed_by').all()
    serializer_class = DistributorApplicationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']
    
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
        """Create distributor application. Approval is automatic if distributor_application_auto_approve setting is True, otherwise requires admin/staff approval."""
        user = request.user
        
        if hasattr(user, 'distributor_application'):
            return Response(
                {'non_field_errors': ['Application already exists. You can only submit one distributor application.']},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Create the application
        application = serializer.save(user=user)
        
        # Check if auto-approval is enabled
        platform_settings = PlatformSettings.get_settings()
        if platform_settings.distributor_application_auto_approve:
            # Automatically approve the application
            application.status = 'approved'
            application.reviewed_at = timezone.now()
            application.save(update_fields=['status', 'reviewed_at'])
            
            # Set user as distributor immediately
            user.is_distributor = True
            user.save(update_fields=['is_distributor'])
        # If auto-approval is False, application remains in 'pending' status
        # Admin/staff will need to approve via update-status endpoint
        
        # Refresh serializer to include updated status
        serializer = self.get_serializer(application)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        """Update distributor application. Users can update their own application to re-accept terms and conditions."""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        
        # Normal users can only update their own application
        if not (request.user.is_superuser or request.user.role in ['admin', 'staff']):
            if instance.user != request.user:
                return Response(
                    {'error': 'You can only update your own application.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Prevent updating read-only fields
        read_only_fields = ['user', 'status', 'submitted_at', 'reviewed_at', 'reviewed_by']
        for field in read_only_fields:
            if field in request.data:
                return Response(
                    {'error': f'Field "{field}" cannot be updated.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        return Response(serializer.data)
    
    def partial_update(self, request, *args, **kwargs):
        """Partial update distributor application."""
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser], url_path='update-status')
    def update_status(self, request, pk=None):
        """Update distributor application status - reject or re-approve (Admin/Staff only). Applications may be automatically approved upon creation if distributor_application_auto_approve setting is True, otherwise they require manual approval."""
        application = self.get_object()
        new_status = request.data.get('status')
        
        # Validate status
        if new_status not in ['approved', 'rejected']:
            return Response(
                {'error': "Invalid status. Must be 'approved' or 'rejected'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if already in the requested status
        if application.status == new_status:
            status_message = 'approved' if new_status == 'approved' else 'rejected'
            return Response(
                {'error': f'Application is already {status_message}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update application status
        application.status = new_status
        application.reviewed_by = request.user
        application.reviewed_at = timezone.now()
        
        if new_status == 'approved':
            # Clear rejection reason if approving
            application.rejection_reason = ''
            application.save()
            
            # Set user as distributor
            user = application.user
            user.is_distributor = True
            user.save(update_fields=['is_distributor'])
            
            return Response({
                'status': 'approved',
                'message': f'Application approved. User {user.username} is now a distributor.'
            })
        else:  # rejected
            # Set rejection reason if provided
            application.rejection_reason = request.data.get('reason', '')
            application.save()
            
            # Remove distributor status when application is rejected
            user = application.user
            user.is_distributor = False
            user.save(update_fields=['is_distributor'])
            
            return Response({
                'status': 'rejected',
                'message': f'Application rejected. User {user.username} is no longer a distributor.'
            })
    
    @action(detail=False, methods=['get'])
    def list_all(self, request):
        """
        List all distributor applications with filtering and pagination (Admin/Staff only)
        Supports filtering by status, date ranges, user_id, and ordering
        Supports pagination with page and page_size query parameters
        """
        # Permission check: Only Admin, Staff, or Superuser can access
        user = request.user
        if not (user.is_superuser or user.role in ['admin', 'staff']):
            raise PermissionDenied("Only Admin/Staff/Superuser can access this endpoint.")
        
        queryset = DistributorApplication.objects.all().select_related('user', 'reviewed_by')
        
        # Filter by status
        status_filter = request.query_params.get('status')
        if status_filter:
            if status_filter in ['pending', 'approved', 'rejected']:
                queryset = queryset.filter(status=status_filter)
        
        # Filter by submission date range
        submitted_date_from = request.query_params.get('submitted_date_from')
        submitted_date_to = request.query_params.get('submitted_date_to')
        if submitted_date_from:
            try:
                queryset = queryset.filter(submitted_at__date__gte=submitted_date_from)
            except (ValueError, TypeError):
                pass  # Invalid date format, ignore filter
        if submitted_date_to:
            try:
                queryset = queryset.filter(submitted_at__date__lte=submitted_date_to)
            except (ValueError, TypeError):
                pass  # Invalid date format, ignore filter
        
        # Filter by review date range
        reviewed_date_from = request.query_params.get('reviewed_date_from')
        reviewed_date_to = request.query_params.get('reviewed_date_to')
        if reviewed_date_from:
            try:
                queryset = queryset.filter(reviewed_at__date__gte=reviewed_date_from)
            except (ValueError, TypeError):
                pass  # Invalid date format, ignore filter
        if reviewed_date_to:
            try:
                queryset = queryset.filter(reviewed_at__date__lte=reviewed_date_to)
            except (ValueError, TypeError):
                pass  # Invalid date format, ignore filter
        
        # Filter by user ID
        user_id = request.query_params.get('user_id')
        if user_id:
            try:
                queryset = queryset.filter(user_id=int(user_id))
            except (ValueError, TypeError):
                pass  # Invalid user_id, ignore filter
        
        # Ordering - validate ordering fields to prevent SQL injection
        ordering = request.query_params.get('ordering', '-submitted_at')
        if ordering:
            # Allow only safe ordering fields
            allowed_ordering_fields = [
                'submitted_at', '-submitted_at',
                'reviewed_at', '-reviewed_at',
                'status', '-status',
                'id', '-id'
            ]
            if ordering in allowed_ordering_fields:
                queryset = queryset.order_by(ordering)
            else:
                # Default to -submitted_at if invalid ordering
                queryset = queryset.order_by('-submitted_at')
        
        # Use custom pagination
        paginator = DistributorApplicationPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

