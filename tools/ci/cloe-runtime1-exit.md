# REPOMAP-CLOE-RUNTIME1 Exit

Status: implemented and reviewed; scoped unit/integration and static/export/privacy
checks passed. One public staging milestone publication is prepared. Complete
hosted qualification remains pending for the exact successor.

ADR0112 enables local setup --config-format cloe, existing-family detection and
loadable CLOE runtime configuration with actual filename mounts. Empty homes
retain the legacy default. Format/backend/target refusals precede runtime and
credential writes; new targets are created privately and exclusively. Existing
configuration and secret bytes are not overwritten. Strict target custody also
intentionally refuses legacy symlinks/non-files/foreign owners/portable aliases.
The normal full-template overlay precedence is explicit; this is not migration
of an existing effective configuration. Known SQLite Local homes are refused.
Malformed legacy bootstrap tolerance and existing ordinary-file permissions
are preserved. Dry-run pins its selected format for API/CLI replay, and setup
JSON diagnostics omit absolute paths, including on repeat setup.

The original scoped failures reproduced before implementation. Native Claude
Opus 5.5 high source review identified a missing dry-run replay option and
required explicit legacy refusal/tolerance evidence. Those findings were
corrected and the final native review found no source/grant blockers. The
review's JSON privacy check reproduced an absolute-path diagnostic leak; setup
now emits stable labels/filenames. Parent follow-up added an injected-read hit
assertion and all mixed-home option variants; no production code changed after
the final review. The later-override precedence, home selector, JSON privacy,
private creation, no-overwrite and original legacy CLI contracts are exercised.

Final product proof: 151 scoped unit cases and 31 containerized integration
cases passed. Fresh admission proof: 36 unit and three integration cases passed.
Every command uses tools/run_tests.py, --no-coverage, --jobs 1 and exact selectors.
Integration reuses the verified cached sandbox and records exact resource-set
cleanup. No local application or SDK build ran.

Unit selectors:

- src/test/unit/python/repomap_kg/runtime/cloe_setup.unit.test.py
- src/test/unit/python/repomap_kg/runtime/local_runtime.unit.test.py
- src/test/unit/python/repomap_kg/runtime/local_home_authority.unit.test.py
- src/test/unit/python/repomap_kg/ops/cloe_config.unit.test.py
- src/test/unit/python/repomap_kg/ops/config_redaction.unit.test.py
- src/test/unit/python/tools/ci/retained_python_projection.unit.test.py
- src/test/unit/python/tools/ci/d12_system_grant.unit.test.py
- src/test/unit/python/tools/ci/d12_system_proof_host.unit.test.py
- src/test/unit/python/tools/system/d12_system_session.unit.test.py
- src/test/unit/python/tools/system/d12_qualification.unit.test.py
- src/test/unit/python/tools/system/d12_system_evidence.unit.test.py

Integration selectors:

- src/test/int/python/repomap_kg/cli/cloe_runtime.int.test.py
- src/test/int/python/repomap_kg/cli/cloe_config.int.test.py
- src/test/int/python/repomap_kg/cli/local_runtime.int.test.py::CliLocalRuntimeIntegrationTests::test_local_setup_creates_runtime_files_under_temp_repo_map_home
- src/test/int/python/repomap_kg/cli/local_runtime.int.test.py::CliLocalRuntimeIntegrationTests::test_local_setup_dry_run_does_not_create_repo_map_home
- src/test/int/python/repomap_kg/cli/local_runtime.int.test.py::CliLocalRuntimeIntegrationTests::test_local_setup_reuses_existing_config_and_env_without_leaking_secret
- src/test/int/python/repomap_kg/cli/local_runtime.int.test.py::CliLocalRuntimeIntegrationTests::test_local_setup_table_output_is_redacted_and_local_only
- src/test/int/python/repomap_kg/cli/local_runtime.int.test.py::CliLocalRuntimeIntegrationTests::test_local_up_and_down_dry_run_do_not_start_or_delete_containers
- src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_system_hold_proof_capture_and_child_secure_writer
- src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_sandbox_dispatch_blocks_system_suite_without_valid_proof
- src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_cross_process_flock_and_o_excl_race_and_execute_system_run

Sealed static enforcement completed with zero cohort regressions. The new
runtime owner and test cohort are admitted cleanly with an exact forward-only
record; prior transitions, selections, tool settings and debt ceilings are
preserved. Topology, file length, suppression inventory, public export,
compilation and diff checks passed. Pinned Betterleaks found zero findings
with full redaction. Runtime local.py and grant proof owners retain their
400-line ceilings. No baseline regeneration or exclusion was used.

CI92 passed all nine jobs on bec838a210f3ffea84986ae85986e4081b2e8291. Its
retained smoke/M/A staging contract was validated against an independently
derived same-tree source digest. That evidence qualifies only its own candidate.
ADR0113 binds the current roadmap/public-CI instruction to one fresh CI93
attempt-1 synchronize campaign through draft PR23, after final identity checks.
All nine earlier actual AMD starts stay spent. One tenth start is reserved;
CI92's nonce/reservation is refused. No automatic retry or eleventh start is
admitted. The final runtime context contains 699 files under the unchanged
SDK/application recipe and supplier pins.

Hosted CI state remains operator-supplied AVAILABLE. No remote action occurred
at this record's preparation; the normal nine-job release-qualification lane is
expected after one ordinary push. Complete unit, smoke/integration, system and
coverage gates remain pending for the successor. Complete local unit,
integration, smoke, staging, system and combined suites, and project coverage,
were intentionally unselected because there is no complete-suite override.

Public main, the protected private checkout, dependency policy, wire/schema
identities and current package/import/executable/default-home names remain
unchanged. No live-home migration, deployment, repository rename, tag or main
promotion is included. Later W1 namespace/default-home/apply/rollback work
retains its reconciliation and migration owners.
