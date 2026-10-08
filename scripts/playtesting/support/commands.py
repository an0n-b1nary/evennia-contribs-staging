"""Narrow read-only probe; fixture actions still use ordinary game commands."""

from django.conf import settings
from evennia import CmdSet
from evennia.commands.default.muxcommand import MuxCommand

from .runtime import enrolled, frame, guard


class Probe(MuxCommand):
    key = "+playtest"
    account_caller = True
    locks = "cmd:all()"
    switch_options = ("info", "arm", "state")

    def func(self):
        guard()
        if not enrolled(self.session):
            return
        token = self.args.strip()
        if not token or len(token) > 80 or not token.replace("-", "").isalnum():
            self.msg("A playtest request token is required.")
            return
        if "arm" in self.switches:
            self.session.ndb.playtest_token = token
            frame(self.session, "armed", token)
        elif "state" in self.switches:
            if self.caller.db.playtest_role != "staff" or not self.caller.check_permstring(
                "Builder"
            ):
                self.msg("Only the playtest staff account can inspect state.")
                return
            from .snapshot import snapshot

            frame(self.session, "state", token, state=snapshot())
        else:
            puppet = self.session.puppet
            frame(
                self.session,
                "info",
                token,
                run_id=settings.PLAYTEST_RUN_ID,
                version=1,
                account=self.caller.pk,
                character=puppet.pk if puppet else None,
                role=self.caller.db.playtest_role,
                permissions=list(self.caller.permissions.all()),
                character_permissions=list(puppet.permissions.all()) if puppet else [],
                superuser=self.caller.is_superuser,
            )


class ProbeCmdSet(CmdSet):
    key = "PlaytestProbe"

    def at_cmdset_creation(self):
        self.add(Probe())
