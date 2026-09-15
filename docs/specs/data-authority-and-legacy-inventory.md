# RepoMap Data Authority And Legacy Inventory

Date: 2026-07-16

## Status

ARCH-CLOSE current authority and historical-legacy inventory. This document
defines normalized data authority, records completed forward decommissioning,
and preserves the safe historical rationale. It does not authorize migration
deletion, graph refreshes, or runtime operations.

ARCH1B implements the resolved topology. ARCH5 migrates stable repository
identity and removes legacy persisted graph families by guarded forward
migration. ARCH7 deploys exact ownership, complete coordinated recovery, and
least-privilege roles. ARCH8 accepts the integrated behavior. Each graph has
one explicit effective database, control is distinct, `postgres` remains a
non-owned maintenance target, and the exact private ownership allowlist
contains graph and control databases only. Stable configured identity is
`repo1:<graph-id>`; root relocation preserves it, while graph-ID changes
require explicit re-registration or migration.

## Scope

This specification covers:

- raw observations and the file/source index;
- legacy nodes, edges, and evidence;
- canonical nodes, edges, evidence, and evidence links;
- rowwise and staged ingestion;
- row construction, COPY, checksums, stage state, validation, statistics, and
  merge;
- publication, receipts, commit-unknown reconciliation, and cleanup;
- graph-database and control-database authority;
- coordinator jobs, attempts, leases, and singleton fencing;
- direct and coordinator execution parity;
- naming and identity inconsistencies that affect a future migration; and
- the safe order for removing legacy persisted graph families.

The evidence boundary is committed repository source, migrations, tests, ADRs,
and status records. Generated graph databases are evidence, not source of
truth. Historical migration files remain part of the permanent migration
history.

## Terms

The authority classifications used in this document are:

- **authoritative**: the durable source used to establish the fact or state;
- **current derived**: a first-class, maintained projection with an explicit
  current product purpose;
- **canonical current**: the current durable graph representation and public
  graph-semantic authority;
- **compatibility**: a maintained representation whose purpose is backward
  compatibility rather than current semantic authority;
- **temporary**: durable or transient work state that is never a published
  result; and
- **protocol state**: durable coordination or publication state rather than
  graph content.

"Public" in the matrices means reachable through supported CLI, operations,
or MCP readback. It does not mean that private graph content is safe to expose.

## Target Model Decision

### Model A: retain legacy persisted graph families

Model A retains `nodes`, `edges`, and `evidence` as permanent persisted
families alongside the canonical graph, raw observations, and the file/source
index. It minimizes near-term migration work but makes dual graph writes,
duplicate identities, compatibility readback, extra staging families, and
additional COPY, WAL, validation, index, and merge costs permanent.

Model A is not selected.

### Model B: raw facts, canonical graph, and first-class file index

Model B retains three deliberately different durable layers:

1. `raw_observations` as authoritative, run-scoped source evidence;
2. `canonical_nodes`, `canonical_edges`, `canonical_evidence`,
   `canonical_node_evidence`, and `canonical_edge_evidence` as the one current
   graph; and
3. `files` as one explicit, first-class derived file/source index.

Legacy `nodes`, `edges`, and `evidence` remain bounded compatibility families
until every reader and contract has a proven replacement. ARCH5D removes their
runtime staging and final relations through one guarded forward migration. The
historical migrations that created and evolved them are never deleted or
rewritten.

**Model B is selected.** It preserves raw provenance and file inventory
semantics without making two graph models permanent.

### Model C: raw facts with rebuildable projections

Model C makes raw observations the durable evidence authority and treats file,
canonical-graph, and compatibility forms as rebuildable projections. A usable
implementation would still need indexed projections for current read latency,
then atomically activate a complete rebuilt generation so readers never observe
a partial graph.

This model reduces the number of independently authoritative forms, but it does
not automatically remove projection storage or write amplification. It also
adds rebuild scheduling, availability, versioning, recovery, and atomic-swap
work; compatibility readers still need adapters; migration must preserve
existing file-index semantics; and baseline/drift history needs an explicit
identity across rebuilt generations. No current operational evidence shows
that repeated full projection rebuilds are preferable to receipt-bearing
publication of the selected durable file and canonical families.

Model C is not selected.

## Data Authority Matrix

The following matrices use the same required fields. "Migration" describes the
ARCH0 direction, not authorization to implement it.

### Identity, generation, and operational state

| Concept | Authority | Durable | Derived | Compatibility | Temporary | Public | Writer | Reader | Replacement | Retention | Migration | Duplication |
| --- | --- | ---:| ---:| ---:| ---:| ---:| --- | --- | --- | --- | --- | --- |
| Configured graph identity | Graph registration in resolved operations configuration; every enabled or disabled graph resolves to one unique effective database | Configuration files | Runtime, service, CLI, MCP, coordinator, and lifecycle ownership projections | Existing accepted config keys and global fallback syntax | Worker capability | Public graph ID only | Explicit configuration edit | Shared resolver and compatibility facades | Later explicit registration | User configuration lifetime | ARCH1B implements one resolution path and collision refusal | The global fallback remains syntax-compatible but cannot collapse two configured graphs into one database |
| Repository identity | Stable configured identity `repo1:<graph-id>` within one dedicated graph database; ARCH5C1 adds nullable `repository_identity`; ARCH5C2A reconciles storage ownership to one configured-root row | Configuration contract and `repositories` with partial unique stable identity plus retained `UNIQUE (root_path)` | Runtime/coordinator generation inputs and public summaries | Root-path lookup and existing stable-key queries | Stage-local numeric id | Database ids and absolute paths remain private | Configuration defines stable identity; ARCH5C2A migrates historical ownership; ARCH5C2B makes configured staged writers conflict on stable identity and update mutable name/root, while retained direct and row-wise adapters accept optional identity and default to historical root conflict | Resolved configuration, final-table queries, publication, backup-first identity state verification, and ARCH5C3 restore/reconstruction acceptance | Root relocation preserves configured identity and repository ID; graph-ID changes require explicit re-registration or migration | Graph database lifetime | ARCH5C1 provides additive schema; ARCH5C2A preserves historical/run-scoped rows, merges final identities, remaps links/stages, and retains highest publication authority; ARCH5C2B cuts writers over; ARCH5C3 accepts migration-only no-drift, historical restore, and stable forward reconstruction | Identity omission remains an explicit compatibility path; configured refresh always supplies identity; restored historical state reconstructs deterministically |
| Source generation | Deterministic exclusion-aware source snapshot | Job, attempt, stage, run, receipt | Status/drift projection | None | Worker capability | Bounded category | Generation scanner/resolver | Claim, worker, publication, status | Later complete generation receipt | Job/run retention | Preserve exact equality | Repeated for cross-database fencing |
| Configuration generation | Deterministic execution-relevant configuration digest | Job, attempt, stage, run, receipt | Status projection | Existing config aliases | Worker capability | Bounded category | Configuration resolver | Claim, worker, publication, status | Later complete generation receipt | Job/run retention | Normalize one resolver | Repeated for fencing |
| Extractor generation | Accepted extractor implementation/version digest | Job, attempt, stage, run, receipt | Status projection | None | Worker capability | Bounded value/category | Refresh/coordinator adapter | Publication/reconciliation | Later complete generation receipt | Job/run retention | Keep distinct from source generation | Repeated intentionally |
| Canonicalizer generation | Accepted canonicalizer implementation/version digest | Job, attempt, stage, run, receipt | Status projection | None | Worker capability | Bounded value/category | Refresh/coordinator adapter | Publication/reconciliation | Later complete generation receipt | Job/run retention | Keep distinct from graph-key version | Repeated intentionally |
| Run and publication freshness | Two current typed concepts: latest recorded run and latest complete receipt-bearing publication; latest successful receiptless import is historical compatibility vocabulary only | `runs`; publication authority requires every receipt field | Status/summary/baseline/drift and reconciliation request their exact authority concept | Existing `latest_run_*` fields and coordinator marker names are explicit compatibility projections | Running/failed recorded candidates | Bounded versioned schemas | Receipt-bearing staged final publication only | Typed run-authority readback, status, summary, baseline, drift, reconciliation | A later complete receipt-bearing publication | Run policy | ARCH1A named the concepts; ARCH4 migrated complete callers, made partial acquisition non-publishing, and removed receiptless writers | No supported receiptless mutation can supersede graph freshness or final state |
| Baseline | Explicit saved baseline by graph and kind | Baseline artifact | CLI/MCP summary | Earlier schema versions | Preflight comparison | Bounded counts/categories | Baseline save/prune commands | Drift/operator reads | Explicit later save/prune | Baseline policy | Version separately from graph schema | Repeats accepted aggregates intentionally |
| Drift | Deterministic comparison against one accepted baseline | Optional result artifact | CLI/MCP output | Earlier result schemas | Comparison state | Bounded counts/categories | Drift operation | Operator/automation | Recomputed comparison | Report policy | Normalize one stable schema | Never graph authority |
| Runtime registration | Configured runtime plus rendered owned-runtime plan | Configuration/rendered artifacts | Path-free HTTP/status and exact-current readiness | Development source runtime | Process/container state | Bounded state and counts only | Explicit render and one-shot runtime commands | Lifecycle/status | Explicit re-render | Runtime policy | ARCH7F/ARCH7G establish the installed release-artifact contract and normalized HTTP projection | Config intent remains authority; rendered state is derived |
| Database lifecycle state | Exact configured graph/control databases plus initialized or upgraded schema state | PostgreSQL catalogs and private backups | Bounded exact-current status/readiness | Supported pre-ledger and prior-version states | Invocation-local provisional ownership | Bounded state category | Explicit one-shot lifecycle CLI | Lifecycle/readback | Explicit successful lifecycle operation | Database/backup policy | ARCH5 and ARCH7C through ARCH7G supply versioning, exact allowlisting, backup-first advancement, and deployed gates | Resolved config defines ownership; catalog ledgers define schema state |
| Database schema version and fresh provisioning | Ordered checksummed committed graph/control migration catalogs, product-owned applied-version ledgers, deterministic control-then-graph maintenance authority, invocation-local provisional ownership, and backup-first exact-prefix advancement | Migration resources and exact applied rows; pending DDL and ledger rows commit together; fresh release-cluster databases are created from `template0` with explicit UTF-8/C attributes | Exact-current readiness and bounded upgrade/recovery results | Exact supported pre-ledger adoption, exact-behind forward migration, and exact-current replay | Disposable reference database, retained verified backup, exclusive upgrade owners, and invocation-local cleanup | Bounded version/readiness and recovery categories only | One-shot fresh initialization, source/restore verification, cleanup-based retry, explicit backup-first adoption/upgrade/rollback, and role reconciliation | Lifecycle, startup, publication admission, upgrade, health, injected failure/retry, and disposable PostgreSQL checks | Later exact supported version | Supported database lifetime | ARCH5 implements ledgers/upgrade/rollback; ARCH7 packages exact ownership, UTF-8/C provisioning, readiness, and complete recovery | Catalog identity and applied ledger intentionally duplicate version identity for drift detection |
| Cluster backup set | Exact owned graph and coordinator-control inventory plus one atomically published complete manifest/set at a maintenance-fenced stable recovery point | Private streamed dumps, checksums, stable-point evidence, and one exact manifest | Bounded counts/categories | Single-database backup command remains a narrow compatibility surface | In-progress private staging sets and maintenance locks | Bounded counts/categories only | Explicit one-shot lifecycle CLI | Backup inspection and restore | ARCH7D provides complete-set capture/restore; ARCH7E reconstructs grants; ARCH7G supplies lifecycle-only mounted capability | Backup policy | Preserve exact allowlisting and backup-root privacy | Per-database dumps intentionally duplicate database membership recorded by the exact manifest |
| PostgreSQL runtime compatibility | ARCH7F immutable server/client/Psycopg/libpq version matrix accepted in ARCH7G deployment | OCI-index-pinned PostgreSQL 16.14 Bookworm supplies the server and fixed-path 16.14 clients; installed Psycopg 3.2.12 supplies bundled libpq 17.6 | Image metadata and readiness | Development host tools | Digest-pinned multi-stage image build | Bounded version categories | Release build | Lifecycle/readiness and acceptance | A later accepted release matrix | Release lifetime | ARCH7F proves multi-architecture construction and resource identity; ARCH7G proves live cluster query, dump, and restore-catalog behavior | Client/server patch identity and explicit fixed paths intentionally duplicate the accepted release matrix for reproducibility |
| Destructive database authorization | Exact collision-free resolved graph/control inventory; maintenance and system databases are excluded | Resolved operations configuration and backup-first recovery evidence | Bounded allowlist state | Safe-name and system-name exclusions remain defense in depth | Confirmation/dry-run state | Bounded category only | Shared resolver | Lifecycle and drop command | ARCH7C1 gates every destructive action before external access; ARCH7C2 holds maintenance authority through backup verification and drop | Configuration lifetime | Reject any existing database outside configured ownership | No material duplication; configuration and runtime catalogs prove different facts |

### Persisted data families

| Concept | Authority | Durable | Derived | Compatibility | Temporary | Public | Writer | Reader | Replacement | Retention | Migration | Duplication |
|---|---|---:|---:|---:|---:|---:|---|---|---|---|---|---|
| Raw observations | Authoritative run-scoped source evidence and provenance | Yes | No | No | No | Bounded source readback | Receipt-bearing staged raw merge | Source readback, canonical evidence resolution, summaries | Later complete publication according to run retention | Retain by run-retention policy | Preserve schema and identity | Payload metadata may overlap derived graph fields by design |
| File/source identity/index | Current first-class derived inventory keyed by repository identity and path | Yes | Yes | No | No | Operations summaries and graph-file projections | Receipt-bearing staged file merge | Summaries, baseline/drift, and inventory metadata | Complete publication for the stable repository identity | Retain | Preserve the explicit file/source-index contract | Canonical file nodes repeat path identity but not the full index contract |
| Legacy nodes | Retired historical graph semantics | No | No | No | No | None | None | None | Canonical nodes plus explicit file/source index where applicable | Historical migrations and status records only | Runtime relation removed by ARCH5D; API/facade removed by ARCH5E | None |
| Legacy edges | Retired historical graph semantics | No | No | No | No | None | None | None | Canonical edges and canonical evidence links | Historical migrations and status records only | Runtime relation removed by ARCH5D; API/facade removed by ARCH5E | None |
| Legacy evidence | Retired historical evidence semantics | No | No | No | No | None | None | None | Canonical evidence plus raw observation provenance | Historical migrations and status records only | Runtime relation removed by ARCH5D; API/facade removed by ARCH5E | None |
| Canonical nodes | Current graph-node authority | Yes | Yes | No | No | Bounded canonical graph readback | Receipt-bearing staged canonical-node merge | Canonical CLI, operations, MCP, summaries | Complete publication | Retain | Continue as the only graph-node family | May aggregate facts from multiple observations |
| Canonical edges | Current graph-edge authority | Yes | Yes | No | No | Bounded canonical graph readback | Receipt-bearing staged canonical-edge merge | Canonical CLI, operations, MCP, summaries | Complete publication | Retain | Continue as the only graph-edge family | May aggregate relationships from multiple observations |
| Canonical evidence | Current normalized evidence authority for canonical graph explanation | Yes | Yes | No | No | Bounded canonical explanation/readback | Receipt-bearing staged canonical-evidence merge | Canonical evidence and source-aware readback | Complete publication | Retain with raw-observation references | Preserve raw reference checks and run identity | References raw evidence while also storing normalized identity metadata |
| Canonical node-evidence links | Current node-to-evidence association authority | Yes | Yes | No | No | Bounded canonical explanation/readback | Receipt-bearing staged link merge | Canonical node explanation/readback | Complete publication | Retain | Preserve logical-link deduplication | Link rows repeat endpoint/evidence identities by necessity |
| Canonical edge-evidence links | Current edge-to-evidence association authority | Yes | Yes | No | No | Bounded canonical edge explanation | Receipt-bearing staged link merge | Canonical edge explanation/readback | Complete publication | Retain | Preserve logical-link deduplication | Link rows repeat endpoint/evidence identities by necessity |

Schema evidence:

- `src/main/resources/rdbms/2026/06/28-001-core-create_graph_tables.sql`
- `src/main/resources/rdbms/2026/06/29-001-core-create_raw_observations.sql`
- `src/main/resources/rdbms/2026/06/29-002-core-create_canonical_graph_tables.sql`
- `src/main/resources/rdbms/2026/07/04-001-core-extend_canonical_edge_kinds.sql`
- `src/main/resources/rdbms/2026/07/12-001-core-add-go-canonical-edge-kinds.sql`

### Ingestion and staging

| Concept | Authority | Durable | Derived | Compatibility | Temporary | Public | Writer | Reader | Replacement | Retention | Migration | Duplication |
|---|---|---:|---:|---:|---:|---:|---|---|---|---|---|---|
| Rowwise ingestion | Retired historical implementation | No | No | No | No | None | None | Historical status records only | Receipt-bearing staged publication for complete generations; acquisition-only non-publication for partial input | Historical records only | Removed in ARCH4C with both primitives and facade exports | None |
| Staged ingestion | Current production full-refresh write path, not publication authority by itself | Yes, until cleanup | Yes | No | Yes | Direct and coordinator refresh operations | `storage/staged_ingestion.py` | Validation, merge, reconciliation, cleanup | None | Retain | Keep one shared implementation for both execution modes | Duplicates final rows temporarily by design |
| Row construction | Deterministic client-side seven-family row construction | Spool-backed during operation | Yes | No | Yes | No | `storage/staged_rows.py`, `storage/row_spool.py` | Checksum and COPY adapters | None | Operation lifetime | Current closed descriptor catalog | Re-expresses file/raw/canonical rows in staging shapes |
| COPY | Transfer mechanism, never semantic or publication authority | Stage rows become durable | No | No | Yes | No | `storage/staging_copy.py` | Stage validation and merge | None | Operation and cleanup lifetime | Seven descriptor-owned current families | Copies each family once into its stage table |
| Checksums | Client-computed transfer receipts | Stored in stage header | Yes | No | Yes | Bounded operational state only | `storage/staging_checksums.py`, stage creation | Publication completeness guard and diagnostics | None | Through stage cleanup/audit window | Document that they are not server-recomputed content validation | Re-encodes row identity and payload for receipt purposes |
| Staging ownership and state | Authoritative owner and lifecycle state for one stage, not graph freshness | Yes | No | No | Yes | Bounded operational status | `storage/staging.py`, staged ingestion/publication/cleanup | Reconciliation and cleanup | None | Through terminal retention and cleanup | Preserve explicit transitions and ownership checks | Mirrors parts of attempt state across the graph/control boundary |
| Validation | Authoritative cardinality gate for staged publication eligibility | Results stored in stage header | Yes | No | Yes | Bounded status only | `storage/staged_validation.py` | Publication guard | None | Through stage lifecycle | Add integrity semantics only in a separate accepted phase | Counts repeat the expected manifest; checksum values are receipts |
| Statistics | Query-planner support only | PostgreSQL statistics are durable but regenerable | Yes | No | Yes | No | Targeted `ANALYZE` in staged ingestion | PostgreSQL planner | None | Regenerable | Keep targeted and evidence-driven | Statistical summaries duplicate distributions, not semantic facts |
| Merge | Final-table proposal application inside publication transaction | Result is durable only on commit | Yes | No | No | No | `storage/staging_merge.py`, `storage/canonical_staging_merge.py` | Final tables and receipt construction | None | Transaction lifetime | Descriptor-owned file/raw/canonical merge | Writes the file index, raw evidence, and canonical graph from one complete proposal set |

Primary evidence:

- `src/main/resources/rdbms/2026/07/14-001-scale1-create_staging_contract.sql`
- `src/main/python/repomap_kg/storage/staged_rows.py`
- `src/main/python/repomap_kg/storage/row_spool.py`
- `src/main/python/repomap_kg/storage/staging_copy.py`
- `src/main/python/repomap_kg/storage/staging_checksums.py`
- `src/main/python/repomap_kg/storage/staging.py`
- `src/main/python/repomap_kg/storage/staged_validation.py`
- `src/main/python/repomap_kg/storage/staging_merge.py`
- `src/main/python/repomap_kg/storage/canonical_staging_merge.py`
- `src/main/python/repomap_kg/storage/staged_ingestion.py`
- `src/main/python/repomap_kg/storage/main.py`
- `src/main/python/repomap_kg/storage/_load_stream.py`
- `src/main/python/repomap_kg/ops/ingestion/source.py`
- `src/main/python/repomap_kg/ops/ingestion/source_archive.py`
- `src/main/python/repomap_kg/ops/ingestion/bulk.py`
- `src/main/python/repomap_kg/ops/ingestion/api.py`
- `src/main/python/repomap_kg/ops/ingestion/github_api.py`
- `src/main/python/repomap_kg/storage/rowwise_caller_contracts.py`
- `src/test/unit/python/repomap_kg/storage/arch3e_rowwise_caller_contracts.unit.test.py`
- `docs/status/2026/07/14/00548-scale9b-validation-cost-legacy-compatibility.md`
- `docs/status/2026/07/14/00553-scale9h-node-evidence-plan-bound.md`
- `docs/status/2026/07/15/00559-scale9l-canonical-node-evidence-merge-bound.md`

The following ARCH3E through ARCH4C progression is historical implementation
evidence. Its future-tense statements describe the then-pending boundaries;
every disposition is complete at ARCH-CLOSE.

ARCH3E froze the caller disposition before writer authority changes:

| Future behavior | Callers | ARCH4 boundary |
| --- | --- | --- |
| Complete staged publication | `storage load-files`, the programmatic row-wise `refresh_graph` compatibility path, and the connector-comparison fixture seed | ARCH4A uses the existing staged receipt, fencing, validation, merge, cancellation, and commit-unknown contract |
| Acquisition-only non-mutating input | Feed, archive, WARC, bulk, generic API, and GitHub acquisition/import commands and their programmatic functions | ARCH4B retains public-safe artifacts and observations but cannot mutate final graph state or freshness |
| Announced retirement | `storage load-canonical`, both row-wise mutation primitives exported through the storage facade, and the SCALE7 row-wise measurement baseline | ARCH4B announces/removes incompatible public and tool surfaces; ARCH4C removes the final row-wise mutation implementation after callers are closed |

The typed registry records replacement and compatibility boundaries plus
direct/coordinator relevance. Its AST-backed test enumerates every production
and repository-tool direct call or default-loader binding. Source drift cannot
add, remove, move, or duplicate a receiptless binding without an explicit
registry update.

ARCH4A implements the complete-generation disposition. `storage load-files`,
programmatic configured refresh, and connector-comparison fixture seeding now
use receipt-bearing staged publication. The registry marks those surfaces as
migrated, and the AST-backed active receiptless-binding census is reduced from
11 to 8. Programmatic refresh rejects row-wise mode before discovery or
storage work. Partial acquisition, incompatible surfaces, and the underlying
row-wise writer remain bounded to ARCH4B and ARCH4C.

ARCH4B implements the acquisition and retirement dispositions. The six
acquisition/import functions retain public-safe artifacts and raw observations
but return a versioned `not_published` result and accept no final-mutation
selectors. `storage load-canonical` and the row-wise SCALE7 baseline are
retired. The registry retains all dispositions for audit, while the active
receiptless-binding census is empty. The two programmatic row-wise primitives
remain uncalled until ARCH4C removes them with their facade exports.

### Publication and cleanup

| Concept | Authority | Durable | Derived | Compatibility | Temporary | Public | Writer | Reader | Replacement | Retention | Migration | Duplication |
|---|---|---:|---:|---:|---:|---:|---|---|---|---|---|---|
| Receipt-bearing staged publication transaction | Sole forced-full staged freshness transition for one accepted refresh | Yes on commit | No | No | No | Reflected through bounded receipt/status readback | `storage/staged_publication.py`, `storage/publication_fencing.py` | Publication readback, reconciliation, coordinator, and freshness consumers | None | Permanent final state | Preserve all-or-nothing merge, completion, receipt, and stage transition | Coordinates several durable records intentionally |
| Publication receipt | Authoritative proof that a specific attempt and generation tuple committed | Yes | No | Supports direct receipt-slot compatibility | No | Bounded status only | Final publication transaction | Reconciliation and coordinator state transition | None | Run retention | Preserve exact attempt and generation matching | Repeats attempt/generation identity so commit can be proven independently |
| Receiptless row-wise final mutation | Retired historical mutation path | No current runtime representation | No | No | No | None | None | Historical migrations, ADR, and phase records only | Receipt-bearing staged publication or acquisition-only non-publication | Historical records only | Removed in ARCH4A through ARCH4C | None; no supported caller or primitive remains |
| Commit-unknown state | Authoritative uncertainty marker until receipt-first reconciliation | Yes | No | No | Protocol-temporary | Bounded operational status | Publication exception/reconciliation path | Coordinator and stage reconciliation | Matching receipt resolves success; conflict quarantines; absence remains reconciliation-required | Until resolved | Never infer rollback or safe failure from a missing receipt alone | Mirrors uncertainty in graph stage and control attempt state |
| Stage cleanup | Destructive reclamation protocol, not graph authority | State and bounded deletion progress are durable | No | No | Yes | Bounded operational status | `storage/staging_cleanup.py` | Cleanup scheduler/operator | None | After terminal retention, owner quiescence, and reconciliation | Seven current staging families only | Deletes temporary copies, not published facts |

Publication schema and implementation evidence:

- `src/main/resources/rdbms/2026/07/13-001-core-add-run-publication-generations.sql`
- `src/main/resources/rdbms/2026/07/13-002-core-add-run-publication-attempts.sql`
- `src/main/python/repomap_kg/storage/staged_publication.py`
- `src/main/python/repomap_kg/storage/publication_fencing.py`
- `src/main/python/repomap_kg/storage/publication_readback.py`
- `src/main/python/repomap_kg/storage/staging_cleanup.py`
- `src/main/python/repomap_kg/ops/refresh_sql.py::build_refresh_status_sql`
- `src/main/python/repomap_kg/ops/refresh_sql.py::build_graph_summary_sql`

### Control and execution authority

| Concept | Authority | Durable | Derived | Compatibility | Temporary | Public | Writer | Reader | Replacement | Retention | Migration | Duplication |
|---|---|---:|---:|---:|---:|---:|---|---|---|---|---|
| Graph database | Authority for graph content, runs, receipts, stages, and graph-local publication projection | Yes | Mixed | No | Contains temporary stage tables | Bounded readback | Storage/publication implementation | CLI, operations, MCP, reconciliation | None | Product retention policy | Do not add scheduler ownership here | Repeats selected control identities only for fencing and receipts |
| Control database | Authority for durable scheduling and ownership, never graph payload | Yes | No | No | No | Bounded coordinator status | Coordinator control store | Coordinator, worker supervisor, lifecycle CLI | None | Coordinator policy | Keep physically and logically separate from graph DB | Repeats graph/job identifiers but stores no graph payload |
| Coordinator jobs | Durable desired work and terminal outcome authority | Yes | No | No | No | Bounded coordinator commands | Control submission/coalescing/state modules | Polling, listing, reconciliation | None | Job retention policy | Preserve stable job identity and state transitions | Job identity is repeated in attempt, lease, receipt, and graph projection |
| Coordinator attempts | Durable execution-attempt and publication-state authority | Yes | No | No | Protocol-temporary until terminal | Bounded coordinator status | Claim, heartbeat, state, reconciliation modules | Worker supervisor and reconciliation | None | Job-attempt retention policy | Preserve one-current-attempt constraint and exact generations | Attempt identity is repeated across lease, capability, stage, and receipt |
| Graph leases | Graph-scoped coordinator ownership authority plus a transaction-ordered execution capability distinct from singleton succession | Lease/attempt identity is durable in control; the distinct capability becomes durable in the graph authority projection when stage creation commits | No | No | Worker capability before graph registration | Bounded coordinator status | Claim/heartbeat/release logic and graph claim registration | Coordinator claim, publication, and reconciliation | A future recovered-attempt republish contract requires an ARCH5 control-schema column | Lease lifetime plus attempt audit; graph projection lifetime | ARCH1C carries the independent capability without unmanaged DDL | Repeats current attempt and coordinator identity intentionally |
| Singleton epoch | Authority for coordinator-instance succession | Yes | No | No | Protocol state | No raw value in public output | Singleton acquisition/heartbeat | Claim and state transitions | None | Control DB lifetime | Remains distinct from graph-claim ordering | Carried beside, never substituted for, the graph capability |
| Graph-local publication authority | Monotonic projection used by the graph transaction, not a second coordinator | Yes | Yes | No | No | No raw values in public output | Coordinator stage creation and finalization | Publication guard | Control DB remains scheduling authority | Graph DB lifetime | ARCH1C registers and revalidates the independent graph claim | Repeats accepted control identity and generations intentionally |
| Direct execution | Explicit local mutation authority using the shared staged implementation | Stage/run/receipt state is durable | No | Uses historical receipt attempt slot | No | Direct refresh CLI | Direct refresh adapter and staged ingestion | Publication and operational status | None | Operation/run retention | ARCH1C uses the same graph-local final transaction lock as coordinator publication | Duplicates coordinator ingestion mechanics intentionally, not scheduler state |
| Coordinator execution | Durable job/attempt/lease authority using the shared staged implementation | Yes | No | No | No | Coordinator CLI/status | Coordinator, worker adapter, staged ingestion | Reconciliation and operational status | None | Control and run retention | Preserve exact capability handoff and fail-closed ownership | Repeats control authority in graph-local stage and receipt |
| Direct/coordinator parity | One semantic ingestion and result contract; orchestration and authority acquisition differ | Evidence is in tests/status, not a separate table | Yes | No | No | Observable through equivalent result contracts | Shared refresh and staged-ingestion code | Tests and operational readback | None | Permanent invariant | ARCH1C proves common final exclusion and coordinator claim ordering without separate loaders | Intentional shared implementation; no connector or mode fallback |

Control and parity evidence:

- `src/main/resources/coordinator-rdbms/2026/07/13-001-async2-create-control-schema.sql`
- `src/main/python/repomap_kg/coordinator/_control_ownership.py`
- `src/main/python/repomap_kg/coordinator/_control_state.py`
- `src/main/python/repomap_kg/coordinator/_control_reconciliation.py`
- `src/main/python/repomap_kg/coordinator/_control_startup.py`
- `src/main/python/repomap_kg/coordinator/refresh_adapter.py`
- `src/main/python/repomap_kg/coordinator/_refresh_execution.py`
- `src/main/python/repomap_kg/storage/staging_ownership.py`
- `docs/adr/2026/07/0039-synchronous-and-asynchronous-architecture.md`
- `docs/adr/2026/07/0040-high-scale-full-refresh-ingestion.md`
- `docs/status/2026/07/14/00545-scale8-production-staged-ingestion.md`

## Exhaustive Persisted-Family Legacy Classification

Each persisted data family in scope appears exactly once in this section and
has one classification.

### `raw_observations`: authoritative evidence

- **Writers:** rowwise canonical load and staged raw merge through
  `storage/canonical_rows.py`, `storage/sql_load.py`, `storage/staged_rows.py`,
  and `storage/staging_merge.py`.
- **Readers:** source readback in `storage/sql_sources.py`, canonical evidence
  reference guards, source summaries, and bounded MCP source tools.
- **CLI and MCP:** explicitly named source/raw readback; raw payload inclusion
  remains separately bounded and disabled by default where required.
- **Baseline and drift:** raw-observation count is a current scalar input in
  operations reports; it is not a legacy count.
- **Connectors:** uses the common psql/Psycopg readback boundary.
- **Tests:**
  `src/test/int/python/repomap_kg/storage/load_sources/raw_observations.int.test.py`,
  `src/test/int/python/repomap_kg/storage/source_archive_readback.int.test.py`,
  `src/test/int/python/repomap_kg/storage/source_feed_readback.int.test.py`, and
  `src/test/int/python/repomap_kg/storage/source_warc_readback.int.test.py`.
- **Schema and migration:** created by
  `src/main/resources/rdbms/2026/06/29-001-core-create_raw_observations.sql`.
  The migration remains permanently.
- **Replacement and parity:** no replacement is required. Canonical evidence
  must continue to preserve exact raw-reference parity.
- **Removal and rollback:** not a removal candidate. Retention-policy changes
  require a separate accepted phase and backup-first rollback planning.
- **Risk and performance:** retaining run-scoped raw payloads consumes storage,
  but removing them would break provenance, replay, and source readback.

### `files`: current first-class derived component

- **Writers:** rowwise file upserts and staged file merge in
  `storage/sql_load.py`, `storage/_load_stream.py`, `storage/staged_rows.py`, and
  `storage/staging_merge.py`.
- **Readers:** `ops/refresh_sql.py`, `ops/reports.py`, baseline/drift operations,
  graph-file inventory projections, and remaining legacy file joins.
- **CLI and MCP:** old direct storage-file commands have been retired or
  replaced; current operations expose canonical graph-file projections and
  summaries rather than declaring `files` to be canonical graph nodes.
- **Baseline and drift:** current file and language counts depend on this
  index. It is part of Model B.
- **Connectors:** uses the common readback connector and summary adapters.
- **Tests:**
  `src/test/int/python/repomap_kg/ops/graph_storage_readback.int.test.py`,
  `src/test/int/python/repomap_kg/ops/graph_summary_readback.int.test.py`,
  `src/test/unit/python/repomap_kg/ops/graph_storage_readback.unit.test.py`, and
  `src/test/unit/python/repomap_kg/ops_refresh/baselines_drift.unit.test.py`.
- **Schema and migration:** created by
  `src/main/resources/rdbms/2026/06/28-001-core-create_graph_tables.sql` and
  extended by
  `src/main/resources/rdbms/2026/06/28-002-core-add_file_run_tracking.sql`.
  Both historical migrations remain.
- **Replacement and parity:** canonical file nodes replace graph identity and
  traversal, not the complete index fields. No removal parity exists today.
- **Removal and rollback:** not a legacy-removal candidate. Any future
  replacement must be additive, field-complete, benchmarked, and reversible
  before a later forward drop migration.
- **Risk and performance:** it duplicates file path identity with canonical
  file nodes, but avoids deriving inventory metadata through expensive graph
  joins and preserves explicit inventory semantics.

### `nodes`: legacy compatibility component

- **Writers:** `storage/sql_load.py`, `storage/_load_stream.py`,
  `storage/staged_rows.py`, and the legacy-node merge in
  `storage/staging_merge.py`.
- **Readers:** `storage/legacy.py`, `storage/sql_readback.py`, explicit legacy
  node/neighborhood/file-neighborhood paths, and legacy status counts.
- **CLI and MCP:** explicit `--legacy` CLI modes remain; MCP graph traversal is
  canonical, while legacy status/routing tests identify residual compatibility
  contracts.
- **Baseline and drift:** current baseline/drift scalar fields do not require
  legacy node counts.
- **Connectors:** legacy reads use the shared psql/Psycopg adapter.
- **Tests:**
  `src/test/int/python/repomap_kg/storage/legacy_node_records.int.test.py`,
  `src/test/unit/python/repomap_kg/storage/legacy_node_records.unit.test.py`,
  `src/test/int/python/repomap_kg/storage/legacy_neighborhood.int.test.py`, and
  `src/test/int/python/repomap_kg/storage/canonical_readback_profiles/legacy_cli_modes.int.test.py`.
- **Schema and migration:** created by
  `src/main/resources/rdbms/2026/06/28-001-core-create_graph_tables.sql`.
  That historical migration remains after a future forward drop migration.
- **Replacement and parity:** canonical nodes replace graph semantics. File
  inventory fields remain in the explicit `files` index. Stable-key output is
  not assumed to have a one-for-one canonical replacement.
- **Removal and rollback:** migrate readers, prove bounded output and empty/error
  parity, stop writers, retain a compatibility release, then drop. Before the
  destructive migration, rollback is a code/config re-enable; afterward it is
  backup-first restoration plus forward migration.
- **Risk and performance:** premature removal breaks explicit legacy clients;
  indefinite retention adds stage rows, COPY, WAL, indexes, validation, and
  merge work.

### `edges`: legacy compatibility component

- **Writers:** rowwise relationship statements and staged legacy-edge merge in
  `storage/sql_load.py`, `storage/_load_stream.py`, `storage/staged_rows.py`,
  and `storage/staging_merge.py`.
- **Readers:** legacy edges, neighborhoods, file neighborhoods, host-mutator
  records, summaries, and residual legacy status paths.
- **CLI and MCP:** explicit legacy edge and neighborhood modes remain; default
  graph-semantic readback is canonical.
- **Baseline and drift:** current baseline/drift uses canonical edge counts, not
  legacy edge counts.
- **Connectors:** legacy edge reads participate in psql/Psycopg parity.
- **Tests:**
  `src/test/int/python/repomap_kg/storage/legacy_edge_records.int.test.py`,
  `src/test/unit/python/repomap_kg/storage/legacy_edge_records.unit.test.py`,
  `src/test/int/python/repomap_kg/storage/legacy_edges_cli.int.test.py`, and
  `src/test/int/python/repomap_kg/storage/legacy_host_mutators.int.test.py`.
- **Schema and migration:** created by
  `src/main/resources/rdbms/2026/06/28-001-core-create_graph_tables.sql` and
  later given repository-scoped stable identity by
  `src/main/resources/rdbms/2026/06/28-004-core-add_edge_stable_key.sql`.
  Both remain in migration history.
- **Replacement and parity:** canonical edges plus canonical evidence links are
  the semantic replacement. Direction, kind, endpoint, evidence explanation,
  pagination, empty result, and error parity must be explicit.
- **Removal and rollback:** remove legacy edge consumers and writers first,
  then drop `edges` before its referenced legacy node/evidence families.
  Restore only through the accepted backup-first rollback plan after DDL.
- **Risk and performance:** edges are the foreign-key ordering constraint for
  legacy removal and add staging, merge, conflict, index, and WAL cost.

### `evidence`: legacy compatibility component

- **Writers:** rowwise legacy evidence statements and staged legacy-evidence
  merge in `storage/sql_load.py`, `storage/_load_stream.py`,
  `storage/staged_rows.py`, and `storage/staging_merge.py`.
- **Readers:** legacy node/file/edge explanation paths and legacy storage status
  counts.
- **CLI and MCP:** exposed indirectly through explicit legacy readback and
  residual legacy status contracts; canonical evidence is the default graph
  explanation surface.
- **Baseline and drift:** current baseline/drift does not require the legacy
  evidence count.
- **Connectors:** uses the same connector facade as other legacy reads.
- **Tests:**
  `src/test/int/python/repomap_kg/storage/legacy_file_neighborhood.int.test.py`,
  `src/test/unit/python/repomap_kg/storage/legacy_file_neighborhood.unit.test.py`,
  `src/test/unit/python/repomap_kg/storage/legacy_readback/nodes_neighborhoods.unit.test.py`,
  and `src/test/unit/python/repomap_kg/storage/legacy_readback/edges_host_summary.unit.test.py`.
- **Schema and migration:** created by
  `src/main/resources/rdbms/2026/06/28-001-core-create_graph_tables.sql` and
  later given repository-scoped stable identity by
  `src/main/resources/rdbms/2026/06/28-003-core-add_evidence_stable_key.sql`.
  Both historical migrations remain.
- **Replacement and parity:** canonical evidence and evidence links provide
  graph explanation; raw observations preserve authoritative source payloads.
  Legacy evidence stable keys are not canonical evidence keys.
- **Removal and rollback:** remove after legacy edges no longer reference it;
  stop writers only after all consumers have parity. Use backup-first restore
  after destructive DDL.
- **Risk and performance:** premature removal loses legacy explanation fields;
  indefinite retention adds duplicate evidence serialization and merge cost.

### `canonical_nodes`: canonical current component

- **Writers/readers:** canonical row construction and rowwise/staged merge;
  canonical CLI, operations, MCP, summaries, and graph-file readback.
- **CLI, MCP, baseline, and drift:** current default graph-node surface and
  current canonical node count.
- **Connectors and tests:** common psql/Psycopg connector; coverage includes
  `src/test/int/python/repomap_kg/storage/psycopg_parity/canonical_nodes.int.test.py`
  and `src/test/unit/python/repomap_kg/storage/canonical_readback/queries.unit.test.py`.
- **Schema/migration:** created by
  `src/main/resources/rdbms/2026/06/29-002-core-create_canonical_graph_tables.sql`;
  migration remains.
- **Replacement/parity/removal/rollback:** no replacement or removal planned.
  Legacy-node parity gates concern public behavior, not row identity.
- **Risk/performance:** identity aggregation is deliberate; deterministic merge
  and indexed readback remain required.

### `canonical_edges`: canonical current component

- **Writers/readers:** canonical row construction and rowwise/staged merge;
  canonical edge, neighborhood, summary, and explanation readback.
- **CLI, MCP, baseline, and drift:** current default graph-edge surface and
  current canonical edge count.
- **Connectors and tests:** common connector; coverage includes
  `src/test/int/python/repomap_kg/storage/psycopg_parity/canonical_edges.int.test.py`
  and `src/test/int/python/repomap_kg/storage/canonical_readback/cli.int.test.py`.
- **Schema/migration:** canonical graph migration plus additive edge-kind
  migrations listed above; all remain.
- **Replacement/parity/removal/rollback:** no replacement or removal planned.
  Legacy parity covers behavior and evidence explanation, not stable-key shape.
- **Risk/performance:** set merge and endpoint validation must remain bounded and
  deterministic.

### `canonical_evidence`: canonical current component

- **Writers/readers:** canonical row construction and merge; canonical
  explanation and source-aware readback.
- **CLI, MCP, baseline, and drift:** used by graph explanation whose embedded
  evidence cardinality is not consistently capped; not a
  separate baseline scalar today.
- **Connectors and tests:** common connector; exercised by canonical readback,
  edge explanation, and staging merge tests, including
  `src/test/int/python/repomap_kg/storage/canonical_readback_profiles/edge_explanations.int.test.py`.
- **Schema/migration:** created by the canonical graph migration, which remains.
- **Replacement/parity/removal/rollback:** no removal planned. Preserve exact
  raw-observation reference validation.
- **Risk/performance:** evidence growth is run-scoped; retention and indexing
  must not weaken provenance.

### `canonical_node_evidence`: canonical current component

- **Writers/readers:** canonical rowwise/staged link merge and canonical node
  explanation/readback.
- **CLI, MCP, baseline, and drift:** indirectly public through canonical
  explanation; not a baseline scalar.
- **Connectors and tests:** common connector; targeted evidence includes
  `src/test/int/python/repomap_kg/storage/scale9h_node_evidence_guard.int.test.py`
  and `src/test/int/python/repomap_kg/storage/scale9l_node_evidence_merge.int.test.py`.
- **Schema/migration:** created by the canonical graph migration, which remains.
- **Replacement/parity/removal/rollback:** no removal planned. Logical-link
  deduplication is the accepted identity, not family ordinal.
- **Risk/performance:** this has been a material merge hotspot; grouped logical
  links and targeted statistics are accepted performance boundaries.

### `canonical_edge_evidence`: canonical current component

- **Writers/readers:** canonical rowwise/staged link merge and canonical edge
  explanation/readback.
- **CLI, MCP, baseline, and drift:** indirectly public through edge
  explanation; not a baseline scalar.
- **Connectors and tests:** common connector and canonical edge-explanation
  coverage.
- **Schema/migration:** created by the canonical graph migration, which remains.
- **Replacement/parity/removal/rollback:** no replacement or removal planned;
  preserve logical-link and endpoint-reference validation.
- **Risk/performance:** link multiplicity can amplify merge cost; deduplication
  must remain deterministic and evidence-complete.

## Complete Legacy And Compatibility Surface Classification

Every candidate named by ARCH0 appears exactly once below and uses exactly one
allowed classification. "Users" covers production readers plus CLI, MCP,
baseline/drift, and connector consumers. The exhaustive persisted-family
entries above provide row-level detail.

| Candidate | Exact classification | Writers and users | Evidence, schema, and migration | Replacement and parity | Removal, rollback, risk, and performance |
| --- | --- | --- | --- | --- | --- |
| `files` storage and current file/source APIs | `current first-class derived component` | Rowwise/staged file merge; summaries, inventory, baseline/drift, and legacy joins; public graph-file queries combine file and canonical evidence | Core graph/file-run migrations; `storage/staging_merge.py`; graph-file, summary, and baseline/drift tests | No complete replacement; canonical file nodes replace graph identity only | Retain. A later replacement must be additive, field/latency complete, and reversible. Current cost is one stage/final family and indexes. |
| Legacy `nodes` | `replaceable after a bounded compatibility adapter` | Rowwise/staged writers; node/neighborhood/file/status readers; explicit legacy CLI and connector parity | Core graph migration; `storage/legacy.py`; legacy-node/neighborhood and legacy-mode tests | Canonical nodes plus file/source index; prove filters, ordering, empty/error, and compatibility output | Reader migration before writer shutdown; rollback by writer re-enable before DDL or backup-first restore after DDL. Retention adds COPY/validation/merge/WAL/index work. |
| Legacy `edges` | `replaceable after a bounded compatibility adapter` | Rowwise/staged writers; edge, neighborhood, host-mutator, status, CLI, and connector users | Core graph and edge-stable-key migrations; legacy edge/host-mutator tests | Canonical edges/evidence; prove direction, kind, endpoints, explanation, and bounds | Remove readers/writers before forward drop, then backup-first rollback. It constrains FK order and adds high row/index amplification. |
| Legacy `evidence` | `replaceable after a bounded compatibility adapter` | Rowwise/staged writers; file/node/edge explanation and status users | Core graph and evidence-stable-key migrations; legacy evidence/readback tests | Raw observations plus canonical evidence; prove location, multiplicity, ordering, and redaction | Remove after edge consumers, before/with nodes. Backup-first rollback after DDL. Adds stage/final storage and joins. |
| Row-wise ingestion | `remove after caller closure` | No supported caller; only two programmatic compatibility exports and their direct tests remain | `storage/main.py`, `storage/sql_load.py`, `storage/_load_stream.py`, row-wise compatibility tests, and the ARCH3E/ARCH4B census | Complete input uses staged publication; partial acquisition returns versioned non-publication; canonical-only CLI and row-wise SCALE7 baseline are retired | Remove both primitives and facade exports in ARCH4C. Revert ARCH4B before that boundary to restore callers. It duplicates transformations and row-shaped writes. |
| Legacy graph summaries | `replaceable by an existing canonical contract` | Read-only summary/status users; no separate writer beyond persisted legacy families | `ops/reports.py`, server status projections, summary tests | File/raw/canonical counts already supply baseline/drift; version residual schemas | Remove legacy fields through announced schema boundary. Rollback retains adapter fields. Query/count cost disappears with tables. |
| Legacy neighborhoods and file neighborhoods | `replaceable after a bounded compatibility adapter` | Explicit legacy CLI; connector adapters execute equivalent SQL | `storage/legacy.py` and legacy neighborhood/file-neighborhood tests | Canonical neighborhood plus file/source lookup; prove depth, direction, kind, ordering, bounds, empty/error, and evidence | Migrate first; retain one compatibility window. Performance risk is legacy joins and unbounded result shapes. |
| Legacy entrypoints | `replaceable after a bounded compatibility adapter` | Explicit legacy CLI/readback and compatibility tests | Legacy entrypoint SQL/readback and `legacy_readback_cli/files_entrypoints.int.test.py` | Canonical entrypoints plus file/source projection | Announce schema/ordering differences; revert to adapter during window. Removing legacy tables removes duplicate indexes. |
| Legacy host-mutator views | `replaceable after a bounded compatibility adapter` | Legacy CLI/storage users and tests; canonical consumers use canonical graph semantics | `storage/legacy.py`, legacy host-mutator tests, canonical shell-family tests | Canonical host-mutation nodes/edges/evidence with compatibility shaping | Prove category/tool/path-free parity; retain boundary adapter until migration. Legacy join cost is removable. |
| Legacy connector adapters | `required compatibility projection` | Psql/Psycopg comparison and legacy readback tools; no semantic writer | `storage/readback_driver.py`, `tools/compare_pg_connectors.py`, parity tests | Common shape-validated canonical/source readback | Remove only after legacy queries retire; keep connector rollback separate. Cost is maintenance and duplicate SQL. |
| Compatibility CLI commands and flags | `requires a public breaking decision` | Explicit legacy-mode users/automation; dispatch calls compatibility readback | CLI parser/dispatch and legacy-mode unit/integration tests | Canonical/source commands with bounded versioned schemas | Deprecate and announce; preserve aliases during a window. Risk is automation breakage; performance follows legacy reads. |
| Compatibility JSON/table schemas | `requires a public breaking decision` | CLI/status consumers; MCP uses separate versioned envelopes | CLI result formatters, schema goldens, MCP JSON-RPC tests | One bounded canonical/source result contract with stable ordering/pagination | Version rather than silently mutate; rollback retains serializer. Cost is duplicate formatting and tests. |
| Old public aliases and compatibility facades | `required compatibility projection` | Imports may be static, dynamic, test-only, or external; facades re-export names | Package facade modules, import tests, and the AST consumer inventory | Direct module imports after a consumer census | Remove only proved-unused names after announcement. Rollback restores re-exports; main cost is layering constraint. |
| Superseded refresh paths | `required compatibility projection` | Programmatic rowwise callers and explicit mode adapters; no hidden fallback | `src/main/python/repomap_kg/ops/refresh.py`, `src/main/python/repomap_kg/ops_refresh.py`, coordinator adapter, and mode/parity tests | One staged semantic implementation with explicit orchestration modes | Retire duplicate transformation/write path, not direct mode. Rollback keeps adapter. Cost is duplicate maintenance and row-shaped execution. |
| Transitional database columns | `misleadingly named but not legacy` | Run/stage/receipt readers and publication/reconciliation writers | Publication-generation/attempt and SCALE staging migrations; receipt/fencing tests | Typed receipt/owner models may clarify concepts without rewriting history | Do not drop by label. Assess through forward migration and reader inventory. Naming can confuse job/operation/attempt semantics; storage cost is small. |
| Transitional configuration fields | `required compatibility projection` | Parser/resolver, runtime/service renderers, direct/coordinator callers | `ops/config.py` and config unit/integration tests | One resolved typed model with compatibility parsing | Remove after versioned config migration and warnings. Rollback retains aliases. Cost is resolution branches and generation complexity. |
| Historical migration files | `historical migration that must remain` | Initialization/upgrade tooling; never runtime graph readers | Both migration changelogs and all applied SQL migrations | New forward migrations only | Never delete or rewrite. Rollback is backup-first plus an accepted migration procedure. No post-application runtime cost. |

No candidate is classified `dead and safely removable` from static search
alone. Dynamic registration, CLI dispatch, facade imports, subprocess
entrypoints, configuration loading, tests, and migration history remain part of
the consumer census.

## Ordinal Model Decision

### Ordinal Model A: typed explicit family descriptors

Ordinal Model A keeps two explicit ordinal domains:

- `source_ordinal` is the run-local provenance identity of a raw observation.
  It becomes final `raw_observations.ordinal` and is referenced by canonical
  evidence.
- `family_ordinal` is a stage-local proposal order for one non-raw staging
  family. It supports deterministic transfer, proposal selection, and bounded
  diagnostics. It is not provenance and is not a canonical identity.

The staging COPY registry is the type boundary that declares which ordinal a
family owns. Raw rows use `source_ordinal`; the other nine staging families use
`family_ordinal`. Checksums use the declared logical family identity, not an
assumed universal ordinal.

**Ordinal Model A is selected.** Evidence is in:

- `src/main/python/repomap_kg/storage/canonical_rows.py`
- `src/main/python/repomap_kg/storage/staged_rows.py`
- `src/main/python/repomap_kg/storage/staging_copy.py`
- `src/main/python/repomap_kg/storage/staging_checksums.py`
- `src/main/python/repomap_kg/storage/staging_merge.py`
- `src/main/python/repomap_kg/storage/canonical_staging_merge.py`
- `src/main/resources/rdbms/2026/07/14-001-scale1-create_staging_contract.sql`

### Ordinal Model B: common technical staging ordinal

Model B gives every staging family a common `stage_row_ordinal`. Raw rows also
retain unique `source_ordinal` because final raw identity remains
`(run_id, source_ordinal)`. For the other nine families,
`stage_row_ordinal` replaces the physical `family_ordinal` name while retaining
its stage-local proposal-order semantics.

The common name simplifies generic COPY descriptors only at the technical row
position. It does not make the underlying semantics common: raw still needs a
second product-semantic ordinal, while proposal ordering remains family-local.
The change therefore adds a redundant raw column and requires forward DDL,
COPY, checksum, validation, merge, and test-contract churn without a current
consumer that needs a universal transfer ordinal.

Ordinal Model B is not selected.

### Ordinal Model C: one ordinal domain for every family

Model C would either make raw provenance depend on family transfer order or
propagate one source ordinal into every derived family. The first option erases
the explicit provenance identity. The second is invalid for canonical rows
that aggregate multiple raw observations and therefore have no single source
ordinal.

Ordinal Model C is not selected.

## Naming and Identity Inconsistency Ledger

| Current term or behavior | Classification | Required ARCH0 interpretation | Future action |
| --- | --- | --- | --- |
| `files` beside legacy graph tables | `harmless naming debt` | Physical age/placement does not make the current file/source index legacy | Document consistently; rename only with API/schema migration evidence |
| `storage.legacy` source helpers | `maintainability defect` | Classify a query by its data authority, not module placement | Move or rename through a behavior-preserving seam |
| Legacy `stable_key` versus canonical node/edge key | `justified semantic distinction` | They encode different identity models; row-for-row key parity is not expected | Migrate public behavior rather than key strings |
| Legacy evidence `stable_key` versus canonical `evidence_key` | `justified semantic distinction` | Raw observations are provenance authority; canonical evidence normalizes explanation identity | Do not expose one as an alias for the other |
| `ordinal`, `source_ordinal`, `raw_observation_ordinal`, `family_ordinal` | `correctness risk` | Provenance, raw references, and proposal order are separate domains | Apply typed Ordinal Model A and qualify every domain |
| `job_id`, `operation_id`, `request_id`, `run_id`, `stage_id`, and `attempt` | `compatibility constraint` | Request intent, local/durable operation, execution attempt, graph run, and stage are distinct; historical receipt slots do not erase the distinction | Define a versioned identity glossary and typed records before public/schema renaming |
| Configured `graph_id` versus database `repository_id` | `justified semantic distinction` | Graph ID is configured/public identity; repository id is graph-database-local storage identity | Reject cross-graph numeric identity use and keep database ids private |
| Configured root path versus repository identity | `compatibility constraint` | A mutable/private path locates source; configured staged refresh now resolves the stable identity and updates that path, while retained callers may omit identity for root-keyed behavior | Complete ARCH5C3 baseline/drift and backup restoration acceptance; keep public identity independent from absolute paths |
| Schema-version fields across config, worker, MCP, baseline, and migrations | `compatibility constraint` | Each versions a different contract and must name that contract | Keep independent versioning but establish one registry and upgrade policy |
| Extractor/canonicalizer versions versus generation values | `justified semantic distinction` | A version labels implementation/protocol; a generation fences the exact accepted execution state | Use explicit `*_version` and `*_generation` names; never compare across domains |
| Four generation token names across jobs, stages, runs, and receipts | `maintainability defect` | The tuple is one publication-fencing contract even when represented in several records | Define one typed generation tuple and field-order invariant |
| UTC timestamps and database/Python timestamp types | `maintainability defect` | Durable instants are timezone-aware UTC; elapsed time is monotonic duration, not a timestamp | Normalize names (`*_at`, `*_elapsed_seconds`) and serialization without rewriting historical columns |
| Byte, row-count, duration, memory, WAL, and temporary-storage units | `correctness risk` | Every resource field requires an explicit base unit and bounded integer/range | Add typed unit suffixes and validation; never compare samples from different intervals as one percentage |
| Nullable coordinator identities in direct stages and required identities in coordinator stages | `justified semantic distinction` | Null is valid only for explicit direct mode; coordinator mode requires job/instance/fences | Put conditional nullability in the typed owner descriptor and database checks |
| Result, status, stage-state, job-state, and error-category vocabularies | `maintainability defect` | These are different closed state machines/projections, not interchangeable success strings | Publish closed enums and explicit translations at presentation boundaries |
| Direct versus coordinator result schemas | `architectural duplication` | Graph outcome semantics must match; scheduler/progress fields may differ explicitly | Define one semantic refresh result plus mode-specific orchestration envelope |
| CLI table versus CLI JSON semantics | `compatibility constraint` | Table is presentation; JSON is the machine contract. Both need stable ordering and equivalent facts | Version JSON, test table/JSON parity, and announce incompatible defaults |
| MCP versus CLI readback semantics | `architectural duplication` | MCP must adapt the same bounded application query contract, not define graph semantics independently | Move schema-neutral query/result contracts below both presentations |
| Staging family dictionaries/descriptors | `correctness risk` | Families differ in ordinals, identity, nullability, duplicate/proposal, checksum, validation, merge, retention, and privacy | ARCH2 defines one closed typed descriptor per family |
| Singular/plural table, model, and family terminology | `harmless naming debt` | Some plural table and singular row-model names are conventional; only ambiguous semantic names require migration | Adopt a glossary and avoid cosmetic DDL/API churn |
| Private, redacted, public-safe, and bounded projection names | `maintainability defect` | Privacy classification and output shape are separate from graph authority | Define one policy vocabulary and schema-specific pure projections |
| Direct operation in the historical receipt attempt slot | `compatibility constraint` | A direct operation is not a coordinator attempt; the slot is receipt-schema compatibility | Version later if needed without rewriting migration history |
| Singleton and graph-lease fencing values | `resolved correctness risk` | ARCH1C assigns transaction-ordered graph claims independently from singleton succession and registers them graph-side before staged work | Preserve the distinction; use an ARCH5 migration if recovered attempts are ever allowed to republish |
| Stage `validated` | `maintainability defect` | Current validation proves counts and SQL invariants; client digests are transfer receipts | State the narrower contract or separately accept stronger validation |
| Graph-local publication authority | `harmless naming debt` | It is a graph-transaction projection, not a second coordinator | Preserve control database semantic authority |
| Direct and coordinator parity | `resolved correctness risk` | ARCH1C gives both modes one nonblocking graph-local final lock and retains coordinator stale-claim fencing | Preserve the shared lock and receipt-bearing transaction in later normalization |
| `last_seen_run_id` versus canonical first/last run fields | `justified semantic distinction` | File-index recency and canonical observation history are not complete run membership | Do not infer membership parity |

## Historical ARCH0 Authority Mismatches And Accepted Resolution

The following subsections preserve the exact ARCH0 mismatch statements and
their ordering rationale. They are historical decision evidence, not current
runtime claims. ARCH1 through ARCH8 completed the named remediations: one
receipt-bearing publication authority, stable relocatable repository identity,
collision-free exact topology, owned upgrade/rollback and complete recovery,
and shared direct/coordinator exclusion. The current matrices above and the
ARCH8 acceptance inventory below are authoritative for ARCH-CLOSE.

### Latest run and receiptless final mutation

`storage/publication_readback.py::read_latest_publication` selects the newest
complete run carrying every receipt field. By contrast,
`ops/refresh_sql.py::build_refresh_status_sql`,
`ops/refresh_sql.py::build_graph_summary_sql`,
`ops/config.py::build_graph_storage_status_sql`, and
`storage/sql_canonical.py::build_canonical_storage_summary_query_sql` select the
highest run id without requiring a complete receipt. Historical and
programmatic row-wise primitives can commit final-table mutations and a
complete run without a receipt, so the three named concepts remain part of the
compatibility model. ARCH4B leaves no supported caller that can create that
divergence; ARCH4C removes the uncalled primitives.

ARCH1 must name and freeze `latest recorded run`, `latest successful import`,
and `latest receipt-bearing publication` as distinct concepts where the product
needs all three. Every final-table mutation command must then migrate either to
the staged receipt-bearing publication contract or to an explicitly versioned
acquisition-only contract that does not mutate final graph state. Commands that
cannot preserve their supported behavior under either contract require an
announced retirement. This is a bounded compatibility normalization; it must
not fabricate receipts for work that did not satisfy staged publication
preconditions.

### Repository identity follows a relocatable path

The initial graph schema makes `repositories.root_path` unique. Both
`storage/sql_load.py::repository_run_prefix_sql` and
`storage/staged_ingestion.py::_ensure_repository` upsert with `ON CONFLICT
(root_path)`. A checkout moved to a different absolute path therefore creates a
new repository row even when the configured graph and repository identity are
unchanged. Forced-full replacement is scoped to the new row, so the old row and
its graph data remain durable and can still affect database-wide storage,
backup, and ownership expectations.

ARCH1 must separate stable configured repository identity from mutable source
location and define collision, relocation, compatibility, and migration rules
without mutating existing schema or rows. ARCH5 must first establish the
product-owned upgrade authority, then add the stable identity and migrate or
merge preexisting path-keyed rows with rollback evidence. Relocation tests must
cover row-wise and staged paths, final-family replacement, readback,
baseline/drift, and absence of stranded old rows without exposing absolute
paths in public results.

### Dedicated database topology and destructive ownership

Graph parsing validates graph-ID uniqueness and database-name syntax, but a
graph may omit `database` and inherit the global PostgreSQL database. Duplicate
effective database names are not rejected, so multiple graphs can share one
database despite the accepted dedicated topology. This also prevents exact
graph-to-database ownership enumeration.

`runtime/backup.py::validate_drop_database_name` rejects template databases and
conditionally `postgres`, but it does not compare the requested name with the
resolved graph/control inventory. After backup-first confirmation, another
existing safe-named database inside the RepoMap-labeled container can be
dropped. Container ownership, safe syntax, and a verified backup mitigate the
operation but do not authorize that database.

Drop takes its dump and verifies it before terminating database backends, with
no writer admission/drain lock spanning the snapshot through destruction. A
concurrent commit after the dump snapshot can therefore be missing from the
verified recovery artifact and then destroyed. Exact ownership must be paired
with an executable maintenance fence and stable recovery point.

ARCH1 must resolve and reject graph database collisions, reject graph/control
use of template or maintenance database names, keep a separate maintenance
connection target, keep the control database distinct, and produce one exact
owned-database allowlist. ARCH7 must apply it to initialization, upgrade, dump,
restore, and drop, with refusal tests for unrelated databases in the owned
container.

### Schema upgrade and cluster recovery authority

ARCH5 establishes checksummed applied-version ledgers and product-owned
backup-first upgrade/rollback for graph and control schemas.
`runtime/backup.py::init_database_from_source` remains the fresh-target graph
initializer; packaged lifecycle commands advance supported existing targets
only through the versioned authority and require exact-current readiness.

Graph source initialization and dump restore create the target before applying
schema or restoring data. ARCH5B treats only that newly created target as
provisionally owned, requires the exact ordered checksummed graph ledger after
the operation, and removes the target after schema, restore, or readiness
failure. Retry therefore begins from absence. A pre-existing graph database is
still refused without mutation. The control initializer uses one Psycopg
transaction for a database created by the same invocation, removes that
database after initialization or readiness failure, and permits an existing
target only when it is already exact-current. Existing empty, partial, or
divergent control state is rejected without repair or adoption.

`runtime/backup.py::dump_all_databases` and coordinated recovery enumerate the
exact resolved graph/control set and exclude the maintenance database. ARCH7D
streams private `0700`/`0600` artifacts through a hidden staging set, publishes
the complete manifest atomically, refuses incomplete/mismatched sets, restores
graphs in stable order and control last, and bounds failure cleanup. ARCH7E
reconciles declarative roles after restore because archives omit owners and
privileges.

ARCH7F pins the PostgreSQL client/server/Psycopg/libpq matrix. ARCH7G creates
the cluster and every product database with explicit UTF-8/C settings and uses
the separate maintenance target. ARCH8 proves query, dump, restore, upgrade,
rollback, and restart through the packaged clients and complete topology.

### Independent graph-lease fencing

The control schema retains its singleton `fencing_epoch` on coordinator
instances, attempts, and graph leases. ARCH1C additionally derives a distinct
graph-claim capability from the successful control claim transaction. The
refresh adapter carries it unchanged, and staged ingestion registers it in the
existing graph-local authority row in the same transaction as run and stage
creation. Equal claims are idempotent only for the exact owner; a greater graph
claim fences an older claim even when the singleton epoch is equal.

The control schema does not redundantly persist the distinct capability.
Startup recovery reconciles an old receipt or queues a new attempt and never
relaunches publication under the old capability. A future recovered-attempt
republish contract would require an ARCH5 versioned migration; ARCH1C does not
introduce unmanaged DDL or misuse an existing control column.

### Direct/coordinator exclusion

Direct and coordinator publication both use the same nonblocking graph-local
advisory transaction lock immediately before prepare and merge. Contention is
rejected before any stage, run, receipt, authority, or graph mutation.
Coordinator publication additionally revalidates its durable graph-local claim
under row lock. The orchestration models remain different; final mutation
exclusion and receipt semantics are shared.

### Checksum terminology

Staged family checksums are deterministic transfer receipts computed during
row construction. Stage validation compares observed and expected counts, and
publication requires a complete manifest and checksum map. The graph database
does not independently recompute the family payload checksums. Documentation
must not describe the current checksum as proof against same-count stage-row
mutation.

## Completed Safe Ordered Decommissioning Sequence

This sequence is retained as the migration rationale. ARCH1 through ARCH5E
completed it in order; historical migrations and status records remain, while
the retired runtime schema, writers, and public facades do not.

Legacy decommissioning is a separate implementation program. ARCH0 establishes
this order:

1. **Freeze the authority inventory.** Treat `raw_observations` as evidence,
   `files` as the explicit current index, canonical families as graph
   authority, and legacy nodes/edges/evidence as compatibility only.
2. **Inventory every consumer.** Reconfirm source writers, rowwise and staged
   writers, SQL readers, Python facades, CLI commands and flags, MCP/server
   routes and schemas, baseline/drift fields, connectors, fixtures, tests,
   migrations, status docs, and operator documentation.
3. **Specify replacement contracts.** Record identity, filters, direction,
   pagination, ordering, explanation, ambiguity, empty-result, error,
   redaction, bounded-output, and connector semantics. Do not promise legacy
   stable-key parity where the canonical model intentionally differs.
4. **Close residual public readers.** Migrate or version legacy MCP status and
   explicit legacy CLI paths. Preserve separately named raw/source readback and
   the file/source index.
5. **Prove connector and mode parity.** Run psql/Psycopg readback comparisons,
   rowwise/staged final-family parity, and direct/coordinator shared-ingestion
   parity. Census and migrate `storage load-files`, `storage load-canonical`,
   feed/archive/WARC/bulk/API/GitHub acquisition, and programmatic row-wise
   callers to receipt-bearing complete publication or acquisition-only input
   that does not mutate final graph state; otherwise retire the command through
   an announced boundary. Add tests for every replacement and for legacy-mode
   rejection after removal.
6. **Measure the compatibility tax.** Record stage row counts, bytes, COPY
   time, WAL, index size, validation time, merge time, and cleanup time for the
   three legacy families using public-safe small, medium, and full fixtures.
   Do not infer savings from row counts alone. Protected evidence remains a
   later SCALE concern after ARCH-CLOSE.
7. **Normalize run and mutation authority.** Make latest-recorded-run and latest
   receipt-bearing-publication projections explicit. Prove that public imports
   cannot silently supersede staged freshness, and preserve their documented
   acquisition or complete-replacement semantics through versioned adapters.
8. **Stop legacy reads before writes.** Ship at least one compatibility window
   in which supported readers use canonical/source/index contracts while
   legacy writers still make rollback possible.
9. **Stop legacy writers.** Remove legacy row construction, rowwise statements,
   COPY descriptors, manifest families, validation entries, merge statements,
   and cleanup clauses together. Keep raw, file-index, and canonical writes
   unchanged. **Completed by ARCH4C:** the active manifest now contains seven
   file/raw/canonical families and production contains no legacy final writer.
10. **Verify no dependencies.** Require zero production readers/writers, no MCP
   or CLI schema references, no baseline/drift dependency, connector parity,
   full unit/integration gates, compileall, file-length, dependency, and diff
   checks. **ARCH4D accepts the writer-transition subset:** migrated readers,
   exact direct/coordinator normalized parity, unchanged recovery behavior,
   retained-table rollback, and the seven-family resource shape. ARCH5 still
   owns schema/API decommissioning verification.
11. **Establish upgrade and recovery authority, then apply forward DDL.** Add a
    product-owned applied-version ledger and backup-first graph/control upgrade
    operation. Enter an executable maintenance state that rejects new
    coordinator/direct/import work, drains or quarantines active attempts and
    stages, reports schema-upgrading as not ready, and holds an owned database
    lock. Prove retry/recovery from partial graph init/restore and, for every
    database changed by ARCH5, exact target ownership, a verified backup/restore
    path, and rollback from the prior supported schema. Only then drop legacy
    `edges`, followed by legacy `evidence` and `nodes`, in the foreign-key-safe
    order established by a new forward migration. Cluster-wide exact owned
    enumeration and coordinated stable-recovery-point backup/restore remain
    ARCH7 acceptance rather than a prerequisite for a correctly scoped
    per-target ARCH5 migration. Commit transactional DDL and the applied-version
    ledger update together; otherwise document and test the nontransactional
    recovery class. Do not drop `files`, raw observations, or canonical
    families.
    **Completed by ARCH5D:** the guarded migration requires stable repository
    identity, narrows the default manifest to seven retained families, drops
    legacy stage tables and then final `edges`, `evidence`, and `nodes`, and is
    accepted by backup, restore, relocation, no-drift, and reapply evidence.
12. **Retain history.** Never delete or rewrite the historical migrations,
    ADRs, or status records that created and evolved the legacy tables. Add a
    new forward migration and a durable closeout record.
13. **Rollback safely.** Before destructive DDL, rollback means restoring the
    prior code/config and re-enabling legacy readers. After destructive DDL,
    rollback requires the accepted backup-first restore path or a new forward
    reconstruction migration; it is not an ad hoc table recreation.
14. **Remove expired compatibility APIs.** Remove legacy graph adapters,
    aliases, flags, result schemas, connector operations, and their obsolete
    tests after the announced boundary and consumer census. Retain current
    canonical graph and file/source readback.
    **Completed by ARCH5E:** production exposes one canonical graph API;
    obsolete compatibility imports and command forms are absent or rejected,
    while historical migrations and status records remain intact.

## Required Parity and Verification Evidence

ARCH5E replaces the expired compatibility tests with absence, rejection, and
current-contract evidence:

- obsolete module/import absence, parser rejection, and canonical-only summary
  contracts:
  `src/test/unit/python/repomap_kg/storage/arch5e_obsolete_compatibility_removal.unit.test.py`;
- current canonical readback and connector parity:
  `src/test/int/python/repomap_kg/storage/canonical_readback/cli.int.test.py`,
  `src/test/int/python/repomap_kg/storage/psycopg_parity/canonical_nodes.int.test.py`,
  `canonical_edges.int.test.py`, `summary.int.test.py`, and
  `src/test/int/python/tools/compare_pg_connectors.int.test.py`;
- baseline, drift, graph storage, and summary contracts:
  `src/test/unit/python/repomap_kg/ops_refresh/baselines_drift.unit.test.py`,
  `src/test/int/python/repomap_kg/ops/graph_storage_readback.int.test.py`, and
  `graph_summary_readback.int.test.py`;
- current MCP graph tools:
  `src/test/unit/python/repomap_kg/mcp_server/storage_canonical_tools.unit.test.py`;
- staging, publication, cleanup, and shared-ingestion behavior:
  `src/test/int/python/repomap_kg/storage/scale1_staging_migration.int.test.py`,
  `scale2_staging_copy.int.test.py`, `scale3_staging_merge.int.test.py`,
  `scale4_canonical_staging_merge.int.test.py`,
  `scale5_publication_fencing.int.test.py`,
  `scale6_staging_cleanup.int.test.py`, and
  `scale8_staged_ingestion.int.test.py`; and
- coordinator capability parity:
  `src/test/unit/python/repomap_kg/coordinator/refresh_adapter.unit.test.py`.

Passing tests establish implementation evidence only. Removal also requires a
consumer inventory, compatibility decision, migration/rollback plan, and
measured performance evidence.

## Performance Interpretation

The selected Model B removes avoidable permanent duplication without treating
all duplicated data as waste:

- raw observations are retained because provenance and replay are product
  semantics;
- the file/source index is retained because inventory and graph identity are
  different responsibilities;
- canonical evidence links are retained because graph explanation requires
  normalized associations; and
- staging duplication is retained only for a bounded operation lifecycle so
  COPY, validation, and atomic publication remain possible.

ARCH4C removed the writer-side performance tax from the legacy graph projection:
legacy row construction, three stage families, COPY traffic, WAL, index
maintenance, validation, merge, and cleanup. ARCH5D removed the retained runtime
schema, and ARCH5E removed its compatibility read and presentation adapters. A
controlled size-4 public-safe
ARCH4B/ARCH4C comparison reduced deterministic staged rows from 73 to 49,
encoded transfer/merge bytes from 40,834 to 30,434, client data-plane
statements from 29 to 22, inserted rows from 146 to 98, and observed WAL bytes
from 92,361 to 64,317. Single-sample timing and resource values are
observational; ARCH4D accepts the deterministic shape while later ARCH6/ARCH8
gates retain optimization and integrated acceptance authority.

## ARCH8 Integrated Acceptance Inventory

ARCH8 adds no data authority, persisted projection, compatibility facade,
schema, or migration. Its closed acceptance catalog is test orchestration, not
a runtime source of truth. The catalog points to existing executable evidence;
its output is a bounded public-safe result projection.

Operational dogfood creates only disposable raw observations, canonical staged
families, complete receipt-bearing publications, and transient measurement
events under the existing authorities. The small, mixed, self-host, and public
full-repository rungs retain raw/source facts and the first-class file/source
index. The public full-repository rung proves repeated complete publication
without introducing a target-specific identity or durable test database into
committed evidence.

The ARCH8 lifecycle correction changes transport only. The same exact
graph/control allowlist, manifests, checksums, restore order, roles, and
PostgreSQL data remain authoritative. `REPOMAP_ADMIN_ROOT` selects the private
artifact root only in the rendered one-shot capability; the rendered runtime
hash and immutable release-image marker bind the internal adapter to the owned
cluster. Neither value becomes a public or persisted graph identity.

## Decision Summary

- Select target **Model B**: raw/source facts, one canonical graph, and one
  explicit file/source index.
- Preserve `raw_observations` as authoritative evidence.
- Preserve `files` as a current first-class derived component; it is not a
  legacy graph family.
- Treat legacy `nodes`, `edges`, and `evidence` as retired historical semantics.
  ARCH5D removes their persisted runtime families, and ARCH5E removes the
  remaining API/facade boundary.
- Preserve canonical nodes, edges, evidence, and evidence links as the current
  graph.
- Select **Ordinal Model A**, with typed family descriptors and distinct
  `source_ordinal` and `family_ordinal` semantics.
- Rowwise storage/source compatibility mutation is retired. Complete callers
  use staged publication, partial acquisition is non-publishing, incompatible
  surfaces use announced retirement, and production exposes no row-wise graph
  writer.
- Enforce a unique effective database per graph; define stable configured
  repository identity in ARCH1; and apply its path-keyed relocation migration
  only after ARCH5's upgrade/rollback authority is operational.
- Derive exact graph/control ownership and reject destructive lifecycle targets
  outside that allowlist; container ownership is not database authorization.
- Preserve graph/control database separation and strengthen graph-lease and
  cross-mode publication fencing in later accepted phases.
- Retain every historical migration; use only new forward migrations for
  decommissioning.
- Establish product-owned versioned graph/control upgrade and complete owned
  database backup/recovery before applying legacy-removal DDL.
- Do not begin removal until public-reader, connector, baseline/drift, test,
  rollback, and measured-performance gates are complete.
- ARCH8 completes the integrated public-safe acceptance gate. Protected-scale
  evidence remains a separate concern and is not a data-authority change.
- ARCH-CLOSE confirms that no active legacy runtime graph component remains.
  Historical migrations and records are retained as evidence, not runtime
  authority. The normalized target model is the current implementation.
