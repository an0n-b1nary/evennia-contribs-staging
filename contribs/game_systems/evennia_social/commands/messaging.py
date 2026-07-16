# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Private messaging — page/+msg command.

Character-level private OOC messaging using Evennia's Msg model.
Supports multi-recipient, reply shortcuts, and message history.
"""

from evennia.commands.default.muxcommand import MuxCommand

from evennia_social.social import find_character


class CmdPage(MuxCommand):
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
        # AccountCmdSet context — try to get puppet
        puppet = self.caller.get_puppet(self.session)
        if puppet:
            return puppet
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

    def _send_page(self, caller_char, targets, message):
        """Create the Msg and deliver to online targets."""
        from evennia.utils import create

        caller_account = caller_char.account

        # Create the persistent Msg with Character sender/receivers.
        target_perms = " or ".join([f"id({t.id})" for t in [*targets, caller_char]])
        create.create_message(
            caller_char,
            message,
            receivers=targets,
            locks=(
                f"read:{target_perms} or perm(Admin);"
                f"delete:id({caller_char.id}) or perm(Admin);"
                f"edit:id({caller_char.id}) or perm(Admin)"
            ),
            tags=[("page", "comms")],
        )

        # Build display strings.
        target_names = [t.key for t in targets]
        target_str = ", ".join(target_names)

        # Deliver to each target.
        offline_targets = []
        for target in targets:
            # Set reply tracking on the receiver.
            target.db.last_pager = caller_char.id

            if not target.has_account:
                offline_targets.append(target.key)
                continue

            # Check ignore at delivery time. Sender's account in target's
            # ignore list = silently skip delivery (not Msg creation).
            target_account = target.account
            ignore_list = target_account.db.ignore_list or []
            is_staff = caller_account.check_permstring("Builder")
            if caller_account.id in ignore_list and not is_staff:
                continue

            # Format the delivery message.
            if len(targets) == 1:
                recv_text = f"|w{caller_char.key}|n pages: {message}"
            else:
                others = [t.key for t in targets if t != target]
                others_str = ", ".join(others)
                recv_text = f"|w{caller_char.key}|n pages you and {others_str}: {message}"

            target.msg(
                (recv_text, {"type": "page"}),
                from_obj=caller_char,
            )

        # Sender confirmation — always show "You paged" regardless of
        # online status (no information leak about ignore or connectivity).
        self.caller.msg(f"You paged {target_str}: {message}")
        if offline_targets:
            offline_str = ", ".join(f"|C{n}|n" for n in offline_targets)
            self.caller.msg(
                f"{offline_str} is offline. They will see your page when they next connect."
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
            sender_name = senders[0].key if senders else "Unknown"
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
                recv_names = ", ".join(r.key for r in receivers)
                lines.append(f"  [{timestamp}] >> To {recv_names}: {msg.message}")
            else:
                sender_name = senders[0].key if senders else "Unknown"
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
        last_pager_id = caller_char.last_pager
        if not last_pager_id:
            self.caller.msg(
                "No one has paged you yet. Use |wpage <character>=<message>|n to start."
            )
            return

        from evennia.objects.models import ObjectDB

        try:
            target = ObjectDB.objects.get(id=last_pager_id)
        except ObjectDB.DoesNotExist:
            self.caller.msg("The character who last paged you no longer exists.")
            caller_char.last_pager = None
            return

        message = self.args.strip()
        if not message:
            self.caller.msg("What do you want to page them?")
            return

        self._send_page(caller_char, [target], message)
