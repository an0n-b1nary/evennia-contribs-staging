# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exact service offers and owner-directed cosmetic Companions."""

from django.db.models import Q
from evennia.objects.models import ObjectDB

from . import companions, modifiers
from .command_base import CraftCommand
from .errors import CraftingError
from .models import CompanionState, ModificationLayer, ModificationOffer


def _number(value, message, *, minimum=1, prefix=False):
    value = value.strip()
    if prefix:
        value = value.removeprefix("#")
    try:
        number = int(value)
    except ValueError:
        raise CraftingError(message) from None
    if number < minimum or number > 2**63 - 1:
        raise CraftingError(message)
    return number


class CmdModify(CraftCommand):
    """Offer and accept cosmetic layers without changing base descriptions.

    Usage:
      +modify
      +modify/offer <customer>/<target> = <niche>/<modifier> ; <line> ; <resources> ; <commission> [; <replace layer>]
      +modify/undo <customer>/<target> = <niche> ; <layer> ; <resources> ; <commission>
      +modify/accept <service number>
      +modify/cancel <service number>
      +modify/layers <target>
      +modify/hide <layer number>
      +modify/show <layer number>

    Resources use key:quantity, key:quantity. The maker supplies materials and
    pays the craft fee; the customer pays the commission. Offers reserve nothing.
    A changed target, ownership, layer or cost requires a new offer. Self services
    still require acceptance with zero commission. Hiding is free OOC visibility;
    undoing is a paid IC service. Both preserve history.
    """

    key = "+modify"
    switch_options = ("offer", "undo", "accept", "cancel", "layers", "hide", "show")
    wave_three = True

    def run(self, switch):
        from .commands import resource_spec

        if switch in ("accept", "cancel", "hide", "show"):
            kind = "service" if switch in ("accept", "cancel") else "layer"
            number = _number(
                self.args,
                f"Use a {kind} number, e.g. +modify/{switch} 3.",
                prefix=True,
            )
            if switch == "accept":
                modifiers.accept(self.caller, number)
                self.msg(f"Service #{number} completed.")
            elif switch == "cancel":
                modifiers.cancel(self.caller, number)
                self.msg(f"Service #{number} cancelled.")
            else:
                modifiers.set_hidden(self.caller, number, switch == "hide")
                self.msg(f"Layer #{number}: {'hidden' if switch == 'hide' else 'visible'} (OOC).")
            return
        if switch in ("offer", "undo"):
            if self.rhs is None or "/" not in self.lhs:
                raise CraftingError("Use customer/target = service terms; see help +modify.")
            customer_name, target_name = self.lhs.split("/", 1)
            customer = self.caller.search(customer_name.strip())
            if customer is None:
                return
            target = self.caller.search(
                target_name.strip(),
                candidates=[
                    customer,
                    *customer.contents,
                    *(customer.location.contents if customer.location else []),
                ],
            )
            if target is None:
                return
            parts = [part.strip() for part in self.rhs.split(";")]
            if switch == "undo":
                if len(parts) != 4:
                    raise CraftingError("Use niche ; layer ; resources ; commission.")
                niche, layer_id, materials, price = parts
                modifier, configuration = (
                    "modifier_undo",
                    {
                        "layer_id": _number(
                            layer_id, "Use a layer number; see help +modify/undo.", prefix=True
                        )
                    },
                )
            else:
                if len(parts) < 4 or "/" not in parts[0]:
                    raise CraftingError(
                        "Use niche/modifier ; line ; resources ; commission [; replace layer]."
                    )
                niche, modifier = parts[0].split("/", 1)
                # Read fixed terms from the right, preserving semicolons in
                # authored prose. Resource terms contain keys, never just an int.
                replacement = len(parts) >= 5 and ":" in parts[-3] and ":" not in parts[-2]
                tail = 3 if replacement else 2
                configuration = {"line": "; ".join(parts[1:-tail])}
                materials, price = parts[-tail:-1] if replacement else parts[-2:]
                if replacement:
                    configuration["layer_id"] = _number(
                        parts[-1], "Use a layer number; see help +modify/offer.", prefix=True
                    )
            row = modifiers.propose(
                self.caller,
                customer,
                target,
                niche,
                modifier,
                configuration,
                resource_spec(materials),
                commission=_number(
                    price, "Use a nonnegative whole-number commission; see help +modify.", minimum=0
                ),
            )
            details = modifiers.ServiceAsset().describe(str(row.pk))
            self.msg(details)
            customer.msg(
                f"{self.caller.key} offers {details}. Use +modify/accept {row.pk} or +modify/cancel {row.pk}."
            )
        elif switch == "layers":
            target = self.caller.search(self.args.strip())
            if target is not None:
                self.msg(
                    "Modification history (OOC):\n"
                    + "\n".join(
                        f"#{row.pk} {row.kind}: {row.text} — {row.hallmark}"
                        f" [{'removed' if row.removed_by_id else 'hidden' if row.hidden else 'visible'}]"
                        for row in ModificationLayer.objects.filter(target_id=target.pk).order_by(
                            "pk"
                        )
                    )
                )
        elif not switch:
            rows = list(
                ModificationOffer.objects.filter(
                    Q(maker_id=self.caller.pk) | Q(customer_id=self.caller.pk)
                ).order_by("-pk")[:30]
            )
            statuses = modifiers.offer_statuses(rows)
            self.msg(
                "Your recent services:\n"
                + "\n".join(
                    modifiers.ServiceAsset().describe(str(row.pk)) + f" [{statuses[row.pk]}]"
                    for row in rows
                )
            )
        else:
            raise CraftingError(
                "See help +modify for offer, undo, accept, cancel, layers, hide and show."
            )


class CmdPet(CraftCommand):
    """Direct a Companion.

    Usage:
      +pet
      +pet/follow <name>
      +pet/stay <name>
      +pet/pose <name> = <prose>
      +pet/trick <name> [= <mode>]

    Only owner-written poses count as posing. Pick up a Companion before gifting
    or selling it; handoff changes ownership and resets it to stay. Companions
    have no inventory or combat mechanics. Automatic output respects mute/ignore.
    """

    key = "+pet"
    switch_options = ("follow", "stay", "pose", "trick")
    wave_three = True

    def run(self, switch):
        if not switch:
            rows = CompanionState.objects.filter(owner_id=self.caller.pk).select_related("item")
            self.msg(
                "Your Companions:\n"
                + "\n".join(
                    f"{row.item.key} (#{row.item_id}): {row.mode}; location #{row.item.db_location_id}."
                    for row in rows
                )
            )
            return
        if switch not in ("follow", "stay", "pose", "trick"):
            raise CraftingError("Use +pet, /follow, /stay, /pose or /trick.")
        ids = CompanionState.objects.filter(owner_id=self.caller.pk).values_list(
            "item_id", flat=True
        )
        item = self.caller.search(
            self.lhs.strip(), candidates=list(ObjectDB.objects.filter(pk__in=ids))
        )
        if item is None:
            return
        if switch in ("follow", "stay"):
            companions.set_mode(self.caller, item, switch)
            self.msg(f"{item.key}: {switch}.")
        elif switch == "pose":
            if self.rhs is None:
                raise CraftingError("Use +pet/pose companion = pose text.")
            companions.pose(self.caller, item, self.rhs)
        else:
            from .wave_two import activate

            activate(self.caller, item, self.rhs.strip() if self.rhs else None)
