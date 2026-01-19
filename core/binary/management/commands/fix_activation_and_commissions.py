"""
Management command to retroactively fix binary commission activation
and pay missing commissions for users who should have been activated.

This fixes cases where:
1. Users have 3+ descendants but binary_commission_activated = False
2. Users are missing commission payments for the 3rd user
"""
from django.core.management.base import BaseCommand
from core.binary.models import BinaryNode
from core.binary.utils import get_total_descendants_count, get_all_descendant_nodes
from core.settings.models import PlatformSettings
from core.wallet.models import WalletTransaction
from core.wallet.utils import add_wallet_balance, deduct_from_booking_balance
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix binary commission activation and pay missing commissions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run in dry-run mode (no changes will be made)',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Fix specific user by ID (optional)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        user_id = options.get('user_id')
        
        platform_settings = PlatformSettings.get_settings()
        activation_count = platform_settings.binary_commission_activation_count
        commission_amount = platform_settings.direct_user_commission_amount
        tds_percentage = platform_settings.binary_commission_tds_percentage
        
        if user_id:
            nodes = BinaryNode.objects.filter(user_id=user_id)
        else:
            # Get all nodes that might need fixing
            nodes = BinaryNode.objects.filter(binary_commission_activated=False)
        
        fixed_count = 0
        activated_count = 0
        commission_paid_count = 0
        
        for node in nodes:
            # Update counts first
            node.update_counts()
            node.refresh_from_db()
            
            # Calculate total descendants using recursive counting
            total_descendants = get_total_descendants_count(node)
            
            if total_descendants >= activation_count and not node.binary_commission_activated:
                self.stdout.write(
                    f"Found user {node.user.id} ({node.user.username}) with {total_descendants} descendants "
                    f"but not activated"
                )
                
                # Find the 3rd member (the one that should have triggered activation)
                all_descendants = []
                all_descendants.extend(get_all_descendant_nodes(node, 'left'))
                all_descendants.extend(get_all_descendant_nodes(node, 'right'))
                all_descendants.sort(key=lambda n: n.created_at)
                
                if len(all_descendants) >= activation_count:
                    third_member_node = all_descendants[activation_count - 1]  # Index 2 for 3rd member
                    
                    if not dry_run:
                        # Activate binary commission
                        node.binary_commission_activated = True
                        node.activation_timestamp = third_member_node.created_at
                        node.save(update_fields=['binary_commission_activated', 'activation_timestamp'])
                        activated_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  ✓ Activated binary commission for user {node.user.id} "
                                f"(activation_timestamp = {third_member_node.created_at})"
                            )
                        )
                    else:
                        self.stdout.write(
                            f"  [DRY RUN] Would activate binary commission for user {node.user.id}"
                        )
                    
                    # Check if 3rd user's commission was paid
                    third_user = third_member_node.user
                    commission_already_paid = WalletTransaction.objects.filter(
                        user=node.user,
                        transaction_type='DIRECT_USER_COMMISSION',
                        reference_id=third_user.id,
                        reference_type='user'
                    ).exists()
                    
                    if not commission_already_paid:
                        self.stdout.write(
                            f"  Missing commission payment for 3rd user {third_user.id} ({third_user.username})"
                        )
                        
                        if not dry_run:
                            # Pay commission for 3rd user
                            tds_amount = commission_amount * (tds_percentage / Decimal('100'))
                            net_amount = commission_amount - tds_amount
                            
                            try:
                                add_wallet_balance(
                                    user=node.user,
                                    amount=float(net_amount),
                                    transaction_type='DIRECT_USER_COMMISSION',
                                    description=f"User commission for {third_user.username} (₹{commission_amount} - ₹{tds_amount} TDS = ₹{net_amount}) [Retroactive Fix]",
                                    reference_id=third_user.id,
                                    reference_type='user'
                                )
                                
                                deduct_from_booking_balance(
                                    user=node.user,
                                    deduction_amount=tds_amount,
                                    deduction_type='TDS_DEDUCTION',
                                    description=f"TDS ({tds_percentage}%) on user commission for {third_user.username} [Retroactive Fix]"
                                )
                                
                                commission_paid_count += 1
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"  ✓ Paid commission ₹{net_amount} (₹{commission_amount} - ₹{tds_amount} TDS) "
                                        f"for user {node.user.id}"
                                    )
                                )
                            except Exception as e:
                                self.stdout.write(
                                    self.style.ERROR(
                                        f"  ✗ Error paying commission for user {node.user.id}: {e}"
                                    )
                                )
                        else:
                            self.stdout.write(
                                f"  [DRY RUN] Would pay commission ₹{commission_amount - commission_amount * (tds_percentage / Decimal('100'))} "
                                f"for user {node.user.id}"
                            )
                    else:
                        self.stdout.write(
                            f"  ✓ Commission already paid for 3rd user {third_user.id}"
                        )
                    
                    fixed_count += 1
        
        self.stdout.write("\n" + "="*60)
        self.stdout.write(f"Summary:")
        self.stdout.write(f"  Users fixed: {fixed_count}")
        self.stdout.write(f"  Activations: {activated_count}")
        self.stdout.write(f"  Commissions paid: {commission_paid_count}")
        if dry_run:
            self.stdout.write(self.style.WARNING("  [DRY RUN MODE - No changes were made]"))
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ All fixes applied successfully"))

