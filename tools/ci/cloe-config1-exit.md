# REPOMAP-CLOE-CONFIG1 Exit

Status: implemented; scoped proof, static/export/privacy checks passed.
One public staging publication is prepared. Hosted qualification remains pending.

ADR 0109 implements the first CLOE compatibility milestone on the exact
CI87-qualified v0.0.3 baseline. Nonempty CLOE_HOME takes precedence after an
explicit invocation home; the legacy default is retained. Homes accept one
of the legacy or CLOE filename families with unchanged base/local precedence.
Mixed families are refused. The new config-migration-plan CLI reads only
configuration and returns a filename plan, refusing collisions, layer changes
and ordering reversals. It never applies changes, accesses a database or reads
source content. The namespace, distribution, wire identities, persisted data,
dependencies and deployed homes are unchanged.

Two new product owners and two test owners are admitted cleanly. Every prior
owner/selection, historical transition, tool setting and debt ceiling is
preserved. New ownership follows the adjacent maintained CLI/configuration
owners; there is no forecast reclassification or source exclusion.

The container-runtime legacy setup producer refuses a CLOE home before writing
configuration, credentials or runtime state. The generic existing dry-run stays
a legacy-template preview. Test isolation clears ambient CLOE_HOME before
collection and per test; explicitly supplied child selections still work.

Verification: three pre-implementation contract failures reproduced. Final
configuration selection: 118 scoped unit cases and 16 containerized integration
cases passed. Final admission selection: 36 scoped unit cases and three
containerized integration cases passed. All use tools/run_tests.py, exact
selectors, --no-coverage and --jobs 1. Integration uses the existing disposable
sandbox with exact resource-set cleanup, with zero application/SDK builds.

Configuration unit selectors:

- src/test/unit/python/repomap_kg/ops/cloe_config.unit.test.py
- src/test/unit/python/repomap_kg/ops/config.unit.test.py
- src/test/unit/python/repomap_kg/ops/sqlite_local_config.unit.test.py
- src/test/unit/python/tools/ci/retained_python_projection.unit.test.py

Configuration integration selectors:

- src/test/int/python/repomap_kg/cli/cloe_config.int.test.py
- src/test/int/python/repomap_kg/cli/ops_config.int.test.py::CliOpsConfigIntegrationTests::test_ops_config_check_reads_example_without_db_check

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

Native Claude Opus 5.5 high source review accepted the configuration and setup
guard. Its separate admission review identified obsolete event/base fixtures;
those were corrected, related synthetic fixtures aligned, and both scoped
admission selections passed. Parent disposition closes those two findings;
pre-existing workflow-ref hardening suggestions remain follow-ups.

The sealed static profile completed with zero cohort regressions and unchanged
debt/tool ceilings. Topology, file length, suppression inventory, public export,
changed-source compilation and diff checks passed. Pinned Betterleaks 1.8.1
found no findings with full redaction. Local checks establish the scoped
contracts and admission refusals; complete hosted qualification is still needed.

Hosted CI state: AVAILABLE. No remote write or trigger has occurred in this
phase. CI87 qualifies only the parent release. Seven native AMD starts remain
consumed; ADR0110 binds the current new-milestone instruction to one fresh
candidate-bound grant for draft PR23 / CI91 attempt 1, cumulative maximum eight.
Opening payloads omit push fields; current main is the derived baseline, and
the live two-parent test merge must prove the exact base/head. Spent grants,
wrong events, stale parents and retries remain refused. No complete local
unit/integration/smoke/staging/system suite or project coverage is selected.
The protected private checkout remains unchanged, and the read-only three-way
map retains its unresolved integration decisions before any namespace move.
