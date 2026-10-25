# REPOMAP-PRODUCT6-NAVIGATION47-CI65REPAIR1: Bounded CI65 Remediation

## Scope and Classification

This document records the bounded source and test-owner remediation for hosted
release-qualification attempt CI65 (`run_id` `40165400267` on `staging` head
`461871c20801c90b7c1db1afff094d17b8a50d10`, classified `EXECUTED_FAIL`).

This slice repairs only the pre-review static dependency attestation and the
two stale unit test assertions exposed by CI65. It does not promise entire
release qualification, and it does not accept runtime, image, or P3 promotion.

## Observed CI65 Outcomes

1. **`pre-review-static` (`EXECUTED_FAIL`)**:
   - Hash-locked C Psycopg `3.3.6` and system `libpq` bootstrap succeeded,
     after which `verify_python_distribution` in `tools/ci/bootstrap_pre_review.py`
     failed when importing `psycopg_c` directly in a fresh child Python process.
   - Upstream `psycopg_c` `3.3.6` (`psycopg_c/__init__.py`,
     https://github.com/psycopg/psycopg/blob/3.3.6/psycopg_c/psycopg_c/__init__.py)
     checks `if "psycopg" not in sys.modules:` and raises
     `ImportError("the psycopg package should be imported before psycopg_c")`.

2. **`unit-tests` (`EXECUTED_FAIL`)**:
   - The canonical unit population failed with **two** pytest assertion failures,
     not a coverage failure:
     - `src/test/unit/python/tools/ci/pipe0_topology_contract.unit.test.py`:
       `test_canonical_test_runner_appears_exactly_three_times` asserted a stale
       three-call count (`3 == 4`), whereas `.github/workflows/repomap-release-qualification.yml`
       has four approved `python3 tools/run_tests.py` invocations across four
       distinct jobs (`unit-tests`, `d12-native-amd64`,
       `staging-integration-gate`, and `main-system-gate`).
     - `src/test/unit/python/tools/test_report_runner.unit.test.py`:
       `test_runner_int_suite_fails_and_refuses_execution_when_discovery_fails`
       expected the v1 partition missing-key list without `'optional'`, whereas
       report schema v2 (`tools/staging_report_contract.py`) requires and sorts
       `['abrupt', 'collected', 'deferred', 'measured', 'optional', 'required', 'sha256']`.
   - Although the unit run reported an `87.6%` branch coverage advisory on the
     failed execution, canonical unit pytest failed two test items and is
     **not** qualified on CI65.

3. **`staging-integration-gate` (Predecessor CI65 Evidence)**:
   - Existing CI65 staging reports recorded `54899 / 60921` lines
     (`90.11506705405361%`) and `16336 / 19864` branches (`82.23922674184455%`),
     passing the `80% / 80%` hard staging gate on the CI65 predecessor commit.
   - Those CI65 predecessor staging measurements belong solely to predecessor
     head `461871c20801c90b7c1db1afff094d17b8a50d10` and must not be attributed
     to the successor candidate.

4. **`d12-native-amd64` and `main-system-gate` (Held / Negative Preflight Evidence)**:
   - `d12-native-amd64` produced valid negative preflight evidence on
     `linux/amd64`, reporting the sole remaining stdlib closure failure on
     `_tkinter` (missing `libtk8.6.so` / Tcl-Tk runtime library).
   - `main-system-gate` remained held before any system SDK or candidate image
     build.

## Bounded Remediation in CI65REPAIR1

1. **Narrow `psycopg_c` Attestation Prerequisite Import (`tools/ci/bootstrap_pre_review.py`)**:
   - `verify_python_distribution` now imports `psycopg` before importing
     `sys.argv[1]` **only** when `sys.argv[1] == "psycopg_c"`.
   - Exact distribution version verification (`importlib.metadata.version(sys.argv[2]) == expected_version`),
     resolved module file ownership (`Path(module.__file__).resolve().is_relative_to(Path(sys.argv[4]).resolve())`),
     native `pg_config` bootstrap custody, binary/pure-Python refusal, and
     license/build boundaries remain unchanged. Unrelated modules receive no
     special handling.
   - Unit regression coverage in
     `src/test/unit/python/tools/ci/pre_review_distribution.unit.test.py` and
     containerized integration coverage in
     `src/test/int/python/tools/ci/pre_review_distribution.int.test.py` verify
     the `psycopg_c` prerequisite import, non-preload for unrelated modules,
     exact version mismatch refusal, resolved `owner_root` refusal, and missing
     module/metadata refusal.

2. **Role-Bound Four-Call Topology Contract (`src/test/unit/python/tools/ci/pipe0_topology_contract.unit.test.py`)**:
   - Updates the canonical runner count assertion to bind all four approved
     invocations in `.github/workflows/repomap-release-qualification.yml` to
     their exact single-execution job roles:
     - `unit-tests` (`--suite unit`),
     - `d12-native-amd64` (bounded `--sandbox --suite int --no-coverage` with
       `--d12-core-image-profile linux/amd64`, `--d12-core-image-preflight`, and
       exact node `src/test/int/python/repomap_kg/runtime/d12_core_image_refresh.int.test.py::test_d12_core_image_refresh_candidate_round_trip`),
     - `staging-integration-gate` (`--suite staging`),
     - `main-system-gate` (`--suite system`),
     while excluding `tools/run_tests.py` from every other job and adding
     negative mutation proofs for missing, duplicate, leaked, or unapproved
     runner invocations.

3. **Discovery-Failure Diagnostic Key Alignment (`src/test/unit/python/tools/test_report_runner.unit.test.py`)**:
   - Updates the expected partition missing-key diagnostic in
     `test_runner_int_suite_fails_and_refuses_execution_when_discovery_fails`
     to include `'optional'`, preserving fail-closed discovery refusal, zero leg
     execution, `StagingReportValidationError` enforcement, and `qualifies == False`.

4. **Additive Retention Inventory Admission (`tools/ci/python_retention_inventory.json`)**:
   - Adds the two new test owner rows and phase cohorts
     (`product6.navigation47.ci65repair1.int_test_owners` and
     `product6.navigation47.ci65repair1.unit_test_owners`) additively without
     modifying existing rows, ordering, ratchets, or historical authority records.

## Unchanged Hard Gates and Held Boundaries

- **Hard Coverage and Quality Gates**: Unit (`85% / 85%` statement/branch) and
  staging integration (`80% / 80%` statement/branch) hard gates, runner
  implementation, report schema, populations, and static-analysis ratchets are
  unchanged.
- **Pending D12 Payload Design and Held System Admission**: No change is made to
  the exact ARM (`_tkinter`) exclusion, `src/main/python/repomap_kg/runtime/python_payload.py`
  implementation, pinned base image digests, frozen D12 source/candidate
  records (`tools/ci/d12_hosted_candidate.json`), application build budget
  ledger, or `main-system-gate` hold. D12 `linux/amd64` `_tkinter` disposition,
  image qualification, runtime acceptance, and P3 remain pending separate
  written design and qualification authority.
