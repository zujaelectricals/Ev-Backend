from django.contrib import admin
from .models import Booking, Payment


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('booking_number', 'user', 'vehicle_model', 'total_amount', 
                   'total_paid', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('booking_number', 'user__username', 'user__email', 'vehicle_model')
    readonly_fields = ('booking_number', 'created_at', 'updated_at', 'confirmed_at', 'completed_at')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'user', 'booking', 'amount', 'payment_method', 
                   'status', 'payment_date')
    list_filter = ('status', 'payment_method', 'payment_date')
    search_fields = ('transaction_id', 'user__username', 'booking__booking_number')
    readonly_fields = ('payment_date', 'completed_at')

