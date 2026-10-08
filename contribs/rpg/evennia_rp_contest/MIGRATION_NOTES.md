# Migration notes

This package was authored directly in staging as a contrib-native pilot,
following the approved non-combat RP test design. It is not an extraction of
a working source implementation. Games retain their ruleset values and thin
subject, vocabulary, scene and session adapters. Existing command stubs may
be replaced by importing or subclassing `commands.CmdTest`.

There are no data migrations from a source game. Run the initial migration
before registering the command. Optional partner references are integer ids,
and all resolution detail is private to staff review.

Install pinned links and rules packages before contest and use that order in
`INSTALLED_APPS`. Configure a subject adapter and vocabulary independently of
chargen: a game-provided `DictStatSource` and the ruleset vocabulary suffice.
Contest does not require or import combat for resolution.

Scenes and RP-session tracking are optional. Configure their app labels and
the scene-id resolver to enable shipped listeners; without them, manual
closure and idle expiry remain available. A native scene system may replace
the check-log writer with its own SYSTEM capture listener. Keep that capture
inside the check transaction and avoid connecting two writers for one check.
