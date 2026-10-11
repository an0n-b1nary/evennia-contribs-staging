# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Carry staff review over to affirmation.

Entries that staff approved through LORE_REQUIRE_APPROVAL (published, with a
review time) become affirmed as they stand, so reviewed lore keeps its
standing. Everything else keeps affirmation "none". 0003 already gave every
existing row kind "fact" and accuracy "accurate".

The digest is computed here with a frozen copy of
``evennia_lore.layers.digest`` as it was when this migration was written, so
later changes to that function can't change what this migration does.
"""

import hashlib
import json

from django.db import migrations
from django.db.models import Max


def _digest(title, summary, body, kind, accuracy, ooc_notes):
    payload = json.dumps(
        [title or "", summary or "", body or "", kind or "", accuracy or "", ooc_notes or ""],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def affirm_reviewed(apps, schema_editor):
    LoreEntry = apps.get_model("evennia_lore", "LoreEntry")
    LoreVersion = apps.get_model("evennia_lore", "LoreVersion")
    reviewed = LoreEntry.objects.filter(status="published", reviewed_at__isnull=False)
    for entry in reviewed.iterator():
        latest = LoreVersion.objects.filter(parent_id=entry.pk).aggregate(
            max_num=Max("version_number")
        )["max_num"]
        entry.affirmation = "affirmed"
        entry.affirmed_version = latest or 0
        entry.affirmed_digest = _digest(
            entry.title, entry.summary, entry.body, entry.kind, entry.accuracy, entry.ooc_notes
        )
        entry.affirmed_by_name = entry.reviewed_by_name
        entry.affirmed_at = entry.reviewed_at
        entry.save(
            update_fields=[
                "affirmation",
                "affirmed_version",
                "affirmed_digest",
                "affirmed_by_name",
                "affirmed_at",
            ]
        )


class Migration(migrations.Migration):
    dependencies = [
        ("evennia_lore", "0003_loreentry_layers_and_lorenotice"),
    ]

    operations = [
        migrations.RunPython(affirm_reviewed, migrations.RunPython.noop),
    ]
