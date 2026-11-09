# PostgreSQL Native Lexical Search Operations (`cloe_lexical`)

`cloe ops lexical-build`, `cloe ops lexical-query`, and `cloe ops lexical-revoke`
manage the opt-in derived PostgreSQL lexical search index stored in the dedicated
`cloe_lexical` schema ([ADR 0129](../adr/2026/10/0129-postgresql-native-lexical-search-and-publication-pinning.md),
[specification](../specs/cloe-native-lexical-search-v1.md)).

## Authority, Privacy, and Role Boundaries

1. **Derived, Non-Authoritative Index**: Canonical graph state in `public.*`
   remains the sole repository authority. `cloe_lexical` is a derived,
   revocable index pinned to an accepted canonical run (`run_id`),
   `publication_bundle_id`, `snapshot_manifest_id`, `extraction_receipt_id`,
   `graph_candidate_id`, and `cloe-lexical-policy-v1` policy digest.
2. **Pre-Open P1 Admission**: Only graphs with resolved `public-dev` privacy and
   bindings with resolved `public-dev` privacy and `full-authorized` retention
   are admitted. Private/inherit, metadata-only, ephemeral, email, feed,
   symlink, and unsupported formats are excluded before opening file bytes.
3. **Owner-Only Database Access**: `cloe_lexical` revokes `PUBLIC` and denies
   `repomap_read_status`, `repomap_refresh_publication`, and
   `repomap_coordinator_control`. Ordinary MCP/HTTP graph readback continues to
   operate on `public.*` with limited credentials and never accesses
   `cloe_lexical`.
4. **PostgreSQL Storage Only**: SQLite Local homes refuse `lexical-*` commands
   with `postgres-home-required` before opening any database.

## CLI Workflow

### Build and Activate a Lexical Generation

```bash
cloe ops lexical-build --repo-map-home /path/to/cloe-home \
  --graph <graph-id> \
  --authorize-body \
  --binding <binding-id> \
  --json
```

- Verifies runtime readiness (`cloe-lexical-schema:1`, `pg_catalog.simple`, GIN
  indexes, FTS smoke probe) and resolves the latest completed canonical
  publication fence (`run_id` and receipt bundle).
- Reads the accepted publication's retained ArtifactStore, rather than recapturing
  a current working tree, into bounded 80-line / 8,192-byte chunks
  with deterministic identifier/path alias splitting (`identifier-path-split-v1`),
  populates `cloe_lexical.{generations,documents,chunks,omissions}` in bounded
  transactions of at most256documents or omissions. Each batch checks the owning
  builder, state and wall-clock lease before and after writing, refreshes the
  lease, and commits. Activation verifies counts, receipt and fresh policy before
  atomically flipping `cloe_lexical.authority`. A failed rebuild preserves the
  previous ready generation; cleanup purges only the failed owner's rows.
- Emits a `cloe-ops-lexical-v1` JSON summary (`result: "published"` exits `0`;
  refused/failed exits `1`).

### Query an Active Lexical Generation

```bash
cloe ops lexical-query --repo-map-home /path/to/cloe-home \
  --graph <graph-id> \
  --authorize-body \
  --query "RetrievalExecutionPipeline" \
  --query-style ranked_terms \
  --binding-id <binding-id> \
  --limit 20 \
  --offset 0 \
  --json
```

Supported `--query-style` (`--style`) values:

- `ranked_terms`: `ranked_discovery` over `captured_text` using `pg_catalog.simple`
  weighted `ranked_vector` (`A` path + identifier aliases, `D` normalized chunk text)
  and `ts_rank_cd(..., 32)` with `ts-rank-cd-deterministic-v1` ordering.
- `normalized_phrase`: `ranked_discovery` over `captured_text` using
  `phraseto_tsquery('pg_catalog.simple', ...)` over `phrase_vector` only so
  aliases or path segments never manufacture false phrase adjacency.
- `literal_captured_text`: `literal_captured_text` over `captured_text` performing
  bounded literal substring matching over stored LF-normalized document text,
  preserving exact line spans across chunk boundaries within a single file and
  using `deterministic-locator-v1` ordering.

Every query executes as a **single read-only SQL statement** that validates the
latest complete canonical `run_id`, publication receipt fields, `policy_digest`,
and per-binding policy digests before scanning `cloe_lexical` rows, and joins
same-run canonical file/symbol definitions inside the same statement snapshot.
Serialized UTF-8 JSON output is bounded to `<= 65,536` bytes.
The bound includes the CLI newline. A fitting partial response reports
`output_budget_exceeded`, carries no query hits and exits1. If a truthful scope,
identity or provenance cannot fit even after projection, serialization validation
emits a bounded stderr diagnostic and no JSON, with exit1. An administrative
operation may already have completed; inspect current state before retrying.
Complete ready/available/revoked/dry-run responses exit0; partial responses exit1.

Repeat `--path-prefix` to select the union of relative prefixes. The complete
prefix list and `path_prefix_match: "any"` are retained in query provenance;
the single-prefix scope field is unset for a union. Build and query both require
explicit body authorization and at least one binding. They use the configured
PostgreSQL credential route; there is no credential override or role fallback.

### Revoke Derived Lexical Generations

```bash
cloe ops lexical-revoke --repo-map-home /path/to/cloe-home \
  --graph <graph-id> \
  --yes \
  --reason operator_revoked \
  --json
```

- Deletes `cloe_lexical.authority` for the repository, marks active or
  in-progress generations `revoked` with the audit reason, and purges derived
  rows from `cloe_lexical.{chunks,documents,omissions}`.
- Uses the same per-repository lifecycle lock as build batches. Revocation clears
  builder custody and lease, so a previously admitted batch cannot later activate.
- Pass `--dry-run` (instead of `--yes`) to inspect counts without mutating database state.

## Backup and Restore Semantics

PostgreSQL dumps include `cloe_lexical` tables and require protected operator
custody. When a database is restored via `init_database_from_dump` or
`restore_coordinated_backup` (`--no-owner --no-privileges`), post-restore
reconciliation (`reconcile_restored_graph_lexical_roles`) verifies database-owner
custody of `cloe_lexical`, re-applies `PUBLIC` and limited-role `REVOKE ALL`
denials, removes `cloe_lexical.authority`, marks restored generations
`revoked` with reason `restored_snapshot_unverified_lexical_index_invalidated`,
and purges derived `documents`, `chunks`, and `omissions` rows. Operators must
run `cloe ops lexical-build` against current on-disk policy and source bindings
to re-enable lexical search after a restore.

## Scope and freshness details

Path prefixes are literal relative path segments: `pkg` selects `pkg` and
`pkg/...`, while `pkg2/...` and partial filenames remain outside that scope.
Trailing slashes normalize away and repeated prefixes deduplicate. Absolute,
home/drive, traversal/dot/empty internal segments, NUL, backslash and glob
syntax refuse before connection use. Percent is a literal filename character;
these filters use no SQL LIKE wildcard matching. Library and CLI paging agree
on limit1..100 and offset0..1000. Hit aggregates explicitly retain the declared
full ordering, including literal occurrence positions.

Freshness is deliberately conservative in this milestone: policy and binding
digests cover the full graph configuration. A policy edit to an unrelated or
excluded binding can stale a generation and require an explicit rebuild. This
is stricter than selected-binding-only invalidation and does not narrow privacy
checks. Lifecycle locks use a shared namespaced BIGINT hash for the full BIGINT
repository-ID range; a collision conservatively serializes unrelated work.
Restore always requests the explicit lexical-purge contract and refuses an
unsupported reconciler instead of silently skipping the purge.

Staged graph publication supports positive PostgreSQL BIGINT repository IDs
under [ADR0162](../adr/2026/11/0162-early-sealing-admission-and-bigint-publication.md).
Integration owners cover publication at `2**63-1` with the refresh role and
high-ID portable publication followed by lexical build/query/revoke, including
competing-lock boundaries. The publisher compatibility follow-up is implemented;
installed and release qualification remain separate.

## First-use workflow

The bounded Server and mixed-privacy sequence is documented in
[First-use workflows](first-use-workflows.md). It reuses this page's native
FTS build/query/revoke commands and records feed/mailbox lexical refusal as a
policy outcome. The guide is source-level; installed proof remains pending.
