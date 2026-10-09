"""Fixed projections of fixture state; no query or mutation interface."""

from django.conf import settings
from evennia.accounts.models import AccountDB
from evennia_rp_chargen.locks import _load
from evennia_rp_chargen.models import AbilityTransaction, CharacterAbility, CharacterBuild
from evennia_rp_chargen.stats import StatHandler
from evennia_rp_contest.models import Challenge, CheckRecord
from evennia_rp_resources.models import ResourceGrant, ResourceHolding
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
        "actors": actors,
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
