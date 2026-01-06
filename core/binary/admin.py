from django.contrib import admin
from .models import BinaryNode, BinaryPair, BinaryEarning


@admin.register(BinaryNode)
class BinaryNodeAdmin(admin.ModelAdmin):
    list_display = ('user', 'parent', 'side', 'level', 'left_count', 'right_count', 'created_at')
    list_filter = ('side', 'level', 'created_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(BinaryPair)
class BinaryPairAdmin(admin.ModelAdmin):
    list_display = ('user', 'left_user', 'right_user', 'pair_amount', 'earning_amount', 
                   'status', 'pair_month', 'pair_year', 'created_at')
    list_filter = ('status', 'pair_month', 'pair_year', 'created_at')
    search_fields = ('user__username', 'left_user__username', 'right_user__username')
    readonly_fields = ('created_at', 'matched_at', 'processed_at')


@admin.register(BinaryEarning)
class BinaryEarningAdmin(admin.ModelAdmin):
    list_display = ('user', 'binary_pair', 'amount', 'pair_number', 'emi_deducted', 
                   'net_amount', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username',)
    readonly_fields = ('created_at',)

