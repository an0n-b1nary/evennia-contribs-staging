from .access import managed_access


def room_visibility(room, viewer=None):
    """True/False for managed rooms, None for host-owned visibility policy."""
    return managed_access(room, viewer, scope="maps")
