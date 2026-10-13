# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Staff-approved plot budgets, frozen at conclusion and safely retryable."""

import logging

from django.apps import apps
from django.db import transaction
from django.utils import timezone
from evennia.objects.models import ObjectDB

from . import conf
from .batch import eligible_characters
from .models import PlotPayoutReceipt, PlotPayoutRun, PlotThreadResourcePayout
from .services import ResourceError, _quantity, definition, grant

logger = logging.getLogger("evennia")


def plot_for(actor, plot_id, *, staff=False, mutable=False):
    if not apps.is_installed("evennia_plots"):
        raise ResourceError("Plots is not installed.")
    model = apps.get_model("evennia_plots", "PlotThread")
    plot = model.objects.select_for_update().filter(pk=plot_id).first()
    if not plot or not (conf.is_staff(actor) or (not staff and plot.is_owner(actor))):
        raise ResourceError("Only plot owners or staff may manage this payout.")
    if mutable and (
        plot.status not in {"proposed", "active"}
        or PlotPayoutRun.objects.filter(thread_id=plot.pk).exists()
    ):
        raise ResourceError("The plot award is frozen; use logged staff adjustments.")
    return plot


@transaction.atomic
def propose(actor, plot_id, key, quantity):
    plot_for(actor, plot_id, mutable=True)
    _quantity(quantity)
    if quantity > 2**63 - 1:
        raise ResourceError("Payout quantity exceeds the supported range.")
    resource = definition(key)
    row, _ = PlotThreadResourcePayout.objects.update_or_create(
        thread_id=plot_id,
        resource=resource,
        defaults={"quantity": quantity, "set_by_id": actor.pk, "approved_by_id": None},
    )
    return row


@transaction.atomic
def approve(actor, plot_id):
    plot_for(actor, plot_id, staff=True, mutable=True)
    rows = list(
        PlotThreadResourcePayout.objects.filter(thread_id=plot_id).select_related("resource")
    )
    if not rows or any(row.resource.archived for row in rows):
        raise ResourceError("Supply a budget of active resources before approval.")
    PlotThreadResourcePayout.objects.filter(pk__in=[row.pk for row in rows]).update(
        approved_by_id=actor.pk
    )
    return len(rows)


@transaction.atomic
def remove(actor, plot_id, key):
    plot_for(actor, plot_id, mutable=True)
    PlotThreadResourcePayout.objects.filter(thread_id=plot_id, resource__key=key).delete()


@transaction.atomic
def on_concluded(sender, thread, **kwargs):
    # Conclude holds the plot row lock, shared with budget editing. No owner or
    # Thread lead becomes a participant merely by holding that role.
    if PlotPayoutRun.objects.filter(thread_id=thread.pk).exists():
        return
    rows = list(
        PlotThreadResourcePayout.objects.filter(thread_id=thread.pk).select_related("resource")
    )
    if any(not row.approved_by_id or row.resource.archived for row in rows):
        raise ResourceError("Approve all payout resources before concluding this plot.")
    eligible = {character.pk for character in eligible_characters()}
    recipients = list(
        thread.participants.filter(is_active=True, character_id__in=eligible)
        .order_by("character_id")
        .values("character_id", "character_name")
    )
    run = PlotPayoutRun.objects.create(
        thread_id=thread.pk,
        plot_name=thread.name,
        amounts={row.resource.key: row.quantity for row in rows},
        approvals={row.resource.key: row.approved_by_id for row in rows},
        recipients=recipients,
    )
    PlotPayoutReceipt.objects.bulk_create(
        [PlotPayoutReceipt(run=run, **recipient) for recipient in recipients]
    )
    # Delivery failures never undo a conclusion: the durable snapshot can retry.
    transaction.on_commit(lambda: deliver(run.pk))


def deliver(run_id):
    result = {"paid": [], "skipped": [], "errors": {}}
    for receipt_id in PlotPayoutReceipt.objects.filter(
        run_id=run_id, paid_at__isnull=True, skipped=False
    ).values_list("pk", flat=True):
        try:
            with transaction.atomic():
                # Character first, matching the holdings service and economy.
                initial = PlotPayoutReceipt.objects.get(pk=receipt_id)
                character = (
                    ObjectDB.objects.select_for_update().filter(pk=initial.character_id).first()
                )
                receipt = (
                    PlotPayoutReceipt.objects.select_for_update()
                    .select_related("run")
                    .get(pk=receipt_id)
                )
                if receipt.paid_at or receipt.skipped:
                    continue
                if character is None:
                    receipt.skipped = True
                    receipt.save(update_fields=["skipped"])
                    result["skipped"].append(receipt.character_id)
                    continue
                for key, quantity in receipt.run.amounts.items():
                    grant(
                        character,
                        key,
                        quantity,
                        "payout",
                        allow_archived=True,
                        thread_id=receipt.run.thread_id,
                        by=receipt.run.approvals[key],
                        note=f"Plot award: {receipt.run.plot_name}",
                        details={"payout_run": run_id, "receipt": receipt.pk},
                    )
                receipt.paid_at = timezone.now()
                receipt.save(update_fields=["paid_at"])
                result["paid"].append(character.pk)
        except Exception as exc:
            logger.exception("Resource plot payout %s receipt %s failed", run_id, receipt_id)
            result["errors"][receipt_id] = str(exc)
    return result


def retry(actor, plot_id):
    with transaction.atomic():
        plot_for(actor, plot_id, staff=True)
        run = PlotPayoutRun.objects.filter(thread_id=plot_id).first()
        if run is None:
            raise ResourceError("No frozen award exists; historical plots are not backfilled.")
    return deliver(run.pk)
