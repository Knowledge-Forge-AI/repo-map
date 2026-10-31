# REPOMAP-CLOE-RETRIEVAL1 Exit: Retrieval contracts and evaluation milestone

Status: NOT ACCEPTED pending the exact successor hosted CI qualification.
Local scoped verification and independent source/grant review are required for
the frozen publication candidate. Complete populations and coverage belong to
hosted CI101 attempt1. W1's CI100 pass does not qualify this successor.

## Scope

[ADR0127](../../docs/adr/2026/10/0127-cloe-retrieval-contracts-and-evaluation.md)
implements W2 in three connected units: internal six-mode/capability contracts
and captured-input reference; a controlled mixed corpus with frozen 24/12 task
split; and real native, SQLite/PostgreSQL graph and projection evaluation arms.
Existing public CLI/MCP schemas and source-blind behavior remain unchanged.

The reference validates accepted-publication correspondence and the real streaming
publisher contract before reading bounded artifacts. Privacy/retention/format
exclusions precede body opens. It preserves source/evidence provenance, UTF-8,
chunk continuity, explicit omissions, generation fencing and bounded page retention.
Typed wire parsing rejects coercion and non-finite scores. This is an internal
in-memory reference, with no production index or generation-retention promise.

The developer instrument uses actual native git grep and maintained accepted
read stores. Execution never uses grading gold to manufacture hits or refusals.
Unsupported modes remain unavailable. A durable experiment root prevents ID
reuse and retains the declaration/source closure before queries and every
repetition afterward. Functional tests cannot qualify retained observations.

The SQLite test MCP transport now uses finite scratch-file stdin, bounded
streaming output drains and existing managed-child cleanup. This corrects the
pipe deadlock while preserving all navigation requests and measured child seams.

## Retained calibration observation

`calibration-attempt-7` completed 24 calibration tasks across five arms with
three repetitions: 360 query observations and 842 durable journal records.
The 26-file execution closure, frozen inputs, runtime and immutable predecessor
are bound before queries. Source/terminal/archive hashes and public artifact
hashes are in `mixed-v1/baseline/retained-attempt-7-evidence.json`.
No held-out retrieval occurred. Earlier drafts and the completed pre-wire-fix
attempt and the pre-validation-correction attempt remain retained against their
actual source, with public disposition
in `attempt-history-v1.json`; none were silently repinned.

| Arm | Whole | Supported | Graded | Unavailable | Body recall@5 | Metadata recall@5 | Graph recall@5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `native_tools_baseline` | 24 | 21 | 19 | 3 | 0.772727 | 0.5 | null |
| `current_graph_baseline:sqlite` | 24 | 12 | 10 | 12 | null | 1.0 | 1.0 |
| `current_graph_baseline:postgresql` | 24 | 8 | 6 | 16 | null | 1.0 | 1.0 |
| `captured_projection_reference:sqlite` | 24 | 18 | 16 | 6 | 0.772727 | 0.75 | null |
| `captured_projection_reference:postgresql` | 24 | 18 | 16 | 6 | 0.772727 | 0.75 | null |

These are observed calibration values, not acceptance floors or a pooled winner.
Null means no graded population. Safety refusals are separate from retrieval
grades. Timing is raw samples/medians, not cold-cache or per-task p95 evidence.
Setup body-input counts and query output layers remain separate; total validator
I/O is unobserved. Unknown model
tokens, source I/O and external task costs remain unavailable. The criteria
artifact is proposed for future W3 parent review, not held-out qualification.

## Verification

The final local report records exact command results for the frozen commit.
Scoped unit and real container integration use `tools/run_tests.py`, jobs1 and
`--no-coverage`. The exact selected owners are:

Unit (`--suite unit --no-coverage --jobs 1 --`):

    src/test/unit/python/repomap_kg/retrieval/query_contracts.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/projection_binding.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/projection_policy.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/projection_text.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/projection_chunks.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/projection_query.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/corpus.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_schema.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_catalog.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_grading.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_native.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_harness.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_criteria.unit.test.py
    src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py
    src/test/unit/python/repomap_kg/cli/sqlite_mcp_transport.unit.test.py
    src/test/unit/python/tools/ci/retained_python_projection.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/projection_paging.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_attempts.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_execution.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/query_wire.unit.test.py
    src/test/unit/python/tools/retrieval_evaluation_comparability.unit.test.py
    src/test/unit/python/repomap_kg/retrieval/projection_validation_required.unit.test.py
    src/test/unit/python/tools/ci/d12_system_grant.unit.test.py

Integration (`--suite int --no-coverage --jobs 1 --pg-container-port 55433 --`):

    src/test/int/python/repomap_kg/retrieval/projection_publication.int.test.py
    src/test/int/python/repomap_kg/retrieval/corpus_publication.int.test.py
    src/test/int/python/repomap_kg/retrieval/native_search_process.int.test.py
    src/test/int/python/repomap_kg/retrieval/evaluation_baselines.int.test.py
    src/test/int/python/repomap_kg/storage/sqlite_mcp_transport.int.test.py
    src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_system_hold_proof_capture_and_child_secure_writer
    src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_sandbox_dispatch_blocks_system_suite_without_valid_proof
    src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_cross_process_flock_and_o_excl_race_and_execute_system_run

Static enforcement uses `tools/ci/python_retention_inventory.py --check --json`.
Compilation, topology, file length, suppression policy, public export and
privacy checks supplement it. Clean ownership admission preserves all old
authority/selection rows and every numerical debt/tool ceiling. New Python
files remain within400 physical lines with no added allowance.

Complete local unit, integration, smoke, staging, system and combined suites,
and Python project coverage, remain intentionally unselected. No application
or SDK image was built, no dependency changed and no image was pulled locally.
The retained developer measurement is separate from ordinary test execution.
A surplus unchanged runtime-cleanup diagnostic materialized one managed test
runtime inside the disposable engine; host resource state returned to baseline.
It grants no application build or acceptance; final grant selectors use only
the three changed-contract cases and require zero materialization.

## Publication and deferrals

[ADR0128](../../docs/adr/2026/10/0128-retrieval-evaluation-milestone-staging-campaign.md)
binds one staging publication, CI101 attempt1 and one eighteenth native AMD
application start. Seventeen prior starts stay spent. No nineteenth start,
automatic retry, main promotion or tag is granted.

W3 persistent/native text indexing and held-out evaluation, W4 context policy,
W5 vectors/fusion, W6 Rust, live deployment and package publication remain
separate roadmap work. Local source/contract evidence does not qualify the new
whole candidate; public CI results remain necessary.

## Resulting-state review correction

Independent review identified a bypass when references/spool storage were absent.
The corrected product refuses those inputs, verifies stored manifest bytes and
requires matching streaming-validator identities. A digest-valid tampered bundle
is rejected by the actual validator. Positive unit fixtures and real backend
queries now prove the maintained `canonical_key`/`raw_kind` provenance join.
Comparator exposure populations and body floors remain separate; the seed-heavy
graph observations define no general graph-quality floor. MCP responses are
checked for privacy canaries, and freeze/criteria outputs cannot overwrite files.

The earlier read-only audit's producer narrative contained invented symbols and
was rejected as authority. Its independent blocker review was valid; its fenced
terminal failed dispatcher validation. Source/index preservation and process
cleanup were proven. Fresh corrected-source review is required before publication.
The unused eighteenth reservation is rebound with retained history and explicit
old-identifier refusals, allocating zero additional application starts.

## Requested mode and metadata surface correction

The captured-reference evaluation adapter preserves each task's requested mode.
When that mode differs from the executed literal-text scan, it records an explicit
caller-selected fallback with both modes and the reason. Ranked navigation-search
hits declare a stored-metadata surface. Unit regressions and the real calibration
integration journal enforce those disclosures. Attempts5/6 remain retained at their
actual source; attempt7 binds the corrected execution bytes without repinning them.
The underlying query accepts an explicit fallback to literal_captured_text, keeps
its original requested mode, and rejects unsupported fallback targets before
execution. Backend tests and unit regressions cover that same direct contract.

The benchmark supplies current accepted-publication readback on every query.
The internal direct projection API's optional omitted readback establishes no
advancement check; callers must supply it for that guarantee. Correspondence
verifies top-level references and stored manifest bytes. Individual projected
body blobs are verified by bounded store reads; missing blobs are explicit
partial/excluded outcomes, not a claim that every manifest entry was preverified.
