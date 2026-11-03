# CLOE W5 model-independent foundations v1

Status: accepted for REPOMAP-CLOE-SEMANTIC-FOUNDATION1 under ADR0137.
The operator approved the bounded BGE/ONNX path under ADR0136; full W5 proof remains open.

## Owners and inputs

Extend evaluator-owned tools and their exact unit/integration test seams. Reuse
existing publication, task, locator, grading, SQL and fixture owners. Do not
change QueryEnvelope, existing modes, catalog labels or historical graders.
The new report namespace is cloe-w5-foundation-v1; subresults identify their
representation/fusion/JSONB policy versions. These are evaluator artifacts.

Use validated immutable structured inputs with explicit bounds. Model payloads,
large arbitrary JSON, executable plugins, arbitrary SQL/executables and implicit
host/config/environment discovery are outside the contract. Public fixtures
retain their declared privacy; the mailbox binding stays a refusal case even
though its bytes are in Git. No held-out task is selected or executed.

## Representation and provenance

Canonical-node-v1 is exactly:

```python
json.dumps(
    {"canonical_key": key, "kind": kind, "display_name": name},
    sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
).encode("utf-8")
```

Require actual strings, encodable Unicode, existing identity/public-output
bounds and at most 500 node/source entries. Return sha256-prefixed digest.
Validate against actual accepted node fields and accepted publication/source
identity, not another imported claim. Different key/kind/name/Unicode bytes must
change the digest or refuse; null, lone surrogates, booleans and malformed
identity fields cannot be coerced into acceptance.

A provenance adapter reads back and normalizes the real accepted publication,
requiring complete pin and snapshot vector, and checks the paired portable
receipt. Require graph/repository/backend, publication/run/generation/bundle/
job/attempt/manifest/receipt identities and the exact selected binding snapshots.
Reuse normalize_accepted_publication(require_pin=True, require_vector=True)
and existing correspondence checks where appropriate; matches_current alone
omits required optional identities. Copy/freeze input mappings before validation.

Select eligible public-binding evidence only. Exclude private-only, withheld or
unverifiable mixed-provenance node representations. A denied-binding query
refuses before candidate access. Do not introduce a caller-trusted=True escape.
Representation validation has no model/network/install/inference side effect.

## File-level fusion and grading

Each observation pairs its actual envelope/evidence with a verified current
publication pin. Current graph/lexical envelopes omit some publication fields;
fill those only through independent read-back correspondence, never caller
assertions. Mismatched graph/backend/repository/publication/snapshot/generation,
unauthorized or unknown binding, malformed evidence, stale receipt and duplicate
arm IDs refuse the entire requested fusion without leaking other-arm hits.

Preserve per-arm execution/capability/refusal/failure/incomplete state. Privacy
refusal takes precedence over unavailability. Missing/unexecuted arms cannot be
credited as successful fused execution or silently replaced. Explicit fallback,
if supported, is a separately disclosed result and does not count as the missing
arm. Keep unsupported and truncated cells visible, with deterministic bounded
reasons and work/output accounting. Output caps do not bound underlying work.

Map vector evidence from verified metadata binding_id/snapshot_id/
source_relative_path; do not split graph-qualified display paths. Lexical
snapshots come from the admitted generation vector. Enumerate evidence within
a declared bound and report truncation rather than silently losing files.
Collapse each arm by the full tuple, retaining best raw rank and bounded support
IDs. Order by best raw rank then tuple UTF-8 bytes, assign ordinal ranks, and
sum exact Fraction(1, 60 + rank) contributions, one per arm. Sort score descending
then tuple bytes. Serialize an explicit score/rank policy without depending on
floating-point near-ties.

The new grading helper asserts each file snapshot equals the task's accepted
binding snapshot before projecting to the gold locator's binding/path identity.
Collapse duplicate/span-level gold targets with unchanged maximum gain per file;
deduplicate returned files before computing file-level metrics and recall
denominators. Preserve the existing node/span grader and frozen labels. Reject
held-out tasks at this execution boundary. Predeclare task mode/stratum/surface
applicability; metadata vectors are not a captured-body comparator. Use a separate
receipt-bound rebuild per fixture generation; no old observation is repinned.

## JSONB named-workload experiment

Use the actual node-evidence expansion owner and identical request shape,
including canonical key, evidence role, repository identity, accepted publication,
current/historical windows, strict context identity where selected, transport
caps and deterministic evidence ordering. Compare normalized complete rows and
identity/refusal/overflow behavior before measuring alternatives. Malformed or
missing metadata cannot be converted into an invented binding/snapshot.

Any projection must be built over the same admitted eligible fixture population
before named queries, not only the already computed requested answer. Charge
preparation, construction, refresh and index costs; preserve the baseline's
live-publication correspondence so an advanced publication invalidates the
projection. Use fixed parameterized SQL/identifier owners and the existing
disposable test executor; no general connection/SQL CLI or live-host fallback.

Freeze binding_id/snapshot_id containment and any source_relative_path equality,
selected keys, repetitions and warm/cold description before execution. Use only
existing public fixture publications and their actual selectivity variation.
A plan may choose a sequential scan; report the actual index use rather than
asserting GIN acceleration. Retain EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON),
rows, buffers, timings, footprint, build/update cost, equality, failures and
cleanup. No final latency claim or schema adoption follows from tiny fixtures.
The disposition may retain the relational path and no additional index.

## Proof and exit

New exact unit owners cover representation/Unicode/type/digest negatives,
immutable publication/provenance and denied-binding behavior, rank/dedup/ties,
unavailable/refused/failed/incomplete propagation, stale/generation mismatch,
file-level grade denominators and JSONB report accounting. New exact canonical
containerized integration owners use actual accepted fixture publications to
prove representation/read-back identity, fusion boundary and named JSONB
row-set/plan/cleanup behavior. Unit fake SQL is not a runtime equality proof.

Record exact selectors and real outcomes with --no-coverage. No complete local
suite, project coverage or application/SDK/optional-image build is authorized.
Preserve the cached SDK, runner policy and all source/debt/coverage denominators.
Bind source and fixtures before experiment queries and retain failed attempts.
Model execution requires the separate accepted ADR0136 artifact and target gates.

Independent review and parent resulting-state proof precede any local checkpoint.
A local foundation checkpoint does not close full W5 or justify an intermediate
public-CI campaign contrary to the operator's substantial-milestone preference.

## Implementation and proof notes (REPOMAP-CLOE-SEMANTIC-FOUNDATION1)

- Evaluator foundation owners implemented under `tools/` (within the 400-line policy):
  - `tools/retrieval_semantic_primitives.py`, `tools/retrieval_semantic_provenance.py`, and `tools/retrieval_semantic_representation.py`: `canonical-node-v1` compact UTF-8 JSON encoding, SHA-256 digest computation, `verify_publication_provenance` / `verify_publication_provenance_from_adapter` (`normalize_accepted_publication(require_pin=True, require_vector=True)`, mandatory live `readback_adapter` cross-verification, `VerifiedPublicationPin.revalidate_current()` live store revalidation, trusted in-process store-adapter construction boundary (not a cryptographic authenticity mechanism), full portable receipt correspondence across `graph_candidate_id` / `generations` / `snapshot_vector`, early policy/scope refusal before candidate access), and `validate_canonical_node_representations` (`<= 500` record bound, independent node/evidence validation, and claimed `EmbeddingEntry` batch verification).
  - `tools/retrieval_semantic_arm_validation.py` and `tools/retrieval_semantic_fusion.py`: `FileIdentityTuple` `(binding_id, snapshot_id, source_relative_path)` validation, per-arm file collapsing (`collapse_arm_to_files`), live store and cross-arm provenance/generation pin enforcement (including complete `observed_accepted_publication` and `QueryEnvelope` scope/provenance checks), refusal precedence over unavailability, `ExecutionState.NOT_RUN` and incomplete/truncated arm propagation, explicit fallback disclosure, and exact `Fraction(1, 60 + rank)` file-level RRF (`fuse_arm_observations_rrf`).
  - `tools/retrieval_semantic_file_projection.py` and `tools/retrieval_semantic_grading.py`: calibration-split-only enforcement (`assert_calibration_split_only`), predeclared arm/stratum/surface applicability (`evaluate_arm_task_applicability`), max-gain file-level gold collapsing (`collapse_gold_targets_to_files`), snapshot-verified file and span-locator projection (`verify_and_project_returned_files`), and dual span/file grading (`compute_file_level_ranking_metrics`, `grade_w5_task_slot`) with fusion-derived state enforcement and incomplete-coverage partial-grade capping.
  - `tools/retrieval_jsonb_contracts.py`, `tools/retrieval_jsonb_sql.py`, `tools/retrieval_jsonb_metrics.py`, and `tools/retrieval_jsonb_evidence.py`: disposable PostgreSQL `repomap_w5_jsonb_exp` population-wide JSONB projection, live-publication correspondence invalidation (including `graph_candidate_id`, `generations`, `snapshot_vector`, and `evidence_fingerprint` over `public.canonical_evidence`), strict equality-first gating across `relational_baseline`, `jsonb_no_index`, `jsonb_gin_ops`, and `jsonb_gin_path_ops` before any `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` execution, inclusive root-buffer/plan/index summary extraction, measured disposition derivation, and guaranteed `RESTRICT` cleanup (`run_jsonb_evidence_experiment`).
- Cohesive test support and exact test selectors:
  - Support: `src/test/support/python/repomap_test_support/w5_semantic_store_support.py`, `src/test/support/python/repomap_test_support/w5_semantic_support.py`, `src/test/support/python/repomap_test_support/w5_jsonb_support.py`.
  - Unit selectors: `src/test/unit/python/tools/retrieval_semantic_representation.unit.test.py`, `src/test/unit/python/tools/retrieval_semantic_fusion.unit.test.py`, `src/test/unit/python/tools/retrieval_semantic_grading.unit.test.py`, `src/test/unit/python/tools/retrieval_jsonb_evidence.unit.test.py`.
  - Containerized integration selectors: `src/test/int/python/repomap_kg/retrieval/semantic_foundations.int.test.py`, `src/test/int/python/repomap_kg/retrieval/jsonb_evidence_workload.int.test.py`.
- While the operator has separately approved exact BGE/ONNX route A, this foundation slice remains strictly within model-independent semantic/hybrid/grading foundations and JSONB evidence without executing model installation/inference or claiming full W5 completion.

The generator/lexical positive integration scenario declares only the existing
public core, companion and feeds bindings in an invocation-owned home. The
original mixed graph retains its private mailbox and is refused as a whole by
model admission. No graph privacy override, source relabelling, fixture text or
task/gold edit is used. Public representations retain mailbox task refusals;
the private binding is absent from the positive publication snapshot vector.
PG EXPLAIN JSON has its own bounded 64-level/20,000-item/2-MiB freezer because
executor Plans arrays exceed shallow publication JSON depth. Publication and
representation limits remain unchanged; oversized or cyclic plans refuse.
