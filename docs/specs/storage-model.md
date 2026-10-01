# RepoMap Storage Model

## Storage Decision

The current reference implementation uses containerized PostgreSQL. Its graph shape
is represented with relational tables and JSONB metadata rather than a dedicated
graph database.

The design keeps JSONL as the raw observation and interchange format.

## Rationale

Postgres is a pragmatic default for RepoMap because the tool must store more
than graph edges. It also needs repository runs, file metadata, extractor
diagnostics, test relationships, coverage relationships, report facts, and
profile metadata.

Postgres provides:

- transactions and constraints;
- migrations and mature backup tooling;
- recursive CTEs for graph traversal;
- JSONB for extractor-specific metadata;
- core relational search operators, including `ILIKE` substring matching;
- a familiar path to dashboards, reports, and service integrations.

Relational PostgreSQL with JSONB currently owns normalized graph and control
data. [ADR 0071](../adr/2026/09/0071-post-promotion-local-server-cloud-architecture.md)
selects SQLite as ordinary Local graph authority and PostgreSQL for Server/Cloud.
Shared graph semantics do not require identical physical schemas. Local starts
with one database per graph, multiple bindings, one serialized publisher, bounded
readers and explicit accepted-generation identity; failures preserve the previous
generation. Ordered/checksummed/drift-refusing/backup-first migration principles
carry across backends.

### SQLite Local first slice (step 4, in progress)

[ADR 0075](../adr/2026/09/0075-sqlite-local-first-slice.md) implements the first
bounded Local loop. A SQLite view and a PostgreSQL view are separately owned
authorities: there is no replication, active-active synchronization, merge or
server fallback between them, and a SQLite graph is never produced by exporting
PostgreSQL rows. The only pre-existing SQLite use,
`artifacts._bundle_stream_links.DiskFamilyLinkValidator`, is a transient
parent-side link-validation scratch database deleted after validation; it is
not graph authority and is not reused.

| Concern | Where it lives |
|---|---|
| Files, raw observations, canonical nodes/edges/evidence and node/edge evidence links of one graph | Local: that graph's `state/sqlite-local/graphs/<graph_id>.sqlite3` |
| Publication runs (portable ids, snapshot vector, family receipts, generations, attempt) and the accepted-publication marker | Local: the same database (`runs`, `accepted_publication`) |
| Graph binding (`graph_id`, `repo1:` identity, `graph:` root, repository name) | Local: the same database (`graph_binding`), checked on every open |
| Schema version, ordered checksums and application id | Local: `local_schema_migrations` (one row per applied catalog migration: v1 `sqlite-local-v1`, v2 `sqlite-local-v2-observation-path-index`), `PRAGMA user_version`, `PRAGMA application_id`; the catalog itself is `storage.sqlite_local.migrations` |
| Physical read indexes | Local: private to the SQLite schema; v2 adds `idx_raw_observations_path_run (path, run_id DESC, ordinal)` for exact-path observation search, with no contract change |
| Control/coordinator state, staging tables, `graph_publication_authority`, database roles, backups, maintenance admission | PostgreSQL Server Engine only |
| Source configuration, privacy and user preferences | The home's `*.rp.toml`/`*.rpl.toml`; never graph facts |

Shared logical contracts, not shared SQL: `graph:<id>` roots and `repo1:<id>`
identities, binding-qualified canonical keys, bundle/receipt/candidate/manifest
ids, family counts, evidence and provenance fields, first/last-seen run
semantics and the page/serializer contracts. Backend-local row ids and run ids
are not shared: SQLite run ids equal accepted generations. PostgreSQL status and
graph summary select repositories by the configured name for pre-identity
restore compatibility; SQLite has no pre-identity state and binds by identity.

## Database Extensions

Current behavior: RepoMap admits no new PostgreSQL extension. Search, ordering, and traversal
semantics rest on the core relational contract; `ILIKE` substring matching
remains the authoritative search behavior.

PostgreSQL's built-in full-text search types and functions are part of that core
contract and are not an extension. They are also not a substitute for substring
search, so their availability does not affect the decision above.

Any future extension — including trigram, vector, hierarchical-path, or
graph-language extensions — must pass the admission and lifecycle policy in
[ADR 0051](../adr/2026/08/0051-postgresql-extension-and-database-capability-architecture.md)
before it may be relied on as a RepoMap-required capability here. Policy
admission is not database enablement.

ADR 0071 requires useful optional Server pgvector before v0.1.0, but satisfies
only ADR 0051 D14 reconsideration, not D15 admission. Exact search anchors recall;
HNSW leads approximate evaluation. Similarity remains heuristic. No Apache AGE
or other graph database is selected; RepoMap owns canonical graph semantics.
JSONB expansion requires named metadata/evidence workloads; identity, authority,
fencing, required constraints and core relations remain relational.

## Data Layers

### Multi-source identity foundation

MS-ID1 keeps PostgreSQL as canonical publication authority without adding a
database migration. Source definitions and graph-source bindings are durable
configuration-owned records. Immutable source snapshots (`snap1:`) and graph
candidates (`cand1:`) are deterministic content/semantic contracts, not graph
rows or accepted publications. Existing graph databases therefore remain
recognizable, replay their existing migration chain unchanged, and retain the
one-source publication contract.

Graph key version 1 and the current repository-scoped uniqueness and foreign
keys are unchanged. MS-FLAKE2 selects an additive namespace encoding rather
than a new persisted family: explicit-binding source-local paths are stored as
`<binding-alias>/<source-relative-path>` in the existing path/key columns.
Aliases cannot contain `/`, and explicit binding graphs use this form from
their first binding. Legacy graph syntax stays on unqualified one-source keys.
The decision is recorded by ADR 0058.

The MS-ID1-FIX1 correction candidate also prevents repository-keyed readback
from selecting one binding. Aggregate storage and refresh status return a
graph-level `multi-source-readback-unsupported` record with no database facts;
graph summary, canonical-file, stored-baseline, drift, CLI, and read-only MCP
paths refuse with the same public-safe classification before database access.
Public graph projections use `[multi-source]`; binding-specific repository
labels remain attributable only inside their explicit binding records. This
does not add a read model, row, migration, writer, or graph-key version.

The MS-ID1-FIX2 candidate also removes source-owned graph configuration values:
multi-binding graphs carry no graph root, extractor profile, or exclusion set,
and graph privacy is public only for an all-public binding inventory. This
closed aggregate representation changes no PostgreSQL row or publication
identity. Its exact containerized PostgreSQL proof was refused before
collection on both permitted executions, so the candidate does not yet satisfy
the then-pending multi-source boundary gate.

The MS-FLAKE2 candidate stores source qualification in existing JSONB metadata:
binding ID, alias, role, revision, snapshot ID, unqualified source-relative path,
and candidate ID. Bounded graph-file readback can enumerate every participant
for a candidate while each record exposes only its owning binding, not another
private binding's metadata. Exact Nix relation evidence carries source/target
binding, cross-binding state, resolution outcome, evidence class, and candidate
identity through the existing canonical edge/evidence families.

MS-FLAKE2-FIX1 also projects those provenance fields in the production
graph-file SQL and routes configured multi-source MCP reads through the same
`graph:<graph-id>` logical repository root used by publication. When effective
graph privacy is non-public, public-safe projections redact every binding's
physical and expanded roots and MCP sanitization treats all of them as private
markers.

No schema migration is necessary: existing JSONB metadata, repository scope,
stage families, accepted tables, and graph-key version 1 already represent the
slice without weakening uniqueness or foreign keys. The unchanged Liquibase
chain remains replay-safe. The pipeline-owned integration owner now asserts
atomic publication, persisted exact generations, replay, prior-generation
preservation, and source-qualified readback, but remains intentionally
unexecuted locally. `source_generation` binds the ordered binding
revision/snapshot vector; snapshot identity transitively binds selection,
ignore policy, paths, digests, sizes, and executable modes. `config_generation`
binds semantic configuration, resolver, extractor capability, canonicalizer,
semantic contract, and quality identities while excluding placement. Existing
receipt, stage, fencing, replay, and reconciliation comparisons therefore bind
all candidate inputs without a new column or authority.

### Portable Artifact And Publication Bundle Seam (STR-SEAM3)

STR-SEAM3 defines a deterministic, database-independent storage seam:
- `ArtifactReference` represents content-addressed artifacts separating semantic
  identity (`sha256:`, size, media type, format, privacy) from physical locators.
- `PortableSnapshotManifest` (`snapmanifest1:`) binds the complete multi-source
  vector and artifact entries.
- `PublicationBundle` (`bundle1:`) encapsulates all seven staging families
  (`files`, `raw_observations`, `canonical_nodes`, `canonical_edges`,
  `canonical_evidence`, `canonical_node_evidence`, `canonical_edge_evidence`)
  as canonical JSONL frames with per-family digests and record counts.
- Current worker-produced bundles declare `row_stage_contract:
  stage-unassigned-v1`, and every row uses `stage-unassigned` as the fixed
  bundle-local placeholder. Only headers without that field select the explicit
  `legacy-absent-v1` decoder, which requires all rows to omit `stage_id`.
  Mixed shapes and every physical stage value are rejected. The sole publisher
  generates PostgreSQL stage identity and replaces the placeholder only inside
  its trusted STR-PUB5 boundary.
- `ArtifactStore` provides store neutrality across `FileSystemArtifactStore`
  (private 0700/0600 roots, atomic rename, fsync, no symlinks) and
  `MemoryArtifactStore` / `FakeObjectStore` with exact monotonic versioning.
- ADR 0061 selects the seam for supported forced-full refresh while PostgreSQL
  remains canonical graph authority and the existing publisher remains the only
  mutator. The final `runs` receipt stores one all-or-none portable binding;
  historical rows retain all-null portable fields. `ingestion_stages` retains
  its existing transient authority instead of duplicating durable portable fields.

`src/test/int/python/repomap_kg/artifacts/seam_pipeline.int.test.py` is the
hosted owner for real-process negotiation, typed failures, deterministic
cancellation, installed authority denial, child crash, parity, replay/conflict,
cleanup, and publisher-validator acceptance/rejection without publication.
TEST-ISO2 keeps it unexecuted locally. STR-PUB5 adds the PostgreSQL owner at
`src/test/int/python/repomap_kg/storage/str_pub5_portable_publication.int.test.py`
and makes the assembled system scenario verify exact portable receipt authority;
both remain hosted-only.

### Raw Observations

Extractor output is written as newline-delimited JSON. Raw observations are
useful for debugging, reproducible tests, and future import/export workflows.

### Normalized Graph

The normalized graph is stored in Postgres. The initial schema should include:

- repositories
- indexing runs
- files
- nodes
- edges
- evidence
- diagnostics
- profiles
- test cases
- coverage targets

## Core Table Sketch

```sql
repositories(
  id,
  name,
  root_path,
  remote_url,
  created_at
)

runs(
  id,
  repository_id,
  git_commit,
  started_at,
  finished_at,
  status,
  tool_versions_json
)

files(
  id,
  repository_id,
  path,
  language,
  role,
  content_hash,
  executable,
  generated,
  metadata_json
)

nodes(
  id,
  repository_id,
  file_id,
  kind,
  name,
  stable_key,
  start_line,
  end_line,
  metadata_json
)

edges(
  id,
  repository_id,
  src_node_id,
  dst_node_id,
  kind,
  stable_key,
  confidence,
  evidence_id,
  metadata_json
)

evidence(
  id,
  repository_id,
  file_id,
  stable_key,
  start_line,
  end_line,
  excerpt,
  extractor,
  metadata_json
)
```

## Migration Strategy

RepoMap uses Liquibase for database versioning and migrations. Migrations
should be explicit, reviewable, and reproducible. Development and CI should be
able to create a fresh database, apply migrations, load fixtures, and run tests.

Migration resources should use this layout:

```text
src/main/resources/rdbms/
  changelog.yaml
  <year>/
    <month>/
      <day>-<counter>-<db id>-<primary action>.sql
```

The root `changelog.yaml` should include the migration tree with `includeAll`.
Migration SQL files should live under folders organized first by year and then
by month, using Liquibase formatted SQL changesets. This keeps the history
browsable while avoiding one large flat migration directory.

The initial migrations are:

```text
src/main/resources/rdbms/2026/06/28-001-core-create_graph_tables.sql
src/main/resources/rdbms/2026/06/28-002-core-add_file_run_tracking.sql
src/main/resources/rdbms/2026/06/28-003-core-add_evidence_stable_key.sql
src/main/resources/rdbms/2026/06/28-004-core-add_edge_stable_key.sql
```

Until the Liquibase CLI is part of the local toolchain, RepoMap includes a
small local schema loader in `repomap_kg.storage`. It discovers the
Liquibase-formatted SQL files from `changelog.yaml` and applies them with
`psql` in disposable Postgres integration tests. This is a test substitute for
local verification, not a replacement for Liquibase as the migration format.

The first ingestion path loads raw discovery `file` observations into Postgres
by creating or updating a repository, recording an indexing run, upserting file
rows with `last_seen_run_id` pointing back to the run that observed them, and
upserting normalized file nodes plus evidence rows with stable keys. Targeted
non-file observations, such as `shell.command`, also persist source nodes,
target nodes, evidence, and stable-keyed relationship edges.
The CLI exposes this path as `repomap-kg storage load-files`, accepting raw
observation JSONL plus repository identity fields and optional `psql` connection
arguments.
LOCAL32 removes the legacy `repomap-kg storage files` command. Configured graph
file nodes can be read back with `repomap-kg ops graph-files --graph
<graph-id>`. The replacement queries canonical nodes and canonical evidence,
uses configured repository names rather than absolute roots, applies filters
before deterministic canonical-key pagination, defaults to 50 records, and
accepts at most 200 records per page. It reports observed and referenced-only
file nodes with bounded candidate and evidence fields; it does not expose raw
metadata, content hashes, internal identifiers, connection values, or roots.
The top-level raw-JSONL `files` command remains separate.
LOCAL35 removes the legacy `repomap-kg storage entrypoints` command without an
alias or fallback. Stored entrypoint-role files can be read back through the
canonical graph-file projection with `repomap-kg ops graph-files --graph
<graph-id> --role entrypoint --observation-state observed`. The top-level
raw-JSONL `entrypoints` command remains separate.
LOCAL38 removes the legacy `repomap-kg storage file-nodes` command without an
alias or fallback. Its co-located legacy node/evidence join is not preserved
as a canonical contract. Use `repomap-kg ops graph-files --graph <graph-id>
[--path <repo-relative-path>]` for bounded canonical file inventory,
`repomap-kg storage file-neighborhood --path <repo-relative-path>` or
`repomap-kg storage neighborhood --node file:<path>` for canonical graph
context, and `repomap-kg storage explain-canonical-edge` for evidence behind a
selected edge. The graph-file `entrypoint` role filter represents observed
inventory classification; it does not assert a cross-language canonical
entrypoint semantic model.
Stored graph nodes can be read back with `repomap-kg storage nodes`, optionally
filtered by canonical node kind, file path, or canonical key, returning
canonical node identity and metadata fields as table or JSON output by default.
Pass `--legacy` for the older observation-derived stable-key shape.
Depth-1 graph neighborhoods can be read back with
`repomap-kg storage neighborhood`, centered on a required canonical key and
optionally filtered to inbound, outbound, or both directions by default. Pass
`--legacy` for the older node-stable-key neighborhood behavior.
Depth-1 file graph neighborhoods can be read back with
`repomap-kg storage file-neighborhood`, which maps a repository-relative path
to the durable canonical `file:<path>` node by default and optionally filters
to inbound, outbound, or both directions. Pass `--legacy` for the older
observation-derived behavior centered on all nodes attached to one stored file
path.
Stored relationship edges can be read back with `repomap-kg storage edges`,
optionally filtered by edge kind, source canonical key, or target canonical key,
returning canonical edge identity and metadata fields as table or JSON output by
default. Pass `--legacy` for the older observation-derived stable-key shape.
Canonical host mutation graph facts can be read back with
`repomap-kg storage host-mutators` by default. The default row view includes
`mutates_host` and `host_mutation_intent` canonical edges, excludes adjacent
`network_intent` and `package_intent` edges, and projects durable fields such
as source_key, edge_kind, target_key, category, graph_key_version,
identity_metadata_hash, confidence, conflict, and run ids plus bounded
tool/command or intent markers when available. It does not include raw command
strings, raw source snippets, raw private paths, or unbounded argv arrays.
`host_mutation_intent` remains source/configuration intent and is not proof that
a shell ran or a host mutation occurred. Pass `--legacy` to preserve the old
observation-derived `storage host-mutators` row shape reconstructed from stored
`shell.host_mutation` nodes, their host target edges, and evidence-backed file
paths. Both raw and storage host-mutator readback support `--category` and
`--tool` filters where their respective data shapes support them honestly.
Raw host-mutator summaries can be read back with
`repomap-kg host-mutators-summary`, returning legacy observation-derived counts
by category and tool with privileged counts. Canonical storage host-mutator
summaries can be read back with `repomap-kg storage host-mutators-summary` by
default. The canonical summary groups by category and edge_kind, includes only
`mutates_host` and `host_mutation_intent`, excludes adjacent `network_intent`
and `package_intent`, and uses explicitly named count fields such as
source_count, canonical_edge_count, privileged_edge_count, intent_edge_count,
and proven_edge_count. It does not reuse the legacy `count` or
`privileged_count` fields. Pass `--legacy` to preserve the old
observation-derived storage summary shape.
Repository storage counts can be read back with `repomap-kg storage summary`,
returning repository identity, latest run id, and counts for runs, files, nodes,
edges, and evidence as table or JSON output.

## Local Development

The default development database should run in a Postgres container. Tests may
use isolated schemas or disposable databases.

Integration tests use the repository-owned container isolation harness, never
host Postgres or a developer database. SQLite boundary integration tests
exercise temporary SQLite inside that isolation; PostgreSQL is needed for
backend parity, not for SQLite storage itself. Hermetic unit owners may use
temporary SQLite files under the test's own temporary directory (a local file,
not a live service); integration success is still claimed only from the
container cohort. SQLite is the accepted Local authority, not merely
a cache; native Local product operation will not require containers.

## STR-WORK4-FIX3 Bundle And Receipt Refinement

Current bundle creation must explicitly select `stage-unassigned-v1`; only the
legacy version-1 decoder accepts an absent stage-contract header. Candidate
semantic identity stays independent of a future physical PostgreSQL stage ID.
Receipt-write absence is valid only for non-completed terminals and is
classified through closed artifact-store codes rather than message matching.
