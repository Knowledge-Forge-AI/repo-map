# ADR 0038: Local Operations, MCP, And Canonical Readback Architecture

## Status

Accepted with explicit review triggers.

## Date

2026-07-13

## Context

RepoMap normally records the governing architecture for an epic in phase
`<FAMILY>0`, before implementation begins. The LOCAL epic deliberately reversed
that order as an experiment. LOCAL0 was an operational assessment, not a formal
ADR. LOCAL1 through LOCAL40 then supplied implementation, correction, lifecycle,
CLI, MCP, privacy, compatibility, and six-graph dogfood evidence before the
architecture was frozen.

LOCAL41 reconstructs, evaluates, and formalizes the architecture that resulted.
It does not claim that LOCAL originated decisions already accepted by earlier
ADRs. Where LOCAL implemented, refined, or tested an earlier decision, this ADR
states that relationship explicitly.

The reverse order had material benefits. Decisions were tested against real
six-graph CLI and MCP behavior; defects and incompatibilities were found before
the architecture was accepted; removal of three legacy commands was based on
observed graph behavior; and privacy, source-protection, database-lifecycle, and
restore contracts were exercised before formal acceptance.

The method also had material costs. Architectural intent was distributed across
41 phase records; repeated decisions were harder to evaluate without one
governing record; a conflicting late conclusion could have invalidated completed
implementation; audit and reconstruction cost was high; and contributors could
temporarily lack one authoritative explanation of the system. The successful
outcome does not make the experimental sequence an automatic default.

Current source and tests agree with the durable LOCAL contracts. No present
correctness, privacy, compatibility, operability, or architectural defect
requires a LOCAL implementation revision.

## Decision

RepoMap accepts the first-release local-operations architecture established and
tested by LOCAL0 through LOCAL40, subject to the review triggers in this ADR.

The final recommendation is:

```text
LOCAL architecture upheld.
No immediate remediation.
LOCAL remains closed after LOCAL41.
```

LOCAL42 is not selected.

The accepted architecture has the following governing principles:

- a configured graph identity and configured repository scope are stable across
  checkout relocation;
- each configured graph uses a dedicated database for destructive isolation;
- machine-local values live in a late-sorting untracked overlay and exact target
  ledger rather than the public repository;
- source roots are protected, read-only inputs and target code is never executed;
- destruction is exact-allowlisted and backup-first;
- rebuild is an explicit composition of inspectable lifecycle primitives;
- lifecycle and destructive operations remain CLI-owned while MCP remains
  read-only;
- private-local dogfood exposes at most one graph to MCP at a time and restores
  the hidden state after each canary;
- MCP metadata is path-free and output is bounded and deterministic;
- canonical storage, canonical graph identity, and the shared canonical edge
  vocabulary define the product model;
- raw observations remain explicitly named evidence and diagnostic access;
- remaining legacy behavior stays visibly labeled and receives a separate
  retirement decision;
- the three obsolete legacy storage commands remain removed; and
- forced-full transactional refresh is the only supported first-release refresh
  mode, while high-scale and incremental storage remain evidence-gated deferrals.

## Stable Graph Identity And Repository Scope

Recommendation: Uphold.

A stable graph ID selects the graph registration. The registration's configured
repository name is the canonical repository scope used by graph identity and
storage. Absolute checkout paths are routing inputs, not durable product
identity. Moving a repository without changing the configured graph ID or
repository name therefore does not change canonical identity.

Changing the configured repository scope is an identity change. It requires an
explicit rebuild and migration decision; it must not silently merge the old and
new scopes or rely on checkout-path coincidence.

## Dedicated Database Per Graph

Recommendation: Uphold with review trigger.

One database per graph provides exact destructive isolation, clear backup and
restore ownership, unambiguous graph-to-database routing, and straightforward
failure attribution. The cost is one database lifecycle per graph and increasing
administrative burden as the graph count grows.

This topology is not a permanent rejection of federation or tenancy. Review it
when database count becomes an evidenced operational burden or when a federation
or multi-tenant architecture changes the isolation boundary.

## Machine-Local Overlay And Exact Target Ledger

Recommendation: Uphold with review trigger.

Machine-local graph, root, and database values remain in an untracked,
late-sorting operations overlay. Destructive authorization requires an exact
graph, root, and database ledger match. This keeps machine-local topology out of
the public repository and prevents a valid component from being recombined into
an unauthorized target.

The design duplicates some registration facts and can drift. Review it if
multiple environments need a shared profile abstraction, if ledger drift becomes
an observed operational failure, or if a typed environment policy can preserve
the same exact-target guarantee with less duplication.

## Protected-Source Dogfood Policy

Recommendation: Uphold.

Registered source roots are read-only inputs. RepoMap does not execute target
code, target scripts, package managers, generators, or tests while extracting or
operating on graphs. External development may continue concurrently.

Operation-scoped before-and-after fingerprints prove that RepoMap did not mutate
the source. Stored drift compares accepted graph state; preflight drift compares
the current source before mutation. Source movement after a stored baseline is
not itself a RepoMap defect when safety drift is absent and provenance is clear.

## Exact-Allowlisted Backup-First Destruction

Recommendation: Uphold.

Destructive database actions require exact target validation. Dropping an
existing authorized database requires a successfully created and verified backup
before the drop proceeds. Unrelated databases are fingerprinted around the
operation, and system, default, and template databases are prohibited targets.

No general emergency bypass is accepted. A future emergency mechanism would
need its own authorization, approval, audit, and recovery architecture; urgency
alone must not weaken exact targeting or backup verification.

## Explicit Rebuild Composition

Recommendation: Uphold with review trigger.

The accepted rebuild sequence is:

```text
backup-first drop
→ init from migrations or verified restore
→ preflight
→ forced-full refresh
→ status
→ summary
→ baseline
→ immediate drift
```

Each primitive has an independently observable result and failure boundary. A
future convenience command may orchestrate these primitives only if it preserves
exact-target validation, backup receipts, stop-on-failure behavior, per-step
reporting, and the ability to inspect or resume safely. RepoMap does not accept an
opaque reset primitive.

## CLI-Owned Lifecycle And Read-Only MCP

Recommendation: Uphold with review trigger.

Initialization, backup, restore, drop, refresh, baseline mutation, and other
lifecycle actions remain CLI-only. MCP remains read-only. RepoMap does not expose
a model-controlled PostgreSQL command or a lifecycle MCP surface.

Review this boundary only after an explicit design provides authentication,
authorization, approval, audit, policy enforcement, exact target scoping,
backup-first recovery, and safe interruption semantics. Read-only model access
does not imply authority to mutate graph or database state.

## One-At-A-Time MCP Visibility

Recommendation: Uphold as a private-local dogfood procedure.

Machine-local dogfood graphs remain hidden by default. A canary may expose one
graph at a time, exercise the applicable read-only surface, and then restore the
hidden configuration. Cleanup is mandatory and hidden graph selection does not
reveal private topology.

This is a private-local dogfood procedure, not a universal deployment policy.
An authenticated multi-user deployment may define a different visibility model
through a separate authorization decision.

## Path-Free MCP Metadata

Recommendation: Uphold with review trigger.

MCP responses expose stable graph, project, repository, and database markers
needed for selection and interpretation, but not operations configuration paths
or public or private absolute roots. Internal routing retains exact configured
paths. Search, status, summaries, neighborhoods, failures, and canonical metadata
mask configured topology consistently.

Review only if RepoMap introduces an authenticated operator-only diagnostic API
with explicit field-level authorization, audit, and redaction contracts. Public
source availability does not justify exposing a caller's local checkout path.

## Bounded Deterministic Output And Errors

Recommendation: Uphold.

List surfaces use explicit defaults, maxima, stable ordering, offsets, and
non-overlapping pages. At acceptance:

- configured canonical file inventory defaults to 50 rows and permits at most
  200 rows per page;
- canonical MCP node and edge lists default to 50 rows and permit at most 200;
- general MCP graph searches default to 20 rows and permit at most 500;
- list offsets default to zero and negative offsets are rejected;
- raw observation payloads are disabled unless explicitly requested;
- bounded PostgreSQL failure details retain at most 512 characters; and
- streamed PostgreSQL capture is bounded at 64 KiB per captured stream.

Launch failures, nonzero exits, malformed or empty output, interruption, and
connector diagnostics remain sanitized and bounded. Runtime child output is
isolated from machine-readable parent JSON. These numeric limits may be changed
compatibly only with tests and documentation; removing a bound is an
architectural change.

## Shared Canonical Edge Vocabulary

Recommendation: Uphold.

Production code uses one canonical edge-kind set. The current set contains 65
schema-supported kinds. Migrations, canonicalization, storage validation, CLI
filters, and edge explanation must remain in parity. A migration parity test is
the required guard against one layer accepting an edge kind that another rejects.

## Explicit Canonical And Legacy Model Labels

Recommendation: Uphold until remaining legacy compatibility receives a separate
retirement decision.

Canonical node and edge counts are identified as the primary graph model.
Legacy-table totals remain explicitly labeled as legacy and must not use generic
names that imply canonical product identity. Remaining legacy MCP neighborhood
or project compatibility is separate from the three removed CLI commands and
must be inventoried and retired through its own accepted decision.

## Canonical Storage As The Product Model

Recommendation: Uphold.

Canonical storage and canonical graph readback are the default product model.
Raw observations remain explicit audit, evidence, and diagnostic access. Legacy
tables are compatibility data and are not product identities. This decision
implements and validates the canonical-storage transition accepted by earlier
ADRs; LOCAL does not claim to originate it.

## Removal Of Legacy CLI Commands

Recommendation: Uphold removal.

The following removals were intentional public-contract changes, not accidental
parser regressions. Backward-compatible aliases were rejected because they would
preserve ambiguous, unbounded, path-selected, or legacy-identity behavior under
apparently supported names.

### `repomap-kg storage files`

The previous command selected legacy storage through an absolute repository
root, returned legacy-table identities, performed client-side filtering, and
could emit an unbounded bare list. Unknown roots could appear to succeed with an
empty result.

The accepted replacement is bounded configured canonical inventory through
`repomap-kg ops graph-files --graph`, with repository markers, role and
observation-state filters, explicit pagination, and deterministic ordering. The
raw `repomap-kg files` route remains explicitly named evidence access. Legacy
node and evidence identifiers are intentionally not translated.

### `repomap-kg storage entrypoints`

The previous command projected an entrypoint role from legacy file rows. It was
not a framework-specific entrypoint model and could be mistaken for one.

The accepted replacement is
`repomap-kg ops graph-files --role entrypoint --observation-state observed`.
The raw `repomap-kg entrypoints` route remains explicit evidence access.
Framework-specific entrypoint facts are intentionally not collapsed into this
file-role projection.

### `repomap-kg storage file-nodes`

The previous command performed a legacy co-location join between file and node
rows without proving a canonical evidence relationship. It exposed legacy and
raw identifiers and could produce a large unbounded result.

There is intentionally no row-parity replacement. Use bounded canonical file
inventory for identity and aggregate evidence, canonical neighborhoods and edge
explanation for graph context, and bounded observation search for raw evidence.
Legacy stable-node and evidence identifiers are not migrated as canonical IDs.

## Canonical File Inventory Replacement

Recommendation: Uphold.

Configured canonical file inventory answers which canonical files belong to a
graph, which file roles they project, and whether they are observed or referenced
only. Neighborhood and edge-explanation surfaces answer graph-context questions.
Explicit raw-observation routes answer evidence and debugging questions.

Keeping inventory, graph context, and raw evidence separate prevents the removed
legacy co-location contract from being recreated under a new name. The
replacement does not promise exact reproduction of legacy node or evidence IDs.

## Forced-Full Refresh For The First Release

Recommendation: Uphold for the first release.

Forced-full refresh is the only supported first-release refresh mode. It
discovers the complete configured repository, prepares the complete result, and
publishes it in one authoritative transaction. A failed refresh publishes no
partial graph.

This preserves determinism and gives the supported local-repository envelope one
auditable truth. GO22 supplied bounded-memory and rollback evidence. GO23
accepted the first-release envelope and deferred high-scale and incremental
storage rather than weakening complete publication.

## Deferred High-Scale And Incremental Storage

Recommendation: Deferred pending post-release demand and measured evidence.

Set-based, COPY, or staging-table ingestion; transactional incremental storage;
append-only history retention changes; and massive-repository support are not
part of the first-release architecture.

Reconsider them when at least one supported repository is release-blocked by
measured refresh time, memory, or database growth, or when two independent
representative repositories demonstrate the same material limit. Any proposal
must preserve deterministic canonical output, one authoritative publication
boundary, rollback without partial visibility, provenance, privacy, and a
language-neutral contract.

## Relationship To Existing ADRs

| ADR | Relationship | LOCAL41 conclusion |
| --- | --- | --- |
| ADR 0001, durable graph model | prerequisite and reaffirmed | LOCAL supplied live evidence for canonical product identity, raw evidence retention, and provenance separation. |
| ADR 0002, canonical keys and vocabulary | prerequisite and reaffirmed | LOCAL corrected and tested migration parity for the shared canonical edge vocabulary. |
| ADR 0003, canonicalization and storage transition | prerequisite and refined | LOCAL completed public canonical readback and clarified the remaining explicit legacy boundary. |
| ADR 0005, additive canonical storage | prerequisite and refined | LOCAL preserves additive raw/canonical evidence while retiring three legacy public commands through a later explicit decision. |
| ADR 0007, canonical readback and explanation | reaffirmed and refined | LOCAL made canonical readback the operational default and added bounded configured file inventory. |
| ADR 0009, public query migration | reaffirmed and partially superseded | Its canonical-default, raw-access, and read-only MCP direction is upheld. Its compatibility posture is superseded only for the three named removed CLI commands; remaining legacy compatibility is unaffected. |
| ADR 0014, source ingestion | prerequisite and unaffected | LOCAL relies on acquisition/extraction separation and static processing but does not redesign ingestion. |
| ADR 0023, bulk local corpus ingestion | prerequisite and separate deferred decision | Protected static local roots are reaffirmed; massive-repository support remains deferred. |
| ADR 0031, permanent local MCP operations | prerequisite and reaffirmed | LOCAL supplied graph-registry and read-only MCP evidence. Runtime and destructive-operation refinements remain owned by ADRs 0032 and 0033. |
| ADR 0032, local runtime and config home | prerequisite and reaffirmed | LOCAL tested lexical overlays, local configuration separation, graph visibility, and exact routing. |
| ADR 0033, backup-first database lifecycle | prerequisite and reaffirmed | LOCAL tested exact-target, backup-first drop, restore, isolation, and CLI-only lifecycle behavior. |
| ADR 0034, operational-policy dogfood | prerequisite and refined | LOCAL demonstrated public-safe, source-protected, bounded operational dogfood across six graphs. |
| ADR 0035, dependency evaluation | unaffected | LOCAL41 adds no dependency and does not change the conservative dependency policy. |
| ADR 0036, package tree architecture | separate deferred decision | Remaining package compatibility is not decided by LOCAL41. |
| ADR 0037, Psycopg candidate | prerequisite and unaffected | Current readback uses the accepted connector boundary with `psql` fallback; LOCAL41 changes neither dependency nor connector policy. |

No reciprocal edit to an earlier ADR is required. The narrow ADR 0009
supersession is fully identified here and does not rewrite its historical phase
contract.

## Corrections That Reinforced The Architecture

LOCAL corrections were not separate architectural decisions. They enforced the
accepted intent:

| Correction | Architectural intent reinforced |
| --- | --- |
| operations redaction | machine-local configuration must not escape public CLI or docs boundaries |
| nested storage-status redaction | privacy applies recursively, not only to top-level fields |
| backup inspection standard-input fix | lifecycle inspection must be deterministic and safe for binary backup artifacts |
| canonical edge-kind parity | one production vocabulary must span migrations, storage, CLI, and explanation |
| bounded PostgreSQL launch, nonzero, malformed, empty, and interruption handling | connector failures must be bounded, sanitized, deterministic, and interruption-safe |
| runtime JSON stream isolation | child diagnostics must not corrupt parent machine-readable output |
| MCP metadata redaction | read-only access does not authorize local topology disclosure |
| explicit legacy count labels | canonical and compatibility models must remain visibly distinct |

## Decisions Changed During LOCAL

LOCAL made several genuine public-contract changes as evidence accumulated:

- MCP metadata became path-free for public as well as private graphs because a
  public repository does not make a local checkout path public metadata.
- Internal repository IDs were removed from MCP presentation while exact
  internal routing was retained.
- Generic storage count names were replaced with explicit legacy count labels.
- The three obsolete storage commands were removed without aliases after their
  behavior and replacement surfaces were evaluated individually.
- Bounded pagination became part of the canonical replacements rather than an
  optional presentation detail.

These changes are accepted refinements. They do not demonstrate a present need
to reopen LOCAL.

## Retrospective ADR Workflow Assessment

The reverse-order experiment improved decision quality by grounding the final
architecture in real lifecycle, privacy, CLI, MCP, connector, compatibility,
and six-graph evidence. It exposed defects before acceptance and prevented an
ADR from freezing mistaken assumptions about legacy behavior.

It did not clearly reduce total rework. Corrections were small and evidence-led,
but the phase count and reconstruction effort were high. Architectural coherence
had to be recovered from many records, and contributors lacked one authoritative
design while the epic was active. A late conflicting conclusion could have made
completed implementation wasteful.

RepoMap therefore retains ADR-first planning as the default. Retrospective ADRs
may be used only for explicitly experimental, exploratory, discovery-led, or
dogfood-led epics whose initial objective is to discover the architecture. The
exception must be declared at the outset and must reserve a mandatory closing
ADR phase before final closure.

Future reverse-order epics should use:

```text
<FAMILY>0 discovery mandate
→ implementation/dogfood phases
→ mandatory retrospective ADR before closure
→ <FAMILY><next> remediation only when the ADR requires revision
```

LOCAL itself used:

```text
LOCAL0 assessment
→ LOCAL1–LOCAL40 implementation and dogfood
→ LOCAL41 retrospective ADR
```

The LOCAL sequence was experimental and is not an accepted general substitute
for ADR-first planning.

## Consequences

Benefits include:

- destructive isolation through dedicated databases;
- an auditable, backup-first lifecycle with explicit recovery boundaries;
- protected source inputs and operation-scoped mutation evidence;
- privacy-preserving read-only agent APIs;
- a clear canonical product model separated from raw and legacy evidence;
- deterministic bounded output and failure diagnostics;
- a simplified first-release refresh contract; and
- strong evidence from real six-graph dogfood before formal acceptance.

Costs include:

- administration of six databases in the accepted dogfood deployment;
- maintenance and drift risk for the private overlay and exact target ledger;
- a deliberately verbose rebuild workflow;
- marker-only MCP topology that is less convenient for local diagnostics;
- no MCP lifecycle automation;
- an intentional compatibility break from the three command removals;
- full-refresh time and resource cost;
- append-only historical run growth;
- deferred scaling and incremental-storage work; and
- high audit and reconstruction cost from formalizing architecture
  retrospectively.

## Alternatives Considered

### Shared Database For All Graphs

A shared database could reduce database count and simplify federation. It was
rejected for the first release because destructive targeting, backup ownership,
restore isolation, and failure attribution would become less explicit.

### Implicit Reset

One reset command could shorten operator workflow. An opaque reset was rejected
because it would hide backup, initialization, preflight, refresh, baseline, and
drift boundaries. A transparent orchestrator remains reviewable under the
explicit rebuild trigger.

### Destructive MCP Tools

Model-accessible lifecycle tools could improve automation. They were rejected
without authentication, authorization, approval, audit, exact-target policy,
and backup-first recovery architecture.

### Public Absolute Roots For Public Graphs

Exposing local paths for public repositories could make diagnostics convenient.
It was rejected because repository publication does not publish a caller's
filesystem topology.

### Compatibility Aliases

Aliases could preserve command spelling. They were rejected because they would
continue ambiguous or unsafe contracts and obscure migration to bounded
canonical surfaces.

### Raw Observations As The Default

Raw observations provide detailed evidence. They were rejected as the product
default because they are not stable canonical identities and can expose larger,
more sensitive payloads.

### Unbounded Output

Unbounded output is simple for small graphs. It was rejected because local and
agent callers require deterministic memory, transport, privacy, and diagnostic
limits.

### Immediate High-Scale Redesign

Set-based or incremental storage could improve scale. It was rejected for the
first release because current supported local repositories pass the forced-full
contract and redesign without measured demand would expand correctness and
rollback risk.

### ADR-First Versus Retrospective ADR Workflow

ADR-first planning gives contributors an authoritative intent and bounds rework.
Retrospective planning gives discovery-led epics more behavioral evidence before
acceptance. ADR-first remains the default; retrospective ADRs remain an
explicitly declared exceptional technique for exploratory dogfood work.

## Review Triggers

- **Dedicated databases:** review when database count causes a measured
  administration or recovery burden, or when federation or tenancy changes the
  isolation boundary.
- **Machine-local overlay and ledger:** review when multiple environments need a
  shared profile model or an observed ledger-drift incident defeats reliable
  operation.
- **Rebuild orchestration:** review after repeated operator error or material
  workflow cost demonstrates a need for a transparent coordinator that preserves
  every accepted primitive and receipt.
- **Lifecycle MCP:** review only after authentication, authorization, approval,
  audit, exact-target policy, backup-first recovery, and interruption controls
  exist as an accepted architecture.
- **Path-marker-only MCP:** review if an authenticated operator-only diagnostic
  API requires topology fields and can enforce field-level authorization and
  audit.
- **Historical run retention:** review when retained history materially breaches
  a documented size, backup, restore, or operator-time budget, or a retention
  policy requires bounded deletion.
- **High-scale ingestion:** review when one supported repository is
  release-blocked by measured refresh limits or two representative repositories
  demonstrate the same material bottleneck.
- **Incremental refresh:** review when measured full-refresh cost blocks a
  supported repository and a language-neutral transactional design can preserve
  determinism, rollback, and provenance.
- **Remaining legacy MCP or project compatibility:** review only through a
  separate inventory and retirement decision with consumer, migration, and
  parity evidence.
- **First-release repository envelope:** review before adding massive
  repositories or currently excluded large ecosystems, or when a current
  supported repository cannot complete a deterministic full refresh within its
  documented operating budget.
- **Retrospective ADR workflow:** review reuse only when an epic is explicitly
  chartered as discovery-led at `<FAMILY>0`; after each reuse, compare decision
  quality, rework, phase count, and audit cost before allowing another exception.

## Explicit Deferrals

- shared-database federation and multi-tenancy;
- an authenticated lifecycle MCP architecture;
- an operator-only topology diagnostic API;
- automated history-retention mutation;
- set-based, COPY, or staging ingestion;
- transactional incremental refresh;
- massive-repository support outside the accepted first-release envelope; and
- retirement of remaining explicitly labeled legacy MCP or project contracts.

## Non-Goals

LOCAL41 does not:

- implement revisions or corrections;
- change production source, tests, fixtures, schemas, or migrations;
- add lifecycle MCP tools or a model-controlled PostgreSQL command;
- restore removed commands or aliases;
- change graph identities, database topology, or machine-local registrations;
- redesign extraction, canonicalization, storage, or refresh;
- change dependencies, package metadata, or connector policy;
- run graph, database, backup, baseline, or runtime lifecycle operations; or
- decide package compatibility or high-scale architecture reserved for separate
  phases.

## Private-Data Boundary

This ADR contains no private roots, local database names, credentials, private
configuration values, backup identifiers or receipts, raw MCP payloads, source
excerpts, graph dumps, raw observations, or private development commit hashes.
Operational evidence is represented only by public paths, semantic phase names,
bounded counts, contract descriptions, and accepted outcomes.
