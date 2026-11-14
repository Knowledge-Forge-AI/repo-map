# CLOE-REBRAND-PREVIEW004 Exit

Source repair and rebranding are locally verified; current hosted qualification
is pending. This is a source-preview checkpoint, not full roadmap, image,
platform, deployment or package-manager acceptance.

## Scope and result

- Complete current Common Lore Index names in root package metadata, current
  contribution/operator guidance, CLI headings and MCP identity/descriptions.
  Source/pyproject/root editable lock agree on 0.0.4; external lock entries stay
  exact. Tool names, request/result structure and read-only behavior stay fixed.
- Preserve finite legacy launch/migration compatibility, persisted graph names,
  service ownership keys and error contracts. New systemd units use the current
  Description; ownership admits only the two exact current/legacy Description
  renderings. Unknown descriptions, commands and metadata still refuse. Legacy
  module activation remains refused; native commands in tests are recording doubles.
- CI144 passed eight jobs but refused one changed Debian header before an
  application start. Refresh only linux-libc-dev 6.12.117-1/all with SHA256
  8b4848725a2705e5b1612f2135c44300716690ba762368ab87df127e9a5ed416;
  preserve the other 47 builder packages, runtime bases and dynamic linking.
- Append eight exact dynamic source/test successors. Published history, other
  census/cohort fields, closed AST recipes and every debt ceiling remain exact.
  Public synthetic placeholders change without scanner/filter/allowlist changes.
- Rename public and private development repositories and the physical private
  checkout, preserving identities, visibility, history and concurrent private
  state. A compatibility path preserves existing local tooling. No live home,
  graph, database or service migration is included.
- Backfill the three [historical RepoMap source releases](../../docs/releases/repomap-previews.md)
  at exact corrected-history commits. Dates distinguish current backfill from
  original source promotion. Prior rights and licensing remain unchanged.
- Apply the operator-selected ancestry-preserving v0.0.4 exception in
  [ADR0195](../../docs/adr/2026/11/0195-common-lore-index-preview004-identity.md)
  and CHANGELOG. Only after exact hosted PASS and same-attempt report audit,
  fast-forward main to the qualified staging commit and tag/release that commit.
  No squash, new merge commit, force-push or history rewrite is selected.

## Verification

The initial identity/preflight failures, legacy systemd failures and stale title
assertions were reproduced before their corresponding corrections. The final
combined source cohort passed **240 unit cases and 46 containerized integration
cases**, with one optional pgvector seed case deselected by the core profile.
That case is not a pass or an optional-runtime admission. Fresh binding proof
passed **35 unit cases and four containerized integration cases**. The cohorts
overlap; their totals are not combined into a unique-test or coverage claim.

Canonical command shape, with phase-owned report storage and the retained exact
diagnostic runtime for integration:

```text
tools/run_tests.py --suite unit --no-coverage --jobs 1 --report-dir <phase-owned> -- <unit selectors below>
tools/run_tests.py --suite int --no-coverage --jobs 1 --report-dir <phase-owned> --pg-container-port 55433 --smoke-image-reference <retained exact diagnostic runtime> -- <integration selectors below> -s
```

Exact selectors for the two final cohorts:

### feature-final-unit13

```text
src/test/unit/python/repomap_kg/cli/cloe_namespace_compatibility.unit.test.py
src/test/unit/python/repomap_kg/cli/coordinator_service.unit.test.py
src/test/unit/python/repomap_kg/cli/core.unit.test.py
src/test/unit/python/repomap_kg/cli/local_ops/ops_config_graphs.unit.test.py::CliLocalOpsConfigGraphsUnitTests::test_ops_config_check_text_output_stays_local_only
src/test/unit/python/repomap_kg/cli/local_ops/ops_config_graphs.unit.test.py::CliLocalOpsConfigGraphsUnitTests::test_ops_graphs_text_output_lists_graphs
src/test/unit/python/repomap_kg/cli/local_ops/ops_refresh.unit.test.py::CliLocalOpsRefreshUnitTests::test_ops_refresh_enabled_prints_table_result
src/test/unit/python/repomap_kg/cli/ops_graph_files.unit.test.py::OpsGraphFilesCliUnitTests::test_table_dispatch_and_storage_errors_are_bounded
src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py::test_mcp_serve_reads_a_sqlite_home_without_the_driver
src/test/unit/python/repomap_kg/local_db_backup/dump_listing_boundaries.unit.test.py::LocalDbBackupDumpListingBoundariesUnitTests::test_backup_info_by_manifest_path_and_table_output
src/test/unit/python/repomap_kg/local_db_backup/reports_inspect.unit.test.py::LocalDbBackupReportsInspectUnitTests::test_live_ops6_backup_inspect_json_reports_bounded_toc_summary
src/test/unit/python/repomap_kg/mcp_server/schemas_jsonrpc.unit.test.py
src/test/unit/python/repomap_kg/ops/config_validation.unit.test.py::OpsConfigValidationUnitTests::test_graph_registry_table_summarizes_graphs
src/test/unit/python/repomap_kg/ops/config_validation.unit.test.py::OpsConfigValidationUnitTests::test_status_table_redacts_and_summarizes_counts
src/test/unit/python/repomap_kg/ops_refresh/baselines_drift.unit.test.py::OpsRefreshBaselinesDriftUnitTests::test_prune_graph_baselines_dry_run_and_actual_preserve_latest
src/test/unit/python/repomap_kg/ops_refresh/baselines_drift.unit.test.py::OpsRefreshBaselinesDriftUnitTests::test_save_graph_baselines_writes_timestamped_and_latest_files
src/test/unit/python/repomap_kg/ops_refresh/facade_summaries.unit.test.py::OpsRefreshFacadeSummaryUnitTests::test_graph_summary_json_and_table_are_bounded
src/test/unit/python/repomap_kg/ops_refresh/preflight.unit.test.py::OpsRefreshPreflightUnitTests::test_refresh_preflight_payload_and_table_are_bounded_and_read_only
src/test/unit/python/repomap_kg/ops_refresh/refresh_execution.unit.test.py::OpsRefreshExecutionUnitTests::test_refresh_result_json_and_table_are_bounded_and_safe
src/test/unit/python/repomap_kg/ops_refresh/refresh_status.unit.test.py::OpsRefreshStatusUnitTests::test_refresh_status_json_shape_does_not_read_roots
src/test/unit/python/repomap_kg/runtime/arch7f_release_resources.unit.test.py
src/test/unit/python/repomap_kg/runtime/arch7g_complete_cluster_lifecycle.unit.test.py
src/test/unit/python/repomap_kg/runtime/d12_release_manifest.unit.test.py
src/test/unit/python/repomap_kg/runtime/local_runtime.unit.test.py::LocalRuntimeUnitTests::test_table_output_reports_redacted_dbeaver_info_and_safety
src/test/unit/python/repomap_kg/server/mcp_decomposition_validation.unit.test.py
src/test/unit/python/repomap_kg/service_package/cloe_module_compatibility.unit.test.py
src/test/unit/python/repomap_kg/service_package/systemd.unit.test.py
src/test/unit/python/repomap_test_support/cli.unit.test.py
src/test/unit/python/repomap_test_support/test_cov5k_r2_fix2_dynamic_targets.unit.test.py
src/test/unit/python/tools/ci/public_export_policy.unit.test.py
src/test/unit/python/tools/scale28_r1_dependency_boundary.unit.test.py
src/test/unit/python/tools/system/d12_system_session.unit.test.py
```

### feature-final-int11

```text
src/test/int/python/repomap_kg/cli/cloe_namespace_compatibility.int.test.py
src/test/int/python/repomap_kg/cli/local_db_lifecycle/drop_guards.int.test.py::CliLocalDbDropGuardIntegrationTests::test_local_db_drop_failure_paths_are_safe_and_table_output_is_bounded
src/test/int/python/repomap_kg/cli/local_db_lifecycle/dump_backup_inspect.int.test.py::CliLocalDbDumpBackupInspectIntegrationTests::test_live_ops6_local_db_backup_inspect_reports_bounded_toc
src/test/int/python/repomap_kg/cli/local_db_lifecycle/dump_backup_inspect.int.test.py::CliLocalDbDumpBackupInspectIntegrationTests::test_local_db_backups_and_backup_info_read_manifest_fixture
src/test/int/python/repomap_kg/cli/local_db_lifecycle/init.int.test.py::CliLocalDbInitIntegrationTests::test_local_db_init_from_source_success_applies_schema_with_fake_container
src/test/int/python/repomap_kg/cli/local_db_lifecycle/smoke_chain.int.test.py::CliLocalDbLifecycleSmokeChainIntegrationTests::test_live_harden1_lifecycle_cli_smoke_chain_is_bounded
src/test/int/python/repomap_kg/cli/local_runtime.int.test.py::CliLocalRuntimeIntegrationTests::test_local_setup_table_output_is_redacted_and_local_only
src/test/int/python/repomap_kg/cli/mcp_domain_readback.int.test.py::McpDomainReadbackIntegrationTests::test_mcp_initialize_and_tools_list_advertises_safety_markers
src/test/int/python/repomap_kg/cli/ops_config.int.test.py::CliOpsConfigIntegrationTests::test_ops_config_check_text_output_redacts_literal_password
src/test/int/python/repomap_kg/cli/ops_config.int.test.py::CliOpsConfigIntegrationTests::test_ops_graphs_table_lists_example_graphs
src/test/int/python/repomap_kg/cli/server_entrypoint.int.test.py
src/test/int/python/repomap_kg/coordinator/local_mode.int.test.py::test_explicit_local_mode_launches_and_replays_configured_refresh
src/test/int/python/repomap_kg/coordinator/product5_job_control.int.test.py::Product5JobControlIntegrationTests::test_job_control_table_formatting_complete_scenarios
src/test/int/python/repomap_kg/ops/graph_files.int.test.py::test_canonical_graph_files_cli_filters_paginates_and_preserves_storage
src/test/int/python/repomap_kg/ops/navigation33_portable_retention_and_local_ops.int.test.py::test_local_refresh_cleanup_and_status_formatting_contracts
src/test/int/python/repomap_kg/runtime/d12_package_preflight.int.test.py
src/test/int/python/repomap_kg/service_package/cloe_module_compatibility.int.test.py
src/test/int/python/repomap_kg/storage/mcp_ops_live/read_only_tools.int.test.py::StorageMcpReadOnlyToolsIntegrationTests::test_mcp_read_only_tools_read_python_canonical_graph
src/test/int/python/repomap_kg/storage/migrations_ops_status.int.test.py::StorageMigrationsOpsStatusIntegrationTests::test_ops_refresh_graph_cli_loads_graph_and_reports_status
src/test/int/python/repomap_kg/storage/ops_graph_runtime/graph_summary_lifecycle.int.test.py::StorageOpsGraphSummaryLifecycleIntegrationTests::test_ops_graph_summary_cli_reports_bounded_private_graph_counts
src/test/int/python/repomap_kg/storage/ops_refresh_preflight.int.test.py::StorageOpsRefreshPreflightIntegrationTests::test_ops_refresh_enabled_skips_disabled_private_placeholders
src/test/int/python/repomap_kg/storage/ops_refresh_preflight.int.test.py::StorageOpsRefreshPreflightIntegrationTests::test_ops_refresh_preflight_cli_does_not_write_storage_rows
src/test/int/python/repomap_kg/storage/semantic_seed.int.test.py::test_seed_public_entry_boundary
```

### governance-ci145-unit1

```text
src/test/unit/python/tools/ci/d12_system_grant.unit.test.py
src/test/unit/python/tools/ci/d12_system_proof_host.unit.test.py
src/test/unit/python/tools/system/d12_system_evidence.unit.test.py
src/test/unit/python/tools/ci/public_export_policy.unit.test.py
```

### governance-ci145-int1

```text
src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py
```

Strict retained/type/static checks, topology/export, privacy, suppression,
file-length, changed-source compilation and whitespace are required again on the
final bound tree before publication. Earlier source checks passed under unchanged
canonical policies and inherited debt ceilings. The exact-commit local report
records the final results and independent read/hash-audited dispositions.

The first independent source checkpoint found the systemd regression and its
full-read claim omitted the dispatch tail. That checkpoint was not accepted.
The corrected source checkpoint found no material blockers and passed complete
actual Read/hash audits for every granted input. Large inventory/lock and
mechanical prose changes were explicitly projected, with full prefix/value/AST
replay recomputed by the parent; no ungranted full-source inspection is claimed.
Final binding/tree review is required after the approved policy amendment.

Complete local Python unit, integration, smoke, staging, system and combined
suites were intentionally unselected; complete-suite override is absent. Local
Python coverage, application/SDK image builds, external base pulls and model
studies were unselected. Exact scoped evidence is not hosted qualification.

## Campaign and remaining boundary

CI144 remains EXECUTED_FAIL with zero application starts. Actual cumulative
spend is 52 application starts, 24 charged Rust qualifier entries and 50 wheel
transfers; actual Rust runtime entries are separately 23. The unused application
reservation is retired with its old nonce. Fresh CI145 attempt1 limits are
53/25/52, with one application start, one qualifier entry and two pinned wheels
at most. Every earlier ledger prefix and spent-identity negative stays intact.
These limits are not observed CI145 consumption. No automatic retry, second
push, CI146 allocation or gate/coverage reduction is granted.

Hosted CI state is operator-set AVAILABLE and unrescinded. One normal staging
push is selected after final review, commit and exact local report. The existing
qualification workflow is expected to run its nine jobs automatically; no manual
duplicate dispatch is selected. Whole-population coverage, exact-current hosted
M/A/system/native acceptance and v0.0.4 promotion remain pending at preparation.
The hard 85/85 unit and 80/80 integration gates remain; the requested additional
two-point coverage margin must be measured in hosted CI.

The qualified staging commit and tree must remain exact for main/tag/release.
The GitHub prerelease will be the first Common Lore Index version; package-manager
or registry publication and live activation remain separate. Required public
author and committer: Samuel Leighton Lair <sam.lair@knowledge-forge.ai>.
