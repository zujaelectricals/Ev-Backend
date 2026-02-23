from django.contrib import admin
from django.db import transaction
from .models import BinaryNode, BinaryPair, BinaryEarning


@admin.register(BinaryNode)
class BinaryNodeAdmin(admin.ModelAdmin):
    list_display = ('user', 'parent', 'side', 'level', 'left_count', 'right_count', 'created_at')
    list_filter = ('side', 'level', 'created_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at')
    
    def save_model(self, request, obj, form, change):
        """
        Override save to update counts when binary node is modified
        """
        # Store old values before saving
        old_parent_id = None
        old_side = None
        if change and obj.pk:
            try:
                old_obj = BinaryNode.objects.get(pk=obj.pk)
                old_parent_id = old_obj.parent_id
                old_side = old_obj.side
            except BinaryNode.DoesNotExist:
                pass
        
        # Update level if parent changed
        if obj.parent:
            obj.level = obj.parent.level + 1
        else:
            obj.level = 0
        
        # Save the object
        super().save_model(request, obj, form, change)
        
        # Refresh obj from database to ensure we have latest state
        obj.refresh_from_db()
        
        # Update counts after saving
        with transaction.atomic():
            # Update old parent's counts if parent changed
            if old_parent_id and old_parent_id != obj.parent_id:
                try:
                    old_parent = BinaryNode.objects.get(id=old_parent_id)
                    old_parent.update_counts()  # This already saves
                    old_parent.direct_children_count = BinaryNode.objects.filter(parent=old_parent).count()
                    old_parent.save(update_fields=['direct_children_count'])
                    
                    # Update all ancestors of old parent
                    self._update_ancestor_counts(old_parent)
                except BinaryNode.DoesNotExist:
                    pass
            
            # Update new parent's counts
            if obj.parent_id:
                # Get parent fresh from DB to ensure we have latest state
                try:
                    new_parent = BinaryNode.objects.get(id=obj.parent_id)
                    new_parent.update_counts()  # This already saves
                    new_parent.direct_children_count = BinaryNode.objects.filter(parent=new_parent).count()
                    new_parent.save(update_fields=['direct_children_count'])
                    
                    # Update all ancestors of new parent
                    self._update_ancestor_counts(new_parent)
                except BinaryNode.DoesNotExist:
                    pass
            
            # Update descendant levels if parent changed
            if old_parent_id != obj.parent_id:
                self._update_descendant_levels(obj)
            
            # Also update counts for the node itself (in case it has children)
            obj.update_counts()  # This already saves
            obj.direct_children_count = BinaryNode.objects.filter(parent=obj).count()
            obj.save(update_fields=['direct_children_count'])
    
    def _update_ancestor_counts(self, node):
        """
        Recursively update counts for all ancestors of a node
        """
        from django.db import connection
        
        if not node.parent_id:
            return
        
        try:
            with connection.cursor() as cursor:
                # Get all ancestor IDs using recursive CTE
                cursor.execute("""
                    WITH RECURSIVE ancestors AS (
                        SELECT id, parent_id, 0 as depth
                        FROM binary_nodes WHERE id = %s
                        UNION ALL
                        SELECT bn.id, bn.parent_id, a.depth + 1
                        FROM binary_nodes bn
                        INNER JOIN ancestors a ON bn.id = a.parent_id
                        WHERE a.depth < 100 AND a.parent_id IS NOT NULL
                    )
                    SELECT id FROM ancestors WHERE id != %s
                """, [node.parent_id, node.id])
                
                ancestor_ids = [row[0] for row in cursor.fetchall()]
                
                # Update counts for all ancestors
                for ancestor_id in ancestor_ids:
                    try:
                        ancestor = BinaryNode.objects.get(id=ancestor_id)
                        ancestor.update_counts()  # This already saves left_count and right_count
                        ancestor.direct_children_count = BinaryNode.objects.filter(parent=ancestor).count()
                        ancestor.save(update_fields=['direct_children_count'])
                    except BinaryNode.DoesNotExist:
                        continue
        except Exception as e:
            # Fallback to simple traversal
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"CTE query failed in admin ancestor update, using fallback: {str(e)}")
            
            current = node.parent
            max_depth = 100
            depth = 0
            
            while current and depth < max_depth:
                try:
                    current.update_counts()  # This already saves left_count and right_count
                    current.direct_children_count = BinaryNode.objects.filter(parent=current).count()
                    current.save(update_fields=['direct_children_count'])
                    
                    if current.parent_id:
                        current = BinaryNode.objects.select_related('parent').get(id=current.parent_id)
                    else:
                        current = None
                except BinaryNode.DoesNotExist:
                    current = None
                except Exception as e:
                    logger.error(f"Error updating ancestor counts: {str(e)}")
                    break
                depth += 1
    
    def _update_descendant_levels(self, node):
        """
        Recursively update levels of all descendant nodes after parent change
        """
        children = BinaryNode.objects.filter(parent=node)
        for child in children:
            child.level = node.level + 1
            child.save(update_fields=['level'])
            self._update_descendant_levels(child)


@admin.register(BinaryPair)
class BinaryPairAdmin(admin.ModelAdmin):
    list_display = ('user', 'left_user', 'right_user', 'pair_amount', 'earning_amount', 
                   'status', 'pair_month', 'pair_year', 'created_at')
    list_filter = ('status', 'pair_month', 'pair_year', 'created_at')
    search_fields = ('user__username', 'left_user__username', 'right_user__username')
    readonly_fields = ('created_at', 'matched_at', 'processed_at')


@admin.register(BinaryEarning)
class BinaryEarningAdmin(admin.ModelAdmin):
    list_display = ('user', 'binary_pair', 'amount', 'pair_number', 'emi_deducted', 
                   'net_amount', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username',)
    readonly_fields = ('created_at',)

