# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Player Pattern proposals through an ordinary Jobs request form."""

from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import override_settings
from evennia.utils.create import create_object

from . import patterns, proposals
from .commands import CmdPattern
from .models import Pattern, PatternKnowledge, PatternStageChange
from .pattern_form import FORM
from .test_patterns import PatternFixture

OTHER = {"label": "Other", "questions": [("name", "Name"), ("niches", "Niches")]}
ANSWERS = {
    "name": "Verse Embroidery",
    "description": "Lines of verse stitched along a hem.",
    "origin": "Market weavers keep it alive.",
    "niches": "Weaver, writing-0, weaving",
    "recognisable": "A border of tiny letters.",
    "combination": "wearable + readable",
    "reuse": True,
}


@skipUnless(apps.is_installed("evennia_jobs"), "Optional Jobs is absent")
@override_settings(JOBS_REQUEST_FORMS={"pattern": FORM, "other": OTHER})
class ProposalTests(PatternFixture):
    def submit(self, author=None, form="pattern", **answers):
        from evennia_jobs.review import submit_request

        values = ANSWERS | answers if form != "other" else {"name": "Verse", "niches": "Weaver"}
        return submit_request(
            author=author or self.char1, form_key=form, title="A Pattern", answers=values
        )

    def review(self, submission, outcome="approved", reviewer=None):
        from evennia_jobs.review import review_request

        return review_request(
            job=submission.job,
            reviewer=reviewer or self.staff,
            outcome=outcome,
            reason="Reviewed.",
            expected_revision=submission.revision,
        )

    def assert_blocked(self, submission, message, reviewer=None):
        from evennia_jobs.models import RequestDecision

        with self.assertRaisesMessage(ValidationError, message):
            self.review(submission, reviewer=reviewer)
        self.assertFalse(RequestDecision.objects.filter(submission=submission).exists())
        self.assertFalse(Pattern.objects.filter(proposal_submission_id=submission.pk).exists())

    def test_the_shipped_form_is_a_valid_jobs_form(self):
        from evennia_jobs.requests import request_forms

        form = request_forms()["pattern"]
        self.assertEqual(form["questions"][-1]["type"], "boolean")
        self.assertLessEqual(
            set(proposals.REQUIRED), {question["key"] for question in form["questions"]}
        )

    def test_approval_creates_a_spreading_pattern_the_proposer_knows(self):
        submission = self.submit()
        with (
            patch.object(type(self.char1), "msg") as told,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.review(submission)
        pattern = Pattern.objects.get(proposal_submission_id=submission.pk)
        self.assertEqual(
            (pattern.key, pattern.name, pattern.stage, pattern.niches, pattern.combinations),
            ("verse-embroidery", "Verse Embroidery", "spreading", ["weaving", "writing-0"], {}),
        )
        self.assertEqual(pattern.created_by_id, self.staff.pk)
        row = PatternKnowledge.objects.get(pattern=pattern)
        self.assertEqual((row.character, row.learned_via), (self.char1, "proposal"))
        self.assertEqual(row.granted_by_id, self.staff.pk)
        change = PatternStageChange.objects.get(pattern=pattern)
        self.assertEqual(
            (change.from_stage, change.to_stage, change.reason),
            ("recovered", "spreading", f"Approved proposal, request #{submission.job.job_number}"),
        )
        told.assert_any_call(
            "Your proposal is approved: you know the Pattern Verse Embroidery. "
            "See +pattern/info verse-embroidery."
        )
        self.assertIn("Your lineage: Char: proposed it.", patterns.info(self.char1, pattern))
        self.assertIn(
            f"Proposed by a player: request #{submission.job.job_number}, revision 1.",
            patterns.roster(self.staff, pattern),
        )
        self.assertEqual(proposals.create_from(submission, self.staff), pattern)
        self.review(submission)
        self.assertEqual(Pattern.objects.filter(name="Verse Embroidery").count(), 1)

    def test_the_proposer_may_teach_and_craft_with_it_at_once(self):
        self.review(self.submit(niches="Scribe 0"))
        pattern = Pattern.objects.get(key="verse-embroidery")
        self.assertIn(patterns.current_stage(pattern), patterns.TEACHABLE)
        self.assertEqual(patterns.for_craft(self.char1, pattern.key, "writing-0"), pattern)

    def test_blocking_problems_roll_back_the_decision(self):
        cases = (
            ({"niches": "Weaver, Gardener"}, "Unknown niches: Gardener."),
            ({"niches": " , "}, "Name at least one niche"),
            ({"name": "Market Lettering"}, "The Pattern key market-lettering is taken"),
            ({"name": "!!!"}, "needs letters or numbers"),
        )
        for answers, message in cases:
            with self.subTest(message=message):
                self.assert_blocked(self.submit(**answers), message)
        patterns.edit(self.staff, self.pattern, name="Verse Embroidery")
        self.assert_blocked(self.submit(), "A Pattern named Verse Embroidery already exists.")

    def test_reviewer_needs_crafting_staff_and_a_playable_proposer(self):
        with override_settings(RP_CRAFTING_STAFF_LOCK="cmd:perm(Admin)"):
            self.assert_blocked(self.submit(), "Only staff may manage Patterns.")
        npc = create_object("evennia.objects.objects.DefaultCharacter", key="Statue")
        self.assert_blocked(self.submit(author=npc), "playable, non-guest")
        with patch("evennia_rp_crafting.proposals.is_guest", return_value=True):
            self.assert_blocked(self.submit(), "playable, non-guest")
        submission = self.submit()
        submission.job.author = None
        submission.job.save(update_fields=["author"])
        self.assert_blocked(submission, "no longer exists")

    def test_other_outcomes_and_forms_create_nothing(self):
        for outcome in ("declined", "changes_requested"):
            self.review(self.submit(), outcome)
        self.review(self.submit(form="other"))
        self.assertEqual(Pattern.objects.count(), 1)

    def test_host_may_rename_the_form_key(self):
        with override_settings(
            JOBS_REQUEST_FORMS={"craft_pattern": FORM}, RP_CRAFTING_PATTERN_FORM="craft_pattern"
        ):
            self.review(self.submit(form="craft_pattern"))
        self.assertTrue(Pattern.objects.filter(key="verse-embroidery").exists())

    def test_staff_review_context_previews_approval(self):
        from evennia_jobs.review import review_fields

        submission = self.submit()
        fields = review_fields(submission, self.staff)
        self.assertEqual(
            fields["Approval creates"], "Verse Embroidery (verse-embroidery), Spreading"
        )
        self.assertEqual(fields["Niches"], "weaving, writing-0")
        self.assertEqual(review_fields(submission, self.char2), {})
        self.assertEqual(
            review_fields(self.submit(niches="Gardener"), self.staff),
            {"Approval": "Blocked: Unknown niches: Gardener."},
        )
        self.review(submission)
        self.assertEqual(
            review_fields(submission, self.staff),
            {"Pattern": "Verse Embroidery (verse-embroidery), created on approval"},
        )

    def test_proposed_patterns_list_like_any_other(self):
        self.review(self.submit())
        self.call(
            CmdPattern(), "", "Verse Embroidery (verse-embroidery) — Spreading", caller=self.char1
        )
        self.call(CmdPattern(), "/info verse-embroidery", "Verse Embroidery", caller=self.char2)
