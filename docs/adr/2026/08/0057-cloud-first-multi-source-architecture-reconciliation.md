# ADR 0057: Cloud-First And Multi-Source Architecture Reconciliation

## Status

Accepted as product and roadmap architecture. MS-ID1 has a separately
authorized local implementation candidate; successor packets remain planned.

Acceptance is not authority to implement a successor. This decision by itself
authorizes no source, test, schema, migration, dependency, runtime, deployment,
database, workflow, cloud-resource, service, or remote change. Every remaining
implementation packet below requires separate operator authorization.

This ADR supersedes ADR 0031 only where ADR 0031 presents local-first delivery
as the long-term product posture. It amends ADR 0056 in part (superseding its
roadmap placement and cloud-decomposition deferral). It preserves their
implemented local, privacy, MCP, publication, and evidence contracts unless
this ADR says otherwise.

MS-ID1 implementation note (2026-08-30): the separately authorized phase made
the source-definition, graph-source-binding, immutable-snapshot, and graph-
candidate identity contracts executable. Operations TOML schema version 1 now
admits `[[graphs.source_bindings]]`, while unchanged legacy graph fields project
to one relocation-stable binding. Several bindings are configuration-valid but
refresh fails closed as `multi-source-refresh-unsupported` before extraction
or mutation; multi-source MCP visibility is not admitted. Configuration owns
durable source/binding identity in this step, while snapshot and candidate
identities are content contracts rather than accepted publication rows.

MS-ID1 deliberately retains graph key version 1 and adds no migration. Current
canonical rows and edge foreign keys remain repository-scoped. MS-FLAKE2 must
select and migrate a binding-qualified relational scope before a real
multi-source publication, prove unchanged one-binding keys and readback, and
retain the single staged publisher and receipt/fencing/reconciliation
authority. This implementation note does not authorize that successor.

MS-ID1-FIX1 correction note (2026-08-30): the local correction candidate
preserves the predecessor parser's accepted legacy source-field domain without
relaxing `[[graphs.source_bindings]]`. Strict-valid legacy extractor profiles
remain unchanged; other accepted profiles project to a bounded
`legacy-<sha256-prefix>` token. Legacy exclude arrays that use duplicates,
Unicode, long relative strings, or `.` receive a separate `select1:` digest
over their exact ordered strings. The raw legacy fields remain the public
configuration projection, while only the compatibility binding carries these
encoded identity values. Explicit source bindings retain the closed token,
path, uniqueness, ASCII, and byte-bound grammar.

The same correction candidate classifies unsupported worker refresh as
configuration, retaining `multi-source-refresh-unsupported` in the sanitized
terminal diagnostics rather than reporting generation drift. Multi-binding
aggregate status returns graph-level `multi-source-readback-unsupported`
without database facts, and graph-specific summary, file, baseline, drift, and
MCP readback refuse with that classification before database access. Internal
compatibility fields remain generation inputs, but public projections use
`[multi-source]` instead of attributing the graph to one binding. The required
changed-boundary PostgreSQL selector has not yet collected because repository
harness admission refused; MS-ID1-FIX1 is therefore not complete and MS-FLAKE2
remains gated. This correction note grants no successor authority.

MS-ID1-FIX2 correction note (2026-08-30): the follow-up local candidate removes
the remaining first-binding graph projection. An explicit graph with several
bindings now has no graph root, extractor profile, or exclusion selection;
uses `[multi-source]` as its repository display; and derives graph privacy as
`public-dev` only when every binding is public, otherwise `private-ops`.
Binding-owned roots, repository labels, extractor profiles, exclusions, and
privacy classes remain attributable only within their binding records. All
single-binding and legacy graph projections remain unchanged.

Legacy exclusion compatibility conditionally falls back to
`select1:repomap-legacy-source-selection-v1` to preserve ordered strings and
duplicates when legacy exclude paths do not satisfy the strict grammar, while explicit
binding syntax canonicalizes its duplicate-free selection set under
`repomap-source-selection-v1`. Extractor profiles derived from non-token legacy
inputs retain `legacy-<32hex>` identities. That exact derived shape and its
versioned `legacy-strict-v1-<64hex>` escape shape are reserved compatibility
domains: explicit binding syntax refuses them, while predecessor-accepted
legacy inputs occupying either shape are escaped deterministically instead of
being rejected. Other strict-valid legacy profiles continue to pass through.

The exact changed-boundary PostgreSQL selector was invoked twice for this
candidate and refused admission before collection both times because the
active-run limit would be exceeded. The first refusal recorded no live runtime
residue and repository recovery reconciled its terminal record before the one
permitted retry. The candidate therefore has scoped unit evidence but no
executed PostgreSQL proof; MS-ID1-FIX2 is not complete and MS-FLAKE2 remains
gated. This correction note grants no successor or publication authority.

MS-FLAKE2 implementation note (2026-08-30): the separately authorized local
candidate admits explicit `folder` and `git-working-tree` binding inventories
through the existing Python extraction, canonicalization, staging, and sole
publisher path. It captures every binding into one ordered `snap1:` vector,
constructs one `cand1:` candidate, and refuses disabled, missing, unreadable,
unsupported, changed-during-capture, or resolver-failing inventories before a
publishable bundle exists. Explicit-binding graphs use binding-alias-qualified
graph-key-v1 paths from their first binding; unchanged legacy graph syntax
keeps its existing one-source paths and keys. ADR 0058 owns that encoding and
the bounded Nix relation decision. No migration, second publisher, Nix
evaluation, hosted acquisition, or successor architecture phase is introduced.
Complete PostgreSQL and promotion qualification remains pending for the
logically approved hosted Staging Gate.

## Date

2026-08-30

## Context

RepoMap's current implementation is a strong local reference system, not the
settled mass-market deployment topology. The committed architecture has:

- one configured source root and stable repository identity per graph;
- one exactly resolved PostgreSQL database per configured graph plus a
  separate local coordinator control database;
- deterministic static extraction and canonicalization;
- direct refresh as the default and recovery path;
- an optional durable Python coordinator with bounded worker processes,
  leases, retries, cancellation, fencing, and `commit_unknown`
  reconciliation;
- receipt-bearing staged publication as the sole supported final graph
  mutation path; and
- bounded CLI and source-blind, read-only MCP readback.

Those contracts are valuable. They are the current as-built authority,
reference implementation, development and qualification environment,
contributor and power-user distribution, and a possible private/self-hosted
product. They do not imply that ordinary users should install and administer a
local PostgreSQL stack.

RepoMap's long-term broadly accessible commercial product is cloud-first. A
managed service is expected to be the easiest distribution for individuals and
teams and the primary recurring-revenue product. Enterprise deployments may
require dedicated placement or private ingestion, while the local product
continues to serve contributors, power users, qualification, and self-hosted
use.

Multi-source graph composition is also immediate. A real first corpus is an
operator-controlled, open-ended constellation of modular Nix flake
repositories: an entry composition, public and private composition layers,
security and domain modules, developer and editor experience, and agent
governance/control modules. More repositories may appear as the constellation
is decomposed. Durable public documentation records those roles, not private
source, machine paths, credentials, or raw private graph data.

The current single-root and database-local assumptions make both directions
more expensive as they harden. The correction therefore begins with additive,
reversible identity and contract seams rather than waiting for the local
implementation to be considered permanently complete.

## Problem Statement

How should RepoMap evolve from its one-root local implementation into a
cloud-first product that composes several immutable source snapshots into one
deterministic graph, while retaining one semantic authority, one publisher per
graph authority, exact evidence, privacy boundaries, and a reversible local
compatibility path?

The control-plane language and final physical service decomposition are
questions to earn with production-shaped evidence. Cloud-first delivery and
early multi-source composition are premises of this decision, not bakeoff
variables.

## Composition Is Not Federation

**Multi-source graph composition** builds one graph candidate and one accepted
publication from several explicitly bound source snapshots. The candidate has
one graph authority, one snapshot vector, one semantic policy, and one
publisher. Cross-source relations are resolved inside that candidate.

**Federation** queries or composes across independently published graph
authorities, tenants, workspaces, or privacy domains. Each member has its own
publication identity, authorization, freshness, and partial-failure boundary.

The modular-flake use case is multi-source composition. It does not require
fleet federation. Federation remains later work because it cannot borrow the
single transaction, single publisher, or single privacy boundary of one graph.

## Decision

### 1. Product delivery is cloud-first; semantics are deployment-neutral

RepoMap will design its durable semantic, snapshot, bundle, and publication
contracts so that they do not depend on a laptop path, container mount, pod,
region, database name, or cloud provider. The same logical contracts must
support:

- a local filesystem snapshot/bundle implementation for development,
  qualification, contributor, power-user, and self-hosted use; and
- a cloud object-storage implementation for immutable snapshots and bundles.

PostgreSQL may remain canonical graph and publication authority. Object
storage, queues, caches, search indexes, and alternate read projections are
operational or derived components. None may become a second semantic engine or
publication authority.

### 2. Logical identity model

The target model has the following distinct concepts. This is a logical
contract, not a schema authorization.

| Concept | Identity and authority |
| --- | --- |
| Account or tenant | Authentication, billing, policy, retention, and top-level isolation boundary. Its stable ID is not a database or cloud-account locator. |
| Workspace or project | Organizational and authorization container inside a tenant. It owns graph definitions but is not itself a graph publication. |
| Graph | Stable logical graph definition and publication authority inside a workspace. Physical storage placement is resolved separately. |
| Source definition | Stable, policy-governed description of an admissible source and acquisition methods. A URL or local path is mutable locator data, not the source definition's identity. |
| Graph-source binding | Stable assignment of one source definition to one graph, with an explicit source role, binding revision, resolution policy, privacy policy, and deterministic precedence/conflict policy. |
| Immutable source snapshot | Content-bound manifest of exactly the files and bytes made available to extraction, plus acquisition and integrity evidence. It never takes identity from a worker mount path. |
| Artifact | Immutable intermediate evidence or extractor product bound to its input snapshot, producing attempt, contract version, and byte domain. It is not accepted graph state. |
| Extraction or resolution attempt | One bounded execution over declared inputs, recording declared and achieved capabilities, outcomes, resource bounds, and producer/consumer verification as required by ADR 0050. |
| Graph candidate | Unaccepted deterministic semantic result bound to one exact graph-source binding revision and snapshot for every member of its source vector, plus semantic/configuration contract versions. |
| Publication bundle | Portable deterministic candidate payload and provenance needed by the publisher. Its integrity does not make its semantics accepted. |
| Accepted graph publication and receipt | Atomically visible graph generation accepted by the graph's sole publisher, with a receipt binding graph, candidate, bundle, generations, and publication outcome. |
| Derived cache, index, or search projection | Rebuildable read optimization bound to an accepted publication. It cannot create canonical facts, advance publication, or silently become semantic authority. |

Account, workspace, and graph identities are stable logical IDs. Source,
binding, snapshot, candidate, bundle, and publication identities are different
because they answer different questions. A digest proves bytes within its
declared framing and domain; it does not prove acquisition authority,
capability, semantics, or acceptance.

ADR 0056's proposed `PublicationRef` is the typed read-side reference to one
accepted publication in this model. Its eventual contract must bind tenant,
workspace, graph, accepted receipt/generation, candidate and snapshot vector,
semantic contract versions, and privacy without exposing or depending on a
physical database locator. It remains unimplemented until separately
authorized.

### 3. Multi-source key and relation invariants

Existing one-source graphs migrate additively into a graph with one explicit
binding. Their current repository identity and canonical semantics remain the
compatibility input; migration must prove equivalent nodes, edges, evidence,
receipt behavior, and readback before the compatibility adapter can retire.

For source-local entities, durable identity is scoped by stable graph and
binding identity before applying the existing versioned canonical key grammar.
In particular:

- a file is identified by binding plus normalized source-relative path, never
  by a checkout or mount path;
- duplicate relative paths in different bindings remain different files;
- duplicate symbol spellings in different bindings remain different symbols
  unless an accepted cross-source rule establishes a shared external or domain
  identity;
- snapshot order and worker scheduling do not affect identity;
- adding a new binding changes the graph candidate but does not re-key
  unrelated bindings or their entities; and
- removing or replacing one binding cannot silently transfer its identity to
  another source.

This is a logical scope requirement, not a selection of a persisted column,
namespace encoding, or graph-key version. `MS-ID1` must decide persisted-family
and cross-source edge scope against the current foreign keys before selecting a
serialization or migration. A binding-qualified relational scope, a
per-namespace version, and a new graph-key version remain alternatives until
that gate; the one-binding adapter must preserve existing public keys while the
decision is reversible.

A graph candidate binds an exact canonical map, ordered by stable binding ID,
from each binding revision to one immutable snapshot. List position is not
identity. The candidate also binds the graph contract, resolution policy,
configuration generation, and achieved-capability evidence required for its
claims.

Cross-source resolution must report one of these outcomes without promotion by
convenience:

- **exact**: one target is established under the pinned policy and achieved
  capabilities;
- **ambiguous**: more than one target remains possible;
- **conflicting**: authoritative inputs or applicable rules disagree;
- **evaluation-dependent**: the result depends on a platform, option,
  evaluation, or runtime fact not established by static evidence; or
- **unsupported**: no admitted resolver achieved the capability required to
  decide.

Only an exact result may become an exact canonical cross-source relation.
Other outcomes remain bounded evidence or explicit unknown/conflict state; an
arbitrary precedence rule cannot disguise them as exact. Any future persisted
family or edge-vocabulary change remains a separately authorized ADR and
migration.

### 4. Source acquisition and custody

Source definitions may permit, subject to explicit policy and authorization:

- an exact Git commit or tree;
- a dirty worktree represented by a closed base-plus-overlay manifest;
- a local directory represented by a closed content manifest;
- an archive with verified framing, membership, and content identity; or
- an authorized remote acquisition that materializes one of those immutable
  forms before extraction.

The acquisition layer records source definition, authorization class,
requested revision, resolved immutable revision when applicable, manifest,
redaction/privacy class, producer, and integrity checks. Git labels, branches,
URLs, remote object keys, local paths, and temporary mount paths are locators or
observations. None is sufficient semantic identity by itself.

Extraction reads only the admitted immutable snapshot. A cloud worker does not
gain ambient forge, tenant, network, or source-root access merely because it
can process a snapshot. Source retention, deletion, encryption, regional
placement, and legal policy belong to tenant/workspace policy and must be
enforced independently from graph semantics.

### 5. Semantic worker and publication authority

The Python extraction, canonicalization, and resolution path remains the one
authoritative semantic implementation until a separate parity decision says
otherwise. Parser helpers may remain language-specific bounded subprocesses;
they do not become competing semantic engines.

The target worker consumes immutable snapshots and a closed job contract,
produces artifacts and a publication bundle, and holds no graph-write
credential. Direct and coordinator modes become adapters over the same worker
and bundle contracts rather than independent semantic paths.

Exactly one accepted publisher owns final mutation for a graph authority. The
publisher verifies bundle contract, graph/candidate binding, generation,
fencing token, idempotency key, achieved-capability requirements, and privacy
policy before atomic publication. Existing Python/Psycopg staged publication
is the incumbent publisher and recovery authority. A new control plane does
not imply a new publisher language.

Publication ambiguity remains explicit. If the publisher loses its connection
across commit, it reconciles the accepted graph marker and receipt before any
retry. A queue, worker result, object-store write, cache fill, or control-plane
status cannot resolve `commit_unknown` by assertion.

### 6. Cloud control and execution contracts

The target topology separates responsibilities without prematurely fixing the
number or language of deployable services:

```text
API / CLI / read-only MCP
        |
tenant, workspace, graph authorization
        |
job control, admission, placement, leases, audit
        |
authorized acquisition -> immutable snapshot store
        |
isolated semantic workers -> artifacts / publication bundles
        |
one fenced publisher per graph authority -> canonical PostgreSQL
        |
read APIs -> rebuildable caches / search projections
```

The control plane owns stable request and job identity, admission, queueing,
leases, retry policy, cancellation, worker placement, quotas, backpressure,
and audit. Every attempt has a unique identity and fencing epoch. An
idempotency key binds the graph operation and exact candidate inputs; it does
not collapse different snapshot vectors. Heartbeat expiry permits reassignment
only after attempt ownership and publication state are reconciled.

Workers are isolated by tenant/workspace policy and receive only the snapshot,
configuration, resource budget, and output capabilities needed for one job.
CPU, memory, wall time, output size, concurrency, and database pressure are
bounded. Cancellation is cooperative first, forceful at a bounded process/job
boundary, and never presents a partial bundle as accepted publication.

### 7. Logical graph isolation is independent of database placement

The current local database-per-graph topology remains a supported placement,
not a cloud identity rule. Hosted evaluation must compare:

- database per graph;
- database per tenant or workspace with logical graph isolation;
- shared partitioned placement with enforced tenant/workspace/graph keys; and
- dedicated enterprise placement.

A placement registry maps logical graph authority to physical PostgreSQL and
object-store locations. Physical cluster, server, database, schema, bucket,
region, pod, and mount identifiers never enter canonical node, edge, snapshot,
candidate, or publication identity.

Any placement may be accepted only with authorization, isolation, backup,
restore, deletion, noisy-neighbor, connection-budget, migration, and
`commit_unknown` evidence appropriate to that topology. Cross-database
atomicity is not presumed. PostgreSQL remains canonical unless a later storage
ADR proves a replacement; derived stores rebuild from an accepted publication
and fail closed on generation mismatch.

### 8. Product surfaces and hosted value

The cloud service may expose an authenticated API, hosted CLI operations, and
read-only MCP readback. MCP remains source-blind by default and gains no graph
write, source acquisition, lifecycle administration, or raw source-byte
authority from cloud deployment.

An optional local/private ingest agent may later acquire private source under
owner policy and upload an encrypted immutable snapshot or bundle. Such an
agent is an acquisition boundary, not a semantic engine or publisher, and
requires its own threat model and authorization.

Hosted value is evaluated separately for:

- individuals: low-friction import, refresh, bounded query, and retained graph
  history without local database administration;
- teams: shared workspaces, explicit graph/source roles, reproducible
  publications, collaboration, quotas, and audit; and
- enterprises: strong tenant isolation, private ingestion, dedicated
  placement where needed, retention/deletion controls, audit, support, and
  commercial assurances.

## Preferred Migration Direction

RepoMap chooses a bounded, seam-first strangler migration. The preferred
direction is not "Go spine now." It is:

1. make source, binding, snapshot, candidate, bundle, and publication
   boundaries explicit and additive;
2. prove multi-source value through the current Python semantic path;
3. remove graph-write credentials from the semantic worker;
4. preserve exactly one publisher; and
5. select a hosted control-plane implementation only after cloud-shaped
   evidence.

This direction can be realized by evolving Python, introducing a Go control
plane later, using managed job execution, or combining them. Control-plane
language is subordinate to the contracts and must not create another semantic
or publication authority.

## Alternatives

| Candidate | Strengths under the cloud-first workload | Risks and evidence required | Disposition |
| --- | --- | --- | --- |
| Evolve the Python coordinator/runtime into modular cloud services | Lowest semantic migration risk; reuses durable job, Psycopg, publication, and recovery knowledge; fastest path to multi-source value | Existing local process/database assumptions may raise operational coupling, horizontal-scaling cost, startup cost, and control-plane maintenance burden | Retained as the incumbent and a bakeoff candidate |
| Go control/API/query spine with Python semantic worker and initial Python/Psycopg publisher | Strong candidate for bounded concurrency, service deployment, static delivery, and control-plane operability while preserving Python semantics | Adds cross-language protocols and operating burden; claimed throughput or packaging benefit must be measured in production-shaped conditions; must not duplicate worker or publisher contracts | Retained as a measured strangler candidate, not preferred by language |
| Thin service layer plus managed/containerized jobs with coordination primarily in PostgreSQL and Python | Small service surface; may exploit managed scheduling and keep durable state close to the incumbent | Provider coupling, queue/database contention, cold starts, cancellation/recovery semantics, and observability may be harder; PostgreSQL must not become an implicit queue without measured limits | Retained for cloud alpha and bakeoff |
| Bounded hybrid using contract seams, isolated jobs, incumbent semantics, and evidence-selected control components | Maximizes reversibility and permits the smallest useful service decomposition | Can become incoherent if "hybrid" excuses duplicate contracts, dual writers, or indefinite component sprawl | Preferred migration method, with physical component and language choices gated |
| Full Go semantic rewrite | Could eventually reduce runtime-language diversity if exact parity were proved | Highest semantic drift and migration risk; creates a second semantic authority during transition; no current evidence justifies it | Rejected as the default candidate; reconsider only under a separate semantic-parity decision |
| Keep the one-root local topology until all local stabilization is complete | Avoids near-term architecture work | Deepens identity, path, database-placement, and writer coupling and delays the immediate multi-source use case | Rejected |
| Treat modular repositories as federated independent graphs | Reuses current graph isolation | Loses one candidate, one cross-source resolver, and one publication authority; adds authorization/freshness fanout without solving composition | Rejected for the immediate use case |
| Design a serious desktop distribution as this cloud migration | Could broaden local accessibility | A credible desktop product likely needs a distinct SQLite-oriented project or derivative and different packaging/storage decisions | Deferred outside this repository phase |

## Decision Gates And Rollback Boundaries

Each successor has an explicit gate and a rollback that does not introduce a
second authority.

| Boundary | Decision gate | Rollback boundary |
| --- | --- | --- |
| Additive identity foundation | One-source compatibility proves unchanged canonical semantics, publication/receipt behavior, and stable existing repository identity; multi-source IDs exclude physical locators | Keep the one-binding adapter and old read path; do not perform destructive key/schema retirement |
| Modular-flake multi-source slice | A public-safe representative fixture and separately authorized private dogfood prove deterministic snapshot vectors, duplicate-path isolation, cross-source outcomes, replay, failure, and useful queries | Disable multi-source admission and retain independently valid one-binding graphs; no source is re-keyed into another binding |
| Portable snapshot/worker/bundle/publisher contracts | Local filesystem and object-storage adapters prove identical manifest/bundle semantics, bounded decoding, integrity domains, cancellation, retry, and receipt binding | Route the same contract through the in-process/local adapter; no live dual protocol or publisher |
| Database-independent semantic worker | Exact semantic equivalence and failure behavior hold with zero graph-write credential and bounded resources | Invoke the incumbent semantic path through the same contract while retaining the incumbent sole publisher |
| Explicit publisher seam | Remove in-process publication coupling and graph-write credentials from the semantic path, writer census remains exactly one accepted publisher, and `commit_unknown`/replay/fencing remain exact | Roll back publisher implementation behind the same single-writer interface; never re-enable concurrent writers |
| Hosted single-tenant alpha | One useful operator/tenant workflow meets security, privacy, recovery, observability, and cost budgets in a production-shaped environment | Stop hosted admission, retain/export immutable artifacts as policy permits, and continue supported local operation |
| Control-plane bakeoff | Python, Go, and managed-job shapes run the same frozen workload and contracts; a winner materially improves measured service objectives without semantic or publisher drift | Retain the incumbent control plane; discard the candidate component without graph migration |
| Multi-tenant hardening | Authorization, isolation, quotas, deletion, retention, billing, placement, backup/restore, and audit pass adversarial and production-shaped gates | Refuse new tenants or return to single-tenant placement; preserve accepted graph publications and local export |
| Federation | Single-graph multi-source value is proven and per-authority identity, authorization, privacy composition, fanout, freshness, and partial failure are accepted | Disable federated queries; independent accepted graph authorities remain intact |

No phase may use rollback as authority to destroy an accepted publication,
discard required audit evidence, weaken tenant isolation, or restore a second
writer.

## Ordered Roadmap

The migration begins now in this order (with prefix namespaces `MS` =
Multi-Source, `STR` = Strangler Seam, `CTRL` = Control Plane, `FED` =
Federation). Every identifier after `CLOUD-MULTISOURCE0` is a planned,
independently authorized packet.

1. `CLOUD-MULTISOURCE0` — reconcile cloud-first product direction and
   immediate multi-source architecture in durable canon.
2. `MS-ID1` — add source definition, binding, snapshot, candidate, and
   publication identity foundations with one-binding compatibility.
3. `MS-FLAKE2` — deliver a modular-flake multi-source vertical slice through
   the current Python semantic and staged-publication path.
4. `STR-SEAM3` — define and prove portable snapshot, existing-worker
   extension, extraction receipt, publication bundle, and publisher contracts.
5. `STR-WORK4` — make the Python semantic worker database-independent and
   remove graph-write credentials.
6. `STR-PUB5` — establish the explicit single publisher interface and remove
   graph-write credentials and in-process publication coupling from the
   semantic path without a dual-writer interval. This does not claim a
   receiptless final writer exists today.
7. `CLOUD-ALPHA6` — operate the smallest useful hosted single-tenant or
   operator-tenant alpha.
8. `CTRL-BAKEOFF7` — compare retained Python, Go, and managed-job control-plane
   shapes under the same production-shaped workload.
9. `CLOUD-HARDEN8` — add multi-tenant authorization, quotas, billing,
   retention/deletion, placement, and enterprise hardening.
10. `FED-LATER9` — consider federation only after single-graph multi-source
    value and its authority contracts are accepted.

This order supersedes ADR 0056's placement of cloud/service decomposition after
the complete local hybrid branch. It does not cancel current local maintenance,
qualification, or separately authorized work; it changes the dependency order
for new architecture and implementation phases.

## Benchmark Authority

### Local deterministic qualification

Laptop and local-container evidence may establish:

- exact one-source and multi-source semantic equivalence;
- identity stability when sources move, mounts change, or unrelated bindings
  are added;
- duplicate-path and duplicate-symbol isolation;
- exact, ambiguous, conflicting, evaluation-dependent, and unsupported
  outcomes;
- deterministic snapshot, bundle, replay, failure, cancellation, and
  `commit_unknown` behavior;
- algorithmic complexity, bounded CPU/allocation profiles, and regression
  detection; and
- fast developer feedback.

These results qualify the named deterministic contract under the recorded
conditions. They do not select production architecture for EKS or an
equivalent managed cloud deployment.

### Production-shaped cloud evaluation

Cloud architecture decisions require Linux containers and the intended class
of managed network, database, object storage, scheduling, and isolation. A
frozen workload must include one-source and multi-source sizes, concurrent
tenants/jobs, cold and warm paths, cancellation, retry, worker loss, publisher
ambiguity, backpressure, and recovery.

Record at least:

- queue delay and admission refusal;
- cold/warm startup;
- acquisition, extraction, bundle, publication, and query p50/p95/p99 latency;
- throughput and concurrency saturation;
- vCPU-seconds, peak and steady memory, database time, connection count and
  wait, object-store operations, and bytes transferred;
- worker retry, cancellation, fencing, `commit_unknown`, and recovery outcomes;
- retained snapshot, bundle, graph, cache, log, and audit storage;
- estimated cost per indexed source unit, candidate/publication, retained
  graph, and representative query; and
- isolation, privacy, deletion, and observability outcomes.

The bakeoff freezes semantic contracts, workload, data shapes, environment,
versions, stopping rule, replacement policy, and acceptance thresholds before
execution. `not_run`, `not_comparable`, and `inconclusive` are valid outcomes.
No laptop throughput or allocation result is sufficient production-selection
evidence.

## Security, Privacy, Retention, And Audit

- Tenant, workspace, graph, source, snapshot, artifact, and publication
  authorization are checked at every acceptance boundary; possession of a
  locator or digest is not authorization.
- Private source and snapshots are encrypted in transit and at rest under a
  separately accepted implementation policy, with bounded service access and
  auditable acquisition, worker, publisher, read, export, retention, and
  deletion events.
- Logs, metrics, receipts, and error payloads are bounded and redacted. They do
  not contain raw private source, secrets, credentials, or unnecessary private
  repository metadata.
- Derived projections inherit at least the accepted publication's privacy and
  retention class and are deleted or rebuilt when their authority publication
  changes or expires.
- Deletion must cover physical replicas and derived stores without rewriting
  semantic identity or falsely claiming immediate erasure where provider
  backup retention still applies.
- Enterprise dedicated placement changes physical custody, not graph or entity
  identity.

## Rejected Interpretations

This ADR does not mean:

- local PostgreSQL is obsolete or no longer supported;
- cloud deployment is implemented or qualified;
- one physical database per graph is the hosted default;
- Go is the selected control plane, query plane, publisher, or semantic engine;
- PostgreSQL must be replaced by an object, graph, vector, search, or NoSQL
  store;
- object storage, a queue, Redis-like cache, or search service is canonical
  semantic authority;
- multi-source composition permits cross-tenant or cross-privacy-domain reads;
- federation is part of the modular-flake slice;
- MCP may return source bytes, acquire source, or mutate graphs;
- a desktop SQLite product is a packaging variation in this roadmap; or
- a local benchmark is hosted-production qualification.

## Scope And Non-Scope

This decision changes product and roadmap canon only. It defines logical
identities, authority boundaries, alternatives, migration gates, benchmark
classes, and rollback boundaries.

It does not create or modify source, tests, schemas, migrations, dependencies,
queues, APIs, MCP tools, object stores, databases, containers, Kubernetes/EKS
resources, cloud accounts, credentials, billing, deployments, workflows,
branches, pull requests, hosted runs, or releases. It does not inspect or copy
private source into this repository.

## Consequences

RepoMap gains a cloud-first commercial direction without pretending that a
cloud service exists, and it gains an immediate multi-source migration path
without conflating composition with federation. The local implementation stays
authoritative for current behavior and becomes the one-binding reference case.

The cost is deliberate contract work before broad service decomposition.
Identity, snapshot custody, bundle verification, single-publisher behavior,
tenant isolation, and production-shaped cost evidence become gates rather than
cleanup after deployment. Language and component choices remain reversible
until the evidence earns them.
