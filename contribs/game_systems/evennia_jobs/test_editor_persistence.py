# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real editor restoration with nonpersistent state discarded."""

from unittest.mock import patch

from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_jobs.commands import CmdRequest, _open_editor
from evennia_jobs.models import Job, JobComment, JobType
from evennia_links.testing import EditorPersistenceMixin


class JobsEditorPersistence(EditorPersistenceMixin, EvenniaCommandTest):
    def test_new_ticket_survives_reload(self):
        self.call(CmdRequest(), "A proposal")
        editor = self.reload_editor(self.char1)
        self.save_and_quit_editor(self.char1, editor, "jobs_editor_context")
        job = Job.objects.get(title="A proposal")
        self.assertEqual(job.description, editor._buffer)
        self.assertEqual(job.author_id, self.char1.pk)

    def test_comment_survives_reload(self):
        job = Job.create_job(
            job_type=JobType.REQUEST, author=self.char1, title="Original", description="Old"
        )
        _open_editor(
            self.char1, JobType.REQUEST, "", mode="comment", job_pk=job.pk, staff_only=True
        )
        editor = self.reload_editor(self.char1)
        self.save_and_quit_editor(self.char1, editor, "jobs_editor_context")
        comment = JobComment.objects.get(job=job)
        self.assertEqual(comment.content, editor._buffer)
        self.assertTrue(comment.is_staff_only)

    def test_deleted_ticket_refuses_comment(self):
        job = Job.create_job(
            job_type=JobType.REQUEST, author=self.char1, title="Original", description="Old"
        )
        _open_editor(self.char1, JobType.REQUEST, "", mode="comment", job_pk=job.pk)
        editor = self.reload_editor(self.char1)
        job.delete()
        with patch.object(self.char1, "msg") as msg:
            self.assertFalse(editor._savefunc(self.char1, editor._buffer))
        self.assertIn("no longer exists", msg.call_args[0][0])
        editor.quit()

    @override_settings(
        JOBS_REQUEST_FORMS={
            "editor_probe": {
                "label": "Proposal",
                "questions": [{"key": "body", "label": "Description"}],
            }
        }
    )
    def test_request_questionnaire_editor_survives_reload(self):
        self.call(CmdRequest(), "/form editor_probe=My proposal")
        self.call(CmdRequest(), "/edit body")
        editor = self.reload_editor(self.char1)
        self.save_and_quit_editor(self.char1, editor, "jobs_request_editor")
        self.assertEqual(self.char1.db.jobs_request_draft["answers"]["body"], editor._buffer)
