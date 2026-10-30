# REPOMAP-CLOE-CI94REPAIR1 Exit

## Failure and corrections

CI94 attempt 1 executed and failed: three unit cases, one pre-review suppression
finding and incomplete staging measurement. Unit coverage was 88.1% line / 87.6%
branch against 85/85, already exceeding the requested two-point margin. All 1,862
measured integration cases passed, but an unregistered discovery-script shard
was correctly rejected and abrupt A remained blocked. Native preflight and the
main-system gate passed; retained build/image/cleanup evidence spends start 11.

Corrections under ADR0117:

- Create the replacement fixture while its original inode still exists, prove
  distinct identity and atomically replace. Retain every drift refusal and
  evidence-preservation assertion; no journal/ownership semantics change.
- Keep stable primitive qualification at import time while deferring only the
  migration `fcntl` probe. Local imports remain neutral, migration still refuses
  unsupported platforms before writes, and filesystem guard/crash fixtures work.
- Update the missed runner assertion to typed first-cause evidence, preserving
  empty-partition, no-execution and qualification-refusal assertions.
- Remove the new type suppression with explicit exception narrowing. Enforce
  the complete suppression policy, not inventory-only observation; no baseline edit.
- Route both raw diagnostic-tool child launches through the existing full
  coverage-environment scrubber. Synthetic-source cases reproduce inherited
  authority with `-I` and `-B` before correction and prove clean child state,
  no child shard, removed bootstrap path and an unchanged parent afterward.
  The child request fixture now passes private-file checks before schema refusal.

The exact retained shard's producer is inferred from launch shape and source,
not asserted from an absent parent-PID trace. The repairs close both raw
diagnostic inheritance paths. Strict unknown-shard refusal, registration/receipt
contracts, M/A populations, source denominator and coverage gates are unchanged.
The initial full lazy platform probe was rejected by scoped guard/crash tests;
the corrected split preserves stable primitive checks and passed those owners.

## Scoped verification

The corrected source passed 92 canonical scoped unit and 23 containerized
integration cases before final grant binding. Final proof adds current grant,
host/session/qualification and secure admission owners below; exact counts and
source hashes are retained with the commit. Native source/grant review, static,
full suppression policy, export, compilation, length, privacy and both whitespace
checks are required before commitment/publication.

Unit: `tools/run_tests.py --suite unit --no-coverage --jobs 1 --` with:

- `src/test/unit/python/repomap_kg/ops/cloe_config_recovery.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/cloe_config_migration.unit.test.py`
- `src/test/unit/python/repomap_kg/storage/sqlite_local_locking.unit.test.py::test_canary_local_closure_never_imports_fcntl`
- `src/test/unit/python/tools/test_report_runner.unit.test.py`
- `src/test/unit/python/tools/test_runner_coverage_diagnostics.unit.test.py::test_unregistered_valid_sqlite_shard_rejected`
- `src/test/unit/python/tools/test_runner_coverage_diagnostics.unit.test.py::test_unmeasured_family_scrubbed_and_extra_env_cannot_override`
- `src/test/unit/python/tools/test_runner_coverage_atomicity.unit.test.py::test_scrub_coverage_environment_disarms_capability_atomically`
- `src/test/unit/python/tools/ci/d12_system_grant.unit.test.py`
- `src/test/unit/python/tools/ci/d12_system_proof_host.unit.test.py`
- `src/test/unit/python/tools/system/d12_system_session.unit.test.py`
- `src/test/unit/python/tools/system/d12_qualification.unit.test.py`
- `src/test/unit/python/tools/system/d12_system_evidence.unit.test.py`

Integration: `tools/run_tests.py --suite int --no-coverage --jobs 1
--pg-container-port 55433 --` with:

- `src/test/int/python/tools/runner_failure_recovery.int.test.py`
- `src/test/int/python/repomap_kg/cli/cloe_config_migration.int.test.py`
- `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_system_hold_proof_capture_and_child_secure_writer`
- `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_sandbox_dispatch_blocks_system_suite_without_valid_proof`
- `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_cross_process_flock_and_o_excl_race_and_execute_system_run`

Scoped Python project coverage is disabled. The synthetic component session uses
only a temporary fixture source; fixed canonical Go-helper component checks emit
their own component coverage. Neither is RepoMap whole-population coverage.
Complete local unit, integration, smoke, staging, system and combined populations
are unselected: no current complete-suite override exists. No local application/
SDK builds, external pulls or live-home/database operations are included.

## Campaign and custody

Eleven observed starts stay spent. The fresh user request binds one twelfth native
AMD start to CI95 attempt 1, with fresh authority, nonce/reservation, pre-append
ledger and final runtime context. All spent pairs remain refused, including CI94;
older before/approval/ledger refusal cases remain and are extended. No thirteenth
start, automatic retry, attempt 2, policy/debt/threshold/pin/dependency change,
main promotion, tag or deployment. Existing reported commits remain immutable.
The protected checkout remains preserved. Public author/committer are Samuel
Leighton Lair <sam.lair@knowledge-forge.ai>.

## Hosted CI

- State: AVAILABLE, operator supplied; no quota/billing change.
- CI94 classification: EXECUTED_FAIL for its exact candidate; successful system
  evidence consumes the allocation without qualifying the failed overall attempt.
- Remote action: one ordinary staging synchronize push is prepared; none at commit time.
- Automatic lane: existing nine-job `repomap-release-qualification` through draft PR23.
- Pending: complete hosted static/unit/smoke/integration/system and coverage for
  the corrected successor, including both two-point coverage margins.
- Local sufficiency: changed-boundary, measurement-custody and admission proof only.
  No successor hosted qualification, installed release or promotion is claimed.
