"""Game-level web staff predicate shared by native pages and navigation."""

from django.conf import settings


def is_staff_user(request) -> bool:
    """Check the configured Evennia lock, failing closed on missing state.

    Django's ``is_staff`` flag controls Django admin access; it does not express
    the Builder permission this game's web surfaces use. Evennia superusers
    retain the normal lock-system bypass.
    """
    if request is None:
        return False
    account = getattr(request, "user", None)
    if account is None or not getattr(account, "is_authenticated", False):
        return False

    lockstring = getattr(settings, "EVENNIA_WEB_STAFF_LOCK", "cmd:perm(Builder)")
    if not isinstance(lockstring, str) or not lockstring.strip():
        return False

    try:
        return bool(account.locks.check_lockstring(account, lockstring))
    except Exception:
        return False
