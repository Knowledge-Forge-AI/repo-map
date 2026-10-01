# SQLite Local First Slice

Operator reference for the first SQLite Local loop
([ADR 0075](../adr/2026/09/0075-sqlite-local-first-slice.md); Product step 4,
in progress). A SQLite Local home needs no PostgreSQL settings, credentials,
`psql`, coordinator, server or Docker daemon, and the commands below start and
run without importing the PostgreSQL Python driver (Psycopg). PostgreSQL homes
are unchanged.

## Installing

The base distribution is the SQLite Local install. Its only dependency is
`typing-extensions==4.16.0`; it installs no PostgreSQL driver. The PostgreSQL
Server Engine needs the `postgres` extra, which pins
`psycopg[binary]==3.2.12` (LOCAL11):

```sh
# From a directory holding the reviewed wheel
python -m pip install --find-links ./dist 'repomap-kg==0.1.0'            # SQLite Local
python -m pip install --find-links ./dist 'repomap-kg[postgres]==0.1.0'  # Server Engine
# From a source checkout
python -m pip install .                  # SQLite Local
python -m pip install '.[postgres]'      # PostgreSQL/Server work
```

The generated Server image installs `.[postgres]`. Repository test, static
and SCALE extras compose with either form (see the README).

The wheel is tagged `py3-none-any`, but that tag is not platform
qualification:

- Linux: the base wheel's Local flow is qualified in a clean container
  (LOCAL11), with Psycopg absent.
- macOS: an attended native installed-wheel proof is prepared but **pending**
  (see Installed-wheel qualification).
- Windows: Local mutation is **not yet native-qualified** and currently
  refuses before locking (see Commands).

The wheel carries no Go helper. Go extraction from a wheel install needs
`REPOMAP_GO_HELPER`.

### Installed-wheel qualification (pending)

The next attended proof installs the exact reviewed base wheel, identified by
its SHA-256, into a fresh ordinary macOS venv. It does not use an editable
checkout, the project `.venv` or `PYTHONPATH`. It runs from an unrelated
directory and uses no network: the operator kit installs with
`--no-index --require-hashes` from the kit's own wheels. It proves:

- Psycopg is absent;
- `repomap_kg` imports from the venv;
- `--help` and `--version`;
- `ops config-check`, `ops graphs --check-db`, `ops sqlite-init`,
  `ops refresh-preflight` and a direct `ops refresh-graph` on a two-file
  fixture;
- stdio MCP reads;
- `ops sqlite-backup` and `ops sqlite-restore`, with equal MCP results after
  restore and the source hidden;
- a PostgreSQL home refuses with `postgresql-driver-unavailable`.

The kit removes only its own marked work directory. The same kit passed in a
Linux container (status 00987). The manager authorizes and reviews the native
run; it is not self-accepted.

## Home

Select the backend once per home, in the home's **first** file. Files load as
`*.rp.toml` by name, then `*.rpl.toml` by name. The first file's `[storage]`
table fixes the backend; if that table is absent, the backend is PostgreSQL.
Any later file may omit `[storage]` or repeat the same backend. Every other
declaration is refused with `storage-backend-conflict`, and no overlay ever
switches a home:

- a SQLite overlay (for example `zz-local.rpl.toml` declaring `sqlite`) on a
  home whose first file has no `[storage]` table or declares `postgresql`;
- a `postgresql` overlay on a SQLite home;
- a later file without `[storage]` that carries `[postgres]` or `[runtime]`
  (PostgreSQL-only settings) in a SQLite home. This includes a SQLite file
  added so that it sorts ahead of an existing PostgreSQL `repomap.rpl.toml`.

```toml
# ~/.repo-map-local/repomap.rp.toml
schema_version = 1

[storage]
backend = "sqlite"

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[[graphs]]
id = "example"
name = "Example"
root_path = "~/src/example"
repository_name = "example"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "./server-memory"
mode = "read_only"
```

Multi-source graphs use the ordinary `[[graphs.source_bindings]]` syntax.
`[postgres]`, `[runtime]` and a per-graph `database` are refused in a SQLite
home.

## Commands

These are the exact argument shapes exercised by the containerized loop owner
(`src/test/int/python/repomap_kg/cli/sqlite_local_loop.int.test.py`).

```sh
# Create the graph's database at the current schema (v2: every migration in
# order). Idempotent: an existing current database of the same graph reports
# `already-current` and is not rewritten; an older-schema database is refused
# (`graph-database-schema-behind`) and never upgraded here (see Schema upgrade).
# The database is built in a temporary sibling file and hard-linked into place
# only when complete; an existing file is never replaced.
repomap-kg ops sqlite-init --repo-map-home ~/.repo-map-local --graph example --json

# Full refresh: capture sources with the portable worker, validate in the
# parent, and publish one new accepted generation.
repomap-kg ops refresh-graph --repo-map-home ~/.repo-map-local --graph example --json

# A second full refresh publishes generation 2 (previous_run_id 1).
repomap-kg ops refresh-graph --repo-map-home ~/.repo-map-local --graph example --json

# Read-only stdio MCP over the accepted generations.
repomap-kg mcp serve --repo-map-home ~/.repo-map-local
```

The ordinary operator workflow
(`src/test/int/python/repomap_kg/cli/sqlite_local_operator_workflow.int.test.py`):

```sh
# Validate the merged home: backend authority, graph registry, source bindings,
# privacy and visibility, and the SQLite-only refusals. Reads no graph root and
# opens no database.
repomap-kg ops config-check --repo-map-home ~/.repo-map-local --json

# Same, plus a read-only readiness probe of every configured graph's database.
repomap-kg ops config-check --repo-map-home ~/.repo-map-local --check-db --json

# Configured graph inventory in configuration order; --check-db adds per-graph
# readiness from the same probe.
repomap-kg ops graphs --repo-map-home ~/.repo-map-local [--check-db] --json

# Inspect one enabled graph's configured sources and excludes; no database,
# worker or publication.
repomap-kg ops refresh-preflight --repo-map-home ~/.repo-map-local --graph example --json

# Refresh every enabled graph, in configuration order, each as a separate direct
# refresh-graph (own lock, reconciliation and publication).
repomap-kg ops refresh-enabled --repo-map-home ~/.repo-map-local --json
```

`config-check` keeps the PostgreSQL envelope (`valid`, `service`, `graphs`,
`graph_counts`, `server_memory`, `sources`, `diagnostics`, `compatibility`,
`safety`) and adds `storage = {"backend": "sqlite"}` and `storage_status`. The
PostgreSQL keys `postgres`, `runtime` and `postgres_status` are absent, not
invented. `graphs` keeps the PostgreSQL row fields; a graph's `database` is
`[graph-database]` (`[private-database]` for a private graph) with
`database_source = "sqlite-graph-file"`, and top-level `storage` names the
backend. The physical database path is never printed. A configuration is valid
without any graph being initialized.

With `--check-db`, `storage_status` (per graph for `graphs`) reports each
configured graph, disabled graphs included, with `state`, `published`,
`accepted_generation` and a bounded `error` code:

| State | Meaning |
|---|---|
| `not-initialized` | No database file; run `ops sqlite-init` |
| `current` | A readable current database of this graph; `published` is false until the first accepted generation |
| `schema-behind` | An exact older known schema (for example a v1 database or a restored v1 backup) with its `accepted_generation`; `error` is `graph-database-schema-behind`. Ordinary reads, refresh and init refuse it until `ops sqlite-upgrade` runs |
| `unrecognized` | The file is not a current or exact-behind RepoMap database of this graph (`graph-database-unrecognized`, `-schema-drift`, `-schema-unsupported`, `-graph-mismatch`) |
| `unavailable` | The database could not be read now (`graph-database-busy`, `graph-database-unavailable`, `sqlite-runtime-unsupported`) |
| `invalid-configuration` | The graph store would overlap a configured source root |

The probe opens an existing file read-only and never creates, initializes,
migrates, repairs or reconciles anything: a missing database stays missing and
no `state/` directory is created. Like every Local read, it may create or keep
an existing database's own `-wal`/`-shm` sidecars; the database bytes do not
change. Resolving the database path reads source-root metadata (path
resolution), never source content.

`refresh-enabled` skips disabled graphs; MCP visibility does not affect
eligibility. A graph-level refusal or failure becomes a failure row
(`graph_id`, `result = "failure"`, `error_category`, path-free `error`) and the
next graph still runs; an interrupt records `cancelled` and stops. The
aggregate `result` is `success`, `partial` or `failed` (exit 0 only on
`success`). `error_category` is `refresh-rejected` (disabled, unsupported or
missing source root), a store code from the table below, a portable-route
category, `refresh-failed` (type name only; rerun `ops refresh-graph` for that
graph to see the sanitized detail) or `cancelled`. Success rows carry the
`refresh-graph` fields without `command` and `storage_backend`. There is no
transaction across graph databases and no PostgreSQL, coordinator or container
fallback.

Direct serialized refresh is the supported Local baseline. `ops refresh-graph
--mode coordinator` on a SQLite home is refused by design with
`sqlite-local-refresh-rejects-coordinator-mode`, with or without
`--idempotency-key`, before the configuration is parsed and before any
database, source, worker or coordinator is touched. SQLite Local has no
durable coordinator.

Each graph's database is
`<home>/state/sqlite-local/graphs/<graph_id>.sqlite3` (mode 0600 in a 0700
directory), with WAL sidecars (`-wal`, `-shm`) and a `.publish.lock` file next
to it. The store must be on a local filesystem; WAL does not work over network
filesystems. Do not copy a database file while RepoMap may be using it, and do
not copy it without its sidecars; use `ops sqlite-backup` (below) instead.

Every command that changes a graph's Local state (`sqlite-init`,
`refresh-graph`/`refresh-enabled`, `sqlite-backup`, `sqlite-restore`,
`sqlite-upgrade` and `sqlite-cleanup --yes`) holds that graph's one lock: an
exclusive, non-blocking operating-system lock on the `.publish.lock` file,
never on the database. A second command for the same graph refuses at once
with `graph-publication-in-progress`; other graphs are independent. The lock
is released when the command exits, including when it is killed; a stale lock
file on disk is harmless and must not be deleted by hand. Its bytes mean
nothing. The lock file must be a regular, single-link file you own (a
mutation resets its mode to `0600`); anything else refuses with
`graph-database-unavailable: graph lock file is not private`. On POSIX hosts
the lock is `flock`. A Windows backend (`msvcrt` byte-range locking) exists
and is contract-tested but not natively qualified; native Windows Local
mutation currently refuses `local-state-layout-invalid` before locking because
ownership cannot be verified there. Any other platform refuses
`local-locking-unavailable` rather than running unlocked.

Commands that change Local state also require `<home>/state` to be a real
directory you own, not a symlink (LOCAL10). Every existing level from `state/`
down to the paths the command uses must be a real directory of your uid, and
the graph database must resolve inside `state/sqlite-local/graphs`. Otherwise
the command refuses `local-state-layout-invalid` (`sqlite-cleanup` reports the
same rule as `sqlite-cleanup-layout-invalid`) before taking the lock or
writing anything. This also applies to a symlinked `state` whose target is
itself named `state`, which LOCAL9 still accepted. The home itself may be a
symlink. Read-only commands (`config-check`, `graphs`, `mcp serve`) do not
check it. RepoMap never relinks or migrates `state/`; to keep data on another
volume, symlink the home instead.

On a SQLite home, `refresh-graph` and `refresh-enabled` refuse
`--psql-command` (`sqlite-local-refresh-rejects-psql-command`), `config-check`
and `graphs` refuse it (`sqlite-local-rejects-psql-command`), and
`refresh-graph` refuses the internal PostgreSQL telemetry options. The remaining
PostgreSQL-only commands (`refresh-status`, `graph-summary`, `graph-files`,
baselines, drift, policy dogfood, backups and the storage commands) refuse a
SQLite home with `sqlite-local-home-requires-local-command`.

Without the PostgreSQL driver installed, the commands above, `--help`,
`--version` and `mcp serve` still work. A command that needs PostgreSQL exits 1
with `postgresql-driver-unavailable`. That includes a home whose configuration
cannot be read (it is routed to the PostgreSQL loader, as before) and a bare
`repomap-kg` with no subcommand. Since LOCAL11 the base `repomap-kg`
distribution does not install Psycopg (see Installing).

## Backup, export and restore

Owned by the containerized backup/restore owner
(`src/test/int/python/repomap_kg/cli/sqlite_local_backup_restore.int.test.py`).
Both commands are SQLite-only, read no source root and start without the
PostgreSQL driver. A PostgreSQL home refuses with `sqlite-local-home-required`
before anything is touched.

```sh
# Write a verified backup of one initialized graph (enabled or not) into a new
# or empty directory. The directory is also the Local export format.
repomap-kg ops sqlite-backup --repo-map-home ~/.repo-map-local --graph example \
  --output ~/repomap-backups/example-2026-09-29 --json

# Restore a verified backup into an ABSENT graph database.
repomap-kg ops sqlite-restore --repo-map-home ~/.repo-map-local --graph example \
  --backup ~/repomap-backups/example-2026-09-29 --json
```

A completed backup is a directory holding exactly two `0600` files. When
`--output` is absent, RepoMap creates the directory with mode `0700` (a process
umask can only narrow it). An existing empty directory you supply keeps its
own mode: RepoMap neither changes nor checks it, so make it private yourself
(for example `chmod 700`). The files:

- `graph.sqlite3`: a self-contained snapshot (no `-wal`/`-shm`) of the graph
  database, taken with SQLite's online backup API under the graph's publisher
  lock, so it includes committed changes still in the live WAL and never
  writes the live database;
- `manifest.json`: canonical JSON with `format`
  (`repomap-sqlite-local-backup`), `manifest_version` (1), `created_at` (UTC),
  `graph` (`graph_id`, `repository_identity`, `root_path = "graph:<id>"`),
  `sqlite` (`application_id`, `user_version`, `schema_name`,
  `schema_checksum`; see below), `publication` (`accepted`, `generation`, `run_id`,
  `publication_bundle_id`, `publication_job_id`, `publication_attempt`,
  `privacy`; all `null` when unpublished) and `database` (`file`, `bytes`,
  `sha256`).

`sqlite.user_version` is the backed-up database's exact schema version (1 or 2)
and `schema_name`/`schema_checksum` identify that version's *head migration*
(the last changeset applied), not a checksum of the whole schema; the
database itself must hold exactly that catalog prefix (ledger, `user_version`
and physical schema). A backup of a v1 database, including every backup made
before LOCAL8, is a v1 backup.

`manifest.json` is written last and marks the backup complete. It contains no
source root, home, backup or other path, no environment value and no graph
content, so it can be shared apart from its graph and publication ids. The
database holds the graph's accepted content and keeps the graph's privacy
classification; treat it like the live database.

`sqlite-backup` JSON: `command`, `storage_backend`, `result = "created"`,
`graph_id`, `schema_version`, `accepted_publication`, `accepted_generation`,
`publication_bundle_id`, `database_bytes`, `database_sha256`.
`sqlite-restore` JSON: the same without `database_bytes`, with
`result = "restored"` and `schema_state` (`current` or `behind`). Neither
prints a path.

Backup rules:

- The output must be absent or an empty directory whose parent exists. It must
  not be inside the home's `state/` directory or any configured source root,
  so a refresh can never capture a backup. An existing backup, complete or
  partial, is never replaced; choose another directory.
- A graph whose publisher lock is held (a refresh or init is running) refuses
  immediately with `graph-publication-in-progress`; rerun when it finishes.
- A failure or interrupt removes what this attempt created. Only a killed
  process can leave a partial directory; it has no `manifest.json`, restore
  refuses it as `sqlite-backup-incomplete`, and it can be deleted by hand.

Restore rules:

- The whole backup is verified before the graph store is touched: exactly the
  two files, a strict manifest for this configured graph and a known schema
  version, the database's length and SHA-256, and the database itself
  (application id, exactly the manifest's schema version, graph binding,
  `integrity_check`, and exactly the manifest's accepted publication). A
  mismatch between the manifest's and the database's version refuses as
  `sqlite-backup-artifact-invalid: schema-mismatch`; unknown, future or
  drifted schemas refuse.
- A v1 backup restores as a v1 database and is never upgraded by restore:
  `graphs --check-db` shows `schema-behind`, and MCP reads and refresh refuse
  `graph-database-schema-behind` until you run `ops sqlite-upgrade`. A v2
  backup restores as `current`.
- The target must be absent. Any existing database file, valid or not, or any
  leftover `-wal`/`-shm`/`-journal` refuses with `sqlite-restore-target-exists`
  and is left untouched. There is no `--force`: replacing an existing or
  corrupt database is a separate, destructive recovery decision (see Recovery).
- After restore, MCP and `ops graphs --check-db` read the restored accepted
  generation with no source roots present. Retained attempts are not touched.
  The next `ops refresh-graph` reconciles them against the restored marker
  under the rules in Recovery → Interrupted publications, and then publishes
  the next generation (generation N+1 with a new bundle id, so a generation
  number alone is not a publication identity). Reconciliation is automatic
  only when an armed unsettled attempt's publication is the restored accepted
  generation (settled accepted) or its expected previous generation is the
  restored one (settled failed). Otherwise it is not automatic. For example,
  after restoring an older backup an armed attempt can expect a generation
  ahead of the restored marker, or the restored marker can be two or more
  generations ahead of it. The refresh then refuses with
  `graph-publication-reconciliation-required: accepted-generation-mismatch`
  (or `publication-identity-conflict`) and changes nothing; follow the manual
  steps in Interrupted publications, which quarantine the stale attempt
  directory by hand.
- Restore keeps the accepted run's privacy class as backed up; it never
  reclassifies data.

Durability: on success, the backup files and their directory, or the restored
database and the graph store directory, have been fsynced (so have a new
store's parent directories up to the home). A failed sync is reported as
`local-durability-failed` or `local-durability-unavailable` and is never
success. On macOS `fsync` does not force the drive's write cache
(`F_FULLFSYNC`), the same as SQLite's default; power loss can still lose the
most recent writes. `sqlite-init` and Local refresh attempt records follow the
same ordering. Each attempt-record replacement fsyncs the attempt directory and
every retention level above it through `<home>/state`
(`attempts/`, `<graph_id>/`, `sqlite-local/`, `portable-publication/`, `state/`),
so the namespace created by a graph's first refresh is durable too. The home
itself is not synced there: `sqlite-init` of a new database, and restore,
sync `state/`'s entry in the home. A home whose database was initialized
before LOCAL7 (or only reported `already-current` since) did not get that
sync. `ops sqlite-cleanup --yes` (see State cleanup) fsyncs `state/` and then
the home, so the entry is durable from that run on. That is current
durability, not proof that the home was ever synced before.

A Local attempt record is replaced only when its resolved directory chain is
exactly `<...>/state/portable-publication/sqlite-local/<graph_id>/attempts/<attempt>`
and no level below `portable-publication` is a symlink; anything else refuses
before any write. Since LOCAL10 a symlinked `state` is refused earlier by
every command that changes Local state (see above); a symlinked home keeps
working.

## Schema upgrade

Owned by the containerized migration owner
(`src/test/int/python/repomap_kg/cli/sqlite_local_migration.int.test.py`).
The current schema is v2. Schema changes are an ordered, checksummed catalog:

| Version | Name | Checksum | Change |
|---|---|---|---|
| 1 | `sqlite-local-v1` | `sha256:7f5b6045f0a46e699d42e8d8e90d51141c5db909b1eecfb3718a69df4825321d` | The LOCAL1 schema (unchanged) |
| 2 | `sqlite-local-v2-observation-path-index` | `sha256:b5518fac02fde45a2a986995e4cf284840ccbee44092a5492c45f04651107489` | `idx_raw_observations_path_run ON raw_observations(path, run_id DESC, ordinal)`, used by exact-path observation search; no result changes |

A database is `schema-behind` only when its ledger is exactly the first
versions of that catalog, `user_version` equals that version and its physical
schema equals that version's schema. Anything else (a wrong checksum or name,
a missing or extra object, `user_version` disagreeing with the ledger) is
`graph-database-schema-drift`; a version beyond the catalog is
`graph-database-schema-unsupported`. Neither is ever upgraded.

```sh
# Explicitly upgrade one older-schema graph, writing a verified backup first.
repomap-kg ops sqlite-upgrade --repo-map-home ~/.repo-map-local --graph example \
  --backup-output ~/repomap-backups/example-pre-v2 --json
```

`sqlite-upgrade` is SQLite-only, source-blind and driver-free; a PostgreSQL
home refuses with `sqlite-local-home-required`. Under the graph's publisher
lock (a held lock refuses immediately with `graph-publication-in-progress`) it:

1. classifies the database. A current database reports
   `already-current` and does nothing: no backup, and `--backup-output` is
   neither checked for emptiness nor created. Drift, future, foreign and
   graph-mismatch databases refuse before any backup;
2. writes a normal backup (the `sqlite-backup` format and output rules) of the
   unchanged database. Its manifest records the old version (`user_version =
   1`). An existing non-empty `--backup-output` refuses with
   `sqlite-backup-target-exists`;
3. re-verifies that backup from disk exactly as `sqlite-restore` would; a
   mismatch refuses with `sqlite-upgrade-backup-unverified` and keeps the
   backup;
4. in one transaction applies each pending migration and its ledger row, sets
   `user_version = 2`, checks the result is exactly the v2 schema, and commits
   once;
5. reads the database back and requires exact v2 with the same accepted
   generation and publication bundle.

JSON: `command = "sqlite-upgrade"`, `storage_backend`, `result`
(`upgraded` or `already-current`), `graph_id`, `from_schema_version`,
`schema_version`, `accepted_publication`, `accepted_generation`,
`publication_bundle_id`, `backup_created`, `backup_database_sha256`. No path.

The accepted generation and bundle never change. No source is captured and no
worker, network, PostgreSQL or container is used. The backup is never deleted;
it is your rollback point: restore it into an absent target with
`ops sqlite-restore` (it restores as v1, `schema-behind`). There is no
downgrade command.

Failures:

- Before the commit (backup failure, verification failure, a migration error
  or an interrupt): the transaction is rolled back and the database is still
  exactly v1; a completed backup stays valid. Rerun with a new empty
  `--backup-output`.
- `graph-migration-reconciliation-required: schema upgrade outcome unknown`:
  the commit was attempted but could not be confirmed by readback. The upgrade
  may have committed, so do not restore over it. Rerun `ops sqlite-upgrade`
  with a **new empty `--backup-output`**:
  - if the first run committed, the rerun reports `already-current` and writes
    no backup. The new output is not checked for emptiness or created; its
    parent and location checks still apply.
  - if it did not commit, the database is still exact v1 and the first run's
    verified backup remains in its original output. The rerun writes a fresh
    backup into the new output and upgrades.

  Reusing the first output while the database is still v1 refuses safely with
  `sqlite-backup-target-exists`.
- A killed upgrade leaves either exact v1 (before commit) or exact v2.
- `refresh-graph` refuses a behind database with
  `graph-database-schema-behind`. If a previous refresh left an armed
  unsettled attempt, reconciliation runs first and reports
  `graph-publication-reconciliation-required: graph-database-schema-behind`;
  upgrade, then refresh. Nothing is captured, run or published either way.

## State cleanup

Owned by the containerized cleanup owner
(`src/test/int/python/repomap_kg/cli/sqlite_local_cleanup.int.test.py`).

```sh
# Inventory one graph's stale Local state. Changes nothing (dry run).
repomap-kg ops sqlite-cleanup --repo-map-home ~/.repo-map-local --graph example --json

# Remove only what is provably safe, then sync state/ and the home.
repomap-kg ops sqlite-cleanup --repo-map-home ~/.repo-map-local --graph example --yes --json
```

`sqlite-cleanup` is SQLite-only, source-blind and driver-free; a PostgreSQL
home refuses with `sqlite-local-home-required`. Any configured graph, enabled
or not, can be cleaned. It looks only at:

- the graph's attempts, under `state/portable-publication/sqlite-local/<graph_id>/attempts/`;
- the shared attempts directory `state/portable-publication/attempts/`, which
  LOCAL1/LOCAL2-era Local refreshes used;
- this graph's temporary files in `state/sqlite-local/graphs/`.

It never scans another graph's namespace or anything outside the home. Every
existing directory on those paths must be a real directory owned by you. A
symlink anywhere refuses `sqlite-cleanup-layout-invalid` before anything is
read.

When the graph store directory (`state/sqlite-local/graphs`) does not exist,
there is no database and no lock file to hold, and cleanup does not create
either to satisfy locking. It then performs only the attempt actions in the
table below, each of which re-checks the attempt's exact identity before
removing it, and a refresh cannot publish without a store. Temporary files
are then reported `not-inspected`, even if a concurrent `sqlite-init` creates
the store while cleanup runs; the next run inspects them under the lock.

What `--yes` does:

| Item | Action |
|---|---|
| Attempt whose record is `terminal-accepted`/`terminal-failed` and whose `expires_at_epoch` has passed (24 h after settlement), in either directory | Removed; its tree must hold only real directories and single-link files you own |
| Terminal attempt not yet expired | Kept |
| Graph attempt still `publication-reconciliation` | Kept; the next `ops refresh-graph` reconciles it (`graph-attempt-unsettled`) |
| Shared attempt still `publication-reconciliation` | Kept; `legacy-unresolved-attempt`, manual recovery required (see Interrupted publications). It carries no publication identity, so RepoMap never attributes it to a graph or settles it |
| Attempt directory without a `portable-result.json` | Kept (`graph-attempt-incomplete`, `legacy-incomplete-attempt`) |
| Orphan `.<graph_id>.sqlite3.init-*` or `.restore-*` beside a current or schema-behind database | Removed. A second hard link to the live database loses only its orphan name |
| Orphan beside an absent database that is empty or a truncated/non-SQLite/non-WAL file, with no non-empty `-wal` or `-journal` | Removed (`partial`) |
| Orphan beside an absent database that is a complete database of this graph | Kept (`recoverable-orphan`; several also `multiple-recoverable-orphans`) |
| Any other orphan beside an absent database (another graph, a failed inspection, a non-empty `-wal` or a `-journal`) | Kept (`unrecognized-orphan-preserved`) |
| Orphan beside a database that is refused, busy or only sidecars | Kept (`final-database-not-valid`) |

Nothing is ever linked, renamed or adopted into the database path, and there
is no force mode; `sqlite-cleanup` never adopts an orphan. A recoverable orphan
is one of two kinds, and neither is recovered by cleanup:

- An **init** orphan holds only a freshly initialized, empty current schema.
  Rerunning `ops sqlite-init` creates the normal current database; it does
  **not** adopt the orphan's contents, and nothing is lost because there were
  none.
- A **restore** orphan holds the content of the backup being restored. Recover
  it by rerunning `ops sqlite-restore` from the **same verified backup** into
  the still-absent database. Do not run `ops sqlite-init` first: that creates
  the database, and restore then refuses `sqlite-restore-target-exists`. If
  that backup is no longer available, stop every RepoMap process and move the
  orphan (with any sidecars of the same name) out of the graph store into a
  quarantine directory for manual forensic handling before any later `--yes`:
  once a database exists, the orphan is stale and `--yes` removes it.

The payload counts both kinds as `recoverable_preserved`. After recovery the
orphan is stale and the next `--yes` removes it. The final database is only
read, and only when an orphan needs classifying.

Without `--yes` nothing is created, removed, chmodded or synced; the lock file
is not created if absent, and an existing one is only opened read-only and
locked. Like `graphs --check-db`, reading the database may
create or keep its own `-wal`/`-shm`. A held publisher lock refuses
`graph-publication-in-progress` in both modes.

`--yes` inventories everything first. If anything is unsafe (a symlink, a
wrong owner, mode or link count, an unreadable or malformed record, an unknown
retention class, an unexpected node inside an expired attempt, or an orphan
that is not a plain owner-only file), the whole run is `refused` and nothing
changes. The payload names only the class (`unsafe-graph-attempt`,
`unsafe-legacy-attempt`, `unsafe-orphan`), not the path. Stop every RepoMap
process, inspect the directories listed above, move the offending entry into a
quarantine directory outside the home, and rerun.

After removal, `--yes` fsyncs `state/` and then the home (`durability:
"established"`). With no `state/` directory, `durability` is `not-applicable`.
Removals themselves are not claimed durable: after a power loss a removed item
may reappear, and the next run removes it again.

JSON: `command = "sqlite-cleanup"`, `storage_backend`, `graph_id`, `result`,
`dry_run`, `changed`, `final_database`, `graph_attempts`,
`legacy_shared_attempts`, `orphans`, `durability`,
`manual_recovery_required`, `warning_count`, `warnings`, `refusal_count`,
`refusals` and `failures`.

- `result` is `dry-run`, `cleaned`, `refused` or `incomplete`.
- `final_database` is `current`, `behind`, `absent`, `not-valid`, or
  `not-inspected` when there is no orphan.
- `graph_attempts` and `legacy_shared_attempts` are counts:
  `expired_terminal_found`, `expired_terminal_removed`, `retained_terminal`,
  `unsettled_preserved` or `unresolved_preserved`, `incomplete_preserved`,
  `unsafe`.
- `orphans` are counts: `stale_found`, `stale_removed`, `partial_found`,
  `partial_removed`, `recoverable_preserved`, `unrecognized_preserved`,
  `held_preserved`, `unsafe`.
- `durability` is `established`, `not-attempted`, `not-applicable`,
  `local-durability-failed` or `local-durability-unavailable`.

A `refused` or `incomplete` run prints its payload and exits 1. `incomplete`
means a removal (`attempt-removal-failed`, `orphan-removal-failed`) or the
durability sync failed after validation; success is never claimed. No path,
file name or token appears in the payload.

## MCP matrix

Supported for SQLite Local graphs (all 23 database-reading tools):
`repomap_canonical_nodes`, `repomap_canonical_edges`,
`repomap_explain_canonical_edge`, `repomap_canonical_neighborhood`,
`repomap_status`, `repomap_graph_status`, `repomap_refresh_status` (one graph
or all visible), `repomap_project_summary`, `repomap_search_nodes`,
`repomap_search_files`, `repomap_search_observations`, `repomap_neighborhood`,
the `repomap_python_summary`, `repomap_terraform_summary`,
`repomap_openapi_summary`, `repomap_js_framework_summary` and
`repomap_nix_summary` tools, and the six source/feed tools
`repomap_ingested_sources`, `repomap_source_summary`, `repomap_source_runs`,
`repomap_source_feed_items`, `repomap_explain_source_feed_item` and
`repomap_source_references`. `repomap_list_graphs`, `repomap_projects` and the
two server-memory tools also work; they do not read a graph database.

Legacy `repomap_status` reads a SQLite graph only when `project` names a
graph-registry graph that is not also a legacy JSON-registry project. A legacy
project, the legacy `default_project` and explicit `root_path`/`pg_*`
arguments keep their PostgreSQL behavior, and a graph id combined with explicit
connection arguments is refused. Observation search keeps the `include_raw`
consent rule: `payload` appears only when requested, `metadata` always.

The source/feed tools answer from the graph's accepted publication only: the
source metadata on its raw observations and its canonical feed nodes, edges and
evidence. They never fetch a feed, read the source root or a retained artifact,
or publish, and they expose no feed body. A published graph without acquired
feed observations reads as empty (`[]`, the `source metadata unavailable`
summary, `item: null`).

Local refresh does not currently publish acquisition metadata. Feed acquisition
(`sources ingest-feed`) retains artifacts without publishing, and a configured
refresh never writes the `source_*` metadata. This is the same on PostgreSQL
configured graphs. So on refresh-published graphs these tools report no sources
until a publication route carries acquisition metadata; see ADR 0075.

## Refusals

| Error | Meaning |
|---|---|
| `graph-database-not-initialized` | Run `ops sqlite-init` for the graph |
| `graph-publication-absent` | Initialized, but no accepted generation yet (content tools, observation search, the neighborhood, the five language summaries and the six source/feed tools refuse; the status tools and project summary report an empty graph) |
| `graph-publication-in-progress` | Another command holds this graph's lock (refresh, init, backup, restore, upgrade or cleanup) |
| `accepted-generation-advanced` | Another publication committed during this attempt |
| `graph-publication-rejected` | Validation or a database constraint refused the bundle; nothing was published |
| `graph-publication-internal-error` | A database programming or interface error stopped the publisher; nothing was published (report it) |
| `graph-publication-reconciliation-required: <reason>` | An earlier refresh of this graph left an attempt whose outcome cannot be settled safely; nothing was captured or published (see Recovery) |
| `graph-database-unrecognized`, `graph-database-schema-drift`, `graph-database-schema-unsupported`, `graph-database-graph-mismatch` | The file is not a current or exact-behind RepoMap database of this graph; it is never reinitialized or upgraded |
| `graph-database-schema-behind: run ops sqlite-upgrade` | An exact older schema; run `ops sqlite-upgrade` (see Schema upgrade) |
| `graph-migration-reconciliation-required: schema upgrade outcome unknown` | An upgrade's commit could not be confirmed; rerun `ops sqlite-upgrade`, do not restore over it |
| `sqlite-upgrade-backup-unverified: <reason>` | The pre-upgrade backup did not verify against the live database; nothing was migrated and the backup was kept |
| `sqlite-upgrade-failed` | The database refused the schema change; it was rolled back and is still the old version |
| `graph-database-read-only` | A write was attempted through a read-only (MCP read) connection and refused; nothing changed |
| `graph-database-busy`, `graph-database-unavailable` | The database could not be read or written now, for example another writer holds it (also used when the store cannot hard-link: initialization needs an atomic no-clobber install, and as `graph-database-unavailable: graph lock file is not private` when the `.publish.lock` path is a symlink, directory, FIFO, second link or another user's file) |
| `local-locking-unavailable` | This platform has no supported graph lock primitive; nothing was changed and nothing runs unlocked |
| `local-state-layout-invalid` | `state/` or a level below it that the command uses is a symlink (even to a directory named `state`) or not a directory you own, or ownership cannot be verified on this platform; nothing was locked or changed |
| `<code>: publication outcome unknown` | The database failed after COMMIT was attempted and readback could not prove the result; the next refresh settles it (see Recovery) |
| `storage-backend-conflict` | A home file tries to change the backend its first file fixes |
| `sqlite-local-refresh-rejects-coordinator-mode` | SQLite Local refreshes directly; there is no coordinator |
| `sqlite-local-refresh-rejects-psql-command`, `sqlite-local-rejects-psql-command` | `--psql-command` is PostgreSQL-only |
| `postgresql-driver-unavailable` | The command needs PostgreSQL and the Psycopg driver is not installed |
| `sqlite-local-home-required` | `sqlite-init`, `sqlite-backup`, `sqlite-restore`, `sqlite-upgrade` and `sqlite-cleanup` need a SQLite home |
| `sqlite-cleanup-layout-invalid` | A level of `state/`, `state/portable-publication/...` or `state/sqlite-local/graphs` is a symlink or not a directory you own; nothing was read or changed (the same rule as `local-state-layout-invalid`) |
| `sqlite-backup-output-invalid`, `sqlite-backup-output-forbidden`, `sqlite-backup-target-exists` | The backup output is not a new or empty directory with an existing parent, is inside the home state or a source root, or already holds files; nothing was written |
| `sqlite-backup-incomplete` | The backup directory has no `manifest.json` (an interrupted backup); nothing was restored |
| `sqlite-backup-artifact-invalid: <reason>` | The backup failed verification (`unexpected-entry`, `manifest-invalid`, `format-unsupported`, `schema-unsupported`, `graph-mismatch`, `database-length-mismatch`, `database-digest-mismatch`, `publication-mismatch`, `database-changed-during-restore`, `schema-mismatch` or a database code); nothing was restored |
| `sqlite-restore-target-exists` | The graph already has a database (or leftover sidecars); restore never replaces it |
| `sqlite-restore-readback-mismatch` | The installed database did not read back as the backup's publication; not success (report it) |
| `sqlite-backup-io-failed: <errno>`, `sqlite-restore-io-failed: <errno>`, `sqlite-upgrade-io-failed: <errno>`, `sqlite-cleanup-io-failed: <errno>` | A filesystem operation failed (for example `EACCES`) |
| `local-durability-failed`, `local-durability-unavailable` | A file or directory sync failed or is unsupported; the operation is not reported as successful |

Errors carry no paths, SQL or driver text. Status tools report an unusable
graph as a status row with `error` set, so one graph never fails an
all-visible status call. A missing source root is reported only after the
database, lock and reconciliation checks, so an uninitialized graph reports
`graph-database-not-initialized` first.

## Recovery

Initialization is crash-safe. A killed `ops sqlite-init` either leaves no
final database, and the next run initializes, or leaves a complete one, and the
next run reports `already-current`. Either way it may leave an orphan
`.<graph_id>.sqlite3.init-<random>` file, possibly with `-wal`/`-shm`
sidecars, in the graph store directory. Use `ops sqlite-cleanup` (State
cleanup) to remove orphans. It holds the graph's lock and removes only
provably stale or partial ones. Do not delete them by hand. Never open an
orphan with SQLite: an orphan left after the install step is a second hard
link to the live database, and a SQLite client opening it would use a
different `-wal`/`-shm` pair.

A final database that RepoMap refuses as `graph-database-unrecognized` is never
deleted or reinitialized automatically, because it may hold user state. This
includes a 0-byte or partial file left by an interrupted initialization before
this change. To recover:

1. Stop every RepoMap process that uses the home (`mcp serve`,
   `ops refresh-graph`, `ops sqlite-init`).
2. Move the database file **together with** its `-wal` and `-shm` sidecars, if
   present, into a quarantine directory outside the graph store. Never move or
   delete a sidecar on its own.
3. Rerun `ops sqlite-init` for the graph, then `ops refresh-graph`.

Inspect or delete the quarantined files only after confirming that they hold
nothing you need. To go back to a backup instead of reinitializing, run
`ops sqlite-restore` after step 2 (the target is then absent). The same applies
when restore refuses `database sidecars present`: that is a leftover
`-wal`/`-shm`/`-journal` without its database; moving it aside is this same
destructive decision, never automatic.

If `sqlite-init` or `sqlite-restore` reports `local-durability-failed` after
installing the database, the database is complete and valid but its directory
entry may not be durable yet. `ops graphs --check-db` reports it normally; a
rerun reports `already-current` (init) or `sqlite-restore-target-exists`
(restore). A killed restore may leave an orphan
`.<graph_id>.sqlite3.restore-<random>` file; `ops sqlite-cleanup` classifies it
like an init orphan, but a recoverable one is recovered only by rerunning
`ops sqlite-restore` from the same backup (see State cleanup), never by
`ops sqlite-init`.

### Interrupted publications

Each refresh arms its retained attempt record
(`<home>/state/portable-publication/sqlite-local/<graph_id>/attempts/*/portable-result.json`,
owner-only) with its publication identity before it writes the database. A
refresh interrupted after COMMIT may or may not have published. Such an attempt
is left unsettled and never reported as failed. The next `ops refresh-graph`
for the graph settles it first, before it looks at the sources:

- If the database shows that attempt's publication as the accepted generation,
  the refresh reports that generation and publishes nothing new. Its stdout is
  the usual success shape, and stderr carries
  `NOTE: sqlite-local-attempt-reconciled: accepted generation N was already published; no new generation was published`.
  `ops refresh-enabled` settles each graph the same way and appends
  ` (graph <graph_id>)` to that NOTE.
  The sources do not need to be present. Run the refresh again to publish new
  source state.
- If the database still shows the previous generation, the attempt is recorded
  as failed and the refresh continues normally.

Anything else refuses with `graph-publication-reconciliation-required: <reason>`
and changes nothing. The reasons are:

- a database code such as `graph-database-unrecognized` or
  `graph-database-busy`;
- `publication-identity-conflict`;
- `accepted-generation-mismatch`;
- `attempt-record-invalid`;
- `multiple-unsettled-attempts`;
- `attempt-record-unwritable`.

A busy database clears once the other writer finishes. For the other reasons:

1. Stop every RepoMap process that uses the home.
2. Confirm the accepted state read-only with `repomap_graph_status` over MCP.
   If the database itself is refused, follow the quarantine procedure above.
3. Find the unsettled attempts: the refusal names a reason, not a directory.
   Every `attempts/*/portable-result.json` under
   `state/portable-publication/sqlite-local/<graph_id>/` whose
   `retention_class` is `"publication-reconciliation"` is one; for
   `multiple-unsettled-attempts` there are several. Decide from the accepted
   state which attempt, if any, is the true one; move each other matching
   attempt directory into a quarantine directory. RepoMap never deletes or
   overwrites them automatically.
4. Rerun `ops refresh-graph`.

Local attempts from LOCAL1/LOCAL2 sit in the shared
`state/portable-publication/attempts/` directory. They carry no publication
identity and are never reconciled by a SQLite home. `ops sqlite-cleanup --yes`
removes only those whose record is terminal and expired. An unsettled one is
reported as `legacy-unresolved-attempt` and kept. RepoMap cannot tell which
graph or backend wrote it, so it never guesses. To dispose of it, stop every
RepoMap process, confirm each graph's accepted state read-only, and move the
directory into a quarantine directory outside the home.
