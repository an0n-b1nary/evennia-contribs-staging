# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Private messaging — page/+msg command.

Character-level private OOC messaging using Evennia's Msg model.
Supports multi-recipient, reply shortcuts, and message history.
"""

from evennia.commands.default.muxcommand import MuxCommand

from evennia_links.command_syntax import StrictSwitchMixin
from evennia_links.identity import comms_identity, is_visitor, sending_character
from evennia_social.ignore import NONE, ignore_level, owners
from evennia_social.social import find_character


class CmdPage(StrictSwitchMixin, MuxCommand):
    """
    Send a private message to another player.

    Usage:
        page <character>=<message>
        page <char1>,<char2>=<message>  - Multi-recipient
        page <message>                  - Reply to last person who paged you
        page/last [N]                   - View last N pages received (default 5)
        page/recall [N]                 - View last N pages sent+received (default 10)

    Private OOC messaging between players. Distinct from IC mail.
    Operates at the character level to protect alt privacy.
    """

    key = "page"
    aliases = ["+msg"]  # noqa: RUF012
    help_category = "Social"
    locks = "cmd:all()"
    switch_options = ("last", "recall")

    def _get_caller_char(self):
        """Return the caller's Character, or None with an error message."""
        from evennia.objects.objects import DefaultCharacter

        if isinstance(self.caller, DefaultCharacter):
            return self.caller
        # Resolve only this session; another session's puppet is not ours.
        puppet = sending_character(self.caller, self.session)
        if puppet:
            return puppet
        if comms_identity() == "character" and (
            is_visitor(self.caller, self.session) or self.caller.check_permstring("Builder")
        ):
            return self.caller
        self.caller.msg("You must be puppeting a character to page.")
        return None

    def _resolve_targets(self, names):
        """Resolve a list of character names to Character objects.

        Returns (targets, errors) where targets is a list of Characters
        and errors is a list of error message strings.
        """
        targets = []
        errors = []
        caller_char = self._get_caller_char()
        if not caller_char:
            return [], ["Could not determine your character."]

        for name in names:
            name = name.strip()
            if not name:
                continue
            target, error = find_character(name)
            if error:
                errors.append(error)
                continue
            if target == caller_char:
                errors.append("You cannot page yourself.")
                continue
            if not target.account and not hasattr(target, "db"):
                errors.append(f"{target.key} has no associated account.")
                continue
            if target not in targets:
                targets.append(target)
        return targets, errors

    def _staff_owned(self, actor):
        from evennia.accounts.models import AccountDB

        return any(
            owner.is_superuser or owner.check_permstring("Builder")
            for owner in AccountDB.objects.filter(pk__in=owners(actor))
        )

    def _display(self, actor, viewer):
        from evennia.accounts.models import AccountDB

        if (
            isinstance(actor, AccountDB)
            and comms_identity() == "character"
            and not self._staff_owned(viewer)
        ):
            return "Staff" if self._staff_owned(actor) else "Newcomer"
        return actor.get_display_name(viewer)

    def _send_page(self, caller_char, targets, message):
        """Persist and deliver allowed contact, with identical sender replies."""
        from evennia.accounts.models import AccountDB
        from evennia.utils import create

        from evennia_links.communication import denial

        visitor = is_visitor(caller_char, getattr(self, "session", None))
        for target in targets:
            blocked = denial(caller_char, "page", target)
            if blocked:
                self.caller.msg(blocked)
                return
            if visitor and not self._staff_owned(target):
                self.caller.msg(
                    "Visitors may page staff only."
                    if comms_identity() == "character"
                    else "Guests may page staff only."
                )
                return
            # Only staff can use the private reply pointer to an account.
            # Accounts are never resolved by the public name search.
            if isinstance(target, AccountDB) and not self._staff_owned(caller_char):
                self.caller.msg("Visitors may page staff only.")
                return

        deliver = [target for target in targets if ignore_level(target, caller_char) == NONE]
        if deliver:

            def lock(actor):
                return f"{'pid' if isinstance(actor, AccountDB) else 'id'}({actor.pk})"

            read = " or ".join(lock(t) for t in [*deliver, caller_char])
            create.create_message(
                caller_char,
                message,
                receivers=deliver,
                locks=(
                    f"read:{read} or perm(Admin);"
                    f"delete:{lock(caller_char)} or perm(Admin);"
                    f"edit:{lock(caller_char)} or perm(Admin)"
                ),
                tags=[("page", "comms")],
            )
        for target in deliver:
            if isinstance(caller_char, AccountDB):
                target.db.last_pager_account = caller_char.pk
                target.db.last_pager = None
            else:
                target.db.last_pager = caller_char.pk
                target.db.last_pager_account = None
            if not isinstance(target, AccountDB) and not target.has_account:
                continue
            if isinstance(caller_char, AccountDB) and comms_identity() == "character":
                # The persistent Msg identifies the account to staff; live
                # visitor contact uses the public label even for staff.
                sender_name = "Staff" if self._staff_owned(caller_char) else "Newcomer"
            else:
                sender_name = self._display(caller_char, target)
            if len(targets) == 1:
                recv_text = f"|w{sender_name}|n pages: {message}"
            else:
                others = ", ".join(self._display(t, target) for t in targets if t != target)
                recv_text = f"|w{sender_name}|n pages you and {others}: {message}"
            target.msg((recv_text, {"type": "page"}), from_obj=caller_char)

        target_str = ", ".join(self._display(t, caller_char) for t in targets)
        self.caller.msg(f"You paged {target_str}: {message}")
        # Connectivity advice must not change depending on ignore delivery.
        offline = [
            self._display(t, caller_char)
            for t in targets
            if not (t.is_connected if isinstance(t, AccountDB) else t.has_account)
        ]
        if offline:
            self.caller.msg(
                f"{', '.join(offline)} is offline. They will see your page when they next connect."
            )

    def _show_last(self, count=5):
        """Show the last N pages received."""
        from django.db.models import Q
        from evennia.comms.models import Msg

        caller_char = self._get_caller_char()
        if not caller_char:
            return

        page_filter = Q(
            db_tags__db_key__iexact="page",
            db_tags__db_category__iexact="comms",
        )
        pages = (
            Msg.objects.get_messages_by_receiver(caller_char)
            .filter(page_filter)
            .order_by("-db_date_created")[:count]
        )

        if not pages:
            self.caller.msg("You have no pages.")
            return

        lines = ["|wRecent pages received:|n"]
        for msg in pages:
            senders = msg.senders
            sender_name = self._display(senders[0], caller_char) if senders else "Unknown"
            timestamp = msg.db_date_created.strftime("%m/%d %H:%M")
            lines.append(f"  [{timestamp}] From {sender_name}: {msg.message}")

        self.caller.msg("\n".join(lines))

    def _show_recall(self, count=10):
        """Show the last N pages sent and received, interleaved."""
        from django.db.models import Q
        from evennia.comms.models import Msg

        caller_char = self._get_caller_char()
        if not caller_char:
            return

        page_filter = Q(
            db_tags__db_key__iexact="page",
            db_tags__db_category__iexact="comms",
        )
        sent = list(
            Msg.objects.get_messages_by_sender(caller_char)
            .filter(page_filter)
            .order_by("-db_date_created")[:count]
        )
        received = list(
            Msg.objects.get_messages_by_receiver(caller_char)
            .filter(page_filter)
            .order_by("-db_date_created")[:count]
        )

        # Merge and deduplicate (a self-page would appear in both).
        seen_ids = set()
        all_pages = []
        for msg in sent + received:
            if msg.id not in seen_ids:
                seen_ids.add(msg.id)
                all_pages.append(msg)

        all_pages.sort(key=lambda m: m.db_date_created)
        all_pages = all_pages[-count:]

        if not all_pages:
            self.caller.msg("You have no page history.")
            return

        lines = ["|wPage history:|n"]
        for msg in all_pages:
            senders = msg.senders
            receivers = msg.receivers
            timestamp = msg.db_date_created.strftime("%m/%d %H:%M")
            is_sent = caller_char in senders

            if is_sent:
                recv_names = ", ".join(self._display(r, caller_char) for r in receivers)
                lines.append(f"  [{timestamp}] >> To {recv_names}: {msg.message}")
            else:
                sender_name = self._display(senders[0], caller_char) if senders else "Unknown"
                lines.append(f"  [{timestamp}] << From {sender_name}: {msg.message}")

        self.caller.msg("\n".join(lines))

    def func(self):
        """Execute command."""
        caller_char = self._get_caller_char()
        if not caller_char:
            return

        # Handle switches.
        if "last" in self.switches:
            count = 5
            if self.args and self.args.strip().isdigit():
                count = int(self.args.strip())
            self._show_last(count)
            return

        if "recall" in self.switches:
            count = 10
            if self.args and self.args.strip().isdigit():
                count = int(self.args.strip())
            self._show_recall(count)
            return

        # No args — show usage.
        if not self.args:
            self.caller.msg(
                "Usage: page <character>=<message> | "
                "page <message> (reply) | page/last | page/recall"
            )
            return

        # Explicit target(s) with = sign.
        if self.rhs is not None:
            targets, errors = self._resolve_targets(self.lhslist)
            for err in errors:
                self.caller.msg(err)
            if not targets:
                return
            message = self.rhs.strip()
            if not message:
                self.caller.msg("What do you want to page them?")
                return
            self._send_page(caller_char, targets, message)
            return

        # No = sign — reply to last pager.
        last_pager_id = caller_char.db.last_pager
        last_account_id = caller_char.db.last_pager_account
        if not last_pager_id and not last_account_id:
            self.caller.msg(
                "No one has paged you yet. Use |wpage <character>=<message>|n to start."
            )
            return

        from evennia.accounts.models import AccountDB
        from evennia.objects.models import ObjectDB

        if last_account_id:
            target = AccountDB.objects.filter(pk=last_account_id).first()
        else:
            target = ObjectDB.objects.filter(pk=last_pager_id).first()
        if target is None:
            self.caller.msg("The person who last paged you no longer exists.")
            caller_char.db.last_pager = None
            caller_char.db.last_pager_account = None
            return

        message = self.args.strip()
        if not message:
            self.caller.msg("What do you want to page them?")
            return

        self._send_page(caller_char, [target], message)
