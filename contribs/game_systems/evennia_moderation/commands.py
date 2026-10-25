# SPDX-License-Identifier: BSD-3-Clause
"""Player admissions, staff moderation, and audited stock ban commands."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from evennia.accounts.models import AccountDB
from evennia.commands.default.admin import IPREGEX, list_bans
from evennia.commands.default.admin import CmdBan as StockBan
from evennia.commands.default.admin import CmdUnban as StockUnban
from evennia.commands.default.comms import CmdPage as StockPage
from evennia.commands.default.muxcommand import MuxCommand
from evennia.server.models import ServerConfig
from evennia_jobs.models import RequestOutcome
from evennia_jobs.requests import clean_answer, get_request_form
from evennia_jobs.review import review_request

from evennia_links.command_syntax import StrictSwitchMixin, whole_number
from evennia_moderation import admissions, services
from evennia_moderation.models import (
    AdmissionsState,
    Application,
    ModerationAction,
    Referral,
    ReferralCode,
    StaffNote,
)
from evennia_moderation.policy import acting_account, active_actions, require_staff, stock_bans


def _error(command, exc):
    command.msg("; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc))


def _account(name):
    matches = list(AccountDB.objects.filter(username__iexact=name.lstrip("*").strip())[:2])
    if len(matches) > 1:
        raise ValidationError("That account name is ambiguous.")
    account = matches[0] if matches else None
    if not account:
        from evennia.objects.models import ObjectDB

        from evennia_moderation.policy import accounts_for

        characters = list(ObjectDB.objects.filter(db_key__iexact=name.strip())[:2])
        if len(characters) > 1:
            raise ValidationError("That character name is ambiguous. Use the account name.")
        character = characters[0] if characters else None
        accounts = accounts_for(character) if character else []
        account = accounts[0] if len(accounts) == 1 else None
    if not account:
        raise ValidationError("No unambiguous account found. Use the account name.")
    return account


class CmdApply(StrictSwitchMixin, MuxCommand):
    """Apply for an account as a guest: +apply. Credentials never enter Jobs."""

    key = "+apply"
    locks = "cmd:all()"
    help_category = "Accounts"

    def func(self):
        from evennia_links.guests import is_guest

        try:
            if not is_guest(self.caller):
                raise PermissionDenied("Only guests may apply for an account.")
            admissions.check_intake()
            admissions.throttle(self.session.address)
            schema = get_request_form(admissions.form_key(), owner="moderation")
            username = yield "Choose an account name:"
            password = yield "Choose a password (kept out of the application questionnaire):"
            username, encoded = admissions.password_hash(username, password)
            del password
            code = ""
            if admissions.value("REFERRAL_MODE") != "off":
                code = yield "Referral code (leave blank if optional):"
            answers = {}
            for question in schema["questions"]:
                while True:
                    answer = yield question["label"] + (
                        "\n" + question["help_text"] if question["help_text"] else ""
                    )
                    try:
                        answers[question["key"]] = clean_answer(question, answer)
                        break
                    except ValidationError as exc:
                        _error(self, exc)
            if schema != get_request_form(admissions.form_key(), owner="moderation"):
                raise ValidationError("The application form changed. Please start again.")
            application = admissions._submit_hashed_application(
                guest=self.caller,
                username=username,
                encoded=encoded,
                answers=answers,
                address=self.session.address,
                code=code.strip(),
            )
            self.msg(
                f"Application #{application.job.job_number} submitted. Connect with your chosen name and password to check its status."
            )
        except (ValidationError, PermissionDenied) as exc:
            _error(self, exc)


class CmdReferral(StrictSwitchMixin, MuxCommand):
    """Issue an invitation or see your own invitations: +referral[/list]."""

    key = "+referral"
    locks = "cmd:all()"
    help_category = "Accounts"
    switch_options = ("list",)

    def func(self):
        try:
            if "list" not in self.switches:
                code = admissions.issue_code(self.caller)
                self.msg(f"Referral code: {code.code}\nUnused until {code.expires_at.isoformat()}.")
                return
            account = acting_account(self.caller)
            admissions.expire_applications()
            state, _ = AdmissionsState.objects.get_or_create(pk=1)
            lines = [
                f"Remaining allowance: {admissions.remaining_allowance(account, state.period)}"
            ]
            for code in ReferralCode.objects.filter(
                owner=account,
                period=state.period,
                used_at__isnull=True,
                invalidated_at__isnull=True,
                expires_at__gt=timezone.now(),
            ):
                lines.append(f"{code.code} — expires {code.expires_at.isoformat()}")
            self.msg("\n".join(lines))
        except (ValidationError, PermissionDenied) as exc:
            _error(self, exc)


class StaffCommand(StrictSwitchMixin, MuxCommand):
    locks = "cmd:all()"  # Dynamic runtime lock is enforced on every invocation.
    help_category = "Staff"

    def access(self, srcobj, access_type="cmd", default=False):
        """Apply the runtime staff lock to matching and help listing, not only to func()."""
        try:
            require_staff(srcobj)
        except PermissionDenied:
            return False
        return super().access(srcobj, access_type=access_type, default=default)

    def at_pre_cmd(self):
        if super().at_pre_cmd():
            return True
        try:
            require_staff(self.caller)
        except PermissionDenied as exc:
            _error(self, exc)
            return True
        return False


class CmdSoftban(StaffCommand):
    """Timed account/IP ban.

    Usage:
        +softban <account>=<reason>
        +softban/ip <CIDR>=<reason>
        +softban/duration <account>=<hours>
        +softban/lift <account>
        +softban/liftip <CIDR>

    Apply a reason before changing a restriction's duration.
    """

    key = "+softban"
    switch_options = ("duration", "lift", "ip", "liftip")
    kind = "softban"

    def func(self):
        try:
            require_staff(self.caller)
            address = self.lhs.strip() if set(self.switches) & {"ip", "liftip"} else ""
            if set(self.switches) & {"ip", "liftip"} and not address:
                raise ValidationError("Specify an IP address or CIDR.")
            if address:
                import ipaddress

                address = str(ipaddress.ip_network(address, strict=False))
            account = None if address else _account(self.lhs)
            query = (
                active_actions(self.kind).filter(address=address)
                if address
                else active_actions(self.kind).filter(account=account)
            )
            if set(self.switches) & {"lift", "liftip"}:
                actions = list(query)
                for action in actions:
                    services.lift(self.caller, action)
                self.msg(f"Lifted {len(actions)} restriction(s).")
            elif "duration" in self.switches:
                hours = whole_number(self.rhs or "")
                if hours <= 0:
                    raise ValidationError("Duration must be a positive whole number of hours.")
                actions = list(query)
                if not actions:
                    raise ValidationError(
                        "Apply the restriction with a reason first, then change its duration."
                    )
                with transaction.atomic():
                    for action in actions:
                        services.lift(self.caller, action, reason="Duration changed")
                        services.restrict(
                            self.caller,
                            kind=self.kind,
                            account=account,
                            address=address,
                            reason=action.reason,
                            hours=hours,
                        )
                self.msg("Restriction duration changed.")
            else:
                action = services.restrict(
                    self.caller,
                    kind=self.kind,
                    account=account,
                    address=address,
                    reason=self.rhs or "",
                )
                self.msg(f"Recorded {self.kind} #{action.pk}.")
        except (ValidationError, PermissionDenied, ValueError) as exc:
            _error(self, exc)


class CmdMute(CmdSoftban):
    """Mute every alt.

    Usage:
        +mute <account>=<reason>
        +mute/duration <account>=<hours>
        +mute/lift <account>

    Blocks player pages, channels, board writing and OOC room speech. Staff
    requests, pages to staff, and IC posing remain available.
    """

    key = "+mute"
    kind = "mute"
    switch_options = ("duration", "lift")


class CmdNotes(StaffCommand):
    """Private staff notes and moderation history: +notes <account>[=<note>]."""

    key = "+notes"
    switch_options = ("actions",)

    def func(self):
        try:
            require_staff(self.caller)
            if "actions" in self.switches:
                self.msg(
                    "\n".join(
                        f"#{a.pk} {a.kind} {a.account_name or a.address} by {a.actor_name}: {a.reason}"
                        for a in ModerationAction.objects.order_by("-pk")[:100]
                    )
                )
                return
            account = _account(self.lhs)
            if self.rhs is not None:
                services.add_note(self.caller, account, self.rhs)
            lines = [f"Staff history: {account.key}"]
            for action in ModerationAction.objects.filter(account=account):
                lines.append(
                    f"#{action.pk} {action.kind} by {action.actor_name}: {action.reason} (ends {action.ends_at}; lifted {action.lifted_at})"
                )
            for note in StaffNote.objects.filter(account=account):
                lines.append(f"{note.created_at.isoformat()} {note.actor_name}: {note.text}")
            self.msg("\n".join(lines))
        except (ValidationError, PermissionDenied) as exc:
            _error(self, exc)


class CmdAdmissions(StaffCommand):
    """Staff admissions.

    Usage:
        +admissions [<job number>]
        +admissions/approve <job>=<reason>
        +admissions/decline <job>=<reason>
        +admissions/declineshare <job>=<reason>
        +admissions/tree <account>
        +admissions/backfill <account>=<referrer>
        +admissions/retire <account>
        +admissions/restore <account>
        +admissions/reset

    Decline reasons stay private unless /declineshare is chosen. /reset resets
    the game-wide referral accounting period.
    """

    key = "+admissions"
    switch_options = (
        "approve",
        "decline",
        "declineshare",
        "tree",
        "backfill",
        "retire",
        "restore",
        "reset",
    )

    def func(self):
        try:
            require_staff(self.caller)
            admissions.expire_applications()
            if "reset" in self.switches:
                self.msg(f"Referral accounting period: {admissions.reset_allowances(self.caller)}")
            elif "retire" in self.switches or "restore" in self.switches:
                admissions.retire_seat(
                    self.caller, _account(self.lhs), retire="retire" in self.switches
                )
                self.msg("Seat count updated.")
            elif "backfill" in self.switches:
                admissions.backfill_referral(
                    self.caller, _account(self.lhs), _account(self.rhs) if self.rhs else None
                )
                self.msg("Referral recorded.")
            elif "tree" in self.switches:
                account = _account(self.lhs)
                parent = Referral.objects.filter(account=account).first()
                children = Referral.objects.filter(referrer=account)
                self.msg(
                    f"{account.key} — referred by: {parent.referrer_name if parent else 'unrecorded'}\nReferred: {', '.join(r.account_name for r in children) or 'none'}"
                )
            elif self.lhs.strip():
                application = Application.objects.select_related("job", "code__owner").get(
                    job__job_number=whole_number(self.lhs)
                )
                if set(self.switches) & {"approve", "decline", "declineshare"}:
                    with transaction.atomic():
                        application.share_decline_reason = "declineshare" in self.switches
                        application.save(update_fields=["share_decline_reason"])
                        latest = application.job.submissions.last()
                        review_request(
                            job=application.job,
                            reviewer=self.caller,
                            outcome=RequestOutcome.APPROVED
                            if "approve" in self.switches
                            else RequestOutcome.DECLINED,
                            reason=self.rhs or "",
                            expected_revision=latest.revision,
                        )
                    self.msg("Application reviewed.")
                else:
                    referrer = (
                        application.code.owner.key
                        if application.code_id and application.code.owner_id
                        else application.code.owner_name
                        if application.code_id
                        else "none"
                    )
                    self.msg(
                        f"Application #{application.job.job_number}: {application.account_name} ({application.status})\nReferrer: {referrer}\nAddress: {application.address or 'purged'}\n"
                        + "\n".join(admissions.reapplication_flags(application))
                    )
            else:
                lines = [f"Reserved and approved seats: {admissions.seat_count()}"]
                lines.extend(
                    f"#{a.job.job_number} {a.account_name} — expires {a.expires_at.isoformat()}"
                    for a in Application.objects.select_related("job").filter(status="pending")
                )
                self.msg("\n".join(lines))
        except Application.DoesNotExist:
            self.msg("No application found.")
        except (ValidationError, PermissionDenied, ValueError) as exc:
            _error(self, exc)


class CmdAccountPage(StrictSwitchMixin, StockPage):
    """Stock account pages with restrictions; install even with Social pages."""

    def func(self):
        from django.db.models import Q
        from evennia.comms.models import Msg

        from evennia_links.communication import denial

        if not self.args or "last" in self.switches or self.args.strip().isdigit():
            return super().func()
        targets = []
        if self.rhs:
            for name in self.lhslist:
                target = self.caller.search(name)
                if not target:
                    return
                targets.append(target)
        else:
            first, *message = self.args.split(" ", 1)
            if message:
                found = self.caller.search(first, quiet=True)
                targets = found[:1] if found else []
        if not targets:
            pages = (
                Msg.objects.get_messages_by_sender(self.caller)
                .filter(
                    Q(db_tags__db_key__iexact="page", db_tags__db_category__iexact="comms")
                    | Q(db_tags__isnull=True)
                )
                .order_by("-db_date_created")
            )
            latest = next(
                (page for page in pages if page.access(self.caller, "read", default=True)), None
            )
            targets = latest.receivers if latest else []
        for target in targets:
            blocked = denial(self.caller, "page", target)
            if blocked:
                self.msg(blocked)
                return
        return super().func()


class CmdBan(StrictSwitchMixin, StockBan):
    """Ban an account name or IP, with persistent history and disconnection.

    Usage:
      ban[/name] <target>[=<reason>]
      ban/ip <address>[=<reason>]
      ban
    """

    switch_options = ("ip", "name")

    def func(self):
        import re
        import time

        from evennia.utils import logger

        if not self.args or (
            self.switches and not any(switch in ("ip", "name") for switch in self.switches)
        ):
            self.msg(list_bans(self, stock_bans()))
            return
        target, reason = self.lhs, self.rhs or ""
        target = target.strip().lower()
        if ":" in target:
            self.msg("Usage: ban <target>=<reason>")
            return
        matches = IPREGEX.findall(target)
        if matches:
            target = matches[0]
            pattern = re.compile(target.replace(".", r"\.").replace("*", "[0-9]{1,3}"))
            entry = ("", target, pattern, time.ctime(), reason.strip())
            kind = "IP"
        else:
            entry = (target, "", "", time.ctime(), reason.strip())
            kind = "Name"
        response = yield f"Are you sure you want to {kind}-ban '|w{target}|n' [Y]/N?"
        if str(response).lower() in {"n", "no"}:
            self.msg("Aborted.")
            return
        with transaction.atomic():
            admissions.state_lock()
            before = stock_bans()
            after = [*before, entry]
            ServerConfig.objects.conf("server_bans", after)
            services.record_stock_changes(self.caller, before, after)
        self.msg(f"{kind}-ban '|w{target}|n' was added. Use |wunban|n to reinstate.")
        logger.log_sec(f"Banned {kind}: {target} (Caller: {self.caller}).")


class CmdUnban(StrictSwitchMixin, StockUnban):
    """Stock unban command with an append-only lift record."""

    def func(self):
        from evennia.utils import logger

        bans = stock_bans()
        if not self.args:
            self.msg(list_bans(self, bans))
            return
        try:
            number = whole_number(self.args)
        except ValueError:
            self.msg("You must supply a valid ban id to clear.")
            return
        if not 0 < number <= len(bans):
            self.msg("Ban id was not found.")
            return
        chosen = bans[number - 1]
        label = chosen[0] or chosen[1]
        response = yield f"Are you sure you want to unban {number}: '|w{label}|n' [Y]/N?"
        if str(response).lower() in {"n", "no"}:
            self.msg("Aborted.")
            return
        with transaction.atomic():
            admissions.state_lock()
            before = stock_bans()
            index = next(
                (
                    i
                    for i, entry in enumerate(before)
                    if (entry[0], entry[1], entry[3], entry[4])
                    == (chosen[0], chosen[1], chosen[3], chosen[4])
                ),
                None,
            )
            if index is None:
                self.msg("That ban was already cleared.")
                return
            after = before[:index] + before[index + 1 :]
            ServerConfig.objects.conf("server_bans", after)
            services.record_stock_changes(self.caller, before, after)
        self.msg(f"Cleared ban {number}: '{label}'")
        logger.log_sec(f"Unbanned: {label} (Caller: {self.caller}).")
