# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional partner seam for approved structured requests.

``request_approved`` sends ``submission`` and ``decision`` inside the review
transaction. Receivers must gate on submission.form_key, make database writes
idempotent using submission.pk, and defer external effects with on_commit().
A receiver failure rolls back the decision and all transactional writes so a
staff member can retry. Jobs itself never creates partner content.
"""

from django.dispatch import Signal

request_approved = Signal()
request_reviewed = Signal()  # submission, decision; all outcomes, inside transaction
request_withdrawn = Signal()  # submission, withdrawal; author action, inside transaction
request_review_context = Signal()  # submission, viewer; staff-only field dictionaries
request_review_form = Signal()  # form, schema, viewer; optional domain-owned fields
