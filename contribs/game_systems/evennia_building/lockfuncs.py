def building_entry(accessing_obj, accessed_obj, *args, **kwargs):
    from .access import can_enter

    return can_enter(accessing_obj, accessed_obj.destination or accessed_obj)
