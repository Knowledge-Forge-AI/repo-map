# ADR 0075: SQLite Local first slice

## Status

Accepted as the REPOMAP-PRODUCT3-SQLITE-LOCAL1 checkpoint. Amended by
REPOMAP-PRODUCT3-SQLITE-LOCAL2-RECOVERY-AUTHORITY1 (layered backend authority,
crash-safe initialization, post-commit process control and read-only refusal;
status 00978) and by REPOMAP-PRODUCT3-SQLITE-LOCAL3-ATTEMPT-RECONCILE1
(commit-outcome truthfulness, retained-attempt reconciliation and bounded
publisher write errors; status 00979) and by
REPOMAP-PRODUCT3-SQLITE-LOCAL4-READ-PARITY1 (the eight ordinary
investigation/summary readers; status 00980) and by
REPOMAP-PRODUCT3-SQLITE-LOCAL5-SOURCE-FEED-PARITY1 (the six source/feed
readers, completing 23 of 23 database reads; status 00981) and by
REPOMAP-PRODUCT3-SQLITE-LOCAL6-OPS-DRIVERFREE1 (the Local operator workflow,
the final direct-only coordinator disposition and Psycopg-free SQLite startup;
status 00982) and by REPOMAP-PRODUCT3-SQLITE-LOCAL7-BACKUP-DURABILITY1
(publication-aware backup/export, no-clobber restore and filesystem durability;
status 00983) and by REPOMAP-PRODUCT3-SQLITE-LOCAL8-MIGRATION1 (the ordered,
checksummed migration catalog and the first backup-first forward migration,
v1 -> v2; status 00984) and by REPOMAP-PRODUCT3-SQLITE-LOCAL9-STATE-HYGIENE1
(conservative Local state cleanup, current state-directory durability and the
retention layout `state` name check; status 00985) and by
REPOMAP-PRODUCT3-SQLITE-LOCAL10-PORTABLE-LOCKING1 (one platform-neutral graph
lock owner, the mutation `state/` integrity rule and corrected orphan recovery;
status 00986) and by REPOMAP-PRODUCT3-SQLITE-LOCAL11-PACKAGE-SPLIT1 (a base
distribution without Psycopg, the `postgres` extra for the Server Engine and
reviewed wheel/sdist candidates; status 00987). Product step 4 is
manager-accepted on LOCAL1–LOCAL11 and the attended native macOS arm64
installed-wheel run (recorded by REPOMAP-PRODUCT4-PRESTAGING-DEBT-CLOSE1;
status 00988). That acceptance excludes Windows-native Local mutation and
distribution. This ADR does not reopen ADR 0071's product direction.

## Date

2026-09-29

## Context

ADR 0071 selects SQLite as ordinary Local graph authority and defers the
transaction, recovery, reader, read-store, migration and packaging decisions
to later slices. Step 3 left logical graph selection neutral (`GraphSelection`)
but config parsing, the store factories and publication PostgreSQL-typed. The
portable semantic worker is already database-independent (its import guard
denies `sqlite3` and `psycopg`), and the parent validates a seven-family
logical bundle before the sole PostgreSQL staged publisher consumes it.

The runtime floor verified for this slice: CPython 3.13 with SQLite 3.50.4 on
the development host; the containerized integration run records the sandbox
runtime in the phase evidence. The project requires Python 3.12 or newer.

## Decision

### Backend selection

A home selects one backend with a top-level `[storage] backend`. There is no
per-graph backend and no plugin registry.

Layered homes follow one source-owned rule
(`ops.config_storage.merge_storage_declarations`). The home's files load in the
existing order: `*.rp.toml` sorted by name, then `*.rpl.toml` sorted by name.

- The **first file** is the base, and it fixes the backend. An explicit
  `[storage]` table sets it; with no table, the backend is `postgresql`. A home
  whose only file is a `*.rpl.toml` uses that file as its base.
- A **later file** may omit `[storage]` and inherit the base backend, or repeat
  the same backend explicitly. Repeating `postgresql` over an implicit base is
  the same backend.
- A later file without `[storage]` that carries PostgreSQL-only sections
  (`[postgres]`, `[runtime]`) declares `postgresql` implicitly.
- Any other declaration is refused with `storage-backend-conflict`. It never
  switches the home in either direction. Only the base table reaches the merged
  payload, so routing and both loaders see the base backend. Overlay tables are
  validated with source-prefixed paths.

A home without `[storage]` keeps its PostgreSQL meaning when a SQLite overlay
appears. Under a PostgreSQL base it routes as PostgreSQL and refuses with the
conflict before any PostgreSQL or SQLite work. A SQLite file that sorts ahead
of a setup-owned `repomap.rpl.toml`, which carries `[postgres]`, becomes the
base, but that PostgreSQL file then conflicts, so the home still refuses with
`storage-backend-conflict`. The rule is positional: a SQLite home must declare
SQLite in its first file, which is `repomap.rp.toml` in the documented shape.

`ops.config_local.LocalSqliteConfig` carries the neutral registry fields of
`OpsConfig` and nothing PostgreSQL-specific. `[postgres]`, `[runtime]` and a
per-graph `database` are refused in a SQLite home. `OpsConfig` and its
PostgreSQL loaders are unchanged except that they refuse a SQLite home
(`sqlite-local-home-requires-local-command`) before deriving any PostgreSQL
value. Only SQLite-capable entry points use the registry loaders: MCP config
loading, server-memory reads, `ops refresh-graph` direct mode and
`ops sqlite-init`. Graph selection accepts a `GraphRegistryConfig` protocol.

### Storage placement and schema

Each graph owns `<control root>/state/sqlite-local/graphs/<graph_id>.sqlite3`
(0600, in a 0700 owner-checked directory, never overlapping a source root).
One database holds one logical graph with one or more source bindings.

Schema v1 is logical, not a copy of the PostgreSQL physical schema: STRICT
tables for the graph binding, runs, the accepted-publication marker, files,
raw observations, canonical nodes/edges/evidence and both link families. It is
created only by explicit `ops sqlite-init`. `local_schema_migrations` records
`(version, name, checksum)`, and `PRAGMA application_id`/`user_version`
identify the file. Every open verifies the ledger, the application id, a digest
of the live schema objects and the bound graph identity. Unknown, future,
drifted, foreign or non-database files are refused and never reinitialized.
Since LOCAL8 the schema is an ordered, checksummed migration catalog (v1, v2)
and a fresh database is created at the current version by applying every
migration in order; an older known version is `schema-behind` and changes only
through the explicit, backup-first `ops sqlite-upgrade` (see Forward schema
migration).

Initialization never creates the final path before the database is complete.
Under the publisher lock it:

1. creates a uniquely named sibling `.<graph_id>.sqlite3.init-<random>` file
   (`O_EXCL|O_NOFOLLOW`, 0600) on the same filesystem;
2. applies the ledger, every catalog migration in order, one ledger row per
   migration, the binding, application id and user version there in one
   transaction;
3. runs `wal_checkpoint(TRUNCATE)` (it must report `(0, 0, 0)`), closes it and
   revalidates it as a current, WAL, correctly bound database;
4. removes its empty sidecars and fsyncs it;
5. installs it with `link(2)`, which fails with `EEXIST` rather than
   overwriting, then removes the temporary name and fsyncs the directory.

An existing target is validated (`already-current`) or refused. It is never
replaced, deleted or reinitialized. A store that cannot hard-link (`EPERM`,
`ENOTSUP`/`EOPNOTSUPP`, `EXDEV`, `EMLINK`) refuses with
`graph-database-unavailable`; there is deliberately no `rename`/`replace`
fallback. A catchable failure removes only that attempt's temporary file and its
sidecars. A crash can leave an orphan `.init-*` file:

- before the link, the final path stays absent and a retry initializes;
- between the link and the unlink, the orphan is a second hard link to the
  complete final database, and a retry reports `already-current`.

Orphans are not swept automatically. Unrecognized final files, such as a 0-byte
file from before this change, are never deleted automatically, because they may
hold user state. The recovery procedure is in `docs/ops/sqlite-local.md`.

### Transactions and journal

Connections use `sqlite3` with `autocommit=True`, so the module never opens an
implicit transaction. The writer uses `BEGIN IMMEDIATE`, `foreign_keys=ON` and
`synchronous=FULL`; nothing weakens durability for speed.

Journal mode is WAL, set once at initialization (it is persistent) and
verified on every open. WAL lets readers keep a committed snapshot while a
publication commits and lets a read-only reader open the database after a
writer is killed before commit. WAL requires one host and a local filesystem;
its `-wal`/`-shm` sidecars belong to the database and must never be copied or
removed independently of it. Automatic checkpointing stays at the default.
A rollback journal was rejected: after a writer crash a read-only reader
cannot recover a hot journal.

### Publication

The portable path is shared, not duplicated: `ops.portable_refresh` exposes
the capture, parent validation and portable-binding helpers used by both the
PostgreSQL route (unchanged order) and `ops.local_refresh`. The SQLite
publisher (`storage.sqlite_local.publisher`) consumes the validated family
spools and never calls the PostgreSQL publisher or reads PostgreSQL.

One publisher per graph holds the graph's exclusive, non-blocking lock on a
sibling `.publish.lock` for the whole attempt (POSIX `flock` since LOCAL1,
through the platform-neutral owner since LOCAL10; see Portable graph locking);
a second attempt refuses immediately (`graph-publication-in-progress`). The accepted generation read at attempt
start fences the commit (`accepted-generation-advanced`). Rows are staged in
connection-local TEMP tables and checked (identity conflicts, raw ordinal
bound) before the write transaction. One `BEGIN IMMEDIATE` transaction then
inserts the run, applies the seven families with PostgreSQL's logical merge
rules and reference guards, updates the graph binding's repository name and
advances the accepted marker. Readers see the previous or the next
generation, never a mix. A failure before `COMMIT` leaves the previous
generation; a failed first publication leaves no accepted generation. SQLite
run ids equal accepted generations.

Commit outcome (LOCAL3). Every exception leaving the publisher carries exactly
one outcome:

- **Not committed** (`is_not_committed`): `COMMIT` was never attempted, so the
  accepted generation is unchanged.
- **Commit unknown** (`is_commit_unknown`): `COMMIT` was attempted and no clean
  readback positively proved this publication. This covers a readback that
  raises, is interrupted, or shows another generation or identity. A readback
  error is never a "not committed" answer.

Process-control exceptions (`KeyboardInterrupt`, `SystemExit` and other
non-`Exception` types) always propagate and never become success. An ordinary
exception after `COMMIT` was attempted returns success only when the accepted
marker shows the expected next generation with this attempt's bundle id, job id
and attempt number. After `COMMIT` was attempted nothing is rolled back or
rewritten. An open transaction left by a failed `COMMIT` holds only uncommitted
work and is discarded before readback. A failing cleanup `ROLLBACK` never
replaces the original error.

Raw `sqlite3` errors raised by the publisher become bounded `LocalStoreError`
codes through the connection classifier (busy/locked, read-only, unavailable,
unrecognized), plus two write classes:

- constraint and data errors are `graph-publication-rejected`;
- programming and interface errors are `graph-publication-internal-error`.

No SQL, path or driver text is carried. After an attempted `COMMIT`, a
classified error is commit-unknown (`<code>: publication outcome unknown`).

### Retained-attempt reconciliation (LOCAL3)

Local attempts reuse the existing owner-only portable retention record
(`portable-result.json`) in one directory per graph,
`state/portable-publication/sqlite-local/<graph_id>/attempts/`, with every
level owner-only. The PostgreSQL route's shared `attempts/` directory is
unchanged. No second journal exists. After parent validation and before the
publisher is entered, Local refresh atomically adds one
`sqlite_local_publication` block to the record: graph id, expected generation,
bundle id, job id and attempt. The job id is unique per invocation.

Refresh settles the attempt failed only when the publisher proved `COMMIT` was
never attempted, or when a failure happened before the publisher was entered.
Every other failure, including an untagged one, leaves the attempt armed.

Every Local refresh takes the graph's publisher lock and reconciles before any
source-root check, capture or worker. It considers only this graph's directory.
It compares the armed, unsettled record with one read-only snapshot of the
accepted marker (no accepted row counts as generation 0):

| Accepted state | Action |
|---|---|
| expected + 1 with the same bundle, job and attempt | settle `terminal-accepted`; replay the accepted outcome from the database without sources, capture or a new generation; stdout shape unchanged, one stderr NOTE |
| still expected | settle `terminal-failed`; refresh normally |
| unreadable or busy database | refuse `graph-publication-reconciliation-required: <reason>`; nothing is settled, overwritten, deleted or superseded |
| expected + 1 with another identity | refuse, as above |
| another generation | refuse, as above |
| invalid or foreign record | refuse, as above |
| more than one armed record | refuse, as above |
| unwritable settlement | refuse, as above |

An unsettled record without the block is settled failed. Arming precedes the
only publisher call under the same lock, so such an attempt never reached the
publisher. Moving the source-root check after reconciliation makes
`graph-database-not-initialized` outrank a missing source root.

### Reads

`server.sqlite_read_binding` binds a SQLite home. Each store operation opens
the existing file read-only (`Path.as_uri()` plus `mode=ro`; never
`immutable=1`), sets `query_only`, runs one deferred transaction and closes
the connection, so one operation sees one committed generation and nothing
pins WAL checkpoints across calls. Missing files are never created. A write
attempted through such a connection fails with plain `SQLITE_READONLY` (code
8), which maps to the bounded `graph-database-read-only`. Busy/locked,
extended read-only codes (recovery, cantlock, rollback, dbmoved, cantinit,
directory) and other operational errors keep their existing classifications.
No path, SQL or driver text is exposed, and `query_only` and `mode=ro` are
unchanged.

The read matrix is all 23 database-reading tools. The first slice served
nine: the four canonical tools, graph status, refresh status, project summary,
node search and file search. LOCAL4 added eight: legacy `repomap_status`,
observation search, the configured-graph neighborhood, and the Python,
Terraform, OpenAPI, JS-framework and Nix summaries. LOCAL5 added the six
source/feed tools: `repomap_ingested_sources`, `repomap_source_summary`,
`repomap_source_runs`, `repomap_source_feed_items`,
`repomap_explain_source_feed_item` and `repomap_source_references`. The
`unsupported-capability` refusal no longer exists. The two configuration
inventories and the two server-memory file readers do not read a graph
database, and the 27-tool catalog is unchanged. Status tools report an unusable
graph as a status row, like the PostgreSQL owner; legacy `repomap_status` of an
initialized but unpublished graph reports zero counts, as project summary does.
Content tools, now including observation search, the configured neighborhood,
the five summaries and the six source/feed tools, refuse an initialized but
unpublished graph (`graph-publication-absent`) where PostgreSQL returns empty
results.

Each LOCAL4 reader is a named SQLite operation beside the first-slice ones
(`investigation_queries.observation_search`, `summary_queries`,
`api_summary_queries`, `nix_summary_queries`); no PostgreSQL SQL is reused or
translated, and there is no generic SQL layer. The summaries select rows with
case-sensitive SQL (`substr`/`IN`, never SQLite's ASCII-folding `LIKE`) and
evaluate the PostgreSQL builders' JSON predicates in Python through
`storage.sqlite_local.raw_payload`, which reproduces `->`/`->>`,
`COALESCE(x::boolean, false)` with PostgreSQL's boolean spellings (and its
refusal of others), `?`, `LIKE`, C-locale `UPPER`, `jsonb::text` and SQL NULL
semantics under `=`, `<>`, `IN`, `LIKE` and `NOT LIKE`. SQLite JSON1 is not
used: it is a compile option at the 3.37 floor, `->>` needs 3.38, and
`json_extract` returns SQL values that break `->>'x' = 'true'`. The configured
neighborhood makes the same unbounded depth-1 call as PostgreSQL; its
direction check runs before any open.

The source/feed readers (LOCAL5) are named SQLite operations in
`storage.sqlite_local.source_queries` (the source-observation scan, the LEFT
JOIN fan-out, inventory, summary and runs) and `source_feed_queries` (feed
items, references and the item explanation), behind
`SqliteSourceReadStore`, one read transaction per call. They add no schema and
no second source/feed authority. Every field is reconstructed from the accepted
publication: the raw rows whose payload `metadata` carries
`source_id_configured` (the PostgreSQL `source_observations` CTE), and the
canonical nodes, edges, evidence and both link families. They are joined by the
raw `(run_id, ordinal)` identity, which PostgreSQL stores as
`canonical_evidence.raw_observation_id`. Both backends retain every
publication's raw rows and evidence, so the counts are publication-history fan-out
counts on both. The PostgreSQL semantics kept are:

- filters apply before grouping;
- `COUNT(*)` counts over the observation × evidence × node-link (× edge-link)
  fan-out;
- `MIN`/`MAX` ignore NULL and compare text in C byte order, while run byte
  lengths and HTTP statuses compare as `bigint`/`int`;
- `latest_*` is the first element of `ARRAY_AGG(... ORDER BY acquired DESC
  NULLS LAST)`;
- `json_agg(DISTINCT ...)` is sorted;
- `duplicate_identity` defaults to false and `not_fetched` to true, with
  PostgreSQL's boolean spellings;
- the feed-item author, category and link lookups ignore the run filter;
- the explanation's `source` is the newest source overall, optionally the
  requested one, and is not tied to the item. Its `references` are not
  source-filtered.

The readers are source-blind. They never fetch, inspect a source root, read a
retained artifact, refresh or publish, and they expose no feed body. A literal
`"source_id_configured"` pre-filter narrows the raw scan before the exact
decoded check.

Legacy `repomap_status` keeps the routing traced in `mcp_core.storage_connection`:
a `project` present in the legacy JSON registry, the legacy `default_project`,
and explicit `root_path`/`pg_*`/`psql_command` arguments stay on PostgreSQL. Only
a `project` absent from the legacy registry resolves as a graph id, and on a
SQLite home that reads the SQLite graph. A graph id combined with any explicit
connection argument keeps its refusal before config load or any open.

### Declared contract differences

- `graph-publication-absent` (above).
- `database_source` is `sqlite-graph-file`; the redacted `database` display is
  the same `[graph-database]` as PostgreSQL's.
- Run ids and run timestamps are backend-local.
- `execution_route` is `portable-worker-v1` on both backends; the SQLite
  publisher is recorded separately as `sqlite-local-direct-v1`, and its
  publisher-owned `portable_stage_id` is `sqlite-local`.
- PostgreSQL stores metadata as JSONB; parity compares parsed JSON values.
  Observation rows go further: `metadata` and consented `payload` are decoded
  from the `jsonb::text` rendering, so their key order and number spelling
  equal the PostgreSQL readback's.
- Observation search matches the query against the PostgreSQL `jsonb::text`
  rendering of each payload (separators `", "`/`": "`, keys ordered by length
  and then bytes, PostgreSQL string escapes), not the stored compact text.
  Portable bundles exclude floats, so payload numbers are integers; the
  renderer's decimal rules are unit-tested only.
- Ordering equals PostgreSQL under the `C` collation that the maintained
  Server Engine provisions; search and C-locale `UPPER` fold ASCII case only.
- A stored flag that PostgreSQL's `::boolean` cast would reject refuses the
  summary on both backends. The SQLite evaluation order follows the builder's
  textual `AND`/`OR` order; PostgreSQL does not guarantee an order, so a row
  holding such a flag behind a false guard may refuse on one backend only.
- Source/feed ties (LOCAL5). Where the PostgreSQL SQL leaves tied rows
  unordered, SQLite breaks the tie deterministically:
  - `ARRAY_AGG` ties on acquisition time, and evidence and reference rows, by
    raw `(run_id, ordinal)` and then link identity;
  - the explanation `item` by `(graph_key_version, id)`;
  - the explanation `source` by source id.

  Parity is claimed where tied rows are payload-identical, and the same-input
  differential asserts that.
- Source run casts (LOCAL5). `source_runs` casts stored byte lengths and HTTP
  statuses the way `::bigint`/`::int` do for decimal text (surrounding
  whitespace and a sign allowed, range-checked). Other spellings refuse,
  including those PostgreSQL 16 also accepts (underscores, `0x`/`0o`/`0b`).
  Acquisition always writes JSON integers. The PostgreSQL explanation
  materializes its source rows, so a malformed value may refuse there too;
  SQLite does not cast in the explanation. Both residuals need malformed
  metadata.

### Shared source/feed limitations (LOCAL5)

These are not backend differences. Both backends behave the same way, and each
item is reported here, not changed:

- **Publication gap.** Only the explicit source-acquisition code
  (`ops/ingestion`: feed, archive and WARC) writes `source_id_configured` and
  the other `source_*`/`acquisition_*` metadata. Feed acquisition
  (`sources ingest-feed`) retains artifacts without publishing, and a
  configured refresh never writes that metadata, on either backend. So on
  refresh-published graphs the six tools return empty inventories, the
  `source metadata unavailable` summary and so on. The only production route that publishes annotated observations is
  PostgreSQL `storage load-files`. The LOCAL5 evidence therefore publishes real
  offline acquisitions through the production canonicalizer and both production
  publishers. A Local publication route for acquisitions is a separate
  decision.
- **Reference scope.** The maintained summary counts (`link_references`,
  `enclosure_references`) and the feed-item `link_targets` select `references`
  edges whose metadata `scope` is `link` or `enclosure`. The feed extractor
  writes `scope: item` (or `channel`) for item links and enclosures. Real feed
  publications therefore report `0` and `[]` on both backends, while the item's
  references are still returned by `repomap_source_references` and the
  explanation. A comparison-only crafted corpus proves the non-zero path is
  identical on both backends. Changing either side is a PostgreSQL contract
  decision outside this slice.
- **Privacy.** The source tools apply no private-marker sanitization on either
  backend. Paths are artifact-relative (`.repomap/source-artifacts/...`), the
  URL summary is the configured safe summary, credentials are redacted at
  config load, and feed bodies are never returned.
- **Scan cost.** Each source/feed call decodes every raw row that carries the
  literal `source_id_configured` key, and each summary or inventory call loads
  those rows' evidence links. This sits next to the observation-search
  sparse-match scan advisory and is not optimized here.

### Local operator workflow and driver-free startup (LOCAL6)

`ops config-check`, `ops graphs`, `ops refresh-preflight` and
`ops refresh-enabled` join `sqlite-init` and direct `refresh-graph` in the one
SQLite command router. It selects on the raw-TOML backend declaration exactly as
before; a PostgreSQL or unreadable home falls through to the unchanged
PostgreSQL dispatcher and its refusal order. PostgreSQL-only options
(`--psql-command`, telemetry) refuse after selection and before any parse, open
or capture.

- **Status projections.** `config-check` and `graphs` share one backend-neutral
  envelope with PostgreSQL (`ops/_registry_status.py`) and add only
  `storage = {"backend": "sqlite"}` and a `storage_status`. PostgreSQL keys are
  absent rather than invented; PostgreSQL output gains no key (absent `storage`
  still means PostgreSQL, as absent `[storage]` does). Databases display as
  `[graph-database]`/`[private-database]` with `database_source =
  "sqlite-graph-file"`, the read-binding convention.
- **Readiness.** One read-only owner (`ops/local_readiness.py`) classifies each
  configured graph as `not-initialized`, `current` (published or not),
  `unrecognized`, `unavailable` or `invalid-configuration`. It uses the
  maintained reader, which `lstat`s first and opens `mode=ro`; it never takes
  the publisher lock, opens the writer, initializes, reconciles or creates a
  directory. As for every Local read, SQLite may create or keep an existing
  WAL database's `-wal`/`-shm`; the main database bytes are unchanged.
  `immutable=1` stays rejected.
- **Preflight** is the maintained PostgreSQL owner, typed to the neutral
  registry; only its `database` display differs.
- **`refresh-enabled`** (`ops/local_refresh_enabled.py`) runs
  `refresh_local_graph` for each enabled graph in configuration order, each
  with its own lock, reconciliation and publication, and follows the
  PostgreSQL aggregate contract (failure rows continue, an interrupt records
  `cancelled` and stops, `success`/`partial`/`failed`). Failure text is kept
  only for path-free refusals; anything else is category plus exception type.
- **Coordinator mode.** SQLite Local has no durable coordinator. Direct
  serialized refresh is the supported Local baseline, and `refresh-graph --mode
  coordinator` is refused by design (`sqlite-local-refresh-rejects-coordinator-mode`)
  before configuration parse, database open, source capture, worker launch or
  any coordinator import or call, with or without an idempotency key. This
  closes the step-4 coordinator obligation by qualified refusal.
- **Driver-free startup.** The CLI facade resolves the names of the eight
  PostgreSQL-implementation modules (durable coordinator, service package API,
  maintenance admission, release cluster, PostgreSQL publishers and
  `ops.refresh`) on access (`cli/_postgres_facade.py`) instead of at import,
  uncached, so `repomap_kg.cli.X` stays the source object and test patches
  cannot freeze. `cli.main.main` routes SQLite `ops` commands before the
  PostgreSQL dispatcher loads. Two eager edges moved to their psycopg-free
  owners (`server/ops.py` imports `query_refresh_status` from
  `ops._refresh_queries`; `ops/portable_refresh.py` defers the staged publisher
  import behind the same module-level name). A PostgreSQL command whose driver
  is missing exits 1 with `postgresql-driver-unavailable`; nothing is emulated.
  This is runtime import independence, not packaging: `pyproject.toml` still
  declares `psycopg[binary]`. (Superseded by LOCAL11: the base distribution no
  longer declares it; see Distribution packaging.)

### Backup, export and restore (LOCAL7)

`ops sqlite-backup` and `ops sqlite-restore` join the SQLite command router
beside `sqlite-init`; like it they always route there and refuse a PostgreSQL
home (`sqlite-local-home-required`) before any filesystem or database action.
Both are source-blind (no source root is checked or read, no worker, network,
PostgreSQL or container path) and driver-free.

- **Artifact.** A backup is one directory holding exactly `graph.sqlite3` (a
  self-contained, checkpointed, sidecar-free, WAL-marked snapshot, `0600`) and
  `manifest.json` (canonical JSON: sorted keys, compact, one trailing newline,
  `0600`), in a directory the command creates `0700` when the output is
  absent; a pre-existing empty operator directory keeps its own mode and is
  neither changed nor checked. The manifest binds `format =
  "repomap-sqlite-local-backup"`, `manifest_version = 1`, `created_at` (UTC),
  the graph binding (`graph_id`, `repository_identity`, `root_path =
  "graph:<id>"`), the SQLite `application_id`, `user_version`, schema name and
  checksum, the exact accepted publication (`accepted`, `generation`, `run_id`,
  `publication_bundle_id`, `publication_job_id`, `publication_attempt` and the
  accepted run's `privacy`; all `null` with `accepted = false` for an
  unpublished graph) and the database byte length and SHA-256. It records no
  source root, home, output or other filesystem path, environment value,
  PostgreSQL metadata or payload body. It is evidence about the artifact, never
  a new accepted publication. The manifest is linked last and is the
  completion marker. The directory is also the Local export format; there is no
  second one. The manifest is shareable apart from its logical ids; the
  database inherits the graph's privacy classification and is not public-safe.
- **Online snapshot.** Under the graph's publisher lock (a held lock refuses
  immediately with `graph-publication-in-progress`, the current non-blocking
  contract) the command opens the live database through the maintained
  read-only reader, reads the accepted publication and, in the same read
  transaction, copies every committed page with SQLite's online backup API in
  one step, WAL-resident frames included. The live main file is never copied
  raw or written. The destination is checkpointed (`TRUNCATE` must return
  `(0,0,0)`), closed, made sidecar-free and fsynced; reopened read-only it must
  show the header WAL mark, the application id, the current schema, the graph
  binding, `integrity_check = ok` and the same accepted publication. Its exact
  bytes are hashed, it is hard-linked (no clobber) to `graph.sqlite3`, the
  directory is fsynced, and then the manifest is written, fsynced, hard-linked
  and the directory fsynced again. The output must be absent or an empty real
  directory whose parent exists, outside the home's `state` tree and every
  configured source root. Any failure, including a catchable interrupt, removes
  only this attempt's names (final names only while they are still this
  attempt's inodes) and an output directory it created; a partial directory is
  never replaced by a later backup.
- **Restore** validates completely before the store is touched: the directory
  holds exactly the two files (no manifest: `sqlite-backup-incomplete`), the
  manifest parses strictly with a supported format and schema and names the
  configured logical graph, the length and SHA-256 match, and the database
  opens with the application id, current schema, binding, a passing
  `integrity_check` and exactly the manifest's publication. Every artifact
  refusal is `sqlite-backup-artifact-invalid: <reason>`. Restore is no-clobber:
  an existing database (valid, empty or unrecognized) or leftover
  `-wal`/`-shm`/`-journal` refuses with `sqlite-restore-target-exists` and is
  left untouched. Under the publisher lock the bytes are copied into a unique
  sibling temporary file while hashed (the copy must still equal the manifest),
  revalidated, fsynced and hard-linked, never overwriting a race winner; the
  store directory is fsynced and success is reported only after a readback
  through the normal read-only path shows the manifest's publication. There is
  no `--force`, deletion, quarantine or in-place replacement: replacing an
  existing or corrupt target is a separate destructive recovery decision.
  Restore does not reclassify privacy (the accepted run's privacy is derived
  from sealed source content, not configuration) and does not touch retained
  attempts. The next refresh reconciles them against the restored marker,
  which is the source of truth, under the unchanged reconciliation rules, and
  publishes the next generation with a new bundle id. Reconciliation is
  automatic only when an armed attempt's publication is the restored accepted
  generation or its expected previous generation is the restored one; an armed
  attempt whose expected generation is ahead of the restored marker, or two or
  more behind it, refuses with `accepted-generation-mismatch` and needs the
  manual Recovery procedure. Publication identity is generation plus bundle
  id, not generation alone.
- **Sealed-artifact reads.** Validation of a backup database and of the backup
  and restore temporary files opens `mode=ro&immutable=1`. That is correct
  only for a closed file no connection writes, and it creates no sidecars in a
  backup directory. Live graph databases keep the `mode=ro`, never
  `immutable=1`, reader rule.

### Filesystem durability (LOCAL7)

One helper (`storage/sqlite_local/durability.py`, POSIX only) fsyncs a
completed regular file before it is published and its directory after the
link, rename or replace that published it. Those syncs are part of the
success result; a failure is `local-durability-unavailable` (not POSIX, no
`O_DIRECTORY`, or `EINVAL`/`ENOTSUP`/`EOPNOTSUPP`: equivalent crash durability
is not claimed) or `local-durability-failed` (the preceding writes are not
confirmed), never suppressed. It applies to: the first no-clobber install of
`sqlite-init` (temporary file, then the store directory and its three parent
levels up to the home before the link, then the store directory after it),
Local retained-attempt record replacement (after the replace, the attempt
directory and every Local retention level above it through `<home>/state`:
`attempts/`, `<graph>/`, `sqlite-local/`, `portable-publication/`, `state/`, so
a namespace created by the first capture is durable too; a record outside that
layout refuses before any write, and the home is not synced, relying on
`sqlite-init` or restore having synced `state/`'s entry, a disclosed
assumption for homes initialized before LOCAL7; the shared PostgreSQL route
keeps its record-file-only default), backup finalization and restore install.
Only the sync after removing an init or restore temporary name is
best-effort; it covers an orphan second link, not the installed database. A
directory sync failure after an install is not success: the installed file is
the complete, validated database, a rerun reports `already-current` (init) or
`sqlite-restore-target-exists` (restore), and readiness classifies it
normally. The primitive is `fsync(2)`; on macOS that is not `F_FULLFSYNC`, so a
drive write cache may still lose acknowledged writes on power loss, matching
SQLite's default `fullfsync=OFF`. The contract is ordered durable writes and
truthful outcomes, not survival of a crash before a sync returns. No other
atomic-file helper in the repository changed.

LOCAL9 adds two things. First, `ops sqlite-cleanup --yes` fsyncs `state/` and
then the home, so an existing home's `state` entry is durable from that
operation on. That is current durability, not proof about the past; nothing
above the home is synced. Second, the Local record guard now names every
resolved level, `state` included, and refuses an attempt directory reached
through a symlink or `..` below the resolved publication root. A symlinked
home, or a symlinked `state` whose target is itself named `state`, still
resolves as before, and init and restore keep resolving their chains the same
way. (Superseded by LOCAL10 for mutation: every Local mutation owner now
refuses a symlinked `state` before any lock or write; the record guard itself
is unchanged.)

### Forward schema migration (LOCAL8)

- **Catalog.** `storage/sqlite_local/migrations.py` is the single schema
  authority: `(version, name, SQL bytes)` with `checksum = "sha256:" +
  sha256(SQL)`, versions 1..n in order. v1 is `sqlite-local-v1` with the
  unchanged LOCAL1 SQL and checksum
  `sha256:7f5b6045f0a46e699d42e8d8e90d51141c5db909b1eecfb3718a69df4825321d`.
  v2 is `sqlite-local-v2-observation-path-index`, checksum
  `sha256:b5518fac02fde45a2a986995e4cf284840ccbee44092a5492c45f04651107489`,
  SQL `CREATE INDEX idx_raw_observations_path_run ON raw_observations(path,
  run_id DESC, ordinal)`. Fresh init applies the whole catalog; there is no
  separate "fresh v2" DDL. Physical schema stays private; no MCP or JSON
  contract version changes.
- **States.** A RepoMap file is `current` or `behind(k)` only when its ledger
  is exactly the catalog's first `k` rows, `user_version = k` and its physical
  schema digest equals an in-memory reference built from the same prefix.
  Behind is never inferred from `user_version` alone. A ledger version or
  `user_version` beyond the catalog is `graph-database-schema-unsupported`;
  every other mismatch (checksum, name, order, gap, missing or extra object,
  `user_version`/ledger disagreement, an empty ledger with the RepoMap
  application id, formerly `unsupported`) is `graph-database-schema-drift`.
  Foreign and non-database files stay `graph-database-unrecognized`. Ordinary
  readers, the writer, publication, refresh and init require exact-current and
  refuse behind with `graph-database-schema-behind`; readiness reports
  `schema-behind` with the accepted generation; backup, restore readback and
  the upgrade command admit exact-behind explicitly.
- **Upgrade.** `ops sqlite-upgrade --graph <id> --backup-output <dir>` is
  SQLite-only, source-blind and driver-free. Under the publisher lock, held
  from the state decision through the final readback: current is
  `already-current` with no backup and the output untouched; drift, future,
  foreign and graph mismatch refuse before any output is touched; behind
  writes a LOCAL7 backup of the unchanged database (manifest `user_version =
  k`), re-verifies it from disk with the restore verifier (it must equal the
  live read), then in one `BEGIN IMMEDIATE` re-checks state and publication,
  applies each pending migration's SQL and ledger row, sets `user_version`,
  requires the result to classify exact-current and commits once. Success
  needs a fresh exact-current readback with the unchanged accepted
  publication (generation, run, bundle, job, attempt, privacy). The backup is
  never deleted; there is no downgrade.
- **Commit outcome.** The LOCAL3 publisher tags are reused
  (`is_not_committed`/`is_commit_unknown`); no recovery framework was added.
  Before COMMIT is attempted every failure rolls back, is bounded and tagged
  not-committed: the database is exact v1 and the verified backup remains.
  After COMMIT is attempted the writer is closed before a positive readback;
  a failed or negative readback is
  `graph-migration-reconciliation-required: schema upgrade outcome unknown`
  tagged commit-unknown, never a definite failure and never followed by a
  restore. Process-control exceptions propagate tagged. Rerun with a **new
  empty** `--backup-output`. If the first run committed, the rerun observes
  exact v2 and reports `already-current`: the new output is neither checked
  for emptiness nor created (its parent and forbidden-location checks still
  apply), and there is no second backup. If it did not commit, the database is still exact
  v1, the first run's verified backup remains in its original output, and the
  rerun writes a fresh backup into the new output and upgrades. Reusing the
  first output while the database is still v1 refuses
  `sqlite-backup-target-exists` (LOCAL9 precision; status 00984 is unchanged).
- **Historical backups.** A manifest records the database's exact version and
  that version's head-migration name and checksum (not a cumulative
  whole-schema checksum); the database must classify as exactly that version
  or restore refuses `schema-mismatch`. Every LOCAL7 manifest is therefore a
  valid v1 manifest. A v1 backup restores exact-behind and is never migrated
  by restore; a v2 backup restores current. Unknown, future and drifted
  backups stay refused; LOCAL7's tamper, hash, application-id, graph,
  integrity and no-clobber checks are unchanged.
- **Workload.** The v2 index serves `observation_search` with `path = ?`: on
  v2 `EXPLAIN QUERY PLAN` of the product SQL is `SEARCH raw_observations
  USING INDEX idx_raw_observations_path_run (path=?)` with no temporary
  B-tree; on v1 the same query sorts with a temporary B-tree.
  `(run_id, ordinal)` is the primary key, so the order is total and results
  are identical before and after; the unfiltered plan is unchanged. No timing
  threshold is part of acceptance.

### State hygiene (LOCAL9)

`ops sqlite-cleanup --graph <id> [--yes]` is SQLite-only, source-blind and
driver-free. Without `--yes` it is a dry run. It lists only three places: the
graph's attempts, the pre-LOCAL3 shared attempts directory and this graph's
names in the graph store. Every existing level of those paths must be a real
directory of this uid (`sqlite-cleanup-layout-invalid` otherwise). The payload
holds counts and bounded codes, never a path, name, token or record content.

- **Attempts.** One read-only classifier covers both the graph-local and the
  shared directory. The only removable class is an owner-valid record that is
  `terminal-accepted` or `terminal-failed`, has an integer `expires_at_epoch`
  that has passed, and whose whole tree holds only real directories and
  single-link owner files. Removal re-checks the record and directory identity
  and uses the existing bounded attempt-root deletion. This is safe whichever
  backend wrote the record, so a shared record is never attributed to a graph.
  An unsettled record (`publication-reconciliation`, armed or not) is always
  preserved. In the shared directory it is `legacy-unresolved-attempt`, manual
  recovery required: pre-LOCAL3 evidence cannot be reconstructed, so it is not
  guessed. In the graph's directory it is `graph-attempt-unsettled`, left to
  refresh reconciliation, which is unchanged. A record-less directory is
  preserved as incomplete. Anything malformed, symlinked, wrong in owner, mode
  or link count, or holding an unexpected node is unsafe.
- **Orphans.** Only `.<graph>.sqlite3.init-<16 hex>` with init's own
  `-wal`/`-shm`, and `.<graph>.sqlite3.restore-<16 hex>` with restore's
  `-wal`/`-shm`/`-journal`, are inventoried, through one pinned store
  descriptor. Every member must be a regular, owner-only, single-link file,
  except an install's second link to the live inode. Classification:
  - beside a current or behind database, every orphan is stale and removed;
    a second link loses only its orphan name;
  - beside an absent database, empty or structurally incomplete ones are
    removed;
  - a group with a non-empty `-wal` or a `-journal`, a base that fails
    immutable inspection, and a sealed database of this graph (recoverable)
    are all preserved;
  - beside any other final state, nothing is removed.

  An orphan is never linked, renamed or adopted. (Corrected by LOCAL10.)
  Rerunning `sqlite-init` creates the normal empty current database and never
  adopts an orphan; an init orphan holds only that empty schema. A recoverable
  restore orphan is recovered by rerunning `sqlite-restore` from the same
  verified backup into the still-absent target (running init first would make
  restore refuse), or it is moved aside for manual forensic handling. After
  either, the next cleanup removes it as stale. The final database is only
  read, and only when an orphan exists.
- **Execution.** A dry run takes an existing lock file read-only with the
  same non-blocking lock (through the LOCAL10 owner), never creates one, and
  writes, removes, chmods and
  syncs nothing (the one exception is the reader's own `-wal`/`-shm`, as for
  `graphs --check-db`). `--yes` holds the publisher lock and inventories
  everything first. Any unsafe item refuses the whole run before anything
  changes. After removal it establishes current durability (Filesystem
  durability above). A failed removal or sync is `incomplete` (exit 1), never
  `cleaned`. Removals are not claimed durable: a lost removal is reclassified
  identically and removed by the next run.
- **Not added.** A recovery journal, force or replace mode, auto-adoption,
  global prune, cross-graph scan, and settlement of shared unresolved records.

### Portable graph locking and the `state/` rule (LOCAL10)

- **One lock owner.** `storage/sqlite_local/locking.py` owns the graph lock.
  `hold_graph_lock` (mutation owners, through `connection.publisher_lock`
  after the private store directory check) creates or validates the sibling
  `.publish.lock` and takes an exclusive, non-blocking interprocess lock;
  `probe_graph_lock` (cleanup dry run) never creates a missing lock file and
  opens an existing one read-only. Contention is `graph-publication-in-progress`;
  the OS releases the lock on close or process death, and the descriptor is
  not inheritable. The lock file must be a regular, single-link file (and on
  POSIX owned by this uid); a mutation sets its mode to `0600`, a probe
  changes nothing. Anything else is the bounded
  `graph-database-unavailable: graph lock file is not private`. Lock-file bytes
  are never read or written and are not publication authority. No production
  Local module imports `fcntl`; `storage/backend_telemetry_events.py` imports it
  inside its PostgreSQL FIFO validation only. Guarded or function-local
  `fcntl` uses in coordinator and service-package modules outside the Local
  closure are unchanged.
- **Backends.** Chosen from `os.name` at call time, lazily imported and never
  from an environment value: POSIX `flock`; Windows `msvcrt.locking` of one
  byte at offset 0 (a region past end of file is allowed, so a zero-length
  lock file locks without a write), with `lstat`/`fstat` identity, type and
  link-count checks instead of `O_NOFOLLOW` and a uid; anything else, or a
  missing primitive, is `local-locking-unavailable` and never runs unlocked.
  The Windows backend is contract-tested with a fake `msvcrt`, not natively
  qualified, and not yet reachable: native Windows mutation refuses the
  `state/` rule first because ownership cannot be verified, and store privacy
  and directory durability remain POSIX-only.
- **Consumers.** Init, refresh (and so `refresh-enabled`), backup, restore,
  upgrade and `sqlite-cleanup --yes` all serialize on the same graph lock.
  Without a graph store directory, cleanup takes no lock and creates none: it
  performs only the qualified attempt actions (each revalidating the exact
  attempt identity), and orphans stay `not-inspected` even if a store appears
  during the run. There is no second cleanup lock.
- **`state/` integrity.** Mutation-owned Local state must be a real,
  owner-controlled `state/` tree under the resolved home. The six mutation
  owners check every existing level from `state` to the paths they use (real
  directory of this uid, database inside `state/sqlite-local/graphs`) before
  any lock or write, refusing `local-state-layout-invalid` (cleanup keeps
  `sqlite-cleanup-layout-invalid` for the same rule). A symlinked home still
  works; read-only config, readiness and MCP reads do not check it. Nothing is
  relinked or migrated. This is a Local-home integrity rule, not a sandbox.

### Distribution packaging (LOCAL11)

- **Base distribution.** `[project].dependencies` is exactly
  `typing-extensions==4.16.0`. It contains no PostgreSQL driver.
  `[project.optional-dependencies].postgres` is exactly
  `psycopg[binary]==3.2.12`, the unchanged pin. Wheel `METADATA` and sdist
  `PKG-INFO` list Psycopg only as `psycopg[binary]==3.2.12; extra == "postgres"`.
- **Why `typing-extensions` stays in base.** No packaged module imports it.
  It is Psycopg's runtime requirement (`python_version < "3.13"`), so moving
  it into `postgres` would leave the Python 3.12 Server image closure
  unpinned. The cost is one pure-Python base dependency. There is no
  `all`/`full` extra.
- **Import census.** Every third-party top-level import in the packaged
  `repomap_kg` modules, including string-literal `import_module` calls, is
  `psycopg`. A unit test pins that set.
- **Server Engine.** `render_server_dockerfile()` installs `".[postgres]"`
  and keeps its Psycopg 3.2.12/libpq 170006 assertions, PostgreSQL 16.14
  clients, packaged migrations, Go helper, entrypoint, labels, and the removal
  of pip, setuptools and ensurepip. The Server never depends on a
  development or test extra for its driver.
- **Repository tooling.** The test runtime image reads base plus `postgres`,
  so its dependency tuple and fingerprint are unchanged. The hosted unit
  lane installs the hash-locked `tools/ci/project_dependencies.lock` closure
  before its editable extras, because unit collection imports Psycopg. The
  lane keeps its no-`postgres`-token topology rule. Development installs add
  `postgres` explicitly.
- **Artifacts.** Both `py3-none-any` wheel and sdist are built with
  `setuptools==83.0.0` in the pinned Python 3.12.13 image, with no network.
  A wheel rebuilt from the sdist matches the original byte for byte. A clean
  Linux container install of the base wheel runs the Local
  CLI/MCP/backup-restore flow with Psycopg absent. The attended native
  macOS run (arm64, Python 3.13.12, host run `host-20260930T202105Z-5jh_qpy_`)
  installed only the reviewed base wheel
  (`15a58dadc3d9d92459e9192010f14ec1bdf1ec6b0fff2ce312c0785dba8f361a`) and
  `typing_extensions` into a fresh venv with Psycopg absent before and after.
  Local CLI, direct refresh, stdio MCP, backup, restore and source-blind
  readback passed, and the PostgreSQL-home negative refused as expected. The
  manager accepted it (status 00988). The evidence class is macOS arm64 only.
  Windows Local mutation is not natively qualified, and the generic wheel tag
  does not qualify it.

## Scope and Non-Scope

In scope: the selector, schema v1, explicit init, full refresh, the 23-tool
read matrix, the Local `config-check`/`graphs`/`refresh-preflight`/
`refresh-enabled` workflow, the direct-only coordinator disposition,
Psycopg-free SQLite startup, publication-aware backup/export, no-clobber
restore into an absent target, the Local filesystem durability ordering and
their tests, and (LOCAL8) the ordered migration catalog, exact schema-state
classification, the explicit backup-first `sqlite-upgrade` to schema v2 and
historical-version backup/restore, and (LOCAL9) the conservative
`sqlite-cleanup` of expired terminal attempts and of stale or partial orphan
temporaries, current state-directory durability and the retention `state`
name check, and (LOCAL10) the platform-neutral graph lock owner with its
contract-tested Windows backend and the mutation `state/` integrity rule. Not
in scope: a Local coordinator,
destructive replacement or recovery of an existing or corrupt target, schema
v3+, a downgrade command, automatic migration by init, restore, refresh or
reads, automatic reconciliation of LOCAL1/LOCAL2-era Local attempts in the shared
PostgreSQL-route directory (they carry no publication identity and are no
longer reconciled by a SQLite home; `sqlite-cleanup` removes only their expired
terminal records), deleting or adopting a recoverable or unrecognized orphan
temporary file, a force or replace cleanup mode, native installed-wheel and
store qualification beyond the accepted macOS arm64 installed-wheel run
(LOCAL11 splits the dependency and builds the candidates),
package publication, native non-POSIX lock qualification and non-POSIX store privacy
and durability, macOS `F_FULLFSYNC`, the remaining
PostgreSQL-only `ops` commands on SQLite, replication or synchronization
between backends, and any Server Engine change.

## Rejected Alternatives

- Making `OpsConfig.postgres` optional or inserting a dummy PostgreSQL
  sentinel: every PostgreSQL consumer would silently lose meaning.
- A plugin registry or per-graph backend: no second integration justifies it.
- Importing SQLite state from live PostgreSQL rows: the two views are
  separately owned authorities.
- A rollback journal, `synchronous=OFF` or `immutable=1` readers of a live
  database. (LOCAL7 uses `immutable=1` only for sealed, closed backup and
  restore files.)
- (LOCAL7) Copying the live main file (with or without its sidecars) for a
  backup, a second export format, a restore that overwrites, deletes or
  quarantines an existing target, and deriving restore privacy from
  configuration.
- (LOCAL10) A third-party locking dependency, `ctypes` `LockFileEx` (the stdlib
  `msvcrt` path already used by the repository's other Windows lock sites
  suffices), writing a byte into the lock file to make Windows locking work, a
  public or environment-selected backend flag, a second cleanup lock, creating
  a store or lock file only to satisfy locking, and automatically relinking or
  migrating a symlinked `state`.

## Consequences

Local users can index and read a graph with no PostgreSQL, container or server.
PostgreSQL behavior, catalog and refusal order are unchanged. Since LOCAL6
the SQLite commands, `--help`, `--version` and `mcp serve` start without
importing the PostgreSQL driver; a home whose configuration cannot be read,
a bare `repomap-kg` and every PostgreSQL-only command still reach the
PostgreSQL dispatcher and report `postgresql-driver-unavailable` without it.

This decision is wrong if any of the following holds: same-input parity finds
a difference outside the declared list; a read-only WAL reader cannot open
after a killed writer on a supported runtime; the runtime SQLite is older than
3.37 (STRICT); the portable worker's import closure reaches
`storage.sqlite_local`; or the PostgreSQL route's order or refusals change.
Since LOCAL2 it is also wrong if any of the following holds:

- a later overlay can switch a home's backend, including an implicit PostgreSQL
  base under a SQLite overlay;
- the no-clobber install replaces an existing target;
- a supported local store cannot hard-link within the graph store directory;
- a process-control exception after `COMMIT` yields a success result;
- a read-only write refusal is reported as unavailability, or the read-only
  discriminator weakens `query_only` or `mode=ro`.

Since LOCAL3 it is also wrong if any of the following holds:

- a publication whose `COMMIT` may have succeeded is settled terminal-failed;
- reconciliation publishes a new generation for an attempt that is already
  accepted, or needs source roots to acknowledge it;
- an ambiguous state is guessed, overwritten or settled instead of refused;
- a failing `ROLLBACK` hides the original publication failure;
- raw `sqlite3` text, SQL or a path escapes a Local write error;
- a publication job id repeats across Local invocations, which would make an
  identity match a false positive.

Since LOCAL4 it is also wrong if any of the following holds:

- a same-input PostgreSQL comparison of any of the eight LOCAL4 readers differs
  outside the declared list, including key order or number spelling of an
  observation row;
- a summary counts a row whose predicate operand is SQL NULL under `<>`,
  `NOT LIKE` or `IN`, or matches a kind by SQLite's case-folding `LIKE`;
- observation search matches the stored compact text instead of `jsonb::text`,
  or `include_raw` adds `payload` without consent;
- legacy `repomap_status` reinterprets a legacy project, the legacy default or
  explicit PostgreSQL arguments as a SQLite read;
- a source/feed tool reaches a database open on a SQLite home (superseded by
  LOCAL5, which serves them).

Since LOCAL5 it is also wrong if any of the following holds:

- a same-input PostgreSQL comparison of any source/feed operation differs
  outside the declared list: identity, order, counts, NULL placement, defaults,
  evidence, references or privacy fields;
- a source/feed read needs a field that schema v1's raw rows and canonical
  tables cannot supply, or a second source/feed store appears;
- a source/feed read fetches, inspects a source root or retained artifact,
  publishes, or falls back to PostgreSQL;
- validation or graph visibility is decided after a SQLite open.

Since LOCAL6 it is also wrong if any of the following holds:

- a SQLite `config-check` or `graphs`, with or without `--check-db`, creates or
  changes anything other than an existing database's own `-wal`/`-shm`: a
  database, directory, lock, init file or the main database bytes;
- the base form (no `--check-db`) opens a database or reads graph-root content;
- `refresh-enabled` refreshes a disabled graph, reaches maintenance admission,
  a coordinator or PostgreSQL, or one graph's failure changes another graph's
  accepted state;
- the coordinator refusal parses configuration, opens a database, captures
  sources, launches a worker or imports the coordinator implementation;
- a qualified SQLite command imports Psycopg when the driver family is
  unavailable, or a facade name is not identical to its source object;
- PostgreSQL `config-check`, `graphs`, `refresh-preflight` or `refresh-enabled`
  output changes.

Since LOCAL7 it is also wrong if any of the following holds:

- a completed backup's manifest does not name the exact accepted generation
  and bundle id held by its database bytes, or a generation still in the live
  WAL is missing from the snapshot;
- a backup writes the live database, succeeds while its snapshot disagrees
  with the live read, or leaves a completed `manifest.json` after any failure;
- a tampered, incomplete, foreign or incompatible artifact creates or changes
  anything under the graph store;
- restore replaces, deletes or quarantines an existing target or a race
  winner, or reports success before the directory sync and readback;
- a success is reported after a failed file or directory sync on init, backup,
  restore or Local attempt-record replacement, or the PostgreSQL route's record
  replacement starts syncing directories;
- a backup or restore reads a source root, launches a worker, touches the
  network, PostgreSQL or a container, or imports Psycopg;
- a manifest, JSON payload or refusal carries a filesystem path, source root,
  environment value or payload body.

Since LOCAL8 it is also wrong if any of the following holds:

- the v1 name, SQL bytes, checksum or physical schema differ from the LOCAL7
  checkpoint, or the catalog is not strictly ordered and checksummed;
- a database classifies `behind` without the exact ledger prefix,
  `user_version` and physical digest (for example a v2 index on a v1 ledger,
  or `user_version = 1` over a v2 ledger), or a future version is not refused;
- any schema object, ledger row or `user_version` change is visible before a
  backup that the restore verifier accepts, or a pre-COMMIT failure leaves any
  part of v2;
- the accepted generation, run or bundle differs across an upgrade;
- `sqlite-init`, `sqlite-restore`, refresh or any read yields v2 from a v1
  database without `ops sqlite-upgrade`;
- a post-COMMIT readback failure is reported as a definite failure or
  triggers a restore;
- the exact-path observation-search SQL on v2 does not use
  `idx_raw_observations_path_run` or needs a temporary B-tree, or any
  observation, summary, source or status read differs across the upgrade;
- the historical-catalog seam is reachable from production code.

Since LOCAL9 it is also wrong if any of the following holds:

- `sqlite-cleanup --yes` deletes, marks or settles an unsettled or record-less
  attempt, attributes a shared attempt to a graph, or removes anything while
  an unsafe item exists;
- any cleanup path can unlink or replace the final database, its sidecars or
  lock, another graph's names, a name outside the two attempt parents and the
  graph store, or a second link to an inode other than the live database's;
- a recoverable, unrecognized or live-WAL orphan beside an absent database is
  removed, or an orphan is linked, renamed or adopted into the final path;
- a dry run creates the lock file, chmods, syncs or changes any byte other
  than the live database's own `-wal`/`-shm`;
- `durability: "established"` is reported without both the `state/` and home
  syncs returning, or anything above the home is synced;
- a cleanup payload or refusal carries a path, entry name or token;
- the retention guard accepts a record whose resolved chain does not name
  `state`, or one reached through a symlink below the publication root, or
  graph-local reconciliation, the PostgreSQL route or its record replacement
  changes.

Since LOCAL10 it is also wrong if any of the following holds:

- importing any `storage.sqlite_local` module attempts `fcntl`, or a Local
  production module imports `fcntl` outside the POSIX backend's lazy load;
- two processes hold one graph lock at once, a lock survives its holder's exit
  or SIGKILL, or an exec'd child spawned under the lock keeps it after the
  holder exits;
- a dry run creates, writes or chmods the lock file, or the Windows algorithm
  writes any lock-file byte;
- a Local mutation owner mutates through a symlinked `state` (including one
  whose target is named `state`), or a read-only path refuses only because
  `state` is a symlink;
- cleanup inspects or removes an orphan when the store was absent at its lock
  decision;
- backend selection depends on an environment value, or an unsupported
  platform runs unlocked;
- any SQLite read, generation, bundle, schema v2, backup or restore format,
  source or feed behavior, or PostgreSQL behavior changes.

Since LOCAL11 it is also wrong if any of the following holds:

- a base (no extra) install of the wheel installs or imports Psycopg, or any
  Local CLI, MCP, backup or restore path needs it;
- wheel `METADATA` and sdist `PKG-INFO` disagree on base dependencies or the
  `postgres` extra, or Psycopg appears without `extra == "postgres"`;
- the Server image obtains Psycopg other than through the `postgres` extra,
  or loses its Psycopg/libpq, PostgreSQL client, migration or Go helper checks;
- a wheel rebuilt from the sdist differs in member set, dependency metadata or
  migration resources;
- an artifact contains a host path, checkout-only file, test runtime artifact
  or secret.
