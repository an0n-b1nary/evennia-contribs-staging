# Migration notes

This initial contrib introduces its own schema. Existing games keep their
character typeclasses and can add the app, migrate, register commands and wire
the scheduler independently of resources. No private game modules are required.

Existing currency data needs an explicit host conversion using the audited
credit API. The package does not assume a legacy balance field or import it
automatically. Apply eligibility rules before enabling the scheduler if only
approved characters should receive stipends or passive income.
