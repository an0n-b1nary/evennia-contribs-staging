# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Scene ids, public SYSTEM entries, scene closure and soft-ref detachment."""

from importlib import import_module

from django.apps import apps
from django.db.models.signals import post_delete

from evennia_rp_contest import conf, narration
from evennia_rp_contest.expiry import close_for_scene
from evennia_rp_contest.models import Challenge, CheckRecord
from evennia_rp_contest.signals import check_recorded, check_voided


def scene_model():
    return apps.get_model(conf.get("RP_CONTEST_SCENES_APP_LABEL"), "Scene")


def scene_id_for(caller):
    room = caller.location
    scene_id = getattr(room, "active_scene_id", None) if room else None
    if (
        scene_id
        and scene_model().objects.filter(pk=scene_id, status__in=("open", "active")).exists()
    ):
        return scene_id
    return None


def on_recorded(sender, record, **kwargs):
    if record.scene_id is None:
        return
    scene = scene_model().objects.filter(pk=record.scene_id, status__in=("open", "active")).first()
    if scene is not None:
        log = apps.get_model(conf.get("RP_CONTEST_SCENES_APP_LABEL"), "LogEntry")
        log.create_entry(scene, record.character, narration.public_text(record), log_type="system")


def on_voided(sender, record, actor=None, **kwargs):
    if record.scene_id is None:
        return
    scene = scene_model().objects.filter(pk=record.scene_id).first()
    if scene is not None:
        log = apps.get_model(conf.get("RP_CONTEST_SCENES_APP_LABEL"), "LogEntry")
        log.create_entry(
            scene, actor, f"Attempt {record.pk} voided: {record.void_reason}", log_type="system"
        )


def on_scene_closed(sender, scene=None, **kwargs):
    if scene is not None:
        close_for_scene(scene.pk)


def on_scene_deleted(sender, instance, **kwargs):
    close_for_scene(instance.pk)
    # links.connect_soft_ref_cleanup cascades bridge rows. These are audit
    # records, so detach the soft reference instead of deleting the history.
    Challenge.all_objects.filter(scene_id=instance.pk).update(scene_id=None)
    CheckRecord.objects.filter(scene_id=instance.pk).update(scene_id=None)


def connect(app_config):
    signals = import_module(f"{app_config.name}.signals")
    signals.scene_closed.connect(on_scene_closed, dispatch_uid="rp_contest.scene_closed")
    check_recorded.connect(on_recorded, dispatch_uid="rp_contest.scene_log")
    check_voided.connect(on_voided, dispatch_uid="rp_contest.scene_void_log")
    post_delete.connect(
        on_scene_deleted, sender=scene_model(), dispatch_uid="rp_contest.scene_deleted"
    )
