# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Letters remain ordinary readable objects with visible physical seals."""

from .command_base import CraftCommand
from .errors import CraftingError
from .readable_commands import find_item


class CmdLetter(CraftCommand):
    """Address a carried Readable or seal it with a carried signet.

    Usage:
      +letter/address <letter> = <descriptive IC addressee>
      +letter/seal <letter> = <signet>

    The addressee does not restrict readers. The first successful page read
    breaks the seal. Sealing permanently freezes text and addressee, including
    journal writing. Resealing retains a visible previously-opened marker.
    No Workshop unlock is required to use a signet somebody else made.
    """

    key = "+letter"
    switch_options = ("address", "seal")

    def run(self, switch):
        if switch not in ("address", "seal") or self.rhs is None:
            raise CraftingError(
                "Use +letter/address letter = addressee, or +letter/seal letter = signet."
            )
        item = find_item(self.caller, self.lhs.strip())
        if item is None:
            return
        from . import letters

        if switch == "address":
            state = letters.address(self.caller, item, self.rhs)
            self.msg(
                f"Letter addressed to (IC): {state.addressee or '(unspecified)'}. Readers still follow the item's access rules."
            )
        else:
            signet = self.caller.search(self.rhs.strip(), candidates=self.caller.contents)
            if signet is None:
                return
            state = letters.seal(self.caller, item, signet)
            self.msg(f"You seal {item.key}: {state.seal_design}. Enclosed text is frozen.")
            if state.seal_number > 1:
                self.msg("The letter remains visibly previously opened and resealed.")
