# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real host settings, rendered routes and seeded request-form integration."""

from importlib import import_module
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import RequestFactory, override_settings
from django.urls import resolve
from evennia.utils.test_resources import EvenniaTest
from evennia_jobs.models import Job
from evennia_jobs.review import submit_request
from evennia_jobs.signals import request_approved

from world.sandbox import content


@override_settings(ROOT_URLCONF="world.sandbox.tests")
class JobsSeams(EvenniaTest):
    """A form registry is useful before any building partner is installed."""

    def test_reseeding_preserves_a_player_request_with_the_demo_title(self):
        player_submission = submit_request(
            author=self.char2,
            form_key="build",
            title=content.REQUEST_DEMO_TITLE,
            answers=content.REQUEST_DEMO_ANSWERS,
        )
        call_command("seed_sandbox", verbosity=0)
        call_command("seed_sandbox", verbosity=0)
        self.assertTrue(Job.objects.filter(pk=player_submission.job_id, author=self.char2).exists())

    def test_seed_proposal_and_form_render_under_real_host_settings(self):
        call_command("seed_sandbox", verbosity=0)
        job = Job.objects.get(title=content.REQUEST_DEMO_TITLE)
        self.assertEqual(job.submissions.get().form_key, "build")
        call_command("seed_sandbox", verbosity=0)
        self.assertEqual(Job.objects.filter(title=content.REQUEST_DEMO_TITLE).count(), 1)
        job = Job.objects.get(title=content.REQUEST_DEMO_TITLE)
        factory = RequestFactory()
        for path in ("/jobs/", "/jobs/forms/build/", f"/jobs/{job.pk}/", f"/jobs/{job.pk}/review/"):
            request = factory.get(path)
            request.user = self.account
            request.session = import_module(settings.SESSION_ENGINE).SessionStore()
            match = resolve(path)
            with patch("evennia_jobs.authoring.require_character", return_value=self.char1.pk):
                response = match.func(request, **match.kwargs)
            response.render()
            self.assertEqual(response.status_code, 200)
            self.assertIn("Propose a build", response.content.decode())

    def test_no_building_or_pattern_partner_is_needed_for_proposals(self):
        submission = submit_request(
            author=self.char2,
            form_key="build",
            title="My reading room",
            answers=content.REQUEST_DEMO_ANSWERS,
        )
        from evennia_jobs.review import review_request

        events = []

        def receiver(sender, **kwargs):
            events.append(kwargs["submission"].pk)

        request_approved.connect(receiver, weak=False)
        try:
            review_request(
                job=submission.job,
                reviewer=self.char1,
                outcome="approved",
                reason="The proposal fits; rooms will be reviewed when construction opens.",
                expected_revision=1,
            )
        finally:
            request_approved.disconnect(receiver)
        self.assertEqual(events, [submission.pk])
