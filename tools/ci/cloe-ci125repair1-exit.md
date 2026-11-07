# REPOMAP-CLOE-CI125REPAIR1 Exit

## Scope and disposition

Forward repair of CI125's two executed regressions under ADR0164. Publication
is conditional on the recorded final checks and independent review. Scoped
proof establishes source readiness; complete candidate qualification is
pending automatic CI126 attempt 1 after one authorized staging publication.

The run-INSERT test now identifies its subject statement rather than relying
on an obsolete prefix index. The busy storage refusal has an internal
`StorageSchemaError` subtype, translated only at durable recovery boundaries.
Closure and legacy quarantine preserve uncertainty without committing closure
writes; unrelated schema/programming failures retain their original identity.
The connected regression proves bounded refusal, absent unexpected diagnostics,
singleton liveness and successful heartbeat recovery after lock release.

## Executed scoped proof

Canonical commands use `tools/run_tests.py --suite unit|int --no-coverage
--jobs 1 --report-dir <run-owned-report> -- <exact-selectors>`; integration
adds `--pg-container-port 55433` and the unchanged cached diagnostic runtime
reference inside the repository-owned disposable sandbox.

Both original failing nodes reproduced before repair. The feature cohort
passes 89 unit and 17 containerized integration cases:

- unit: `src/test/unit/python/repomap_kg/storage/publication_generations.unit.test.py`
- unit: `src/test/unit/python/repomap_kg/storage/publication_lock_bounds.unit.test.py`
- unit: `src/test/unit/python/repomap_kg/storage/repository_admission_lock.unit.test.py`
- unit: `src/test/unit/python/repomap_kg/coordinator/restart_fencing.unit.test.py`
- unit: `src/test/unit/python/repomap_kg/coordinator/startup_recovery.unit.test.py`
- unit: `src/test/unit/python/repomap_kg/coordinator/recovery_diagnostics.unit.test.py`
- int: `src/test/int/python/repomap_kg/coordinator/startup_recovery_fencing.int.test.py`
- int: `src/test/int/python/repomap_kg/storage/bigint_publication_exclusion.int.test.py`

Fresh campaign proof selects the grant unit owner and these exact admission
integration nodes; its unrelated runtime-materialization test is excluded:

- unit: `src/test/unit/python/tools/ci/d12_system_grant.unit.test.py`
- int: `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_system_hold_proof_capture_and_child_secure_writer`
- int: `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_sandbox_dispatch_blocks_system_suite_without_valid_proof`
- int: `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_cross_process_flock_and_o_excl_race_and_execute_system_run`

The grant proof passes five unit and three containerized integration cases,
for a combined 94 unit and 20 integration cases. All observed build/pull and
residue counters are zero; the unrelated materialization case was not selected.
The phase commit and private manager report record final changed-source static
enforcement, compileall, topology, export, length, whitespace, suppression,
privacy and independent review results after execution. No coverage claim
follows from these scoped commands.

## Preserved boundaries and hosted status

CI state: AVAILABLE under the standing operator declaration. CI125 is
EXECUTED_FAIL, with hard coverage floors met. Its successful constituent
jobs do not qualify the failed candidate. CI126 permits one application
start 37 after authenticated 36, native AMD Rust command 6 and the same two
pinned wheels at cumulative cap 16. Fresh approval, ledger and reservation
are bound to the live context and unchanged public main; old grants remain
spent. Only the current guard digest changes in the 264-path Rust closure.

Complete local unit, integration, smoke, staging, system and combined suites
are intentionally unselected: hosted CI owns full-population qualification
and no current complete-suite override exists. Local coverage, application/
SDK builds, acquisitions, native model/parser execution and automatic retries
are unselected. No new dependency, runner policy, suppression or debt allowance.
No main/tag/release/deployment, image/installed/full W6/W7 acceptance is claimed.
Other resource-governance advisories remain deferred to a later milestone.
