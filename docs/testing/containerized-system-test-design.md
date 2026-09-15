# Containerized Assembled-Product System Gate Design

## 1. Overview and Purpose

The `system` test suite (`tools/run_tests.py --suite system`) provides the canonical assembled-product qualification gate for promoting candidate revisions from `staging` to `main` (REPOMAP-SYS0-FIX1).

Unlike unit, integration, or container smoke suites:
- The system gate tests the **packaged release artifact** end-to-end.
- It builds the exact candidate release image (`repomap-system-candidate:<tree_prefix>`) from `render_server_dockerfile()` and runs all RepoMap application services (`init-upgrade`, `http`, `mcp`, `coordinator`, `lifecycle-admin`) from that image.
- It enforces a strict **zero host-source-mount invariant** across all application containers.
- It validates the full durable cluster lifecycle under network isolation, simulated coordinator crash/recovery, and public line-delimited JSON-RPC MCP stdio semantic readback.
- It emits a closed-schema system report (`repomap-system-gate-report-v1`) and a companion binding artifact (`repomap-system-gate-binding-v1`) binding all candidate identities and the report SHA-256.

## 2. Canonical Invocation

In the approved hosted promotion gate (`repomap-main-system-gate.yml`):
```bash
python3 tools/run_tests.py \
  --suite system \
  --system-timeout 3600 \
  --hygiene-profile exhaustive \
  --declared-complete-gates 1 \
  --operator-attest-exclusive \
  --operator-attest-pressure-degradation \
  --sandbox \
  --gate-request-json "${RUNNER_TEMP}/gate-request.json" \
  --candidate-sha "${CANDIDATE_SHA}" \
  --candidate-tree "${CANDIDATE_TREE}" \
  --candidate-base-parent "${CANDIDATE_BASE_PARENT}" \
  --candidate-head-parent "${CANDIDATE_HEAD_PARENT}" \
  --report \
  --report-dir "${REPORT_DIR}"
```

The hosted 3,600-second semantic deadline runs inside the Main System Gate's
90-minute outer qualification envelope. The remaining 30 minutes are reserved
for checkout, tool installation, image/build setup, cleanup, report generation,
and hosted-runner variance. The outer envelope is not an expected runtime, and
the larger hosted deadline does not change the 1,500-second ordinary local
default shown below.

For local reproduction:
```bash
python3 tools/run_tests.py \
  --suite system \
  --system-timeout 1500 \
  --hygiene-profile heavy \
  --declared-complete-gates 0 \
  --operator-attest-exclusive \
  --operator-attest-pressure-degradation \
  --sandbox
```

## 3. Candidate Image Architecture

1. **Build Authority**: The candidate image is built under the `MANAGED_SYSTEM_CANDIDATE` authority class and accounted for via `RunWideDockerBoundary.managed_system_candidate_build()`.
2. **Metadata & Labels**:
   - `org.repomap.test.image.class`: `system-candidate`
   - `org.repomap.test.managed`: `"true"`
   - `org.repomap.test.candidate-tree`: `<full_git_tree_sha>`
   - `org.repomap.test.run-id`: `<run_id>`
   - Release labels: `io.repomap.release.postgresql`, `io.repomap.release.python`, `io.repomap.release.go`, `io.repomap.release.psycopg`, `io.repomap.release.libpq`.
3. **Packaging Self-Test**: A standalone container runs `python -c "import repomap_kg; ..."` with `network_mode="none"` and no workspace volume mounts to verify package self-containment. Output must be valid JSON; probed runtime observations (`python`, `psycopg`, `libpq`, `go_helper`) are strictly matched against release labels without fallback.

## 4. Compose Topology & Source Mount Boundary

- The runtime plan renders base Compose YAML and an override file (`docker-compose.override.yml`) setting `image: repomap-system-candidate:<tree_prefix>` for all application services (`init-upgrade`, `http`, `mcp`, `coordinator`, `lifecycle-admin`).
- Before starting containers, `inspect_and_verify_topology()` runs `docker compose config --format json` and verifies:
  1. Every application service exists and uses the exact candidate image tag.
  2. No service mounts repository root or any descendant path (`src/main/python`, `/workspace/src`, etc.). Only the isolated test fixture directory is mounted for indexing.

## 5. Five-Phase Scenario Lifecycle

The system scenario executes 5 sequential phases under monotonic budget tracking:

1. **Packaged-Cluster Readiness (`packaged_cluster_readiness`)**:
   - Boots PostgreSQL container, applies migrations via `init-upgrade` container, boots `http` and `coordinator` services.
   - Polls HTTP `/readyz`, `/livez`, `/healthz`, `/status`, and verifies coordinator readiness via `ops coordinator-health`.
2. **Durable Coordinator Execution (`durable_coordinator_execution`)**:
   - Submits a durable refresh request for the mixed Python/Go fixture repository in coordinator mode (`mode=coordinator`).
   - Tracks background submission process, correlates exact submitted job ID and idempotency key, and verifies `state` is claimed/in-flight.
3. **Controlled Coordinator Interruption and Recovery (`controlled_coordinator_interruption_recovery`)**:
   - Stops the running coordinator container mid-execution.
   - Restarts the coordinator container from the same persisted database state and image.
   - Awaits job completion (`succeeded`) via `ops coordinator-job-wait` and verifies authoritative publication receipt via `ops refresh-status`.
   - The system-only Compose override enables `_REPOMAP_SYSTEM_TEST_PAUSE_PATH`
     with the one accepted value `/tmp/system_pause_trigger`. After configuration
     and generation validation, the refresh worker creates the fixed readiness
     marker without following a symlink, records the exact job and attempt, and
     waits only while the fixed trigger exists, for at most 30 seconds. Other
     values are ignored. Marker-write failure does not block production refresh,
     and no public configuration or ordinary runtime default enables this bounded
     test interruption hook.
4. **Idempotency & Fencing (`idempotency_and_fencing`)**:
   - Resubmits the identical refresh request with same idempotency key.
   - Verifies the coordinator coalesces/replays the request (`replayed: True`), returning the identical job ID, with single publication preserved.
5. **MCP Public stdio Readback (`mcp_public_stdio_readback`)**:
   - Executes candidate MCP service in stdio mode (`docker compose --profile integration run --rm -i mcp`).
   - Sends line-delimited JSON-RPC messages (`initialize`, `notifications/initialized`, `repomap_list_graphs`, `repomap_graph_status`, `repomap_search_nodes`).
   - Parses each line as JSON-RPC response matched by request ID; rejects errors or malformed payloads.
   - Extracts structured facts into a stable canonical semantic projection and computes SHA-256 across container recreation to assert deterministic byte-level equality.

The STR-PUB5 assembled owner additionally requires the controlled coordinator
recovery step to execute the selected route and read back an exact
`portable-worker-v1` final receipt carrying manifest, extraction-receipt, bundle,
and candidate identities. The scenario still exercises supported CLI status and
read-only MCP behavior. This is executable product evidence, not a callable or
documentation placeholder, and remains unexecuted outside the hosted Main System
Gate.

## 6. Budget & Cleanup Guarantees

- **Total Budget**: Maximum 3600 seconds (60 minutes) for hosted qualification
  runs, with 1500 seconds (25 minutes) as the ordinary local default (see Section 2).
  The outer runner propagates a non-resettable wall-clock deadline epoch
  (`_REPOMAP_SYSTEM_DEADLINE_EPOCH`); each process derives its own monotonic
  remaining-budget accounting from that epoch.
- **Cleanup Reserve**: At least 120 seconds are strictly reserved for cleanup.
  Every Docker SDK operation rechecks the cleanup deadline and clamps the SDK
  request timeout to the remaining reserve. An unavailable client or exhausted
  deadline fails closed and cannot report terminal absence as verified.
- **Exact Run-Owned Teardown**:
  - `docker compose --profile * down -v --remove-orphans`
  - Explicit candidate image tag/ID removal.
  - Removal of exact run-labeled containers, volumes, and recorded IDs only (no global or home-hash deletion).
  - Terminal absence verification of all run-owned resources.
- **Reports**:
  - `repomap-system-gate-report.json` conforming to `repomap-system-gate-report-v1`.
  - `repomap-system-gate-binding-v1.json` conforming to `repomap-system-gate-binding-v1` containing candidate SHAs, parents, image digest, approval ID, conclusion, merge authorization, and system report SHA-256.
    For a locally built image with no repository digest, the retained
    `candidate_image_digest` field contains the exact Docker image configuration
    ID; it is not independent registry provenance.

## 7. One-Time Promotion Bootstrap Exception Procedure

The executable one-time bootstrap exception procedure is:
1. An operator exception lands only the trusted executor bootstrap closure on
   `main`, so the workflow and stdlib-only verifier exist on the trusted base.
2. The exception record states explicitly that the bootstrap commit was not
   pre-qualified by `REPOMAP-SYS0` and authorizes no later candidate.
3. Open or refresh the ordinary `staging`-to-`main` promotion pull request.
4. Run the now-existing workflow against that exact open pull request, base,
   head, merge candidate, and tree.
5. Merge only the exact candidate whose trusted result says
   `merge_authorized=true`; there is no post-merge authorization substitute.
