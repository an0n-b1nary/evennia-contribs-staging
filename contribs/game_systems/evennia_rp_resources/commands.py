# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Player gathering choices and audited staff controls."""

from evennia import CmdSet
from evennia.commands.default.muxcommand import MuxCommand

from evennia_links.command_syntax import StrictSwitchMixin, whole_number

from . import conf
from .batch import holdings_cap, run_weekly_batch
from .catalog import seed_catalog
from .command_syntax import split_comment
from .gathering import LEAN_ATTRIBUTE, lean_description, pool, set_lean
from .models import ResourceGrant, ResourceHolding
from .services import ResourceError, grant, spend, total_held
from .summary import gains_text, latest_receipt


class _ResourceCommand(StrictSwitchMixin, MuxCommand):
    locks = "cmd:all()"
    help_category = "Resources"

    def access(self, srcobj, access_type="cmd", default=False, **kwargs):
        return super().access(srcobj, access_type, default, **kwargs) and conf.visible(srcobj)


class CmdGather(_ResourceCommand):
    """Choose which resources you gather, without changing the quantity.

    Usage: +gather [resource or category], +gather/clear
    Choices persist. Only open terrain resources and the common pool are offered.
    """

    switch_options = ("clear",)

    key = "+gather"

    def func(self):
        if not conf.visible(self.caller):
            return
        try:
            if self.switches == ["clear"]:
                self.caller.attributes.remove(LEAN_ATTRIBUTE)
                self.msg("Gathering lean cleared.")
            elif self.switches:
                self.msg("Usage: +gather [resource or category] or +gather/clear")
            elif self.args.strip():
                set_lean(self.caller, self.args)
                self.msg(f"Gathering lean: {lean_description(self.caller)}.")
            else:
                choices = (
                    ", ".join(f"{resource.name} ({resource.key})" for resource in pool()) or "none"
                )
                self.msg(
                    f"Gathering lean: {lean_description(self.caller)}.\nOpen resources: {choices}\nCategories: {', '.join(conf.categories().values())}"
                )
        except ResourceError as exc:
            self.msg(str(exc))


class CmdResources(_ResourceCommand):
    """View holdings and recent accrual; staff can seed, grant, spend and audit.

    Usage:
      +resources
      +resources/catalog
      +resources/run [dry]                    (staff)
      +resources/seed                         (staff; update configured catalogue)
      +resources/grant <character>=<quantity> <resource> [# note]   (staff)
      +resources/spend <character>=<quantity> <resource> [# note]   (staff)
      +resources/audit [character]            (staff; last 30 ledger rows)
      +resources/payout <plot>=<quantity> <resource> (owner/staff proposal)
      +resources/payoutremove <plot>=<resource>      (owner/staff)
      +resources/payouts <plot>                    (owner/staff inspection)
      +resources/payoutapprove <plot>              (staff)
      +resources/payoutretry <plot>                (staff; frozen award only)
    """

    key = "+resources"
    switch_options = (
        "catalog",
        "run",
        "seed",
        "grant",
        "spend",
        "audit",
        "payout",
        "payoutremove",
        "payouts",
        "payoutapprove",
        "payoutretry",
    )

    def func(self):
        if not conf.visible(self.caller):
            return
        try:
            self._run()
        except (ResourceError, ValueError) as exc:
            self.msg(str(exc))

    def _run(self):
        if self.switches:
            if len(self.switches) != 1:
                raise ResourceError("Use one switch at a time.")
            switch = self.switches[0]
            if switch in {"payout", "payoutremove", "payouts", "payoutapprove", "payoutretry"}:
                from django.apps import apps
                from django.db import transaction

                from . import payouts
                from .models import PlotPayoutRun, PlotThreadResourcePayout

                if not apps.is_installed("evennia_plots"):
                    raise ResourceError("Plots is not installed.")
                plot = (
                    apps.get_model("evennia_plots", "PlotThread")
                    .objects.filter(plot_number=whole_number(self.lhs.strip().lstrip("#")))
                    .first()
                )
                if plot is None:
                    raise ResourceError("No such plot.")
                plot_id = plot.pk
                if switch == "payout":
                    key, amount = quantity_resource(self.rhs or "")
                    payouts.propose(self.caller, plot_id, key, amount)
                    self.msg("Payout proposed; staff approval is required.")
                elif switch == "payoutremove":
                    payouts.remove(self.caller, plot_id, (self.rhs or "").strip())
                    self.msg("Payout resource removed.")
                elif switch == "payoutapprove":
                    self.msg(f"Approved {payouts.approve(self.caller, plot_id)} payout resources.")
                elif switch == "payoutretry":
                    self.msg(f"Payout retry: {payouts.retry(self.caller, plot_id)}")
                else:
                    with transaction.atomic():
                        payouts.plot_for(self.caller, plot_id)
                        run = PlotPayoutRun.objects.filter(thread_id=plot_id).first()
                        rows = PlotThreadResourcePayout.objects.filter(
                            thread_id=plot_id
                        ).select_related("resource")
                        self.msg(
                            "\n".join(
                                f"{row.resource.key}: {row.quantity} each; {'approved' if row.approved_by_id else 'awaiting approval'}"
                                for row in rows
                            )
                            or "No payout budget."
                        )
                        if run:
                            self.msg(
                                f"Frozen award: {run.amounts}; {len(run.recipients)} recipients; {run.receipts.filter(paid_at__isnull=True, skipped=False).count()} pending."
                            )
                return
            if switch == "catalog":
                self.msg(
                    "\n".join(
                        f"{resource.key}: {resource.name} [{resource.category}]"
                        for resource in pool()
                    )
                    or "No open resources."
                )
                return
            if not conf.is_staff(self.caller):
                raise ResourceError("Only staff may use this switch.")
            if switch == "run":
                if self.args.strip() not in ("", "dry"):
                    raise ResourceError("Usage: +resources/run [dry]")
                result = run_weekly_batch(dry_run=self.args.strip() == "dry")
                verb = "Preview" if self.args.strip() else "Batch"
                self.msg(
                    f"{verb} {result['week']}: {len(result['characters'])} characters; {sum(sum(amounts.values()) for amounts in result['characters'].values())} units. Errors: {result['errors']}"
                )
                return
            if switch == "seed":
                self.msg(f"Catalogue seeded: {len(seed_catalog(update=True))} resources.")
                return
            if switch in ("grant", "spend"):
                text, note = split_comment(self.args)
                target_text, separator, stock = text.partition("=")
                if not separator or not target_text.strip() or not stock.strip():
                    raise ResourceError(
                        f"Usage: +resources/{switch} <character>=<quantity> <resource> [# note]"
                    )
                key, amount = quantity_resource(stock)
                target = self.caller.search(target_text.strip(), global_search=True)
                if not target:
                    return
                note = note or "Staff adjustment"
                if switch == "grant":
                    grant(target, key, amount, "staff", by=self.caller, note=note)
                else:
                    spend(target, key, amount, note, source="staff", by=self.caller)
                self.msg(f"Resources updated for {target.key}.")
                return
            if switch == "audit":
                target = (
                    self.caller.search(self.args, global_search=True)
                    if self.args.strip()
                    else self.caller
                )
                if not target:
                    return
                rows = (
                    ResourceGrant.objects.filter(character=target)
                    .select_related("resource")
                    .order_by("-pk")[:30]
                )
                self.msg(
                    "\n".join(
                        f"#{row.pk} {row.source}: {row.quantity:+d} {row.resource.key if row.resource else '(batch)'} {row.week} by #{row.by_id}: {row.note}"
                        for row in rows
                    )
                    or "No grants."
                )
                return
            raise ResourceError("Unknown resources switch. See help +resources.")
        rows = (
            ResourceHolding.objects.filter(character=self.caller, quantity__gt=0)
            .select_related("resource")
            .order_by("resource__category", "resource__key")
        )
        message = (
            f"Resources: {total_held(self.caller)} units; trickle cap {holdings_cap(self.caller)}.\n"
            + (
                "\n".join(f"{row.resource.name}: {row.quantity}" for row in rows)
                or "Your stores are empty."
            )
        )
        receipt = latest_receipt(self.caller)
        if receipt:
            message += f"\nLast batch ({receipt.week}): {gains_text(self.caller, receipt.week)}."
        self.msg(message)


def quantity_resource(text):
    """Read one give-style quantity and resource key, without inline options."""
    try:
        amount, key = text.split()
        return key, whole_number(amount)
    except ValueError as exc:
        raise ResourceError(
            "Supply a whole quantity followed by a resource key, such as 2 timber."
        ) from exc


class ResourcesCmdSet(CmdSet):
    key = "ResourcesCmdSet"

    def at_cmdset_creation(self):
        self.add(CmdGather)
        self.add(CmdResources)
