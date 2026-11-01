# ADR 0129: Publication-bound PostgreSQL lexical search and truthful evaluation

## Status and authority

Status: Accepted architecture for REPOMAP-CLOE-LEXICAL1, 2026-10-31.
Implementation remains gated on the dispatcher's independent plan checkpoint.

The operator reported CI101 passed and requested continuation of the approved
CLOE roadmap. The manager selects the first W3 milestone below under that
authority. Independent design review found defects in earlier proposed drafts;
this consolidated decision resolves them before source implementation. The
fresh plan checkpoint must inspect this resulting ADR/spec and actual source,
not infer acceptance from a producer's correction narrative.

No new dependency, extension, role class, credential store, runtime image,
live migration/deployment, complete local suite or public CI build is allocated
by this architecture decision. Publication qualification is candidate-specific.

## Context

CI101 attempt 1 qualified staging `ae636963abcf3c952150bb738b122464cec9399f`
(merge `e5759e8fbda0946098771ed395c0f059cfcf9e0c`) across all nine jobs.
Unit results were 14,766 passed/40 skipped, with 88.1% statement and 87.4% branch
coverage. Integration results were 1,928 passed/12 skipped, with 90.1% statement
coverage and 16,980/20,720 covered branches (81.9498%). The hard integration gates
passed. The requested 82% branch margin needs 11 more covered branches on that
unchanged denominator; a successor must account for its actual full denominator
and any regressions. Eighteen native AMD application starts are spent under
[ADR 0128](0128-retrieval-evaluation-milestone-staging-campaign.md).

W2's bounded captured-text projection is an evaluation reference, not a
persistent PostgreSQL index. PostgreSQL navigation and node-location read-store
methods remain unsupported. Existing calibration summaries group some
body-fallback results by metadata task intent, concealing the actual retrieval
surface. Empty resolved selection also permits an unjustified absence claim.

The accepted [roadmap](../../../specs/cloe-roadmap-transition-v1.md) calls for
core PostgreSQL lexical search before later context/fusion work. Under
[ADR 0051 D11](../08/0051-postgresql-extension-and-database-capability-architecture.md),
FTS is a separate product query; existing ILIKE substring contracts remain intact.

## Decision

Deliver three connected units and one predeclared calibration observation in
the first W3 milestone. The companion
[specification](../../../specs/cloe-native-lexical-search-v1.md) defines the
behavioral contracts and proof obligations. Later held-out execution remains
separately gated after source qualification and manager criteria acceptance.

### 1. Core PostgreSQL lexical lifecycle and explicit CLI

Use built-in PostgreSQL 16 tsvector/tsquery, GIN, pg_catalog.simple and ts_rank_cd, with
versioned analyzer, ranking and query-style policies. Terms and normalized
lexeme phrases report ranked_discovery over captured_text. A separate literal
style searches bounded LF-normalized captured text, including punctuation and
cross-chunk matches within one file. It never joins files or reads live roots.
Keep all six QueryMode and five MatchSurface values and the existing v1 envelope
unchanged. No hidden fallback, exact-identity claim or BM25 claim is introduced.

Expose `cloe ops lexical-build`, `lexical-query` and `lexical-revoke` using
maintained selected config/home/graph resolution. Build/query require explicit
body authorization and a nonempty binding selection. Query defaults disabled,
performs no DDL/indexing and returns bounded versioned JSON. Existing MCP tools
and InvestigationReadStore acquire no lexical method or owner credentials.

P1 admission is selected: supported code/prose in explicitly selected public-dev
graphs and public-dev/full-authorized bindings. Preserve actual PUBLIC or
RAW_SOURCE artifact classification. Exclude private/inherit, metadata-only,
ephemeral and email/feed bodies before artifact opens or matching. Build checks
both fresh config policy and retained portable manifests/artifacts using the
maintained validators. Query reloads actual on-disk policy without needing the
portable store; a supplied digest or cached graph object is not authority.

Store all body-derived vectors, identifiers, positions and bounded normalized
text in dedicated schema `cloe_lexical`, accessible only through existing
configured owner authority. Deny PUBLIC and existing read-status, publication
and control roles. No new roles or hidden credential fallback. Ordinary graph
readback remains useful with its existing limited authority.

Use an isolated lexical driver with the already installed dynamically linked
Psycopg 3 implementation. It owns transactions, sanitized SQLSTATE outcomes and
bounded connection/lock/statement timeouts. Do not add a second generic psql
error parser or alter ordinary readback driver selection. Missing Psycopg or
authority is categorical unavailable, never an installation request.

Builders derive accepted publication from PostgreSQL, validate exact retained
portable correspondence, and persist the FULL RunPublicationReceipt mapping.
Build/activation/query use the latest complete run and exact receipt semantics,
including a newer legacy run becoming stale. Direct mode does not depend on
graph_publication_authority. Every lexical response resolves its fence, hits
and optional canonical evidence within one read-only SQL snapshot.

Use owned generation identities, concurrency/lease fencing, bounded batch
transactions, verified counters, atomic activation and exact failure/orphan
cleanup. Revoke invalidates active and in-progress derived generations so an
old builder cannot resurrect body rows or authority. Index failure never blocks
canonical publication. Aggregate-budget overflow fails closed; per-file prefix
truncation and exclusions make query scope explicitly partial.

Backups contain body-derived material. Protected archive custody is an operator
obligation; the current backup manifest does not attest a separate classification.
Restore --no-owner/--no-privileges and core_v1 schema-set checks do not establish
lexical ACL readiness. Narrow restore finalization verifies existing owner
custody, reconciles existing role denials and purges restored lexical authority
and body rows; an explicit authorized rebuild is required. Canonical graph
restore remains unchanged. No live restore is authorized by this source phase.

### 2. PostgreSQL metadata navigation and location parity

Implement existing navigation_search and node_locations contracts under
readback_postgres_authority, querying public graph tables only. They never
reference cloe_lexical or require a generation. Preserve
[ADR 0078](0078-stored-node-source-locations.md) through
[ADR 0082](0082-navigation-source-admission.md): selected-run-before-role
resolution, ambiguity/history, safe relative locations, source admission before
node caps, byte/count limits and deterministic public-safe wire behavior.
Compile each request into one read-only statement/snapshot. This does not
promise a snapshot shared across separate MCP calls.

### 3. Source-bound evaluation v2 and future admission gate

Preserve full requested/effective mode, fallback, actual surface, exposure,
backend and failure state per slot. Partition summaries and criteria by actual
execution; body fallbacks do not qualify stored-metadata floors. Existing
attempt7, task/split/fixture inputs, history and raw evidence remain immutable.
A historical v2 projection is a separate analysis bound to original journal,
terminal, declaration/report and source/closure bytes, never a new execution.

Add postgres_native_fts using real maintained PG corpus publication and the
production lexical service. Predeclare one new calibration observation using
the existing declaration/admission/journal mechanism and exact candidate,
fixture, policy, runtime, task and stopping/replacement bindings before queries.
Retain failures; a corrected replacement needs a new source/attempt identity.
No held-out queries or held-out tuning occur in this milestone.

Implement future held-out admission on the existing declaration model, with
compatible v1 canonical serialization or an explicit version transition. Before
future held-out queries, verify actual accepted-criteria bytes, exact candidate
and fixture freeze, source qualification and separate manager authorization.
Three nonempty strings alone do not establish acceptance. Synthetic admission
tests may validate the gate without executing held-out questions.

Preserve the W2 omitted-selection default to a nonempty authorized policy
selection. Only an empty resolved scope becomes unavailable, never absence;
fix the benchmark adapter's empty-subset misclassification separately.

## Alternatives and limits

No SQLite FTS5 prerequisite, external BM25, pg_trgm installation/admission,
private/email/feed body expansion, MCP owner elevation, vector/fusion/JSONB,
Rust or new distribution/repository rename is included. Optional pg_trgm
inspection reports installation facts only; presence is not feature admission.

PostgreSQL concatenation offsets right-hand tsvector positions. Therefore
ranked field/alias sections must disclose their positional effect; phrase
vectors contain only native body positions. Identifier normalization does not
prove exact identity. Unicode and overlong-token behavior require actual native
DB proof, and ranking weights remain calibration hypotheses. See PostgreSQL's
[vector manipulation](https://www.postgresql.org/docs/16/textsearch-features.html)
and [ranking controls](https://www.postgresql.org/docs/16/textsearch-controls.html).

## Verification, admission and rollback

Use exact scoped unit and disposable-container integration selectors with
--no-coverage. All complete local suites remain unselected. Require actual
publication, ACL, fresh policy/revocation, failure/race, analyzer, CLI, parity,
restore and evaluator proofs. Hosted CI measures full coverage: target 87% for
unit statements/branches and 82% for integration statements/branches, retaining
all hard gates and exact numerator/denominator arithmetic.

New Python owners target 350 physical lines and stay <=400. Existing stronger
budgets hold; cohesive helpers avoid forced unrelated refactors. Admit new
clean modules by guarded forward-only ownership/selection/scope additions:
preserve every prior record, numerical debt/tool/length ceiling and authority
prefix. A candidate export is not enforcement acceptance. No baseline genesis,
suppression, debt reset or exclusion of new production code is allowed.

Migration discovery uses existing includeAll and actual Liquibase headers and
rollback. No changelog mirror or historical migration rewrite. Rollback removes
only the new owned schema/derived data; canonical graph authority is independent.
Live application/rollback requires ordinary operator runtime authority outside
this contribution task. The phase exit records exact selectors, outcomes and
remaining limitations; no successor inherits CI101 qualification.

## Resulting-state review clarification

Safe lexical query prefixes use exact-file-or-descendant segment matching, with
shared normalization before connection use; glob syntax is unsupported. Native
library paging matches CLI/spec100/1000 limits. Ordered result aggregation must
name its complete ordering keys. Restore reconciliation always forwards its
explicit purge flag; test-double signatures cannot alter production behavior.
Lifecycle fencing uses a namespaced BIGINT hash over the full repository ID,
shared by claim, batches, activation and revoke; collisions only serialize work.
For this milestone retain the conservative full-graph policy digest: unrelated
binding-policy changes may stale a generation. Selected-binding-only freshness
is not claimed. Corrected-source calibration has a new pre-query attempt ID and
paths; original successful observations and their actual source remain intact.
