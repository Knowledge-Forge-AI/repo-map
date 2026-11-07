# REPOMAP-CLOE-CI91REPAIR1 Exit

Status: CI91 failures reproduced and repaired; scoped proof and native source
review passed. Static/export/privacy checks passed. One corrected staging
publication is prepared; hosted qualification remains pending for the successor.

CI91 attempt 1 failed unit and integration behavior checks while seven other
jobs passed, including native AMD system qualification. Unit coverage was
88.0% statements / 87.6% branches; integration was 90.2% / 82.4%. These exceed
the hard floors by at least two points but do not qualify a successor tree.

The loader now imports its discovery helper privately, restoring the existing
eager public facade without adding an API. Empty-home diagnostics retain the
legacy filename wording and also name CLOE files. The autouse CLOE isolation
fixture owns a separate MonkeyPatch context, preserving the original shared
test monkeypatch/resource-restoration teardown order. Injected failure and
rollback assertions remain intact; the integration owner asserts both filename
families in the diagnostic.

Native Claude Opus 5.5 high found no correctness or regression blockers. Its
consumer searches were completed: no dependent use of the accidental loader
export or lost CI91 empty-home wording remains. The unchanged workflow admits
pull_request synchronize and has no push trigger. Sealed static enforcement
completed with zero cohort regressions. Topology, file length, suppression
inventory, public export, compilation and diff checks passed; pinned
Betterleaks found zero findings with full redaction. Ownership, historical
transitions, debt ceilings, workflow policy, package metadata and supplier pins
remain unchanged.

Canonical scoped verification uses tools/run_tests.py with --no-coverage and
--jobs 1. Before correction, unit reproduced one assertion failure and one
teardown error; integration reproduced the legacy diagnostic assertion.
After correction, 35 unit and 16 containerized integration cases passed.
Fresh grant/admission proof added 36 passing unit cases and three passing
containerized integration cases. No application or SDK build ran locally;
integration verified exact resource cleanup using existing cached identities.

Repair unit selectors:

- src/test/unit/python/repomap_kg/ops/config_redaction.unit.test.py
- src/test/unit/python/repomap_test_support/resource_run_transaction_fix1.unit.test.py
- src/test/unit/python/repomap_kg/ops/cloe_config.unit.test.py

Repair integration selectors:

- src/test/int/python/repomap_kg/cli/ops_config.int.test.py::CliOpsConfigIntegrationTests::test_ops_config_check_reports_config_home_shape_errors
- src/test/int/python/repomap_kg/cli/cloe_config.int.test.py

Admission unit selectors:

- src/test/unit/python/tools/ci/d12_system_grant.unit.test.py
- src/test/unit/python/tools/ci/d12_system_proof_host.unit.test.py
- src/test/unit/python/tools/system/d12_system_session.unit.test.py
- src/test/unit/python/tools/system/d12_qualification.unit.test.py
- src/test/unit/python/tools/system/d12_system_evidence.unit.test.py

Admission integration selectors, each in
src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py:

- test_system_hold_proof_capture_and_child_secure_writer
- test_sandbox_dispatch_blocks_system_suite_without_valid_proof
- test_cross_process_flock_and_o_excl_race_and_execute_system_run

ADR0111 binds the current "CI failed. Try again." instruction to one corrected
staging synchronize publication through draft PR23 and CI92 attempt 1. CI91's
actual eighth build is retained as spent using hash-verified build intent and
image-binding evidence. All eight consumption observations are preserved.
A fresh exact grant reserves at most one ninth AMD start and denies CI91's
spent nonce/reservation. Synchronize before/after fields, exact main/staging
identities, frozen source, native host/SDK and live merge parents remain strict.
No automatic retry, tenth start, attempt 2 or manual duplicate is admitted.

Hosted CI state remains operator-supplied AVAILABLE. No remote action has
occurred at this record's preparation. Expected automatic lane is the normal
nine-job release-qualification campaign. Complete unit, smoke/integration,
system and coverage gates remain pending for the corrected exact candidate.
Local complete unit, integration, smoke, staging, system and combined suites,
and project coverage, were intentionally unselected; no override was granted.
Public main, supplier pins, dependency policy, debt ceilings and the protected
private checkout remain unchanged.
