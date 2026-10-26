# REPOMAP-PRODUCT6-NAVIGATION47-D12SYSTEM1 Route B One-Use AMD System Candidate Evidence Exit

## Summary

Phase `REPOMAP-PRODUCT6-NAVIGATION47-D12SYSTEM1` implements the approved Route B one-use
`linux/amd64` system candidate build and diagnostic evidence path defined in
`docs/adr/2026/10/0095-one-use-amd-system-candidate.md`.

While product release constants in `src/main/python/repomap_kg/runtime/release.py` remain
fail-closed (`PSYCOPG_LIBPQ_VERSION = None`, `DYNAMIC_PACKAGE_MANIFEST = {}`), the sealed
CI68 exploration artifact populates a separate candidate-only module
`src/main/python/repomap_kg/runtime/release_manifest.py` (`D12_CANDIDATE_LIBPQ_VERSION = 180006`,
`D12_CANDIDATE_PACKAGE_MANIFEST["amd64"]`).

## Route B Admission and Execution Chain

1. **Candidate-only manifest isolation (`repomap_kg.runtime.release_manifest`)**
   - Mechanically generated from the sealed CI68 exploration record.
   - Product callers (`release.py`, `commands.py`, `local.py`, `python_payload.py`) remain
     unchanged and fail closed when explicit candidate overrides are not supplied.
2. **Pre-sandbox host admission (`tools/ci/d12_system_grant.py`, `tools/ci/d12_system_proof_host.py`,
   `tools/ci/d12_system_hold.py`)**
   - `d12_hosted_qualification.py system-hold` validates the tracked grant
     `tools/ci/d12_system_build_grant.json`, `tools/ci/d12_hosted_candidate.json`, live
     `repomap_test_support.d12_recipe.frozen_identity(repo_root, "linux/amd64")`, the exact
     approved draft PR13 `synchronize` event (`pull_request.draft is True` identity for this
     one-use diagnostic campaign, without implying ordinary draft merge eligibility or ready-for-review
     promotion), exact `GITHUB_WORKFLOW_REF` workflow path, `raw_event_sha256` over raw
     `GITHUB_EVENT_PATH` bytes, live Git `HEAD`/`HEAD^{tree}`/parents, and native
     `Linux`/`X64`/`x86_64` host identity before creating the mode-`0600` proof file in the
     mode-`0700` host directory `${RUNNER_TEMP}/repomap-d12-system-admission`.
   - `tools/test_sandbox_dispatch.py` (`integration_sandbox_dispatch`) calls
     `verify_host_system_proof_for_dispatch` (which delegates to
     `tools/ci/d12_system_proof_host.py:verify_host_proof_against_live_environment`) before
     `ensure_sandbox_image` can run for `--suite system`, re-verifying `raw_event_sha256` and all
     live event/Git/host bindings.
   - `tools/test_sandbox_arguments.py` (`sandbox_report_arguments`) reads the bounded host
     proof bytes (`<= 16384` bytes, `MAX_D12_SYSTEM_PROOF_BYTES`) and rewrites
     `--d12-system-proof-json` to `/run/repomap-d12-system-proof.json`, and
     `tools/test_sandbox_execution.py` calls `transfer_system_proof`
     (`tools/test_sandbox_arguments.py`) to stream the exact bounded proof bytes over the
     existing owned `docker exec -i` stdin pipe into an exclusively created (`O_CREAT | O_EXCL`)
     mode-`0600` file at `/run/repomap-d12-system-proof.json` inside the sandbox container
     (no extra bind mount).
3. **Inner runner session, same-daemon preflight, and one-use build lock (`tools/system/d12_system_session.py`)**
   - `D12SystemSession.establish` (via `tools/system/candidate_identity.py:load_and_verify_session_authority`)
     re-validates the exclusively created mode-`0600` inner proof file, grant, candidate JSON,
     live `d12.frozen_identity`, and live Git/tree/arch bindings inside the runner.
   - `run_same_daemon_preflight` (`_default_same_daemon_preflight`) composes
     `tools/d12_dependency_preflight.py` (`import d12_dependency_preflight as inner`, calling
     `inner.explore`) against the active Docker daemon and verifies exact equality against
     `release_manifest.py` and `server_inventory` (`verify_preflight_matches_manifest`) before
     reserving the candidate build.
   - `reserve_one_use_candidate_build` acquires `LOCK_EX | LOCK_NB` on
     `report_dir/d12-system-build.lock` and exclusively writes fsynced mode-`0600`
     `report_dir/d12-system-build-intent.json` (`intent_id == reservation_id == grant_id`).
4. **Candidate image build, post-build probes, and Compose build/pull suppression**
   - `tools/system/candidate_image.py` passes `--iidfile` and records the built image ID on
     `D12SystemSession` immediately so `finally` cleanup removes the image even if post-build
     verification fails.
   - `tools/system/d12_system_evidence.py` runs `run_post_build_candidate_probes`
     (`observe_and_assess_candidate`), where the packaging probe (`PACKAGING_PY`) verifies
     `pq.__impl__ == "c"` and `pq.version() == 180006` alongside dynamic linkage and stage
     inventory attribution, and the disposable core PostgreSQL archive round-trip probe
     (`ROUND_TRIP_PY`, also exposed via `run_disposable_roundtrip_probe`) verifies 2,000 fixture
     rows, `fixture_md5` parity, `CURRENT` graph schema, `["plpgsql"]` extensions, `0`
     replication slots, and `{"btree"}` index access methods (full extension replay and pgvector
     acceptance are not granted).
   - `tools/system/compose_topology.py` and `tools/system/compose_command.py` enforce
     `build: !reset null`, `pull_policy: never`, and subcommand-scoped `--no-build --pull never`
     while preserving `exec`/`run` service command payloads byte-for-byte.
5. **Bounded session reports, candidate evidence sidecar, and fail-closed qualification while P3 is unaccepted**
   - `D12SystemSession._write_bounded_json` (`tools/system/d12_system_session.py`) and
     `tools/system/d12_system_reports.py` enforce `d12.REPORT_PART_LIMIT = 1_500_000` bytes per
     part, `d12.REPORT_TOTAL_LIMIT = 5_000_000` bytes total across session JSON reports and the
     sidecar, and `d12.REPORT_CLEANUP_RESERVE = 100_000` bytes.
   - `build_and_write_d12_system_candidate_evidence` (`tools/system/d12_system_evidence.py`)
     populates `sdk_sandbox` from immutable `session.expected_candidate["sdk_sandbox"]`,
     validates `d12-system-candidate-evidence.json` (`repomap-d12-system-candidate-evidence-v1`)
     via `validate_d12_system_candidate_evidence`, and writes it atomically via
     `tools/system/d12_system_reports.py:write_bounded_json_to_targets`, recording
     `diagnostic_steps_passed` and `cleanup_succeeded` while keeping `image_accepted=false`,
     `p3_accepted=false`, `merge_authorized=false`, and `qualified=false`.
   - `execute_system_run` (`tools/system/runner_execution.py`) keeps
     `SystemSuiteResult.passed=False` and `merge_authorized=False` while P3 remains unaccepted.
