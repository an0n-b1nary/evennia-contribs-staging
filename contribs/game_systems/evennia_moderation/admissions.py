# SPDX-License-Identifier: BSD-3-Clause
"""Transactional admissions services. A pending application reserves one seat."""

import hashlib
import ipaddress
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.crypto import salted_hmac
from evennia.accounts.models import AccountDB
from evennia.utils import create
from evennia.utils.utils import class_from_module
from evennia_jobs.models import RequestOutcome
from evennia_jobs.review import submit_request

from evennia_links.guests import is_guest
from evennia_moderation.config import value
from evennia_moderation.models import (
    AdmissionsState,
    Application,
    ApplicationThrottle,
    Notice,
    Referral,
    ReferralCode,
    RetiredSeat,
)
from evennia_moderation.policy import (
    acting_account,
    connection_restriction,
    require_staff,
    staff_accounts,
)
from evennia_moderation.signals import account_admitted

logger = logging.getLogger("evennia")


def state_lock():
    """Acquire a writer before reading, including on SQLite."""
    if not AdmissionsState.objects.filter(pk=1).update(period=F("period")):
        AdmissionsState.objects.get_or_create(pk=1)
        AdmissionsState.objects.filter(pk=1).update(period=F("period"))
    return AdmissionsState.objects.select_for_update().get(pk=1)


def form_key():
    return getattr(settings, "MODERATION_APPLICATION_FORM", "admission")


def normalize_address(address):
    if isinstance(address, (list, tuple)):
        address = address[0]
    try:
        return str(ipaddress.ip_address(address))
    except ValueError as exc:
        raise ValidationError("A valid connection address is required.") from exc


def guest_typeclass_paths():
    """Account typeclass paths in use that resolve to guest classes, as is_guest() does."""
    from evennia.accounts.accounts import DefaultGuest

    paths = []
    for path in AccountDB.objects.order_by().values_list("db_typeclass_path", flat=True).distinct():
        try:
            typeclass = class_from_module(path)
        except Exception:
            continue  # Evennia falls back to the default, non-guest account typeclass.
        if isinstance(typeclass, type) and issubclass(typeclass, DefaultGuest):
            paths.append(path)
    return paths


def seat_count():
    """Approved seats plus live reservations, in a fixed number of queries."""
    approved = (
        AccountDB.objects.exclude(db_typeclass_path__in=guest_typeclass_paths())
        .exclude(pk__in=RetiredSeat.objects.values("account_id"))
        .exclude(pk__in=staff_accounts().values("pk"))
        .count()
    )
    return (
        approved
        + Application.objects.filter(status="pending", expires_at__gt=timezone.now()).count()
    )


def check_intake():
    if value("INTAKE_CLOSED"):
        raise ValidationError(value("CLOSED_MESSAGE"))
    cap = value("PLAYER_CAP")
    if cap is not None and seat_count() >= cap:
        raise ValidationError("The game is at capacity and is not taking applications right now.")


def throttle(address):
    """Commit attempts even when a subsequent application is rejected."""
    address = normalize_address(address)
    digest = salted_hmac("moderation-application", address, algorithm="sha256").hexdigest()
    now = timezone.now()
    with transaction.atomic():
        state_lock()
        bucket, _ = ApplicationThrottle.objects.get_or_create(
            key=digest, defaults={"expires_at": now + timedelta(hours=1)}
        )
        if bucket.expires_at <= now:
            bucket.attempts = 0
            bucket.expires_at = now + timedelta(hours=1)
        bucket.attempts += 1
        bucket.save()
        blocked = bucket.attempts > getattr(settings, "MODERATION_APPLICATION_ATTEMPTS", 10)
    if blocked:
        raise ValidationError("Too many application attempts. Please try again in an hour.")


def notice(account, text):
    if account:
        saved = Notice.objects.create(account=account, text=text)
        transaction.on_commit(lambda: deliver_notices(account, only=saved.pk))


def deliver_notices(account, only=None):
    if not account.sessions.count():
        return
    qs = Notice.objects.filter(account=account, delivered_at__isnull=True)
    if only:
        qs = qs.filter(pk=only)
    for saved in qs.order_by("pk"):
        try:
            account.msg(saved.text)
        except Exception:
            logger.exception("Unable to deliver moderation notice #%s", saved.pk)
        else:
            saved.delivered_at = timezone.now()
            saved.save(update_fields=["delivered_at"])


def _release(application, status, reason=""):
    now = timezone.now()
    application.status = status
    application.decided_at = now
    application.password_hash = ""
    application.reserved_name = None
    application.save(update_fields=["status", "decided_at", "password_hash", "reserved_name"])
    if application.code_id:
        code = application.code
        code.invalidated_at = now
        code.code = ""
        code.save(update_fields=["invalidated_at", "code"])
        detail = f" Reason: {reason}" if reason and application.share_decline_reason else ""
        notice(code.owner, f"{application.account_name}'s application was not approved.{detail}")


def expire_locked():
    now = timezone.now()
    for application in Application.objects.select_related("code__owner").filter(
        status="pending", expires_at__lte=now
    ):
        _release(application, "lapsed")


@transaction.atomic
def expire_applications():
    state_lock()
    expire_locked()


def password_hash(username, password):
    account_type = class_from_module(settings.BASE_ACCOUNT_TYPECLASS)
    username = account_type.normalize_username(username)
    valid, errors = account_type.validate_username(username)
    if not valid:
        raise ValidationError(errors)
    valid, errors = account_type.validate_password(
        password, account=account_type(username=username)
    )
    if not valid:
        raise ValidationError(errors)
    return username, make_password(password)


def submit_application(*, guest, username, password, answers, address, code=""):
    if not is_guest(guest):
        raise PermissionDenied("Only guests may apply for an account.")
    throttle(address)
    username, encoded = password_hash(username, password)
    return _submit_hashed_application(
        guest=guest, username=username, encoded=encoded, answers=answers, address=address, code=code
    )


def _submit_hashed_application(*, guest, username, encoded, answers, address, code=""):
    """The interactive command hashes the password as soon as it is entered."""
    if not is_guest(guest):
        raise PermissionDenied("Only guests may apply for an account.")
    address = normalize_address(address)
    with transaction.atomic():
        state_lock()
        expire_locked()
        check_intake()
        normalized = username.casefold()
        if (
            AccountDB.objects.filter(username__iexact=username).exists()
            or Application.objects.filter(reserved_name=normalized).exists()
        ):
            raise ValidationError("That account name is unavailable.")
        referral_code = None
        mode = value("REFERRAL_MODE")
        if mode == "required" and not code:
            raise ValidationError("A referral code is required.")
        if mode != "off" and code:
            digest = hashlib.sha256(code.strip().encode()).hexdigest()
            referral_code = (
                ReferralCode.objects.select_for_update()
                .filter(
                    digest=digest,
                    owner__isnull=False,
                    used_at__isnull=True,
                    invalidated_at__isnull=True,
                    expires_at__gt=timezone.now(),
                )
                .first()
            )
            if referral_code is None:
                raise ValidationError("That referral code is unavailable.")
        submission = submit_request(
            author=guest,
            form_key=form_key(),
            title=f"Account application: {username}",
            answers=answers,
            owner="moderation",
        )
        application = Application.objects.create(
            job=submission.job,
            account_name=username,
            reserved_name=normalized,
            password_hash=encoded,
            address=address,
            code=referral_code,
            expires_at=timezone.now() + timedelta(days=value("APPLICATION_DAYS")),
        )
        if referral_code:
            referral_code.used_at = timezone.now()
            referral_code.save(update_fields=["used_at"])
        return application


def application_status(username, password):
    application = Application.objects.filter(
        reserved_name=username.casefold(), status="pending", expires_at__gt=timezone.now()
    ).first()
    if application and check_password(password, application.password_hash):
        return "Your application is pending staff review."
    return None


def remaining_allowance(account, period):
    approved = Referral.objects.filter(referrer=account, period=period).count()
    codes = (
        ReferralCode.objects.filter(owner=account, period=period, invalidated_at__isnull=True)
        .filter(
            Q(used_at__isnull=True, expires_at__gt=timezone.now())
            | Q(application__status="pending", application__expires_at__gt=timezone.now())
        )
        .count()
    )
    return max(0, value("REFERRAL_ALLOWANCE") - approved - codes)


@transaction.atomic
def issue_code(actor):
    state = state_lock()
    account = acting_account(actor)
    if is_guest(account):
        raise PermissionDenied("Guests cannot issue referrals.")
    expire_locked()
    if remaining_allowance(account, state.period) <= 0:
        raise ValidationError("You have no referral allowance remaining.")
    code = secrets.token_urlsafe(24)
    return ReferralCode.objects.create(
        owner=account,
        owner_name=account.key,
        code=code,
        digest=hashlib.sha256(code.encode()).hexdigest(),
        period=state.period,
        expires_at=timezone.now() + timedelta(days=value("CODE_DAYS")),
    )


@transaction.atomic
def review_admission(sender, *, submission, decision, **kwargs):
    if submission.form_key != form_key():
        return
    require_staff(decision.reviewer)
    state_lock()
    application = (
        Application.objects.select_for_update()
        .select_related("code__owner")
        .filter(job=submission.job)
        .first()
    )
    if (
        not application
        or application.status != "pending"
        or application.expires_at <= timezone.now()
    ):
        raise ValidationError("This application is no longer pending.")
    if decision.outcome == RequestOutcome.DECLINED:
        options = getattr(decision, "review_options", {})
        if "share_decline_reason" in options:
            if type(options["share_decline_reason"]) is not bool:
                raise ValidationError("Sharing a decline reason must be a boolean choice.")
            application.share_decline_reason = options["share_decline_reason"]
            application.save(update_fields=["share_decline_reason"])
        _release(application, "declined", decision.reason)
        return
    if decision.outcome != RequestOutcome.APPROVED:
        raise ValidationError("Applications may only be approved or declined.")
    if AccountDB.objects.filter(username__iexact=application.account_name).exists():
        raise ValidationError("That account name has become unavailable.")
    # Do not call DefaultAccount.create: it would validate/hash a new plaintext
    # password and retain creator_ip. The stored hash is already validated.
    account = create.create_account(
        application.account_name, "", None, typeclass=settings.BASE_ACCOUNT_TYPECLASS
    )
    account.password = application.password_hash
    account.save(update_fields=["password"])
    account.db.FIRST_LOGIN = True
    for definition in settings.DEFAULT_CHANNELS:
        from evennia.comms.models import ChannelDB

        channel = ChannelDB.objects.get_channel(definition.get("key", ""))
        if channel and channel.access(account, "listen"):
            channel.connect(account)
    referrer = application.code.owner if application.code_id else None
    state = AdmissionsState.objects.get(pk=1)
    referral = Referral.objects.create(
        account=account,
        account_name=account.key,
        referrer=referrer,
        referrer_name=referrer.key
        if referrer
        else application.code.owner_name
        if application.code_id
        else "",
        period=state.period,
        submission_id=submission.pk,
    )
    if application.code_id:
        application.code.code = ""
        application.code.save(update_fields=["code"])
    application.delete()  # deletes credentials and address at approval
    account_admitted.send(
        sender=Referral, account=account, submission=submission, referral=referral
    )
    notice(
        referrer,
        f"{account.key}'s application was approved. Their account name and password now work.",
    )


@transaction.atomic
def retire_seat(actor, account, *, retire=True):
    state_lock()
    staff = require_staff(actor)
    if retire:
        RetiredSeat.objects.get_or_create(account=account, defaults={"retired_by": staff})
    else:
        RetiredSeat.objects.filter(account=account).delete()


@transaction.atomic
def reset_allowances(actor):
    state = state_lock()
    require_staff(actor)
    expire_locked()
    if Application.objects.filter(status="pending").exists():
        raise ValidationError("Decide pending applications before resetting referral allowances.")
    state.period += 1
    state.save(update_fields=["period"])
    ReferralCode.objects.filter(invalidated_at__isnull=True, used_at__isnull=True).update(
        invalidated_at=timezone.now(), code=""
    )
    return state.period


@transaction.atomic
def backfill_referral(actor, account, referrer=None):
    state = state_lock()
    require_staff(actor)
    if account == referrer:
        raise ValidationError("An account cannot refer itself.")
    current = referrer
    seen = {account.pk}
    while current:
        if current.pk in seen:
            raise ValidationError("That referral would create a cycle.")
        seen.add(current.pk)
        parent = Referral.objects.filter(account=current).first()
        current = parent.referrer if parent else None
    record, created = Referral.objects.get_or_create(
        account=account,
        defaults={
            "account_name": account.key,
            "referrer": referrer,
            "referrer_name": referrer.key if referrer else "",
            "period": state.period,
        },
    )
    if not created and record.referrer_id != getattr(referrer, "pk", None):
        raise ValidationError("This account already has a different recorded referrer.")
    return record


def reapplication_flags(application):
    from evennia_moderation.policy import stock_banned

    flags = []
    if stock_banned(username=application.account_name, address=application.address or ""):
        flags.append("Matches an active permanent ban.")
    if connection_restriction(username=application.account_name, address=application.address or ""):
        flags.append("Matches an active moderation restriction.")
    previous = Application.objects.filter(
        address=application.address, status__in=["declined", "lapsed"]
    ).exclude(pk=application.pk)
    if application.address and previous.exists():
        flags.append("This address has a previous declined or lapsed application.")
    return flags


def admission_review_fields(sender, *, submission, viewer, **kwargs):
    if submission.form_key != form_key():
        return {}
    try:
        require_staff(viewer)
    except PermissionDenied:
        return {}
    application = (
        Application.objects.select_related("code__owner").filter(job=submission.job).first()
    )
    if not application:
        return {}
    return {
        "moderation": {
            "Account name": application.account_name,
            "Referrer": (
                application.code.owner.key
                if application.code.owner_id
                else application.code.owner_name + " (deleted)"
            )
            if application.code_id
            else "none",
            "Connection address": application.address or "purged",
            "Checks": "; ".join(reapplication_flags(application)) or "No matching restrictions.",
            "Application state": application.status,
        }
    }
