# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Gated scene capture and owned soft-reference cleanup."""

from importlib import import_module

from django.db.models.signals import post_delete
from django.utils import timezone

from . import services
from .models import NPCSceneAppearance, NPCSpawnRecord, PlotNPCLink
from .signals import npc_pose_recorded


def object_deleting(sender, instance, **kwargs):
    from evennia.objects.models import ObjectDB

    if not isinstance(instance, ObjectDB):
        return
    NPCSpawnRecord.objects.filter(spawned_object_id=instance.pk, despawned_at=None).update(
        despawned_at=timezone.now(), unique_blueprint=None, controller=None, controller_name=""
    )


def connect_scenes(cfg):
    signals = import_module(f"{cfg.name}.signals")
    signals.log_entry_created.connect(scene_entry, dispatch_uid="npcs.scene_entry")
    post_delete.connect(
        scene_deleted, sender=cfg.get_model("Scene"), dispatch_uid="npcs.scene_deleted"
    )
    npc_pose_recorded.connect(capture_pose, dispatch_uid="npcs.capture_pose")


def capture_pose(sender, npc, text, pose_type, **kwargs):
    model = services.partner_model("NPCS_SCENES_APP_LABEL", "Scene")
    if model is not None:
        module = model._meta.app_config.name
        import_module(f"{module}.capture").capture_to_scene(npc, text, log_type=pose_type)


def scene_entry(sender, entry, scene, **kwargs):
    if entry.author_id:
        record = NPCSpawnRecord.objects.filter(
            spawned_object_id=entry.author_id, despawned_at=None
        ).first()
        if record:
            NPCSceneAppearance.objects.get_or_create(spawn=record, scene_id=scene.pk)


def scene_deleted(sender, instance, **kwargs):
    NPCSceneAppearance.objects.filter(scene_id=instance.pk).delete()


def visible_scene(actor, ref):
    model = services.partner_model("NPCS_SCENES_APP_LABEL", "Scene")
    if model is None:
        return None
    scene = model.objects.filter(pk=ref).first()
    if scene is None:
        return None
    if (
        scene.is_web_readable(scene.privacy)
        or services.is_staff(actor)
        or scene.creator_id == actor.pk
        or scene.participants.filter(character=actor, is_invited=True).exists()
    ):
        return scene
    return None


def require_scene_access(npc, actor):
    model = services.partner_model("NPCS_SCENES_APP_LABEL", "Scene")
    ref = getattr(npc.location, "active_scene_id", None) if npc.location else None
    if model is None or not ref:
        return
    scene = model.objects.filter(pk=ref, status__in=("open", "active")).first()
    if (
        scene
        and scene.privacy != "public"
        and not services.is_staff(actor)
        and scene.creator_id != actor.pk
        and not scene.participants.filter(character=actor, is_invited=True).exists()
    ):
        raise services.NPCError(
            "Ask the scene creator to invite your character before portraying an NPC here."
        )


def connect_plots(cfg):
    signals = import_module(f"{cfg.name}.signals")
    collector = getattr(signals, "collect_thread_content", None)
    if collector is not None:
        collector.connect(plot_content, dispatch_uid="npcs.plot_content")
    post_delete.connect(
        plot_deleted, sender=cfg.get_model("PlotThread"), dispatch_uid="npcs.plot_deleted"
    )


def plot_deleted(sender, instance, **kwargs):
    PlotNPCLink.objects.filter(thread_id=instance.pk).delete()


def plot_content(sender, thread, **kwargs):
    return {"npcs": PlotNPCLink.objects.filter(thread_id=thread.pk).exists()}
