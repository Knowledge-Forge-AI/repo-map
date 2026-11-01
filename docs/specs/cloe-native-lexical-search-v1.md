# CLOE native lexical search specification v1

Status: Accepted for REPOMAP-CLOE-LEXICAL1, with implementation gated on
independent plan review. [ADR 0129](../adr/2026/10/0129-postgresql-native-lexical-search-and-publication-pinning.md)
owns the architecture, scope and authority. All new names below are proposed
implementation seams, not assertions that an API already exists.

## Milestone and ownership

Deliver three units together: core PG lexical CLI/lifecycle; PG metadata
navigation/location parity; truthful evaluation v2 plus a new predeclared
calibration observation. Implement future held-out admission but execute zero
held-out questions. One later manager-owned public staging checkpoint follows
source proof. No image build/publication is allocated by this spec.

Use cohesive new owners in retrieval/lexical_*, storage/lexical_*,
ops/lexical_*, cli/_parser_ops_lexical.py and cli/ops_lexical_commands.py;
metadata parity belongs in storage/postgres_navigation_* and
storage/postgres_node_locations.py with a small server dispatch helper.
New runtime/_lexical_restore* helpers integrate narrowly with existing restore
completion paths. Extend retrieval_evaluation* tools and maintained test-support
owners for evaluation. Keep query_contracts.py unchanged. Existing ordinary
readback_driver.py, SQLite investigation and SQLite CLI routing need no changes
merely to support a new lexical method.

Python files stay <=400 physical lines, new owners target 350. Keep existing
near-limit owners within their actual current budgets through small cohesive
delegation, not arbitrary forced shrinking. Tests use maintained repomap_kg
physical roots, matching the actual storage/ops/CLI/runtime owner boundary.

## Policy and trust

Build/query require authorize_body=True and nonempty selected binding IDs.
Resolve graph through maintained ops config/home mechanisms without imposing
MCP visibility. Reload actual disk config at each request. A cached config is
only a locator for reloading, not current policy authority. Reload/config
resolution failures refuse before body matching. Revoke remains available after
private reclassification and does not need body authorization.

P1 admits only resolved public-dev graph/binding policy, full-authorized retention
and supported code/prose. Keep actual artifact PUBLIC|RAW_SOURCE classification.
At build time apply config checks AND existing ManifestBinding/artifact checks,
retained portable validation, strict UTF-8/NUL handling and pre-open exclusions.
Do not infer classification from a filename or silently change source policy.
Email/feed, inherit/private, metadata-only/ephemeral and unsupported bodies are
excluded before opening. Query performs config-only P1 validation, with no source
root or portable artifact-store access.

Define one canonical cloe-lexical-policy-v1 fingerprint used by build/query.
Frame graph identity, resolved per-binding policy labels, admitted selection,
limits, analyzer and representation versions deterministically. Store admitted
binding IDs and per-binding policy digests as well as the generation fingerprint.
Queries may select a nonempty SUBSET of the admitted set; fresh live policy must
still validate EVERY binding admitted to the generation. Edits/removal affecting
an admitted binding invalidate the generation; unrelated excluded bindings do
not silently become indexed. Preserve graph-level privacy/inheritance changes.
Current-code analyzer/representation/budget policy must be compatible with the
stored generation. Never compare a subset-derived W2 reference digest to a
larger production generation or trust a caller-supplied digest.

Admitted in-flight requests finish under their fresh policy snapshot and SQL
statement snapshot. Subsequent requests observe new config and DB revocation.
No claim of immediate retroactive cancellation is made. Activation also checks
fresh policy; a stale builder cannot restore revoked authority.

## Derived schema, lifecycle and transport

One forward rdbms SQL migration creates dedicated cloe_lexical schema and owned
generation, authority, document and chunk records. Use actual Liquibase formatted
SQL/changeset/rollback headers; existing includeAll discovers it. Do not rewrite
historical SQL or add a Python registration mirror.

Required integrity:

- Repository/run/generation/receipt/policy/analyzer identity cannot be mixed
  across authority or documents/chunks. Persist FULL RunPublicationReceipt
  mapping and validate it, not a guessed subset or fictional column list.
- Authority references only a ready generation of the same repository, run and
  policy. Choose transaction/FK ordering or deferred integrity deliberately so
  superseding an existing authority does not violate its ready-state reference.
- Documents are unique by generation/binding/safe relative path. Chunks tie to
  that document AND generation and have stable sequence, source/representation
  digests, byte/line extents, classification and policy provenance.
- Empty-file records preserve existing 0/0 line extents; nonempty chunks have
  positive ordered line extents. Chunk text <=8,192 UTF-8 bytes, file projected
  prefix <=262,144 bytes, with existing 80-line chunk policy and valid UTF-8 cutoff.
- Store exclusions/omissions and truncation explicitly; vectors/identifiers and
  normalized text are body-sensitive. No public-schema body copy or sanitized
  backup claim. The graph is the authority, never a derived index.

The initial production build ceiling is 65,536 files / 256 MiB aggregate captured
input, bounded per-file normalization, bounded SQL batches and bounded worker
time. Aggregate overflow fails the generation without activating partial rows.
No silent fallback to W2's 4,096-file / 8 MiB reference cap. Retained per-file prefixes
and excluded files make the queried scope incomplete. Counts/bytes are verified
before activation; source read and projected byte accounting remain distinct.

Use existing configured DB-owner credentials only, through a NEW dedicated
lexical driver built on already installed Psycopg 3. No psql compatibility promise,
new dependency, role, password source or hidden fallback. Lazy import preserves
SQLite startup isolation. Transactions, credential handling and connection
lifetime are explicit. Connect timeout <=5s, lock timeout <=500ms and query statement
timeout <=2,000ms (respect a stricter existing bound); bounded population batches
may use a separately declared capped build timeout. Queries are read-only.
Sanitize all database diagnostics to categorical public-safe reasons.

Map missing driver/authority, absent schema/table, SQLSTATE42501 permission denial,
57014 statement cancellation and55P03 lock timeout to categorical unavailable or
partial with incomplete scope, never absence or installation. Probe pg_catalog
using OIDs/null guards where useful; to_regclass on an inaccessible schema can
raise, so it is not a substitute for actual driver error handling. Do not expose
raw SQL, DSNs, credential values, filesystem paths or source bodies in errors.

Claim a per-repository derived build slot using owned locking/generation identity;
reject an unexpired competing build. Populate in bounded transactions with lease
refresh and owner/status checks on EVERY batch. Validate, then activate atomically
after accepted-publication and fresh-policy checks. Reap only expired owned
derived generations, under the same lifecycle lock. Failure rollback/purge and
cleanup are separate bounded transactions if a transaction is already aborted.
Revoke invalidates building/validated/ready authority and purges body rows; every
later batch/activation from an old builder must fail. Test failure, expiration,
concurrency, revoke and newer-publication races. Canonical publication must not
need or wait for derived indexing.

Migration revokes PUBLIC. Existing runtime role reconciliation handles named
read-status/refresh-publication/control roles when present, denying schema,
table/sequence and default privileges. Do not blindly seize a preexisting foreign
schema. Use the maintained existing DB-owner authority/custody checks. Limited
graph readers remain useful while body access is denied. Real connection tests
must prove the boundary, not just inspect generated REVOKE strings.

Backups automatically include body-derived schema data and require protected
operator custody. Current manifest schema does not encode a new classification
attestation. After disposable restore --no-owner/--no-privileges, narrow restore
finalization verifies owner custody, reconciles denials, invalidates/purges restored
lexical authority/body rows and requires explicit rebuild. Test actual limited-role
denial plus ordinary canonical graph usefulness after maintained dump/restore.
No live restore or general backup-policy change belongs to this source task.

## Publication fence and query semantics

Builder acceptance comes from actual maintained PostgreSQL readback and validated
retained portable correspondence. Direct and coordinator modes both work.
Do not use graph_publication_authority as the sole accepted-run fence.

Lexical query compiles a single statement joining latest complete run, active
ready generation and all stored receipt fields with semantics equivalent to
build_receipt_predicate_sql. It does not need a caller receipt. A newer complete
legacy run, changed receipt, missing authority, incompatible policy or revoked
generation returns stale/unavailable with no hits. Any canonical enrichment
joins the same accepted run inside THAT statement. Separate SQL calls do not
share an asserted transaction or snapshot.

Query styles:

- ranked_terms: ranked_discovery/captured_text using pg_catalog.simple native
  FTS plus explicit compatible identifier aliases. Stable top-chunk/document
  aggregation and deterministic locator tie-breaking. Initial pg_ts_rank_cd_v1
  weights/bonuses are a declared calibration hypothesis, not BM25/probability.
- normalized_phrase: ranked_discovery/captured_text using native body-only
  phrase positions. Aliases/metadata cannot manufacture phrase adjacency. This
  does not prove literal punctuation/byte matching or a cross-chunk phrase.
- literal_captured_text: literal_captured_text/captured_text, true substring
  matching over bounded stored LF text, every bounded occurrence, including
  adjacent-chunk boundaries within one file. Never join files. Use existing
  deterministic-locator-v1 ordering and exact original line extents.

Do not expand QueryMode/MatchSurface or mutate old QueryHit. Keep original bytes
for true identity and label case/Unicode aliases as normalization. Native vector
concatenation offsets RHS positions; disclose field-section effects rather than
claiming source-token positional alignment. Query syntax/SQL injection cannot
come from user operators/quotes/backslashes. Normalization never changes the
literal body/line representation. Native DB tests cover short names, Unicode,
mixed case, compounds/paths, punctuation/operators, very long tokens, weighted
fields, repeated quotations and chunk/file boundaries. Disclose actual dropped
or overlong-token limitations; do not promise all Unicode survives the parser.

Limits are real: <=5,000 matching candidate chunks / 1,000 candidate documents for
ranked styles; literal scan <=4,096 scoped documents / 16 MiB projected text before
aggregation, and bounded occurrences. Fail closed deterministically on overflow,
not arbitrary LIMIT windows. Statement timeout bounds actual database work;
GIN bitmap work is not bounded merely by a result LIMIT. Any truncation,
exclusion, overflow, timeout or incomplete evidence sets scope_complete=False.
Applicable omission records survive all styles, even if useful hits are returned.
Ranked discovery never establishes exhaustive absence.

## CLI records

NEW parser/dispatch owners follow actual add_ops_graph_commands and existing
ops dispatch conventions. Check declared backend up front for clean SQLite
unavailable; do not invent an existing _POSTGRES_ONLY_OPS_COMMANDS constant.
No MCP visibility requirement and no lexical method in InvestigationReadStore.

Common maintained --repo-map-home/--config and --graph resolution applies.
`lexical-build` requires --authorize-body, repeatable nonempty --binding and
--portable-store-root. Maintenance_activity_for_home takes its actual existing
one-argument form when used. `lexical-query` requires --query and body/selection
authorization, supports --style ranked_terms|normalized_phrase|literal_captured_text,
optional safe --path-prefix, --limit 1..100 (default 20), --offset 0..1000 (default 0).
It does not accept a caller policy digest. `lexical-revoke` takes --dry-run|--yes
and --graph, and can purge after policy reclassification without body authorization.

Closed JSON wrapper schema cloe-ops-lexical-v1 has common fields:
schema_version, command, status, reason. Define and validate exact per-command
fields before returning them:

- build: graph_id, generation_id|null, accepted_run_id|null, document_count,
  chunk_count, projected_body_bytes, omission_count, truncated_document_count;
  ready/refused/unavailable/failed status, sanitized reason, no body payload.
- query: graph_id, query_style, envelope (unchanged QueryEnvelope.to_dict()).
  Locator-only hits suffice; no optional snippets are required in this milestone.
- revoke: graph_id, dry_run, generations_invalidated, documents_purged,
  chunks_purged, authority_removed. Dry run reports bounded counts without mutation.

Actual serialized UTF-8 output <=65,536 bytes including wrapper/envelope. If it
would overflow, return a bounded partial envelope with no hits and explicit
output_budget_exceeded; never silently slice serialized JSON. Successful ready,
available, revoked or dry_run exits 0; incomplete/refused/stale/unavailable/failed
and validation errors exit 1 so scripts cannot mistake partial success for complete
success. Empty resolved selection is unavailable and cannot establish absence.

## PostgreSQL metadata parity

node_locations/navigation_search use existing readback_postgres_authority and
public tables only, with one self-contained statement per request. Preserve
the SQLite contracts and ADR 0078–0082, including location_run_id selected across
all linked evidence BEFORE evidence-role filtering, current/historical windows,
ambiguity/withheld alternatives, corroborated binding revisions, safe relative
paths and private markers. Source admission precedes NODE_SCAN_LIMIT 2,000; preserve
EVIDENCE_SCAN_LIMIT 10,000, ADMISSION_CHECK_LIMIT 100,000 and 32 MiB admission bytes.
Bound results and retained metadata without relying on arbitrary SQL row windows.
No lexical generation or owner privilege is needed for ordinary parity.

## Evaluation and future held-out admission

Version new summaries/criteria explicitly. Per-slot records retain requested_mode,
effective_mode, full fallback (from/to/reason_code/caller_selected), actual surface,
query style, exposure/backend, execution/capability/refusal/unavailable/failure
state. Aggregate actual effective populations separately from task intent and
exclude body fallback from stored-metadata qualification floors. Preserve failed
and ungraded denominators and actual byte/timing accounting; unknown cost stays
unknown. Three samples do not establish per-task p95 or cold OS-cache evidence.

Historical attempt7 re-projection validates exact retained evidence, journal,
terminal, public declaration/report and source/closure/input byte bindings.
Emit a separate historical_journal_reprojection object, never repin old evidence
or label it a new execution. Old mixed-v1 task/catalog/split/gold/source fixture,
attempt7/history/baseline bytes remain immutable. New W3 artifacts use a separate
baseline/w3 directory and new attempt identity.

Use maintained real PG corpus publication and the production lexical builder/
query service for postgres_native_fts. Its exposure and fallback must be truthful
for every task, with no metadata credit from a body route. Keep native-tool and
existing current-graph/reference arms identifiable. Before the first retained
query, admit exact source/fixture/policy/runtime closure, ordered calibration IDs,
arms/repetitions, stopping and replacement policy using existing journal seams.
Parent verifies the declaration before launch. Functional checks remain separate.
Retain every failed attempt; replace only after an instrument correction and new
source/attempt identity. Freeze observations; manager separately accepts criteria.

Future held-out admission extends existing AttemptDeclaration/FreezeManifest,
not a parallel freeze system. Preserve old v1 canonical serialization when absent
fields would otherwise change its digest, or use an explicit new declaration
version with backward-compatible reading. Validate actual proposal bytes and
SHA256, accepted source qualification and manager authorization references,
candidate/source closure, fixture/catalog/freeze identity and correct held-out
task IDs/count BEFORE any query. Reject mismatches/missing proof, not merely empty
strings. This milestone executes ZERO held-out queries, including tests.

## Proof and closeout

Require scoped --no-coverage unit and real disposable PostgreSQL integration
owners for lifecycle/receipt/policy/ACL, analyzer/injection/timeouts/overflow,
CLI JSON/exit bounds, restore, metadata parity and evaluation integrity. Use
maintained accepted publications, not manual canonical rows described as a product
publisher. Schema-level relational-corruption tests may use explicit isolated
SQL fixtures where their narrower purpose is stated.

Exercise useful W2 projection exclusions, empty scope, lost authority, UTF-8,
aggregate limits and default-selection regressions through actual publication.
Hosted coverage targets are 87% unit and 82% integration statements/branches;
for integration branches require 100 * covered >= 82 * total on actual successor counts.
No complete local suites or project coverage. Preserve every static debt ceiling;
only guarded clean forward module/ownership/scope additions are allowed.

The phase exit records exact selectors/results, actual calibration and historical
analysis bindings, independent findings/dispositions, cleanup and limitations.
Live deployment, image acceptance, held-out qualification and successor hosted
results are never inferred from scoped local proof or CI101.
