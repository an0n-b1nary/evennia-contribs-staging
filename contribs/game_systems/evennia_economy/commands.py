# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.db.models import Q
from evennia import CmdSet
from evennia.commands.default.muxcommand import MuxCommand

from . import assets, conf
from .batch import money_cap, run_stipends, run_weekly_batch
from .exchange import accept_offer, cancel_offer, create_offer, expire_offers
from .models import LedgerEntry, Offer, ReviewFlag
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
    """Give a carried item or other asset under the same exchange safeguards.

    give <assets> = <character>
    Uses the same account, freeze, item-hook and fee checks as +offer.
    """

    key = "give"
    rhs_split = ("=", " to ")
    arg_regex = r"\s|$"

    def run(self):
        if not self.rhs or self.switches:
            raise EconomyError("Usage: give <assets> = <character>")
        target = self.caller.search(self.rhs)
        if not target:
            return
        # Creation and immediate acceptance are one outer transaction. A failed
        # gift leaves no spurious open offer.
        from django.db import transaction

        with transaction.atomic():
            offer = create_offer(self.caller, target, assets.parse_spec(self.caller, self.lhs))
            accept_offer(target, offer.pk)
        self.msg("Gift completed.")


class CmdEconomy(EconomyCommand):
    """Staff economy reconciliation, adjustments and review queue.

    +economy                     (money/partner totals and per-account accrual)
    +economy/run [dry]            (weekly UBI preview/payment)
    +economy/stipends             (reconcile first eligibility/reveal stipends)
    +economy/credit character=amount[,note]
    +economy/debit character=amount[,note]
    +economy/audit [character]    (last 50 journal entries)
    +economy/flags                (unreviewed round trips)
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


class EconomyCmdSet(CmdSet):
    key = "EconomyCmdSet"

    def at_cmdset_creation(self):
        for command in (CmdBalance, CmdOffer, CmdAccept, CmdGive, CmdEconomy):
            self.add(command)
