# ADR 0125: CI99 observer source-freeze namespace successor and remaining cutover consumer repair

## Status

Accepted before implementation, 2026-10-30, for `REPOMAP-CI99-REPAIR1`.

## Date

2026-10-30

## Context

ADR 0046 and the `COV5K-R2` successor observer protocol froze eleven observer and
readback tool files under `tools/` in
`src/test/support/python/repomap_test_support/test_cov5k_r2_observer_protocol.py`.
CI98 attempt 1 qualified staging `6d818ad6d43d38d47c64b8c474c2b64b853f631a` with
those exact predecessor byte hashes passing.

ADR 0123 (`REPOMAP-CLOE-CUTOVER1`) moved the canonical Python package namespace
from `repomap_kg` to `common_lore_index`, updated the distribution identity to
`common-lore-index`, set the preferred CLI to `cloe`, and moved packaged data
files to `share/common-lore-index`. Six of the eleven frozen observer tool files
imported `repomap_kg` and were mechanically rewritten to `common_lore_index`,
while `FROZEN_SUCCESSOR_SOURCE_DIGESTS` in `test_cov5k_r2_observer_protocol.py`
still bound the pre-namespace `6d818ad` SHA-256 digests.

In CI99 attempt 1 (run `41137663565`, head `3c326f254aaffcdc382434f7a9cd86429fbb0b6c`,
merge `fc464cfbd000e47ad736918280adee3dad3b2108`), `source-and-export-policy`,
`pre-review-static`, `main-system-gate`, `d12-native-amd64`,
`sbom-and-vulnerability-scan`, and both `codeql-analysis` jobs passed, and
observed coverage met the hard gates plus two-point margins (unit 88.1% line /
87.7% branch; measured integration 90.1% line / 82.2% branch). However,
`unit-tests` failed with 27 failures and 29 setup errors, and
`staging-integration-gate` failed with 7 integration failures across five
closed failure families:

1. **F1 (Observer successor source freeze — 16 unit failures, 29 unit errors, 2 integration failures):**
   `verify_source_freeze` rejected the six namespace-projected observer tool
   files in `test_cov5k_r2_observer_protocol.unit.test.py` (1 failure),
   `test_cov5k_r2_fix1_model.unit.test.py` (15 failures), the three other
   `test_cov5k_r2_fix1_*` unit owners (29 fixture setup errors via
   `closed_source_manifest_digest`), and the two `test_cov5g_r1_*` storage
   integration owners (2 failures).
2. **F2 (CLI `--version` and `identity --json` consumer expectations — 5 unit failures, 4 integration failures):**
   `sqlite_local_import_boundary.unit.test.py` (1 failure),
   `cloe_ownership.unit.test.py` (1 failure), `cli.unit.test.py` (2 failures),
   `pr26_staging_qual6_fixture_seams.unit.test.py` (1 failure),
   `server_entrypoint.int.test.py` (3 failures), and `cloe_ownership.int.test.py`
   (1 failure) still asserted pre-cutover `repomap-kg` version or identity
   values instead of `cloe 0.0.3`, `Common Lore Index`, `common-lore-index`, and
   `cloe`.
3. **F3 (Installed migration data-files prefix — 4 unit failures, 1 integration failure):**
   `coordinator_migration_packaging.unit.test.py` (4 failures) and
   `cloe_ownership.int.test.py` (1 failure) referenced `share/repomap-kg`
   instead of `share/common-lore-index`.
4. **F4 (Retained test-tree module path derivation — 1 unit failure):**
   `extractors/languages/python.unit.test.py` (1 failure) had its expected
   output module names rewritten to `common_lore_index.*` while passing physical
   `src/test/{unit,int}/python/repomap_kg/...` input paths to the pure path
   mapper `importable_module_name`.
5. **F5 (Fixture-anchored pointer extraction literal — 1 unit failure):**
   `server/server_memory_bridge.unit.test.py` (1 failure) asserted
   `./src/main/python/common_lore_index/mcp_server.py` against the immutable
   historical fixture `src/test/fixtures/server_memory/paths/memory.jsonl` whose
   literal payload is `./src/main/python/repomap_kg/mcp_server.py`.

## Decision

### 1. Observer source-freeze namespace successor (F1)

In `src/test/support/python/repomap_test_support/test_cov5k_r2_observer_protocol.py`:

- Record `PRE_NAMESPACE_SOURCE_COMMIT = "6d818ad6d43d38d47c64b8c474c2b64b853f631a"`.
- Preserve the existing eleven-entry pre-namespace tuple byte-for-byte as
  `PRE_NAMESPACE_SUCCESSOR_SOURCE_DIGESTS` and export its canonical digest
  `PRE_NAMESPACE_SOURCE_MANIFEST_DIGEST` (`a461e7eb6fc5001059eacd397fb39b5952466b9012d40606a7432fa5e62397e7`).
- Define `FROZEN_SUCCESSOR_SOURCE_DIGESTS` with the same eleven paths in the
  same order, updating only the six files whose `repomap_kg` import tokens
  changed under ADR 0123 and keeping the five token-free files at their
  unchanged SHA-256 digests:

| Relative path | `6d818ad` predecessor SHA-256 | Current projected SHA-256 | Changed |
|---|---|---|---|
| `tools/scale15_actual_path_readback.py` | `2a67a8ec2eee4fab3de049a489976351a7b7b328bf935cc1beba62b04a3ff606` | `0d672b01f8ea519968b6dd9fc7e9bc3e971312500ace89898a5c4cc64102b417` | Yes (5 tokens) |
| `tools/scale15_readback_records.py` | `52b2aaff5dc51a0090f2d2ad19bf2cc8edebb125c87bf87bf2b2580f4ae39e6c` | `abc58ca1d5477dee9ef75c9faf7e7ccc05a5b639d921c03974bce735ca20c754` | Yes (4 tokens) |
| `tools/scale15_readback_contracts.py` | `25a278749c397eb59b3b8cdf0c1dccebcf3481538e487d628248619e1290fdd4` | `82d926d3041bd74f5c094240c2ba759973b45bbdca67ae6144dfe95ceb383056` | Yes (2 tokens) |
| `tools/scale28_backend_observer_session.py` | `fe387621d9fa9b1f5c227a31921418622b6bacc11f84a80951205ff6493a667b` | `5a82b9053cf9305cddb927c904f7571079a7ba875ffefb238861f0016f380fce` | Yes (2 tokens) |
| `tools/scale28_backend_observer_session_values.py` | `8dd549a0458cec893c1e1aa9a45b62605d869ed2dff4ccdea4dffe50bd6293a0` | `8dd549a0458cec893c1e1aa9a45b62605d869ed2dff4ccdea4dffe50bd6293a0` | No (0 tokens) |
| `tools/scale28_backend_observer_session_startup.py` | `116da58e7c83927c6578fef562a8de83d660b3451ec41e56e4ac79855809bb1c` | `116da58e7c83927c6578fef562a8de83d660b3451ec41e56e4ac79855809bb1c` | No (0 tokens) |
| `tools/scale28_backend_observer_session_cleanup.py` | `eb6e3d79bec896245a606d39e6e3346281b6271d7e966433c14f656a34b65fc6` | `eb6e3d79bec896245a606d39e6e3346281b6271d7e966433c14f656a34b65fc6` | No (0 tokens) |
| `tools/scale28_observer_deadlines.py` | `c8443c8ce449d1dbcb00a0dbb93e33b8defbcc1cab3d780c0058c35e8c35a858` | `c8443c8ce449d1dbcb00a0dbb93e33b8defbcc1cab3d780c0058c35e8c35a858` | No (0 tokens) |
| `tools/scale14_backend_monitor.py` | `2cb531278eb69ae32568f2cc3983ee5535868d5eb1c194227ec0cf50f551811c` | `7b07792ae4b1998dc29a7657932b90183b777556e2f9e3fa8b69b8bd3bbed02a` | Yes (1 token) |
| `tools/scale14_backend_monitor_events.py` | `6fd2c064da8ae35a33e23861dbda757e57f019086eb6cf5977881b42de4c09f9` | `c810f5b6a77f8956f1a0693c20b33289f39724bd6cff1537a7d0dbc9b4340f3a` | Yes (2 tokens) |
| `tools/scale14_backend_monitor_reporting.py` | `cbd10fb98e42aee0d13c66728e969d8462326795c8f99668024fdd92b0ca05ed` | `cbd10fb98e42aee0d13c66728e969d8462326795c8f99668024fdd92b0ca05ed` | No (0 tokens) |

- Bind `SOURCE_MANIFEST_DIGEST` (`b77f0fb41577375b2b9179f91ac1fe27676f03aea61b1c2ce48801c97dd60bb2`)
  to `FROZEN_SUCCESSOR_SOURCE_DIGESTS`.
- Provenance is established by exact byte projection from immutable commit
  `6d818ad6d43d38d47c64b8c474c2b64b853f631a` under both whole-identifier regex
  `(?<![A-Za-z0-9_])repomap_kg(?![A-Za-z0-9_])` -> `common_lore_index` and
  `tools/ci/retained_python_namespace_contract.py`'s `_TEXT_ROOT` mapping
  `(?:(?<=src/main/python/)|(?<![\w./\\-]))repomap_kg(?![\w-])` ->
  `common_lore_index`, with zero `common_lore_index` tokens in the `6d818ad`
  blobs and exact inverse projection back to the `6d818ad` bytes.
- Keep `verify_source_freeze` strictly comparing observed file SHA-256 digests
  against `FROZEN_SUCCESSOR_SOURCE_DIGESTS`. No normalize-on-read, runtime
  projection, fallback to predecessor hashes, or exception suppression is
  permitted.
- Extend `test_cov5k_r2_observer_protocol.unit.test.py` to pin the literal hex
  digests of both `PRE_NAMESPACE_SOURCE_MANIFEST_DIGEST` and
  `SOURCE_MANIFEST_DIGEST`, verify the bidirectional whole-identifier projection
  between `PRE_NAMESPACE_SUCCESSOR_SOURCE_DIGESTS` and current disk bytes without
  requiring Git history in CI, require a clean-tree pass before every negative,
  and refuse current source mutations (all 11 files), substituted predecessor
  bytes (all 6 changed files), wrong expected hashes (predecessor hash on the 6
  changed entries and single-hex-digit flip on all 11 entries), wrong paths
  (swapped path order and missing path), and semantic edits (same-length import
  target edit, deadline constant edit, and partial namespace projection).

### 2. Remaining consumer test repairs (F2–F5) and retention witness

- **F2 (CLI `--version` and `identity --json` consumer expectations):** Update
  stale `repomap-kg` version prefix and project identity assertions in
  `sqlite_local_import_boundary.unit.test.py`, `cloe_ownership.unit.test.py`,
  `cli.unit.test.py`, `pr26_staging_qual6_fixture_seams.unit.test.py`,
  `server_entrypoint.int.test.py`, and `cloe_ownership.int.test.py` to expect
  `cloe 0.0.3` (`^cloe \d+\.\d+\.\d+$`), `name="Common Lore Index"`,
  `distribution="common-lore-index"`, and `cli="cloe"`, keeping the six-key set,
  `package`, `license`, `database`, and MCP `serverInfo.name == "repomap-kg"`
  values unchanged.
- **F3 (Installed migration data-files prefix):** Update
  `coordinator_migration_packaging.unit.test.py` and
  `cloe_ownership.int.test.py` from `share/repomap-kg` to
  `share/common-lore-index`. Retain the function name
  `test_real_catalog_readback_in_simulated_installed_layout_preserves_frozen_prefix`
  for node-ID stability, and keep the legacy non-fallback negative at
  `cloe_ownership.unit.test.py:44` and
  `src/test/fixtures/cloe/migration-continuity-v1.json` unchanged.
- **F4 (Retained test-tree module path derivation):** Restore
  `"repomap_kg.test_cli.unit.test"` and `"repomap_kg.test_storage.int.test"` in
  `extractors/languages/python.unit.test.py` (matching the physical
  `src/test/{unit,int}/python/repomap_kg/...` input paths), identical to its
  `6d818ad` expectation.
- **F5 (Fixture-anchored pointer extraction literal):** Restore
  `"./src/main/python/repomap_kg/mcp_server.py"` in
  `server/server_memory_bridge.unit.test.py` (matching the immutable fixture
  `src/test/fixtures/server_memory/paths/memory.jsonl`), identical to its
  `6d818ad` expectation.
- **Dynamic retention witness re-attestation:** Updating
  `src/test/unit/python/repomap_test_support/cli.unit.test.py` changes its
  `test_sha256` for the active dynamic boundary record of
  `src/test/support/python/repomap_test_support/cli.py::run_module_entrypoint`.
  Because `tools/ci/python_retention_dynamic_history.py` requires both
  `owner_sha256` and `test_sha256` to change in a successor record, append the
  no-op re-attestation comment `# v0.0.3 CI99 dynamic target re-attestation.` to
  `src/test/support/python/repomap_test_support/cli.py` (following the precedent
  at lines 63–64) and append one successor record at the end of
  `dynamic_boundaries` in `tools/ci/python_retention_inventory.json` superseding
  `cloe.cutover1.cloe.ownership1.navigation40.ci57.preview003.v002.revise39.cli.py.run_module_entrypoint`,
  leaving all historical inventory entries byte-for-byte unchanged.

## Scope and Non-Scope

- **In scope:** `test_cov5k_r2_observer_protocol.py`,
  `test_cov5k_r2_observer_protocol.unit.test.py`, the seven other failing unit
  / integration test files in F2–F5, the no-op re-attestation trailer in
  `src/test/support/python/repomap_test_support/cli.py`, one appended active
  dynamic boundary successor record in `tools/ci/python_retention_inventory.json`,
  this ADR, and the phase exit `tools/ci/cloe-ci99repair1-exit.md`.
- **Out of scope:** Product source under `src/main/python/`, the eleven
  production observer tools under `tools/`, historical source-freeze records,
  namespace/scope/export ledgers, ratchet baselines, suppression allowances,
  dependencies/locks/pins, immutable fixtures, CI workflows, and CI100
  publication/grant binding (owned by the parent).

## Consequences and Invalidation Conditions

- `verify_source_freeze` enforces the exact post-cutover SHA-256 digests of the
  eleven observer tools while retaining the complete `6d818ad` predecessor tuple
  and digest for non-Git provenance verification in unit tests.
- This ADR would be invalidated if any of the eleven observer tool files
  diverged from the exact whole-identifier `repomap_kg` -> `common_lore_index`
  projection of `6d818ad`, if an unaffected tool file changed bytes, if a
  historical inventory prefix required modification, or if hosted CI100
  exposed a product contract defect outside F1–F5.
