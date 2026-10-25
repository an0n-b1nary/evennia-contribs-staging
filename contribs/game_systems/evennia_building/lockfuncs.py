def building_entry(accessing_obj, accessed_obj, *args, **kwargs):
    from .access import can_enter
    from .attachments import departure_allows

    return bool(accessed_obj.destination and departure_allows(accessed_obj)) or can_enter(
        accessing_obj, accessed_obj.destination or accessed_obj
    )


def building_staff(accessing_obj, accessed_obj, *args, **kwargs):
    """Use the host's Building staff policy for command access and help visibility."""
    from .access import is_staff

    return is_staff(accessing_obj)
