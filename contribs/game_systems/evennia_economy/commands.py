# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.db.models import Q
from evennia import CmdSet
from evennia.commands.default.muxcommand import MuxCommand

from . import assets, conf
from .batch import money_cap, run_stipends, run_weekly_batch
from .exchange import accept_offer, cancel_offer, create_offer, expire_offers, give
from .models import LedgerEntry, Offer, ReviewFlag, Storefront
from .reports import account_accrual, reconciliation
from .services import EconomyError, balance, credit, debit


class EconomyCommand(MuxCommand):
    locks = "cmd:all()"
    help_category = "Economy"

    def access(self, srcobj, access_type="cmd", default=False, **kwargs):
        return super().access(srcobj, access_type, default, **kwargs) and conf.visible(srcobj)

    def func(self):
        if not conf.visible(self.caller):
            return
        try:
            self.run()
        except (EconomyError, ValueError) as exc:
            self.msg(str(exc))


class CmdBalance(EconomyCommand):
    """View your purse and the soft cap on passive income: +balance."""

    key = "+balance"
    aliases = ("+purse",)

    def run(self):
        self.msg(
            f"Purse: {conf.currency(balance(self.caller))}; income cap {conf.currency(money_cap(self.caller))}."
        )


class CmdOffer(EconomyCommand):
    """Offer an atomic swap or gift in the same room.

    +offer[/secret] character = give [for want]
    +offer                       (list your sent and received offers)
    +offer/cancel <number>
    Assets: 40 coins, resource:grain:3, item:#12, or a carried item's name.
    Nothing is reserved. Acceptance rechecks all stock and permissions.
    """

    key = "+offer"

    def run(self):
        if "cancel" in self.switches:
            if self.switches != ["cancel"]:
                raise EconomyError("Use one offer switch.")
            cancel_offer(self.caller, int(self.args.strip().lstrip("#")))
            self.msg("Offer cancelled.")
            return
        if set(self.switches) - {"secret"}:
            raise EconomyError("Usage: +offer[/secret] character=give [for want]")
        expire_offers()
        if not self.args.strip():
            offers = Offer.objects.filter(
                Q(giver=self.caller) | Q(recipient=self.caller), status="open"
            )
            self.msg(
                "\n".join(
                    f"#{o.pk}: {o.giver.key} to {o.recipient.key}: {assets.describe(o.give)} for {assets.describe(o.want)}"
                    for o in offers
                )
                or "No open offers."
            )
            return
        if not self.rhs:
            raise EconomyError("Usage: +offer[/secret] character=give [for want]")
        target = self.caller.search(self.lhs)
        if not target:
            return
        give_text, separator, want_text = self.rhs.partition(" for ")
        give = assets.parse_spec(self.caller, give_text)
        want = assets.parse_spec(target, want_text) if separator else []
        offer = create_offer(self.caller, target, give, want, secret="secret" in self.switches)
        self.msg(f"Offer #{offer.pk} sent to {target.key}.")
        target.msg(
            f"Offer #{offer.pk} from {self.caller.key}: {assets.describe(give)} for {assets.describe(want)}. Use +accept {offer.pk}."
        )


class CmdAccept(EconomyCommand):
    """Accept an offer addressed to you: +accept[/secret] <number>."""

    key = "+accept"

    def run(self):
        if set(self.switches) - {"secret"}:
            raise EconomyError("Usage: +accept[/secret] number")
        offer = accept_offer(
            self.caller, int(self.args.strip().lstrip("#")), secret="secret" in self.switches
        )
        self.msg(f"Offer #{offer.pk} accepted.")


class CmdGive(EconomyCommand):
    """Give something you carry to someone here.

    give <things> = <character>
    give <things> to <character>

    Separate several things with commas. Giving to your own other characters
    isn't allowed.
    """

    # Replaces Evennia's give, so it stays available while the economy is hidden:
    # then (for non-staff) it hands over carried items only, and says nothing of
    # money or other assets. Coins and resources follow the market's freeze and fees.
    key = "give"
    rhs_split = ("=", " to ")
    arg_regex = r"\s|$"
    help_category = "General"

    def access(self, srcobj, access_type="cmd", default=False, **kwargs):
        return super(EconomyCommand, self).access(srcobj, access_type, default, **kwargs)

    def func(self):
        try:
            self.run()
        except (EconomyError, ValueError) as exc:
            self.msg(str(exc))

    def run(self):
        if not self.lhs or not self.rhs or self.switches:
            raise EconomyError("Usage: give <things> = <character>")
        target = self.caller.search(self.rhs)
        if not target:
            return
        spec = assets.parse_spec(self.caller, self.lhs, items_only=not conf.visible(self.caller))
        offer = give(self.caller, target, spec)
        described = assets.describe(offer.give)
        self.msg(f"You give {described} to {target.key}.")
        target.msg(f"{self.caller.key} gives you {described}.")


class CmdEconomy(EconomyCommand):
    """Staff economy reconciliation, adjustments and review queue.

    +economy                     (money/partner totals and per-account accrual)
    +economy/run [dry]            (weekly UBI preview/payment)
    +economy/stipends             (reconcile first eligibility/reveal stipends)
    +economy/credit character=amount[,note]
    +economy/debit character=amount[,note]
    +economy/audit [character]    (last 50 journal entries)
    +economy/flags                (unreviewed round trips, floor transfers, quiet stalls)
    +economy/reviewed number
    Freeze and reveal: +runtime RP_ECONOMY_FROZEN=true, etc.
    """

    key = "+economy"

    def run(self):
        if not conf.is_staff(self.caller):
            raise EconomyError("Only staff may use +economy. Use +balance for your purse.")
        if len(self.switches) > 1:
            raise EconomyError("Use one economy switch at a time.")
        switch = self.switches[0] if self.switches else ""
        if not switch:
            self.msg(
                f"Economy: {reconciliation()}\n"
                + "\n".join(
                    f"Account #{r['id']} {r['name']}: {r['characters']} characters; balance {r['balance']}; UBI {r['ubi']}; stipends {r['stipends']}"
                    for r in account_accrual()
                )
            )
        elif switch == "run":
            if self.args.strip() not in ("", "dry"):
                raise EconomyError("Usage: +economy/run [dry]")
            result = run_weekly_batch(dry_run=self.args.strip() == "dry")
            ubi = sum(row["ubi"] for row in result["characters"].values())
            stipends = sum(sum(row["stipends"].values()) for row in result["characters"].values())
            self.msg(
                f"{'Preview' if self.args.strip() else 'Batch'} {result['week']}: {len(result['characters'])} characters; UBI {conf.currency(ubi)}; stipends {conf.currency(stipends)}; frozen={result['frozen']}; errors={result['errors']}"
            )
        elif switch == "stipends":
            self.msg(f"Stipends: {run_stipends()}")
        elif switch in ("credit", "debit"):
            if not self.rhs:
                raise EconomyError("Usage: +economy/credit character=amount[,note]")
            target = self.caller.search(self.lhs, global_search=True)
            if not target:
                return
            amount, _, note = self.rhs.partition(",")
            (credit if switch == "credit" else debit)(
                target, int(amount), by=self.caller, note=note.strip()
            )
            self.msg(f"Purse updated for {target.key}.")
        elif switch == "audit":
            rows = LedgerEntry.objects.all()
            if self.args.strip():
                target = self.caller.search(self.args, global_search=True)
                if not target:
                    return
                rows = rows.filter(Q(from_id=target.pk) | Q(to_id=target.pk))
            self.msg(
                "\n".join(
                    f"#{r.pk} {r.kind}: {r.from_name or '(mint)'} -> {r.to_name or '(sink)'}; amount {r.amount}; fee {r.fee} {r.fee_kind}; assets {r.assets}; {r.note}"
                    for r in rows.order_by("-pk")[:50]
                )
                or "No ledger entries."
            )
        elif switch == "flags":
            self.msg(
                "\n".join(
                    f"#{r.pk} {r.title}: {r.description}"
                    for r in ReviewFlag.objects.filter(reviewed=False).order_by("-pk")[:50]
                )
                or "No review flags."
            )
        elif switch == "reviewed":
            if not ReviewFlag.objects.filter(pk=int(self.args.strip().lstrip("#"))).update(
                reviewed=True
            ):
                raise EconomyError("No such flag.")
            self.msg("Flag marked reviewed.")
        else:
            raise EconomyError("Unknown economy switch. See help +economy.")


class CmdStall(EconomyCommand):
    """Manage a stall in a market room.

    +stall                       (your stalls)
    +stall/claim [name]
    +stall/name [stall number] = name
    +stall/desc [stall number] = description
    +stall/list [stall number/]item or lot = price
    +stall/unlist listing number
    +stall/close [stall number]

    Listing reserves the stock. Buyers must visit, but you can be offline.
    Staff can close any stall remotely to return its stock, even while frozen.
    """

    key = "+stall"

    def run(self):
        from . import stalls

        if len(self.switches) > 1:
            raise EconomyError("Use one stall switch at a time.")
        switch = self.switches[0] if self.switches else ""
        if not switch:
            own = Storefront.objects.filter(owner=self.caller, status="open").order_by("pk")
            self.msg(
                "\n".join(f"#{s.pk} {s.name} in {s.room.key}" for s in own)
                or "You hold no stalls. Use +stall/claim in a market room."
            )
            return
        if switch == "claim":
            store = stalls.claim(self.caller, name=self.args.strip() or None)
            self.msg(f"Claimed stall #{store.pk}: {store.name}.")
            return
        if switch == "unlist":
            listing = stalls.unlist(self.caller, int(self.args.strip().lstrip("#")))
            self.msg(f"Listing #{listing.pk} returned to your inventory.")
            return
        if switch not in ("name", "desc", "list", "close"):
            raise EconomyError("Unknown stall switch. See help +stall.")
        if switch == "list":
            if not self.rhs:
                raise EconomyError("Usage: +stall/list item or lot = price")
            stores = Storefront.objects.filter(
                owner=self.caller, room_id=stalls.place(self.caller), status="open"
            )
            asset_text = self.lhs
            number, separator, stock = self.lhs.partition("/")
            if separator and number.strip().lstrip("#").isdecimal():
                stores = stores.filter(pk=int(number.strip().lstrip("#")))
                asset_text = stock
        else:
            target = self.args.strip() if switch == "close" else self.lhs.strip()
            stores = Storefront.objects.filter(status="open")
            if target:
                stores = stores.filter(pk=int(target.lstrip("#")))
            else:
                stores = stores.filter(owner=self.caller, room_id=stalls.place(self.caller))
        choices = list(stores[:2])
        if len(choices) != 1:
            raise EconomyError("Choose a stall by number, or visit your only stall in this room.")
        store = choices[0]
        if switch == "list":
            listing = stalls.list_stock(
                self.caller,
                store.pk,
                assets.parse_spec(self.caller, asset_text),
                int(self.rhs.strip()),
            )
            self.msg(
                f"Listing #{listing.pk}: {assets.describe(listing.assets)} for {conf.currency(listing.price)}."
            )
        elif switch == "close":
            stalls.close(self.caller, store.pk)
            self.msg(f"Stall #{store.pk} closed; reserved stock returned to its owner.")
        else:
            if self.rhs is None:
                raise EconomyError(f"Usage: +stall/{switch} [number] = text")
            stalls.edit(
                self.caller, store.pk, **{"name" if switch == "name" else "description": self.rhs}
            )
            self.msg("Stall updated.")


class CmdBrowse(EconomyCommand):
    """Browse nearby stalls: +browse [stall number]. Discovery is also global via +market."""

    key = "+browse"

    def run(self):
        from . import stalls

        stores = stalls.directory(self.caller, room=stalls.place(self.caller))
        if self.args.strip():
            number = int(self.args.strip().lstrip("#"))
            stores = [(s, rows) for s, rows in stores if s.pk == number]
        lines = []
        for store, listings in stores:
            lines.append(f"Stall #{store.pk}: {store.name} ({store.owner.key})")
            if store.description:
                lines.append(store.description)
            lines.extend(
                f"  Listing #{r.pk}: {assets.describe(r.assets)} — {conf.currency(r.price)}"
                for r in listings
            )
            if not listings:
                lines.append("  No stock for sale.")
        self.msg("\n".join(lines) or "No open stalls here.")


class CmdBuy(EconomyCommand):
    """Buy a reserved listing in this room: +buy listing number."""

    key = "+buy"

    def run(self):
        from .stalls import buy

        if self.switches:
            raise EconomyError("Usage: +buy listing number")
        listing = buy(self.caller, int(self.args.strip().lstrip("#")))
        self.msg(
            f"Bought listing #{listing.pk}: {assets.describe(listing.assets)} for {conf.currency(listing.price)}."
        )


class CmdMarket(EconomyCommand):
    """Find open stalls by name, description or listed stock: +market [search text].

    Discovery is global. Visit the stall's room to buy.
    """

    key = "+market"

    def run(self):
        from .stalls import directory

        self.msg(
            "\n".join(
                f"#{s.pk} {s.name} — {s.room.key} ({len(rows)} listings)"
                for s, rows in directory(self.caller, self.args.strip())
            )
            or "No matching open stalls."
        )


class EconomyCmdSet(CmdSet):
    key = "EconomyCmdSet"

    def at_cmdset_creation(self):
        for command in (
            CmdBalance,
            CmdOffer,
            CmdAccept,
            CmdGive,
            CmdEconomy,
            CmdStall,
            CmdBrowse,
            CmdBuy,
            CmdMarket,
        ):
            self.add(command)
