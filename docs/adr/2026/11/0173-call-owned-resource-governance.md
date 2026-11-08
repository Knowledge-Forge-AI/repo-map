# ADR 0173: Call-owned resource governance

## Status

**Accepted by the parent for implementation under current roadmap authority.** Design checkpoint for `REPOMAP-CLOE-RESOURCE-GOVERNANCE2` (W7), continuing the accepted `CLOE-RESOURCE-GOVERNANCE` namespace. Source parent: `52c60169303458905d11c1f307504ec9ff3ebe4b`.

The parent accepts this design after two independent design checkpoints and owns implementation acceptance. This record grants no build, acquisition, native campaign or remote mutation.

Both independent checkpoints and the parent dispositions are recorded in specification sections 15–17. The second review condition is adopted exactly: budget plus resource report requires explicit schema 2 before configuration work. Implementation and executed proof remain open.

All choices here are ordinary W7 engineering choices. Reserved decisions and parent disposition items are listed at the end; none of them is selected.

## Date

2026-11-08

## Context

These are source observations at the parent, from registered grants and direct repository reads.

1. **Sealing reads each body at least six times.** `artifacts/source_sealer.py` runs, in order: a first real scan, the ADR 0162 inventory admission, a descriptor-streamed copy into the store, a second real scan and a manifest store.
   - For each file, both scans run a discovery content hash (`graph/discovery_file_metadata.py`) and a stable capture (`graph/multi_source_capture.py`, up to three full attempts).
   - The copy reads the file once more.
   - `FileSystemArtifactStore.put` always reads the installed object back with `verify_stream_path`.
   - When the digest already exists, `put` first runs `compare_stream_collision`, which reads both the stored object and the temporary file, and then still performs the readback.
   - Totals per unique canonical selected file: six full reads for a new file and eight on a collision. Stable-capture retries add up to four (ten new, twelve collision). Files that reach the zsh completion check add two. Eligible in-root aliases add repeated discovery/classification work before FileInfo deduplication; the meter charges those encounters too.
2. **ADR 0162's count is stale.** Its Context says 'roughly one of five body reads' and omits the store readback and the collision comparison. This is a documentation discrepancy, not a defect in ADR 0162's decision.
3. **Classification has extra, unbounded readers.**
   - `first_line` reads the first text line of `.sh`, `.profile` and unknown-extension files, with no line bound.
   - `is_go_generated_file` reads up to 40 unbounded lines of each `.go` file.
   - `is_zsh_completion_candidate(path)` calls `read_text` on the whole file for unknown-extension files that no name, extension or shebang rule classifies.
   - Nothing bounds traversal, opens, entries or bytes before the ADR 0162 admission, and that admission runs only after the first scan has already read every body at least twice.
4. **No I/O accounting exists.** The internal view `cloe-resource-view-v1` (ADR 0159/0165) reports `sealing_io_limit` as `absent`, and always reports `worker_cpu` and `worker_peak_rss` as `not_observed`. Version 1 is public and closed: `_slots.py` requires a schema bump for any new vocabulary. Its bounds are 8,192 payload bytes, 24 metrics and 16 limits.
5. **No worker usage reaches the parent.** The portable worker runs under `_run_protocol_worker` through `ManagedProcess`: a POSIX new session with a process group, or a Windows job object. Reaping goes through `Popen.poll` and `Popen.wait`, so no rusage is retained.
6. **An interrupt can orphan the worker.** The supervision loop has no handler. A `BaseException` raised in the parent skips termination, and because the child runs in its own session it can outlive the parent.
7. **Sealing failures leave the attempt root behind.** `capture_portable_candidate` removes the attempt root only for worker-phase failures. A sealing failure leaves the private attempt root and any objects already stored, pending existing retention.
8. **Worker protocol frames are closed.** Fields are validated exactly, so a new terminal field would break readers on either side of a version skew.
9. **Line budgets are tight.** `ops/portable_refresh.py` is at 399 lines, at the boundary.

## Decision

Implement three connected epics, as specified in the [governance2 contract](../../../specs/cloe-resource-governance2-v1.md).

### Epic 1: accounting and refuse-first sealing governance

**Boundary.** The named boundary is the single `seal_configured_sources` call made by `capture_portable_candidate` in the parent process. It covers:
- traversal and classification readers;
- content hashing;
- stable capture, including retries;
- the copy;
- store writes, readback and collision comparison;
- the second scan;
- the manifest.

Worker, validation, publication and attempt-setup I/O are outside it.

**Meter.** A call-owned `SealingMeter` counts:
- bytes returned by reads, per reader class;
- bytes handed to store writers;
- read calls, descriptor opens (including directory and anchor opens), directory entries, fsyncs and stable-capture retries.

Metadata calls are not counted individually; the entries budget bounds them.

**Budget.** An optional `SealingBudget` limits read bytes, write bytes, opens, directory entries and cooperative elapsed milliseconds. Admission happens before each read, write, open or entry, so a counter never exceeds its budget.

**Modes.**
- *Governed mode* (any budget):
  - walks every binding's inventory using metadata only;
  - applies the existing `ArtifactLimits` predicate during traversal;
  - refuses a provable lower bound before any body read;
  - bounds retained classification text;
  - uses a finite directory-entry visit ceiling: the caller value when selected, otherwise 100,000 for this explicit governed operation. This is derived from the existing default manifest-entry scale, not an estimate of selected files or a global default.
- *Observe-only mode* (a v2 report without a budget): keeps the incumbent order and outcomes and only counts.
- *Default* (no budget and no v2 report): unchanged.

### Epic 2: owned-worker attribution

**Reaping.** For observed v2 calls only, the POSIX `ManagedProcess` of the portable worker reaps its exact child with `os.wait4` through a single owning reaper. It sets `Popen.returncode` and keeps that pid's rusage.

**Reported values.**
- Worker user, system and total CPU, in nanoseconds at microsecond resolution.
- Peak RSS in bytes: Linux KiB × 1024, macOS bytes as reported. The basis is the largest single process's high-water mark, never a sum, cgroup value or cap.
- Unsupported, absent, reaped-elsewhere and invalid data become `unavailable`.
- A process-group probe reports group members remaining after the reap. Processes that escaped the group are documented as unobservable.

**Interrupt cleanup.** The same opt-in usage-collecting launches get a bounded kill-first interrupt cleanup. The default path, and ticketed coordinator launches, are unchanged. Extending the cleanup to them is a parent disposition item.

### Epic 3: numeric controls and versioned delivery

**Report schema.**
- New schema `cloe-resource-view-v2`, a superset of the v1 tables, with bounds of 16,384 bytes, 48 metrics and 24 limits.
- `--resource-report-schema {1,2}` defaults to 1, so ordinary v1 output stays byte-identical.
- A budget combined with a report requires explicit schema 2; otherwise refuse before configuration with `sealing-budget-requires-report-schema-2`. The analogous Python API refuses a budget combined with a v1 observer before work, rather than emitting the false v1 `sealing_io_limit: absent` claim.

**Budget options.** `--sealing-max-read-bytes`, `--sealing-max-write-bytes`, `--sealing-max-opens`, `--sealing-max-entries` and `--sealing-max-elapsed-ms`, on single-graph Local and Server `ops refresh-graph` only.

**Plan command.**
- New read-only command `ops sealing-plan`, emitting a metadata-only `cloe-sealing-plan-v1` with labelled lower bounds.
- Governed v2 reports carry the plan rows and the measured rows of the same operation.

**Compatibility.**
- The strict reader accepts v1 and v2; older readers refuse v2.
- No configuration key, MCP field, SQL, DDL, role, image, dependency or worker frame change.

**No new default numeric ceilings.** Existing `ArtifactLimits` remain the default policy. A read ceiling consistent with them would be at least six times their total-bytes limit, and more with collisions and retries, so it would never bind before the existing limits. A stronger safe default is therefore unsupported by evidence.

## Alternatives considered

- **Growing v1 tables in place.** Rejected: v1 is public and closed.
- **A worker self-report frame or a new `job_start` field.** Rejected: closed frames break version-skewed readers, and the data would be self-reported.
- **Sampling `RUSAGE_CHILDREN`.** Rejected: it is process-global and misattributes concurrent children.
- **`psutil` polling.** Rejected: new dependency, missed peaks, pid-reuse risk.
- **cgroup or container memory.** Rejected: needs privilege or image changes and is not per-operation.
- **Default-on budgets.** Rejected: no workload evidence supports them.
- **A configuration key.** Rejected: it would apply silently to coordinator and aggregate runs, and it needs a configuration schema decision.
- **Removing the redundant discovery hash.** Deferred: it removes two of six reads but changes default I/O and race categories, so it needs a separate design.
- **Truncating classification lines.** Rejected: it would change language detection.
- **Cleaning the attempt root on sealing refusal.** Deferred: the layout is shared with coordinator attempts and replay custody.
- **Physical block I/O (`ru_inblock`).** Rejected: page-cache hits make it misleading.
- **Default-path interrupt cleanup.** Not selected: it changes default behavior, and ADR 0159's parent clarification refused a comparable change. It is kept as a parent disposition item.
- **The PostgreSQL startup timeout.** Remains held and is not adopted.

## Non-goals

This design does not provide or claim:
- PostgreSQL physical-work governance or a server-side deadline;
- a hard RSS cap, or treating worker counts as memory bounds;
- efficiency or scientific claims;
- worker-side byte I/O governance;
- coordinator or aggregate refresh budgets;
- MCP exposure (MCP stays read-only);
- Windows qualification;
- installed, release or main promotion;
- complete local suites or local coverage;
- full W7, W6 or v0.1.0 acceptance.

## Consequences

- Operators can measure actual sealing work, see when it refused, and set refuse-first ceilings. Default calls are unchanged.
- There are three new opt-in public CLI surfaces and one new Server `error_category`, `resource_budget_exceeded`, reachable only with budgets.
- Version 2 report files are refused by older offline readers.
- Residual gaps:
  - classification allocations stay unbounded in default and observe-only modes;
  - governed directory-entry visits have a finite effective ceiling; default and observe-only traversal retain incumbent behavior;
  - metadata calls are bounded but not counted;
  - the elapsed limit is cooperative between operations;
  - wait4 descendant coverage is platform-defined outside Linux;
  - processes that escape the worker group are unobservable;
  - the default-path interrupt orphan risk remains.
- Forecast: about 14,500 meaningful lines including tests and documentation, range 12.5k-17.5k (spec section 14).

## Current selection and separate authority

This phase selects only explicit governed operations and opt-in unticketed usage collection. Global default budgets, default/ticketed interrupt cleanup, discovery-hash removal and a replacement for the held PostgreSQL timeout are unselected. A later ordinary W7 design may address them under parent authority; historical exclusions do not permanently reserve them to the operator.

New dependencies, images, privileged cgroup sources, runner-policy changes, native platform campaigns and live/installed mutation remain outside current authority and require their actual governing approval. No such choice is selected here.

## Implementation sequence

Specification steps S0-S8. Behavior-preserving extractions come first, and each step keeps its exact selectors green. One future campaign needs its own final-source binding.


## Implementation containment clarification

The concrete meter stays outside graph.discovery. Its optional graph-local I/O
hooks are supplied by capture through a metered adapter, preserving the native
qualification import boundary. The parent dispositions the reviewed P6 helper-
reexport patch limitation and governed multi-limit refusal order in specification
section 19. Required classify/discovery facade seams and normal defaults remain
preserved; neither limitation grants a containment or quality waiver.

## Elapsed timing scope

The elapsed clock starts at portable capture entry, before attempt setup and
retention pruning. Those operations are excluded from the I/O counters, but
their duration and retention-lock waits consume the opted-in elapsed budget.
A slow setup can therefore cause refusal at the first sealing admission. This
conservative timing scope is accepted for this preview; it is a cooperative
check between operations, not a per-syscall deadline.
