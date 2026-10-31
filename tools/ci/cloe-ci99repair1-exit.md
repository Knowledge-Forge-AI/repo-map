# REPOMAP-CI99-REPAIR1 Exit

- **Date:** 2026-10-30
- **Phase ID:** `REPOMAP-CI99-REPAIR1`
- **Status:** Local implementation and scoped verification complete; hosted qualification `NOT ACCEPTED` pending single-attempt `CI100` staging campaign
- **Governing ADRs:** ADR 0046, ADR 0123, ADR 0124, ADR 0125

## Summary

`REPOMAP-CI99-REPAIR1` repairs the five remaining coordinated-cutover (`REPOMAP-CLOE-CUTOVER1` / ADR 0123) consumer failure families exposed by staging qualification run `CI99` (`run_id`: `41137663565`, head `3c326f254aaffcdc382434f7a9cd86429fbb0b6c`, merge `fc464cfbd000e47ad736918280adee3dad3b2108`), where `unit-tests` failed with 27 failures and 29 errors and `staging-integration-gate` failed with 7 failures.

No product source under `src/main/python/` and no observer production tools under `tools/` were modified. All repairs are confined to ADR 0125, observer protocol test support, unit and integration test consumers, dynamic retention boundary re-attestation, and phase exit documentation.

## Failure Families Remediated

1. **F1 — Observer source-freeze pre-namespace hash pin (`16` unit failures, `29` unit errors, `2` integration failures):**
   - Recorded [ADR 0125](../../docs/adr/2026/10/0125-ci99-observer-source-freeze-namespace-successor.md) establishing the post-ADR-0123 `FROZEN_SUCCESSOR_SOURCE_DIGESTS` tuple and `SOURCE_MANIFEST_DIGEST` (`b77f0fb41577375b2b9179f91ac1fe27676f03aea61b1c2ce48801c97dd60bb2`) while preserving the pre-namespace baseline (`PRE_NAMESPACE_SOURCE_COMMIT = "6d818ad6d43d38d47c64b8c474c2b64b853f631a"`, `PRE_NAMESPACE_SUCCESSOR_SOURCE_DIGESTS`, `PRE_NAMESPACE_SOURCE_MANIFEST_DIGEST = "a461e7eb6fc5001059eacd397fb39b5952466b9012d40606a7432fa5e62397e7"`).
   - Updated `src/test/support/python/repomap_test_support/test_cov5k_r2_observer_protocol.py` and expanded `src/test/unit/python/repomap_test_support/test_cov5k_r2_observer_protocol.unit.test.py` with bidirectional whole-identifier projection provenance checks and negative drift/mutation/order/semantic-edit tests across all 11 observer files.
2. **F2 — CLI `--version` and `identity --json` consumer expectations (`5` unit failures, `4` integration failures):**
   - Updated `src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py`, `src/test/unit/python/repomap_kg/runtime/cloe_ownership.unit.test.py`, `src/test/unit/python/repomap_test_support/cli.unit.test.py`, `src/test/unit/python/repomap_test_support/pr26_staging_qual6_fixture_seams.unit.test.py`, `src/test/int/python/repomap_kg/cli/server_entrypoint.int.test.py`, and `src/test/int/python/repomap_kg/runtime/cloe_ownership.int.test.py` to expect `cloe 0.0.3`, `"name": "Common Lore Index"`, `"distribution": "common-lore-index"`, and `"cli": "cloe"`, while preserving intentional compatibility assertions (`serverInfo.name == "repomap-kg"` and negative fallback checks).
3. **F3 — Installed migration data-files prefix (`4` unit failures, `1` integration failure):**
   - Updated `src/test/unit/python/repomap_kg/runtime/coordinator_migration_packaging.unit.test.py` and `src/test/int/python/repomap_kg/runtime/cloe_ownership.int.test.py` to use `share/common-lore-index`.
4. **F4 — Retained test-tree module path derivation (`1` unit failure):**
   - Updated `src/test/unit/python/repomap_kg/extractors/languages/python.unit.test.py` to expect `repomap_kg.test_cli.unit.test` and `repomap_kg.test_storage.int.test` for paths under `src/test/{unit,int}/python/repomap_kg/`.
5. **F5 — Fixture-anchored pointer extraction literal (`1` unit failure):**
   - Updated `src/test/unit/python/repomap_kg/server/server_memory_bridge.unit.test.py` to assert `./src/main/python/repomap_kg/mcp_server.py` matching the immutable fixture `src/test/fixtures/server_memory/paths/memory.jsonl`.

## Dynamic Retention Boundary Re-Attestation

- Appended `# v0.0.3 CI99 dynamic target re-attestation.` to `src/test/support/python/repomap_test_support/cli.py` (`owner_sha256`: `200b7ef707c799d920726ca4da9ba72989ce9af94e65b894e0c86870d8c45031`).
- Appended active record `cloe.ci99repair1.cloe.cutover1.cloe.ownership1.navigation40.ci57.preview003.v002.revise39.cli.py.run_module_entrypoint` at the end of `dynamic_boundaries` in `tools/ci/python_retention_inventory.json`, superseding `cloe.cutover1.cloe.ownership1.navigation40.ci57.preview003.v002.revise39.cli.py.run_module_entrypoint` and binding `src/test/unit/python/repomap_test_support/cli.unit.test.py` (`test_sha256`: `62620ebb03736f35ed4143cb65657b3bb53e9eb0cb9ef8d101b3f62f832bde5b`).

## Verification

### Scoped Unit Tests (`--no-coverage`)

- **Selector (`12` files):**
  `src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py`,
  `src/test/unit/python/repomap_kg/extractors/languages/python.unit.test.py`,
  `src/test/unit/python/repomap_kg/runtime/cloe_ownership.unit.test.py`,
  `src/test/unit/python/repomap_kg/runtime/coordinator_migration_packaging.unit.test.py`,
  `src/test/unit/python/repomap_kg/server/server_memory_bridge.unit.test.py`,
  `src/test/unit/python/repomap_test_support/cli.unit.test.py`,
  `src/test/unit/python/repomap_test_support/pr26_staging_qual6_fixture_seams.unit.test.py`,
  `src/test/unit/python/repomap_test_support/test_cov5k_r2_fix1_anti_inflation.unit.test.py`,
  `src/test/unit/python/repomap_test_support/test_cov5k_r2_fix1_anti_inflation_parts/execution_mutations.unit.test.py`,
  `src/test/unit/python/repomap_test_support/test_cov5k_r2_fix1_model.unit.test.py`,
  `src/test/unit/python/repomap_test_support/test_cov5k_r2_fix1_p0_reproductions.unit.test.py`,
  `src/test/unit/python/repomap_test_support/test_cov5k_r2_observer_protocol.unit.test.py`
- **RED baseline (`parent-ci99-red-u`):** exited `1` (`27 failed, 80 passed, 29 errors in 9.41s`), reproducing all 56 `CI99` unit failures and errors.
- **GREEN verification (`parent-ci99-green-u2`):** exited `0` (`175 passed in 24.55s`), plus Go helper unit checks (`4` packages passed).

### Scoped Containerized Integration Tests (`--no-coverage`)

- **Selector (`4` files, `-s`, using the existing diagnostic image override recorded privately):**
  `src/test/int/python/repomap_kg/cli/server_entrypoint.int.test.py`,
  `src/test/int/python/repomap_kg/runtime/cloe_ownership.int.test.py`,
  `src/test/int/python/repomap_kg/storage/test_cov5g_r1_configured_characterization.int.test.py`,
  `src/test/int/python/repomap_kg/storage/test_cov5g_r1_process_containment.int.test.py`
- **RED baseline (`parent-ci99-red-i`):** exited `1` (`7 failed, 3 passed in 4.76s`), reproducing all 7 `CI99` staging integration failures.
- **GREEN verification (`parent-ci99-green-i`):** exited `0` (`10 passed in 355.50s`), with `0` new application builds, `0` new SDK builds, and `0` Docker image or volume residue.

### Static Enforcement and Hygiene

- `tools/ci/python_retention_inventory.py --check --json --repo-root /workspace` (existing pinned sealed SDK; exact local Engine identity retained privately): passed (`status: passed`, `classification: passed`, `enforcement_complete: true`, `cohort_regressions: 0`).
- `tools/ci/ci_topology.py`, `tools/ci/check_file_lengths.py`, `tools/ci/scanner_suppressions.py`, `tools/ci/public_export_policy.py --expected-version 0.0.3`, and `compileall` on all changed Python files: passed (`exit: 0`).
- `betterleaks` (`--config=tools/ci/betterleaks.toml --redact=100`): passed (`finding_count: 0`).
- `git diff --check` and `git diff --cached --check`: passed (`0` findings).

### Complete Suites Intentionally Unselected

Under the repository scoped-testing policy (`repo-map-testing-standards`), complete unit, complete integration, smoke, staging, system, and combined suites were intentionally not run locally. Hosted staging qualification remains `NOT ACCEPTED` until `CI100` completes green.

## Parent CI100 publication binding

[ADR 0126](../../docs/adr/2026/10/0126-ci99-remediation-and-single-ci100-campaign.md)
records the operator-requested retry as one fresh CI100 attempt-1 campaign and
one seventeenth native AMD application start. All sixteen observed earlier
starts remain spent. There is no eighteenth start, duplicate trigger or
automatic retry. The parent owns the final source/grant verification, independent
review, exact-commit report and one ordinary staging synchronize push.

The source-dispatch static diagnostics exceeded their internal allocation by
one execution. That extra read-only diagnostic is retained and dispositioned;
final acceptance requires a separate parent-controlled retained static check.
The observer unit owner's final compacted and annotated layout is also selected
for fresh parent unit verification alongside the grant/proof owners. Exact final
commands, counts and candidate hashes are recorded in the commit and local report.
No complete local suite or project coverage is admitted by this binding.
