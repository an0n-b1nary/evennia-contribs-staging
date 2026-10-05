# Migration notes

This package was authored directly in staging as a contrib-native pilot,
following the approved non-combat RP test design. It is not an extraction of
a working source implementation. Games retain their ruleset values and thin
subject, vocabulary, scene and session adapters. Existing command stubs may
be replaced by importing or subclassing `commands.CmdTest`.

There are no data migrations from a source game. Run the initial migration
before registering the command. Optional partner references are integer ids,
and all resolution detail is private to staff review.
