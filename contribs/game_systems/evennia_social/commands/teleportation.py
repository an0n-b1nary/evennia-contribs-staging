# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Consensual teleportation — +summon and +join commands.

Request-based teleportation that bypasses allow_teleport restrictions.
Both commands require acceptance from the other party.
"""

from datetime import UTC

from evennia.commands.default.muxcommand import MuxCommand

from evennia_social.social import find_character, is_staff

_SUMMON_EXPIRY_SECONDS = 600  # 10 minutes


def _get_pending_requests(character):
    """Return the pending requests dict for a character, cleaning expired."""
    from datetime import datetime

    requests = character.pending_summon_requests or {}
    now = datetime.now(UTC)
    expired = []
    for char_id, info in requests.items():
        ts = datetime.fromisoformat(info["timestamp"])
        if (now - ts).total_seconds() > _SUMMON_EXPIRY_SECONDS:
            expired.append(char_id)
    for char_id in expired:
        del requests[char_id]
    if expired:
        character.pending_summon_requests = requests
    return requests


def _store_request(target, requester, request_type, room_id):
    """Store a summon/join request on the target character."""
    from datetime import datetime

    requests = target.pending_summon_requests or {}
    requests[requester.id] = {
        "type": request_type,
        "room_id": room_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    target.pending_summon_requests = requests


def _check_ignore_silent(caller, target):
    """Check if target is ignoring caller. Returns True if ignored (silently).

    Staff (Builder+) bypass ignore lists.
    """
    caller_account = caller.account
    target_account = target.account
    if not caller_account or not target_account:
        return False
    ignore_list = target_account.db.ignore_list or []
    is_staff_caller = caller_account.check_permstring("Builder")
    return caller_account.id in ignore_list and not is_staff_caller


class CmdSummon(MuxCommand):
    """
    Request another player to teleport to your location.

    Usage:
        +summon <character>            Send a summon request
        +summon/accept <character>     Accept a pending summon request
        +summon/decline <character>    Decline a pending summon request
        +summon/pending                List your pending requests

    Sends a request for <character> to come to your current location.
    They must accept before being moved. Works even if your room is
    set to private — your request is your consent.

    Staff (Builder+) can summon into staff rooms.
    """

    key = "+summon"
    aliases = []  # noqa: RUF012
    help_category = "Social"
    locks = "cmd:all()"

    def func(self):
        """Execute command."""
        if "accept" in self.switches:
            self._do_accept()
        elif "decline" in self.switches:
            self._do_decline()
        elif "pending" in self.switches:
            self._do_pending()
        elif self.switches:
            self.caller.msg("Unknown switch. See |w+help +summon|n for usage.")
        else:
            self._do_summon()

    def _do_summon(self):
        """Send a summon request."""
        caller = self.caller
        target, error = find_character(self.args.strip())
        if error:
            caller.msg(error)
            return
        if target == caller:
            caller.msg("You cannot summon yourself.")
            return
        if not target.account:
            caller.msg(f"|w{target.key}|n has no associated account.")
            return
        if target.location == caller.location:
            caller.msg(f"|w{target.key}|n is already here.")
            return
        # Staff room check: non-staff can't summon into staff rooms.
        room = caller.location
        if getattr(room, "room_type", "ic") == "staff" and not is_staff(caller):
            caller.msg("You cannot summon players to a staff room.")
            return

        # Store request on target.
        _store_request(target, caller, "summon", room.id)

        # Always show confirmation to caller (no ignore info leak).
        caller.msg(f"You sent a summon request to |w{target.key}|n.")

        # If ignored, don't notify target.
        if _check_ignore_silent(caller, target):
            return

        target.msg(
            f"|w{caller.key}|n wants to summon you to |w{room.get_display_name(target)}|n.\n"
            f"Type |w+summon/accept {caller.key}|n to accept "
            f"or |w+summon/decline {caller.key}|n to decline."
        )

    def _do_accept(self):
        """Accept a pending summon request — move self to summoner."""
        caller = self.caller
        name = self.args.strip()
        if not name:
            caller.msg("Usage: |w+summon/accept <character>|n")
            return

        requests = _get_pending_requests(caller)
        target, error = find_character(name)
        if error:
            caller.msg(error)
            return
        info = requests.get(target.id)
        if not info or info["type"] != "summon":
            caller.msg(f"No pending summon request from |w{target.key}|n.")
            return

        # Move to summoner's CURRENT location (they consented).
        destination = target.location
        if not destination:
            caller.msg(f"|w{target.key}|n has no valid location.")
            del requests[target.id]
            caller.pending_summon_requests = requests
            return
        if destination == caller.location:
            caller.msg(f"You are already in the same room as |w{target.key}|n.")
            del requests[target.id]
            caller.pending_summon_requests = requests
            return

        # Clear the request before moving.
        del requests[target.id]
        caller.pending_summon_requests = requests

        # Execute the move.
        caller.move_to(destination, quiet=False)
        caller.msg(f"You were summoned to |w{target.key}|n's location.")
        target.msg(f"|w{caller.key}|n accepted your summon request.")

    def _do_decline(self):
        """Decline a pending summon request."""
        caller = self.caller
        name = self.args.strip()
        if not name:
            caller.msg("Usage: |w+summon/decline <character>|n")
            return

        requests = _get_pending_requests(caller)
        target, error = find_character(name)
        if error:
            caller.msg(error)
            return
        info = requests.get(target.id)
        if not info or info["type"] != "summon":
            caller.msg(f"No pending summon request from |w{target.key}|n.")
            return

        del requests[target.id]
        caller.pending_summon_requests = requests
        caller.msg(f"You declined the summon request from |w{target.key}|n.")
        if target.has_account:
            target.msg(f"|w{caller.key}|n declined your summon request.")

    def _do_pending(self):
        """List pending requests."""
        caller = self.caller
        requests = _get_pending_requests(caller)
        summon_requests = {cid: info for cid, info in requests.items() if info["type"] == "summon"}
        if not summon_requests:
            caller.msg("You have no pending summon requests.")
            return

        from evennia.utils.search import search_object

        lines = ["|wPending summon requests:|n"]
        for char_id, _info in summon_requests.items():
            matches = search_object(f"#{char_id}")
            name = matches[0].key if matches else f"Unknown (#{char_id})"
            lines.append(f"  From |w{name}|n")
        caller.msg("\n".join(lines))


class CmdJoin(MuxCommand):
    """
    Request to teleport to another player's location.

    Usage:
        +join <character>            Send a join request
        +join/accept <character>     Accept a pending join request
        +join/decline <character>    Decline a pending join request
        +join/pending                List your pending requests

    Sends a request to go to <character>'s current location. They must
    accept before you are moved. Works even if their room is set to
    private — their acceptance is their consent.

    Staff (Builder+) can join into staff rooms.
    """

    key = "+join"
    aliases = []  # noqa: RUF012
    help_category = "Social"
    locks = "cmd:all()"

    def func(self):
        """Execute command."""
        if "accept" in self.switches:
            self._do_accept()
        elif "decline" in self.switches:
            self._do_decline()
        elif "pending" in self.switches:
            self._do_pending()
        elif self.switches:
            self.caller.msg("Unknown switch. See |w+help +join|n for usage.")
        else:
            self._do_join()

    def _do_join(self):
        """Send a join request."""
        caller = self.caller
        target, error = find_character(self.args.strip())
        if error:
            caller.msg(error)
            return
        if target == caller:
            caller.msg("You cannot join yourself.")
            return
        if not target.account:
            caller.msg(f"|w{target.key}|n has no associated account.")
            return
        if target.location == caller.location:
            caller.msg(f"|w{target.key}|n is already here.")
            return
        # Staff room check: non-staff can't join into staff rooms.
        target_room = target.location
        if getattr(target_room, "room_type", "ic") == "staff" and not is_staff(caller):
            caller.msg("You cannot join a player in a staff room.")
            return

        # Store request on target.
        _store_request(target, caller, "join", target_room.id)

        # Always show confirmation to caller (no ignore info leak).
        caller.msg(f"You sent a join request to |w{target.key}|n.")

        # If ignored, don't notify target.
        if _check_ignore_silent(caller, target):
            return

        target.msg(
            f"|w{caller.key}|n wants to join you at your location.\n"
            f"Type |w+join/accept {caller.key}|n to accept "
            f"or |w+join/decline {caller.key}|n to decline."
        )

    def _do_accept(self):
        """Accept a pending join request — move requester to self."""
        caller = self.caller
        name = self.args.strip()
        if not name:
            caller.msg("Usage: |w+join/accept <character>|n")
            return

        requests = _get_pending_requests(caller)
        target, error = find_character(name)
        if error:
            caller.msg(error)
            return
        info = requests.get(target.id)
        if not info or info["type"] != "join":
            caller.msg(f"No pending join request from |w{target.key}|n.")
            return

        # Move requester to accepter's CURRENT location.
        destination = caller.location
        if target.location == destination:
            caller.msg(f"|w{target.key}|n is already here.")
            del requests[target.id]
            caller.pending_summon_requests = requests
            return

        # Clear the request before moving.
        del requests[target.id]
        caller.pending_summon_requests = requests

        # Execute the move.
        target.move_to(destination, quiet=False)
        target.msg(f"|w{caller.key}|n accepted your join request. You have been moved.")
        caller.msg(f"You accepted |w{target.key}|n's join request.")

    def _do_decline(self):
        """Decline a pending join request."""
        caller = self.caller
        name = self.args.strip()
        if not name:
            caller.msg("Usage: |w+join/decline <character>|n")
            return

        requests = _get_pending_requests(caller)
        target, error = find_character(name)
        if error:
            caller.msg(error)
            return
        info = requests.get(target.id)
        if not info or info["type"] != "join":
            caller.msg(f"No pending join request from |w{target.key}|n.")
            return

        del requests[target.id]
        caller.pending_summon_requests = requests
        caller.msg(f"You declined the join request from |w{target.key}|n.")
        if target.has_account:
            target.msg(f"|w{caller.key}|n declined your join request.")

    def _do_pending(self):
        """List pending requests."""
        caller = self.caller
        requests = _get_pending_requests(caller)
        join_requests = {cid: info for cid, info in requests.items() if info["type"] == "join"}
        if not join_requests:
            caller.msg("You have no pending join requests.")
            return

        from evennia.utils.search import search_object

        lines = ["|wPending join requests:|n"]
        for char_id, _info in join_requests.items():
            matches = search_object(f"#{char_id}")
            name = matches[0].key if matches else f"Unknown (#{char_id})"
            lines.append(f"  From |w{name}|n")
        caller.msg("\n".join(lines))
