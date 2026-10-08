# ADR 0073: Real-Corpus Publication Scale Bounds

## Status

D1 live-measured and Product step 2 accepted under the captured-snapshot
criterion by `REPOMAP-PRODUCT1-QUAL12-READBACK1` (status 00969): **Product step 2:
live DINAS multi-source captured-snapshot proof qualified; observed browser-ux
source drift disclosed; current-worktree freshness not claimed.**

D2 and D3 remain reviewed architecture with inherited scoped evidence. They were
not re-measured live. QUAL1, QUAL2 and QUAL3 failed and did not publish private
main. HOST1's historical disposition is unchanged. Private-main publication of
this acceptance is subject to APGR finalization.

## Date

2026-09-26

## Context

During multi-source dogfood execution on a real multi-source DINAS corpus (measured
as 10 sources, 1,899 files, 626,582 staged records across 7 publication families),
the historical scale limits proved restrictive:
1. The historical bundle byte limit (64 MiB in `bundle.py` and `portable_refresh.py`)
   was insufficient for large multi-source graphs. An ad-hoc CONT2 expansion to 4 GiB
   was rejected during review as an unauthorized, unbounded resource expansion.
   CONT4 proposed 512 MiB without live measurement. CONT5 measured the canonical
   bundle at 646,981,165 bytes (617.01 MiB), halting on an architecture blocker
   against non-streaming memory expansion.
2. The historical worker process deadline in `limits.py` was 60 seconds default with a
   600-second hard maximum, and then adjusted to 1800s default / 3600s hard maximum.
   Decoupling supervisor attempt limits from leaf worker execution limits was required
   to establish robust safety bounds without overfitting to single-machine timing.
3. The PostgreSQL canonical staging merge query in `canonical_staging_merge.py`
   took 1724.02 seconds in CONT7, requiring query plan characterization and targeted
   statistics management to eliminate pathological query planner execution plans.

## Characterization and Decisions

### D1: Bundle Bytes and Resource Contract (Streaming Implemented; Live-Measured by READBACK1)

QUAL1/QUAL2 measurements do not establish acceptance. The reviewed historical
CONT5 measurement above remains architecture background only. READBACK1
recorded the fresh supported publication's actual bundle-object size against
the code-derived ceilings (item 8).

Manager disposition mandated:
> Do not authorize a larger non-streaming memory budget. Resolve D1 with a bounded
> stream/spool-backed publication bundle path while preserving the current v1 wire contract
> and old-artifact compatibility.

Decision:
1. Preserve the non-streaming in-memory ceiling at `MAX_BUNDLE_BYTES = 512 * 1024 * 1024` (512 MiB)
   in `bundle.py`, maintaining existing decode parity and strict backward compatibility floors
   (>= 64 MiB).
2. Implement a bounded streaming pipeline with `STREAMING_MAX_BUNDLE_BYTES = 1024 * 1024 * 1024` (1 GiB)
   governing product publication bundle generation, storage, and validation, contrasted with the
   broader `4 GiB` generic worker capability ceiling (`max_bundle_bytes`).
3. Preserve the exact wire format `repomap-publication-bundle-jsonl-v1` (dual header framing,
   per-family record sorting, trailer framing).
4. Implement `StreamingBundleEncoder` with `BoundedExternalRowSorter` using bounded memory buffers
   (`_MAX_MEMORY_BUFFER_BYTES = 64 * 1024 * 1024`, 64 MiB default) and disk-backed external merge sort
   to guarantee byte-identical canonical JSONL ordering without heap materialization. Checkpointing
   occurs at 1,000 record intervals.
5. Implement `StreamingBundleParser` and `validate_bundle_stream()` providing single-pass validation,
   incremental checksum verification, disk-backed link validation (`DiskFamilyLinkValidator` with
   ephemeral SQLite `PRAGMA journal_mode = OFF`), and direct stage row spooling (`RowSpoolWriter`).
6. Update `FileSystemArtifactStore` to stream chunks in `put()` and `open_stream()` with
   verifying SHA-256 wrappers (`VerifyingArtifactStream`).
7. Update publisher staging COPY (`staged_ingestion.py`) to consume `ValidatedBundleDescriptor`
   directly via `to_prepared_stage_rows()`, eliminating $O(\text{bundle-bytes})$ memory allocation.
8. Live D1 measurement (READBACK1, status 00969). This is the retained
   content-addressed bundle of the committed ten-binding DINAS publication
   `bundle1:0b41e4f5…9586`.
   - Size: 797,627,437 bytes (760.68 MiB), 740,130 records.
   - The reference size equals the `lstat` size equals the streamed verified
     length.
   - `validate_bundle_stream` passed, and its family summaries equal the
     committed run receipts.
   - The bundle exceeds the 512 MiB non-streaming ceiling, so the streaming
     path was required. It is within the 1 GiB `STREAMING_MAX_BUNDLE_BYTES`
     at 74.3%.
   - No minimum size or large-corpus benchmark is implied.

### D2: Supervisor Worker Process Deadline (Watchdog Architecture Decoupled)

#### Architectural Call Chain & Watchdog Decoupling
CONT10 uncovered that under the coordinator supervisor route (`configured_refresh.py` -> `refresh_adapter.build_refresh_worker_runner`), the child process `repomap_kg.coordinator.refresh_worker` executed the entire refresh lifecycle—sealing, inner worker extraction ($T \approx 169$s), streaming bundle validation ($93$s), and PostgreSQL staged publication ($31$s)—under a single process watchdog. Reusing a 300s deadline left only $\approx 6.5$s headroom.

CONT11 decouples the supervisor watchdog architecture:
1. **Outer Refresh Attempt Deadline (`refresh_attempt_deadline_seconds`)**:
   - Bounds the full coordinator refresh attempt: preflight, discovery, sealing, inner worker execution, streaming bundle validation, and PostgreSQL staged publication.
   - Configured with `default = 3600s` (1 hour) and `hard maximum = 86400s` (24 hours).
2. **Inner Leaf Worker Deadline (`process_deadline_seconds`)**:
   - Bounds only the inner leaf worker subprocess (`run_portable_worker`) performing semantic extraction and bundle generation.
   - Configured with `default = 600s` (10 minutes) and `hard maximum = 3600s` (1 hour).
3. **Anti-Aliasing & Invariant Validation**:
   - `CoordinatorLimits`, `_refresh_attempt_supervision_limits`, and `build_refresh_worker_runner`
     strictly enforce:
     `refresh_attempt_deadline_seconds > process_deadline_seconds >= cancel_deadline_seconds`.
   - Supervisor and worker runner reject configurations that omit `refresh_attempt_deadline_seconds`
     or alias it to `process_deadline_seconds`.
4. **Plumbed Authority**:
   - The leaf `process_deadline_seconds` is plumbed from coordinator limits through `RefreshCapability` -> `IngestionAuthority` -> `execute_portable_refresh` -> `run_portable_worker`.

#### Performance Policy Reconciliation
Per manager policy amendment:
- Performance measurements provide diagnostic reference signals; pre-v0.1 qualification must
  **not overfit pass/fail criteria to single-machine wall-clock timing**. Historical timings
  (such as ADR 0040 SCALE timings and CONT5–CONT10 measured durations) are descriptive
  historical evidence, not acceptance gates or release-blocking service-level objectives.
- Correctness and resource bounds (streaming memory bounds, fail-closed SQL constraints, protocol
  invariants) are strictly split from observed execution durations.
- Watchdog deadlines (`refresh_attempt_deadline_seconds`, `process_deadline_seconds`) represent
  coarse safety bounds and deadlock prevention limits, not performance service-level objectives
  (SLOs) or expected operational runtimes.
- Representative performance qualification is explicitly deferred to a dedicated release-readiness
  phase under controlled environments.
- Integration tests assert architectural boundaries, protocol invariants, and structural query
  plan properties (e.g., session-local TEMP target maps, absence of repeated permanent table probes
  per staged link, bounded set-based join structure with planner/version dependent join algorithm,
  zero temp spill, fail-closed collision handling) rather than brittle wall-clock execution durations.
- Timeout and watchdog verification uses generous safety budgets (e.g., 20s–120s) and deterministic
  execution hooks (`_REPOMAP_SYSTEM_TEST_TIMEOUT_TRIGGER` and synchronization ready-markers) or
  synthetic mock processes rather than brittle sub-second wall-clock races, ensuring tests are
  deterministic across varying host hardware speeds.

### D3: PostgreSQL Canonical Staging Merge Query (Variant F Session-Local Temp Maps Correctness Closure)

CONT10 demonstrated that session-local temporary target maps with `ANALYZE` under the standard unprivileged `repomap_refresh_publication` role reduced `merge.canonical_edge_evidence` from 110.16s to 2.14s on a 626k-record corpus.

CONT11 completes correctness and robustness closure for Variant F:
1. **Fail-Closed Collision Handling**:
   - `IF NOT EXISTS` is omitted from `CREATE TEMP TABLE temp_canonical_edge_map ...` and `temp_canonical_evidence_map`. Pre-existing temporary tables in the session trigger `psycopg.errors.DuplicateTable`, failing closed rather than silently overwriting or reusing untrusted data.
2. **Schema Qualification**:
   - Statements explicitly qualify temporary tables with `pg_temp.` for `ANALYZE`, `JOIN`, and `DROP TABLE IF EXISTS pg_temp.temp_canonical_edge_map; DROP TABLE IF EXISTS pg_temp.temp_canonical_evidence_map;`.
3. **Parity Verification Against Reference Pre-F Helper**:
   - `canonical_merge_reference.py` exports the canonical pre-Variant-F SQL helper `build_reference_edge_evidence_merge_statement`.
   - Scoped integration tests (`scale4_canonical_staging_merge.int.test.py`) establish exact output/link identity parity for successful paths across identity sets, associations, `link_kind`, repo/run scope, duplicate collapse, and replay idempotence against the reference SQL helper, while verifying refusal coverage for missing edges and missing evidence through shared reference/existence guards (SCALE4 reference guards) and transaction integrity without claiming separate execution of legacy refusal branches.
4. **Explain Diagnostics**:
   - Captured query plan diagnostics with `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` recorded in `scale4_explain_diagnostics.json`.

## Consequences

- D1 streaming implementation is retained and live-measured on the committed
  DINAS publication; see decision item 8 and status 00969.
- D2 and D3 are not re-measured live; the observed attempt timing is
  diagnostic only.
- D2 supervisor watchdog architecture is cleanly decoupled: outer refresh attempt watchdog (`refresh_attempt_deadline_seconds`, 3600s/86400s) supervises the full refresh attempt, while inner leaf worker watchdog (`process_deadline_seconds`, 600s/3600s) supervises semantic extraction.
- D3 stats-independent target mapping via Variant F session-local temporary maps with `ANALYZE` is robust, fail-closed, schema-qualified, and verified against the reference SQL helper across successful merge paths alongside reference existence guard verification.
- Standard-role privileges remain least privilege (NOSUPERUSER, non-owner, no MAINTAIN).
- Product step 2 is accepted under the captured-snapshot criterion, subject to
  APGR finalization. Current-worktree freshness is not claimed.
- Product step 3 is not started or authorized.
- SQLite Local, the host-native MCP/read-store seam, installed-package/store
  qualification, public staging and package publication remain pending.

## Rollback and Falsification Conditions

1. **Watchdog Ordering Invariant Falsification**: If runtime configuration supplies `refresh_attempt_deadline_seconds <= process_deadline_seconds`, validation fails closed at coordinator startup and worker runner construction.
2. **Session-Local Temporary Map Falsification**: If session-local temporary tables encounter temporary disk space exhaustion or catalog lock contention under concurrent repository refreshes, fallback to connection-isolated staging schemas or unlogged session maps.
3. **Structural Query Plan Regression Rollback**: If PostgreSQL query planner changes cause the canonical edge-evidence merge or map preparation statements to regress to repeated permanent table probes per staged link, or induce disk-spilling temp sorts under unanalyzed statistics, the mapping strategy must be redesigned without granting database superuser, table ownership, or MAINTAIN privileges.
