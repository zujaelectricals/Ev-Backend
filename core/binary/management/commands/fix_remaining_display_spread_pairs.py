"""
Fix a user so remaining_left/remaining_right display naturally (no weak-leg zeroing).

Weak-leg zeroing applies only when the most recent day (before today) that had pairs
hit the daily limit. This command spreads that day's pairs into the previous day so
the most recent day has count < daily_limit, so the user will see natural remaining
counts (e.g. 1 left, 2 right) instead of (0, 2).

Usage:
  python manage.py fix_remaining_display_spread_pairs --user-id=403
  python manage.py fix_remaining_display_spread_pairs --user-id=403 --dry-run
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from core.binary.models import BinaryPair
from core.settings.models import PlatformSettings


class Command(BaseCommand):
    help = (
        'Spread a user\'s pairs so the most recent day with pairs is below daily limit, '
        'so remaining_left/remaining_right display naturally (no weak-leg zeroing).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            required=True,
            help='User ID to fix (e.g. 403 for test2@toqse.com)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only print what would be done, do not change data',
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
        daily_limit = PlatformSettings.get_settings().binary_daily_pair_limit

        # Only pairs on past days (pair_date < today) with pair_number_after_activation set
        past_pairs = BinaryPair.objects.filter(
            user=user,
            pair_number_after_activation__isnull=False,
            pair_date__lt=today,
        ).exclude(pair_date__isnull=True)

        if not past_pairs.exists():
            self.stdout.write(
                f'User {user.username} (id={user_id}) has no pairs on past days. '
                'Display is already natural.'
            )
            return

        last_pair_date = past_pairs.aggregate(Max('pair_date'))['pair_date__max']
        if last_pair_date is None:
            self.stdout.write('No pair_date on past pairs; nothing to change.')
            return

        count_on_last_day = past_pairs.filter(pair_date=last_pair_date).count()
        if count_on_last_day < daily_limit:
            self.stdout.write(
                f'User {user.username}: last day with pairs is {last_pair_date}, '
                f'count={count_on_last_day}, daily_limit={daily_limit}. No fix needed.'
            )
            return

        # Move enough pairs to the previous day so count on last_day < daily_limit
        pairs_to_move = count_on_last_day - daily_limit + 1
        new_date = last_pair_date - timedelta(days=1)

        pairs_on_last_day = list(
            past_pairs.filter(pair_date=last_pair_date).order_by('id')[:pairs_to_move]
        )

        self.stdout.write(
            f'User {user.username} (id={user_id}): last day {last_pair_date} has '
            f'{count_on_last_day} pairs (limit={daily_limit}). Moving {pairs_to_move} '
            f'pair(s) to {new_date} so remaining counts display naturally.'
        )
        for p in pairs_on_last_day:
            self.stdout.write(f'  Pair id={p.id} pair_date {p.pair_date} -> {new_date}')

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run: no changes made.'))
            return

        with transaction.atomic():
            for p in pairs_on_last_day:
                p.pair_date = new_date
                p.pair_month = new_date.month
                p.pair_year = new_date.year
                p.save(update_fields=['pair_date', 'pair_month', 'pair_year'])

        self.stdout.write(self.style.SUCCESS(f'Updated {len(pairs_on_last_day)} pair(s).'))
        self.stdout.write(
            f'Next tree_structure for this user will show natural remaining counts '
            f'(e.g. remaining_left=1, remaining_right=2) if raw counts are 1 and 2.'
        )
