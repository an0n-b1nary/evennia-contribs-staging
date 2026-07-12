"""Sandbox glue — the handful of dotted-path settings hooks that have no
shipped contrib default.

Every other cross-contrib wiring point in this game (XP collectors,
antigaming sweeps, scene display) is a function shipped inside a contrib
itself — see server/conf/settings.py. Only these hooks are game-local
because no contrib ships a working default for them (each is documented as
such in its owning contrib's README/settings-reference table):

- RPTRACKER_FLAG_REVIEW_HOOK — no shipped default
- BOARDS_ANTIGAMING_REPORTER — no shipped default
- LORE_SESSION_CONTEXT_PROVIDER — no shipped default (degrades gracefully
  without one, but this sandbox wires a real one so +lore's passive trickle
  has room/scene signal to work with)

That these three must be hand-written here — instead of shipping as optional
adapters inside evennia_rptracker/evennia_boards/evennia_lore — is itself a
sandboxing finding worth feeding back upstream.
"""


def rptracker_flag_review_hook(title, description):
    """RPTRACKER_FLAG_REVIEW_HOOK: file a staff ticket via evennia_jobs.

    Called by evennia_rptracker.antigaming when a session is auto-flagged
    for pose-spam or manual-end abuse. Signature fixed by the contrib:
    callable(title: str, description: str) -> None.
    """
    from evennia_jobs.models import Job, JobType

    Job.create_job(
        job_type=JobType.DISCUSS,
        author=None,
        title=title,
        description=description,
    )


def boards_antigaming_reporter(title, description):
    """BOARDS_ANTIGAMING_REPORTER: file a staff ticket via evennia_jobs.

    Called by evennia_boards.integrations.xp.sweep_cutscene_spam when an
    author is flagged for posting >=3 IC posts within 24h. Same signature as
    the rptracker hook above.
    """
    from evennia_jobs.models import Job, JobType

    Job.create_job(
        job_type=JobType.DISCUSS,
        author=None,
        title=title,
        description=description,
    )


def lore_session_context_provider(session):
    """LORE_SESSION_CONTEXT_PROVIDER: room/scene context for the passive
    lore trickle, using the rptracker + scenes contribs installed in this
    sandbox. Adapted from the worked example in evennia_lore's README
    (region resolution dropped — no regions contrib exists in this repo
    yet; region_id is always None here).

    Args:
        session: an evennia_rptracker RPSession instance.

    Returns:
        dict: {"room_id": int|None, "region_id": int|None, "thread_ids": set[int]}
    """
    from evennia_plots.models import ScenePlotLink
    from evennia_rptracker.models import RPSessionSceneLink

    room_id = session.room_id
    thread_ids = set()

    scene_ids = set(
        RPSessionSceneLink.objects.filter(session=session).values_list("scene_id", flat=True)
    )
    if scene_ids:
        thread_ids = set(
            ScenePlotLink.objects.filter(scene_id__in=scene_ids).values_list("thread_id", flat=True)
        )

    return {"room_id": room_id, "region_id": None, "thread_ids": thread_ids}
