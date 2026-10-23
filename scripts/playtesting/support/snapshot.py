"""Fixed projections of fixture state; no query or mutation interface."""

from django.conf import settings
from evennia.accounts.models import AccountDB
from evennia_building.models import BuildProject, BuildSubmission, Property
from evennia_calendar.models import RSVP, CalendarEvent, ClusterRSVP, PriorityToken
from evennia_economy.models import (
    LedgerEntry,
    Listing,
    Offer,
    Purse,
    ReviewFlag,
    Storefront,
    UBIPayment,
)
from evennia_npcs.models import NPCBlueprint, NPCSpawnRecord
from evennia_plots.models import PlotThread
from evennia_rp_chargen.locks import _load
from evennia_rp_chargen.models import AbilityTransaction, CharacterAbility, CharacterBuild
from evennia_rp_chargen.stats import StatHandler
from evennia_rp_contest.models import Challenge, CheckRecord
from evennia_rp_crafting.models import (
    ActivationUse,
    CraftRecord,
    EventUse,
    FixtureInstallation,
    NicheUnlock,
    RoomLayer,
    Workshop,
)
from evennia_rp_resources.models import PlotPayoutRun, ResourceGrant, ResourceHolding
from evennia_rptracker.models import RPSession
from evennia_scenes.models import LogEntry, Scene
from evennia_xp.models import CharacterXP, XPLog, XPSpend


def rows(query, *fields):
    return list(query.order_by("pk").values(*fields))


def snapshot():
    actors = {}
    ids = []
    room_ids = set()
    for account in AccountDB.objects.all():
        if not account.tags.has(settings.PLAYTEST_RUN_ID, category="playtest"):
            continue
        character = account.characters.all()[0]
        ids.append(character.pk)
        room_ids.add(character.location.pk if character.location else None)
        build = CharacterBuild.objects.filter(character=character).first()
        actors[account.db.playtest_role] = {
            "id": character.pk,
            "room": character.location.pk if character.location else None,
            "status": build.status if build else None,
            "allowance": str(build.allowance_left) if build else None,
            "stats": {
                key: rating.display() if rating else None
                for key, rating in StatHandler(character).ratings().items()
            }
            if build
            else {},
            "locked": _load(character).locked,
            "abilities": rows(
                CharacterAbility.objects.filter(character=character),
                "ability__key",
                "tag__key",
                "level",
                "equipped",
            ),
        }
    return {
        "calendar_events": rows(
            CalendarEvent.objects.filter(creator_id__in=ids),
            "id",
            "title",
            "cluster_id",
            "is_cancelled",
            "is_staff_event",
        ),
        "calendar_rsvps": rows(
            RSVP.objects.filter(character_id__in=ids),
            "id",
            "character_id",
            "event_id",
            "status",
            "waitlist_position",
        ),
        "calendar_applications": rows(
            ClusterRSVP.objects.filter(character_id__in=ids),
            "id",
            "character_id",
            "cluster_id",
            "status",
        ),
        "calendar_tokens": rows(
            PriorityToken.objects.filter(character_id__in=ids),
            "id",
            "character_id",
            "redeemed_event_id",
            "redeemed_at",
        ),
        "plots": rows(
            PlotThread.objects.filter(creator_id__in=ids), "id", "plot_number", "name", "status"
        ),
        "plot_awards": rows(
            PlotPayoutRun.objects.all(), "id", "thread_id", "amounts", "recipients"
        ),
        "building_projects": rows(
            BuildProject.objects.filter(owner_id__in=ids), "id", "name", "version", "state"
        ),
        "building_submissions": rows(
            BuildSubmission.objects.filter(project__owner_id__in=ids),
            "id",
            "project_id",
            "revision",
        ),
        "building_properties": rows(
            Property.objects.filter(owner_id__in=ids), "id", "name", "owner_id"
        ),
        "build_acknowledgement": getattr(
            settings,
            "BUILDING_REUSE_ACKNOWLEDGEMENT",
            "I acknowledge that this submitted content may be reused by this game.",
        ),
        "npc_blueprints": rows(
            NPCBlueprint.objects.filter(creator_id__in=ids), "id", "name", "kind", "archived"
        ),
        "npc_spawns": rows(
            NPCSpawnRecord.objects.filter(blueprint__creator_id__in=ids),
            "id",
            "blueprint_id",
            "spawned_object_id",
            "controller_id",
            "despawned_at",
        ),
        "actors": actors,
        "economy_purses": rows(
            Purse.objects.filter(character_id__in=ids), "character_id", "balance"
        ),
        "economy_stalls": rows(
            Storefront.objects.filter(owner_id__in=ids),
            "id",
            "owner_id",
            "room_id",
            "kind",
            "property_id",
            "status",
            "last_active",
        ),
        "economy_listings": rows(
            Listing.objects.filter(storefront__owner_id__in=ids),
            "id",
            "storefront_id",
            "assets",
            "price",
            "status",
            "buyer_id",
        ),
        "economy_flags": rows(ReviewFlag.objects.all(), "id", "kind", "reviewed"),
        "crafting_workshops": rows(
            Workshop.objects.filter(character_id__in=ids),
            "id",
            "character_id",
            "invested_money",
            "last_craft",
        ),
        "crafting_niches": rows(
            NicheUnlock.objects.filter(workshop__character_id__in=ids),
            "id",
            "workshop__character_id",
            "niche__key",
            "position",
            "abandoned_at",
        ),
        "crafts": rows(
            CraftRecord.objects.filter(crafter_id__in=ids),
            "id",
            "crafter_id",
            "niche__key",
            "behaviour",
            "item_id",
            "resources_spent",
            "money_spent",
            "hallmark",
            "prose",
            "furnishing_weeks",
        ),
        "fixture_installations": rows(
            FixtureInstallation.objects.filter(craft__crafter_id__in=ids),
            "id",
            "craft_id",
            "room_id",
            "active",
        ),
        "temporary_layers": rows(
            RoomLayer.objects.filter(actor_id__in=ids),
            "id",
            "room_id",
            "craft_id",
            "cleared_at",
            "expires_at",
        ),
        "activation_uses": rows(
            ActivationUse.objects.filter(actor_id__in=ids), "id", "craft_id", "mode", "message"
        ),
        "economy_offers": rows(
            Offer.objects.filter(giver_id__in=ids),
            "id",
            "giver_id",
            "recipient_id",
            "status",
            "give",
            "want",
        ),
        "economy_ledger": rows(
            LedgerEntry.objects.filter(from_id__in=ids) | LedgerEntry.objects.filter(to_id__in=ids),
            "id",
            "kind",
            "from_id",
            "to_id",
            "amount",
            "fee",
            "assets",
            "exchange_id",
        ),
        "economy_ubi": rows(
            UBIPayment.objects.filter(character_id__in=ids), "character_id", "week", "amount"
        ),
        "resource_holdings": rows(
            ResourceHolding.objects.filter(character_id__in=ids),
            "character_id",
            "resource__key",
            "quantity",
        ),
        "resource_grants": rows(
            ResourceGrant.objects.filter(character_id__in=ids),
            "character_id",
            "resource__key",
            "quantity",
            "source",
            "week",
            "by_id",
        ),
        "transactions": rows(
            AbilityTransaction.objects.filter(character_id__in=ids),
            "id",
            "character_id",
            "kind",
            "ability_name",
            "level_from",
            "level_to",
            "allowance_amount",
            "xp_amount",
            "ledger_ref",
        ),
        "xp": rows(
            CharacterXP.objects.filter(character_id__in=ids),
            "character_id",
            "current_balance",
            "total_earned",
        ),
        "spends": rows(
            XPSpend.objects.filter(character_id__in=ids),
            "id",
            "character_id",
            "amount",
            "refunded_at",
        ),
        "event_uses": rows(
            EventUse.objects.filter(actor_id__in=ids),
            "id",
            "craft_id",
            "actor_id",
            "room_id",
            "destinations",
        ),
        "earn_count": XPLog.objects.filter(character_id__in=ids).count(),
        "challenges": rows(
            Challenge.objects.filter(room_id__in=room_ids),
            "id",
            "number",
            "set_by_id",
            "status",
            "closed_reason",
            "difficulty",
            "once",
        ),
        "checks": rows(
            CheckRecord.objects.filter(character_id__in=ids),
            "id",
            "character_id",
            "challenge_id",
            "scene_id",
            "stat",
            "tag",
            "rating_display",
            "difficulty",
            "outcome_key",
            "alternative",
            "attempt_no",
            "voided_at",
            "detail",
            "comment",
        ),
        "scenes": rows(Scene.objects.filter(room_id__in=room_ids), "id", "status"),
        "logs": rows(
            LogEntry.objects.filter(scene__room_id__in=room_ids),
            "id",
            "scene_id",
            "log_type",
            "content",
        ),
        "sessions": rows(
            RPSession.objects.filter(character_id__in=ids),
            "id",
            "character_id",
            "status",
            "pose_count",
        ),
    }
