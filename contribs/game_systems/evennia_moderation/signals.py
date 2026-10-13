# SPDX-License-Identifier: BSD-3-Clause
from django.dispatch import Signal

# Inside the approval transaction. Gate by submission.pk, make writes
# idempotent, and defer external effects with transaction.on_commit().
account_admitted = Signal()  # account, submission, referral
