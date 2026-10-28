# CI86 test-inventory and measurement-path repair Exit

Phase REPOMAP-PRODUCT6-NAVIGATION47-CI86REPAIR1. The current remediation
request covers the three remaining CI86 failures. The maintainer subsequently
approved ADR0108's exact CI87 grant and necessary unchanged tooling IO extraction.
This changes no product source, runner policy, runtime supplier pin, dependency,
debt ceiling, coverage threshold or hosted trigger.

## Observed CI86 results

Run 40752598642 attempt 1 executed staging
`a89592ffa2150974f81c640ced79035f5b8cd661`, test merge
`2fb2ff0c41ef8d7847c18da4975d97bafb16dd6f`, tree
`329c36f42c8017bf3aa6b733fef306bb14b381b5`.
Seven jobs passed; unit and staging failed on tests. The unit population had
two failures, 14177 passes and 40 skips. Staging's measured leg had one failure,
1815 passes and 12 skips. Those remain failures despite sufficient coverage.

Unit measured 87.9763% lines / 87.6070% branches against hard 85/85 and the
requested 87/87 margin. Staging measured 90.1724% / 82.3417% against hard 80/80
and the requested 82/82 margin. These values belong only to CI86.

The native AMD assembled-system gate passed all five scenarios, archive round
trip and MCP readback. Parent postflight independently validated the retained
host proof, export manifest, committed policy bytes, v2 supplement, report and
binding, exact candidate identity and terminal cleanup. This is positive system
evidence for that exact candidate; the overall workflow remains unqualified.

## Causes and corrections

- The active package-root inventory did not list the ADR0106 `_temporary.py`
  owner. Add that exact owner and retain strict equality with actual root files.
- The projection test's exact forward-admission list stopped before the reviewed
  CI85 repair admission. Add that literal phase while retaining the inherited
  proof hops, chain digests, transition count and baseline byte assertions.
- The workflow test moved its product package into disposable installed-layout
  scratch. Under complete staging measurement, the runner correctly refused that
  unregistered PYTHONPATH. Restore this one test's original source-layout body,
  byte-for-byte from the preceding publication, preserving all receipt/outcome
  assertions. The separate native installed-package and mixed-language regression
  owners remain unchanged. Do not grant the copied root measurement authority.

A new exact copied-package-root negative case confirms refusal before launch
or child registration. Existing allowed-path/environment and rogue-path/ambient
rejection cases remain selected. No coverage adapter or capability rule changed.

## Scoped verification

The two original unit failures reproduced before correction. The following
commands use `tools/run_tests.py --suite unit|int --no-coverage --jobs 1
--report-dir <owned-report-directory> -- <selectors>`.

### repair-unit1

Result: `69 passed in 32.21s`.

- `src/test/unit/python/repomap_kg/root_package_structure.unit.test.py`
- `src/test/unit/python/tools/ci/retained_python_projection.unit.test.py`
- `src/test/unit/python/tools/test_runner_portable_coverage.unit.test.py::RunnerPortableCoverageUnitTests::test_relocated_package_does_not_inherit_source_measurement_authority`
- `src/test/unit/python/tools/test_runner_portable_coverage.unit.test.py::RunnerPortableCoverageUnitTests::test_negative_containment_and_ambient_rejections`
- `src/test/unit/python/tools/test_runner_portable_coverage.unit.test.py::RunnerPortableCoverageUnitTests::test_authorized_environment_passes_only_bounded_fields`

The selected adapter unit cases construct fixture configuration and injected
launch doubles; they do not start project coverage or run measured product
children. Complete measured-population acceptance remains hosted.

### workflow-int1

Result: `1 passed in 0.62s`. Containerized execution also uses
`--pg-container-port 55433 --smoke-image-reference
sha256:ff710677e697054c516f12c53c92166f1aef075f21b2a593f4c615e522112b4e`.

- `src/test/int/python/repomap_kg/coordinator/run25_portable_workflows.int.test.py::test_workflow_end_to_end_portable_worker_execution_and_cleanup`

Source preservation, exact owned cleanup and before/after host resource equality
passed. No local application/SDK build, dependency-runtime materialization or
new image pull was performed beyond ordinary canonical transient inner setup.
No complete local unit, integration, smoke, staging, system or combined suite
and no local project Python coverage was selected.

## Approved CI87 publication boundary

The maintainer selected Route A from the reviewed CI87 packet. ADR0108 allocates
exactly one seventh native AMD application start and one ordinary staging
synchronize to draft PR13, triggering CI87 attempt 1. Six consumed observations
remain immutable. Fresh approval, nonce/reservation, pre-append ledger and exact
candidate/event/Git/platform/SDK binders are required. Both validators deny spent
CI86 values alongside every earlier pair. No eighth start or automatic retry.

The runtime image context remains unchanged at 696 files. The old positive
system report remains bound to CI86 and cannot qualify a successor tree.
At most one necessary hosted SDK materialization may use the unchanged recipe.
No local application/SDK build or complete local test/coverage run occurred.

To preserve the existing 400-line limit, existing strict JSON/file IO and its
error class moved unchanged to one clean tooling owner. Original public names
are re-exported. Parent AST comparison verifies unchanged bodies: duplicate-key,
UTF-8, regular-file/no-follow, mode and byte-bound refusal behavior is retained.
No dependency or policy change; only a clean additive tooling inventory entry.

### admission-ci87-unit2

Result: `34 passed in 1.55s`, through the same scoped unit runner contract.

- `src/test/unit/python/tools/ci/d12_system_grant.unit.test.py`
- `src/test/unit/python/tools/ci/d12_system_proof_host.unit.test.py`
- `src/test/unit/python/tools/system/d12_system_session.unit.test.py`
- `src/test/unit/python/tools/system/d12_qualification.unit.test.py`

### admission-ci87-int1

Result: `3 passed in 0.33s`, using the same containerized configuration above.

- `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_system_hold_proof_capture_and_child_secure_writer`
- `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_sandbox_dispatch_blocks_system_suite_without_valid_proof`
- `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_cross_process_flock_and_o_excl_race_and_execute_system_run`

The final binder/IO source review completed with no blockers. Parent corrections
were limited to deterministic cohort insertion and the unused import identified
by review/static checking; other code ASTs and all reviewed record fields remained
unchanged. Fresh canonical sealed retention enforcement passed with zero cohort
regressions and unchanged debt. Final export/privacy/commit checks are required
before publication. Initial repair evidence is retained separately. Hosted CI state is AVAILABLE. CI86 unit/staging remain
EXECUTED_FAIL; its exact assembled-system workload is verified EXECUTED_PASS.
The successor is NOT ACCEPTED as hosted qualification; complete populations,
the two-point coverage margin and native AMD system evidence remain pending.
No new remote mutation has occurred before source acceptance. Main remains
public preview v0.0.3. No main promotion, tag, deployment or dispatcher interruption.
