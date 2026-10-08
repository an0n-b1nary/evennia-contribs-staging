# Downstream snapshot verification

The gate installs every contrib, with its web extras where declared, from
public Git revisions into two fresh Python 3.12 environments. It verifies
non-editable PEP 610 provenance, versions, dependency consistency, and the
installed Python files, templates and static assets against the public tree.
Existing migration files must be present and unchanged in the target tree;
dependency locks are retained alongside the per-package provenance.
The reference game is copied from the corresponding immutable snapshot.
One public clone supplies the Git objects for all subdirectory installs through
a per-process URL rewrite. Requirements and PEP 610 provenance retain the public
URL and exact SHA; no Git configuration is changed outside the install process.

From a Python 3.12 environment:

```sh
python scripts/downstream_gate.py \
  --new-revision 0d5beef3fcf7ebdcb34eb57f07a4056de1d9a34f
```

The default old revision is
`1939b8aa80d8e90c408715d68ca18a379d1699b4`: it includes the XP spend ledger,
but predates chargen's additive `budget_cost_overrides` migration. Override it
with `--old-revision <full-sha>`. Both revisions must be reachable from a
branch in the public repository. Use a target whose required CI checks passed.
The workflow **Downstream snapshots** runs the same command on demand with
explicit revision inputs and uploads only sanitized evidence.

Four phases run:

1. **Fresh installation:** the complete nonempty sandbox integration suite,
   deterministic RP and Chromium cases, a separate normal-RNG host, rendered
   pages for every mounted web contrib plus API/client shells, static discovery,
   system checks and contrib migration-state checks.
2. **Population and backup:** real ordinary-player commands create sheets,
   abilities, purchases, checks, scenes and logs in the older snapshot. Older
   allowance-only chargen skips the newer mixed-XP case. The public XP service
   adds a persistent spend and a refunded spend, and fixture setup adds a
   lore/scene link and acquisition. After server shutdown, SQLite's backup API
   creates an independent backup with a private logical snapshot and checksum.
3. **Upgrade:** a new target host receives a copy of that backup, runs migrations,
   verifies every existing row projected onto its original columns, then boots
   and checks sheet/ability/ledger/audit persistence, player commands, denied
   unauthorized XP grants and a new check. Added rows, columns and tables are
   permitted; changed/deleted old data fails until an explicit expected data
   transformation is implemented. Applied migration differences are recorded.
4. **Restore:** another new host uses the original backup and older packages.
   It repeats data, cross-link, login and gameplay checks. The original backup's
   checksum must remain unchanged. Each host verifies its owned processes stop.

Hosts and listeners are disposable and localhost-only. The existing live
driver's guarded synchronization hooks are copied only into those hosts.
A declared fixture setting uses `BaseOption` for the blank pose separator,
avoiding the known old scaffold `Text` deserialization error; package code is
never patched. Browser testing runs against the target snapshot. The old
population phase is fixture preparation, not a full browser acceptance pass.

The migration check compares Django's detected changes for contrib apps and
reports upstream app drift separately. This avoids writing Evennia's known
model/migration drift into site-packages. No migrations are generated here.

Runs live under `.downstream-runs/<id>/`, or `--output-root <directory>`.
Only that run's `evidence/` directory is suitable for sharing. The sibling
environments, games, backup, snapshots and raw logs contain disposable
credentials and full player data. Keep them local. A failed run exits nonzero
and retains its artifacts; inspect its logs. To retry with the same revisions:

```sh
python scripts/downstream_gate.py \
  --old-revision <original-old-sha> --new-revision <original-new-sha> \
  --resume .downstream-runs/<id>
```

Resume reuses complete isolated environments and successful phase results;
incomplete package installations are retried from the verified public clone.
failed phases receive new host directories. It is for an interrupted run with
the same driver, not a substitute for a fresh gate after driver changes.

Driver fault tests:

```sh
python -m pip install psutil==7.1.0
python scripts/test_downstream_gate.py
python scripts/test_playtest.py
```

This verifies the selected reference snapshots and SQLite upgrade path.
Downstream permission/settings/theme overrides, other database backends,
future data transformations and subjective balance need their own checks.
