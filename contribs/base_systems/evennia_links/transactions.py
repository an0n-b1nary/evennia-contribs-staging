"""Atomic services that restore Evennia's Python caches after database rollback."""

from functools import wraps

from django.db import transaction


def atomic_objects(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        from evennia.objects.models import ObjectDB
        from evennia.typeclasses.attributes import Attribute

        before = {obj.pk: obj for obj in ObjectDB.get_all_cached_instances()}
        try:
            with transaction.atomic():
                return function(*args, **kwargs)
        except Exception:
            # Attributes and contents handlers do not follow SQL savepoint rollback.
            # Restore existing instances (including occupants retained by callers)
            # and evict objects created by the failed transaction.
            Attribute.flush_instance_cache(force=True)
            cached = {obj.pk: obj for obj in ObjectDB.get_all_cached_instances()}
            cached.update(before)
            # Idmapper's get()/refresh_from_db() may return the very instance
            # whose fields are dirty. Fetch scalar rows to bypass that cache.
            fields = [field.attname for field in ObjectDB._meta.concrete_fields]
            live = {
                row["id"]: row for row in ObjectDB.objects.filter(pk__in=cached).values(*fields)
            }
            for pk, obj in cached.items():
                if pk not in live:
                    obj.flush_from_cache(force=True)
                    continue
                obj.pk = pk
                obj._is_deleted = False
                obj.__dict__.update(live[pk])
                obj._state.fields_cache.clear()
                obj._prefetched_objects_cache = {}
                obj.attributes.reset_cache()
                obj.tags.reset_cache()
                obj.aliases.reset_cache()
                obj.locks.reset()
                obj.contents_cache.init()
            raise

    return wrapped
