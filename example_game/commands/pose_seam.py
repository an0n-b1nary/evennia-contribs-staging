"""Pose command override that feeds the rptracker/scenes seams.

Evennia's stock `pose`/`emote` command (`evennia.commands.default.general.CmdPose`)
calls `location.msg_contents()` directly — it has no character-level hook a
downstream game can override. The contribs' integration recipes (see the
"Integration recipe" / "Wire capture hooks" sections of the evennia-rptracker
and evennia-scenes READMEs) assume the game's own pose command calls back into
the character. This is that callback point for the sandbox: a thin CmdPose
subclass that does exactly what stock CmdPose does, then reports the pose to
whichever seams are installed.
"""

import time

from evennia.commands.default.general import CmdPose


class CmdSandboxPose(CmdPose):
    """Strike a pose, then feed evennia_rptracker + evennia_scenes."""

    def func(self):
        super().func()
        if not self.args:
            return

        caller = self.caller
        pose_text = f"{caller.name}{self.args}"

        # rptracker's record_rp_activity reads last_pose_time off the
        # character rather than setting it — the game is responsible for
        # updating it on every pose (see the contrib's Integration recipe).
        caller.last_pose_time = time.time()

        if caller.location:
            from evennia_rptracker import record_rp_activity

            record_rp_activity(caller, caller.location)

        from evennia_scenes.capture import capture_to_scene

        capture_to_scene(caller, pose_text, log_type="pose")
