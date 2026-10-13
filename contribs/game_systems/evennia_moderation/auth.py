# SPDX-License-Identifier: BSD-3-Clause
"""Install the backend AND middleware; account mixin covers game sessions."""

from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden
from evennia.accounts.accounts import LOGIN_THROTTLE
from evennia.web.utils.backends import CaseInsensitiveModelBackend

from evennia_moderation.policy import connection_restriction, stock_banned


def remote_address(request):
    return request.META.get("REMOTE_ADDR", "") if request is not None else ""


def ban_message(account=None, username="", address=""):
    if isinstance(address, (tuple, list)):
        address = address[0]
    restriction = connection_restriction(account, username, address)
    if restriction:
        return restriction
    if stock_banned(username=username or (account.key if account else ""), address=address):
        return "This account or address is banned. Please contact staff."
    return None


class ModerationBackend(CaseInsensitiveModelBackend):
    """Replace the stock backend; PermissionDenied prevents fallback bypasses."""

    def authenticate(self, request, username=None, password=None, autologin=None, **kwargs):
        account = super().authenticate(
            request, username=username, password=password, autologin=autologin
        )
        from evennia_links.guests import is_guest

        if account and (
            not account.is_active
            or (request is not None and is_guest(account))
            or ban_message(account, address=remote_address(request))
        ):
            raise PermissionDenied("This account is unavailable.")
        if account:
            account.backend = "evennia_moderation.auth.ModerationBackend"
        return account

    def get_user(self, user_id):
        # Middleware must see the account in order to revoke the session and
        # show the restriction, rather than silently treating it as anonymous.
        return super().get_user(user_id)


class ModerationMiddleware:
    """After AuthenticationMiddleware: stop existing sessions and IP bans."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        account = user if getattr(user, "is_authenticated", False) else None
        message = ban_message(account, address=remote_address(request))
        if message:
            if account:
                logout(request)
            return HttpResponseForbidden(message)
        return self.get_response(request)


class ModerationAccountMixin:
    """Before DefaultAccount (also before GuestAccountMixin on guest accounts)."""

    @classmethod
    def is_banned(cls, **kwargs):
        address = kwargs.get("ip", "")
        if isinstance(address, (tuple, list)):
            address = address[0]
        return bool(ban_message(username=kwargs.get("username", ""), address=address))

    @classmethod
    def authenticate(cls, username=None, password=None, ip="", **kwargs):
        from evennia_moderation.admissions import application_status

        address = ip[0] if isinstance(ip, (tuple, list)) else ip
        blocked = ban_message(username=username or "", address=address)
        if blocked:
            return None, [blocked]
        if username is not None:
            if address and LOGIN_THROTTLE.check(address):
                return None, ["Too many login failures; please try again in a few minutes."]
            pending = application_status(username, password)
            if pending:
                return None, [pending]
            account, errors = super().authenticate(
                username=username, password=password, ip=address, **kwargs
            )
        else:
            account, errors = super().authenticate(ip=ip, **kwargs)
        # A renamed account still carries its restrictions. Game-only hosts
        # need this check even when their Django backend is the stock one.
        blocked = ban_message(account, address=address) if account else None
        if blocked:
            return None, [blocked]
        return account, errors

    def at_post_login(self, session=None, **kwargs):
        from evennia_moderation.admissions import deliver_notices

        super().at_post_login(session=session, **kwargs)
        deliver_notices(self)
