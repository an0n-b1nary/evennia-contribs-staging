# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from .command_base import CraftCommand as _CraftCommand
from .errors import CraftingError


class CmdFixture(_CraftCommand):
    """Install, remove or temporarily display a crafted fixture.

    +fixture lists permanent fixtures and temporary layer numbers.
    +fixture/install <carried item>
    +fixture/uninstall <installed item>  (owner or staff)
    +fixture/decorate <carried item> [= duration in seconds]
    +fixture/clear <layer number>  (creator, owner or staff)
    Temporary layers earn no cap credit. Installing grants no removal rights.
    """

    key = "+fixture"
    wave_two = True

    def run(self, switch):
        from . import fixtures

        room = self.caller.location
        if room is None:
            raise CraftingError("Visit a room first.")
        if switch == "clear":
            number = self.args.strip()
            if not number.isdecimal():
                raise CraftingError("Usage: +fixture/clear <layer number>")
            fixtures.clear_layer(self.caller, int(number))
            self.msg("Temporary atmosphere cleared.")
        elif switch in ("install", "uninstall", "decorate"):
            candidates = list(room.contents if switch == "uninstall" else self.caller.contents)
            item = self.caller.search(self.lhs.strip(), candidates=candidates)
            if item is None:
                return
            if switch == "install":
                fixtures.install(self.caller, item, room)
                self.msg(f"Installed {item.key}.")
            elif switch == "uninstall":
                fixtures.uninstall(self.caller, item)
                self.msg(f"Uninstalled {item.key}; it belongs to the property owner.")
            else:
                seconds = self.rhs.strip() if self.rhs else ""
                if seconds and not seconds.isdecimal():
                    raise CraftingError("Usage: +fixture/decorate <carried item> [= seconds]")
                row = fixtures.decorate(
                    self.caller, item, room, seconds=int(seconds) if seconds else None
                )
                self.msg(
                    f"Temporary layer #{row.pk}: {item.key}, expires {row.expires_at:%Y-%m-%d %H:%M UTC} or at scene close."
                )
        elif switch:
            raise CraftingError("Use +fixture, /install, /uninstall, /decorate or /clear.")
        else:
            rows = ["Room fixtures:"]
            rows += [
                f"  {row.craft.prose['name']} (installed)" for row in fixtures.installations(room)
            ]
            rows += [
                f"  #{row.pk} {row.craft.prose['name']} (temporary)"
                for row in fixtures.active_layers(room)
            ]
            self.msg("\n".join(rows))


class CmdSense(_CraftCommand):
    """Inspect the room or one local item's sensory prose.

    Usage: +smell [item], +listen [item], +touch <item>

    No target: room prose followed by attributed fixture lines (wave two).
    An item target: private, immutable sensory prose with no emissions.
    """

    key = "+smell"
    aliases = ["smell"]  # noqa: RUF012
    sense = "smell"

    def run(self, switch):
        if switch or self.rhs is not None:
            raise CraftingError(f"Usage: {self.key} [item]")
        if self.args.strip():
            from .item_details import local_items, sense

            item = self.caller.search(self.args.strip(), candidates=local_items(self.caller))
            if item is not None:
                self.msg(f"{item.key}\n{sense(self.caller, item, self.sense)}")
            return
        if self.sense == "touch":
            raise CraftingError("Usage: +touch <item>")
        from . import conf
        from .fixtures import layers

        if not conf.wave_two_visible(self.caller):
            return
        room = self.caller.location
        if room is None:
            raise CraftingError("Visit a room first.")
        base = room.attributes.get(f"room_{self.sense}", default="")
        self.msg(
            "\n".join([value for value in [base, *layers(room, self.sense)] if value])
            or "Nothing stands out."
        )


class CmdListen(CmdSense):
    key = "+listen"
    aliases = ["listen"]  # noqa: RUF012
    sense = "sound"


class CmdTouch(CmdSense):
    """Privately inspect a carried or locally visible crafted item's texture."""

    key = "+touch"
    aliases = ["touch"]  # noqa: RUF012
    sense = "touch"
