import logging

from django.db import models, connection
from django.db.models import F
from django.utils import timezone
from django.conf import settings
from core.users.models import User

logger = logging.getLogger(__name__)


class BinaryNode(models.Model):
    """
    Binary tree node representing user's position in left/right tree
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='binary_node')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    
    # Tree position
    side = models.CharField(max_length=5, choices=[('left', 'Left'), ('right', 'Right')], null=True, blank=True)
    level = models.IntegerField(default=0)
    position = models.IntegerField(default=0)  # Position within level
    
    # Counts
    left_count = models.IntegerField(default=0)  # Total referrals on left
    right_count = models.IntegerField(default=0)  # Total referrals on right
    
    # Binary Commission Tracking
    binary_commission_activated = models.BooleanField(default=False)  # Track if binary commission is activated
    activation_timestamp = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when binary commission was activated for this user"
    )
    direct_children_count = models.IntegerField(default=0)  # Count of direct children (left + right)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'binary_nodes'
        verbose_name = 'Binary Node'
        verbose_name_plural = 'Binary Nodes'
        constraints = [
            models.UniqueConstraint(
                fields=['parent', 'side'],
                condition=models.Q(parent__isnull=False),
                name='unique_parent_side'
            )
        ]
    
    def __str__(self):
        return f"Binary Node - {self.user.username} ({self.side})"
    
    def update_counts(self):
        """Recompute and persist left_count and right_count from the actual subtree.

        Uses a single recursive-CTE SQL query per side, so this is O(1) round-trips
        regardless of subtree size. Prefer apply_placement_delta() for incremental
        updates triggered by a single placement; use update_counts() only when a
        full recount is genuinely needed (moves, admin saves, maintenance jobs).
        """
        self.left_count = self.get_all_descendants_count('left')
        self.right_count = self.get_all_descendants_count('right')
        self.save(update_fields=['left_count', 'right_count'])

    def get_all_descendants_count(self, side):
        """Count ALL descendants on the given side using one recursive CTE.

        Args:
            side: 'left' or 'right'

        Returns:
            int: Total descendants on the specified side of this node's subtree.
        """
        if side not in ('left', 'right'):
            raise ValueError(f"Invalid side: {side}. Must be 'left' or 'right'")

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH RECURSIVE subtree AS (
                        SELECT id
                        FROM binary_nodes
                        WHERE parent_id = %s AND side = %s
                        UNION ALL
                        SELECT bn.id
                        FROM binary_nodes bn
                        INNER JOIN subtree s ON bn.parent_id = s.id
                    )
                    SELECT COUNT(*) FROM subtree
                    """,
                    [self.id, side],
                )
                row = cursor.fetchone()
                return int(row[0]) if row and row[0] is not None else 0
        except Exception as exc:
            logger.warning(
                "CTE descendant count failed for node %s side %s, falling back to bounded traversal: %s",
                self.id, side, exc,
            )
            return self._fallback_descendants_count(side)

    def _fallback_descendants_count(self, side, max_depth=100):
        """Bounded iterative descendant counter used only if the CTE query fails."""
        total = 0
        frontier = list(
            BinaryNode.objects.filter(parent_id=self.id, side=side).values_list('id', flat=True)
        )
        depth = 0
        while frontier and depth < max_depth:
            total += len(frontier)
            frontier = list(
                BinaryNode.objects.filter(parent_id__in=frontier).values_list('id', flat=True)
            )
            depth += 1
        return total

    @classmethod
    def apply_placement_delta(cls, new_node_id, delta=1):
        """Incrementally adjust ancestor counts for a single placement.

        Walks the ancestor chain of ``new_node_id`` once via a recursive CTE and
        issues at most three batch UPDATEs:

        - left_count += delta for every ancestor whose chain step came from the left
        - right_count += delta for every ancestor whose chain step came from the right
        - direct_children_count += delta for the immediate parent

        This is the cheap, allocation-time replacement for the old "recount the
        entire tree from every ancestor" path that was timing out gunicorn
        workers in production.

        Args:
            new_node_id: PK of the newly placed (or removed) BinaryNode.
            delta: +1 when adding a node, -1 when removing it.

        Returns:
            int: Number of ancestor rows updated (excluding direct_children_count).
        """
        chain = cls._fetch_ancestor_chain(new_node_id)
        if not chain:
            return 0

        left_ids = [aid for aid, side in chain if side == 'left']
        right_ids = [aid for aid, side in chain if side == 'right']
        parent_id = chain[0][0]

        if left_ids:
            cls.objects.filter(id__in=left_ids).update(left_count=F('left_count') + delta)
        if right_ids:
            cls.objects.filter(id__in=right_ids).update(right_count=F('right_count') + delta)
        if parent_id is not None:
            cls.objects.filter(id=parent_id).update(
                direct_children_count=F('direct_children_count') + delta
            )

        return len(left_ids) + len(right_ids)

    @staticmethod
    def _fetch_ancestor_chain(node_id, max_depth=100):
        """Return [(ancestor_id, side_of_child_relative_to_ancestor), ...] from
        immediate parent up to root for the given node, via a single recursive CTE.

        ``side`` at each level is the ``side`` value of the child node we just
        stepped up from, so it tells the caller which side of the ancestor the
        delta should be applied to. Falls back to a bounded ORM walk if the CTE
        query is unavailable.
        """
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH RECURSIVE chain AS (
                        SELECT id, parent_id, side, 0 AS depth
                        FROM binary_nodes WHERE id = %s
                        UNION ALL
                        SELECT bn.id, bn.parent_id, bn.side, c.depth + 1
                        FROM binary_nodes bn
                        INNER JOIN chain c ON bn.id = c.parent_id
                        WHERE c.depth < %s AND c.parent_id IS NOT NULL
                    )
                    SELECT parent_id, side
                    FROM chain
                    WHERE parent_id IS NOT NULL
                    ORDER BY depth
                    """,
                    [node_id, max_depth],
                )
                return [(row[0], row[1]) for row in cursor.fetchall()]
        except Exception as exc:
            logger.warning(
                "CTE ancestor-chain query failed for node %s, falling back to bounded traversal: %s",
                node_id, exc,
            )
            chain = []
            try:
                current = BinaryNode.objects.only('id', 'parent_id', 'side').get(id=node_id)
            except BinaryNode.DoesNotExist:
                return chain
            depth = 0
            while current and current.parent_id and depth < max_depth:
                chain.append((current.parent_id, current.side))
                try:
                    current = BinaryNode.objects.only('id', 'parent_id', 'side').get(id=current.parent_id)
                except BinaryNode.DoesNotExist:
                    break
                depth += 1
            return chain


class BinaryPair(models.Model):
    """
    Binary pair matching record
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('matched', 'Matched'),
        ('processed', 'Processed'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='binary_pairs')
    
    # Pair details
    left_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='left_pairs', null=True, blank=True)
    right_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='right_pairs', null=True, blank=True)
    
    pair_amount = models.DecimalField(max_digits=10, decimal_places=2)
    earning_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    matched_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    # Month tracking for max pairs limit
    pair_month = models.IntegerField()  # 1-12
    pair_year = models.IntegerField()
    
    # Pair tracking after activation
    pair_number_after_activation = models.IntegerField(
        null=True,
        blank=True,
        help_text="Pair number after binary commission activation (null if before activation)"
    )
    
    # Daily limit tracking
    pair_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date when pair was created (for daily limit tracking)"
    )
    
    # Carry-forward tracking
    is_carry_forward_pair = models.BooleanField(
        default=False,
        help_text="Whether this pair used carried-forward members from previous day"
    )
    carry_forward = models.ForeignKey(
        'BinaryCarryForward',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pairs',
        help_text="Reference to carry-forward record if this pair used carried-forward members"
    )
    
    # Extra deduction for 6th+ pairs
    extra_deduction_applied = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Amount of extra deduction applied for 6th+ pairs (additional 20%)"
    )
    
    # Commission blocking for non-Active Buyer distributors
    commission_blocked = models.BooleanField(
        default=False,
        help_text="Whether commission was blocked due to Active Buyer requirement (6th+ pair for non-Active Buyer distributors)"
    )
    blocked_reason = models.TextField(
        blank=True,
        help_text="Reason for blocking commission (e.g., 'Not Active Buyer, 6th+ pair')"
    )
    
    class Meta:
        db_table = 'binary_pairs'
        verbose_name = 'Binary Pair'
        verbose_name_plural = 'Binary Pairs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'pair_month', 'pair_year']),
        ]
    
    def __str__(self):
        return f"Binary Pair - {self.user.username} ({self.pair_month}/{self.pair_year})"
    
    def save(self, *args, **kwargs):
        if not self.pair_month or not self.pair_year:
            now = timezone.now()
            self.pair_month = now.month
            self.pair_year = now.year
        super().save(*args, **kwargs)


class BinaryCarryForward(models.Model):
    """
    Track carried-forward members from long leg after daily pair limit
    SHORT leg is ignored, LONG leg members are carried forward
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='binary_carry_forwards')
    
    # Carry-forward details
    carried_forward_date = models.DateField(help_text="Date when members were carried forward")
    side = models.CharField(max_length=5, choices=[('left', 'Left'), ('right', 'Right')], help_text="Side with long leg (more remaining members)")
    
    # Member tracking
    initial_member_count = models.IntegerField(help_text="Total members carried forward from long leg")
    matched_count = models.IntegerField(default=0, help_text="How many carried-forward members have been matched")
    
    # Status
    is_active = models.BooleanField(default=True, help_text="Whether this carry-forward is still active")
    matched_at = models.DateTimeField(null=True, blank=True, help_text="When last match occurred")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'binary_carry_forwards'
        verbose_name = 'Binary Carry Forward'
        verbose_name_plural = 'Binary Carry Forwards'
        ordering = ['-carried_forward_date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'is_active', 'carried_forward_date']),
        ]
    
    def __str__(self):
        return f"Carry Forward - {self.user.username} ({self.side}) - {self.initial_member_count} members"
    
    @property
    def remaining_count(self):
        """Calculate remaining unmatched members"""
        return self.initial_member_count - self.matched_count


class BinaryEarning(models.Model):
    """
    Binary earnings record
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='binary_earnings')
    binary_pair = models.ForeignKey(BinaryPair, on_delete=models.CASCADE, related_name='earnings')
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    pair_number = models.IntegerField()  # Which pair this is (1st, 2nd, etc.)
    
    # EMI deduction details
    emi_deducted = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'binary_earnings'
        verbose_name = 'Binary Earning'
        verbose_name_plural = 'Binary Earnings'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Binary Earning - {self.user.username} (₹{self.net_amount})"

