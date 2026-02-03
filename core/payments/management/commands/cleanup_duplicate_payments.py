from django.core.management.base import BaseCommand
from django.db import transaction
from core.payments.models import Payment
from collections import defaultdict


class Command(BaseCommand):
    help = 'Clean up duplicate Payment records with the same payment_id'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )
        parser.add_argument(
            '--keep-latest',
            action='store_true',
            default=True,
            help='Keep the latest Payment record for each payment_id (default: True)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        keep_latest = options['keep_latest']

        # Find all Payment records with non-null payment_id
        payments_with_id = Payment.objects.exclude(payment_id__isnull=True).exclude(payment_id='')
        
        # Group by payment_id
        payment_groups = defaultdict(list)
        for payment in payments_with_id:
            payment_groups[payment.payment_id].append(payment)

        # Find duplicates
        duplicates = {pid: payments for pid, payments in payment_groups.items() if len(payments) > 1}

        if not duplicates:
            self.stdout.write(self.style.SUCCESS('No duplicate Payment records found.'))
            return

        self.stdout.write(
            self.style.WARNING(
                f'Found {len(duplicates)} payment_ids with duplicate Payment records:'
            )
        )

        total_to_delete = 0
        payments_to_delete = []

        for payment_id, payments in duplicates.items():
            self.stdout.write(f'\n  payment_id: {payment_id}')
            self.stdout.write(f'  Found {len(payments)} Payment records:')
            
            # Sort by created_at (latest first if keep_latest, oldest first if not)
            payments_sorted = sorted(
                payments,
                key=lambda p: p.created_at,
                reverse=keep_latest
            )

            for idx, payment in enumerate(payments_sorted):
                status_icon = '✓' if idx == 0 else '✗'
                self.stdout.write(
                    f'    {status_icon} ID: {payment.id}, order_id: {payment.order_id}, '
                    f'status: {payment.status}, created_at: {payment.created_at}'
                )

            # Mark all except the first one for deletion
            if keep_latest:
                to_delete = payments_sorted[1:]
            else:
                to_delete = payments_sorted[:-1]

            payments_to_delete.extend(to_delete)
            total_to_delete += len(to_delete)

            self.stdout.write(
                self.style.WARNING(
                    f'  → Will {"KEEP" if keep_latest else "DELETE"} the latest payment, '
                    f'{"DELETE" if keep_latest else "KEEP"} {len(to_delete)} older ones'
                )
            )

        self.stdout.write(
            self.style.WARNING(
                f'\nTotal Payment records to delete: {total_to_delete}'
            )
        )

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS('\nDRY RUN: No changes made. Use --no-dry-run to apply changes.')
            )
            return

        # Confirm deletion
        self.stdout.write(self.style.WARNING('\nThis will permanently delete the duplicate records.'))
        confirm = input('Do you want to proceed? (yes/no): ')

        if confirm.lower() != 'yes':
            self.stdout.write(self.style.ERROR('Operation cancelled.'))
            return

        # Delete duplicates
        with transaction.atomic():
            deleted_count = 0
            for payment in payments_to_delete:
                self.stdout.write(
                    f'Deleting Payment ID: {payment.id}, order_id: {payment.order_id}, '
                    f'payment_id: {payment.payment_id}'
                )
                payment.delete()
                deleted_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'\nSuccessfully deleted {deleted_count} duplicate Payment records.'
            )
        )

