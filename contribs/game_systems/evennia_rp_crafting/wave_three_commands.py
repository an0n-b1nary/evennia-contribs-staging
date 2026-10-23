# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exact service offers and owner-directed cosmetic Companions."""

from django.db.models import Q
from evennia.objects.models import ObjectDB
from evennia.utils.dbserialize import deserialize

from . import companions, conf, modifiers, services
from .behaviours import behaviour
from .command_base import CraftCommand
from .command_syntax import bare_value, select_resource
from .errors import CraftingError
from .models import CompanionState, ModificationLayer, ModificationOffer

MODIFY_DRAFT_KEY = "rp_crafting_modify_draft"


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
      +modify/new <customer>/<target> = <niche>/<modifier>
      +modify/undo <customer>/<target> = <niche>
      +modify/line <prose>
      +modify/resources <quantity> <resource key>  (repeat per resource; replaces that key)
      +modify/unresource <resource key>
      +modify/price <commission>  (defaults to zero)
      +modify/replace <layer number>  (blank clears; required for undo)
      +modify/offer
      +modify/cancel
      +modify/accept <service number>
      +modify/cancel <service number>
      +modify/layers <target>
      +modify/hide <layer number>
      +modify/show <layer number>

    /new and /undo start persistent drafts; bare +modify previews yours and lists
    recent services. /cancel alone discards your draft; with a service number it
    cancels that offer. /offer sends the exact terms and clears the draft only on
    success. Drafts and offers reserve nothing. The maker supplies materials and
    pays the craft fee; the customer pays the commission.
    A changed target, ownership, layer or cost requires a new offer. Self services
    still require acceptance with zero commission. Hiding is free OOC visibility;
    undoing is a paid IC service. Both preserve history.
    """

    key = "+modify"
    switch_options = (
        "new",
        "undo",
        "line",
        "resources",
        "unresource",
        "price",
        "replace",
        "offer",
        "accept",
        "cancel",
        "layers",
        "hide",
        "show",
    )
    wave_three = True

    def start_draft(self, switch):
        usage = (
            "Usage: +modify/new customer/target = niche/modifier"
            if switch == "new"
            else "Usage: +modify/undo customer/target = niche"
        )
        if self.rhs is None or self.lhs.count("/") != 1:
            raise CraftingError(usage)
        customer_name, target_name = (part.strip() for part in self.lhs.split("/"))
        terms = [part.strip() for part in self.rhs.split("/")]
        if (
            not customer_name
            or not target_name
            or not all(terms)
            or len(terms) != (2 if switch == "new" else 1)
        ):
            raise CraftingError(usage)
        niche = services.niche(terms[0])
        kind = terms[1] if switch == "new" else "modifier_undo"
        implementation = behaviour(kind)
        if implementation.role != "service" or kind not in niche.behaviours:
            raise CraftingError("That niche doesn't grant this Modifier service.")
        if not implementation.available() or not conf.component_visible(self.caller, kind):
            raise CraftingError("That Modifier service is unavailable; services require Economy.")
        if switch == "new" and implementation.kind == "undo":
            raise CraftingError("Start an undo draft with +modify/undo customer/target = niche.")
        customer = self.caller.search(customer_name)
        if customer is None:
            return
        target = self.caller.search(
            target_name,
            candidates=[
                customer,
                *customer.contents,
                *(customer.location.contents if customer.location else []),
            ],
        )
        if target is None:
            return
        draft = {
            "customer_id": customer.pk,
            "target_id": target.pk,
            "niche": niche.key,
            "modifier": kind,
            "configuration": {},
            "selected": {},
            "commission": 0,
        }
        self.caller.attributes.add(MODIFY_DRAFT_KEY, draft)
        self.preview_draft(draft)

    def preview_draft(self, draft):
        def name(pk):
            obj = ObjectDB.objects.filter(pk=pk).first()
            return f"{obj.key} (#{pk})" if obj else f"unavailable (#{pk})"

        config = draft["configuration"]
        selected = (
            ", ".join(f"{quantity} {key}" for key, quantity in draft["selected"].items()) or "none"
        )
        self.msg(
            f"Service draft: {draft['niche']}/{draft['modifier']}\n"
            f"Customer: {name(draft['customer_id'])}; target: {name(draft['target_id'])}.\n"
            f"Line: {config.get('line', '(not set)')}\n"
            f"Layer to replace or undo: {config.get('layer_id', 'none')}.\n"
            f"Maker resources: {selected}. Customer commission: {draft['commission']}.\n"
            "Nothing reserved or paid. +modify/offer validates costs and sends the exact quote for acceptance."
        )

    def edit_draft(self, switch):
        if switch == "offer" and self.args.strip():
            raise CraftingError("Usage: +modify/offer (send your draft). Start with +modify/new.")
        stored = self.caller.attributes.get(MODIFY_DRAFT_KEY)
        if not stored:
            raise CraftingError("Start a service draft with +modify/new or +modify/undo.")
        draft = deserialize(stored)
        if switch == "offer":
            customer = ObjectDB.objects.filter(pk=draft["customer_id"]).first()
            target = ObjectDB.objects.filter(pk=draft["target_id"]).first()
            if customer is None or target is None:
                raise CraftingError("The customer or target no longer exists; start a new draft.")
            row = modifiers.propose(
                self.caller,
                customer,
                target,
                draft["niche"],
                draft["modifier"],
                draft["configuration"],
                draft["selected"],
                commission=draft["commission"],
            )
            self.caller.attributes.remove(MODIFY_DRAFT_KEY)
            details = modifiers.ServiceAsset().describe(str(row.pk))
            self.msg(details)
            customer.msg(
                f"{self.caller.key} offers {details}. Use +modify/accept {row.pk} or +modify/cancel {row.pk}."
            )
            return
        value = bare_value(self)
        if switch == "line":
            from .wave_two import line

            if behaviour(draft["modifier"]).kind == "undo":
                raise CraftingError(
                    "Undo drafts have no replacement prose; select the layer with /replace."
                )
            draft["configuration"]["line"] = line(value, "Modification")
        elif switch in ("resources", "unresource"):
            select_resource(draft, value, remove=switch == "unresource")
        elif switch == "price":
            draft["commission"] = _number(
                value, "Use a nonnegative whole-number commission.", minimum=0
            )
        elif switch == "replace":
            if value:
                draft["configuration"]["layer_id"] = _number(
                    value, "Use a layer number.", prefix=True
                )
            else:
                draft["configuration"].pop("layer_id", None)
        self.caller.attributes.add(MODIFY_DRAFT_KEY, draft)
        self.preview_draft(draft)

    def run(self, switch):
        if switch in ("new", "undo"):
            self.start_draft(switch)
            return
        if switch in ("line", "resources", "unresource", "price", "replace", "offer"):
            self.edit_draft(switch)
            return
        if switch == "cancel" and not self.args.strip():
            self.caller.attributes.remove(MODIFY_DRAFT_KEY)
            self.msg("Service draft discarded.")
            return
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
        if switch == "layers":
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
            if self.args.strip():
                raise CraftingError("Usage: +modify (preview your draft and list recent services).")
            draft = self.caller.attributes.get(MODIFY_DRAFT_KEY)
            if draft:
                self.preview_draft(deserialize(draft))
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
                "See help +modify for service drafts, acceptance and layer history."
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
