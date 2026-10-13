from django.dispatch import Signal

property_promoted = Signal()  # property, submission, actor; transaction may roll back
property_transferring = (
    Signal()
)  # property, actor, new_owner, stock_disposition; inside transaction
property_changed = Signal()  # property, actor; after commit, cache invalidation only
frontier_changed = Signal()  # frontier, actor; after commit
