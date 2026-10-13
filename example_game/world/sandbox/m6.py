"""Persistent approved shop and plot budget; system seller stays switched off."""

from django.db import transaction
from evennia_building import services
from evennia_building.models import BuildProject, Property
from evennia_economy import shops, stalls
from evennia_economy.models import Listing
from evennia_plots.models import PlotThread
from evennia_rp_resources import payouts
from evennia_rp_resources.models import PlotThreadResourcePayout
from evennia_rp_resources.services import grant

from .building_seed import _object


@transaction.atomic
def seed(market):
    owner = _object("Demo Shopkeeper", "typeclasses.characters.Character")
    reviewer = _object("Demo Building Reviewer", "typeclasses.characters.Character")
    reviewer.permissions.add("Builder")
    court = _object("Supply Court", "typeclasses.rooms.Room")
    court.db.room_type = "ic"
    court.db.allow_teleport = "public"
    court.db.desc = "A persistent court for the supply shop. The market quartermaster is disabled until staff enable the system seller."
    from evennia.objects.models import ObjectDB
    from evennia.utils.create import create_object

    for source, target, name in ((market, court, "supply court"), (court, market, "market")):
        if not ObjectDB.objects.filter(db_location=source, db_destination=target).exists():
            create_object("typeclasses.exits.Exit", key=name, location=source, destination=target)
    project = BuildProject.objects.filter(owner=owner, name="Sample Supply Shop").first()
    if project is None:
        project = services.new_project(owner, "Sample Supply Shop", purpose="shop")
        entry = project.rooms.get(entry=True)
        services.edit_project(
            owner,
            project,
            room=entry,
            description="A small supply counter. Use +browse to inspect its reserved stock.",
        )
        services.attach(owner, project, court, "supply shop")
        project.refresh_from_db()
        from django.conf import settings

        acknowledgement = getattr(
            settings,
            "BUILDING_REUSE_ACKNOWLEDGEMENT",
            "I acknowledge that this submitted content may be reused by this game.",
        )
        submission = services.submit(
            owner, project, expected_version=project.version, acknowledgement=acknowledgement
        )
        services.review(
            reviewer,
            submission,
            expected_revision=submission.revision,
            outcome="approved",
            reason="Reference supply shop.",
        )
    property = Property.objects.get(promotion__project=project)
    store = shops.reconcile(reviewer, property.pk)
    if (
        store.status == "open"
        and not Listing.objects.filter(storefront=store, status="active").exists()
    ):
        original = owner.location
        owner.location = store.room
        try:
            grant(owner, "timber", 2, note="Reference shop stock")
            stalls.list_stock(
                owner, store.pk, [{"kind": "resource", "key": "timber", "quantity": 2}], 12
            )
        finally:
            owner.location = original
    plot = PlotThread.objects.filter(name="The Supply Expedition", creator=owner).first()
    if plot is None:
        plot = PlotThread.create_thread(
            "The Supply Expedition",
            owner,
            description="An approved rare-resource reward illustrates plot payouts.",
        )
        plot.activate()
    if (
        plot.status == "active"
        and not PlotThreadResourcePayout.objects.filter(thread_id=plot.pk).exists()
    ):
        payouts.propose(owner, plot.pk, "rare-crystal", 2)
        payouts.approve(reviewer, plot.pk)
    market.tags.add("system_seller", category="rp_economy")
    return {"shops": 1, "payout_budgets": 1}
