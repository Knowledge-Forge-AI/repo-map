# ADR 0005: Canonical Storage DDL, Raw Observation Retention, and Dual-Write Plan

## Status

Accepted

## Date

2026-06-29

## Context

ADR 0001 accepts the long-term distinction between raw observations, evidence
records, canonical nodes, and canonical edges. ADR 0002 accepts graph key
version 1, canonical key grammar, and the canonical relationship vocabulary.
ADR 0003 accepts the storage transition strategy: canonicalization is a tested
pure layer before Postgres storage changes, and canonical graph storage is
introduced alongside the current observation-derived storage. ADR 0004 accepts
the in-memory canonicalizer contract and golden fixture strategy.

Phase A and Phase B now provide a pure `CanonicalizationResult` containing a
`CanonicalGraph`, diagnostics, canonical nodes, canonical edges, canonical
evidence records, node evidence links, and edge evidence links. Phase C is the
first phase that may plan Postgres storage for that output.

This ADR is a Phase C plan only. It does not authorize implementation in this
change.

## Decision

RepoMap will add raw observation retention and canonical graph tables as an
additive storage layer. Existing observation-derived tables remain in place and
existing commands keep their current behavior during Phase C.

The canonical storage shape is:

- `raw_observations`
- `canonical_nodes`
- `canonical_edges`
- `canonical_evidence`
- `canonical_node_evidence`
- `canonical_edge_evidence`

`canonical_evidence` is included because ADR 0001, ADR 0003, and ADR 0004 treat
evidence records as first-class provenance records. The node and edge evidence
join tables link canonical facts to those evidence records.

Phase C starts with DDL and a canonical loader path that loads from
`CanonicalizationResult`. `repomap-kg storage load-files` must not change its
public output or current readback semantics until integration tests prove the
canonical write path is compatible. A developer-facing
`repomap-kg storage load-canonical` command may be added first to exercise the
canonical tables without changing current storage reads. Only after that path
passes integration tests should `storage load-files` dual-write current rows
and canonical rows.

No public canonical readback command is required in Phase C. Canonical readback
and query migration are Phase D or later concerns unless a later ADR narrows
that boundary.

## Raw Observation Retention

`raw_observations` is the replay source of truth. JSONL artifacts may still be
kept externally for debugging or export, but canonical replay uses this table.

### `raw_observations`

```sql
CREATE TABLE raw_observations (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL
        REFERENCES repositories(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL
        REFERENCES runs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    path TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, ordinal),
    CHECK (ordinal >= 0),
    CHECK (schema_version > 0),
    CHECK (payload_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX idx_raw_observations_repository_run
    ON raw_observations(repository_id, run_id, ordinal);

CREATE INDEX idx_raw_observations_kind
    ON raw_observations(repository_id, kind);

CREATE INDEX idx_raw_observations_payload_hash
    ON raw_observations(repository_id, payload_hash);
```

### Ordinal Policy

`ordinal` is zero-based and is assigned from the validated raw observation JSONL
order supplied to the storage load. It is stable only within a run. It is never
part of canonical node or edge identity.

`UNIQUE (run_id, ordinal)` is the idempotence key for raw observation retention.
If a loader retries an insert for the same run and ordinal, the existing
`payload_hash` must match. A mismatch is a load error because it means two
different observations are trying to occupy the same run position.

### Payload Hash Policy

`payload_hash` is the lowercase SHA-256 digest of the deterministic JSON
serialization of the validated raw observation payload:

- sorted JSON object keys;
- compact separators;
- UTF-8 bytes;
- no dependence on the original JSONL whitespace; and
- no dependence on database-generated ids.

Duplicate payload hashes are allowed across ordinals and runs. The hash is an
audit, replay, and idempotence aid, not a global uniqueness claim.

Malformed JSONL or raw observations that fail the raw observation schema remain
input validation errors and are not stored. Future malformed-input retention
would require a separate rejected-input table or artifact policy.

## Canonical Nodes

`canonical_nodes` stores durable graph entities identified by ADR 0002 canonical
keys.

```sql
CREATE TABLE canonical_nodes (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL
        REFERENCES repositories(id) ON DELETE CASCADE,
    graph_key_version INTEGER NOT NULL,
    canonical_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    display_name TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence TEXT NOT NULL,
    conflict BOOLEAN NOT NULL DEFAULT false,
    first_seen_run_id BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    last_seen_run_id BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repository_id, graph_key_version, canonical_key),
    CHECK (graph_key_version >= 1),
    CHECK (canonical_key <> ''),
    CHECK (kind <> ''),
    CHECK (display_name <> ''),
    CHECK (confidence IN ('manual', 'extracted', 'heuristic', 'unknown'))
);

CREATE INDEX idx_canonical_nodes_kind
    ON canonical_nodes(repository_id, graph_key_version, kind);

CREATE INDEX idx_canonical_nodes_last_seen_run
    ON canonical_nodes(last_seen_run_id);
```

### Canonical Node Uniqueness

Canonical node identity is exactly:

```text
repository_id
graph_key_version
canonical_key
```

`display_name`, `metadata_json`, confidence, conflict state, run ids, and
timestamps are not identity. If metadata changes for the same canonical key, the
loader updates summary fields and `last_seen_run_id`; it does not create a new
node.

The database enforces non-empty keys and graph key version constraints. Full key
grammar validation remains owned by `repomap_kg.graph_keys` before storage.

## Canonical Edges

`canonical_edges` stores durable relationships between canonical nodes.

```sql
CREATE TABLE canonical_edges (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL
        REFERENCES repositories(id) ON DELETE CASCADE,
    graph_key_version INTEGER NOT NULL,
    source_canonical_key TEXT NOT NULL,
    edge_kind TEXT NOT NULL,
    target_canonical_key TEXT NOT NULL,
    identity_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    identity_metadata_hash TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence TEXT NOT NULL,
    conflict BOOLEAN NOT NULL DEFAULT false,
    first_seen_run_id BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    last_seen_run_id BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (
        repository_id,
        graph_key_version,
        source_canonical_key,
        edge_kind,
        target_canonical_key,
        identity_metadata_hash
    ),
    FOREIGN KEY (repository_id, graph_key_version, source_canonical_key)
        REFERENCES canonical_nodes(repository_id, graph_key_version, canonical_key)
        ON DELETE CASCADE,
    FOREIGN KEY (repository_id, graph_key_version, target_canonical_key)
        REFERENCES canonical_nodes(repository_id, graph_key_version, canonical_key)
        ON DELETE CASCADE,
    CHECK (graph_key_version >= 1),
    CHECK (source_canonical_key <> ''),
    CHECK (target_canonical_key <> ''),
    CHECK (identity_metadata_hash ~ '^[0-9a-f]{64}$'),
    CHECK (
        edge_kind IN (
            'defines',
            'executes',
            'sources',
            'reads_env',
            'writes_env',
            'mutates_host',
            'imports',
            'exposes_script',
            'depends_on',
            'wraps',
            'tests'
        )
    ),
    CHECK (confidence IN ('manual', 'extracted', 'heuristic', 'unknown'))
);

CREATE INDEX idx_canonical_edges_source
    ON canonical_edges(repository_id, graph_key_version, source_canonical_key);

CREATE INDEX idx_canonical_edges_target
    ON canonical_edges(repository_id, graph_key_version, target_canonical_key);

CREATE INDEX idx_canonical_edges_kind
    ON canonical_edges(repository_id, graph_key_version, edge_kind);
```

### Canonical Edge Uniqueness

Canonical edge identity is exactly:

```text
repository_id
graph_key_version
source_canonical_key
edge_kind
target_canonical_key
identity_metadata_hash
```

`identity_metadata_hash` is the lowercase SHA-256 digest of deterministic JSON
serialization of `CanonicalEdge.identity_metadata`. Empty identity metadata is
encoded as `{}` and still has a hash. `metadata_json`, confidence, conflict
state, evidence links, run ids, and timestamps are not edge identity.

Multiple evidence records that support the same edge identity collapse onto one
canonical edge. Multiple observations produce additional evidence links, not
duplicate edges.

## Canonical Evidence

`canonical_evidence` stores the storage representation of
`CanonicalEvidence`. It is derived from raw observations by the pure
canonicalizer and keeps selected provenance fields near the graph facts.

```sql
CREATE TABLE canonical_evidence (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL
        REFERENCES repositories(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL
        REFERENCES runs(id) ON DELETE CASCADE,
    graph_key_version INTEGER NOT NULL,
    raw_observation_id BIGINT
        REFERENCES raw_observations(id) ON DELETE SET NULL,
    evidence_key TEXT NOT NULL,
    raw_observation_ordinal INTEGER NOT NULL,
    raw_schema_version INTEGER NOT NULL,
    raw_kind TEXT NOT NULL,
    raw_source_id TEXT NOT NULL,
    path TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    extractor TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    confidence TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, graph_key_version, evidence_key),
    CHECK (graph_key_version >= 1),
    CHECK (evidence_key <> ''),
    CHECK (raw_observation_ordinal >= 0),
    CHECK (raw_schema_version > 0),
    CHECK (
        (start_line IS NULL AND end_line IS NULL)
        OR (
            start_line IS NOT NULL
            AND end_line IS NOT NULL
            AND start_line > 0
            AND end_line >= start_line
        )
    ),
    CHECK (confidence IN ('manual', 'extracted', 'heuristic', 'unknown'))
);

CREATE INDEX idx_canonical_evidence_raw_observation
    ON canonical_evidence(raw_observation_id);

CREATE INDEX idx_canonical_evidence_path
    ON canonical_evidence(repository_id, path);
```

`raw_observation_id` should be populated when the raw observation was retained
in the same database. It remains nullable so imported canonical fixtures or
future external evidence can be represented without fabricating a raw
observation row.

Full raw observation JSON is not duplicated in `canonical_evidence.metadata_json`.
Evidence metadata stores selected explanatory fields from ADR 0004. Source
excerpts remain deferred unless a later ADR defines excerpt retention,
redaction, and size policy.

## Canonical Evidence Join Tables

### `canonical_node_evidence`

```sql
CREATE TABLE canonical_node_evidence (
    canonical_node_id BIGINT NOT NULL
        REFERENCES canonical_nodes(id) ON DELETE CASCADE,
    canonical_evidence_id BIGINT NOT NULL
        REFERENCES canonical_evidence(id) ON DELETE CASCADE,
    link_kind TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (canonical_node_id, canonical_evidence_id, link_kind),
    CHECK (link_kind <> '')
);

CREATE INDEX idx_canonical_node_evidence_evidence
    ON canonical_node_evidence(canonical_evidence_id);
```

### `canonical_edge_evidence`

```sql
CREATE TABLE canonical_edge_evidence (
    canonical_edge_id BIGINT NOT NULL
        REFERENCES canonical_edges(id) ON DELETE CASCADE,
    canonical_evidence_id BIGINT NOT NULL
        REFERENCES canonical_evidence(id) ON DELETE CASCADE,
    link_kind TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (canonical_edge_id, canonical_evidence_id, link_kind),
    CHECK (link_kind <> '')
);

CREATE INDEX idx_canonical_edge_evidence_evidence
    ON canonical_edge_evidence(canonical_evidence_id);
```

Join table rows are appendable support records. They do not change node or edge
identity. One evidence record may support multiple canonical nodes and multiple
canonical edges. A canonical node or canonical edge may have many evidence
records.

## Graph Key Version Columns and Constraints

Canonical storage uses graph key version columns as follows:

- `canonical_nodes.graph_key_version` is required and participates in node
  uniqueness.
- `canonical_edges.graph_key_version` is required and participates in edge
  uniqueness.
- `canonical_evidence.graph_key_version` is required because evidence
  serialization and evidence keys are produced by a specific canonicalizer
  graph version.
- `raw_observations` does not have `graph_key_version`; raw observations are
  graph-version-neutral input and carry `schema_version` instead.
- Join tables do not repeat `graph_key_version`; they inherit it through their
  referenced canonical node, edge, and evidence rows.

Version 1 is the first supported value. `CHECK (graph_key_version >= 1)` keeps
the schema open for future versions, but application code must reject unknown
versions unless a version-specific parser and canonicalizer are installed.

## Loading from `CanonicalizationResult`

Canonical storage loads from the pure `CanonicalizationResult`; it must not
re-run extractor logic or hand-format canonical keys inside storage code.

The load algorithm is:

1. Validate raw observation JSONL into `RawObservation` values.
2. Assign zero-based ordinals in JSONL order.
3. Compute deterministic `payload_hash` values.
4. Run the pure canonicalizer to produce `CanonicalizationResult`.
5. Open one transaction.
6. Upsert `repositories` and create or reuse the target `runs` row according
   to the current storage load policy.
7. Insert `raw_observations` ordered by ordinal. On conflict for
   `(run_id, ordinal)`, require the stored `payload_hash` to match.
8. If `CanonicalizationResult.ok` is false, keep retained raw observations,
   store no canonical graph rows for that result, mark the run failed or return
   a storage error according to the calling command, and include diagnostics in
   the error path. Phase C does not need a diagnostics table unless a later ADR
   adds one.
9. Upsert all `CanonicalNode` rows by
   `(repository_id, graph_key_version, canonical_key)`.
10. Upsert all `CanonicalEdge` rows by canonical edge identity, using
    deterministic `identity_metadata_hash`.
11. Insert or upsert all `CanonicalEvidence` rows by
    `(run_id, graph_key_version, evidence_key)`, linking them to
    `raw_observations` by `(run_id, raw_observation_ordinal)`.
12. Insert node evidence links by resolving `canonical_key` and `evidence_key`.
13. Insert edge evidence links by resolving `edge_key` to canonical edge
    identity and `evidence_key` to canonical evidence.
14. Commit only after raw observations, canonical rows, and joins all satisfy
    constraints.

Canonical storage must treat the in-memory `edge_key` as a deterministic helper
for resolving result links. The durable database edge identity remains
source key, edge kind, target key, graph key version, and identity metadata
hash.

## Compatibility with Observation-Derived Storage

The existing observation-derived tables remain authoritative for current public
storage readback during Phase C:

- `files`
- `nodes`
- `edges`
- `evidence`

Existing storage commands continue to query those tables. Canonical tables are
written alongside them but are not used to change public output until Phase D or
later.

Compatibility rules:

- Existing `stable_key` fields remain observation-derived identity.
- Canonical keys are stored in canonical tables as `canonical_key`,
  `source_canonical_key`, and `target_canonical_key`.
- Current JSON output must not silently replace legacy `stable_key` fields with
  canonical keys.
- `storage summary` continues to report counts for the current public storage
  shape unless a later ADR adds canonical counts.
- Current table output remains unchanged.
- Canonical writes are additive and must not delete or rewrite current rows.

## Load Command Plan

Phase C should add the canonical storage path in two subphases.

### Phase C1: Canonical Loader First

Add a developer-facing command:

```text
repomap-kg storage load-canonical <jsonl_path> \
  --repository-name <name> \
  --root-path <path> \
  [--git-commit <commit>] \
  [--pg-host <host>] \
  [--pg-port <port>] \
  [--pg-user <user>] \
  [--pg-database <database>] \
  [--psql-command <command>] \
  [--json]
```

This command loads `raw_observations` and canonical tables from
`CanonicalizationResult`. It does not write current observation-derived rows.
Its purpose is to test the canonical schema and loader without changing current
storage command behavior.

### Phase C2: Dual-Write `storage load-files`

After C1 integration tests pass, `repomap-kg storage load-files` may dual-write:

1. the current observation-derived rows used by existing readback; and
2. raw observation and canonical rows.

The command name, accepted arguments, exit behavior for current valid inputs,
and user-visible output remain unchanged. JSON output remains:

```json
{"files": 1, "repository_id": 7, "run_id": 11}
```

Canonical write failures during C2 are load failures, not silent partial writes.
The transaction must leave both current and canonical storage in a consistent
state. If compatibility risk remains high, the dual-write call may be guarded by
an internal feature flag during development, but the public command contract
must not require users to opt in with a new flag.

## Existing CLI Commands That Remain Unchanged

The following commands and their existing options remain unchanged in Phase C:

- `repomap-kg --version`
- `repomap-kg discover <root> [--profile <path>] [--jsonl]`
- `repomap-kg files <jsonl_path> [--role <role>] [--language <language>] [--generated include|exclude|only] [--json]`
- `repomap-kg entrypoints <jsonl_path> [--json]`
- `repomap-kg host-mutators <jsonl_path> [--category <category>] [--tool <tool>] [--json]`
- `repomap-kg host-mutators-summary <jsonl_path> [--category <category>] [--tool <tool>] [--json]`
- `repomap-kg identity [--json]`
- `repomap-kg observations normalize <jsonl_path> [--json]`
- `repomap-kg storage load-files <jsonl_path> --repository-name <name> --root-path <path> [--git-commit <commit>] [--pg-host <host>] [--pg-port <port>] [--pg-user <user>] [--pg-database <database>] [--psql-command <command>] [--json]`
- `repomap-kg storage files --root-path <path> [--role <role>] [--language <language>] [--generated include|exclude|only] [--pg-host <host>] [--pg-port <port>] [--pg-user <user>] [--pg-database <database>] [--psql-command <command>] [--json]`
- `repomap-kg storage entrypoints --root-path <path> [--pg-host <host>] [--pg-port <port>] [--pg-user <user>] [--pg-database <database>] [--psql-command <command>] [--json]`
- `repomap-kg storage file-nodes --root-path <path> [--path <file>] [--pg-host <host>] [--pg-port <port>] [--pg-user <user>] [--pg-database <database>] [--psql-command <command>] [--json]`
- `repomap-kg storage nodes --root-path <path> [--kind <kind>] [--path <file>] [--stable-key <key>] [--pg-host <host>] [--pg-port <port>] [--pg-user <user>] [--pg-database <database>] [--psql-command <command>] [--json]`
- `repomap-kg storage neighborhood --root-path <path> --node <stable-key> [--direction both|in|out] [--depth 1] [--pg-host <host>] [--pg-port <port>] [--pg-user <user>] [--pg-database <database>] [--psql-command <command>] [--json]`
- `repomap-kg storage file-neighborhood --root-path <path> --path <file> [--direction both|in|out] [--depth 1] [--pg-host <host>] [--pg-port <port>] [--pg-user <user>] [--pg-database <database>] [--psql-command <command>] [--json]`
- `repomap-kg storage edges --root-path <path> [--kind <kind>] [--source-node <stable-key>] [--target-node <stable-key>] [--pg-host <host>] [--pg-port <port>] [--pg-user <user>] [--pg-database <database>] [--psql-command <command>] [--json]`
- `repomap-kg storage host-mutators --root-path <path> [--category <category>] [--tool <tool>] [--pg-host <host>] [--pg-port <port>] [--pg-user <user>] [--pg-database <database>] [--psql-command <command>] [--json]`
- `repomap-kg storage host-mutators-summary --root-path <path> [--category <category>] [--tool <tool>] [--pg-host <host>] [--pg-port <port>] [--pg-user <user>] [--pg-database <database>] [--psql-command <command>] [--json]`
- `repomap-kg storage summary --root-path <path> [--pg-host <host>] [--pg-port <port>] [--pg-user <user>] [--pg-database <database>] [--psql-command <command>] [--json]`

## New Readback Commands

No new public readback commands are part of Phase C.

The following command names are candidates for Phase D, but this ADR does not
authorize them:

- `repomap-kg storage canonical-nodes`
- `repomap-kg storage canonical-edges`
- `repomap-kg storage canonical-neighborhood`
- `repomap-kg storage explain-canonical-edge`
- `repomap-kg storage replay-canonical`

Phase D must define their exact arguments, output fields, filters, and
compatibility with legacy `stable_key` filters before implementation.

## Migration Ordering

Current migrations stop at:

```text
src/main/resources/rdbms/2026/06/28-004-core-add_edge_stable_key.sql
```

Phase C migrations should be ordered as:

1. `2026/06/<day>-001-core-create_raw_observations.sql`
   - create `raw_observations`;
   - add raw observation indexes;
   - rollback drops indexes then table.
2. `2026/06/<day>-002-core-create_canonical_graph_tables.sql`
   - create `canonical_nodes`;
   - create `canonical_edges`;
   - create `canonical_evidence`;
   - create `canonical_node_evidence`;
   - create `canonical_edge_evidence`;
   - add canonical graph indexes;
   - rollback drops join tables, evidence, edges, and nodes in dependency
     order.
3. Optional `2026/06/<day>-003-core-add_canonical_storage_constraints.sql`
   - only if constraints need to be split for backfill or local Postgres
     compatibility reasons.

No migration should alter or drop current observation-derived tables in Phase C.
`changelog.yaml` continues to use `includeAll` over the migration tree.

## Rollback Strategy

Phase C rollback is additive rollback:

1. Stop calling the canonical loader or disable the internal dual-write path.
2. Keep existing observation-derived storage commands on `files`, `nodes`,
   `edges`, and `evidence`.
3. If a database rollback is required before release, apply Liquibase rollback
   for the canonical tables in reverse migration order.
4. If canonical tables have shipped, do not drop them in a patch release unless
   no released command depends on them. Prefer disabling writes and leaving rows
   inert.
5. Raw observations may be retained even if canonical tables are disabled,
   because they are useful for later replay.

Because canonical tables are additive, rollback must not require destructive
changes to current public storage rows.

## Integration Test Strategy

Phase C implementation must include integration tests before dual-write is
enabled in `storage load-files`.

Required integration coverage:

- applying migrations creates `raw_observations`, `canonical_nodes`,
  `canonical_edges`, `canonical_evidence`, `canonical_node_evidence`, and
  `canonical_edge_evidence`;
- graph key version, confidence, line-span, payload hash, and edge-kind
  constraints reject invalid rows;
- raw observations insert in zero-based ordinal order;
- retrying the same `(run_id, ordinal)` with the same payload hash is
  idempotent;
- retrying the same `(run_id, ordinal)` with a different payload hash fails;
- a golden fixture such as `shell_executes_collapse` loads one canonical edge
  with multiple edge evidence links;
- a fixture with file node evidence loads node evidence links;
- a dynamic placeholder fixture loads `dynamic:*` nodes and edges without
  fabricated precise targets;
- an unsupported future observation is retained in `raw_observations` and does
  not fabricate canonical graph rows;
- C1 `storage load-canonical` writes canonical tables without writing legacy
  `nodes`, `edges`, or `evidence`;
- C2 `storage load-files` writes both current and canonical rows while keeping
  the existing output payload unchanged;
- all existing storage readback commands still pass against the same fixtures;
- replaying retained raw observations for a run produces the same canonical
  node and edge identities as the original load; and
- rollback or disabled dual-write leaves current storage readback working.

Unit tests should cover SQL generation, payload hash computation, canonical
edge identity hash computation, and conflict handling without requiring
Postgres.

## Replay Strategy from `raw_observations`

Replay is based on retained raw observations ordered by `(run_id, ordinal)`.

The replay algorithm is:

1. Select a repository and one or more source runs.
2. Read `payload_json` from `raw_observations` ordered by `run_id, ordinal`.
3. Validate each payload against the current raw observation schema.
4. Run the requested canonicalizer graph key version.
5. Load the resulting `CanonicalizationResult` into canonical tables using the
   same loader used by `storage load-canonical`.
6. Link canonical evidence back to original `raw_observations` rows when
   available.
7. Keep old canonical rows until the replay command or maintenance task has an
   explicit replacement policy.

Phase C should make replay possible and testable through internal loader
functions. A public replay CLI command is deferred until Phase D defines
readback and explain behavior.

Old raw observations can be replayed into newer canonical graph versions only
when a version-specific key parser, builder, and canonicalizer exist. RepoMap
must not rewrite graph key version 1 rows in place to pretend they are graph key
version 2 rows.

## What Phase C Will Not Do

Phase C will not:

- change raw extractors;
- change the raw observation schema except through a separate ADR;
- change ADR 0002 canonical key grammar;
- change Phase A/B canonicalizer behavior except to fix bugs revealed by
  storage tests;
- add parser-backed Python, Nix, or Ruby extraction;
- add graph key version 2;
- change existing public readback output;
- migrate public query semantics to canonical graph identity;
- remove or rename legacy `stable_key` fields;
- drop or replace `files`, `nodes`, `edges`, or `evidence`;
- add MCP support;
- add embeddings or graph visualization;
- add a diagnostics storage table unless a later ADR accepts it; or
- add public canonical readback commands before Phase D defines their contracts.

## Rejected Alternatives

### Replace Current Storage In Place

Rejected. Replacing `nodes`, `edges`, and `evidence` in place would break
existing readback commands and would blur observation-derived identity with
canonical graph identity.

### Store Raw Observation JSON Only in Evidence Metadata

Rejected. Evidence metadata is selected explanatory context. Full raw
observation payloads belong in `raw_observations` so replay does not depend on
edge or node evidence shape.

### Skip `canonical_evidence`

Rejected. Joining canonical nodes and edges directly to `raw_observations`
would lose the evidence record boundary accepted in ADR 0001 and ADR 0004.
Canonical evidence records can support multiple facts and can carry selected
explanatory metadata without duplicating full raw payloads.

### Dual-Write `storage load-files` Before a Canonical Loader Test Path

Rejected for initial Phase C. A separate canonical loader path lets RepoMap test
DDL, retention, constraints, canonical row loading, and replay without changing
the current public storage command surface. `storage load-files` should dual-
write only after those tests pass.

### Add Public Canonical Readback in the Same Slice as DDL

Rejected. Phase C should prove storage correctness first. Canonical readback,
filter names, explain output, and compatibility fields need their own Phase D
contract.

### Make Payload Hash Globally Unique

Rejected. Two observations may legitimately have identical payloads in different
runs or even repeated positions in one run. The hash is for audit and
idempotence checks, not global identity.

### Let the Database Validate Full Canonical Key Grammar

Rejected. Full graph key grammar belongs in `repomap_kg.graph_keys`. Database
constraints enforce coarse safety and relational integrity; application code
performs grammar validation before rows are written.
