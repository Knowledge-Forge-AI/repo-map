# ADR 0071: Post-Promotion Local, Server Engine, and Cloud Architecture

## Status

Accepted. Records manager product direction for the post-promotion product
architecture. This ADR authorizes no implementation, dependency adoption,
extension admission, schema migration, runtime operation, or publication.
Every implementation and release slice requires separate authority.

## Date

2026-09-24

## Context

The multi-source and portable-worker/publication implementation has reached
private main. The old private-main promotion prerequisite is satisfied; that
fact does not establish public promotion or hosted qualification. Current
PostgreSQL behavior remains the reference implementation. Local SQLite and
host-native MCP are accepted targets, not shipped capabilities.

## Decision

### One product, three deployment and operations surfaces

| Surface | Accepted role | Implementation boundary |
|---|---|---|
| RepoMap Local | Useful private, offline-capable baseline; complete headless CLI/MCP without a GUI, container runtime, PostgreSQL installation, or cloud account | Embedded SQLite graph authority; retained Python semantic/extraction machinery; host-native read-only source-blind MCP |
| RepoMap Server Engine | PostgreSQL graph authority for reference and self-hosted operation; containerized reference distribution remains supported | May offer enhanced capabilities, including pgvector and queryable JSONB; self-hosting is not artificially restricted to force Cloud use |
| RepoMap Cloud | Managed service using Server Engine semantics | Remote admission, scheduling, retained publications/history, managed capacity, continuous refresh, quotas, and later multi-tenant/commercial operations |

Cloud is not synonymous with PostgreSQL. All surfaces share graph, source,
binding and snapshot identity, canonical meaning, evidence/provenance, privacy,
uncertainty, capability vocabulary/versioning, publication lineage and ordinary
operation semantics. SQL dialects, physical schemas/layouts, query plans,
process topology and optional capabilities need not match.

### Worker and publication authority

Preserve ADRs 0059–0061: the database-independent semantic worker consumes
sealed snapshots and emits untrusted receipt/publication bundles validated by
the parent. It acquires no SQLite, PostgreSQL, enrichment or publisher authority
by introducing Local. Backend-specific publication belongs to the parent/backend:
SQLite for Local, PostgreSQL for Server/Cloud. There is never more than one
accepted publication authority for a logical graph view. Current seven-family
bundle semantics remain intact; PostgreSQL physical staging is not a mandate
to copy its schema into SQLite.

### Local graph authority

Initially use one SQLite database per logical graph, with multiple source
bindings allowed, one serialized publisher/writer and bounded concurrent readers.
Accepted-generation identity is explicit. Failure or crash must preserve the
previous accepted generation. Migrations retain ordered, checksummed,
drift-refusing, backup-first principles without requiring PostgreSQL tooling.

Local may support structural traversal, symbol/path lookup, evidence/provenance
filters, bounded recursive queries, justified FTS and multi-source composition.
Local vector search is neither required initially nor architecturally prohibited.
Headless Local is part of this repository; a desktop GUI is not a prerequisite
or an implementation selected by this ADR.

### Multi-source product proof

Build on ADRs 0057/0058, MS-ID1, MS-FLAKE2, explicit bindings, source-qualified
identity and the portable-worker route. Before v0.1.0 prove useful graph
construction from multiple real sources. The private dogfood corpus is the
operator-designated darwin-is-not-a-snowflake/DINAS composition and source
family. The implementation must inspect the live DINAS source catalog/topology
and select relevant composition checkouts; no frozen folder membership or
private locator belongs in durable product semantics.

Extend the existing public-safe synthetic Nix constellation for CI: multiple
bindings, overlapping relative paths, source-qualified identity, cross-source
relations, ambiguity/refusal, provenance and atomic publication. Do not import
private source bytes or paths. The fixture lives at
`src/test/fixtures/multi_source_nix_constellation/`; current canonical pipeline
and portable publication integration owners are foundations, not greenfield work.

### PostgreSQL enhanced intelligence and admission

A useful, evidence-backed pgvector capability must be delivered before v0.1.0.
It is an optional enhanced Server capability, not an extension required in every
Server deployment. This product decision satisfies only ADR 0051 D14's
precondition for reconsidering vector search. It is **not** the D15 admission
record and admits no extension or inference runtime. Step 6 must produce a
complete accepted D15 record before adoption/enablement, preserving extension
ownership, readiness, lifecycle, restore and rollback requirements.

Use semantic candidate discovery over versioned representations of canonical
nodes/symbols, source/file summaries or unresolved-reference context. Combine
nearest candidates with exact graph/evidence filters and subsequent traversal
or resolver validation. Similarity remains heuristic unless a deterministic
resolver independently justifies a stronger canonical edge. Record embedding
model/version, dimensions, normalization/input representation, source publication
and capability version. Missing pgvector means explicit enhanced-capability
unavailability, never silent substitution under the same capability name.

Exact pgvector search is the correctness/recall reference. HNSW is the leading
approximate candidate; IVFFlat may be a benchmark alternative. Measure approximate
recall against exact search and useful task outcomes. No Apache AGE or additional
graph database is selected: RepoMap already owns graph semantics.

Vectors, summaries and embedding inputs inherit at least their source's privacy
class, including effective private-ops classification for mixed graphs. They
are not anonymized merely by embedding. Remote processing of private content
requires explicit operator authorization and a separately accepted privacy/data
handling contract; this ADR grants neither. Step 6 must name the embedding
generator/enrichment principal, input access, model/runtime authority, retention,
deletion and publication binding. The portable semantic worker gains none of
that authority by default. Current prohibitions on inference/vector generation
remain operative until the separately authorized slice accepts those contracts.

### JSONB

JSONB is workload-driven. Later evaluation may cover extractor evidence facets,
unresolved-reference metadata, model/capability provenance, server enrichment,
optional analyzer output or publication-bound query attributes. Keep canonical
identity, source/binding identity, publication authority, required foreign keys,
generation/fencing, core node/edge relations and correctness constraints
relational. Compare jsonb_ops and jsonb_path_ops GIN indexes only against named
queries. No ungoverned generic property bag or migration is authorized.

### Rust extraction and retained Python

Rust extraction is required before v0.1.0 and belongs to the shared semantic
layer independent of the eventual publisher. Start with an ADR-0050-governed
bounded parser/extractor pilot comparing credible approaches: Tree-sitter Rust,
rust-analyzer syntax/parser libraries or helper boundaries, and syn. These are
candidate families, not current capability, licensing or packaging attestations.
Verify those facts and supply-chain costs at implementation time.

Measure parse wall time, startup/process overhead, peak RSS/install footprint
where practical, observation yield, unresolved/ambiguous counts, curated-task
graph-quality deltas, malformed/incomplete-source partial evidence, platform
availability and failure containment. The selected parser is admitted under
ADR 0050 (D14's out-of-process default unless a variance is recorded) and feeds
the retained Python semantic path. A broader extractor campaign requires
separate scope; it cannot itself replace Python canonicalization or resolution.
No wholesale extractor rewrite is mandated.

Maintained Python has no speculative Go/Rust replacement exemption. Preserve
and expand existing no-new-debt ratchets in coherent retained cohorts; do not
require repository-wide zero debt before product work or invent a second quality
system. Go/Rust adoption remains component-level and evidence-driven.

### MCP and connected operation

MCP remains a primary interface. Local MCP is host-native, read-only and
source-blind: queries cannot acquire sources, refresh, publish or administer
storage. Connected operation starts with explicit publication-bound results or
projections. Server/Cloud results never silently become Local's accepted
publication. Active-active database synchronization is not selected.

### Development evidence and releases

Behavior-changing product slices require narrow local unit **and containerized
integration** tests for the changed boundary, exact paths/node IDs and
--no-coverage, with both owners updated in the same slice. SQLite integration
must exercise temporary SQLite publication/read/recovery inside the repository's
container isolation boundary; it need not use PostgreSQL except for parity.
A missing harness is work for that separately authorized slice, not permission
to bypass isolation. Refused/unavailable required integration leaves a named
verification gap and blocks claiming the slice complete unless the manager
explicitly accepts that gap. A candidate may be retained; unrelated work need
not stop. Historical MS-ID1 refusal dispositions are not rewritten.

Complete local unit, integration, smoke, staging, system or combined suites
require a manager prompt override with bounded execution count. Scoped evidence
never substitutes for hosted exhaustive milestone/release qualification.
This docs-only phase runs no product tests.

Develop on private main. Do not publish every slice to public staging. After a
significant manager-accepted milestone, separately project the exact reviewed
milestone to public staging and run the approved hosted CI campaign. Only after
that candidate passes and the manager separately authorizes promotion may public
staging move to public main as v0.0.2. Versions below v0.1.0 are GitHub-only
public previews, not package-manager releases; v0.1.0 is the first package-manager
target. Private development version metadata remains unchanged. ADR 0054's
logical gate and actor-owned branch-movement contracts remain binding.

## Supersession and preservation map

- ADR 0057 section 1's cloud-first delivery/PostgreSQL-may-remain-canonical
  posture and section 7's PostgreSQL-canonical-unless-replaced close are
  superseded by simultaneous Local SQLite and Server/Cloud PostgreSQL authorities
  over separately owned graph views, not a global backend replacement.
- Section 5's Python/Psycopg incumbent publisher remains an as-built Server
  fact, not the sole future backend publisher. Its retained Python semantics
  and bounded helper boundary remain; SQLite adds a parent/backend publisher.
- The alternatives row deferring serious desktop SQLite outside this repository
  and the rejected interpretation excluding a desktop SQLite packaging variation
  do not exclude headless Local here. A GUI remains separately scoped.
- CLOUD-ALPHA6, CTRL-BAKEOFF7, CLOUD-HARDEN8 and FED-LATER9 are deferred outside
  the required v0.1.0 sequence; none is a release prerequisite. Reopening needs
  separate authority, and federation still follows useful single-graph
  multi-source composition and independent-authority contracts.
- ADR 0031's useful private local baseline is reaffirmed, but its old physical
  topology is not revived. ADR 0032 remains the current containerized reference
  contract until separately changed. Local-first is not an exclusive commercial
  destination; Local, Server and Cloud form one product.
- ADRs 0058–0061 retain implemented identity, privacy, snapshot, worker,
  validation, fencing, receipt and publication contracts. Their original
  qualification/activation statements describe their checkpoints, not today's
  private-main placement or new hosted qualification.
- ADR 0051 admission rules and ADR 0050 dependency/capability rules are preserved.
  No historical status record is rewritten.

## Roadmap and deferred implementation

The executable ordering is in the [roadmap](../../../specs/roadmap.md):
architecture reconciliation; DINAS multi-source proof; host-native MCP/read-store
seam; SQLite Local/parity; first public-preview milestone; PostgreSQL intelligence;
Rust extractor pilot; v0.1.0 readiness. Steps 6 and 7 may reorder or partially
parallelize with explicit dependencies, but both remain release prerequisites.

Separate slices must decide SQLite transactions/recovery and reader bounds,
read-store interfaces, migrations and packaging, capability identifiers,
embedding model/representation and authorized generator, JSONB workloads/indexes,
Rust parser admission, and connected-result transport. Acceptance of this ADR
is not successor execution authority.

## Consequences

Subsequent slices execute against one Local/Server/Cloud vocabulary without
reopening the boundary. Maintaining two publisher backends adds parity,
migration and packaging cost that slices 3 and 4 must bound and measure.

This decision is wrong, and must be revisited by a new ADR rather than silently
adjusted, if any of the following is shown:

- SQLite Local cannot reach semantic parity with PostgreSQL on the one-source
  and synthetic multi-source corpora without violating the shared identity,
  evidence or publication-lineage semantics above;
- the host-native read-store seam cannot preserve PostgreSQL read parity without
  giving the portable worker or MCP storage or publisher authority;
- the DINAS or synthetic multi-source proof produces no useful graph beyond
  independent single-source graphs;
- measured pgvector candidate discovery shows no useful task advantage over
  exact graph/evidence search, or its approximate recall cannot be qualified
  against exact search;
- the Rust pilot finds no parser approach that meets ADR 0050 containment and
  packaging requirements for the retained Python semantic path.
