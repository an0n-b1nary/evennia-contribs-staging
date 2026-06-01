# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Staff ticket system commands.

Player commands for submitting and viewing tickets (+request, +bug, +issue).
Staff commands for ticket management (+discuss, +jobs).

Add all five commands to your CharacterCmdSet::

    from evennia_jobs.commands import CmdBug, CmdDiscuss, CmdIssue, CmdJobs, CmdRequest
    self.add(CmdRequest)
    self.add(CmdBug)
    self.add(CmdIssue)
    self.add(CmdDiscuss)
    self.add(CmdJobs)

Settings:
  JOBS_STAFF_LOCK — lock string for +discuss and +jobs (default "cmd:perm(Builder)").
"""

from django.conf import settings
from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.eveditor import EvEditor

from evennia_jobs.models import JobPriority, JobStatus, JobType

try:
    from evennia_accessibility import uses_screenreader
except ImportError:

    def uses_screenreader(_):
        """Fallback when evennia-accessibility is not installed."""
        return False


def _is_staff(character):
    """Return True if *character* has the staff permission level.

    Uses the lock string from JOBS_STAFF_LOCK (default ``cmd:perm(Builder)``)
    with the ``cmd:`` prefix stripped so it works as a lock expression.
    """
    lock_expr = getattr(settings, "JOBS_STAFF_LOCK", "cmd:perm(Builder)")
    # Strip leading "cmd:" if present to get a bare perm expression.
    expr = lock_expr[4:] if lock_expr.startswith("cmd:") else lock_expr
    try:
        return bool(character.locks.check_lockstring(character, expr))
    except Exception:
        return False


# Human-readable priority sort order (lower index = higher urgency).
_PRIORITY_ORDER = {
    JobPriority.URGENT: 0,
    JobPriority.HIGH: 1,
    JobPriority.NORMAL: 2,
}

# Colour codes for priority labels.
_PRIORITY_COLOR = {
    JobPriority.URGENT: "|r",
    JobPriority.HIGH: "|y",
    JobPriority.NORMAL: "|w",
}

# Colour codes for status labels.
_STATUS_COLOR = {
    JobStatus.OPEN: "|g",
    JobStatus.IN_REVIEW: "|c",
    JobStatus.ANSWERED: "|y",
    JobStatus.CLOSED: "|x",
}

# Valid values for +jobs/status and +jobs/priority switches.
_VALID_STATUSES = {s.value for s in JobStatus}
_VALID_PRIORITIES = {p.value for p in JobPriority}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lookup_job(arg):
    """Resolve a job by its job_number.

    Returns:
        (Job, None) on success.
        (None, error_str) on failure.
    """
    from evennia_jobs.models import Job

    arg = arg.strip()
    if not arg.isdigit():
        return None, "Ticket ID must be a number (e.g. |w+jobs 12|n)."
    try:
        return Job.objects.get(job_number=int(arg)), None
    except Job.DoesNotExist:
        return None, f"No ticket #{arg} found."


def _priority_label(job):
    color = _PRIORITY_COLOR.get(job.priority, "|w")
    return f"{color}{job.get_priority_display()}|n"


def _status_label(job):
    color = _STATUS_COLOR.get(job.status, "|w")
    return f"{color}{job.get_status_display()}|n"


def _type_label(job):
    return f"|w{job.get_job_type_display()}|n"


def _format_job_row(job, viewer_is_staff):
    """Single-line summary row for list views."""
    assignee = job.assignee_name if job.assignee_name else "|x(unassigned)|n"
    prio_col = _PRIORITY_COLOR.get(job.priority, "|w")
    status_col = _STATUS_COLOR.get(job.status, "|w")
    type_label = job.get_job_type_display().upper()[:4]
    return (
        f" |w#{job.job_number:<4}|n {prio_col}{job.get_priority_display():<6}|n "
        f"{status_col}{job.get_status_display():<9}|n |c{type_label:<4}|n "
        f"{job.title[:40]:<40} — {assignee}"
    )


def _format_job_detail(job, viewer_is_staff, sr_mode=False):
    """Full job detail view including visible comments."""

    if job.job_type == JobType.ISSUE and not viewer_is_staff:
        reporter = "[Reporter hidden]"
    else:
        reporter = job.author_name or "(unknown)"

    comments = job.comments.all()
    if not viewer_is_staff:
        comments = comments.filter(is_staff_only=False)

    if sr_mode:
        assignee = job.assignee_name or "unassigned"
        lines = [
            f"Ticket #{job.job_number}: {job.title}",
            f"  Type: {job.get_job_type_display()}"
            f" | Status: {job.get_status_display()}"
            f" | Priority: {job.get_priority_display()}",
            f"  Submitted: {job.created_at.strftime('%Y-%m-%d %H:%M')} UTC by {reporter}",
        ]
        if viewer_is_staff:
            lines.append(f"  Assigned: {assignee}")
        lines.append(f"  Updated: {job.updated_at.strftime('%Y-%m-%d %H:%M')} UTC")
        if job.closed_at:
            lines.append(f"  Closed: {job.closed_at.strftime('%Y-%m-%d %H:%M')} UTC")
        lines.append(f"Description: {job.description}")
        if comments.exists():
            lines.append("Comments:")
            for c in comments:
                staff_tag = " [staff-only]" if c.is_staff_only else ""
                ts = c.created_at.strftime("%Y-%m-%d %H:%M")
                lines.append(f"  {c.author_name} ({ts}){staff_tag}: {c.content}")
        else:
            lines.append("  (No comments.)")
        return "\n".join(lines)

    lines = []
    sep = "|b" + "=" * 70 + "|n"
    lines.append(sep)
    lines.append(
        f" Ticket |w#{job.job_number}|n — {_type_label(job)}  "
        f"{_status_label(job)}  {_priority_label(job)}"
    )
    lines.append(sep)
    reporter_display = (
        "|x[Reporter hidden]|n"
        if job.job_type == JobType.ISSUE and not viewer_is_staff
        else f"{job.author_name or '|x(unknown)|n'}"
    )
    lines.append(f" Title    : {job.title}")
    lines.append(
        f" Submitted: {job.created_at.strftime('%Y-%m-%d %H:%M')} UTC  by {reporter_display}"
    )
    if viewer_is_staff and job.assignee_name:
        lines.append(f" Assigned : {job.assignee_name}")
    lines.append(f" Updated  : {job.updated_at.strftime('%Y-%m-%d %H:%M')} UTC")
    if job.closed_at:
        lines.append(f" Closed   : {job.closed_at.strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append("|b" + "-" * 70 + "|n")
    lines.append(job.description)
    lines.append("|b" + "-" * 70 + "|n")

    if comments.exists():
        lines.append(" Comments:")
        for c in comments:
            tag = " |r[staff-only]|n" if c.is_staff_only else ""
            ts = c.created_at.strftime("%Y-%m-%d %H:%M")
            lines.append(f"  |w{c.author_name}|n ({ts}){tag}:")
            lines.append(f"    {c.content}")
    else:
        lines.append(" |x(No comments.)|n")

    lines.append(sep)
    return "\n".join(lines)


def _sorted_jobs(queryset):
    """Sort a Job queryset by priority (urgent→high→normal) then age."""
    from evennia_jobs.models import Job

    pks = queryset.values_list("pk", flat=True)
    return list(Job.objects.by_priority().filter(pk__in=pks))


# ---------------------------------------------------------------------------
# EvEditor callbacks
# ---------------------------------------------------------------------------


def _jobs_load(caller):
    """Always start with an empty editor buffer (new content only)."""
    return ""


def _jobs_save(caller, buffer):
    """Create a job or comment from the editor buffer."""
    from evennia_jobs.models import Job, JobComment

    ctx = getattr(caller.ndb, "_jobs_context", None)
    if not ctx:
        caller.msg("|rError: no ticket editor context found.|n")
        return False

    content = buffer.strip()
    if not content:
        caller.msg("Nothing to save — buffer is empty.")
        return False

    mode = ctx.get("mode")

    if mode == "create":
        job = Job.create_job(
            job_type=ctx["job_type"],
            author=caller,
            title=ctx["title"],
            description=content,
        )
        type_label = job.get_job_type_display()
        caller.msg(f"|gTicket #{job.job_number} ({type_label}) submitted.|n")
        if ctx["job_type"] == JobType.ISSUE:
            caller.msg("|xYour identity is only visible to staff.|n")
        return True

    if mode == "comment":
        try:
            job = Job.objects.get(pk=ctx["job_pk"])
        except Job.DoesNotExist:
            caller.msg("|rError: the ticket no longer exists.|n")
            return False
        JobComment.create_comment(
            job=job,
            author=caller,
            content=content,
            is_staff_only=ctx.get("is_staff_only", False),
        )
        tag = " (staff-only)" if ctx.get("is_staff_only") else ""
        caller.msg(f"|gComment added to ticket #{job.job_number}{tag}.|n")
        return True

    caller.msg("|rError: unknown editor mode.|n")
    return False


def _jobs_quit(caller):
    """Clean up the ticket editor context."""
    caller.ndb._jobs_context = None
    caller.msg("Ticket editor closed.")


def _open_editor(caller, job_type, title, mode="create", job_pk=None, staff_only=False):
    """Stash context and open EvEditor for job creation or commenting."""
    caller.ndb._jobs_context = {
        "mode": mode,
        "job_type": job_type,
        "title": title,
        "job_pk": job_pk,
        "is_staff_only": staff_only,
    }
    EvEditor(caller, loadfunc=_jobs_load, savefunc=_jobs_save, quitfunc=_jobs_quit)


# ---------------------------------------------------------------------------
# +request
# ---------------------------------------------------------------------------


class CmdRequest(MuxCommand):
    """
    Submit a proposal or suggestion to staff.

    Usage:
        +request                        - List your open/answered tickets
        +request <id>                   - View a ticket you submitted
        +request <title>                - Submit a new request (opens editor)
        +request <title>=<description>  - Submit a new request (inline)
        +request/comment <id>           - Add a comment (opens editor)
        +request/comment <id>=<text>    - Add a comment (inline)

    Creates a ticket of type 'request' for staff review. Use this for
    proposals, suggestions, questions, or anything that needs staff input.
    """

    key = "+request"
    aliases = []  # noqa: RUF012
    help_category = "Requests"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        switches = [s.lower() for s in self.switches]

        if "comment" in switches:
            self._add_comment()
            return

        if not self.args:
            self._list_own()
            return

        if self.rhs is None and self.lhs.strip().isdigit():
            self._view(self.lhs.strip())
            return

        if self.rhs is not None:
            title = self.lhs.strip()
            desc = self.rhs.strip()
            if not title:
                caller.msg("Usage: |w+request <title>=<description>|n")
                return
            if not desc:
                caller.msg("Description cannot be empty.")
                return
            self._create_inline(title, desc)
            return

        title = self.args.strip()
        if not title:
            caller.msg("Usage: |w+request <title>|n")
            return
        _open_editor(caller, JobType.REQUEST, title)

    def _create_inline(self, title, desc):
        from evennia_jobs.models import Job

        job = Job.create_job(
            job_type=JobType.REQUEST, author=self.caller, title=title, description=desc
        )
        self.caller.msg(f"|gTicket #{job.job_number} (Request) submitted.|n")

    def _list_own(self):
        from evennia_jobs.models import Job

        caller = self.caller
        jobs = list(
            Job.objects.filter(author=caller)
            .exclude(status=JobStatus.CLOSED)
            .exclude(job_type=JobType.DISCUSS)
        )
        if not jobs:
            caller.msg("You have no open tickets. Use |w+request <title>|n to submit one.")
            return
        sorted_jobs = sorted(jobs, key=lambda j: j.created_at)
        if uses_screenreader(caller):
            count = len(sorted_jobs)
            lines = [f"Your Open Tickets: {count} ticket{'s' if count != 1 else ''}"]
            for j in sorted_jobs:
                assignee = j.assignee_name or "unassigned"
                lines.append(
                    f"  #{j.job_number} ({j.get_priority_display()},"
                    f" {j.get_status_display()},"
                    f" {j.get_job_type_display()}): {j.title} — {assignee}"
                )
            caller.msg("\n".join(lines))
            return
        lines = ["|w Your Open Tickets |n"]
        lines.append("|b" + "=" * 70 + "|n")
        for j in sorted_jobs:
            lines.append(_format_job_row(j, False))
        caller.msg("\n".join(lines))

    def _view(self, id_str):
        caller = self.caller
        job, err = _lookup_job(id_str)
        if err:
            caller.msg(err)
            return
        if job.job_type == JobType.DISCUSS:
            caller.msg("That ticket is staff-only.")
            return
        if not _is_staff(caller) and job.author_id != caller.id:
            caller.msg("You can only view your own tickets.")
            return
        caller.msg(_format_job_detail(job, _is_staff(caller), sr_mode=uses_screenreader(caller)))

    def _add_comment(self):
        from evennia_jobs.models import JobComment

        caller = self.caller
        id_str = self.lhs.strip() if self.lhs else ""
        if not id_str:
            caller.msg("Usage: |w+request/comment <id>[=<text>]|n")
            return
        job, err = _lookup_job(id_str)
        if err:
            caller.msg(err)
            return
        if job.job_type == JobType.DISCUSS:
            caller.msg("That ticket is staff-only.")
            return
        if not _is_staff(caller) and job.author_id != caller.id:
            caller.msg("You can only comment on your own tickets.")
            return
        if job.status == JobStatus.CLOSED:
            caller.msg("That ticket is closed. Contact staff if you need it reopened.")
            return

        if self.rhs is not None:
            text = self.rhs.strip()
            if not text:
                caller.msg("Comment text cannot be empty.")
                return
            JobComment.create_comment(job=job, author=caller, content=text)
            caller.msg(f"|gComment added to ticket #{job.job_number}.|n")
        else:
            _open_editor(caller, job.job_type, "", mode="comment", job_pk=job.pk)


# ---------------------------------------------------------------------------
# +bug
# ---------------------------------------------------------------------------


class CmdBug(MuxCommand):
    """
    Report a bug or technical problem.

    Usage:
        +bug <title>                - Report a bug (opens editor for details)
        +bug <title>=<description>  - Report a bug (inline)

    Creates a ticket of type 'bug' for staff review. Include steps to
    reproduce, what you expected, and what actually happened.
    """

    key = "+bug"
    aliases = []  # noqa: RUF012
    help_category = "Requests"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        if not self.args:
            caller.msg("Usage: |w+bug <title>[=<description>]|n")
            return

        if self.rhs is not None:
            title = self.lhs.strip()
            desc = self.rhs.strip()
            if not title:
                caller.msg("Usage: |w+bug <title>=<description>|n")
                return
            if not desc:
                caller.msg("Description cannot be empty.")
                return
            from evennia_jobs.models import Job

            job = Job.create_job(job_type=JobType.BUG, author=caller, title=title, description=desc)
            caller.msg(f"|gBug report #{job.job_number} submitted. Thank you!|n")
        else:
            title = self.args.strip()
            _open_editor(caller, JobType.BUG, title)


# ---------------------------------------------------------------------------
# +issue
# ---------------------------------------------------------------------------


class CmdIssue(MuxCommand):
    """
    Report an interpersonal complaint or moderation request.

    Usage:
        +issue <title>                - Report an issue (opens editor for details)
        +issue <title>=<description>  - Report an issue (inline)

    Creates a ticket of type 'issue' for staff review. Use this for
    interpersonal complaints, harassment reports, or moderation requests.

    Your identity is only visible to staff — other players cannot see who
    submitted the report.
    """

    key = "+issue"
    aliases = []  # noqa: RUF012
    help_category = "Requests"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        if not self.args:
            caller.msg("Usage: |w+issue <title>[=<description>]|n")
            return

        if self.rhs is not None:
            title = self.lhs.strip()
            desc = self.rhs.strip()
            if not title:
                caller.msg("Usage: |w+issue <title>=<description>|n")
                return
            if not desc:
                caller.msg("Description cannot be empty.")
                return
            from evennia_jobs.models import Job

            job = Job.create_job(
                job_type=JobType.ISSUE, author=caller, title=title, description=desc
            )
            caller.msg(
                f"|gIssue report #{job.job_number} submitted.|n\n"
                "|xYour identity is only visible to staff.|n"
            )
        else:
            title = self.args.strip()
            _open_editor(caller, JobType.ISSUE, title)


# ---------------------------------------------------------------------------
# +discuss
# ---------------------------------------------------------------------------


class CmdDiscuss(MuxCommand):
    """
    Create and manage staff-to-staff discussion tickets.

    Usage:
        +discuss                        - List open staff discussions
        +discuss <id>                   - View a discussion
        +discuss <title>                - Create a new discussion (opens editor)
        +discuss <title>=<description>  - Create a new discussion (inline)
        +discuss/comment <id>           - Add a comment (opens editor)
        +discuss/comment <id>=<text>    - Add a comment (inline)

    Staff-only ticket type for internal discussion topics.
    """

    key = "+discuss"
    aliases = []  # noqa: RUF012
    help_category = "Requests"
    locks = getattr(settings, "JOBS_STAFF_LOCK", "cmd:perm(Builder)")

    def func(self):
        caller = self.caller
        switches = [s.lower() for s in self.switches]

        if "comment" in switches:
            self._add_comment()
            return

        if not self.args:
            self._list_all()
            return

        if self.rhs is None and self.lhs.strip().isdigit():
            self._view(self.lhs.strip())
            return

        if self.rhs is not None:
            title = self.lhs.strip()
            desc = self.rhs.strip()
            if not title:
                caller.msg("Usage: |w+discuss <title>=<description>|n")
                return
            if not desc:
                caller.msg("Description cannot be empty.")
                return
            self._create_inline(title, desc)
            return

        title = self.args.strip()
        _open_editor(caller, JobType.DISCUSS, title)

    def _create_inline(self, title, desc):
        from evennia_jobs.models import Job

        job = Job.create_job(
            job_type=JobType.DISCUSS, author=self.caller, title=title, description=desc
        )
        self.caller.msg(f"|gDiscussion ticket #{job.job_number} created.|n")

    def _list_all(self):
        from evennia_jobs.models import Job

        jobs = _sorted_jobs(
            Job.objects.filter(job_type=JobType.DISCUSS).exclude(status=JobStatus.CLOSED)
        )
        if not jobs:
            self.caller.msg("No open staff discussions.")
            return
        lines = ["|w Staff Discussions |n"]
        lines.append("|b" + "=" * 70 + "|n")
        for j in jobs:
            lines.append(_format_job_row(j, True))
        self.caller.msg("\n".join(lines))

    def _view(self, id_str):
        job, err = _lookup_job(id_str)
        if err:
            self.caller.msg(err)
            return
        if job.job_type != JobType.DISCUSS:
            self.caller.msg("Use |w+request <id>|n to view player tickets.")
            return
        self.caller.msg(_format_job_detail(job, True))

    def _add_comment(self):
        from evennia_jobs.models import JobComment

        caller = self.caller
        id_str = self.lhs.strip() if self.lhs else ""
        if not id_str:
            caller.msg("Usage: |w+discuss/comment <id>[=<text>]|n")
            return
        job, err = _lookup_job(id_str)
        if err:
            caller.msg(err)
            return
        if job.job_type != JobType.DISCUSS:
            caller.msg("Use |w+jobs/comment|n for player tickets.")
            return
        if job.status == JobStatus.CLOSED:
            caller.msg("That discussion is closed. Use |w+jobs/reopen|n first.")
            return

        if self.rhs is not None:
            text = self.rhs.strip()
            if not text:
                caller.msg("Comment text cannot be empty.")
                return
            JobComment.create_comment(job=job, author=caller, content=text)
            caller.msg(f"|gComment added to discussion #{job.job_number}.|n")
        else:
            _open_editor(caller, JobType.DISCUSS, "", mode="comment", job_pk=job.pk)


# ---------------------------------------------------------------------------
# +jobs
# ---------------------------------------------------------------------------


class CmdJobs(MuxCommand):
    """
    Manage the staff ticket queue.

    Usage:
        +jobs                           - List all non-closed tickets
        +jobs <id>                      - View a ticket with all comments
        +jobs/list <type>               - Filter by type (request/bug/issue/discuss)
        +jobs/assign <id>=<character>   - Assign ticket to a staff member
        +jobs/status <id>=<status>      - Set status (open/in_review/answered/closed)
        +jobs/priority <id>=<priority>  - Set priority (normal/high/urgent)
        +jobs/comment <id>              - Add public comment (opens editor)
        +jobs/comment <id>=<text>       - Add public comment (inline)
        +jobs/staffonly <id>            - Add staff-only note (opens editor)
        +jobs/staffonly <id>=<text>     - Add staff-only note (inline)
        +jobs/close <id>                - Close a ticket
        +jobs/reopen <id>               - Reopen a closed ticket

    Staff-only command for full ticket management. Staff-only notes
    (via /staffonly) are hidden from the ticket submitter.
    """

    key = "+jobs"
    aliases = []  # noqa: RUF012
    help_category = "Staff"
    locks = getattr(settings, "JOBS_STAFF_LOCK", "cmd:perm(Builder)")

    def func(self):
        caller = self.caller
        switches = [s.lower() for s in self.switches]

        if not switches:
            if not self.args:
                self._list_all()
            elif self.args.strip().isdigit():
                self._view(self.args.strip())
            else:
                caller.msg("Usage: |w+jobs [<id>]|n or use a switch.")
            return

        if "list" in switches:
            self._filter_list(self.args.strip().lower() if self.args else "")
        elif "assign" in switches:
            self._assign()
        elif "status" in switches:
            self._set_status()
        elif "priority" in switches:
            self._set_priority()
        elif "comment" in switches:
            self._add_comment(staff_only=False)
        elif "staffonly" in switches:
            self._add_comment(staff_only=True)
        elif "close" in switches:
            self._close()
        elif "reopen" in switches:
            self._reopen()
        else:
            caller.msg(f"Unknown switch: {switches}")

    def _list_all(self):
        from evennia_jobs.models import Job

        jobs = list(Job.objects.by_priority().exclude(status=JobStatus.CLOSED))
        if not jobs:
            self.caller.msg("No open tickets.")
            return
        lines = ["|w Ticket Queue |n"]
        lines.append("|b" + "=" * 70 + "|n")
        for j in jobs:
            lines.append(_format_job_row(j, True))
        self.caller.msg("\n".join(lines))

    def _filter_list(self, type_str):
        from evennia_jobs.models import Job

        valid = {t.value for t in JobType}
        if type_str not in valid:
            self.caller.msg(f"Unknown type '{type_str}'. Valid: {', '.join(sorted(valid))}")
            return
        jobs = list(
            Job.objects.by_priority().filter(job_type=type_str).exclude(status=JobStatus.CLOSED)
        )
        if not jobs:
            self.caller.msg(f"No open {type_str} tickets.")
            return
        lines = [f"|w {type_str.title()} Tickets |n"]
        lines.append("|b" + "=" * 70 + "|n")
        for j in jobs:
            lines.append(_format_job_row(j, True))
        self.caller.msg("\n".join(lines))

    def _view(self, id_str):
        job, err = _lookup_job(id_str)
        if err:
            self.caller.msg(err)
            return
        self.caller.msg(_format_job_detail(job, True))

    def _assign(self):
        from evennia.objects.models import ObjectDB

        caller = self.caller
        if not self.lhs or not self.rhs:
            caller.msg("Usage: |w+jobs/assign <id>=<character>|n")
            return
        job, err = _lookup_job(self.lhs.strip())
        if err:
            caller.msg(err)
            return
        name = self.rhs.strip()
        matches = ObjectDB.objects.filter(db_key__iexact=name)
        if not matches.exists():
            caller.msg(f"No character named '{name}' found.")
            return
        assignee = matches.first()
        job.assignee = assignee
        job.assignee_name = assignee.key
        job.save(update_fields=["assignee", "assignee_name", "updated_at"])
        caller.msg(f"|gTicket #{job.job_number} assigned to {assignee.key}.|n")

    def _set_status(self):
        caller = self.caller
        if not self.lhs or not self.rhs:
            caller.msg("Usage: |w+jobs/status <id>=<status>|n")
            return
        job, err = _lookup_job(self.lhs.strip())
        if err:
            caller.msg(err)
            return
        new_status = self.rhs.strip().lower()
        if new_status not in _VALID_STATUSES:
            caller.msg(
                f"Invalid status '{new_status}'. Valid: {', '.join(sorted(_VALID_STATUSES))}"
            )
            return
        if new_status == JobStatus.CLOSED:
            job.close()
        elif new_status == JobStatus.OPEN:
            job.reopen()
        else:
            job.status = new_status
            job.save(update_fields=["status", "updated_at"])
        caller.msg(f"|gTicket #{job.job_number} status set to {new_status}.|n")

    def _set_priority(self):
        caller = self.caller
        if not self.lhs or not self.rhs:
            caller.msg("Usage: |w+jobs/priority <id>=<priority>|n")
            return
        job, err = _lookup_job(self.lhs.strip())
        if err:
            caller.msg(err)
            return
        new_priority = self.rhs.strip().lower()
        if new_priority not in _VALID_PRIORITIES:
            caller.msg(
                f"Invalid priority '{new_priority}'. Valid: {', '.join(sorted(_VALID_PRIORITIES))}"
            )
            return
        job.priority = new_priority
        job.save(update_fields=["priority", "updated_at"])
        caller.msg(f"|gTicket #{job.job_number} priority set to {new_priority}.|n")

    def _add_comment(self, staff_only=False):
        from evennia_jobs.models import JobComment

        caller = self.caller
        id_str = self.lhs.strip() if self.lhs else ""
        if not id_str:
            switch = "staffonly" if staff_only else "comment"
            caller.msg(f"Usage: |w+jobs/{switch} <id>[=<text>]|n")
            return
        job, err = _lookup_job(id_str)
        if err:
            caller.msg(err)
            return
        if job.status == JobStatus.CLOSED:
            caller.msg(f"Ticket #{job.job_number} is closed. Use |w+jobs/reopen|n first.")
            return

        if self.rhs is not None:
            text = self.rhs.strip()
            if not text:
                caller.msg("Comment text cannot be empty.")
                return
            JobComment.create_comment(
                job=job, author=caller, content=text, is_staff_only=staff_only
            )
            tag = " (staff-only)" if staff_only else ""
            caller.msg(f"|gComment added to ticket #{job.job_number}{tag}.|n")
        else:
            _open_editor(
                caller, job.job_type, "", mode="comment", job_pk=job.pk, staff_only=staff_only
            )

    def _close(self):
        caller = self.caller
        id_str = self.args.strip() if self.args else ""
        if not id_str:
            caller.msg("Usage: |w+jobs/close <id>|n")
            return
        job, err = _lookup_job(id_str)
        if err:
            caller.msg(err)
            return
        if job.status == JobStatus.CLOSED:
            caller.msg(f"Ticket #{job.job_number} is already closed.")
            return
        job.close()
        caller.msg(f"|gTicket #{job.job_number} closed.|n")

    def _reopen(self):
        caller = self.caller
        id_str = self.args.strip() if self.args else ""
        if not id_str:
            caller.msg("Usage: |w+jobs/reopen <id>|n")
            return
        job, err = _lookup_job(id_str)
        if err:
            caller.msg(err)
            return
        if job.status != JobStatus.CLOSED:
            caller.msg(f"Ticket #{job.job_number} is not closed (current: {job.status}).")
            return
        job.reopen()
        caller.msg(f"|gTicket #{job.job_number} reopened.|n")
