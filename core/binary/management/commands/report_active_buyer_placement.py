"""
Report when a user became Active Buyer and how many tree members were placed before vs after.
Use for debugging "pair 5 onwards, only members placed after you became Active Buyer" rule.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.users.models import User
from core.binary.models import BinaryNode, BinaryPair
from core.binary.utils import (
    get_all_descendant_nodes,
    has_activation_payment,
)


class Command(BaseCommand):
    help = (
        'Report active_buyer_since for a user and count of tree nodes placed before vs after. '
        'Use to debug pair-5-onwards placement rule.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'user_id',
            type=int,
            nargs='?',
            default=217,
            help='User ID (default: 217)',
        )

    def handle(self, *args, **options):
        user_id = options['user_id']
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User id={user_id} not found.'))
            return

        try:
            node = BinaryNode.objects.get(user=user)
        except BinaryNode.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User {user.username} has no BinaryNode.'))
            return

        self.stdout.write('=' * 60)
        self.stdout.write(self.style.SUCCESS(f'Active Buyer placement report: user_id={user_id}'))
        self.stdout.write('=' * 60)
        self.stdout.write(f'User: {user.get_full_name()} ({user.email})')
        self.stdout.write(f'is_active_buyer: {user.is_active_buyer}')
        self.stdout.write(f'Node ID: {node.id}')
        self.stdout.write('')

        active_buyer_since = getattr(user, 'active_buyer_since', None)
        if active_buyer_since is None:
            self.stdout.write(self.style.WARNING(
                'active_buyer_since is NOT SET. Pair-5-onwards rule uses this; '
                'if user is Active Buyer, it may need backfilling (e.g. from first payment that crossed threshold).'
            ))
            self.stdout.write('')
            left_all = get_all_descendant_nodes(node, 'left')
            right_all = get_all_descendant_nodes(node, 'right')
            self.stdout.write(f'Total descendants: left={len(left_all)}, right={len(right_all)}')
            return

        self.stdout.write(self.style.SUCCESS(f'Became Active Buyer at: {active_buyer_since}'))
        if timezone.is_naive(active_buyer_since):
            self.stdout.write('(naive datetime)')
        self.stdout.write('')

        left_all = get_all_descendant_nodes(node, 'left')
        right_all = get_all_descendant_nodes(node, 'right')

        def count_before_after(nodes, cutoff):
            before = [n for n in nodes if n.created_at < cutoff]
            after = [n for n in nodes if n.created_at >= cutoff]
            return before, after

        left_before, left_after = count_before_after(left_all, active_buyer_since)
        right_before, right_after = count_before_after(right_all, active_buyer_since)

        self.stdout.write('Placement vs active_buyer_since (all descendants):')
        self.stdout.write('  Left leg:  before=%s, after=%s' % (len(left_before), len(left_after)))
        self.stdout.write('  Right leg: before=%s, after=%s' % (len(right_before), len(right_after)))
        self.stdout.write('')

        # Replicate pairing eligibility (same as get_unmatched_users_for_pairing)
        pairs = BinaryPair.objects.filter(user=user)
        matched_user_ids = set()
        for pair in pairs:
            if pair.left_user:
                matched_user_ids.add(pair.left_user.id)
            if pair.right_user:
                matched_user_ids.add(pair.right_user.id)

        left_eligible = [
            n for n in left_all
            if n.user.id not in matched_user_ids
            and has_activation_payment(n.user)
        ]
        right_eligible = [
            n for n in right_all
            if n.user.id not in matched_user_ids
            and has_activation_payment(n.user)
        ]

        left_eligible_after = [n for n in left_eligible if n.created_at >= active_buyer_since]
        right_eligible_after = [n for n in right_eligible if n.created_at >= active_buyer_since]

        self.stdout.write('Eligible for pairing (unmatched, has activation payment; includes activation members):')
        self.stdout.write('  Left leg:  total eligible=%s, of those placed AFTER Active Buyer=%s' % (
            len(left_eligible), len(left_eligible_after)))
        self.stdout.write('  Right leg: total eligible=%s, of those placed AFTER Active Buyer=%s' % (
            len(right_eligible), len(right_eligible_after)))
        self.stdout.write('')

        if len(left_eligible_after) == 0 or len(right_eligible_after) == 0:
            self.stdout.write(self.style.WARNING(
                'WHY THE MESSAGE: For pair 5+, only "eligible + placed after Active Buyer" count. '
                'On at least one leg that count is 0, so no pair can be formed -> message is shown.'
            ))
            self.stdout.write('')
            if len(left_eligible_after) == 0:
                self.stdout.write('  Left has 0 eligible nodes placed after -> add new members on LEFT after becoming Active Buyer.')
            if len(right_eligible_after) == 0:
                self.stdout.write('  Right has 0 eligible nodes placed after -> add new members on RIGHT after becoming Active Buyer.')
        else:
            self.stdout.write(self.style.SUCCESS(
                'Both legs have eligible nodes placed after Active Buyer. Pair 6+ should form (if no other limit).'
            ))

        self.stdout.write('=' * 60)
