# CI130 Coverage Remediation and CI131 Publication Exit

Phase: `REPOMAP-CLOE-CI130REPAIR1`.

CI130 executed and failed only the integration branch floor: 19,623/24,570
(79.8657%), 33 branches below 80%. All 2,300 measured integration cases and
17,243 unit cases passed. Eight other jobs passed; the staging manager report
names only `M: coverage floors not met`. Component successes remain separate
from whole-candidate qualification.

This test-only repair adds actual filesystem destination admission, report-write
and cleanup faults after real publications, fallback source-sealing custody,
rehashed retained-artifact/record refusal, durable backup conflict, real SQLite
publication correspondence and pure bounded PostgreSQL executor contracts.
The Server fixture now proves private namespace modes under umasks 022 and 002.
No product behavior, runtime payload, dependency, schema, workflow trigger,
measurement boundary, coverage denominator, exclusion or debt ceiling changes.

## Scoped verification

Feature proof passed 71 unit cases and 44 containerized integration cases,
using `tools/run_tests.py --suite unit|int --no-coverage --jobs 1 -- <selectors>`.
Exact unit selectors:

- `src/test/unit/python/repomap_kg/ops/sqlite_local_retention_layout.unit.test.py`
- `src/test/unit/python/repomap_kg/storage/postgres_context_expansion.unit.test.py`
- `src/test/unit/python/repomap_kg/retrieval/context_identity.unit.test.py`

Exact integration selectors:

- `src/test/int/python/repomap_kg/ops/resource_report_local_cli.int.test.py::test_destination_admission_refuses_real_unsafe_paths_before_any_refresh`
- `src/test/int/python/repomap_kg/ops/resource_report_fault_custody.int.test.py::test_destination_parent_change_after_publication_preserves_both_directories`
- `src/test/int/python/repomap_kg/artifacts/source_sealer_admission.int.test.py::test_fallback_source_open_uses_real_identity_checks_and_preserves_store_custody`
- `src/test/int/python/repomap_kg/ops/resource_report_fault_custody.int.test.py::test_owned_report_write_and_cleanup_faults_never_undo_the_real_publication`
- `src/test/int/python/repomap_kg/retrieval/projection_publication.int.test.py::test_real_sqlite_publication_correspondence_custody_gates`
- `src/test/int/python/repomap_kg/ops/server_retained_attempt_recovery.int.test.py::test_real_rehashed_retained_objects_reach_deeper_artifact_gates`
- `src/test/int/python/repomap_kg/ops/server_retained_attempt_recovery_custody.int.test.py::test_real_conflicting_backup_holds_after_valid_proofs_without_graph_change`
- `src/test/int/python/repomap_kg/ops/server_retained_attempt_recovery_custody.int.test.py::test_real_retained_record_schema_refusals_preserve_private_state`

The final binding additionally requires the five cases in
`src/test/unit/python/tools/ci/d12_system_grant.unit.test.py`, the five cases in
`src/test/unit/python/tools/ci/d12_system_proof_host.unit.test.py`, and three
exact nodes in `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py`:

- `test_system_hold_proof_capture_and_child_secure_writer`
- `test_sandbox_dispatch_blocks_system_suite_without_valid_proof`
- `test_cross_process_flock_and_o_excl_race_and_execute_system_run`

Static/type enforcement, privacy, suppression, topology, export, length,
changed-source compilation, whitespace and historical-custody checks are
required on final source, followed by independent `dynamic_default` review.
Final source counts, selectors and results are retained in the exact commit
report. Complete local unit, integration, smoke, staging, system and combined
suites are intentionally unselected, as are local coverage, application/SDK
builds, native qualification and acquisitions. Source arc forecasts are not
measured percentages; hosted 85/80 floors and desired 87/82 margins remain
pending.

## One publication boundary

Hosted capacity: `AVAILABLE`. Current manual retry authority selects one
ordinary staging push through existing draft PR23 and automatic CI131 attempt 1.
Authenticated consumed counters are 41 application starts, 10 native AMD
commands and 24 wheel transfers. Fresh caps are 42/11/26 under ADR 0172.
All earlier spent authorizations and ledger prefixes remain preserved. No
automatic retry, CI132, second push, main/tag promotion or release acceptance
is included. Hosted execution remains pending until exact source-bound
results arrive; local proof is not whole-population acceptance.
