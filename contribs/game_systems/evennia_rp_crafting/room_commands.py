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
            fixtures.clear_layer(self.caller, int(self.args.strip()))
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
                row = fixtures.decorate(
                    self.caller, item, room, seconds=int(self.rhs) if self.rhs else None
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
    """+smell or +listen: room prose first, followed by attributed fixture lines."""

    key = "+smell"
    sense = "smell"
    wave_two = True

    def run(self, switch):
        if switch or self.args.strip():
            raise CraftingError(f"Usage: {self.key}")
        from .fixtures import layers

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
    sense = "sound"
