"""
Management command to recompute binary commission activation status
based on the NEW logic (active direct referrals only).

This is safe for live after:
- Direct referral commissions have been corrected / reverted.
- You only want to fix the flags:
    - BinaryNode.binary_commission_activated
    - BinaryNode.activation_timestamp

What it does:
- For each BinaryNode (or a specific user via --user-id):
    1. Finds all descendant nodes.
    2. Filters to descendants that:
        - Have activation payment (has_activation_payment == True), and
        - Are direct referrals of the node owner (used their referral code).
    3. Sorts them by created_at.
    4. If count >= activation_count (from PlatformSettings):
        - Ensures binary_commission_activated=True.
        - Sets activation_timestamp to the created_at of the Nth active direct referral
          (the one that should have triggered activation under the new rules).
    5. If count < activation_count:
        - Ensures binary_commission_activated=False and activation_timestamp=None.

IMPORTANT:
- This command DOES NOT touch any commissions, wallet transactions, or pairs.
- It only fixes activation flags to match the current business rules.
"""

from django.core.management.base import BaseCommand

from core.binary.models import BinaryNode
from core.binary.utils import (
    get_all_descendant_nodes,
    is_direct_referral_of,
    has_activation_payment,
)
from core.settings.models import PlatformSettings


class Command(BaseCommand):
    help = "Recompute binary_commission_activated/activation_timestamp for binary nodes using new direct-referral logic."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without writing to the database.",
        )
        parser.add_argument(
            "--user-id",
            type=int,
            help="Limit to a specific user id (owner of the BinaryNode).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        user_id = options.get("user_id")

        platform_settings = PlatformSettings.get_settings()
        activation_count = platform_settings.binary_commission_activation_count

        if user_id:
            nodes = BinaryNode.objects.filter(user_id=user_id)
            self.stdout.write(f"Processing BinaryNode for user_id={user_id} (activation_count={activation_count})")
        else:
            nodes = BinaryNode.objects.all()
            self.stdout.write(
                f"Processing ALL BinaryNodes (total={nodes.count()}) "
                f"with activation_count={activation_count}"
            )

        total = 0
        activated_fixed = 0
        deactivated_fixed = 0
        timestamp_adjusted = 0

        for node in nodes.select_related("user"):
            total += 1
            user = node.user

            # Gather all descendants (both sides)
            left_descendants = get_all_descendant_nodes(node, "left")
            right_descendants = get_all_descendant_nodes(node, "right")
            all_descendants = []
            all_descendants.extend(left_descendants)
            all_descendants.extend(right_descendants)

            # Filter to active descendants that are direct referrals of node.user
            active_direct_nodes = [
                n
                for n in all_descendants
                if is_direct_referral_of(n.user, user) and has_activation_payment(n.user)
            ]

            # Sort by created_at so we can identify the Nth activation member
            active_direct_nodes.sort(key=lambda n: n.created_at)
            active_direct_count = len(active_direct_nodes)

            expected_activated = active_direct_count >= activation_count
            current_activated = node.binary_commission_activated
            current_ts = node.activation_timestamp

            # Determine the expected activation timestamp (if any)
            expected_ts = None
            if expected_activated:
                # Nth active direct referral is the trigger
                trigger_index = activation_count - 1  # 0-based index
                if trigger_index < active_direct_count:
                    expected_ts = active_direct_nodes[trigger_index].created_at

            # Decide what to do with this node
            if expected_activated and not current_activated:
                # Should be activated but is not
                activated_fixed += 1
                msg = (
                    f"User {user.id} ({user.username}) should be ACTIVATED "
                    f"(active_direct_count={active_direct_count}) "
                    f"-> setting binary_commission_activated=True, "
                    f"activation_timestamp={expected_ts}"
                )
                if dry_run:
                    self.stdout.write(f"[DRY RUN] {msg}")
                else:
                    node.binary_commission_activated = True
                    node.activation_timestamp = expected_ts
                    node.save(update_fields=["binary_commission_activated", "activation_timestamp"])
                    self.stdout.write(self.style.SUCCESS(msg))

            elif not expected_activated and current_activated:
                # Currently activated but should not be under new logic
                deactivated_fixed += 1
                msg = (
                    f"User {user.id} ({user.username}) should NOT be activated "
                    f"(active_direct_count={active_direct_count} < {activation_count}) "
                    f"-> setting binary_commission_activated=False, activation_timestamp=None"
                )
                if dry_run:
                    self.stdout.write(f"[DRY RUN] {msg}")
                else:
                    node.binary_commission_activated = False
                    node.activation_timestamp = None
                    node.save(update_fields=["binary_commission_activated", "activation_timestamp"])
                    self.stdout.write(self.style.WARNING(msg))

            elif expected_activated and current_activated:
                # Both say activated; ensure timestamp matches the trigger member
                if expected_ts and current_ts != expected_ts:
                    timestamp_adjusted += 1
                    msg = (
                        f"User {user.id} ({user.username}) is ACTIVATED but timestamp differs "
                        f"(current={current_ts}, expected={expected_ts}) "
                        f"-> aligning activation_timestamp."
                    )
                    if dry_run:
                        self.stdout.write(f"[DRY RUN] {msg}")
                    else:
                        node.activation_timestamp = expected_ts
                        node.save(update_fields=["activation_timestamp"])
                        self.stdout.write(self.style.SUCCESS(msg))

        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Processed BinaryNodes: {total}")
        self.stdout.write(f"Activated (was False -> True): {activated_fixed}")
        self.stdout.write(f"Deactivated (was True -> False): {deactivated_fixed}")
        self.stdout.write(f"Timestamps adjusted (True -> True with new timestamp): {timestamp_adjusted}")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN mode - no database changes were written."))
        else:
            self.stdout.write(self.style.SUCCESS("Done - activation flags are now consistent with new logic."))

