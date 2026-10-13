from django.dispatch import Signal

property_promoted = Signal()  # property, submission, actor; transaction may roll back
property_changed = Signal()  # property, actor; after commit, cache invalidation only
frontier_changed = Signal()  # frontier, actor; after commit
