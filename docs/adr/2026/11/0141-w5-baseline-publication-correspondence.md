# ADR 0141: W5 baseline publication correspondence

## Status

Accepted bounded technical continuation of REPOMAP-CLOE-SEMANTIC1 under the
operator's 2026-11-03 roadmap instruction. Independent design review found no
reserved operator decision and required the generation/readback corrections
below. The parent accepts that corrected design before implementation.
ADR0136/0137 authority and their reserved operator decisions remain unchanged.

## Context

CI109 attempt 1 qualified staging e012f0180b7e2b85112e46a361fc4cd7fcd66472:
all nine jobs, same-attempt staging measured/abrupt obligations and five system
scenarios passed, with verified terminal cleanup. Full W5 remains open.

Retained calibration has 369 generation-1 and 15 generation-2 baseline file
grading gaps. Native filesystem and captured-reference envelopes describe their
actual backends; graph envelopes omit full publication scope. The strict W5
validator correctly refuses those envelopes as PostgreSQL publication evidence.
Passing one PostgreSQL pin to every arm cannot establish correspondence.
Refused/unavailable FTS cells also appear among these gaps; they must retain
their actual capability/reason rather than receive invented file credit.

Generation-2 evaluation also used intentionally historical PostgreSQL MCP
observation search for a current-publication task, returning a deleted file.
The shared historical-search contract must remain unchanged.

## Decision

Add a versioned evaluator-only baseline-correspondence sidecar. Preserve raw
QueryEnvelope/backend/mode/surface/fallback/omission observations. The sidecar
certifies independently verified correspondence, never relabels an execution.

Database arms use their own backend-specific accepted publication, complete
portable receipt and snapshot-vector readback, validated before and after
execution. Native, SQLite graph and SQLite projection use the SQLite pin;
PostgreSQL graph, FTS and projection use the PostgreSQL pin. Distinct backend
bundle IDs are not forced equal. Cross-backend comparison requires an
explicitly witnessed common snapshot vector, otherwise a visible gap.

Both backends' current metadata enumeration and graph-investigation observation
lookups use evaluator-owned fixed queries fenced by accepted run/repository
identity. The accepted marker and matched repository, not the database's latest
complete run or a trusted-caller flag, determine the PostgreSQL readback.
Reuse postgres_accepted_run_cte_sql(context_identity=True) and its existing
complete identity checks. Raw observations are freshly materialized per run;
unchanged bindings remain visible in the new accepted run. Canonical navigation
historical fallback is a different contract and remains unchanged.

The generic reader owns a dependency-neutral expected-pin protocol and typed
read refusal. Its identity always comes from actual store readback. W5's issued
capture and strict correspondence verifier retain concrete authenticated pins;
the protocol cannot issue sidecar verification or grading credit. Keep generic
evaluation tools independent of the semantic experiment layer.

Fixture/task generation and backend publication generation are distinct
concepts. The controlled two-generation experiment refreshes one SQLite home
in place, as PostgreSQL already does, and verifies the expected correspondence
before grading. Do not coerce task labels or weaken generation equality/null
guards. Populate PostgreSQL ProjectionInputs generation from independent
accepted-run readback; missing generation is a refusal, not a wildcard.

Native arms bind actual materialized public bytes and manifest to the accepted
SQLite publication, source capture and selected snapshots. The existing native
view has no such witness fields: emit or independently recompute a versioned
materialization witness. Recompute rendered metadata bytes from the accepted
manifest/bundle/store/policy; their hashes need not equal raw artifact hashes.
Captured-reference
arms validate ProjectionInputs and full correspondence to the underlying
backend. Unsupported correspondence remains an explicit gap. Paths, task/gold
data, repository-name strings, caller mappings, dataclass types and boolean
trust flags cannot establish identity.

Record observed arm/backend, correspondence kind, independently verified
publication/source/input/manifest identities, selected binding snapshots and
pre/post validation outcomes. File grading consumes a sidecar only after
revalidating the actual readback/materialization boundary. Preserve the strict
envelope-only validator for callers without a sidecar. Stale, foreign,
incomplete, forged, private or malformed inputs refuse before credit; no
other-arm hits may escape through a refused fusion.

Use a new evaluator-owned result version for correspondence/grading fields.
Historical artifacts and node/span graders remain unchanged. File identity
stays binding/snapshot/source-relative-path, with existing maximum-gain gold
projection and exact rational fusion.

Separate raw process output, decoded candidates, serialized envelope bytes
and underlying work. Keep the native process bound and disclose its exposure.
The proposed 65,536-byte scientific criterion remains unaccepted: do not
silently adopt it, hide large native output, change queries or tune populations.

## Proof and acceptance

Exact scoped unit and canonical containerized core integration owners use
--no-coverage. Prove independent SQLite/PG pins, byte/materialization drift,
stale/foreign publications, privacy refusals, forged sidecars, backend/mode
preservation, absent artifacts, pre/post publication advance, and
complete/partial/unavailable/refused grading. Prove deleted historical PG rows
are excluded and current matches remain visible. Keep historical-search
differential coverage unchanged.

The connected batch covers correspondence, current-generation comparison and
related publication/privacy boundaries. Aim for the operator's substantial
10k–100k LOC batch without filler. All new/decomposed Python owners must meet
the existing 400-line profile; no debt or coverage ceiling is relaxed.

After source review, a separately predeclared fresh public calibration may use
ADR0136's conditional exact artifact/runtime route and ADR0077's disposable
pgvector profile. Preserve the same 648-cell population, archive-before-query
rule, raw journals, unsupported generation-2 vector query, failed attempts and
single-owner cleanup accounting. Never repin old evidence.

## Boundaries and rollback

No product QueryEnvelope/CLI/MCP vocabulary, canonical schema, production index,
core dependency/lockfile, runner policy, workflow, threshold or denominator
change. No local complete suite, Python coverage, application/SDK build, live
DB, private input, new corpus/labels, body embedding, model substitution,
held-out execution or accepted scientific criteria.

CI109 spent start 25. This ADR grants no start 26 or publication. The parent
owns exact-candidate review/report/campaign binding. Full W5 and main promotion
remain separate. Rollback removes only evaluator changes and invocation-owned
disposable outputs, preserving history, canonical publication and shared search.
