from django.core.management.base import BaseCommand
from django.db import transaction
from core.binary.models import BinaryNode
from django.db.models import Count, Q


class Command(BaseCommand):
    help = 'Fix duplicate BinaryNode entries by moving them to the correct side'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without making changes',
        )
        parser.add_argument(
            '--auto-fix',
            action='store_true',
            help='Automatically fix duplicates by moving newer nodes to empty side',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        auto_fix = options.get('auto_fix', False)

        if not auto_fix and not dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "Use --dry-run to see what would be fixed, or --auto-fix to apply fixes"
                )
            )
            return

        # Find all nodes with duplicate (parent, side) combinations
        duplicates = BinaryNode.objects.filter(
            parent__isnull=False
        ).values('parent', 'side').annotate(
            count=Count('id')
        ).filter(count__gt=1)

        if not duplicates:
            self.stdout.write(self.style.SUCCESS("SUCCESS: No duplicate nodes found. Database is clean!"))
            return

        self.stdout.write("=" * 80)
        self.stdout.write(self.style.WARNING("DUPLICATE NODE FIX"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"\nFound {len(duplicates)} parent-side combinations with duplicates\n")

        fixed_count = 0
        error_count = 0

        for dup in duplicates:
            parent_id = dup['parent']
            side = dup['side']
            count = dup['count']

            try:
                parent_node = BinaryNode.objects.get(id=parent_id)
                duplicate_nodes = list(
                    BinaryNode.objects.filter(parent_id=parent_id, side=side).order_by('created_at')
                )

                self.stdout.write(
                    f"\nParent Node {parent_id} ({parent_node.user.email if parent_node.user else 'N/A'}) - {side.upper()} side:"
                )
                self.stdout.write(self.style.ERROR(f"  Found {count} nodes (expected 1)"))

                # Determine which side should be empty
                opposite_side = 'right' if side == 'left' else 'left'
                opposite_nodes = BinaryNode.objects.filter(parent=parent_node, side=opposite_side)

                # Strategy: Keep the first node (oldest), move the rest to the opposite side
                node_to_keep = duplicate_nodes[0]
                nodes_to_move = duplicate_nodes[1:]

                self.stdout.write(f"  Keeping: Node {node_to_keep.id} (user: {node_to_keep.user.email}, created: {node_to_keep.created_at})")

                for node_to_move in nodes_to_move:
                    self.stdout.write(
                        f"  Moving: Node {node_to_move.id} (user: {node_to_move.user.email}, created: {node_to_move.created_at})"
                    )

                    if opposite_nodes.exists():
                        # Opposite side is also occupied - this is a complex case
                        self.stdout.write(
                            self.style.ERROR(
                                f"    WARNING: Opposite side ({opposite_side}) is also occupied!"
                            )
                        )
                        self.stdout.write(
                            f"    This node cannot be moved automatically. Manual intervention required."
                        )
                        error_count += 1
                        continue

                    if dry_run:
                        self.stdout.write(
                            self.style.WARNING(
                                f"    [DRY RUN] Would move Node {node_to_move.id} to {opposite_side} side"
                            )
                        )
                        fixed_count += 1
                    else:
                        # Actually move the node
                        try:
                            with transaction.atomic():
                                old_side = node_to_move.side
                                node_to_move.side = opposite_side
                                node_to_move.save(update_fields=['side'])

                                # Recalculate parent's counts
                                parent_node.update_counts()

                                # Update direct_children_count
                                parent_node.direct_children_count = BinaryNode.objects.filter(
                                    parent=parent_node
                                ).count()
                                parent_node.save(update_fields=['direct_children_count'])

                                # Recalculate counts for all ancestors
                                current = parent_node.parent
                                while current:
                                    current.update_counts()
                                    current.direct_children_count = BinaryNode.objects.filter(
                                        parent=current
                                    ).count()
                                    current.save(update_fields=['direct_children_count', 'left_count', 'right_count'])
                                    current = current.parent

                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"    SUCCESS: Moved Node {node_to_move.id} from {old_side} to {opposite_side} side"
                                    )
                                )
                                fixed_count += 1
                        except Exception as e:
                            self.stdout.write(
                                self.style.ERROR(f"    ERROR: Failed to move Node {node_to_move.id}: {str(e)}")
                            )
                            error_count += 1

            except BinaryNode.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Parent node {parent_id} not found"))
                error_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing duplicate: {str(e)}"))
                error_count += 1

        # Summary
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("SUMMARY")
        self.stdout.write("=" * 80)
        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN: Would fix {fixed_count} nodes"))
        else:
            self.stdout.write(self.style.SUCCESS(f"SUCCESS: Fixed {fixed_count} duplicate nodes"))
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f"ERROR: {error_count} nodes could not be fixed (manual intervention required)"))

        # Verify no duplicates remain
        remaining_duplicates = BinaryNode.objects.filter(
            parent__isnull=False
        ).values('parent', 'side').annotate(
            count=Count('id')
        ).filter(count__gt=1)

        if remaining_duplicates:
            self.stdout.write(
                self.style.WARNING(
                    f"\nWARNING: {len(remaining_duplicates)} duplicate combinations still remain (complex cases requiring manual fix)"
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nSUCCESS: All duplicates have been fixed!"))

