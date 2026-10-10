# Migration notes

The source project supplied early NPC data definitions and a command sketch.
This release implements a standalone public package with host ruleset values,
registry-gated partners and additive migrations. It does not import legacy
tables automatically. Import scripts should preserve identity and permission
semantics explicitly; deleted holders must never become open permissions.

History stores scene references on spawn records rather than relying on an
object foreign key that becomes null after despawn. Combat profiles hold durable
configuration only; fight state belongs to a combat provider.
