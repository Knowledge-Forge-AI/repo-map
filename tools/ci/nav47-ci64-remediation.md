# NAV47 CI64 Bootstrap And Measured-Test Fixture Remediation

Phase `REPOMAP-PRODUCT6-NAVIGATION47-CI64REPAIR1` remediates the two concrete defects exposed by
hosted CI run [`40154773099`](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/40154773099)
on `staging` commit `0284aa36075c9c74cda1b179ed3240659c7b3164` (test merge `38bb`), while recording
the positive negative-evidence export from the `d12-native-amd64` job.

## Scope And References

- Governing ADR amendment:
  [`docs/adr/2026/10/0093-ci63-pg-config-and-native-report-export.md`](../../docs/adr/2026/10/0093-ci63-pg-config-and-native-report-export.md)
- Prior CI63 remediation note:
  [`tools/ci/nav47-ci63-remediation.md`](nav47-ci63-remediation.md)
- Upstream `dpkg` `dpkg-divert` reference:
  [`src/divert/main.c`](https://github.com/guillemj/dpkg/blob/main/src/divert/main.c)
- Upstream pinned Coverage `7.15.4` startup references:
  [`coverage/pth_file.py`](https://github.com/coveragepy/coveragepy/blob/7.15.4/coverage/pth_file.py),
  [`coverage/control.py`](https://github.com/coveragepy/coveragepy/blob/7.15.4/coverage/control.py),
  and [`coverage/patch.py`](https://github.com/coveragepy/coveragepy/blob/7.15.4/coverage/patch.py)
- Hosted CI64 run:
  [`40154773099`](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/40154773099)

## Hosted CI64 Evidence Summary

Run `40154773099` established three concrete observations across the hosted qualification jobs:

1. **`unit-tests` and `pre-review-static`**:
   Both jobs failed during C Psycopg bootstrap (`Build the hash-locked C Psycopg prerequisite` in
   `unit-tests` and `Materialize the pinned pre-review toolchain` in `pre-review-static`) with
   `psycopg bootstrap refused: diverted target /usr/bin/pg_config.libpq-dev is itself diverted`
   (exit code `2`) before unit or static checks executed.
2. **`staging-integration-gate` (`M` and `A`)**:
   Measured integration leg `M` completed the C Psycopg bootstrap and passed all `1,793` selected
   integration tests (`12` skipped, `24` deselected) before strict post-pytest coverage shard
   integrity validation (`validate_shard_directory_integrity`) rejected an unregistered coverage
   shard with `launch_shape == "cpython:-c"` (`no owner can be inferred from PID alone`). Because
   `M` failed after test execution, dependent reconciliation leg `A` remained blocked with empty
   records.
3. **`d12-native-amd64`**:
   The native AMD64 D12 preflight job exported a valid sealed negative-evidence bundle with zero
   seal or validation errors, retaining the complete native AMD64 baseline and authentic refusal
   for missing Tcl/Tk shared libraries (`libtk8.6.so` and `libtcl8.6.so`). `main-system-gate`
   remained held as expected. No raw baseline copies are duplicated in public repository paths.

## 1. `dpkg-divert` Endpoint Semantics And Custody Verification

In upstream `dpkg` (`src/divert/main.c`, functions `diversion_listpackage` and `diversion_truename`),
a single diversion stanza binds its `divert` struct to the file-name nodes of both the diverted
source path (`/usr/bin/pg_config`) and the `useinstead` destination path
(`/usr/bin/pg_config.libpq-dev`):

- `dpkg-divert --listpackage /usr/bin/pg_config` and
  `dpkg-divert --listpackage /usr/bin/pg_config.libpq-dev` both check `if (fnn->divert)` and print
  the same diversion owner (`postgresql-common` or `LOCAL`).
- `dpkg-divert --truename /usr/bin/pg_config` and
  `dpkg-divert --truename /usr/bin/pg_config.libpq-dev` both check
  `if (fnn->divert && fnn->divert->useinstead)` and print `/usr/bin/pg_config.libpq-dev`.

CI63 checked `if target_mgr or target_true != true_p:` on `/usr/bin/pg_config.libpq-dev`, which
treated the normal non-empty `--listpackage` output (`postgresql-common`) on the destination
endpoint as a chained diversion.

### Custody And Test Updates

- [`tools/ci/psycopg_pg_config_custody.py`](psycopg_pg_config_custody.py) updates
  `_verify_diversion_records` so that after verifying `mgr in _KNOWN_DIVERSION_MANAGERS` on the
  source path, the diverted target path must satisfy `target_mgr == mgr` (refusing empty,
  `"LOCAL"`, foreign, or mismatched diversion managers) and `target_true == true_p` (refusing
  chained target truenames).
- [`src/test/unit/python/tools/ci/psycopg_custody_fixture.py`](../../src/test/unit/python/tools/ci/psycopg_custody_fixture.py)
  populates default endpoint diversion manager and truename entries for both the diverted source
  and the `useinstead` destination before applying test-specific override mappings.
- [`src/test/unit/python/tools/ci/psycopg_pg_config_custody.unit.test.py`](../../src/test/unit/python/tools/ci/psycopg_pg_config_custody.unit.test.py)
  and [`src/test/unit/python/tools/ci2a_psycopg_bootstrap.unit.test.py`](../../src/test/unit/python/tools/ci2a_psycopg_bootstrap.unit.test.py)
  retain full bootstrap and private build-child binding unit proof and verify positive four-call
  endpoint checks across `/usr/bin/pg_config` and `/usr/bin/pg_config.libpq-dev` as well as
  defensive owner-level refusals for missing, `"LOCAL"`, mismatched known
  (`postgresql-common-dev`), and foreign (`custom-pkg`) target managers and chained target
  truenames (`target_true != true_p`).
- [`src/test/int/python/tools/ci/psycopg_pg_config_custody.int.test.py`](../../src/test/int/python/tools/ci/psycopg_pg_config_custody.int.test.py)
  exercises the changed custody boundary directly against the container's real `dpkg-divert` and
  `dpkg --print-architecture` binaries on a test-owned temporary `--admindir` and `--instdir`
  while proving `/var/lib/dpkg/diversions` and `/var/lib/dpkg/status` remain unchanged. It uses a
  strict runner that delegates only `dpkg-divert` to the real CLI, returns explicit minimal
  `dpkg-query -S` and `dpkg-query -L` transcript fixtures, and raises on any unexpected command
  (without faking `pip`, C Psycopg attestation, private `PATH` symlink execution, global
  `realpath` patching, or installed-package qualification). It proves positive
  `postgresql-common` and `postgresql-common-dev` diversion pairs, real `dpkg-divert --add` CLI
  nonzero refusal when attempting to add a chained or conflicting diversion, and
  `_verify_diversion_records` refusals for missing, `--local`, unknown-manager, uninstalled-manager,
  unexpected-truename, malformed `diversions`-database, and conflicting chained database records
  using stable explicit alphanumeric pytest parameter `ids` compatible with strict canonical report
  partition validation.

## 2. Measured Integration Isolation For Stdlib Import Probes

During measured integration runs (`M`), `python_payload.observe` executes short-lived CPython
subprocesses of the form `[executable, "-I", "-B", "-c", f"import {module}"]` with
`env={**os.environ, "LD_BIND_NOW": "1"}` for each candidate shared extension in the staged mount
(in `python_payload_contract.int.test.py`, `_select_sdk_extensions(2)` selects the first two
available shared extensions from its declared `_SDK_EXTS` tuple, plus `_tkinter` in the broken-ELF
trim test). Under `-I` (isolated mode), CPython ignores `PYTHONPATH` and therefore skips the test
runner's `bootstrap/sitecustomize.py` coverage manifest registration, while standard `site.py`
still processes `site-packages/*.pth` (`a1_coverage.pth` in pinned Coverage `7.15.4`, generated
from [`coverage/pth_file.py`](https://github.com/coveragepy/coveragepy/blob/7.15.4/coverage/pth_file.py)
and invoking `coverage.process_startup(slug="pth")` in
[`coverage/control.py`](https://github.com/coveragepy/coveragepy/blob/7.15.4/coverage/control.py)
whenever `COVERAGE_PROCESS_START` or `COVERAGE_PROCESS_CONFIG` from
[`coverage/patch.py`](https://github.com/coveragepy/coveragepy/blob/7.15.4/coverage/patch.py) is
present in the inherited environment). Those `-I -B -c` probes wrote an unregistered coverage shard
with `launch_shape == "cpython:-c"` that failed `validate_shard_directory_integrity`. This
root-cause chain remains a source-derived inference until a fresh hosted measured `M` run
completes.

### Test-Support Probe Adapter And Contract Coverage

- [`src/test/support/python/repomap_test_support/python_payload_probes.py`](../../src/test/support/python/repomap_test_support/python_payload_probes.py)
  provides `validate_allowed_stdlib_modules`, `is_stdlib_import_probe_command`, and
  `make_stdlib_import_probe_runner`. For commands matching `[executable, "-I", "-B", "-c",
  "import <stdlib>"]` on the validated stdlib module allowlist, the wrapper passes the child
  environment through `prepare_child_coverage_environment(..., family="unmeasured")` to strip
  `COVERAGE_PROCESS_START`, `COVERAGE_PROCESS_CONFIG`, `COVERAGE_FILE`, and other `COVERAGE_*`
  variables plus coverage bootstrap `PYTHONPATH` entries while preserving `LD_BIND_NOW="1"` and all
  other caller environment variables. All non-probe commands (`ldd`, `dpkg-query`, and non-`-c`
  invocations) pass through unchanged, and unapproved `-I -B -c` or `-c` snippets raise
  `ValueError`.
- [`src/test/unit/python/repomap_test_support/python_payload_probes.unit.test.py`](../../src/test/unit/python/repomap_test_support/python_payload_probes.unit.test.py)
  seeds both `COVERAGE_PROCESS_START` and literal `COVERAGE_PROCESS_CONFIG` in its synthetic
  environment fixture (without deserializing or activating coverage) and verifies allowlist
  validation, narrow command matching, `COVERAGE_*` scrubbing on approved stdlib probes,
  preservation of `COVERAGE_PROCESS_START` and `COVERAGE_PROCESS_CONFIG` on non-probe calls,
  `LD_BIND_NOW` and caller environment preservation, and unapproved probe refusal.
- [`src/test/int/python/repomap_kg/runtime/python_payload_contract.int.test.py`](../../src/test/int/python/repomap_kg/runtime/python_payload_contract.int.test.py)
  routes every `python_payload.observe`, `python_payload.main`, and `python_payload.owners`
  subprocess seam — including all four refusal-case `payload.main` invocations in
  `test_real_walk_special_entries_and_main_guard_refusals` — through
  `make_stdlib_import_probe_runner` over the actual selected SDK stdlib modules without depending
  on guard/probe ordering or altering production `python_payload.py`, test-runner shard integrity
  gates, or leg `A` reconciliation semantics.

## 3. Scoped Verification Boundaries, Commands, And Preserved Program Holds

- **Scoped verification commands (`--no-coverage`)**:
  - Unit selector:
    `python3 tools/run_tests.py --suite unit --no-coverage --jobs 1 --report-dir <owned-report> -- src/test/unit/python/tools/ci/psycopg_pg_config_custody.unit.test.py src/test/unit/python/tools/ci2a_psycopg_bootstrap.unit.test.py src/test/unit/python/repomap_test_support/python_payload_probes.unit.test.py`
  - Containerized integration selector:
    `python3 tools/run_tests.py --suite int --no-coverage --jobs 1 --report-dir <owned-report> --pg-container-port 55433 -- src/test/int/python/tools/ci/psycopg_pg_config_custody.int.test.py src/test/int/python/repomap_kg/runtime/python_payload_contract.int.test.py`
  - Scoped static verification: container-isolated offline scoped static profile over the
    phase-touched Python files, retention inventory, ratchets, type ownership, and CI topology.
  - Complete local `unit`, `int`, `smoke`, `staging`, `system`, and combined suites and local
    Python coverage measurement remain intentionally unselected. Actual execution receipts and
    results belong to the generated phase Exit record, commit message, and local report.
- [`tools/ci/python_retention_inventory.json`](python_retention_inventory.json) additively
  registers the `product6.navigation47.ci64repair1.test_owners` and
  `product6.navigation47.ci64repair1.test_support` cohorts and their three new tracked Python
  files while preserving every existing cohort and file entry.
- The exact native AMD64 Python payload exclusion (and native AMD64 D12 image/platform admission)
  remains **held** (neither admitted nor added to `PYTHON_PAYLOAD_EXCLUSIONS`); negative-evidence
  acquisition does not admit a platform, build, or exclusion.
- `d12_hosted_candidate.json` (`libpq: null`, empty dynamic package map,
  `application_builds_maximum: 0`, `application_builds_used: 0`), P3/incumbent comparisons,
  `main-system-gate`, and `preview0.0.3` remain held pending hosted qualification.
