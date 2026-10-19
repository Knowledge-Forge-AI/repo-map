# REPOMAP-PRODUCT6-NAVIGATION30-OPTIONAL-RUNTIME-PROJ1 Exit

This supporting public-projection record documents the bounded optional-runtime
test and runner projection for the already-projected `NAVIGATION27` semantic
candidate, seed, and embedding-profile surfaces. It is not evidence of review
approval, publication, hosted execution, or release qualification; those events
require separate evidence bound to the candidate commit and workflow run.

## Scope and Projected Surfaces

- **Projected optional-runtime test owners and support (14 added, 6 replaced)**:
  - Integration owners (3 added):
    `src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py`,
    `src/test/int/python/repomap_kg/storage/semantic_seed.int.test.py`, and
    `src/test/int/python/repomap_kg/storage/embedding_profiles.int.test.py`.
  - Test support and profile helpers (3 added, 2 replaced):
    `src/test/support/python/repomap_test_support/pgvector_profile.py`,
    `src/test/support/python/repomap_test_support/semantic_candidate_restore.py`,
    `src/test/support/python/repomap_test_support/semantic_seed_publication.py`,
    `src/test/support/python/repomap_test_support/postgres_container.py`, and
    `src/test/support/python/repomap_test_support/postgres_container_config.py`.
  - Unit owners (3 added, 1 replaced):
    `src/test/unit/python/repomap_kg/storage/semantic_seed_publication.unit.test.py`,
    `src/test/unit/python/tools/pgvector_profile.unit.test.py`,
    `src/test/unit/python/tools/pgvector_materializer.unit.test.py`, and
    `src/test/unit/python/repomap_test_support/postgres_container_structure.unit.test.py`.
  - Runner and pinned source manifest (5 added, 3 replaced):
    `tools/pgvector_test_source.json`,
    `tools/runner_pgvector_profile.py`,
    `tools/runner_sandbox.py`,
    `tools/runner_sandbox_assets.py`,
    `tools/runner_command.py`,
    `tools/runner_arguments.py`,
    `tools/runner_unit_environment.py`, and
    `tools/test_sandbox_entrypoint.py`.
- **Public-variant updates (4 paths)**:
  - `tools/ci/python_retention_inventory.json`
  - `docs/adr/2026/10/0077-publication-bound-pgvector-candidates.md`
  - `docs/contrib/skills/repo-map-testing-standards/SKILL.md`
  - `tools/ci/nav30-optional-runtime-exit.md`
- **Product source invariance**: Zero `src/main/` files, schema migrations,
  package versions (`0.0.2`), lockfiles, workflows, coverage floors, or debt
  ceilings are modified.

## Static Retention Admission and Governance Boundaries

- Thirteen new non-product Python files (`files`: `2551 -> 2564`) and three new
  cohorts (`cohorts`: `1421 -> 1424`) are admitted into
  `tools/ci/python_retention_inventory.json` under static AST, Ruff, mypy, and
  file-length proof:
  - `navigation30-optional-runtime.test_owners` (6 files; `test_owners`)
  - `navigation30-optional-runtime.test_support` (3 files; `test_support`)
  - `navigation30-optional-runtime.tools` (4 files; `tools`)
- Whereas the initial phase plan hypothesized zero cross-cohort import cycles,
  actual AST analysis across all `2,564` inventory paths and `1,424` cohorts shows
  that `navigation30-optional-runtime.test_owners` is a standalone cohort
  (`atomic_group_id: null`), while the other two new cohorts form same-root,
  same-profile strongly connected components (SCCs) with incumbent clean cohorts:
  - `navigation30-optional-runtime.test_support` forms a 4-cohort
    `clean_test_support` atomic group
    (`scc-v1-e6813f458abbe82c90442410900c9140dd35c9bf5aaa9efe367cf8904401a0cd`)
    with `src-test-support-python-repomap_test_support.postgres_container`,
    `src-test-support-python-repomap_test_support.postgres_harness`, and
    `src-test-support-python-repomap_test_support.postgres_logical_backup`.
  - `navigation30-optional-runtime.tools` forms a 2-cohort `clean_tooling`
    atomic group
    (`scc-v1-85cbe5c59cf184be778234f930fe61b84d67b890987adc93dc35053fb8214bee`)
    with `tools.test_sandbox`.
  The unchanged public `tools/ci/python_retention_inventory.py --check`
  (`evaluate_cohorts` / `build_atomic_groups`) natively evaluates and admits both
  same-profile atomic groups with `status: "passed"`,
  `effective_enforcement: true`, and zero root-mismatch, mixed-profile, or
  dependency blockers, preserving all `1,421` incumbent cohorts and `2,551`
  incumbent file records unchanged.
- All existing authority manifests (`python_type_ownership.json`,
  `retained_python_ratchets.json`, `retained_python_projection_proofs.json`) and
  debt ceilings (`Ruff 1906/1906`, `mypy 159/159`, `file length 62/62`,
  `migration imports 0/0`) remain unchanged.

## Scoped Verification Selectors and Results

- **U1 (4 unit files — new and replaced unit owners)**:
  ```sh
  python3 tools/run_tests.py --suite unit --no-coverage -- \
    src/test/unit/python/tools/pgvector_profile.unit.test.py \
    src/test/unit/python/tools/pgvector_materializer.unit.test.py \
    src/test/unit/python/repomap_test_support/postgres_container_structure.unit.test.py \
    src/test/unit/python/repomap_kg/storage/semantic_seed_publication.unit.test.py
  ```
  Result: `94 passed` (`94` collected, `0` deselected, `0` failed, `0` skipped) in `U1`, exit `0`.
- **U2 (26 unit files — default-core compatibility, replaced-module consumers, and guidance owners)**:
  ```sh
  python3 tools/run_tests.py --suite unit --no-coverage -- \
    src/test/unit/python/repomap_test_support/postgres_harness.unit.test.py \
    src/test/unit/python/repomap_test_support/postgres_harness_ipc.unit.test.py \
    src/test/unit/python/repomap_test_support/test_cov5k_r2_safety3_docker_commands.unit.test.py \
    src/test/unit/python/repomap_test_support/test_scratch_cleanup_lifecycle.unit.test.py \
    src/test/unit/python/repomap_test_support/unit_purity.unit.test.py \
    src/test/unit/python/repomap_kg/ops/operational_json_readback_failures_container.unit.test.py \
    src/test/unit/python/tools/test_sandbox_workspace.unit.test.py \
    src/test/unit/python/tools/test_sandbox.unit.test.py \
    src/test/unit/python/tools/test_sandbox_image_lifecycle.unit.test.py \
    src/test/unit/python/tools/test_iso1_runner.unit.test.py \
    src/test/unit/python/tools/test_report_runner.unit.test.py \
    src/test/unit/python/tools/test_report_coverage_selection.unit.test.py \
    src/test/unit/python/tools/test_runner_safety1.unit.test.py \
    src/test/unit/python/tools/test_runner_safety3_build_policy.unit.test.py \
    src/test/unit/python/tools/test_runner_coverage_combine.unit.test.py \
    src/test/unit/python/tools/scale14_postgres_storage.unit.test.py \
    src/test/unit/python/tools/smoke/host_mcp_native.unit.test.py \
    src/test/unit/python/tools/smoke/host_mcp_native_kit.unit.test.py \
    src/test/unit/python/tools/smoke/host_mcp_native_launch.unit.test.py \
    src/test/unit/python/tools/smoke/host_mcp_native_status.unit.test.py \
    src/test/unit/python/tools/staging_execution.unit.test.py \
    src/test/unit/python/tools/staging_discovery.unit.test.py \
    src/test/unit/python/repomap_kg/project_guidance/skill_architecture.unit.test.py \
    src/test/unit/python/repomap_kg/storage/embedding_profiles.unit.test.py \
    src/test/unit/python/repomap_kg/mcp_server/similar_nodes.unit.test.py \
    src/test/unit/python/repomap_kg/mcp_server/embedding_profiles.unit.test.py
  ```
  Result: `377 passed` (`377` collected, `0` deselected, `0` failed, `0` skipped) in `U2`, exit `0`.
- **I1 (3 integration files under default `core` profile)**:
  ```sh
  python3 tools/run_tests.py --suite int --no-coverage --pg-container-port 55433 -- \
    src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py \
    src/test/int/python/repomap_kg/storage/semantic_seed.int.test.py \
    src/test/int/python/repomap_kg/storage/embedding_profiles.int.test.py
  ```
  Result: `1 passed` (`test_absent_extension_preserves_ordinary_publication_and_reads`), `3 deselected`, `0 failed`, `0 skipped`, exit `0`.
- **I2 (10 integration selectors, 36 nodes — core baseline, nested direct-pytest, and heavy `psql_scalar` / container consumers)**:
  ```sh
  python3 tools/run_tests.py --suite int --no-coverage --pg-container-port 55433 -- \
    "src/test/int/python/repomap_kg/storage/mcp_ops_live/read_only_tools.int.test.py::StorageMcpReadOnlyToolsIntegrationTests::test_mcp_read_only_tools_read_python_canonical_graph" \
    src/test/int/python/repomap_kg/cli/sqlite_local_loop.int.test.py::test_sqlite_local_loop_indexes_and_serves_database_tools_without_postgres \
    src/test/int/python/repomap_kg/cli/mcp_host_native_read_store.int.test.py::test_host_native_stdio_mcp_reads_seam_tools_without_docker_or_sources \
    src/test/int/python/repomap_kg/cli/mcp_host_native_domain_read_store.int.test.py::test_host_native_stdio_mcp_reads_twelve_domain_tools_without_docker_or_sources \
    src/test/int/python/repomap_kg/cli/mcp_host_native_runner.int.test.py::test_runner_exercises_fixture_and_stdio_mechanics_in_the_linux_harness \
    src/test/int/python/repomap_test_support/scale28_diag1_fix2_direct_pytest.int.test.py \
    src/test/int/python/repomap_kg/storage/graph_identity_readback.int.test.py \
    src/test/int/python/repomap_kg/storage/scale5_publication_transactions.int.test.py \
    src/test/int/python/repomap_kg/storage/scale1_staging_migration.int.test.py \
    src/test/int/python/repomap_kg/storage/migrations_ops_status.int.test.py
  ```
  Result: `36 passed`, `0 failed`, `0 skipped`, exit `0`.
- **P1 (3 `requires_pgvector` integration nodes under `--pg-test-profile pgvector`)**:
  ```sh
  python3 tools/run_tests.py --suite int --no-coverage --pg-test-profile pgvector \
    --pg-container-port 55433 -- \
    src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py::test_selected_candidate_capability_boundary \
    src/test/int/python/repomap_kg/storage/semantic_seed.int.test.py::test_seed_public_entry_boundary \
    src/test/int/python/repomap_kg/storage/embedding_profiles.int.test.py::test_profile_discovery_publication_and_stdio_boundary
  ```
  Result: `3 passed`, `0 deselected`, `0 failed`, `0 skipped`, exit `0`, with
  `repomap-pgvector-setup-v1` stage events and the final
  `"pgvector_setup": "materialized"` receipt confirming source verification
  (`cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85`, `133025`
  bytes), ABI `16` (`PostgreSQL 16.14`), `runtime_smoke` stdout `16|0.8.7|0|1`,
  and disposable builder/smoke container cleanup (`removed: true`,
  `verified: true`).
- **N1 (Cheap admission refusal without `--no-coverage`)**:
  ```sh
  python3 tools/run_tests.py --suite int --pg-test-profile pgvector -- \
    src/test/int/python/repomap_kg/storage/semantic_candidates.int.test.py::test_selected_candidate_capability_boundary
  ```
  Result: non-zero exit (`2`) from host-side option validation
  (`validate_runner_options` / `validate_sandbox_profile_options`), refusing
  missing `--no-coverage` with
  `ERROR: --pg-test-profile pgvector requires scoped int --no-coverage` before
  starting any container (while non-empty forwarded selector enforcement runs
  inside the outer sandbox in `tools/runner_sandbox.py` prior to pgvector image
  materialization).
- **Intentionally unselected complete suites (scoped-testing policy, no override)**:
  complete `unit`, complete `int`, `smoke`, `staging`, `system`, and retired `combined`.

## Claim Limits and Hosted CI Classification

- **Claim limits**: `P1` proves synthetic mechanics only (exact cosine ordering,
  publication/stale/foreign/profile/dimension refusals, `SELECT`-only reader
  role enforcement, disposable same-cluster logical `pg_dump`/restore under a
  lifecycle superuser role after pre-installing `vector` `0.8.7` and rewriting
  `CREATE EXTENSION` to `IF NOT EXISTS`—not a least-privilege or as-is D9
  production restore certification—`RESTRICT` teardown, and stdio MCP
  read/refusal boundaries with zero canonical table mutations). Retrieval
  utility remains `utility_not_measured`, ADR 0051 D15 production extension
  admission remains refused, and ADR 0071 roadmap step 6 remains in progress.
- **Pre-push hosted CI classification**: `NOT_REQUESTED_CONSERVATION`.
  Historical `repomap-release-qualification` Run `49` (`39268848295`, attempt
  `1`, `8/8` jobs passed, tested merge
  `ab071dc2560f02afda851ad8f65ee3ce373e0b98`,
  <https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/39268848295>)
  applies only to parent public `staging` commit
  `76691373abf67cb44c5d05bee08a4bbbf308661c` (integration branch coverage
  `15002 / 18722 = 80.1303%`, `24` arcs above the `80.00%` floor) and is not
  claimed as post-change hosted qualification for this candidate.
