# CLOE resource governance2 contract

Status: accepted for implementation with ADR 0173 under current parent roadmap authority. Phase `REPOMAP-CLOE-RESOURCE-GOVERNANCE2`. Source parent: `52c60169303458905d11c1f307504ec9ff3ebe4b`.

Paths are repository-relative. Python modules are under `src/main/python/common_lore_index/` unless stated otherwise.

The spec uses three labels:
- **Observation:** a source fact seen at the parent.
- **Proposal:** this design.
- **Precondition:** an unread fact the implementer must verify first. A failed precondition is a stop-and-report condition, not licence to improvise.

Section 15 records the review dispositions and the independent-review gap.

## 1. Scope, authority, boundaries

There are three connected epics, E1-E3. W7 continuation authority covers ordinary choices.

Excluded:
- new dependencies, images, DDL, roles or grants;
- configuration keys;
- MCP changes;
- worker protocol frames;
- the held PostgreSQL startup timeout;
- native parser or model work;
- installed or live-state mutation;
- complete local suites and local coverage;
- main or release promotion.

Default calls (no budget, no v2 report) keep their functional outputs, exit codes and incumbent I/O. Required facade seams are those explicitly named by P6/P9; the helper-reexport patch limitation is recorded below and in the exit.

## 2. Source inventory (observation)

### 2.1 Parent sealing boundary readers

The boundary is one `seal_configured_sources` call made by `capture_portable_candidate`. Per selected file of size `s`:

| Id | Reader or traversal | Owner | Cost per scan | Retries | Retained allocation today |
|---|---|---|---|---|---|
| T0 | `os.walk` (`onerror=None`) plus `is_symlink`, `resolve`, `is_file`, `os.access` per entry | `graph/discovery.py` | metadata | none | name list per directory |
| R1 | `content_hash` (follows symlinks) | `graph/discovery_file_metadata.py` | `s` | none | 1 MiB chunk |
| R2 | `first_line` (`.sh`, `.profile`, unknown extension; `.profile` reaches it twice) | same | at least first line, 8 KiB decode chunks | none | unbounded line |
| R3 | `is_go_generated_file` (`.go`) | `graph/discovery.py` | up to 40 lines | none | unbounded lines |
| R4 | `is_zsh_completion_candidate(path)` via `read_text` (unknown extension, unclassified by name, extension or shebang) | `extractors/shell/zsh_identity.py` | `s` | none | whole file decoded |
| R5 | `_read_stable_file` | `graph/multi_source_capture.py` | `s` per attempt | up to 3 attempts | 1 MiB |
| R6 | `_SourceBody` via `open_source_body`, exact size, no EOF read; anchored per-component directory opens | `artifacts/_source_sealing_io.py` | `s` | none | 1 MiB |
| W1 | `put` temporary write, file fsync; on a new object, install plus directory fsync | `artifacts/_store_filesystem.py` | `s` written | none | one chunk copy |
| R7 | `verify_stream_path` readback, run on every put (64 KiB reads plus EOF) | `artifacts/_store_stream.py` | `s` | none | 64 KiB |
| R7c | `compare_stream_collision` when the target exists, before R7; no directory fsync; temporary unlinked in `finally` | same | `2s` in addition to R7 | none | 64 KiB x2 |
| W2, R8 | manifest canonical bytes put and verify (plus R7c if it already exists) | `artifacts/source_sealer.py` | `m` <= 16 MiB | none | `m` |

- The second scan repeats T0 through R5.
- Nominal successful minimum per file: **6s** for a new object (R1, R5, R6, R7, R1, R5) and **8s** on a collision.
- Add `s` per stable-capture retry: up to 4, so 10s new and 12s collision.
- Add `2s` when R4 applies, plus the applicable R2 and R3 bytes.
- `classify_path` resolves file paths and discovery deduplicates FileInfo by the canonical relative path. Eligible in-root aliases can succeed via the regular target; every encountered alias still adds discovery/classification reads before deduplication. Escaping aliases remain excluded by the incumbent policy, and changed/invalid selected targets remain refused.
- R1's digest is replaced by R5's, so it never reaches the snapshot.
- Pure steps with no I/O: `_validate_inventory_shape`, `SourceSnapshot.create` (P7), `GraphCandidate.create` and `PortableSnapshotManifest.create`.

### 2.2 Outside the sealing I/O counters (elapsed scope below)

- **Attempt setup:** private directories, `_prune_expired_terminal_attempts`, the `_retained_result` read and the capability write.
- **Worker process I/O:** E2 attributes CPU and RSS only.
- **Parent validation:** `validate_portable_capture` and spools.
- **Publication:** SQLite and PostgreSQL.
- **Root checks and Local reconciliation.**
- **The coordinator worker route** (`coordinator/refresh_worker.py`).

### 2.3 Worker lifecycle

The call chain is:
`capture_portable_candidate` -> `run_portable_worker` -> `_run_portable_worker_command` -> `run_worker_spec` -> `_run_protocol_worker` -> `launch_managed_process`.

- On POSIX the launch uses `Popen(start_new_session=True)` with `PosixProcessGroup`. On Windows it uses a job object.
- `ManagedProcess.poll` and `wait` delegate to `Popen`.
- `SyntheticWorkerResult` records launches, timeouts, terminate, kill and group cleanup, with no usage.
- There is no handler around supervision.
- The only `ru_maxrss` use is `RUSAGE_SELF` in `storage/staging_resource_observability.py`.

### 2.4 Report contract

`ops/resource_view/_contracts.py`, `_slots.py` and `ops/resource_reports/_codec.py` define v1 as closed:
- `local_refresh` has 12 metric rows and `server_refresh` has 11;
- refresh tables have 6 limit rows;
- `MAX_FILE_BYTES` is 8,193;
- `sealing_io_limit` is always `absent`.

The parser defines `ops resource-report check|show --input`. `tools/ci/cloe-resource-report1-exit.md` says `ops resource check/show`. This is a recorded document discrepancy; the parser is authoritative (P8, confirmed).

## 3. Epic 1: sealing accounting and governance (accepted design)

### 3.1 Interfaces

**Public module `artifacts/sealing_governance.py`.**
- `SealingBudget`: frozen, with fields `max_read_bytes`, `max_write_bytes`, `max_opens`, `max_directory_entries` and `max_elapsed_ms`, each `int | None`.
  - Values must be integers, not bools.
  - Bytes, opens and entries must be in 0..2^63-1.
  - `max_elapsed_ms` must be in 0..86,400,000, matching the coordinator hard maximum of 86,400 s per attempt.
  - Anything else raises `ValueError('invalid sealing budget')`.
  - An all-None budget normalizes to no budget.
- `SealingBudgetExceeded(ValueError)`:
  - `.limit` is one of `read_bytes`, `write_bytes`, `opens`, `directory_entries`, `elapsed_ms`, `planned_read_bytes`, `planned_write_bytes`, `classification_retention`;
  - `.category = 'resource_budget_exceeded'`;
  - the message is `sealing budget exceeded: <limit>`, path-free and at most 64 bytes.

**Internal module `artifacts/_sealing_meter.py`.**
- `SealingMeter(budget, *, governed, _monotonic_ns=None)`.
- It is owned by one thread. Use from another thread raises `SealingMeterMisuse(RuntimeError)`.
- Counters only increase and are never reset. They persist across bindings, scans, attempts, retries and collisions, and there is no refund API.
- `closed` is set only by `close()` after the manifest put. Every snapshot carries `complete=closed`.

**Threaded keywords.** All default to None and are forwarded only when set (`governance_kwargs`), so default calls and mock seams are unchanged:
- `refresh_local_graph(..., sealing_budget=None)`
- `refresh_graph(..., sealing_budget=None)` -> `_refresh_graph_call` -> `_refresh_graph_impl` -> `execute_portable_refresh(..., sealing_budget=None)` -> `capture_portable_candidate(..., sealing_budget=None)`
- `seal_configured_sources(..., io_meter=None)`
- `scan_multi_source_generations(graph, *, io_meter=None)`
- `_capture_inventory(..., io_meter=None)`
- `FileSystemArtifactStore.put(..., io_meter=None)`

**Meter creation.** `capture_portable_candidate` creates a meter when a budget is set (governed) or a v2 observer is attached (observe-only). It calls `note_sealing_meter(observer, meter)` before sealing and closes the meter after `seal_configured_sources` returns. v1 observers ignore the note.

### 3.2 Metered I/O rules (every reader in 2.1)

- **A1. Admit before acting.**
  - Before each read call of requested length `L` (L >= 1), require `read_charged + L <= max_read_bytes`; otherwise raise before `os.read`.
  - Writes are checked the same way with the exact chunk length before `write`.
  - Each open is checked before `os.open`, `scandir`, `mkstemp` or an anchored component open.
  - Each directory entry is checked before it is accepted from `scandir`.
  - Elapsed is checked before every admitted operation and refuses when `elapsed_ns >= max_elapsed_ms * 10^6`.
  - Invariant: a counter never exceeds its budget.
- **A2. Request sizing.**
  - While declared `fstat` bytes remain: `L = min(reader_chunk, declared_remaining)`. Chunks are 1 MiB for R1, R5 and R6, 64 KiB for R7 and R7c, and the BufferedReader buffer for text.
  - After that, an EOF probe uses `L = min(reader_chunk, remaining_budget)`, or `reader_chunk` without a budget.
  - If the probe returns data, reading continues until EOF. If the budget runs out first, the read refuses with `read_bytes`.
  - R6 keeps its exact-size, no-probe behavior. R5 keeps incumbent signature-retry semantics.
- **A3. Charging.**
  - Charge the bytes actually returned. A short read charges `n` and recomputes `L`.
  - A zero-byte return charges zero and counts one read call.
  - `OSError` charges no bytes; the existing mapping applies.
  - EINTR is retried under PEP 475. A signal-handler exception propagates, and the counters reflect only completed calls.
  - Each admitted open, scandir, mkstemp or anchored component open counts as one open even if the call then fails.
  - `_fsync_directory` counts one open plus one fsync. Each file fsync counts one fsync.
- **A4. Zero and EOF.**
  - `max_read_bytes=0` refuses before the first read call. Because every seal verifies its manifest, a zero read or write budget always refuses.
  - `max_opens=0` refuses at the first listing.
  - `max_directory_entries=0` passes only empty roots.
  - `max_elapsed_ms=0` refuses at the first check.
  - An exact-need run needs read headroom of the per-file costs in 2.1 + manifest bytes + 1.
- **A5. Pre-open admission.** For a full-body reader, if the inventory size exceeds the remaining read budget, refuse before opening.
- **A6. Cleanup.**
  - Every metered descriptor is closed in `finally`. Scandir iterators use context managers.
  - A refusal inside `put` propagates through its existing temporary unlink. A refusal inside `open_source_body` closes the body through the incumbent handler.
  - No refusal deletes stored objects or the attempt root; incumbent custody is kept.
- **A7. Categories.** Governed code re-raises `SealingBudgetExceeded` before any generic `ValueError` or `OSError` mapping, so it never becomes `source_invalid` or `source_capture`.

### 3.3 Readers and traversal (new `graph/_metered_discovery.py`, `artifacts/_metered_io.py`)

**Walker.**
- A `scandir` walker equivalent to `os.walk` (top-down, `followlinks=False`, listing errors skipped as with `onerror=None`).
- It reuses discovery's pure predicates and order: sorted names, `IGNORED_DIR_NAMES`, configured excludes, in-root symlinks, `is_file` and `files_by_path` deduplication.
- Governed mode always has a finite effective entry ceiling: `budget.max_directory_entries` when supplied, otherwise 100,000. The latter is a conservative opt-in policy derived from the existing default manifest-entry scale. It counts directory entries across bindings, metadata preflight and both scans, including entries later filtered out; it is not an equivalent selected-artifact limit.
- Admit each retrieved entry before retaining it in any directory-name list or inventory. The one call-owned counter never resets. Therefore pending sorted names and traversal work are bounded by the effective ceiling even when another budget option alone selected governed mode. A caller may explicitly choose a different finite visit ceiling.
- No budget and v2 observe-only calls retain incumbent traversal with no new default limit. `ops sealing-plan` is an explicitly governed operation and uses the same 100,000 fallback when no entry option is supplied.

**Classification.** Reuses `classify_path` and `detect_language` through new optional `first_line_fn` and `completion_fn` parameters. When these are None, the module-global names are resolved at call time, so patch seams are preserved.

**R1, R5, R7, R7c.** Metered `os.read` loops under A1-A3. Digests and comparisons are identical to the incumbent.

**R2.**
- Uses the incumbent `TextIOWrapper(BufferedReader(MeteredRaw), encoding='utf-8')` stack, with buffer size from `st_blksize` as `open()` chooses it, so decode-error timing matches.
- It may stop once the first non-whitespace characters of the line are not `#!`. This is result-equivalent: all shebang regexes and the unknown-extension branch require `^#!` after strip (P5 confirmed).
- The second `.profile` call is metered separately.

**R3.**
- Observe-only mode keeps the incumbent 40-line read.
- Governed mode keeps the incumbent 40-line read. P11's early-stop equivalence does not hold generally: a later line can raise `UnicodeDecodeError` before the incumbent detector is called.
- Use the same `TextIOWrapper(BufferedReader(MeteredRaw), encoding="utf-8", newline=None)` decoding and readahead behavior as R2. Enforce the combined retained-character bound with bounded `readline(remaining + 1)` before large allocation. Preserve later-line and buffered readahead UTF-8 failures.
- The same combined 1,048,576-character governed retention bound applies to those lines. A file exceeding that explicit owner bound may be refused even if an earlier package/marker already determines the content predicate. This conservative opt-in refusal is intentional, not truncation or a claim that every previously valid file fits the new policy.

**R4.** Streaming strict UTF-8 incremental decode.
- Per line, it skips `str.isspace` characters, checks the `#compdef` and `_arguments` prefixes using `splitlines` separators, and keeps at most 10 characters of carry.
- It stops at the first decode error (the result is then `False`, as with `read_text`) or at EOF.
- BOM, CRLF, CR, U+2028 and U+0085 cases are covered.

**Retention bound** (governed only): `CLASSIFICATION_MAX_RETAINED_CHARS = 1_048_576`.
- It applies per reader call, to the R2 line and to the combined R3 lines. Exceeding it refuses with `classification_retention`.
- Basis: the repository's existing chunk and protocol-line bounds are 1 MiB. No kernel shebang-size claim is needed for this deliberately conservative opt-in retention policy.
- Default and observe-only modes keep incumbent unbounded retention: a residual gap.

### 3.4 Scheduling

**Observe-only mode** keeps the incumbent per-binding order and refusal precedence, and never refuses.

**Governed mode:**
1. Metadata-walk all bindings.
2. During the walk, apply the existing inventory predicate incrementally: count against `max_artifacts`, stat bytes against `max_total_bytes`, and per-path bytes. The same `ValueError` types and messages as ADR 0162 are reused, and retained inventory is at most 100,000 entries.
3. Refuse `planned_read_bytes` when `6S + 1 > remaining_read` (S = sum of unique canonical selected sizes per binding), or `planned_write_bytes` when `S > remaining_write`.
4. Classify, hash and capture binding by binding.
5. Run ADR 0162 admission, the copy, then the governed second scan.

In governed mode, metadata and availability failures of every binding take precedence over body failures, as documented.

### 3.5 Invariants

For a stable tree within budget, metered `seal_configured_sources` returns a manifest, reference and `candidate_id` equal to the unmetered call, and an equal `_capture_inventory` tuple. Sanitized categories, shared immutable objects and the second-scan comparison are unchanged.

## 4. Epic 2: owned-worker attribution (proposal)

### 4.1 Mechanism

New module `coordinator/_usage_reaper.py`, with `ChildUsageReaper(pid, platform)` and a frozen `WorkerResourceUsage`.

`launch_managed_process(..., collect_usage=False)`, POSIX only. When true, the `ManagedProcess` delegates all reaping to the single reaper:
- **`poll()`:** return `popen.returncode` if it is set. Otherwise call `os.wait4(pid, WNOHANG)`; `(0, ...)` returns None. When the pid comes back, keep its rusage, set `popen.returncode = os.waitstatus_to_exitcode(status)` (negative for a signal, matching Popen) and return it.
- **`wait(timeout)`:** poll with backoff from 0.5 to 50 ms until the deadline, then raise `subprocess.TimeoutExpired`. `wait(None)` blocks on `os.wait4(pid, 0)`.
- **ECHILD:** mark usage `reaped_elsewhere`. Reuse `popen.returncode` only if it was already established by a legitimate owning reap. If status is unknown, raise `ProtocolError("worker_status_unknown")`, using the existing sanitized worker-crash/not-started path; never call the CPython ECHILD fallback to invent returncode zero. No success or verified cleanup is inferred from missing child status.
- **Pid check:** the reaper asserts that the returned pid equals the launched pid. That launch and that reap are the lifecycle identity. The pid is never reported.
- **Single owner:** the supervising thread is the only caller of poll or wait for a usage-collecting process. No other thread may call `popen.poll` or `popen.wait` (P10), because CPython would otherwise report returncode 0 through its ECHILD path.

**Plumbing.**
- Forward the defaulted keyword only along the actual private portable chain: `_portable_worker_launch` -> `_worker_launch` -> `_run_protocol_worker` -> `launch_managed_process`. Keep the public `coordinator/protocol.py` facade signature and its injected factory unchanged. Only forward `collect_usage=True` when selected; preserve omitted-default patch seams (P3).
- `collect_usage` is forwarded only when True. If an injected launch factory or a launch ticket is present, it raises `ValueError('usage collection requires owned launch')` before launch.
- `SyntheticWorkerResult` gains a trailing `resource_usage: WorkerResourceUsage | None = None`, kept by `dataclasses.replace`.
- `capture_portable_candidate` passes `collect_usage=True` only for v2 observers. It calls `note_worker_usage(observer, worker.resource_usage, worker)` before `_worker_references`, so failed workers are attributed too.

### 4.2 Units and bases

| Row | Value | Basis |
|---|---|---|
| `worker_user_cpu` | `round(ru_utime * 10^6) * 1000` ns | Linux `wait4_self_and_waited_descendants`; Darwin `wait4_platform_defined` |
| `worker_system_cpu` | `round(ru_stime * 10^6) * 1000` ns | same |
| `worker_cpu` | user + system of the same rusage | same |
| `worker_peak_rss` | Linux `ru_maxrss * 1024`; Darwin `ru_maxrss` bytes | Linux `wait4_max_single_process_rss`; Darwin `wait4_platform_defined` |
| `worker_launches` | 0 or 1 | `supervisor_record` |
| `worker_group_members_after_reap` | 1 if `killpg(pgid, 0)` succeeds after the reap, else 0 | `process_group_probe` |

**Unknowns are `unavailable`:**
- `platform_unsupported`: Windows, no `os.wait4`, or an unknown `maxrss` unit;
- `reaped_elsewhere`;
- `invalid_owner_value`: negative, non-finite, CPU above 2^63-1 ns, `maxrss <= 0`, or an `EPERM` probe;
- `not_started`: no launch, a replay or a retained result;
- `not_observed`: launched, but no note.

**Coverage.**
- CPU covers the child plus the descendants it waited for. Peak RSS is the largest single process's high-water mark. Neither is a sum, a cgroup value, PSS or a cap.
- The group probe sees only processes still in the worker's group. Members that called setsid or setpgid escape both the probe and cleanup and are unobservable. pgid reuse after the group empties is theoretically possible and is documented.
- `operation_process_cpu` stays parent-self, and nothing adds parent and worker values.
- The Linux labels require the integration evidence in section 9. If a waited grandchild is not included, the label falls back to `wait4_platform_defined`.

### 4.3 Interrupt cleanup, opt-in scope (B1)

This applies only when `collect_usage=True`, which means an owned, unticketed portable launch. The default path and coordinator launches are unchanged.

The supervision loop is wrapped in `except BaseException`. The handler:
1. calls `kill_tree` immediately, with no graceful phase;
2. waits on the reaper for at most `termination_grace`;
3. calls cleanup with zero termination grace and remaining-deadline-derived kill timeouts, accounting for every internal wait (the incumbent cleanup can otherwise take termination plus twice the kill timeout);
4. closes stdout/stderr before bounded joins, all under the same shared deadline;
5. re-raises the original exception unchanged.

Ordinary `Exception` failures inside the handler go to `add_note`. A second `BaseException` during the handler is not caught: it propagates with the original as `__context__`, after the kill only if `kill_tree` completed. A second interruption during `kill_tree` leaves cleanup unproved; no hard operating-system wall-time guarantee is claimed.

Extending this to the default path or ticketed launches is a parent disposition item and requires P4.

## 5. Epic 3: controls, plan and v2 delivery (accepted design)

### 5.1 `cloe-resource-view-v2`

**Modules.** New `ops/resource_view/_slots_v2.py`. `_contracts.py` gets per-schema bounds and closed sets, and `_observer_reporting.py` gets v2 dispatch. New `_sealing_projection.py` and `_worker_projection.py`.

**Bounds.** Payload at most 16,384 bytes and file at most 16,385. At most 48 metrics and 24 limits, depth 3, integers in 0..2^63-1.

**Slot model.** Each slot has a name, a unit and an allowed basis set; enforcement is likewise a set. Version 1 tables and domains stay unchanged. Select the record/report version before construction and validation; standalone v1 records and v1 reports must reject v2-only names, reasons, bases and enforcement values. Do not broaden an unversioned global enum or validator and accidentally admit new values into v1. Separate v2 records or explicitly schema-selected constructors may reuse pure validators without changing v1 defaults.

**Additions.**
- Bases: `call_meter_exact`, `call_meter_partial`, `metadata_inventory`, `derived_lower_bound`, `wait4_self_and_waited_descendants`, `wait4_max_single_process_rss`, `wait4_platform_defined`, `supervisor_record`, `process_group_probe`.
- Reasons: `platform_unsupported`, `reaped_elsewhere`.
- Enforcement: `call_budget_pre_io`, `call_budget_cooperative`, `pre_body_admission`, `governed_owner_bound`.
- Outcome: `refused` for refresh tables.

**`local_refresh` metric order (31 rows):**
1. the 10 v1 time and total rows, in v1 order, without `worker_cpu` and `worker_peak_rss`;
2. `sealing_read_bytes`, `sealing_discovery_read_bytes` (R1), `sealing_classification_read_bytes` (R2-R4), `sealing_capture_read_bytes` (R5), `sealing_copy_read_bytes` (R6), `sealing_store_read_bytes` (R7, R7c, R8), `sealing_write_bytes`, `sealing_read_calls`, `sealing_opens`, `sealing_directory_entries`, `sealing_fsyncs`, `sealing_capture_retries`;
3. `planned_inventory_files`, `planned_inventory_bytes`, `planned_min_read_bytes`;
4. `worker_launches`, `worker_cpu`, `worker_user_cpu`, `worker_system_cpu`, `worker_peak_rss`, `worker_group_members_after_reap`.

`server_refresh` drops `lock_and_reconcile_elapsed`, giving 30 rows.

**Refresh limits (14 rows):**
1. the five v1 worker and manifest rows;
2. `inventory_max_artifacts` and `inventory_max_total_bytes` (`pre_body_admission`);
3. `sealing_max_read_bytes`, `sealing_max_write_bytes`, `sealing_max_opens`, `sealing_max_directory_entries` ({`call_budget_pre_io`, `absent`});
4. `sealing_max_elapsed` in ms ({`call_budget_cooperative`, `absent`});
5. `classification_max_retained_chars` (`governed_owner_bound`);
6. `stable_capture_max_attempts` (`owner_enforced`, 3).

`sealing_io_limit` is not used in v2. Lexical and context v2 tables equal v1.

**Outcome rules.**
- A closed meter gives `call_meter_exact`. An unclosed one gives `call_meter_partial` and an `incomplete` report.
- A meter refusal with no other outcome gives `refused`. This is positive proof, because the refusal is raised before the worker and publisher.
- Server `error_category == 'resource_budget_exceeded'` gives `refused` ahead of `failed` only with a genuine terminal budget refusal and positive publisher-not-entered witness. If store temporary cleanup raises `ArtifactIntegrityError`, the terminal outcome is `failed`; do not relabel it from a remembered meter flag. Commit-uncertainty and cancellation precedence are unchanged. An installed object followed by pre-fsync refusal remains under incumbent store custody: do not delete it or claim durable persistence.
- Local replay sets sealing and worker rows to `not_started`, and budget rows to `applies_this_call=false`.
- The worst-case canonical payload is estimated at about 7.5 KB, under 16,384; a unit test asserts it is at most 75% of the bound.

### 5.2 Codec and delivery

- **Reader.** `decode_report` reads at most 16,385 bytes, parses strictly, dispatches on `schema`, then re-applies the per-schema byte bound, so a v1 file over 8,193 bytes stays `too_large`. It requires canonical re-encoding. Older readers refuse v2.
- **Writer.** `encode_report` dispatches on schema. ADR 0165 delivery custody is unchanged.
- **`show`.** Renders v2 through the existing bounded renderer. `ops resource-report check|show` help changes from v1-only to v1 or v2.

### 5.3 CLI

Owners: `cli/_parser_ops_resource.py` (the shared `add_resource_report_option`), `cli/_parser_ops_graph.py`, `cli/_parser_ops_lexical.py`, `cli/_parser_ops_context.py`, `cli/parser.py`, `cli/_ops_refresh_dispatch.py`, `cli/_ops_sqlite_dispatch.py`, `cli/ops_resource_commands.py`, `cli/main.py`, and the new `cli/_sealing_budget_options.py`.

**`--resource-report-schema {1,2}`.**
- The effective default is 1 and it is valid on the six existing seams. Preserve whether the option was explicitly supplied (for example with an internal None sentinel).
- An explicitly supplied schema option without `--resource-report` is a usage error: `resource-report-schema-requires-report`. Ordinary calls with neither option remain valid and byte-identical.
- Any sealing budget combined with `--resource-report` requires explicitly selected `--resource-report-schema 2`. Otherwise refuse with `sealing-budget-requires-report-schema-2` before configuration. Budget calls without a report remain allowed. At the Python API boundary, reject a nonempty budget combined with a v1 observer before any operation; v1 must never claim an active sealing limit is absent.

**`--sealing-max-*` options.**
- Apply to single-graph `ops refresh-graph` only, Local and Server direct.
- Values must be ASCII digits, unsigned, at most 19 digits and within the ranges in 3.1. Anything else is a usage error: `invalid sealing budget: <option>`.
- Refuse syntactically known coordinator or all-enabled modes before configuration work. If mode selection requires reading configuration, refuse after that read and before selected-source, database, worker or publication work. The bounded code is `sealing-budget-unsupported-mode`; no unknown configured mode is guessed before reading it.

**Errors.**
- Server: failure with `error_category='resource_budget_exceeded'`, `publication_state='not_started'` and diagnostic code `sealing-budget-exceeded` (path-free; names the limit). This needs an explicit branch in `classify_refresh_failure`, because non-portable errors otherwise map to `worker_crash`. Positive `not_started` comes from the existing `ValueError` NOT_ENTERED handling (P1, confirmed viable).
- Local: the dispatcher's existing `(OSError, ValueError)` handling, with exit 1 and the report still delivered, and code `sealing-budget-exceeded:<limit>` (P2, confirmed viable).
- Output when no option is given stays byte-identical.

### 5.4 `ops sealing-plan`

New `ops/sealing_plan.py` and `cli/ops_sealing_plan_commands.py`, registered in `cli/parser.py`.

Usage: `cloe ops sealing-plan --graph ID [--json] [--sealing-max-entries N] [--sealing-max-opens N] [--sealing-max-elapsed-ms N]`, with Local home or Server configuration selection.

- Cheap refusals come first: unknown, disabled or unsupported graph, and unavailable root.
- After ordinary read-only configuration resolution, it runs the governed metadata walk only: no selected-source body reads, database connection, graph lock, worker or write. Configuration reads and path metadata are not mislabeled as zero total I/O.
- Stdout is `cloe-sealing-plan-v1`: canonical JSON of at most 4,096 bytes, identity-free. Fields:
  - `schema`, `instrumentation`, `refusal`;
  - `bindings`, `inventory_files`, `inventory_bytes`, `inventory_symlinked_files`, `directory_entries`, `opens`;
  - `planned_min_read_bytes` (`6S+1`, `derived_lower_bound`) and `planned_min_write_bytes` (`S`);
  - `factors`: {`full_body_reads_per_file`: 6, `collision_extra_reads_per_file`: 2, `stable_capture_max_attempts`: 3};
   - `effective_max_directory_entries`, `projected_directory_entries` and `projection_basis`: projected visits are three times the observed preflight entry visits for an unchanged metadata tree, because preflight and both scans are distinct walks. This is a labelled estimate, not a bound or promise for a changed tree. The finite effective cap counts actual visits across all three walks.
- `planned_min_read_bytes` is a lower bound for a *successful* seal of the metadata inventory at that instant. A refusal reads less, and the bound is not a promise about a later refresh.
- MCP exposure: none.

## 6. Public error categories (closed)

- `SealingBudgetExceeded.limit`: the eight names in 3.1.
- Server `error_category`: `resource_budget_exceeded`.
- CLI usage codes: `invalid sealing budget`, `resource-report-schema-requires-report`, `sealing-budget-requires-report-schema-2`, `sealing-budget-unsupported-mode`.
- Report reader `CATEGORIES`: unchanged.
- Worker protocol `_ERROR_CATEGORIES`: unchanged.

## 7. Compatibility and rollback

| Surface | Old | New |
|---|---|---|
| v1 report files | unchanged bytes and reader | still the default |
| v2 report files | refused by old readers | strict accept |
| Worker frames, `job_start` | unchanged | unchanged; parent-only measurement |
| `SyntheticWorkerResult` | positional construction valid | trailing default field |
| Python refresh APIs | unchanged defaults | keyword-only, forwarded only when set |
| `ResourceObserver()` | v1 | `ResourceObserver(report_schema='cloe-resource-view-v2')` |
| Default supervision | unchanged | unchanged |

Rollback: stop passing the options, or revert. There is no persisted state, migration or configuration. Operator report files are never deleted, and attempt roots follow incumbent retention.

## 8. Behavior-change inventory

| Id | Class | Scope |
|---|---|---|
| B1 | bounded kill-first interrupt cleanup | opt-in usage-collecting portable launches only |
| B2 | governed scheduling, new refusals, retention bound, governed R3 combined retention bound | opt-in budgets |
| B3 | metered read sizing, early non-shebang stop, streaming completion check stopping at the first decode error; identical results | opt-in v2 or budgets |
| B4 | wait4 reaping | opt-in v2 observed calls |
| B5 | v2 schema, options, plan command | additive public CLI |
| B6 | `resource_budget_exceeded` | reachable only with budgets |
| B7 | `SyntheticWorkerResult` field | additive API |

## 9. Verification plan

Command: `tools/run_tests.py --suite unit|int --no-coverage --jobs 1 -- <selectors>`. Integration runs in the existing disposable container sandbox.

**New unit owners** (`src/test/unit/python/repomap_kg/`):
- `artifacts/sealing_meter.unit.test.py`
- `artifacts/metered_io.unit.test.py`
- `artifacts/source_sealer_governance.unit.test.py`
- `artifacts/store_metered_put.unit.test.py`
- `graph/metered_discovery_equivalence.unit.test.py`
- `coordinator/usage_reaper.unit.test.py`
- `coordinator/protocol_interrupt_cleanup.unit.test.py`
- `ops/resource_view_v2_contracts.unit.test.py`
- `ops/resource_view_v2_observer.unit.test.py`
- `ops/resource_report_v2_codec.unit.test.py`
- `ops/sealing_budget_cli.unit.test.py`
- `ops/sealing_plan.unit.test.py`

**Adjacent unit owners** (each `.unit.test.py`): `artifacts/source_sealing_io`, `artifacts/source_sealer`, `artifacts/source_sealer_admission`, `ops/resource_view_contracts`, `ops/resource_view_observer`, `ops/resource_report_codec`, `ops/resource_report_cli`, the parser-owner selectors for the files in 5.3, and `tools/ci/retained_python_projection`.

**New integration owners** (`src/test/int/python/repomap_kg/`):
- `artifacts/sealing_governance.int.test.py`
- `coordinator/usage_reaper.int.test.py`
- `ops/resource_report_v2_local_cli.int.test.py`
- `ops/resource_report_v2_server_cli.int.test.py`
- `ops/sealing_plan_cli.int.test.py`

**Adjacent integration owners** (each `.int.test.py`): `artifacts/source_sealer_admission`, `artifacts/navigation33_store_stream_and_sealing`, `ops/resource_view_local`, `ops/resource_view_server`, `ops/resource_report_local_cli`, `ops/resource_report_server_cli`, `ops/resource_report_offline_cli`, `ops/first_use_local`, `ops/first_use_server`, `ops/first_use_mixed`.

**Unit claims.** Every refusal branch is driven by real inputs; there are no coverage-only calls.
- Every budget kind at zero, at exact need, and at exact need minus 1.
- Mid-file and mid-listing refusal.
- Short reads, growth probe, shrink retry, and retry exhaustion with counters never reset.
- Pre-open refusal.
- Charging of failed admitted opens and of directory fsync opens.
- Incremental inventory and the planned lower bound.
- Retention bound: per line and combined R3.
- Elapsed via an injected clock; cross-thread misuse; invalid budget types.
- Descriptor count unchanged after every refusal point.
- Walker equivalence: ignored and excluded globs, in-root and escaping symlinks, non-regular files, unreadable directories.
- Classification equivalence:
  - invalid UTF-8 at chunk boundaries;
  - CRLF, CR, BOM and U+2028;
  - long `#!` lines;
  - double R2 on `.profile`;
  - R4 stopping at the first decode error, with byte counts;
  - governed R3 40-line/decode equivalence for admitted inputs, plus the intentional combined-retention refusal;
- Collision expectation: store reads equal 3s.
- wait4 fakes:
  - units per platform, invalid values, ECHILD, timeout, signal return codes;
  - injected factory or ticket refusal;
  - no wait4 and no handler change on the default path.
- B1: kill-first ordering, bounded deadline, second-interrupt propagation, original exception identity.
- v2 tables, with a worst-case payload of at most 75% of 16,384; v1 table digests unchanged.
- Strict v1 and v2 decode matrix.
- CLI conflicts and option-absent byte identity.

**Integration claims** (real files, SQLite, PostgreSQL and child processes):
- Exact counters equal independently computed expectations on known-size trees, including collision (8s) and empty files.
- A file positioned after the budget point is never opened. Use an independent test-boundary `os.open` recorder and exact sentinel witness, corroborated by meter counters. This proof works under root and never relies on mode-000 permissions, subject counters alone, skip or xfail.
- Metered and unmetered manifests and candidates are identical.
- Real Local and Server CLI v2 reports:
  - committed;
  - refused, with `not_started` and accepted state unchanged;
  - v1 default bytes unchanged.
- A test-support worker module run via `_run_portable_worker_command(module=...)` proves:
  - CPU at least a known burn lower bound;
  - a 64 MiB resident allocation gives `worker_peak_rss` of at least 64 MiB;
  - a waited grandchild is included;
  - a grandchild remaining in the group is flagged;
  - SIGKILL still yields rusage;
  - return code matches Popen;
  - after an injected `KeyboardInterrupt`, no group survives.
- A production worker run proves only the presence and plausibility of the values.
- The plan's counts equal the governed walk.

Coverage: these are real branches toward the open 105 unit and 475 integration branch margins of the 87/82 thresholds. Closing those margins is not claimed.

## 10. What would make this design wrong

- Any reader inside the boundary that 2.1 does not list, or a store read quantity other than the 2.1 rows.
- Walker or classification output that differs from the incumbent on any matrix case.
- `open()` choosing a different buffer than the metered stack.
- Linux wait4 excluding waited descendants, or a `maxrss` unit other than KiB.
- A v2 worst-case payload over 16,384 bytes.
- `classify_refresh_failure` being unable to give positive `not_started` proof.
- Another thread polling a usage-collecting Popen.
- Any new file over 400 lines, or an existing file over its ceiling.

## 11. Preconditions

- **P1.** The `ops/_refresh_outcome.classify_refresh_failure` branch. Reviewer: viable.
- **P2.** Local dispatcher exception handling. Reviewer: viable.
- **P3.** `coordinator/_worker_launch.run_worker_spec` passes keywords through, and the production portable path supplies no injected factory or ticket.
- **P4.** `coordinator/_supervisor_fencing` semantics for unrecorded killed launches. Required only for any future default-path extension of B1.
- **P5.** Shebang predicates require `#!`. Reviewer: confirmed.
- **P6.** File-length ceilings.
  - `ops/portable_refresh.py` first moves its path helpers and the `PortableCapture` record into siblings, keeping the names bound, and ends at 390 lines or fewer.
  - `ops/refresh.py` threads a single forwarded-kwargs line.
  - If `graph/discovery.py` would exceed its ceiling, move `classify_path`, `detect_language` and `detect_role` into `graph/_discovery_classify.py` with same-name re-exports.
- **P7.** `SourceSnapshot.create` performs no I/O.
- **P8.** Offline command name: `ops resource-report`. Reviewer: confirmed.
- **P9.** The `_capture_inventory` facade seam remains for the default path.
- **P10.** No thread other than the supervisor polls or waits on the protocol worker's Popen.
- **P11 resolved negatively by parent.** Keep the 40-line read; later Unicode failure can affect the incumbent result. No early-stop implementation is selected.
- **P12.** The container sandbox's test user identity.

## 12. Ownership and quality

**New production modules:**
- `artifacts/sealing_governance.py`, `artifacts/_sealing_meter.py`, `artifacts/_metered_io.py`
- `graph/_metered_discovery.py`, `graph/_metered_capture.py`
- `coordinator/_usage_reaper.py`
- `ops/resource_view/_slots_v2.py`, `_sealing_projection.py`, `_worker_projection.py`
- `ops/sealing_plan.py`
- `cli/_sealing_budget_options.py`, `cli/ops_sealing_plan_commands.py`
- the extraction siblings from P6

**Modified existing owners:** the parser and command files in 5.3, the observer and codec modules, `coordinator/process_supervision.py`, the protocol and launch modules, `artifacts/_store_filesystem.py`, `artifacts/_store_stream.py`, `artifacts/source_sealer.py`, discovery, capture and the refresh entry points.

**Quality enrollment.**
- Each new or modified owner gets an exact clean enforcement entry, an ownership digest and appended source-backed retained-set lineage.
- No debt ceiling, denominator or hard 85/85 and 80/80 gate changes.
- New files target 350 lines or fewer.

**Documentation:** `docs/ops/sealing-governance.md` and `tools/ci/cloe-resource-governance2-exit.md`. The exit also records the ADR 0162 count discrepancy and the `tools/ci/cloe-resource-report1-exit.md` command-name discrepancy.

## 13. Implementation sequence

| Step | Content |
|---|---|
| S0 | Preconditions P1-P12 and behavior-preserving extractions (adjacent selectors) |
| S1 | Meter and metered I/O |
| S2 | Metered walker and classification equivalence |
| S3 | Store, sealing and governed scheduling, plus the sealing integration owner |
| S4 | v2 contracts and codec |
| S5 | Observer v2, threading, errors, parsers and CLI, plus the v2 CLI integration owners |
| S6 | Reaper, opt-in B1 and worker projection, plus the reaper integration owner |
| S7 | Plan command |
| S8 | Documentation and enrollment |

Each step keeps its selectors green. There is one batched milestone, and any future campaign needs a fresh final-source binding.

## 14. LOC forecast (source forecast only)

| Area | Production | Unit tests | Integration tests | Support | Subtotal |
|---|---|---|---|---|---|
| E1 | ~1,750 | ~3,300 | ~900 | ~300 | ~6,250 |
| E2 | ~650 | ~1,300 | ~700 | ~150 | ~2,800 |
| E3 | ~1,350 | ~2,150 | ~900 | ~150 | ~4,550 |
| Docs, exit, enrollment | - | - | - | ~900 | ~900 |

Total: about 14,500 lines, range 12.5k-17.5k. The E3 increase over the reviewed draft covers the parser-owner additions. Not padded.

## 15. Review disposition record (closer)

| Finding | Disposition | Change |
|---|---|---|
| B-1 collision readback | accepted; source re-read at `artifacts/_store_filesystem.py` 243-271 | ADR item 1; 2.1 R7c; 3.2 A4; 5.4 factors; 9 |
| A1 Go retention | amended under P11 | 3.3 R3; 8 B2; 11 |
| A2 walker allocation | accepted as a bounded-by-budget residual | 3.3 walker; ADR Consequences |
| A3 charging | accepted | 3.2 A3; 9 |
| A4 R4 stop | accepted | 3.3 R4; 8 B3 |
| A5 root witness | accepted | 9; P12 |
| A6 B1 default path | accepted: narrowed to opt-in; default-path extension is a parent item | 4.3; 8; ADR |
| A7 plumbing | accepted | 4.1; P3; P10 |
| A8 probe naming | accepted | 4.2; 5.1 |
| A9 proof scope | accepted | 9 |
| A10 owners | accepted | 5.3; 12 |
| A11 labels | accepted | 5.4; ADR item 1 |
| A12 arithmetic | accepted | 14 |

**First-checkpoint review gap closed at the second checkpoint.** The complete amended ADR/spec and parent dispositions were independently read and reviewed. Section 17 records the remaining conditional finding and its exact parent adoption. Neither design review establishes executed implementation proof.


## 16. Parent dispositions independently reviewed

1. **Legacy defaults stay unchanged.** Broad default/ticketed interrupt cleanup is excluded. The bounded kill-first handler applies only to the new usage-collecting unticketed owned launch, with a single shared monotonic cleanup deadline. Default, injected-factory and coordinator routes keep incumbent behavior. A second interrupt is propagated and any interrupted cleanup remains unproved.
2. **Finite governed traversal.** The 100,000 fallback in section 3.3 applies only after explicit governance selection (including `sealing-plan`). Report the effective finite entry ceiling with `call_budget_pre_io`, even when the caller supplied only a byte/open/elapsed cap. It covers all visits across preflight/bindings/scans, not selected-file count. The caller can choose another finite value; no hard-RSS or default-mode traversal bound is claimed.
3. **P1/P2 are implementation requirements, not source facts already present.** Add the explicit `SealingBudgetExceeded` classifier/Local output branches. Positive `not_started` is allowed only while the existing witness is `NOT_ENTERED`; publication uncertainty and returned/committed states retain priority even if a later callback raises the same exception type.
4. **Reaping is single-owner.** Preserve factory/ticket refusal before a usage-collecting launch, no direct Popen poll/wait while the reaper owns the child, exact kernel-returned PID validation, and fail-closed unknown status on ECHILD. Do not convert unknown exit status to success.
5. **Controlled I/O is program I/O.** Read bytes mean completed bytes returned through the owned readers, write bytes mean bytes admitted to the owned writer; open counters count admitted attempts. These are not physical storage traffic. On interrupted/failed writes the snapshot is partial and must not claim exact physical persistence. Elapsed admission also precedes fsync work; mandatory close/unlink cleanup still runs after exhaustion and is not blocked by the work budget.
6. **Go classification uses the conservative reviewed bound.** P11 is false in general. Keep the 40-line read and the combined governed retention bound; disclose the intentional refusal outside that bound. Default and observe-only semantics stay unchanged.
7. **Version selection is explicit.** Preserve all v1 record and report domains, public bytes and existing size rules. New v2 domains require an explicitly selected version; no global enum widening may relax v1.
8. **Source preconditions checked.** P5/P7/P8/P9 are verified against current source. P3 needs keyword plumbing through the private portable chain only, preserving the public facade; P6 needs same-name/patch-seam-preserving extractions and strict new-owner enrollment. P4 is not an activation gate because default/ticketed cleanup is excluded. P10 single-owner execution and P12 sandbox identity are verified by implementation proof; use a UID-independent sentinel/open-call witness rather than relying on mode000 or trusting only the subject's own counters.
9. **Authority stays with its real owner.** No operator decision is requested here. Current user continuation authorizes these ordinary W7 choices. Future global-default policy or a safe replacement for the held timeout would need separate parent design disposition, not an invented permanent operator reservation. Actual dependency/image/runner-policy, native qualification and live-state boundaries remain excluded.
10. **Primary OS references.** Linux peak RSS units and wait/usage scope are documented in `https://man7.org/linux/man-pages/man2/getrusage.2.html`; Darwin byte units in `https://github.com/apple-oss-distributions/xnu/blob/main/bsd/man/man2/getrusage.2`; Unix availability and process/thread scope in `https://docs.python.org/3.12/library/resource.html`. These references do not establish executed native qualification. Never label the group probe as detecting escaped processes.


## 17. Second design checkpoint and final parent disposition

The complete proposal received a second independent design review on 2026-11-08. Its sole blocker B-1 is resolved by adopting the recommended refusal in section 5.3: a sealing budget plus report requires explicit schema 2 before configuration; the Python API similarly refuses a v1 observer before work. No operator decision is required for this ordinary W7 compatibility choice.

Advisories are adopted: R3 keeps TextIOWrapper buffering/UTF-8 semantics with bounded governed readline allocation; cleanup failures remain failed rather than refused; plans disclose all three projected traversal passes and the effective visit ceiling; only the private portable launch chain grows; unknown ECHILD status uses ProtocolError; opt-in interrupt cleanup shares one deadline and closes pipes before joins; independent open/sentinel witnesses work under root; classification retention has unit `count`; and the Server diagnostic branch must fit the 400-line profile through a narrow extraction. No default, v1, public-facade, uncertain-publication or cleanup-custody rule is relaxed.

Parent source check confirms `discover_repository` appends every eligible `classify_path` result, `classify_path` always returns FileInfo including a content hash, and `_capture_inventory` captures every discovered item. Classification does not remove metadata-selected files. The `6S+1` successful-seal lower bound therefore holds for the static eligible inventory, subject to the stated unchanged-tree/success conditions; symlink or availability refusal is not a successful seal. Tests must independently enumerate metadata selection equivalence, retries, empty files, collisions and changes rather than trusting the planner's own totals.

Both reviews are design evidence only. The parent retains their full hashed private receipts; source implementation, scoped unit and containerized integration proof, strict static enrollment, final frozen-candidate review and campaign binding remain required.


## 18. Parent source-fact and proof clarification

S in the successful `6S+1` lower bound is the canonical, deduplicated selected
inventory per binding. Metadata preflight resolves and deduplicates like
incumbent discovery; actual discovery still charges every eligible encountered
alias. `inventory_symlinked_files` counts eligible symlink entries before
deduplication, independent of visit order; it may exceed unique inventory files.
Escaping or excluded entries do not become eligible aliases. Encountered-name
exclusions preserve incumbent behavior, including an eligible alias selecting
a canonical target whose own encountered name was excluded.

Independent refreshes allocate new generation/run/publication identities and
Server timestamps. Exact byte identity applies to equal underlying results and
the fixed-result/clock v1 codec and formatter contract, not to two unrelated
refreshes. Real CLI proof retains output-shape/noninterference assertions and
adds independent accepted-marker readback before and after refusal. It does not
normalize away changed identities or relabel metadata snapshots as no-read proof.

These source-fact clarifications change no default selection, budget ceiling,
worker protocol or stored graph identity. Additional real alias/retry and plan
witnesses, full v2 worker projections and accepted-marker preservation are part
of parent proof completion before the frozen candidate review.


## 19. Implementation containment and residual disposition

Independent review found that graph.discovery is a native qualification call
root, so concrete artifact-meter imports there are forbidden. The corrected
entrypoint accepts graph-local optional I/O hooks. Capture adapts the one
call-owned meter through MeteredDiscoveryHooks outside that pure entrypoint.
This preserves the dynamic multi_source_pipeline discovery seam and the
discovery.classify_path seam without importing artifact/storage code into the
native host closure. No containment policy or import gate is relaxed.

The parent accepts the recorded P6 helper-reexport limitation: patching the
reexported first_line/content_hash/is_go_generated_file/detect_language names
does not redirect the extracted classifier; no repository caller depends on
those patch-only effects. Required P6/P9 facade seams and normal call results
remain preserved. This is an explicit internal test-seam residual, not an
unreported promise that every module-global monkeypatch retains routing.
Governed incremental count/path/byte admission can choose a different first
refusal when multiple limits fail together; default-mode ordering is unchanged.

## 20. Final review: elapsed timing scope

The elapsed clock starts at portable capture entry, before attempt setup and
retention pruning. Those operations are excluded from the I/O counters, but
their duration and retention-lock waits consume the opted-in elapsed budget.
A slow setup can therefore cause refusal at the first sealing admission. This
conservative timing scope is accepted for this preview; it is a cooperative
check between operations, not a per-syscall deadline.
