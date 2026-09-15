# ADR 0041: RepoMap As-Built Architecture, Algorithmic Soundness, And Normalization Strategy

## Title

RepoMap As-Built Architecture, Algorithmic Soundness, And Normalization
Strategy

## Status

Accepted on 2026-07-16.

ARCH-CLOSE accepted the implemented normalization after re-auditing every
finding and resumption gate. Nineteen findings are resolved and one
maintainability finding is accepted debt. No review trigger fired. The exact
result is:

```text
ARCH accepted and closed. SCALE may resume under a separately approved plan.
```

The RepoMap operator accepted this decision and authorized autonomous execution
of the remediation sequence through ARCH-CLOSE. Each implementation phase
remains bounded by this ADR's review triggers, compatibility requirements, and
phase-specific verification.

ARCH1B implements the resolved-topology portion of this decision. The shared
model rejects graph/control/maintenance collisions, exposes the exact private
graph/control allowlist, and defines stable configured repository identity as
`repo1:<graph-id>` independently from root path. Existing schema and rows remain
path-keyed until ARCH5 establishes upgrade authority and performs the additive,
backup-first identity migration.

ARCH1C implements the cross-mode publication-exclusion portion. Direct and
coordinator publication now use one nonblocking graph-local transaction lock.
Coordinator claims additionally carry a transaction-ordered graph capability
distinct from singleton succession, register it durably in the existing graph
authority projection with stage creation, and revalidate it immediately before
the unchanged receipt-bearing final transaction. No schema migration is
introduced; recovered attempts reconcile rather than republish.

## Date

2026-07-16

## Decision owners

- RepoMap operator: architectural acceptance and implementation authorization.
- RepoMap maintainers: evidence accuracy, compatibility, migration, and phase
  execution after authorization.

## Context

RepoMap has accumulated a capable local static-analysis product through
incremental extraction, canonicalization, PostgreSQL, Psycopg, Go extraction,
durable-coordinator, runtime, and high-scale phases. That history preserved
behavior and safety, but it also retained transition surfaces and distributed
some authorities across compatibility and presentation layers.

The SCALE10 campaign proved that publication safety held under a bounded stop:
the attempt did not publish, left no active or commit-unknown stage, and left
no retained graph rows. It did not isolate enough of the staging/COPY/
validation partition to justify a source correction or another protected
attempt. ARCH0 therefore audits committed source as a whole before more
high-scale work.

The detailed evidence is in:

- `docs/specs/as-built-architecture.md`;
- `docs/specs/data-authority-and-legacy-inventory.md`;
- `docs/specs/algorithmic-complexity-and-amplification-ledger.md`; and
- `docs/specs/architectural-findings-and-remediation-map.md`.

Accepted predecessor decisions remain authoritative unless this ADR explicitly
refines their current interpretation. In particular, ADRs 0001, 0003, 0005,
0007, and 0009 govern graph identity and canonical transition; ADR 0039 governs
direct/coordinator execution; and ADR 0040 governs staged, fenced,
receipt-bearing publication.

## Why SCALE is paused

SCALE10 produced a bounded non-acceptance result, not a reproducible product
defect and not permission to retry. The current architecture performs work for
ten retained families, retains both legacy and canonical graph projections,
and crosses several preparation, serialization, checksum, transfer,
validation, and merge boundaries. Those costs must be separated into necessary
correctness work, compatibility work, and removable duplication before another
large campaign.

The disposition is exact:

```text
SCALE remains open but paused after SCALE10.

No SCALE successor is opened while ARCH evaluates and normalizes the
architecture.

No SCALE acceptance, closure, publication, parity, baseline, drift, or GO24
result is implied by ARCH0.
```

## Decision-time as-built architecture

The sections from this heading through "Non-goals" preserve the ARCH0
decision-time baseline, problem statements, target contracts, and authorized
sequence. Future-tense and transitional statements in those sections are
historical rationale. They do not override the current specifications or the
ARCH-CLOSE implementation disposition at the end of this ADR.

RepoMap is a local, deterministic static knowledge-graph builder with one
Python product entrypoint, a controlled packaged Go extraction subprocess,
exactly owned dedicated PostgreSQL graph databases and separate control state,
an optional durable Python coordinator, read-only MCP over stdio, a bounded
configuration/storage/schema-readiness HTTP server, a complete Linux container
cluster, and optional user-service adapters.

The forced-full semantic path is:

```text
resolved graph configuration
→ static discovery and filtering
→ language extraction and raw observations
→ deterministic observation spool
→ legacy, raw, file, and canonical row projection
→ durable stage ownership and family transfer
→ validation and set-based merge
→ one fenced transaction with a complete publication receipt
→ readback, baseline, drift, CLI, and MCP projections
```

Direct and coordinator execution share extraction, projection, staged
ingestion, validation, merge, receipt, and commit-unknown reconciliation.
Their orchestration differs: direct mode uses an explicit local operation and
advisory transaction serialization; coordinator mode uses durable jobs,
attempts, graph leases, singleton fencing, bounded worker capabilities, and a
graph-local fencing projection.

Separate supported storage and source-acquisition commands do not use that
staged path. `storage load-files`, `storage load-canonical`, feed/archive/WARC
imports, bulk import, API acquisition, and GitHub acquisition call row-wise
loaders that directly upsert final families and create a normally receiptless
run transaction. They provide neither forced-full replacement nor the staged
manifest, fence, validation, receipt, and commit-unknown contract. This is an
active transitional final-state mutation path and a second meaning of
"complete run," not staged publication.

## Intended versus implemented architecture

| Subsystem | Documented intent | Implemented source and executable evidence | Classification |
| --- | --- | --- | --- |
| Canonical graph | Canonical identity is the sole graph authority and public graph readback model. | ARCH5D removes persisted legacy stage/final graph families; ARCH5E removes the expired compatibility API/facade boundary while retaining the current file/source index. | No material mismatch |
| File/source model | File identity supports discovery, status, and source-oriented reads. | `files` remains a materialized index with language, role, hash, and last-seen state. | `implementation is authoritative and docs are stale` where files are grouped with legacy graph families |
| Raw evidence | Raw observations remain replay/explain evidence. | Run-scoped raw rows remain stored and canonical evidence preserves raw ordinals. | `implementation is authoritative and docs are stale` only where raw is described as temporary |
| Async execution | One semantic worker, durable optional coordinator, explicit direct mode, no fallback. | Shared refresh/storage implementation with different orchestration adapters. | `implementation is authoritative and docs are stale` where early target prose remains |
| Row-wise imports and source acquisition | Current graph mutation and freshness use staged, fenced, receipt-bearing publication. | Eight public commands plus programmatic callers directly mutate final families and normally create receiptless complete runs. | `implementation is transitional` |
| Latest run | One explicit freshness meaning follows accepted publication. | Generic status/summary selects highest run ID; receipt readback selects newest complete fully receipted run. | `implementation is ambiguous` |
| Publication | Durable stage, COPY, validation, one final transaction, receipt and fencing. | Implemented and functionally covered; fine-grained high-scale attribution is incomplete. | `implementation is ambiguous` for performance, not semantics |
| HTTP/MCP | Local service direction with read-only MCP. | HTTP exposes health/status only; MCP remains a distinct stdio JSON-RPC process. | `documentation describes an unimplemented target` where HTTP is called MCP |
| HTTP privacy | Public status is path-free and subject to explicit output limits. | ARCH7B exposes only schema-version 1 allowlisted status values and bounded counts; graph probes cap at 200 and serialized responses cap at 8 KiB. | No material mismatch |
| Container deployment | Local PostgreSQL plus explicit HTTP, MCP, coordinator, and one-shot lifecycle units in an owned runtime. | ARCH7G composes the complete cluster from ARCH7F artifacts with persistent data, read-only config/source mounts, narrow writable state, per-unit secrets, and loopback-only HTTP publication. ARCH8 integrates its fresh/restart/recovery evidence with the complete public-safe repository ladder. | No material mismatch |
| Database topology and repository identity | One database per graph; checkout relocation preserves stable configured identity. | ARCH1B rejects collisions and defines `repo1:<graph-id>` independently from root path; ARCH5C1 adds the nullable stable slot; ARCH5C2A reconciles existing family ownership to one configured-root survivor after verified backup; ARCH5C2B makes configured staged writers identity-keyed while preserving explicit root-keyed compatibility; ARCH5C3 accepts no-drift restore and reconstruction; ARCH5D refuses destructive DDL until identity is stable. | No material mismatch |
| Database lifecycle and recovery | Existing graph/control schema upgrade, exact ownership, complete backup/restore, and retryable provisioning. | ARCH5 and ARCH7C through ARCH7E implement versioned upgrade, exact admission/exclusion, private atomic coordinated recovery, retry cleanup, and role reconstruction; ARCH7F installs the same migration/client authority; ARCH7G deploys idempotent fresh/current and backup-first supported-forward one-shot lifecycle; ARCH8 integrates the complete upgrade/recovery evidence. | No material deployed-lifecycle mismatch |
| Cluster privilege and readiness | Long-running units are least-privilege and become ready only after storage/schema readiness. | ARCH7B separates readiness signals; ARCH7E separates credentials; ARCH7G projects per-unit secrets and gates HTTP, MCP, and coordinator on PostgreSQL health plus completed exact-current graph/control initialization or upgrade. | No material mismatch |
| Source distribution | Installable Python distribution with runtime resources. | ARCH7F packages both migration catalogs as wheel data, resolves installed resources outside a checkout, and installs the distribution into an immutable image. | No material release-resource mismatch |
| Direct/coordinator authority | One semantic implementation and graph-local mutation serialization. | Semantic work is shared, but direct and coordinator exclusion use different authority mechanisms whose accepted cross-layer sequencing preconditions are not proved as one invariant. | `implementation is ambiguous` until one enforceable exclusion contract is proved |
| Early architecture prose | Small initial extraction/storage architecture. | Product now includes canonical, coordinator, service, runtime, platform, and staged-publication subsystems. | `historical documentation is superseded` |

Every material row is expanded with source/test/status evidence in the as-built
baseline. Historical phase records are not rewritten.

## System boundaries

RepoMap accepts configured repository or source artifacts and configuration; it
does not execute target code. It reads source within an allowlisted configured
root, emits deterministic observations, and writes only through RepoMap-owned
graph and control contracts. PostgreSQL, the optional Go helper, local
transport, container runtime, and service managers are adapters at explicit
boundaries.

Target package managers, builds, tests, hooks, generated commands, remote
dependency fetches, and arbitrary worker commands are outside the product
authority. MCP remains read-only. Destructive database and runtime lifecycle
operations remain explicit CLI-owned actions with backup-first rules. Exact
graph/control database allowlisting is the accepted target but is not enforced
by the current container/name guard.

## Process and deployment model

The implemented process units are:

1. `repomap-kg` or `python -m repomap_kg` for CLI operations;
2. an optional package-local Go helper using a versioned bounded JSONL
   subprocess protocol;
3. a foreground durable coordinator with local authenticated transport and
   bounded worker subprocesses;
4. read-only MCP over stdio;
5. a separate HTTP health/status server; and
6. PostgreSQL with the enforced distinct graph/control topology.

### End-user container-cluster decision

The self-contained end-user container cluster **is accepted by ARCH7G**.
Neither the PSYCOPG nor GO dependency requires a different storage engine or
service topology:

- Psycopg can be installed in the RepoMap image while `psql` remains available
  for schema initialization, lifecycle, a future product-owned upgrade path,
  and supported fallback/comparison boundaries;
- the Go helper is a standard-library executable behind a versioned JSONL
  contract and can be built in a deterministic multi-stage image or supplied
  as an OS/architecture release artifact; and
- the foreground coordinator can run as another process unit while its control
  database remains distinct inside the owned PostgreSQL service.

The accepted cluster satisfies these requirements:

1. an image containing the installed Python distribution, both migration
   trees, Psycopg, `psql`, and the matching Go helper at its controlled path;
2. explicit process units for HTTP health/status, read-only MCP integration,
   and the durable coordinator;
3. one-shot administrative initialization, version-tracked backup-first graph
   and control schema upgrades, and other backup-first lifecycle commands with
   maintenance exclusion and a stable recovery point through backup/verify/drop,
   without granting long-running services destructive authority;
4. explicit allowlisted read-only config/source mounts for long-running units,
   narrowly owned coordinator writable state, lifecycle-only backup/admin
   mounts, persistent data, deterministic path mapping, and secret projection;
5. fresh-artifact acceptance proving Python and Go extraction, direct and
   coordinator refresh, MCP reads, restart recovery, publication, graph and
   control upgrade from a prior supported version, upgrade rollback, and
   backup-first lifecycle without host-installed Python, Go, PostgreSQL, or
   `psql`;
6. a path-free HTTP health/status projection that does not expose the RepoMap
   home or private configured graph, repository, or database identifiers;
7. applied-version authorities, readiness checks, idempotent provisioning, and
   bounded partial-init/partial-upgrade recovery for both schema families;
8. exact owned graph/control database enumeration plus coordinated backup,
   restore ordering, and recovery acceptance;
9. fail-closed resolved configuration that assigns a unique effective graph
   database to every graph, forbids graph/control template or maintenance
   names, and keeps a separate control and maintenance target;
10. destructive lifecycle refusal for any database outside the exact resolved
    graph/control allowlist, replacing the current container/name-only guard;
11. separate least-privilege read/status, refresh/publication,
    coordinator-control, and one-shot lifecycle-admin database roles and
    secrets, with declarative role/grant reprovisioning after restore;
12. distinct liveness, configuration-health, storage-readiness, and
    schema-readiness signals, with PostgreSQL health and completed one-shot
    initialization/upgrade gating coordinator and MCP readiness;
13. bounded streaming dump/restore, deterministic private backup artifact
    modes, and atomic manifest/set publication with incomplete-set refusal;
14. a pinned/tested PostgreSQL client/server/Psycopg/libpq compatibility
    matrix; and
15. declared database encoding/collation or explicit byte-stable protocol
    ordering across fresh init, upgrade, and restore.

Self-contained means the application toolchain and services are contained; a
supported container runtime, persistent storage, configured secrets, and
explicit source mounts remain deployment prerequisites.

ARCH7F supplies requirement 1 and the immutable compatibility substrate for
requirements 5 and 14. Its OCI-index-pinned build uses PostgreSQL 16.14,
Python 3.12.13, Go 1.25.12, Psycopg 3.2.12, and bundled libpq 17.6; it installs
the matching `psql`, `pg_dump`, and `pg_restore` 16.14 clients at fixed paths
and builds the Linux arm64 or amd64 helper only in the builder stage. ARCH7G
supplies the remaining composition, mount, secret, health, deterministic
database, restart, and fresh-cluster acceptance work. ARCH8 broadens this proof
through the complete public-safe integrated acceptance ladder.

## Package and layering model

The intended direction is:

```text
domain models
→ extraction and canonicalization
→ storage contracts
→ operations
→ coordinator/runtime/service adapters
→ CLI and MCP presentation
```

Committed source does not form that DAG today. Static AST analysis found
strongly connected components across operations/runtime, CLI/MCP, coordinator
worker/protocol, graph discovery, storage telemetry, and extractor
configuration facades. Function-local imports prevent some import-time
failures but do not remove responsibility inversion. Compatibility facades,
especially the broad canonicalization facade, also expose private-looking
symbols as de facto contracts.

ARCH1 must publish an allowed dependency matrix and remove cycles one seam at a
time while preserving imports. Presentation must depend on domain/operation
contracts; storage and extraction must not depend on CLI, MCP, runtime, or
service-manager behavior.

ARCH1D publishes the matrix at
`docs/contrib/package-dependency-matrix.md`, adds a repository-wide static AST
cycle and production/test-support guard, and removes the first component. The
storage telemetry event records now form a neutral contract below both
connection wrapping and private-pipe transport. Existing telemetry facades and
direct module imports remain compatible. Five explicitly pinned components and
the synthetic-worker test-support subprocess exception remain for later ARCH1
slices.

ARCH1E removes the graph discovery/extractor-routing component. `FileInfo` and
its unchanged raw-observation projection now live in a neutral graph record
module imported by both discovery orchestration and extractor routing.
`graph.discovery` re-exports the same class object, so production imports and
patch targets remain stable. Four components remain pinned for later ARCH1
slices.

ARCH1F removes the coordinator protocol/launch/refresh component. Protocol
state, validation, framing, diagnostics, and process supervision now live in an
internal core below launch adapters. Refresh errors and Windows worker
environment policy are neutral contracts shared downward. Public protocol and
worker-launch paths remain compatibility facades, including established patch
targets and subprocess behavior. Three components remain pinned for later
ARCH1 slices; the exact synthetic-worker test-support subprocess exception also
remains transitional.

ARCH1G removes the CLI/server/MCP component. Canonical node, edge, and
neighborhood filter validation now lives in a neutral storage-facing module
below both adapters. `cli.main`, the dynamic `repomap_kg.cli` package facade,
and `server.mcp_core` expose the same function objects. CLI dispatch remains
the outward owner of MCP startup without a reverse server-to-CLI dependency.
ARCH1H removes the operations/runtime component. Configuration loading,
merging, validation, and construction now live below runtime adapters, while
the public operations config facade retains status SQL/readback orchestration
and all established exported identities and patch targets. Report records use
their lower diagnostic/redaction contracts directly. One extractor
configuration component remains pinned for the next ARCH1 slice.

ARCH1I removes the final extractor-configuration component. Neutral format,
reference, value, observation, profile, and structure contracts now sit below
the generic registry and format implementations. The generic facade preserves
its routing behavior, exported identities, and YAML limit patch targets. The
static SCC allowlist is empty and the committed production import graph is a
DAG; only the separately pinned synthetic-worker production/test-support
subprocess exception remains before `ARCH0-LAYER-001` can close.

ARCH1J removes that final production/test-support exception. Production owns a
generic immutable worker launch specification and supervised execution through
the established protocol patch seam. Test support owns the synthetic mode
allowlist, fixture module target, support search path, and fixture-selecting
coordinator factory. Both architecture allowlists are empty, the committed
production import graph is a DAG, and `ARCH0-LAYER-001` is resolved.

ARCH2A establishes the closed staging-family contract beside the existing
runtime mappings. One immutable typed descriptor now records each retained
family's row shape, stage table, COPY order, technical and semantic ordinals,
identity and payload columns, nullability, checksum strategy, duplicate and
proposal policy, validation rules, merge dependencies, retention, and privacy
classification. Raw observations explicitly retain `source_ordinal`; all
other families explicitly retain `family_ordinal`; canonical evidence alone
also declares `raw_observation_ordinal` as semantic provenance. Exhaustive
tests prove parity with the existing DDL, adapters, COPY mappings, checksum
payloads, validation, merge, and cleanup ownership. Runtime consumers remain
on their existing mappings until ARCH2B migrates ownership.

ARCH2B makes the descriptor registry the retained staging-family authority.
Compatibility family and COPY catalogs are derived views. Row adaptation uses
the descriptor's explicit technical ordinal and ordered row shape; checksums
use descriptor identity columns; duplicate guards use descriptor identity,
semantic payload, policy, and table metadata; validation, merge operations,
cleanup, publication completeness, and privacy classification use derived
descriptor views. All ten families remain present. The checksum algorithm is
unchanged and is accepted as a client-computed trusted transfer receipt for
the repository-owned local transport boundary, not server-recomputed or
adversarial end-to-end cryptographic integrity. Publication, receipts,
rollback, and commit-unknown semantics are unchanged. `ARCH0-NORM-001` and
`ARCH0-STORAGE-001` are resolved.

ARCH2C adds an opt-in, non-authoritative staging measurement contract with a
closed category, unit, availability, and payload schema. Descriptor-owned
family iteration attributes preparation, row count, normalized bytes, spool
bytes, checksum, and COPY for all ten families. The staged orchestrator also
attributes statistics, completeness validation, semantic guards, merge, and
receipt; cleanup execution has the same optional boundary. Resource events
contain only aggregate process peak memory, cluster-wide WAL and
current-database temporary-byte upper bounds, and safely available
current-backend PostgreSQL memory samples. Events cannot carry source paths,
row values, SQL, repository or database identifiers, backend identifiers, or
credentials. A synthetic PostgreSQL parity fixture proves identical final
state and receipt, at most 96 events, and exactly four additional aggregate
resource queries. No Argo CD or private graph run occurred. `ARCH0-PUB-001` is
resolved for ARCH2, and the typed staging-family normalization phase is
complete.

ARCH3A freezes the legacy node-list reader and establishes separate canonical
node and first-class file/source replacement contracts. A bounded source-
backed adapter reconstructs the six-field legacy node shape from retained raw
observations and the `files` index, including deterministic proposal
selection, historical file identities, file-join timing, exact filters,
ordering, empty results, and psql/Psycopg parity. The existing MCP canonical-
node and file/source searches now delegate to the typed compatibility boundary
without changing SQL or public payloads. Golden PostgreSQL fixtures prove
legacy-table/source-adapter equality across repeated imports while explicitly
showing that canonical keys and file paths are not legacy stable keys. Legacy
writers and public legacy readers remain active for the later ARCH3 migration
slices.

ARCH3B freezes the legacy edge-list contract and its embedded evidence
projection. A bounded source-backed adapter reconstructs the twelve-field row
shape from retained raw observations and the first-class file index while
independently selecting the latest edge, node, and evidence proposals. It
preserves evidence-to-file attachment timing, exact filters and ordering,
empty results, the existing missing-path decoder error, and psql/Psycopg
parity. The existing legacy SQL facade delegates to the typed compatibility
boundary without changing generated SQL. Canonical edge and exact edge-
explanation contracts replace legacy identity and embedded evidence with
canonical composite identity and ordered provenance; their identifiers are
explicitly not legacy stable keys. Legacy writers and public readers remain
active.

ARCH3C freezes legacy node/file neighborhoods, raw entrypoint listing, and
storage host-mutator listing. Bounded node and file neighborhood adapters
compose the ARCH3A node and ARCH3B edge boundaries with deterministic
deduplication and explicit truncation state. A bounded file-index adapter
preserves the raw six-field entrypoint shape, and a bounded raw/source adapter
reconstructs host-mutator rows with independent node, edge, and evidence
selection plus evidence-file timing. PostgreSQL goldens prove exact legacy-
shape, filter, order, empty, error, privacy, and connector parity while
canonical neighborhoods retain their existing unbounded depth-one contract.
Some target keys may coincide across models, but no blanket key equality or
inequality is asserted. Public readers and legacy writers remain unchanged.

ARCH3D migrates public legacy CLI, MCP/ops status, connector comparison, and
legacy/canonical summary compatibility reads to complete collectors over the
bounded ARCH3 adapters. Public commands, payloads, ordering, filters, errors,
and unbounded compatibility shapes remain unchanged. Canonical MCP graph reads
and baseline/drift summaries remain on their accepted canonical/source graph
authority. A disposable PostgreSQL golden proves exact payload parity through
psql and Psycopg after legacy final-table rows are removed. Legacy writers,
schema, migrations, and row-wise caller contracts remain active.

ARCH3E closes the receiptless row-wise caller census. A typed registry assigns
one future behavior to 13 public, programmatic, production-compatibility, and
repository-tool surfaces: complete generations move to staged publication,
partial source acquisition becomes non-mutating input, and incompatible
canonical-only or row-wise mutation surfaces retire through announced
boundaries. An AST-backed census closes all direct calls and default-loader
bindings in production source and repository tools. Runtime behavior and
legacy writers remain unchanged until ARCH4.

ARCH4A migrates all three complete-generation callers to the existing staged
publication transaction. `storage load-files`, configured programmatic
refresh, and connector-comparison fixture seeding now create deterministic
generation authority and commit a complete receipt. Programmatic refresh
rejects its retired row-wise mode before discovery or storage work. The typed
census retains the announced contracts while reducing active receiptless
bindings from 11 to 8. Partial acquisition and legacy-family staged writes are
unchanged until ARCH4B and ARCH4C respectively.

ARCH4B makes feed, archive, WARC, bulk, generic API, and GitHub acquisition
explicitly non-publishing. Their versioned result states that graph state and
freshness were not mutated, and mutation-only repository and PostgreSQL
selectors are no longer accepted by those commands or functions. The
incompatible `storage load-canonical` command and the SCALE7 row-wise baseline
are retired. The executable census has no active receiptless caller binding;
only the two uncalled programmatic row-wise primitives remain for coordinated
removal in ARCH4C. Legacy-family staged writes remain unchanged.

ARCH4C removes both row-wise primitives and their facade exports, the row-wise
stream and legacy SQL builders, legacy proposal construction, and all three
legacy staging-family row/manifest/COPY/checksum/validation/merge/cleanup
contracts. The active publication manifest now contains files, raw
observations, and the five canonical/evidence-link families only. Disposable
PostgreSQL tests prove that physical legacy graph rows remain zero while
source/canonical-backed public compatibility results remain populated. Legacy
tables, historical migrations, and read adapters remain for rollback; no DDL,
canonical identity, dependency, receipt, fencing, cancellation, or
commit-unknown contract changes in this slice. ARCH4D owns the normalized
parity and rollback campaign.

ARCH4D accepts the writer transition. Separate disposable databases produce
exactly equal normalized files, raw observations, canonical graph, evidence,
and evidence-link rows for direct and coordinator ownership, with zero legacy
graph writes. A second complete publication preserves seeded legacy rollback
rows and all three legacy staging tables while migrated readers remain stable.
The accepted fencing, failure, cancellation, cleanup, replay, and
commit-unknown campaigns remain green. The repeated size-4 measurement retains
the seven-family deterministic shape. ARCH4 is complete; ARCH5A must establish
product-owned upgrade authority before any identity or legacy-removal DDL.

ARCH5A1 establishes the graph half of applied-version authority for fresh
managed databases. Migration discovery now assigns unique ordered changesets,
repository-relative paths, and content checksums. Initialization and pending
migration ledger rows commit in one transaction; exact replay is a no-op, and
unmanaged or divergent state fails closed. ARCH5A2 adds verified backup-first
adoption for an existing graph database only when its deterministic catalog
manifest exactly matches a freshly initialized same-runtime reference after
excluding the ledger. Adoption applies a ledger-only transaction, verifies the
complete catalog identity, and retains the pre-upgrade dump for rollback.
ARCH5A3 applies the same product-owned authority to the coordinator-control
database: ordered checksummed discovery, transactional fresh initialization,
exact-current readiness, verified backup-first pre-ledger adoption against a
fresh same-runtime reference, and ledger-only bootstrap. Cross-plane
maintenance exclusion is now partially implemented by ARCH5A4A. Coordinator
workers hold shared ownership for their complete lifetime; submission,
coalescing, and claims fail closed behind a queued or held exclusive owner;
the exclusive owner drains existing workers; and configured coordinator
health reports schema maintenance as not ready. ARCH5A4B completes the
cross-plane boundary: staged graph publication/import holds graph-local shared
ownership, configured direct work also holds control ownership, graph upgrade
owns control then its target graph, and control upgrade owns control then every
configured graph in deterministic order before backup through cleanup. ARCH5A
is complete without applying forward DDL or removing legacy schema.

## Configuration authority

Configuration files and environment inputs are source material. The resolved
operations configuration is the authoritative graph-registration and
PostgreSQL model. Workers receive a narrow capability derived from that model;
they do not discover arbitrary roots, executables, databases, connectors, or
credentials. Source, configuration, extractor, and canonicalizer generation
tokens fence publication against stale work.

Runtime and service renderers currently re-project configuration and retain
source-checkout assumptions. The normalized target has one pure resolution
path, one typed resolved model, one credential boundary, and separate
public-safe projections. Environment variables may select documented paths or
secrets; ambient executable and database discovery are not authorities.

The accepted topology is one dedicated database per configured graph plus one
derived control database and one distinct non-owned maintenance connection.
ARCH1B resolves every effective database name, rejects collisions and
template/maintenance ownership, and derives the exact graph/control allowlist.
ARCH7C1 makes that allowlist authoritative for local lifecycle and coordinator
maintenance admission and routes create/drop existence work through the
resolved maintenance connection. Coordinated enumeration and recovery remain
ARCH7D work.

Generated Compose also gives the long-running server the same bootstrap
`POSTGRES_USER` and password used to create the PostgreSQL service. The HTTP
command surface has no lifecycle method, but the process-level database
capability is administrative. ARCH7 must separate read/status,
refresh/publication, coordinator-control, and one-shot lifecycle-admin roles
and secrets, keeping admin capability out of long-running read/status units.

It also mounts the entire RepoMap home read-write into that server, including
credential and backup/admin state. ARCH7 must replace that capability with
allowlisted read-only config/source views, narrowly owned coordinator writable
state, and lifecycle-only backup/admin mounts.

## Data authority matrix

| Concept | Authority | Durable/derived/compatibility representation | Writer and replacement rule |
| --- | --- | --- | --- |
| Graph and repository identity | Configured graph registration plus resolved stable identity; one effective database per graph | Public graph ID is a projection; database ids are private implementation details; ARCH1B retains fallback syntax but rejects effective collisions | Root relocation preserves `repo1:<graph-id>`; graph-ID changes require explicit re-registration or migration |
| Repository row identity | Stable configured repository identity; source location is mutable/private | ARCH5C2A populates one stable row, preserves historical ownership, merges overlapping final identities, and retains the configured root separately; ARCH5C2B resolves configured staged writes by identity and keeps identity omission as the historical root-keyed adapter contract; ARCH5C3 accepts rollback, baseline, drift, staged, and historical compatibility evidence | Root relocation preserves numeric and configured identity; graph-ID change remains explicit re-registration or migration |
| Four generations | Deterministic source/config/extractor/canonicalizer generation computation | Stored on jobs/stages/runs/receipts | Resolver/coordinator/refresh; new generation supersedes stale work only after a complete receipt |
| Raw observation | Run-local normalized observation and ordinal | `raw_observations`; spools/stage rows are temporary transfer forms | Extraction/normalization; retained by graph-data policy |
| File/source identity | Materialized `files` index scoped to repository/path | Canonical file nodes and public file queries are derived views | Refresh writes; later complete runs replace last-seen state |
| Legacy node/edge/evidence | Retired historical semantics | No runtime relations, public adapters, aliases, flags, result schemas, or connector operations; historical migrations and status records remain | No reader or writer; reintroduction requires a new decision |
| Canonical graph/evidence/links | Canonical keys and accepted graph-key version | Canonical final tables; readback/API projections are derived | Canonicalization and publication transaction |
| Staging ownership | Exact stage owner tuple and state machine | `ingestion_stages` plus seven retained file/raw/canonical stage families | Staged ingestion; publication/reconciliation/cleanup transitions replace state |
| Job/attempt/lease/epoch | Coordinator control database | Worker capabilities and graph-local fencing are projections | Coordinator transactions; legal transitions and leases replace state |
| Publication receipt | Complete staged-publication receipt in graph `runs` row | Reconciliation and staged-freshness projections are derived | Final staged graph transaction; only a later matching complete receipt replaces staged freshness |
| Latest run | Two current typed meanings: highest recorded run ID and newest complete receipt-bearing publication | Status/summary and receipt readback request the exact authority concept; no supported receiptless mutation can create divergence | Staged publication advances graph freshness; running or failed executions can advance only recorded-run state |
| Row-wise final mutation | Retired historical path | No current runtime, public command, facade export, or freshness representation | Complete callers use staged publication; partial acquisition is non-publishing; incompatible surfaces and primitives are removed |
| Baseline/drift | Explicit stored baseline and comparison contract | JSON artifacts and public summaries | Baseline commands; save/prune rules are explicit and atomic |
| Runtime registration/lifecycle | Configuration plus CLI-owned lifecycle | Rendered Compose/service artifacts and status are derived | Explicit operator command; no read or long-running service mutates authority |
| Existing-database schema upgrade and fresh provisioning | Committed graph/control migration resources, product-owned applied-version ledgers, deterministic control-then-graph maintenance ownership, cleanup-based retry, and backup-first exact-prefix advancement | ARCH5 implements checksummed ledgers, adoption, forward upgrade, rollback rehearsal, stable identity, and guarded legacy removal; ARCH7 packages and deploys the authority | Current release-cluster lifecycle accepts fresh, exact-current, prior-supported, rollback/reconstruction, and failure-cleanup paths |
| Cluster backup/recovery | Exact configured graph and coordinator-control ownership plus declarative post-restore grants | ARCH7D2 captures the stable complete owned set; ARCH7D3 accepts only an exact stable checksummed set, restores graphs deterministically and control last, and removes invocation-created targets after failure; ARCH7E reapplies roles; ARCH7G confines private backup/admin capability to one-shot lifecycle administration; ARCH8 corrects its writable-root and container-internal packaged-client adapter and performs real two-graph/control recovery plus abrupt restart | No material authority mismatch |
| Destructive database authorization | Exact resolved graph/control ownership | ARCH7C1 rejects every unrelated safe name before container, backup, lock, or destructive access and uses the resolved maintenance connection for database DDL | Preserve exact admission while ARCH7C2 extends exclusion from recovery-point capture through destruction |

The complete matrix, including retention, migration, readers, invalidation, and
duplication, is in `docs/specs/data-authority-and-legacy-inventory.md`.

## Storage and publication model

The accepted model gives each configured graph one unique dedicated graph
database, keeps coordinator control distinct, and excludes the maintenance
database from product ownership. A forced-full attempt creates a run and
durable stage header, transfers seven file/raw/canonical family streams through
Psycopg COPY, validates row counts and SQL invariants, performs set-based
file/raw and canonical merges, and finalizes the run receipt and stage state in
one graph transaction.

For staged forced-full refresh, the receipt-bearing transaction is the only
publication proof. COPY completion, stage validation, worker exit, queue state,
and authority projection alone are not freshness. Commit-unknown recovery is
receipt-first: a matching receipt resolves success, a conflicting receipt
quarantines/errors, and an absent receipt remains reconciliation-required rather
than proving rollback. ARCH normalization must not weaken these properties.

Receipt-bearing staged publication is the sole final graph mutation authority.
`storage load-files`, configured refresh, and supported complete-generation
programmatic use share it. Source acquisition is versioned acquisition-only
input that cannot update graph state or freshness. The canonical-only command,
row-wise primitives, and legacy writer families are removed. Latest recorded
run and latest receipt-bearing publication remain explicitly named and read
separately.

Stage checksums are deterministic client transfer receipts rather than
independently recomputed server content digests. Closed family descriptors,
typed manifests, count validation, SQL invariants, and receipt-bearing atomic
publication preserve that explicit trust boundary.

## Coordinator and direct-mode model

The semantic pipeline is shared. Direct and coordinator modes may differ in
intent, scheduling, transport, supervision, cancellation orchestration, and
progress delivery, but not in graph transformation, validation, merge,
receipt, or reconciliation semantics. There is no silent fallback.

ARCH1C closes the as-built authority seam. Both modes take the same nonblocking
graph advisory transaction lock before final mutation. Each coordinator claim
also receives a graph capability ordered independently from singleton
succession, registers it in the existing graph-local authority projection with
stage creation, and revalidates it immediately before publication. The final
merge, run receipt, authority update, and stage transition remain one
transaction, and commit-unknown reconciliation remains receipt-first.

## Lifecycle authority

CLI operations own fresh database initialization, backup, restore, drop,
runtime setup/up/down, control-database initialization, and service-package
installation/start/stop/uninstallation. Exact resolved graph/control
allowlisting and backup-first deletion are enforced before external access;
container ownership alone is insufficient. HTTP, MCP, coordinator, workers,
and ordinary readback expose no destructive lifecycle command.

ARCH5 establishes one version-tracked, backup-first graph/control upgrade
authority with transactional ledger updates, idempotent provisioning,
deterministic readiness, partial-target recovery, and rollback evidence before
legacy removal. ARCH7 packages the same authority in the end-user cluster
without a container-only alternative. ARCH8 proves every supported graph
upgrade, control pre-ledger adoption, complete recovery, and restart.

Backup and restore authority now covers the complete configured graph/control
set. `local db dump-all` captures that exact set under cross-plane exclusion,
and `local db restore-all` accepts only the matching stable coordinated set for
an empty compatible topology. Both operations preserve conservative ownership
and backup-root privacy.

ARCH7D1 streams dump output and restore input through files without allocating
the complete archive in the client. Backup directories use explicit `0700`
modes, artifacts use `0600`, completed files and directories are flushed, and
one hidden same-filesystem staging directory is renamed to the final set only
after dump, manifest, and restore note completion. Pre-publication failure
removes the complete staging set; an orphaned hidden staging set is excluded
from enumeration and refused as an explicit restore target. ARCH7D2 and
ARCH7D3 extend these primitives to exact coordinated graph/control sets,
coordinated incomplete-set refusal, deterministic graph-first/control-last
restore, and reverse cleanup of invocation-created targets after a failed
attempt. Restore still omits owner and privilege metadata. ARCH7E therefore
reconciles the accepted role/grant model after init, upgrade, and restore.

ARCH7D2 makes `dump-all` the exact resolved graph/control backup operation.
The CLI holds the existing control-then-all-graphs maintenance window through
every ordered streaming dump and atomic directory publication. Manifest format
version 1 remains unchanged while stable coordinated sets add a bounded
recovery-point assertion and one checksum entry per owned database. Dry-run is
non-locking, mid-set failure publishes nothing, and the non-owned maintenance
database is excluded. ARCH7D3 adds `local db restore-all`: it verifies the
stable assertion, exact configured topology, one unique dump and checksum per
owned database, and absence of every target before mutation. Graph databases
restore in sorted order and control restores last. A failure removes every
database created by the invocation in reverse order; cleanup failure is a
bounded explicit diagnostic.

ARCH7E separates database authority into read/status, refresh/publication,
coordinator-control, and one-shot lifecycle-administration capabilities. Fixed
non-administrative login roles receive generated owner-protected secrets and
an idempotent declarative grant contract. Graph databases grant read access to
read/status and mutation only to refresh/publication; the control database
grants read access to read/status and mutation only to coordinator-control.
Fresh init, dump restore, graph/control upgrade, and coordinated restore
reapply the contract. Long-running HTTP/MCP configuration is projected onto
the read role, while the foreground coordinator loads only control and refresh
credentials and cannot connect to the maintenance database. The lifecycle
administrator remains confined to explicit one-shot operations.

ARCH7G initializes PostgreSQL and every product database with explicit UTF-8/C
settings; stable application ordering remains explicit. ARCH8 repeats
fresh-init, upgrade, restore, and deterministic publication evidence.

ARCH1 derives the exact owned graph/control database allowlist from
collision-free resolved configuration. ARCH7 requires that authorization for
dump, restore, upgrade, and drop; container ownership and a verified backup do
not independently prove database ownership.

ARCH7C2 holds the accepted cross-plane maintenance exclusion continuously from
before backup-first drop captures its dump through verification and database
destruction. Graph drops hold control plus the exact target graph; control
drops hold control plus every configured graph in deterministic order. The
window drains admitted writers before recovery-point capture, refuses new
direct, coordinator, and import work, and releases on success or failure.
ARCH7D establishes the equivalent stable recovery point for coordinated
multi-database backup and exact complete-set restore.

Those lifecycle operations depend on enforced database topology. Resolved
configuration rejects duplicate effective database names, graph/control or
maintenance collisions, and reserved targets. ARCH7 proves multi-graph/control
provisioning, ownership, backup, restore, and least-privilege operation from
that validated model.

ARCH7B publishes distinct `/livez` process liveness, `/healthz` configuration
health, and `/readyz` storage and required-schema readiness. The generated
server healthcheck uses `/readyz`, while `/status` remains informational. Current
ARCH7G adds PostgreSQL health and a completed one-shot exact-current
initialization/upgrade gate before HTTP, coordinator, or MCP startup.

Lifecycle reads may report state but must not initialize, start, repair, or
delete implicitly. Runtime and service-manager adapters render and invoke the
same explicit lifecycle contract; they do not define product graph semantics.

## Readback and MCP model

Product reads include graph status/summary, baseline/drift, canonical lists and
explanations, file/source queries, neighborhoods, entrypoints, host-mutator
views, connector adapters, CLI JSON/table output, and read-only MCP tools.

Psycopg and `psql` readback share shape validation. Canonical and source-based
reads are the only current graph/source vocabulary; legacy storage, aliases,
flags, result schemas, and connector operations are removed. ARCH7A1 bounds direct CLI and MCP canonical
node/edge lists with the shared schema-version 1 page envelope, stable existing
SQL ordering, limits of 1 through 200, offset continuation, lookahead
truncation, and equivalent item membership. ARCH7A2 applies the same version,
bounds, continuation, and diagnostic vocabulary to independently windowed
neighborhood node/edge collections and explanation evidence. Announced
schema-zero aliases return bounded legacy arrays or result objects. Internal
storage queries retain their unbounded internal default, so the presentation
envelope does not become a second graph-query model. ARCH7B through ARCH7G
complete HTTP privacy, readiness, roles, packaging, and deployment.

The HTTP health/status server is not MCP-over-HTTP. A deployment that claims
MCP must provide the existing stdio integration or a separately accepted,
authenticated, local-only, bounded, read-only HTTP transport.

## Privacy and platform boundaries

Configured roots, source values, credentials, database identities, local
paths, tokens, raw exceptions, and private telemetry are private. Public CLI,
MCP, health, status, logs, reports, and tracked artifacts receive bounded,
path-free projections. ARCH7B removes the HTTP exception: schema-version 1
health/readiness/status payloads contain only allowlisted states and bounded
counts, never RepoMap home, graph, repository, database, or raw diagnostic
values. Graph probes cap at 200 and responses cap at 8 KiB. Local-only binding
remains a reachability control rather than a redaction substitute. Reusable
privacy-policy vocabulary may still be normalized without centralizing
raw-secret access.

Static extraction never executes target code. Workers receive allowlisted
capabilities and separate argv values, not arbitrary commands. Paths must stay
within configured roots; excluded files are not opened. MCP is read-only and
cannot proxy mutation or lifecycle.

Core graph semantics are platform-neutral. POSIX local transport, launchd,
systemd-user, Windows foreground/job-object behavior, container path mapping,
and the packaged Go binary are adapters. Native Windows background packaging
remains deferred and is not reopened by ARCH.

WSL remains a Linux-style foreground operating pattern through `wsl.exe`, with
no WSL-specific semantic implementation and no assumption that a systemd user
unit keeps the distribution alive, as recorded by status 00533 and
ASYNC-CLOSE.

ARCH7F pins official multi-architecture PostgreSQL 16.14 Bookworm, Python
3.12.13 slim Bookworm, and Go 1.25.12 Bookworm images by OCI index digest. The
final image inherits the server-matched PostgreSQL 16.14 `psql`, `pg_dump`, and
`pg_restore` clients at fixed paths, installs Psycopg 3.2.12 with bundled libpq
17.6, and records the matrix as immutable image labels. Fresh arm64 and amd64
builds verify the installed migrations and package-local helper without Go or
source-tree execution in the runtime image.

ARCH7G composes PostgreSQL, one-shot initialization/upgrade, HTTP
health/status, read-only MCP integration, the foreground coordinator, and
one-shot lifecycle administration from that artifact. PostgreSQL initializes
with UTF-8/C defaults; graph and control databases are created from `template0`
with explicit UTF-8/C attributes. Per-unit secrets, read-only configuration
and source mounts, narrow coordinator state, lifecycle-only backup/admin state,
and a loopback-only HTTP publication preserve least-capability operation.
Initialization preflights all existing graphs before mutation, refuses
pre-existing empty graph adoption, and removes invocation-created graph targets
in reverse plus an invocation-created control target after later failure.
Fresh-cluster acceptance proves exact-current gating, HTTP/MCP/coordinator
readiness, packaged dump/restore clients, and persistent restart recovery.
The generated coordinator unit retries bounded startup failure for at most 75
seconds after an abrupt database restart while preserving the existing
60-second singleton lease and prohibiting forced takeover; non-container CLI
startup remains fail-fast.

## Legacy inventory

The legacy inventory classifies every candidate exactly once in the supporting
specification. The governing conclusions are:

- `files` is a **current first-class derived component**, not a legacy graph
  family;
- `raw_observations` is retained authoritative evidence;
- legacy `nodes`, `edges`, and `evidence` are **replaceable after bounded
  compatibility adapters**;
- legacy summaries, neighborhoods, entrypoints, host-mutator views, connector
  adapters, CLI modes, and JSON schemas are **required compatibility
  projections** until canonical/source parity and an announced boundary;
- row-wise ingestion is a **required compatibility projection** across eight
  active public commands and programmatic callers until they migrate to
  acquisition-only input plus complete staged refresh, or are retired through
  an announced boundary;
- old aliases and facades require a consumer inventory and are not dead from
  textual search alone;
- transitional columns and configuration fields require case-specific
  classification; and
- historical migrations are **historical migrations that must remain**.

## Legacy-decommissioning decision

RepoMap selects the prompt's **Model B — raw facts, canonical graph, and
first-class file index**:

```text
raw/source facts as retained evidence
+ one canonical graph
+ one explicit file/source index
+ temporary compatibility adapters or views at public boundaries
```

Persisted legacy node, edge, and evidence projections will be decommissioned
only after executable parity. The order is:

```text
freeze semantics and inventory readers
→ prove canonical/source parity
→ add bounded adapters or views
→ migrate CLI, MCP, connector, baseline, and drift consumers
→ prove small and medium repository parity
→ separate latest recorded run from latest receipt-bearing publication
→ migrate public row-wise mutation/import callers without adding partial publication
→ stop legacy writes
→ prove normalized dogfood parity and rollback
→ remove legacy staging, validation, and merge
→ remove final legacy runtime tables and indexes by forward migration
→ remove adapters after an announced compatibility boundary
```

Historical migration files are never dropped. The file/source index remains
until a separately evidenced first-class replacement proves its fields,
latency, baseline, and drift semantics.

## Ordinal-contract case study

RepoMap selects **Ordinal Model A — explicit family descriptors**.

`source_ordinal` is the deterministic run-local provenance identity of a raw
observation and becomes final `raw_observations.ordinal`.
`family_ordinal` is a stage-local deterministic proposal order for the other
families and may resolve proposal ordering; it is not provenance or canonical
identity. Canonical evidence separately carries `raw_observation_ordinal` when
it refers to raw evidence.

A common `stage_row_ordinal` would duplicate raw ordering today without a
demonstrated independent transfer-order requirement. One universal ordinal
would be incorrect because aggregated canonical nodes, edges, and links may
derive from multiple observations. ARCH2 will instead define typed family
descriptors that state the technical ordinal column and semantic ordinal, if
any, for every family.

The governing rule is:

```text
semantically identical concepts share one contract;
semantically distinct concepts are represented explicitly rather than hidden
behind generic assumptions.
```

## Normalization principles

Later implementation reviews must enforce all of these principles:

1. One authoritative model exists per concept; derived and compatibility
   forms are explicitly named.
2. One term denotes one concept, and materially different semantics use
   different terms.
3. Family contracts are closed and typed, including identity, ordering,
   checksum, duplicate, validation, merge, retention, and privacy rules.
4. State and error vocabularies are closed, versioned, and bounded.
5. Direct and coordinator modes share one semantic implementation and one
   graph-local exclusion invariant.
6. One receipt-bearing transaction is forced-full graph publication authority;
   receiptless import runs are transitional and may not masquerade as
   publication freshness.
7. CLI-owned exact allowlisted operations are lifecycle authority.
8. Configuration follows one resolution path into a typed model; credentials
   remain boundary-owned.
9. Public output follows one privacy/redaction policy and one path/identity
   policy.
10. Resource and output contracts are bounded and observable.
11. No mode, connector, executable, root, database, or lifecycle authority is
    selected through a hidden fallback.
12. Workers and presentation surfaces have no arbitrary execution authority.
13. Platform-specific adapters remain outside graph-domain semantics.
14. Compatibility is isolated at public boundaries and expires only through an
    announced, tested migration.

## Algorithmic complexity model

Let `F` be included files, `B` included bytes, `O` raw observations, `R`
relationship proposals, `FN` file/source rows, `LN/LE/LV` legacy
node/edge/evidence rows, `CN/CE/CV` canonical node/edge/evidence rows, and
`CNL/CEL` canonical evidence links.

Discovery and ordinary extraction are generally `O(B + F log F + O)`, with
output-linear memory because current orchestration materializes file and
observation collections. Projection and staged preparation are generally
linear plus per-family deterministic sorts, but all retained families,
spooling, checksum, encoding, COPY, validation, merge, and indexes add large
constants and storage amplification.

ARCH6A resolves CSS descendant matching by building one element pointer index
per matched HTML document and reusing it across linked stylesheets and
selectors. Deterministic traversal evidence grows near-linearly.

ARCH6B resolves canonical edge metadata accumulation by retaining a private
equality-key index with the first-seen value list. Repeated proposals no longer
copy or scan the complete accumulated list. Deterministic fan-in evidence grows
linearly while canonical edge identity and the serialized graph digest remain
unchanged.

These bounded ARCH6 algorithm corrections are complete. The high-scale staging
result is not called quadratic: available evidence supports a linear but
over-amplified pipeline with insufficient boundary attribution.

Subsystem judgments are:

| Subsystem | Judgment |
| --- | --- |
| Configuration and generation | `sound but over-amplified` |
| Discovery/filtering/hashing | `algorithmically sound` under current whole-repository memory bounds |
| Extraction | `algorithmically sound under documented bounds` after ARCH6A removes repeated CSS/HTML index construction |
| Canonicalization | `algorithmically sound under documented bounds` after ARCH6B; pipeline lifetime and cancellation structure still require revision |
| Projection and staging | `contains an architectural duplication defect` |
| COPY, validation, and merge | `sound but over-amplified`; high-scale attribution is incomplete |
| Publication and recovery | `algorithmically sound` when accepted fencing/exclusion preconditions hold |
| Coordinator | `sound only under documented bounds` and requires a unified publication-exclusion invariant |
| Baseline and drift | `algorithmically sound` |
| Readback and APIs | `sound only under documented bounds` because bounds differ by surface |
| Lifecycle and deployment | `contains an architectural duplication defect` between development orchestration and release packaging |

The overall judgment is exact: **Architecture is sound only after specified
structural revisions.**

## Performance-amplification model

The retained model can emit one or more rows into seven file/raw/canonical
stage families and their final indexes for one observation. Before ARCH4C and
ARCH5D, the same pipeline also carried three legacy families; historical SCALE
evidence remains valid for that earlier shape. The exact current ratio depends
on extractor kind, canonical aggregation, and evidence multiplicity; no
universal percentage is valid.

The defensible attribution is structural:

- file/source index: one first-class family plus its final index work;
- raw evidence: one retained run-scoped family;
- legacy graph families: no runtime schema, presentation adapter, or connector
  operation after ARCH5E; historical migration evidence remains only;
- canonical graph: five authority/evidence families; and
- staging metadata/validation: one header, manifests, checksums, statistics,
  ownership, reconciliation, and cleanup work shared by all families.

ARCH2 and ARCH6 must measure rows, normalized bytes, spool bytes, COPY bytes,
WAL, temporary bytes, scans, sorts, hashes, serialization passes, merge
statements, client/PostgreSQL memory, and elapsed time per boundary on
public-safe small, medium, and full fixtures. No protected-repository
completion is inferred.

ARCH6C applies the ARCH2 observer to deterministic 32, 512, and 4,200
file-observation fixtures. Stage preparation traverses the observation sequence
four times and retains all seven current family containers. Each observation
produces five prepared rows. The full fixture retains five private spools with
21,000 rows and 8,131,599 bytes, then decodes every spooled row once solely for
the pre-COPY checksum pass. ARCH6D is therefore limited to fusing checksum
accumulation with spool creation while preserving the later COPY pass and every
publication contract.

ARCH6D accumulates the unchanged checksum-v2 receipt immediately before each
private spool row is written. Materialized families retain the ordinary
checksum pass, while spooled families carry the fused receipt into stage
preparation. The full fixture therefore performs zero checksum-only spool
replays and decodes zero rows before the independent COPY replay. All accepted
row counts, normalized and spool bytes, family and manifest digests, observer
cardinality, private-spool controls, and publication behavior remain exact.
The iterable `checksum_family()` implementation remains the parity oracle; it
is not a hidden spool-replay fallback.

ARCH6E measures the retained COPY lifetime without changing runtime behavior.
The 4,200-observation fixture enters each of the seven family COPY boundaries
with all five private spools and 8,131,599 bytes still live. It performs exactly
five spool replay passes covering 21,000 rows, all attributable to COPY, but all
five spools remain live after the COPY loop. No later validation, receipt,
rollback, or publication boundary consumes their rows. ARCH6F is therefore
limited to closing a spool immediately after its successful family COPY while
retaining the aggregate prepared evidence and final idempotent cleanup.

ARCH6F closes only a private `RowSpool`, and only after that family's
`copy_stage_rows()` call returns successfully. On the full fixture, live spool
count before each family COPY falls from 5 to 4 to 3 to 2 to 2 to 1 to 0, and
live bytes fall from 8,131,599 to 6,399,216 to 4,251,033 to 3,218,943, remain
3,218,943 across the materialized edge family, fall to 1,077,180, and then zero.
The five COPY replay passes, 21,000 copied rows, checksums, receipts, rollback,
and publication remain exact. A failed family remains live with all unconsumed
spools until the caller's existing idempotent final cleanup.

ARCH6G attributes the remaining observation work on 32, 512, and 4,200
file-observation fixtures. File projection, Go-context filtering, canonical
dispatch, and raw-observation projection each perform exactly one complete
pass, for exactly `4N` item visits and no unattributed traversal. The Go-context
pass produces zero claims on the file-only fixture, but it is the canonical
layer's required kind filter and forward-resolution prepass; moving the filter
into a storage-owned index would relocate rather than eliminate the scan and
would introduce a new cross-layer contract without measured benefit. The five
full-fixture pre-COPY spools remain the sole pending COPY sources and are
released by ARCH6F at their final consumers. ARCH6 therefore accepts the four
fixed-count linear passes as bounded architecture and closes the performance
finding without another source change.

## Architectural findings

The closed register contains high findings for cross-mode publication
exclusion, receiptless row-wise final mutation/latest-run ambiguity, dual
persisted graph models, database/repository identity, active legacy graph
writes, missing typed family contracts, staged amplification, coarse
publication attribution, configuration authority, incomplete release
deployment, incomplete upgrade/ownership/recovery authority, HTTP status
disclosure, helper/platform packaging, and integrated acceptance evidence.
Medium findings cover localized quadratic algorithms, dependency cycles,
unbounded public reads, checksum trust wording, privacy-policy duplication, and
stale architecture prose.

No critical finding requires a new storage engine, new dependency, abandoned
dedicated-database topology, changed canonical identity, removed raw evidence,
or weakened publication safety. Therefore no mandatory architecture-choice
stop is triggered before this proposed decision can be reviewed.

## Candidate target architectures

### Model A — normalized current multi-projection architecture

Retaining raw, file, legacy, and canonical persisted families minimizes public
migration but permanently preserves dual graph authority risk, three legacy
stage/merge families, extra indexes/WAL, and reader divergence. Rejected as the
long-term target.

### Model B — raw facts, canonical graph, and first-class file index

This model preserves replay/evidence, canonical graph semantics, and required
file/source product reads while eliminating persisted legacy graph duplication
after parity. It has a bounded additive migration and rollback path. Selected.

### Model C — raw facts with rebuildable projections

Treating most graph forms as rebuilt projections simplifies durable authority
but weakens read availability, makes publication/rebuild cost central, and does
not match current baseline, drift, explain, and operational contracts. Rejected
for the intended local product.

No source-derived Model D is materially better than Model B.

## Decision

RepoMap will normalize toward Model B, preserve dedicated graph databases,
retained raw evidence, canonical identities, one atomic receipt-bearing
publication transaction, explicit direct/coordinator modes, read-only MCP, and
CLI-owned lifecycle.

The project will remove persisted legacy node/edge/evidence runtime components
through a reader-first migration; retain the file/source index as first-class;
adopt typed explicit family descriptors with distinct raw provenance and stage
proposal ordinal semantics; remove package cycles; correct proven quadratic
algorithms; bound public reads; reduce measured representation/serialization
amplification; unify publication exclusion; migrate or retire receiptless
row-wise final mutation so import runs cannot become publication freshness;
preserve bounded path-free HTTP status; establish version-tracked, backup-first
graph and control schema upgrades; establish complete owned-database backup/recovery;
enforce unique graph-database assignment and relocation-stable repository
identity; constrain destructive operations to exact owned databases; separate
database roles; normalize readiness; and turn the current development runtime
into a complete fresh-artifact container-cluster contract.

This is a proposed architecture decision. It authorizes no implementation
until the operator accepts ADR 0041.

## Consequences

Positive consequences:

- one graph authority and one retained evidence authority become explicit;
- genuinely legacy runtime writes and storage costs become removable;
- family-specific semantics stop hiding behind generic mappings;
- direct/coordinator safety and API bounds become reviewable contracts;
- latest recorded runs and receipt-bearing publications become distinct,
  reviewable contracts;
- performance work targets measured boundaries rather than broad rewrites; and
- the end-user container deployment goal remains viable and testable.

Negative consequences:

- the migration spans multiple bounded phases and temporarily adds adapters;
- some future API defaults may need an announced incompatible change;
- schema retirement requires forward migration, backup-first rollback, and
  compatibility evidence, and first requires an upgrade mechanism that the
  current product does not have;
- removing package cycles while preserving broad facades is deliberate work;
  and
- SCALE remains paused until the complete normalization epic closes.

## Compatibility and migration

No supported reader loses a writer or table before replacement parity. ARCH3
adds canonical/source compatibility adapters and migrates internal consumers.
ARCH4 stops new legacy writes only after executable parity and rollback gates.
ARCH5 removes runtime tables and indexes through new forward migrations, never
by deleting historical migrations. ARCH5E ends the announced compatibility
interval and removes the aliases and adapters after the consumer census and
canonical replacement gates pass.

ARCH1 first splits latest recorded run from latest receipt-bearing publication.
It also rejects duplicate effective graph databases, defines the exact owned
graph/control allowlist, and defines stable repository identity separately from
source path, including the compatibility and migration contract. ARCH1 does not
mutate existing repository rows or schema.
ARCH3 inventories every public and programmatic row-wise caller and preserves
its supported acquisition/output behavior. ARCH4 then routes acquisition into
the complete refresh pipeline or retires the immediate mutation command through
an announced compatibility boundary. No ARCH phase introduces partial
publication or fabricates a receipt for work that did not satisfy the staged
contract.

Before any identity or legacy DDL is applied, ARCH5 establishes a product-owned
applied-version ledger and backup-first upgrade/rollback operation for existing
graph and control databases. It then applies an additive stable repository
identity schema/data migration with compatibility lookup and rollback evidence,
followed by the legacy-removal changes as new forward migrations. Each
changeset must quiesce active jobs/stages; legacy changes also verify zero
legacy readers/writers. Transactional DDL and its ledger update commit together,
or a documented nontransactional class supplies deterministic recovery. ARCH5
uses an executable maintenance-exclusion state/lock to reject new
coordinator/direct/import work, drain or quarantine active attempts/stages, and
report schema-upgrading as not ready through MCP/cluster readiness. It also
closes partial fresh-init and restore recovery so failed targets are
deterministic and retryable. ARCH7 reuses and packages that same authority as
an explicit one-shot cluster administration action. Existing installations
must not be required to recreate their databases merely to adopt the normalized
schema.

Canonical keys, graph-key versions, raw-observation retention, final receipt
semantics, dedicated graph database topology, and complete publication remain
unchanged. Any later phase that discovers a need to change those contracts must
stop for a new operator decision.

## Remediation sequence

1. `ARCH1` — authority contracts, latest-run semantics, and package-layer
   normalization.
2. `ARCH2` — typed staging-family and ordinal-contract normalization.
3. `ARCH3` — canonical parity and compatibility adapters for legacy readers.
4. `ARCH4` — legacy node/edge/evidence and row-wise final-mutation shutdown
   after reader/caller parity.
5. `ARCH5` — version-tracked graph/control schema upgrade authority followed by
   stable-identity data/schema migration and legacy staging/final schema and
   API decommissioning.
6. `ARCH6` — proven algorithmic corrections and representation simplification.
7. `ARCH7` — lifecycle, readback, public-contract, privacy, platform, and
   container-deployment normalization.
8. `ARCH8` — normalized public-safe multi-repository dogfood and recovery.
9. `ARCH-CLOSE` — evidence audit, accepted-debt record, and SCALE gate decision.

Each phase maps to findings and verification in
`docs/specs/architectural-findings-and-remediation-map.md`. ARCH contains no
protected Argo CD attempt.

## SCALE resumption criteria

The one recommendation is:

```text
Resume SCALE only after the complete ARCH normalization epic.
```

ARCH-CLOSE must prove all of these before opening a new SCALE phase:

- legacy node/edge/evidence write amplification is removed, or an explicit
  accepted exception states its measured cost;
- typed family descriptors cover every retained family and ordinal semantic;
- proven asymptotic defects and high-priority amplification findings are
  corrected;
- no non-trivial internal import cycle remains, and production orchestration
  has no dependency on test-support code;
- direct CLI lists and MCP embedded collections have deterministic enforced
  public bounds, stable ordering, and versioned continuation semantics;
- family preparation, checksum, COPY, statistics, validation, merge, receipt,
  WAL, temporary-storage, client-memory, and PostgreSQL-memory boundaries are
  observable and bounded;
- public-safe small and medium repository results are deterministic and show
  direct/coordinator, row/receipt, and API parity;
- a public-safe full-repository gate publishes successfully within accepted
  resource bounds;
- upgrade, compatibility, rollback, baseline, and drift gates pass;
- direct and coordinator mutation share one enforced graph-local exclusion
  invariant;
- resolved configuration rejects graph-database collisions and keeps every
  graph and the control database in distinct owned databases;
- repository relocation preserves one stable storage identity, migrates old
  path-keyed rows, and leaves no stranded graph state;
- destructive lifecycle refuses databases outside the exact resolved
  graph/control allowlist;
- latest recorded run and latest receipt-bearing publication are unambiguous,
  and no supported receiptless row-wise path mutates final graph state;
- no publication, fencing, receipt, cancellation, or commit-unknown safety
  regression exists; and
- the selected container deployment has a fresh-artifact acceptance path,
  including graph/control upgrade from a prior supported version, deterministic
  partial-init/partial-upgrade recovery, proved rollback, and coordinated
  backup/restore of every owned graph and control database, with least-privilege
  roles and storage/schema readiness gating.

Only then may a separately planned protected attempt establish SCALE evidence.

## Risks

- Compatibility adapters can become permanent unless ARCH5 has an explicit
  exit boundary.
- Canonical parity may expose semantic differences that require an announced
  public decision.
- Stronger publication exclusion must not introduce deadlock or a second
  authority.
- Per-family streaming can accidentally weaken deterministic checksums or
  atomic publication if implemented without descriptor and receipt parity.
- API bounding can be breaking if defaults change without versioning.
- A container cluster can leak paths or credentials if mounts and projection
  rules remain implicit; ARCH7B closes the HTTP projection exception, while
  release-cluster mount and credential isolation remain open.
- Legacy schema retirement can strand existing graph or control databases if
  ARCH5 removes DDL before a version-tracked, backup-first upgrade and rollback
  authority exists.
- A multi-graph cluster can produce an incomplete recovery set if `dump-all`
  retains its current single-runtime-database scope without explicit owned
  graph/control enumeration.
- Duplicate effective graph-database configuration can collapse destructive
  and backup ownership unless ARCH1 makes dedicated topology fail closed.
- Path-keyed repository rows can strand old graph data after checkout
  relocation unless ARCH1 defines the stable-identity contract and ARCH5
  migrates existing rows after upgrade authority is operational.
- Shared bootstrap credentials can make a long-running unit overprivileged;
  HTTP signal separation does not replace cluster startup gating.
- Synthetic resource evidence may not predict the final protected workload;
  it is a prerequisite, not acceptance.

## Rejected alternatives

- Retain every persisted projection indefinitely: rejects the stated
  normalization and amplification objective.
- Remove legacy writes immediately: unsafe before every supported reader has a
  proven replacement.
- Remove the file/source index with legacy graph tables: unsupported by current
  file, status, baseline, drift, and last-seen requirements.
- Rebuild all graph forms on every read: conflicts with local readback and
  operational availability requirements.
- Collapse source and family ordinals into one field: erases materially
  different provenance and proposal-order semantics.
- Add a redundant common stage ordinal now: no independent transfer-order need
  justifies the extra raw key/index.
- Replace PostgreSQL or abandon dedicated graph databases: no evidence requires
  it.
- Weaken the final transaction, receipt, fencing, or commit-unknown contract to
  improve throughput: rejects publication safety.
- Treat the HTTP health/status server as MCP: conflicts with implemented
  transport and authority boundaries.
- Run another protected attempt before normalization: the current broad
  category cannot select a bounded correction.

## Review triggers

Stop and obtain a new operator decision if implementation evidence indicates
that RepoMap must change canonical identities or graph-key versions, abandon
dedicated graph databases, stop retaining raw observations, adopt another
storage engine or dependency, weaken atomic publication or receipt authority,
or choose between materially incompatible public read contracts without an
accepted migration.

Also review this ADR if canonical parity cannot replace a legacy reader, the
file/source index proves redundant with full field and latency parity, a typed
family contract cannot express a retained family safely, or a fresh cluster
cannot package the accepted Python/Psycopg/Go boundaries.

## Non-goals

ARCH0 does not implement production or test changes; add or modify migrations,
schemas, dependencies, package metadata, commands, JSON schemas, MCP tools,
canonical identities, graph keys, publication semantics, service packaging,
or lifecycle behavior; mutate a graph, database, runtime, or protected source;
begin ARCH1, SCALE11, GO, or another protected attempt; or evaluate, recommend,
prototype, benchmark, or phase caching work.

## ARCH-CLOSE implementation disposition

The accepted target is implemented: retained raw/source evidence, one
canonical graph, one first-class file/source index, and no active legacy graph
runtime or compatibility API. Latest recorded run and latest receipt-bearing
publication are distinct. Complete graph mutation has one receipt-bearing
authority, and direct/coordinator publication shares one graph-local exclusion
invariant. Resolved configuration enforces dedicated ownership and stable
repository relocation. Versioned upgrade, rollback, complete graph/control
backup and restore, API bounds, HTTP privacy, least privilege, readiness,
packaging, restart, and public-safe repository acceptance are executable.

The sole accepted debt is duplicated pure privacy-policy vocabulary across
boundary-specific adapters. Existing malicious/private fixtures prove those
boundaries path-free and bounded. Consolidation may occur later as a source-only
maintainability refactor and is not a SCALE safety prerequisite.

ARCH-CLOSE performed no protected operation and did not begin SCALE. Any SCALE
successor requires separate approval and must preserve this ADR's identities,
publication, ownership, privacy, and recovery boundaries.
