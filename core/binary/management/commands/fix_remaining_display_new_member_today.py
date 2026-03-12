"""
Fix a user so "remaining_right" (or left) shows only the newly added member as 1
when in post-limit "new only" display mode.

Display counts only nodes with created_at >= start of today. If the member you
added today has created_at before today (e.g. timezone), they don't count as "new"
and remaining shows 0. This command sets the most recent unmatched node on the
given side to created_at=now so it counts as new and remaining shows 1.

Usage:
  python manage.py fix_remaining_display_new_member_today --user-id=403 --side=right
  python manage.py fix_remaining_display_new_member_today --user-id=403 --side=right --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.users.models import User
from core.binary.models import BinaryNode, BinaryPair
from core.binary.utils import get_all_descendant_nodes, has_activation_payment


class Command(BaseCommand):
    help = (
        'Set the most recent unmatched node on a side to created_at=now so '
        'remaining_X_members_to_be_paired shows 1 for the newly added member.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            required=True,
            help='User ID (e.g. 403 for test2@toqse.com)',
        )
        parser.add_argument(
            '--side',
            type=str,
            choices=['left', 'right'],
            required=True,
            help='Side where you added the member (left or right)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only print what would be done',
        )

    def handle(self, *args, **options):
        user_id = options['user_id']
        side = options['side']
        dry_run = options['dry_run']

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User id={user_id} not found.'))
            return

        try:
            node = BinaryNode.objects.get(user=user)
        except BinaryNode.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'No binary node for user {user_id}.'))
            return

        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        pairs = BinaryPair.objects.filter(user=user)
        matched_user_ids = set()
        for pair in pairs:
            if pair.left_user:
                matched_user_ids.add(pair.left_user.id)
            if pair.right_user:
                matched_user_ids.add(pair.right_user.id)

        descendants = get_all_descendant_nodes(node, side)
        unmatched = [
            n for n in descendants
            if n.user.id not in matched_user_ids and has_activation_payment(n.user)
        ]
        if not unmatched:
            self.stdout.write(
                f'User {user.username}: no unmatched members on {side} side. Nothing to fix.'
            )
            return

        new_count = sum(1 for n in unmatched if n.created_at >= today_start)
        if new_count >= 1:
            self.stdout.write(
                f'User {user.username}: already {new_count} "new" (today) on {side}. '
                'remaining_{0}_members_to_be_paired should show {1}.'.format(side, new_count)
            )
            return

        # Pick the most recently created unmatched node to mark as "new"
        latest = max(unmatched, key=lambda n: n.created_at)
        self.stdout.write(
            f'User {user.username}: setting node id={latest.id} (user={latest.user.username}) '
            f'created_at from {latest.created_at} to now so remaining_{side} shows 1.'
        )
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run: no changes made.'))
            return

        with transaction.atomic():
            now = timezone.now()
            BinaryNode.objects.filter(id=latest.id).update(created_at=now, updated_at=now)

        self.stdout.write(self.style.SUCCESS('Updated. Next tree_structure will show remaining_{}=1.'.format(side)))
