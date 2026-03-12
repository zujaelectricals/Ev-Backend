"""
Revert a previous "spread" so the user is back in post-limit mode: most recent day
hits the daily limit, so weak leg shows new-only and long leg shows carry-forward.

Moves pairs from the earliest past day back to the latest past day for this user.

Usage:
  python manage.py fix_remaining_display_revert_spread --user-id=403
  python manage.py fix_remaining_display_revert_spread --user-id=403 --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max, Min
from django.utils import timezone

from core.binary.models import BinaryPair


class Command(BaseCommand):
    help = (
        'Revert spread: move pairs from earliest past day back to latest past day '
        'so user is in post-limit mode (weak=new only, long=carry forward).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            required=True,
            help='User ID (e.g. 403 for test2@toqse.com)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only print what would be done',
        )

    def handle(self, *args, **options):
        user_id = options['user_id']
        dry_run = options['dry_run']

        from core.users.models import User
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User id={user_id} not found.'))
            return

        today = timezone.now().date()
        past_pairs = BinaryPair.objects.filter(
            user=user,
            pair_number_after_activation__isnull=False,
            pair_date__lt=today,
        ).exclude(pair_date__isnull=True)

        if not past_pairs.exists():
            self.stdout.write(f'User {user.username}: no pairs on past days.')
            return

        min_date = past_pairs.aggregate(Min('pair_date'))['pair_date__min']
        max_date = past_pairs.aggregate(Max('pair_date'))['pair_date__max']
        if min_date is None or max_date is None or min_date >= max_date:
            self.stdout.write(
                f'User {user.username}: only one past day with pairs. Nothing to revert.'
            )
            return

        to_move = list(past_pairs.filter(pair_date=min_date).order_by('id'))
        if not to_move:
            return

        self.stdout.write(
            f'User {user.username} (id={user_id}): moving {len(to_move)} pair(s) '
            f'from {min_date} back to {max_date} so post-limit display applies '
            f'(weak=new only, long=carry forward).'
        )
        for p in to_move:
            self.stdout.write(f'  Pair id={p.id} pair_date {p.pair_date} -> {max_date}')

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run: no changes made.'))
            return

        with transaction.atomic():
            for p in to_move:
                p.pair_date = max_date
                p.pair_month = max_date.month
                p.pair_year = max_date.year
                p.save(update_fields=['pair_date', 'pair_month', 'pair_year'])

        self.stdout.write(self.style.SUCCESS(f'Updated {len(to_move)} pair(s).'))
        self.stdout.write(
            'Next tree_structure: weak leg = new members only, long leg = full carry-forward.'
        )
