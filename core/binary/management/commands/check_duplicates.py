from django.core.management.base import BaseCommand
from core.binary.models import BinaryNode
from django.db.models import Count


class Command(BaseCommand):
    help = 'Check for duplicate BinaryNode entries (same parent + side)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--node-id',
            type=int,
            help='Check specific node ID',
        )

    def handle(self, *args, **options):
        # Find all nodes with duplicate (parent, side) combinations
        duplicates = BinaryNode.objects.filter(
            parent__isnull=False
        ).values('parent', 'side').annotate(
            count=Count('id')
        ).filter(count__gt=1)

        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("DUPLICATE NODE ANALYSIS"))
        self.stdout.write("=" * 80)

        if duplicates:
            self.stdout.write(
                self.style.WARNING(
                    f"\nFound {len(duplicates)} parent-side combinations with duplicates:\n"
                )
            )

            for dup in duplicates:
                parent_id = dup['parent']
                side = dup['side']
                count = dup['count']

                try:
                    parent_node = BinaryNode.objects.get(id=parent_id)
                    self.stdout.write(
                        f"Parent Node {parent_id} ({parent_node.user.email if parent_node.user else 'N/A'}) - {side.upper()} side:"
                    )
                    self.stdout.write(f"  Expected: 1 node")
                    self.stdout.write(self.style.ERROR(f"  Actual: {count} nodes"))
                    self.stdout.write(f"  Duplicate nodes:")

                    nodes = BinaryNode.objects.filter(parent_id=parent_id, side=side)
                    for node in nodes:
                        self.stdout.write(
                            f"    - Node {node.id}: user_id={node.user.id}, email={node.user.email}, created={node.created_at}"
                        )
                    self.stdout.write("")
                except BinaryNode.DoesNotExist:
                    self.stdout.write(self.style.ERROR(f"Parent node {parent_id} not found\n"))

            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(self.style.WARNING("RECOMMENDATION:"))
            self.stdout.write("=" * 80)
            self.stdout.write(
                "1. These duplicates violate binary tree structure (each parent-side should have max 1 node)"
            )
            self.stdout.write("2. You need to decide which node to keep and which to remove/move")
            self.stdout.write("3. After cleanup, add a UniqueConstraint to prevent future duplicates")
            self.stdout.write(
                "4. The UniqueConstraint should be: UniqueConstraint(fields=['parent', 'side'], condition=Q(parent__isnull=False))"
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nSUCCESS: No duplicate nodes found. Database is clean!"))

        # Check specific case: node 38 or specified node
        node_id = options.get('node_id') or 38
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(f"SPECIFIC CHECK: Node {node_id}")
        self.stdout.write("=" * 80)
        try:
            node = BinaryNode.objects.get(id=node_id)
            self.stdout.write(f"Node {node_id}: {node.user.email}")
            self.stdout.write(
                f"Left children: {BinaryNode.objects.filter(parent=node, side='left').count()}"
            )
            self.stdout.write(
                f"Right children: {BinaryNode.objects.filter(parent=node, side='right').count()}"
            )
            self.stdout.write(f"Total children: {BinaryNode.objects.filter(parent=node).count()}")

            self.stdout.write("\nLeft side nodes:")
            left_nodes = BinaryNode.objects.filter(parent=node, side='left')
            if left_nodes.exists():
                for n in left_nodes:
                    self.stdout.write(f"  - Node {n.id}: user_id={n.user.id}, email={n.user.email}")
            else:
                self.stdout.write("  (none)")

            self.stdout.write("\nRight side nodes:")
            right_nodes = BinaryNode.objects.filter(parent=node, side='right')
            if right_nodes.exists():
                for n in right_nodes:
                    self.stdout.write(f"  - Node {n.id}: user_id={n.user.id}, email={n.user.email}")
            else:
                self.stdout.write("  (none)")

        except BinaryNode.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Node {node_id} not found"))

