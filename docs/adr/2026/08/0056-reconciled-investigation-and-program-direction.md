# ADR 0056: Reconciled Investigation And Program Direction

## Status

Accepted as product and roadmap canon. Docs-only.

Acceptance is not authority to implement. This decision does not authorize a
graph refresh, benchmark run, source or schema change, new MCP capability,
dependency, migration, provider integration, or successor phase.

Amended in part by ADR 0057. Cloud-first product delivery and immediate
multi-source graph composition now precede the late cloud/service placement in
this ADR's hybrid sequence. ADR 0057 replaces that sequence with additive
multi-source and strangler seams, while preserving this ADR's source-blind MCP,
single semantic authority, single publisher, evidence, privacy, and measured
Go-versus-Python decision boundaries.

## Date

2026-08-28

## Context

Two proposal families asked RepoMap to pursue a hybrid execution architecture
and an investigation/impact-intelligence product. Their amended responses and
the final adjudication converge on one contracts-first program, `RECON0`, but
the proposal corpus is evidence rather than repository authority.

Current RepoMap canon establishes these starting facts:

- direct refresh is the default and recovery path, while coordinator mode is
  explicit;
- receipt-bearing staged publication is the only supported final graph
  mutation authority;
- Python and Psycopg own canonical readback, with `psql` retained for its
  accepted lifecycle and fallback roles;
- each configured graph resolves one dedicated database;
- the Go helper is a controlled static-extraction subprocess, not an accepted
  coordinator or read plane; and
- the MCP surface is bounded and read-only.

The proposal terms `RECON0`, `COMP0`, `PublicationRef`, `sc1:`, and
`source-blind` did not previously occur in RepoMap canon. This ADR introduces
the accepted terms explicitly; it does not present them as implemented facts.
The exact proposal label `redact-first` was also absent, but RepoMap already
requires “Redact first,” public-safe output, and private-root redaction. This
decision preserves that existing semantic policy rather than claiming to
originate it.

## Decision

RepoMap accepts a strategic direction toward a local, deterministic repository
evidence engine for bounded cross-artifact investigations. The direction is a
target to test, not a demonstrated superiority claim.

RepoMap will pursue one planned reconciliation program, `RECON0`, before any
successor implementation packet. Standalone `COMP0`, the original parallel
`RM0 + RM1-Q + RM1-P` start, and any implied Go destination are rejected.
`RECON0` itself requires a separate operator authorization. The two runtime
exceptions proposed by the adjudication--one bounded public grounding refresh
and gated read-pinning implementation--are future gates, not authority granted
by this docs-only decision.

### Terms entering canon

**Source-blind MCP.** The default MCP may return bounded stored graph facts,
identifiers, line/path markers, summaries, and evidence references, but it does
not return repository source bytes. A future source-byte resolver is a distinct,
default-off advertised capability requiring an ADR 0031 amendment, immutable
source identity, authorization, confinement, privacy, audit, and client
qualification. Read-only is necessary but does not by itself satisfy this
source-byte boundary. The term builds on, and does not replace, the current
`no_source_tree_reads`, `no_source_acquisition`, and `no_refresh` safety
markers.

**`PublicationRef`.** A proposed typed reference to one accepted graph
publication. Its contract must bind registry `graph_id`, stable repository and
source-state identity, accepted receipt and graph/source/config generations,
snapshot or artifact identity, exact hash domains and trust sources, contract
versions, and privacy. A path, display name, or producer assertion is not a
`PublicationRef`.

**`sc1:` subject-capability vocabulary.** A proposed closed, versioned
vocabulary for operational capabilities of a subject. It remains distinct from
extractor capability, source intent, runtime proof, policy judgment, side
effects, and severity. No `sc1:` graph family or edge kind is authorized here.

### Hybrid decision dispositions

| ID | Disposition | Canonical action |
| --- | --- | --- |
| RM-D1′ | Amended | Keep the target language-neutral. Go is a later measured control/runtime hypothesis, never a preference inferred from this decision. |
| RM-D2′ | Accepted | Preserve direct refresh and explicit coordinator mode as two adapters over one semantic publication path. |
| RM-D3′ | Accepted | Design graph, repository, source definition, binding, immutable source state, artifact, candidate, and publication as distinct identities that extend existing authority. |
| RM-D4′ | Accepted | Decide persisted-family scope and edge-crossing rules before key grammar, capsules, evidence references, or labels. Retain all five proposal options until evidence eliminates them. |
| RM-D5′ | Amended | Plan one public-first quality instrument, but make every score and competitive statement cohort-specific and permit truthful non-results. |
| RM-D6′ | Narrowed | Produce a delta against the accepted durable job/coordinator contract. Only a missing snapshot manifest, receipt binding, or publication bundle role may be proposed. |
| RM-D7′ | Accepted | Keep Python/Psycopg as the current agent-facing read owner and retain accepted `psql` roles. Connector change requires a separate decision. |
| RM-D8′ | Accepted | Keep core PostgreSQL authoritative. Extensions, FTS, imported indexes, vector stores, and alternate graph stores remain separate hypotheses. |
| RM-D9′ | Accepted | Preserve one receipt-bearing publisher per graph, atomic generation visibility within a graph database, and explicit `commit_unknown` reconciliation. |
| RM-D10′ | Deferred | Re-enter packaging experiments only after a stable worker boundary and separate license, supply-chain, compatibility, rollback, and measured-value review. |
| RM-D11′ | Accepted | Preserve the distinct RepoMap, control, and runner ownership surfaces. Exact-commit and immutable-result patterns are design input only. |
| RM-D12′ | Amended | Place planned `RECON0` first. This ADR records its envelope but does not authorize execution or any successor. |

### Investigation decision dispositions

| ID | Disposition | Canonical action |
| --- | --- | --- |
| INV-D1′ | Amended | Treat deterministic cross-artifact investigation as a product hypothesis; superiority requires a controlled, version-pinned, cohort-specific benchmark. |
| INV-D2′ | Rejected | Do not create standalone `COMP0`; place its fixture, comparator, scorer, and evidence work inside planned `RECON0`. |
| INV-D3′ | Accepted | Pursue reference-first, publication-pinned evidence capsules in principle; source-byte resolution remains a separate default-off capability. |
| INV-D4′ | Accepted | Pursue a bounded Python path engine in principle, using accepted facts, typed policy, deterministic order, explicit unknowns, and one pinned publication. |
| INV-D5′ | Deferred | Re-enter delta and test-impact work only after the first path milestone proves value; recommendations remain conservative and evidence-labeled. |
| INV-D6′ | Narrowed | Make `sc1:` the second product wedge only after the vocabulary, facets, coverage model, migrations, and separate coverage/recall measures are accepted. |
| INV-D7′ | Deferred | Try current structured retrieval and graph reranking first; consider SCIP/LSIF, FTS, parser, or LSP additions only through separate evidence and dependency gates. |
| INV-D8′ | Deferred | Re-enter federation only after single-graph value, publication-vector identity, privacy composition, bounded fanout, partial-failure, and authorization contracts are accepted. |
| INV-D9′ | Accepted | Preserve the current MCP compatibility surface. New investigation or evidence surfaces require exact advertised tools, safety markers, and client qualification. |
| INV-D10′ | Accepted | Exclude editing, refactoring, debugger control, shell or target execution, forge mutation, embeddings, learned ranking, and GNN work from this roadmap. |

## Product Use Cases

The planned product wedges are:

1. **UC-A--cross-artifact scoping:** publication-pinned, evidence-cited change
   scoping across source,
   configuration, tests, infrastructure, scripts, and generated artifacts;
2. **UC-B--automation and operational review:** bounded path explanations and
   later subject-capability investigations with static intent, derived paths,
   runtime proof, and policy judgment kept distinct;
3. **UC-C--change and test impact:** conservative overlay comparison and test
   guidance only after the path engine proves value; and
4. **Capsule handoff:** reference-first evidence packaging as an enabling
   workflow, not a first-phase product claim.

Fleet-wide federation, private-first corpora, source-byte evidence, and
mutation-capable agent workflows are not first-product use cases.

## Position Among Adjacent MCPs And Tools

The relevant tools solve different jobs. Their official documentation is
treated as a changing external snapshot, not as evidence of relative quality:

- [Serena](https://github.com/oraios/serena) provides semantic code retrieval
  and editing through language-aware backends. RepoMap aims to complement it:
  RepoMap scopes and explains cross-artifact evidence; a semantic editor
  navigates and performs authorized edits.
- [Sourcegraph](https://sourcegraph.com/docs) and its
  [MCP interface](https://sourcegraph.com/docs/api/mcp) provide code search and
  code-intelligence access. RepoMap does not target fleet-scale search; it aims
  to add local publication identity, evidence provenance, deterministic
  bounded paths, and explicit uncertainty for heterogeneous repository
  investigations.
- [GitHub MCP Server](https://github.com/github/github-mcp-server) exposes
  GitHub repository and collaboration operations. RepoMap remains a local
  read-only evidence engine and complements, rather than absorbs, forge state
  and mutation authority.
- [CodeGraphContext](https://github.com/CodeGraphContext/CodeGraphContext) and
  [Code Search MCP](https://github.com/LLMTooling/code-search-mcp) are relevant
  local graph/search comparators. RepoMap aims to differentiate on accepted
  publication binding, cross-language operational facts, privacy-aware
  evidence, and truthful unknowns.

No sentence above ranks a product or establishes RepoMap superiority. RepoMap
may claim an advantage only for a named use case, cohort, version/configuration,
source exposure, tool surface, context/output budget, and scoring contract
whose frozen evidence supports it. `not_run`, `not_comparable`, and
`inconclusive` are first-class outcomes. Complementarity--including RepoMap
plus a semantic tool versus that tool alone--is a valid success condition.

## Planned RECON0 Order

`RECON0` is a planned, separately authorized program with this dependency
order:

1. bind a live accepted-authority/resulting-state manifest and promotion path;
2. resolve persisted-family and edge-crossing scope, then identity options and
   the `PublicationRef` contract;
3. specify immutable snapshot, canonical serialization, hash-domain, privacy,
   and evidence-security contracts;
4. specify publication-pinned reads, continuations, and a reference-first
   capsule contract;
5. define the source-blind default and the separate evidence-read decision;
6. build one content-addressed public fixture, corpus, capability matrix,
   comparator matrix, deterministic scorer, and preflight;
7. only under separate source/runtime authority, evaluate the bounded public
   refresh and read-pinning gates; and
8. return every successor as an independently dispositionable packet.

The fixture, not a moving live graph, is the measurement instrument of record.
The first scoreable cohort is `public-dev`. Derived artifacts inherit at least
the graph's accepted privacy class. Private graph evidence and hosted comparator
exposure require separate disposition; `sensitive-local` remains excluded.

## Acceptance Criteria For A Separately Authorized RECON0

`RECON0` may claim completion only when:

- current facts are re-verified against live semantic repository state and
  evidence-labeled without recreating a brittle historical hash gate;
- accepted direct/coordinator, publication, connector, database, Go-helper,
  MCP, privacy, and promotion contracts remain explicit;
- persisted-family and edge scope precede key, capsule, evidence, and label
  freezes;
- every hash names its algorithm, framing, byte domain, and trust source;
- every cross-database transition defines receipt, retry, replay, quarantine,
  failure, and reconciliation behavior without claiming atomicity;
- the default MCP source-byte posture and optional evidence capability cannot
  be confused;
- the fixture, corpus, labels, scorer, comparator equivalence, privacy, bounds,
  denominators, thresholds, and inconclusive causes are frozen before a scored
  run;
- read-pinning returns bounded evidence or an honest specification-only result;
  and
- each successor can be rejected without authorizing or rejecting another.

## Successor Order And Re-Entry Gates

After a separately authorized and accepted `RECON0`, two advisory branches may
return for disposition.

The hybrid contract/runtime branch is:

1. `HYB-ID1`--multi-source identity and isolation proof on public fixtures;
2. `HYB-PROTO2`--only accepted durable-contract extensions;
3. `HYB-WORK3`--database-independent Python semantic bundle worker;
4. `HYB-PUB4`--bundle input at the existing sole publisher;
5. `HYB-GO5`--Go parity-and-cost hypothesis with an `inconclusive` outcome;
6. `HYB-CUT6`--optional transition only after a separately accepted positive
   hypothesis and superseding ADR;
7. `HYB-EXP7`--separately governed dependency/packaging experiments; and
8. `HYB-CLOUD8`--cloud or service decomposition only after local authority,
   identity, privacy, recovery, and quality evidence.

The investigation branch is:

1. `REPOMAP-EVID1`--reference-first evidence/capsule foundation;
2. `REPOMAP-PATH2`--generation-pinned typed investigation engine;
3. `REPOMAP-CAP3`--accepted first slice of `sc1:` intelligence;
4. `REPOMAP-DELTA4`--coordinator-owned overlay and conservative test view;
5. `REPOMAP-PREC5`--conditional precision experiments; and
6. `REPOMAP-FED6`--conditional federation.

Each identifier is a planned packet, not implementation authority. The hybrid
branch preserves one semantic authority and cannot preempt the Python
investigation branch. `EVID1` depends on accepted identity, pinning,
canonicalization, evidence-security, and privacy contracts. `PATH2` depends on
the reference-first foundation and public fixture. `CAP3` depends on measured
path value. `DELTA4` depends on immutable overlay identity. `PREC5` depends on
measured unresolved precision gaps. `FED6` depends on accepted single-graph
value and external identity/privacy contracts.

## Explicit Rejections And Deferrals

Rejected:

- standalone `COMP0` and the parallel original first-phase envelope;
- a preferred Go destination or a second semantic implementation authority;
- repository consolidation, archive, freeze, relocation, or authority transfer;
- a duplicate durable worker protocol;
- default or unrestricted MCP source-byte access;
- live dual writers, a replacement Git engine, or cross-database atomicity;
- broad, unscoped superiority claims; and
- implementation inferred from acceptance of this ADR.

Deferred behind the gates above:

- read-pinning implementation and any public grounding refresh;
- capsule, path, evidence resolver, `sc1:`, overlay, and federation code;
- graph-key, persisted-family, edge, schema, or migration changes;
- Go/pgx/Nuitka work or `psql` retirement;
- FTS, extensions, vector stores, imported indexes, SCIP/LSIF, parser, LSP,
  packaging, or dependency adoption; and
- private/hosted competitive runs or publication of competitive claims.

## Scope And Non-Scope

This decision changes RepoMap product and roadmap canon only. It does not edit
or authorize source, tests, fixtures, scripts, dependencies, schemas,
migrations, workflows, CI, branches, deployment, containers, runtime
configuration, `repo-map_ctrl`, MCP wiring, graph databases, hosts, or remotes.

JACA owns model-provider execution, hosted-provider CLI, authentication
fallback, reviewer/producer doctrine, mutation/network roles, notifications,
and XO orchestration. Agent-Security-ND owns security admission and policy.
Those topics create no RepoMap interface in this decision and are deliberately
not duplicated here. Repository content remains untrusted evidence regardless
of which orchestrator consumes RepoMap results.

## Evidence Sources

The controlling proposal evidence is retained in the separate
`agent-skunkworks` repository:

- `repo-map/responses/REPOMAP-HYBRID-REFACTOR-REVIEW-RESPONSE-AND-AMENDED-PROPOSAL.md`;
- `repo-map/responses/REPOMAP-INVESTIGATION-IMPACT-INTELLIGENCE-REVIEW-RESPONSE-AND-AMENDED-PROPOSAL.md`;
- `repo-map/reviews/06-luna-max-swarm-counter-proposal-reconciled-program-envelope.md`;
  and
- `repo-map/reviews/12-fable-adjudication-of-counter-proposals.md`.

Current RepoMap authority used for reconciliation is
`docs/specs/as-built-architecture.md`, ADRs 0031, 0038, 0041, 0049, 0050,
0054, and 0055, and the live source/tests those documents identify. Proposal
baselines and exact historical commits remain evidence, not current-state
prerequisites.

## Consequences

RepoMap gains one ordered product program, one identity/evidence vocabulary
direction, explicit competitive-claim discipline, and a stable boundary with
semantic editors, code-search systems, forge MCPs, and local graph/search MCPs.
The cost is deliberate sequencing: near-term implementation is deferred until
identity, publication pinning, evidence safety, privacy, fixtures, and scoring
are independently dispositionable and falsifiable.
