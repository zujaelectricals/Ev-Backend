from django.core.management.base import BaseCommand
from django.db import transaction
from core.users.models import User
from core.binary.models import BinaryNode
from core.binary.utils import process_binary_initial_bonus
from core.wallet.models import WalletTransaction
from core.settings.models import PlatformSettings


class Command(BaseCommand):
    help = 'Backfill binary initial bonus for users who are activated but did not receive the bonus'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            help='Process bonus for specific user ID only',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually processing',
        )

    def handle(self, *args, **options):
        user_id = options.get('user_id')
        dry_run = options.get('dry_run', False)
        
        # Get settings to check if bonus is configured
        settings = PlatformSettings.get_settings()
        if settings.binary_commission_initial_bonus <= 0:
            self.stdout.write(
                self.style.WARNING(
                    f'Binary initial bonus is set to {settings.binary_commission_initial_bonus}. '
                    'No bonus will be paid. Update the setting first.'
                )
            )
            return
        
        # Get users who are activated
        if user_id:
            try:
                user = User.objects.get(id=user_id)
                users = [user]
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'User with ID {user_id} not found.')
                )
                return
        else:
            # Get all users with activated binary commission
            activated_nodes = BinaryNode.objects.filter(
                binary_commission_activated=True
            ).select_related('user')
            users = [node.user for node in activated_nodes]
        
        if not users:
            self.stdout.write(self.style.WARNING('No activated users found.'))
            return
        
        self.stdout.write(
            f'Found {len(users)} user(s) with activated binary commission.'
        )
        
        processed = 0
        skipped = 0
        failed = 0
        
        for user in users:
            # Check if bonus was already paid
            if WalletTransaction.objects.filter(
                user=user,
                transaction_type='BINARY_INITIAL_BONUS'
            ).exists():
                self.stdout.write(
                    self.style.WARNING(
                        f'  User {user.id} ({user.username}): Bonus already paid. Skipping.'
                    )
                )
                skipped += 1
                continue
            
            if dry_run:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  [DRY RUN] Would process bonus for user {user.id} ({user.username})'
                    )
                )
                processed += 1
            else:
                try:
                    with transaction.atomic():
                        result = process_binary_initial_bonus(user)
                        if result:
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'  User {user.id} ({user.username}): Bonus processed successfully'
                                )
                            )
                            processed += 1
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'  User {user.id} ({user.username}): Bonus processing returned False'
                                )
                            )
                            skipped += 1
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f'  User {user.id} ({user.username}): Error - {str(e)}'
                        )
                    )
                    failed += 1
        
        # Summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('Summary:'))
        self.stdout.write(f'  Processed: {processed}')
        self.stdout.write(f'  Skipped (already paid): {skipped}')
        self.stdout.write(f'  Failed: {failed}')
        self.stdout.write(self.style.SUCCESS('=' * 60))

