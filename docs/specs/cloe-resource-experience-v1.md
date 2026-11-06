# CLOE resource view and first-use workflows v1

## Status and authority

Accepted for bounded source implementation under
[ADR 0159](../adr/2026/11/0159-resource-view-and-first-use-workflows.md), phase
`REPOMAP-CLOE-RESOURCE-EXPERIENCE1`. Design checkpoint 3 is closed with independent
review and parent disposition. Both epics are implemented; scoped proof passed
141 unit and 57 containerized integration cases. The
[source exit](../../tools/ci/cloe-resource-experience1-exit.md) records executed
selectors and hashes; final source acceptance requires independent review,
whose disposition is recorded in the phase commit.
The ADR's parent implementation clarifications control
over draft hook-placement or applicability wording. Complete local suites,
coverage, new dependencies, acquisition, builds and native parser commands
remain excluded.

The milestone has two epics:

- **A:** a report-only resource view over current retained-Python Local and
  Server refresh, the existing PostgreSQL lexical build, and bounded compact
  context;
- **B:** reproducible source-level first-use workflows for Local, Server and
  mixed material.

Paths are under `src/main/python/common_lore_index/` unless stated otherwise.
Line numbers describe the tree this design read. The implementer must check
each cited line again before editing.

## Verified source facts

| Owner | Fact relied on |
|---|---|
| `ops/portable_refresh.py` (399 lines) | `execute_portable_refresh` (94–138) runs capture (108), validation (110), the staged publisher (114–125) and `mark_terminal(accepted=True)` (126). `capture_portable_candidate` (141–258) seals (175–180) and reuses a retained result if one exists (204–205). It launches the worker only in the branch at 206. The artifact-cap literal is at 218, the bundle cap at 219, and leaf-limit derivation at 222–229. The worker call is at 230–237, and cleanup on `BaseException` is at 238–246. `_worker_references` is at 362–387. The module-level `run_staged_portable_refresh` (47–55) is a patch seam. |
| `ops/_portable_retention.py` | This module was already extracted from `portable_refresh` and is imported back by it. It imports nothing from `portable_refresh`, so a sibling extraction there is an established pattern with no cycle. |
| `artifacts/manifest.py` | `PortableSnapshotManifest.total_files` and `.total_bytes` (49–50) are set when the manifest is created (116, 132). |
| `artifacts/_manifest_records.py` | `ArtifactLimits` (32–38) caps 100,000 artifacts and 4 GiB in total. `_validate_inventory` (166–191) enforces both when the manifest is created. |
| `artifacts/source_sealer.py` | Sealing scans (40), reads, hashes and stores every entry (50–68), and scans again (77–79) before creating the manifest (94). The manifest bounds are therefore checked only after all sealing I/O. |
| `ops/local_refresh.py` (367 lines) | `refresh_local_graph(config, graph_id, *, limits=None)` (163–241). It takes the lock (179), then reconciles (180–182). A replay returns `reconciled=True` (341–349) without capture, a worker or publication. It then captures (187), validates (191), publishes (219–224) and settles (231). Refusals raise `LocalRefreshError` or `LocalStoreError`. |
| `ops/refresh.py` (354 lines) | `refresh_graph(..., staging_measurements=None)` (98–158). Only `KeyboardInterrupt` becomes a returned failure, with `error_category="cancelled"` and `publication_state="rolled_back"` (136–158). `SystemExit` propagates. `_refresh_graph_impl` returns failure results with `not_started` or `commit_unknown` (218–240), and success with `committed` (241–253). `OpsRefreshError` propagates. |
| `storage/staging_observability.py` | `_emit` catches only `Exception` (282–293). `_emit_operation` and `_emit_phase` count a `KeyboardInterrupt` and re-raise it (295–347). `SystemExit` is not caught. `timed` emits in `finally` (176–197), so a sink's `BaseException` there replaces an exception already in flight. `bind_direct_publication_attempt` calls its sink unguarded (88–103). |
| `storage/_staging_lifecycle_emission.py` | Terminal finalization defers a pre-sink `KeyboardInterrupt` for up to eight attempts, then re-raises it (54–81). |
| `storage/staging_resource_observability.py` | Imports `psycopg` (10). Each capture runs two queries (27–54). WAL and temporary values are deltas of shared counters. `postgresql_memory` is the max of whichever before/after backend samples are available, so it may be one sample (76–92). `client_memory` is the `RUSAGE_SELF` process-lifetime peak (142–146). |
| `storage/_staging_measurement_records.py` | 27 closed categories (28–57). The upper-bound set holds WAL, temp and `client_memory` (87–93). |
| `ops/lexical_service.py` (264 lines) | `build_graph_lexical_generation` (99–132) receives the six projection limits as arguments. |
| `ops/lexical_publication.py` | `LexicalBuildOutcome` (146–162). `_refused` sets both aggregates to the literal 0 with `plan=None` (256–268). That is not a measurement. A published outcome carries the plan and its aggregates (364–378). The build timeout is `DEFAULT_BUILD_STATEMENT_TIMEOUT_MS` (243). |
| `retrieval/lexical_capture.py` | `LexicalCapturePlan` holds `aggregate_input_bytes` and `aggregate_projected_bytes`, plus document and omission tuples (79–111). |
| `retrieval/context_assembly.py` | `build_compact_context(..., work_ledger=None)` (175–188) already accepts a caller-owned ledger. A `budget_error` returns before any ledger is used (184–186). Otherwise it uses `work_ledger or WorkLedger(backend=port.backend)` (188). |
| `retrieval/context_budget.py` | The `budget_error` envelope (62–70) has no `request` or `work_ledger` key. It is produced only when the requested budget failed validation, so its `budget_bytes` is not an enforced limit. |
| `retrieval/context_packet_builder.py`, `retrieval/context_budget.py` | The packet carries `work_ledger = ledger.to_dict()` (builder 40). `compute_actual_bytes_fixpoint` writes `actual_bytes` into the packet mapping (budget 99–115), not into the ledger object. |
| `retrieval/context_work.py` | Ceiling constants (10–24), including `WALL_CLOCK_DEADLINE_MS = 10_000` (24) and `SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT = 250` (20), and the 16 `WORK_LEDGER_KEYS` (26–43). The default ledger takes those constants (81–82), and caller values are clamped to them (100–117). Neither `deadline_ms` nor the callback limit is in `to_dict`. `elapsed_ms` updates only when the ledger checks it (119–122). `to_dict` returns null for the SQLite-only keys on PostgreSQL (178–202). |
| `retrieval/context_contracts.py` | `PACKET_STATUSES` is a closed set of seven values (36–38). |
| `coordinator/limits.py` | `process_deadline_seconds = 600` (84). Coordinator-only fields such as `max_running_workers` (71) do not govern direct refresh. |
| `coordinator/_protocol_execution.py` | The parent-side protocol runner reads `process_deadline_seconds` from the limits it is given (77). |
| Existing owners of the extracted seams | `ops/portable_refresh_routing.unit.test.py` drives `execute_portable_refresh`. `coordinator/publication_phase.unit.test.py` imports `_worker_references` from `portable_refresh` (12) and covers its categories. `ops/sqlite_local_reconcile.unit.test.py` covers Local retained-attempt replay. `ops/navigation33_portable_retention_and_local_ops.int.test.py` imports `_attempt_root` and `_worker_references` from `portable_refresh` (53). The independent review found no test reference to `portable_refresh.DEFAULT_LIMITS` or the 4 GiB literal. |
| Existing first-use-adjacent owners | `cli/sqlite_local_operator_workflow.int.test.py` (LOCAL6) already proves the guarded no-Psycopg CLI path over shell sources: `sqlite-init`, preflight, direct refresh, `refresh-enabled`, a source-blind MCP read, and a refused refresh that preserves the accepted generation. `cli/lexical_cli_roundtrip.int.test.py` publishes `mixed-v1` `core`/`companion` to PostgreSQL and round-trips lexical CLI output. `retrieval/context_evaluation.int.test.py` uses `mixed-v1` for evaluation-capability observations. |
| Test support | `retrieval_evaluation_fixture.py` provides `materialize_mixed_v1_working_copy` (88–122; it removes and rebuilds its target), `write_mixed_v1_sqlite_home` (256–274) and `write_mixed_v1_postgres_home` (277–310). Its bindings are `core` and `companion` (public-dev, full-authorized), `feeds` (metadata-only) and `mailbox` (private-memory, metadata-only) (215–242). `context_fixture.py` builds SQLite and PostgreSQL context fixtures. |

## Boundaries

- **Observe only.** The view never enforces anything. Admission, retry,
  leases, locks, reconciliation, cleanup, rollback, commit uncertainty, return
  values and exception precedence stay with their current owners.
- **No public surface change.** There is no CLI flag, CLI or MCP JSON field,
  configuration key, schema or migration, graph vocabulary, worker protocol or
  bundle field, receipt authority, packet field or durable report store. The
  bytes of every command's output are unchanged.
- **No extra work.** Reporting adds no SQL, source or artifact read, manifest
  parse, entry traversal, process or host sampling, `getrusage`, discovery or
  worker message. It reads clocks and values already in parent memory, nothing
  else.
- **No staging tier.** The view never constructs or enables
  `StagingMeasurements`, so it never triggers
  `capture_staging_resources`. Staging resource values are projected only
  from events that a caller collected through its own, independently selected,
  existing `staging_measurements` argument. Otherwise they stay unavailable.
- **Local stays independent.** Local imports no Psycopg, PostgreSQL, Docker,
  parser or enrichment module.
- **Unknown stays unknown.** Worker CPU and RSS, sealing I/O volume, PostgreSQL
  server CPU and per-operation memory peaks are never estimated.

## Data contract: `cloe-resource-view-v1`

A frozen `ResourceReport` holds:

- `schema`;
- `operation`;
- `backend`;
- `outcome`;
- `instrumentation`;
- `metrics`, a tuple of frozen `ResourceMetric`;
- `limits`, a tuple of frozen `ResourceLimit`.

`to_payload()` returns a new mapping of closed strings, nonnegative integers
and nulls. A report holds no reference to any business object. Its payload
contains no graph, repository or binding identity, path, digest, query text,
body, refusal code, error text, database name or environment value.

### Closed vocabularies

| Field | Values |
|---|---|
| `operation` | `local_refresh`, `server_refresh`, `lexical_build`, `compact_context`; null before begin |
| `backend` | `sqlite`, `postgresql`; null before begin |
| `outcome` | `local_refresh`: `published`, `reconciled_replay`. `server_refresh`: `committed`, `failed`, `commit_unknown`, `cancelled`. `lexical_build`: `published`, `refused`. `compact_context`: any value in `PACKET_STATUSES`. All operations: `unclassified`, `not_recorded`. |
| `instrumentation` | `complete`, `incomplete`, `degraded` |
| `availability` | `measured`, `unavailable` |
| `basis` | `monotonic_span`, `process_clock_inclusive`, `accepted_manifest_total`, `parent_validated_total`, `owner_aggregate`, `ledger_counter`, `ledger_lower_bound`, `owner_parameter`, `owner_constant`, `estimate`, `shared_upper_bound`, `sampled_max`, `process_lifetime_peak` |
| `reason` (only when unavailable) | `not_started`, `not_reached`, `not_selected`, `not_observed`, `backend_not_applicable`, `not_emitted`, `ambiguous_repeat`, `invalid_owner_value`, `observer_failed` |
| `unit` | `nanoseconds`, `milliseconds`, `seconds`, `bytes`, `count` |
| `enforcement` | `parent_supervised`, `declared_to_worker`, `post_capture_validation`, `database_statement_timeout`, `owner_enforced`, `absent` |
| `applies_this_call` | `true`, `false`, `null` (unknown) |

### Outcome versus instrumentation

`outcome` is copied from the real owner's terminal state, and only from closed
fields:

| Operation | Owner state | `outcome` |
|---|---|---|
| Local | A returned result with `reconciled=False` | `published` |
| Local | A returned result with `reconciled=True` | `reconciled_replay`. No worker, capture or publication happened in this call. |
| Server | `result == "success"` and `publication_state == "committed"` | `committed` |
| Server | `error_category == "cancelled"` | `cancelled`. The owner's `rolled_back` label is not copied (see the discrepancies section). |
| Server | `publication_state == "commit_unknown"` | `commit_unknown` |
| Server | Any other `result == "failure"` | `failed` |
| Lexical | `result == "published"` / `"refused"` | `published` / `refused`. The refusal code is not copied. |
| Context | `packet["status"]` in `PACKET_STATUSES` | that status |
| Any | An unrecognized combination | `unclassified` |
| Any | The call raised, or the report was read before the call finished | `not_recorded` |

No other outcome means a new publication. An emitted metric, a worker terminal
or a returned failure is never evidence of success.

`instrumentation` describes the observer only:

- `complete`: the outcome was recorded, and every stage that started also
  ended;
- `incomplete`: the outcome was not recorded, or a stage started but did not
  end;
- `degraded`: an ordinary observer error occurred. Every metric is then
  `unavailable` / `observer_failed`. Recorded limit values are kept with
  `applies_this_call=null`, and outcome is `not_recorded`. Reuse cannot promote
  prior-call evidence to the current call.

### Metrics per operation

| Metric | Unit | Basis | Operations | Source |
|---|---|---|---|---|
| `operation_elapsed` | ns | `monotonic_span` | Local, Server, lexical | From the entry hook to outcome recording |
| `operation_process_cpu` | ns | `process_clock_inclusive` | Local, Server, lexical | The `process_time_ns` delta. It includes every thread in the parent and excludes the worker process and the PostgreSQL server. |
| `lock_and_reconcile_elapsed` | ns | `monotonic_span` | Local | Lock wait plus `_reconcile` |
| `capture_elapsed` | ns | `monotonic_span` | Local, Server | Sealing plus the worker, if launched |
| `validation_elapsed` | ns | `monotonic_span` | Local, Server | Parent bundle validation |
| `publication_elapsed` | ns | `monotonic_span` | Local, Server | From entry to the publisher `try`, after binding and Local attempt arming, to outcome recording. It includes the publisher, terminal mark or settle, `validated.close()`, Local lock release and result construction. Binding and arming are excluded. The span ends outside every owner handler (see placement rule P3). |
| `sealed_manifest_files` / `sealed_manifest_bytes` | count / bytes | `accepted_manifest_total` | Local, Server | `manifest.total_files` / `.total_bytes`. This is the accepted inventory, not I/O volume, rehashing or retries. |
| `validated_bundle_records` / `validated_bundle_bytes` | count / bytes | `parent_validated_total` | Local, Server | The sum over `validated.family_summaries` of `record_count` / `byte_length` |
| `worker_cpu` / `worker_peak_rss` | ns / bytes | — | Local, Server | Always `unavailable`: `not_observed` if a worker launched in this call, otherwise `not_started` (a reused retained result or a replay) |
| `lexical_input_bytes` / `lexical_projected_bytes` | bytes | `owner_aggregate` | lexical | `outcome.plan` aggregates. Without a plan (refusal), `not_reached`. The literal zeros in a refusal are never copied. |
| `lexical_documents` / `lexical_omissions` | count | `owner_aggregate` | lexical | `len(plan.documents)` / `len(plan.omissions)` |
| Ledger counters (`config_revalidations_executed`, `logical_read_units`, `sql_statements_executed`, `scan_units_executed`, `seed_expansions_executed`, `candidate_rows_scanned`, `evidence_rows_scanned`) | count | `ledger_counter` | context | `packet["work_ledger"]` |
| `elapsed_ms` | ms | `ledger_lower_bound` | context | The ledger's last check, not the end of assembly |
| `actual_bytes` | bytes | `ledger_counter` | context | The packet's fixpoint, including its trailing newline |
| `sqlite_progress_callbacks` | count | `ledger_counter` | context | `null` on PostgreSQL maps to `backend_not_applicable` |
| `sqlite_vm_steps_estimate` | count | `estimate` | context | Callbacks × interval. It is not CPU, instructions or cross-backend work. |
| `sqlite_progress_interval_ops` | count | `owner_parameter` | context | A parameter, not work |

If a stage never started (a replay, or a call that raised earlier), its
metrics are `not_started`. For a context `budget_error`, every ledger-derived
metric (counters, `elapsed_ms`, `actual_bytes` and the SQLite rows) is
`not_reached`, because no ledger was used. A caller-supplied ledger is not read
in that case. Metrics are non-additive:

- stage spans sit inside `operation_elapsed`, but gaps such as root checks,
  annotation and settling are not reported;
- nothing is summed across stages, operations, families of different units, or
  between a process clock and a span;
- there is no grand total.

### Limit rows: existing controls, not predictions

| `limit` | Value source | `enforcement` | `applies_this_call` |
|---|---|---|---|
| `worker_process_deadline` (s) | `process_deadline_seconds` on the leaf-limits object actually passed to `run_portable_worker`. A non-integer value omits the row. | `parent_supervised` | `true` |
| `worker_max_artifact_bytes`, `worker_max_bundle_bytes` | The validated capability's fields | `declared_to_worker` | `true` |
| `manifest_max_artifacts`, `manifest_max_total_bytes` | `DEFAULT_ARTIFACT_LIMITS` | `post_capture_validation` (checked after all sealing I/O) | `true` only after manifest construction/validation; otherwise unknown |
| `sealing_io_limit` | `null` | `absent` | `null` |
| The six lexical `max_*` projection limits | The arguments given to `build_graph_lexical_generation` | `owner_enforced` | `true` |
| `lexical_build_statement_timeout` (ms) | `DEFAULT_BUILD_STATEMENT_TIMEOUT_MS` | `database_statement_timeout` | `true` |
| `max_logical_read_units`, `max_sql_statements`, `max_scan_units`, `max_seed_expansions` | The packet's `work_ledger` | `owner_enforced` | `true` |
| `budget_bytes` | `packet["request"]["budget_bytes"]` | `owner_enforced` | `true` |
| `wall_clock_deadline` (ms) | A caller-supplied `WorkLedger.deadline_ms` (already clamped). Without one, `WALL_CLOCK_DEADLINE_MS` is only the owner's ceiling; the packet does not reveal a selected lower value. | `owner_enforced` (checked at ledger check points, not continuously) | `true` with the supplied ledger; otherwise `null` |
| `sqlite_progress_callback_limit` | As above, from `sqlite_progress_callback_limit` or `SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT`. SQLite packets only; omitted on PostgreSQL. | `owner_enforced` | `true` with the supplied ledger; otherwise `null` |

The three worker rows are recorded only by `note_worker_launch`, so they exist
only when a worker launched in this call. A reused retained result or a Local
replay constructs no capability, and the rows are omitted rather than filled
from constants that the retained result may not have been produced under.

For a context `budget_error`, no limit row is emitted. The ledger ceilings,
`budget_bytes`, the deadline and the callback limit are all omitted, because
no ledger was used and the requested budget failed validation. A
caller-supplied ledger never yields an `applies_this_call=true` row here.

`parent_supervised` relies on the parent-side protocol runner reading
`process_deadline_seconds` (`coordinator/_protocol_execution.py:77`). Unit 1
must still confirm that `run_portable_worker` reaches that runner with the
leaf limits it was given. Otherwise the label is `declared_to_worker`.

Coordinator-only limits are never reported for direct Local or Server refresh.
This includes concurrency, lease and retry limits. Polling-only
`SourceGenerationLimits` are never copied either, because ordinary refresh
does not use them.

### Bounds

- At most 24 metrics and 16 limit rows. The slots are fixed per operation, and
  a repeated write to a slot degrades the report. No per-file, per-row or
  per-event history is kept.
- The compact sorted-key serialization of a payload is at most 8,192 bytes.

### Staging event projection (opt-in by the caller, not by the view)

`project_staging_resources(events, *, measurements_failed)` is pure. It
accepts only events from a `StagingMeasurements` that the caller constructed
and passed through the existing `refresh_graph(staging_measurements=...)`
argument. It returns four metrics and ignores every other category:

| Category | Basis | Rule |
|---|---|---|
| `wal_upper_bound`, `temporary_byte_upper_bound` | `shared_upper_bound` | Database-wide counter delta; not attributable |
| `postgresql_memory` | `sampled_max` | The max of up to two backend samples (before and after), possibly one; not a peak |
| `client_memory` | `process_lifetime_peak` | Never subtracted or relabeled as an operation peak |

Each category must appear exactly once:

- if it is absent, the metric is `not_emitted`;
- if it repeats, the metric is `ambiguous_repeat`;
- if it arrives as an unavailable event, the metric stays unavailable;
- if `measurements_failed` is true, all four metrics are `observer_failed`.

This projection never calls the caller's sink or any SQL.

## Observer lifecycle and failure semantics

`ResourceObserver()` is call-owned. The caller passes it by keyword and reads
`report()` after the call returns or raises. There is no ambient, global or
context-variable state, and no caller callback runs inside an operation. Owners
call module-level hook functions, each a no-op when the observer is `None`.

The hooks are `begin`, `mark`, `end_stage`, `note_worker_launch`,
`note_manifest`, `note_validated` and the per-operation `finish_*`.

1. **Normal-path only.** Hooks run only on statement boundaries of the normal
   path. They never run in an `except` or `finally` block or in a
   context-manager exit. An operation exception therefore propagates with the
   same identity, `__context__` and `__cause__` as today, and no observer code
   runs while it is in flight. A stage that raises is never ended, so the
   report shows it as `incomplete`.
2. **Ordinary observer errors.** Every hook body catches `Exception` only. It
   then sets `degraded`, stops further recording and returns normally. The
   business path continues identically. This also covers a wrong-type
   observer argument (`AttributeError`) and slot overflow. Misuse produces
   degradation, never a refusal or `ValueError`.
3. **`KeyboardInterrupt` and `SystemExit`.** Hooks never catch them. If one is
   raised inside a hook, it propagates from that call site. In production this
   can only happen through an asynchronous signal. In tests it happens through
   an injected clock. Existing handlers then apply:
   - Server converts `KeyboardInterrupt` to `cancelled`;
   - portable cleanup and attempt marking catch `BaseException`;
   - Local propagates the exception.

   Because rule 1 keeps hooks out of exception paths, a hook cannot replace an
   exception already in flight. A hook's `BaseException` reaches exactly the
   handlers that an asynchronous interrupt delivered at that statement boundary
   reaches today. The placement rules below choose boundaries where those
   handlers give a truthful business state.
4. **Placement rules.**
   - **P1.** No hook sits after a commit, `mark_terminal(accepted=True)` or
     `_settle(accepted=True)` inside a `try` whose handler can mark, settle,
     remove or relabel the attempt or the result. Otherwise an injected
     interrupt would turn a committed, terminal-accepted publication into a
     failed terminal mark or a Server `cancelled` result.
   - **P2.** A hook inside a `try` sits as the first statement before a
     business statement whose failure reaches the same handlers. In that
     position a hook interrupt behaves like a failure of that statement before
     it ran. The worker-launch note is the first statement in the worker
     `try` (before 231), so its interrupt gets the existing attempt-root
     cleanup. The validation end is the first statement in the outer `try`
     in both refresh owners. This outer `try` owns the validated descriptor.
     In Local, it precedes the inner binding/arming block and its failure
     settlement handler. An interrupt there closes the descriptor and leaves
     an unarmed retained attempt for existing reconciliation to settle failed.
     The publication mark is the first statement of the publisher `try`, after
     binding and Local arming, so its interrupt reaches the publisher's handler.
   - **P3.** The publication span therefore has no end hook inside
     `execute_portable_refresh` or Local's `try` blocks. It ends at outcome
     recording: `finish_server` after `_refresh_graph_call` returns, and
     `finish_local` on the return after the `with publisher_lock` block.
   - **P4.** The remaining hooks are `begin`, Local's lock-and-reconcile end
     and replay `finish_local` (inside the `with publisher_lock` body, outside
     any `try`; the replay is already settled), capture start
     and end, and the manifest note after sealing. They sit between statements
     outside any `try`. An
     interrupt there leaves an unvalidated or worker-less attempt, which is the
     same state an interrupt at that boundary leaves today and which existing
     retention and reconciliation already own.
5. **Observed wrapper boundary.** The original Server handler and its returns
   remain in `_refresh_graph_call`. Default calls return through that owner
   without any reporting hook. Observed calls run `begin` before invoking it
   and `finish_server` after its result exists. Both hooks are outside the
   owner's `except KeyboardInterrupt` conversion. An interrupt there propagates;
   it cannot convert a committed result into `cancelled` with `rolled_back`.
   The reporting layer adds no handler.
6. **Server cancellation.** `finish_server` runs on the `cancelled` result
   after the existing `except KeyboardInterrupt` handler has completed, outside
   it. That is a normal return, so outcome `cancelled` is recorded. The
   handler's body and its result are unchanged.
7. **Injected-interrupt test expectations.** For each hook boundary, the test
   asserts that the interrupt propagates with the same identity, or that it
   becomes Server `cancelled`, exactly as an interrupt at the adjacent business
   statement would. It then reads the real attempt and publication state.
   - An interrupt in `finish_server` or `finish_local` after a commit
     propagates out of the owner. The publication is committed and the attempt
     terminal-accepted on readback. The report is `not_recorded` /
     `incomplete`.
   - No test may expect a committed publication to be reported, marked or
     settled as failed.
8. **At most once.** The first `report()` call builds and caches one frozen
   report and seals the observer. Later hooks are ignored, and later
   `report()` calls return the identical object. Calling `report()` while the
   call is still running yields `not_recorded` / `incomplete` and seals the
   observer.
9. **Reuse, reentrancy and concurrency.** `begin` on an observer that has
   already begun, a stage hook on an observer that has not begun, and a hook
   from a thread other than the one that began it all degrade the report.
   Nested owners share one observer: `refresh_graph` begins it, and
   `execute_portable_refresh` and `capture_portable_candidate` only add stages.
10. **Detachment.** Hooks copy integers out of the manifest, the validated
    descriptor and the outcome or packet. Records are frozen tuples of frozen
    dataclasses, so mutating a delivered payload cannot reach any business
    object.
11. **Existing staging sinks are unchanged.** Their `BaseException` semantics
    (see the verified facts) are neither wrapped nor changed. The view does
    not claim that they swallow all failures.

## Attachment seams

These are keyword-only parameters that default to `None`, added on:

- `refresh_local_graph`;
- `refresh_graph`;
- `build_graph_lexical_generation`;
- the internal `execute_portable_refresh` and `capture_portable_candidate`.

An owner forwards `resource_observer=` to an inner call only when it is not
`None`. Default calls therefore pass exactly the current keyword set. Existing
test fakes and patch seams that patch `portable_refresh.execute_portable_refresh`
or `local_refresh.capture_portable_candidate` keep working.

`build_compact_context` is unchanged. The context report is
`project_compact_context(packet, *, work_ledger=None)`, run over the returned
packet and the optional caller-owned ledger. No CLI caller passes an observer.

| Owner | Hook placement | Planned net delta |
|---|---|---|
| `local_refresh.py` | `begin` at entry. Lock/reconcile start and end surround the existing lock/reconciliation; replay uses `finish_local`. Capture forwards `note_manifest`. Validation end and `note_validated` begin the outer descriptor-owning `try`, before binding/arming. Publication starts first inside the publisher `try`, after arming. There is no hook after accepted settlement inside its handlers. `finish_local` wraps the final result after lock release. | final owner 382 lines |
| `refresh.py` | A public wrapper invokes the unchanged cancellation owner `_refresh_graph_call`. Default calls return directly. Observed calls run `begin` before invocation and `finish_server` after its result, outside its handler. `_refresh_graph_impl` forwards the observer. | final owner 389 lines |
| `portable_refresh.py` | Capture start/end surround capture outside any `try`. Validation end and `note_validated` begin the outer descriptor-owning `try`. Publication starts first in the inner publisher `try`, after binding. No hook follows accepted terminal marking inside that `try`. `note_manifest` follows sealing; the worker-launch note begins the worker `try`, preserving cleanup. | final owner 383 lines after extraction |
| `lexical_service.py` | `begin` with the six limit arguments and the timeout. The return is wrapped by `finish_lexical`. | about +7 |

### Bounded extraction from `portable_refresh.py`

The extraction lands as its own behavior-preserving step before any
instrumentation. The new sibling `ops/_portable_worker_terms.py` (about 60
lines) holds the terms of the worker launch and the reading of its terminal:

- `PORTABLE_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024 * 1024`, which replaces the
  literal at 218 with the same value;
- `effective_leaf_limits(limits, authority)`, the logic of 222–229;
- `_worker_references(terminal)`, moved unchanged from 362–387.

Its dependencies were verified:

- `ArtifactReference` from `artifacts`;
- `PortableRefreshError` from `ops._portable_retention`;
- `DEFAULT_LIMITS` and `dataclasses.replace`;
- the existing lazy import of `_ERROR_CATEGORIES` from
  `coordinator._protocol_validation`.

None of these imports `portable_refresh`.

`portable_refresh.py` imports the three names into its own module namespace,
so `capture_portable_candidate` still resolves them as module globals, and
attribute patches on `portable_refresh` still take effect. The independent
review found two by-name imports of `_worker_references` from
`portable_refresh` (`coordinator/publication_phase.unit.test.py:12` and
`ops/navigation33_portable_retention_and_local_ops.int.test.py:53`). Re-binding
the name in `portable_refresh` preserves both. It found no test reference to
`portable_refresh.DEFAULT_LIMITS` or to the 4 GiB literal. The implementer
repeats that search on the tree being edited. The `DEFAULT_LIMITS` import is
removed only if nothing references it.

Planned arithmetic:

| Change | Lines |
|---|---|
| Leaf-limit block replaced by one call | −7 |
| `_worker_references` and its spacing moved out | −28 |
| Import changes | +2 |
| Instrumentation and forwarding in `execute_portable_refresh` (keyword, capture start/end, validation end) | +6 |
| Instrumentation and keyword in `capture_portable_candidate` | +3 |
| **Result** | about 375 lines (stop above 399) |

`local_refresh.py` and `lexical_publication.py` keep importing
`portable_attempts_parent` and the other public names from `portable_refresh`.

### New production modules

All are under `ops/resource_view/` and each stays under 400 lines.

| Module | Responsibility | Estimate |
|---|---|---|
| `__init__.py` | Re-exports the contracts and observer only | about 20 |
| `_contracts.py` | Closed `StrEnum` vocabularies, frozen records, validation and `to_payload` | about 180 |
| `_observer.py` | `ResourceObserver`, the fixed slots and the guarded hook functions | about 220 |
| `_observer_reporting.py` | Pure finish and frozen-report construction split from the observer to preserve the module length limit | about 275 |
| `_controls.py` | Limit-row builders that read only values passed in, plus `DEFAULT_ARTIFACT_LIMITS` | about 110 |
| `_projections.py` | The Server and lexical outcome mappings, `project_compact_context` and `project_staging_resources` | about 220 |

Local imports only `__init__`, `_contracts`, `_observer`, `_observer_reporting`
and `_controls`. The report-construction split is a parent-adopted implementation
detail; it adds no runtime or storage import.
`_projections` imports `storage._staging_measurement_records`, and no Local
path imports `_projections`. No module imports `staging_resource_observability`,
`staged_ingestion`, `ops.refresh`, lexical storage or `psycopg`. New modules
join the retained ownership inventory only as clean additions. If the
existing ownership rule, architecture placement or debt ceiling would change,
stop. Exact new clean-owner entries update the ownership digest and selection
through an appended scope-transition record; they do not reclassify an incumbent.

## Epic B: first-use workflows

Source-level workflows use existing commands and APIs. The command names are
those already documented in `docs/ops/sqlite-local.md`,
`docs/ops/lexical-search.md` and `docs/ops/compact-context.md`. The workflows
add no product command, acquisition, repository-code execution, body
retention or MCP tool. They run over the public `mixed-v1` fixture through
test-owned homes. Frozen tasks, golds and the held-out split are neither read
for scoring nor executed. Expected values are correctness fixtures, not
calibration.

#### Non-duplication rule

Existing owners already prove parts of the first-use path. The
first-use owners reuse those steps as setup only and do not assert them again:

- LOCAL6 (`cli/sqlite_local_operator_workflow.int.test.py`) owns the guarded
  no-Psycopg CLI path over shell sources: `sqlite-init`, preflight, direct
  refresh, `refresh-enabled`, a source-blind MCP read, and a refused refresh
  that preserves the accepted generation.
- `cli/lexical_cli_roundtrip.int.test.py` owns the `mixed-v1`
  `core`/`companion` PostgreSQL publication and the lexical CLI JSON/table
  round trip.
- `retrieval/context_evaluation.int.test.py` owns evaluation-capability
  observations over `mixed-v1`.

The first two are adjacent selectors for Unit 2. The third is a reference only
(see the selectors). Each first-use owner asserts only
the delta below. If, at implementation time, an existing owner already asserts
a listed delta, that delta is dropped and the parent is told, rather than
duplicated.

| Workflow owner | Setup reused | Asserted delta |
|---|---|---|
| `first_use_local` | The LOCAL6 guarded child pattern (`sqlite_local_guard` / `LocalHarness`), now with a `mixed-v1` SQLite home | (a) An end-to-end `context-select` and `context-pack` over `mixed-v1` in the guarded child, with default output keys unchanged. (b) A selection pinned at generation 1 and then used after generation 2, with the status and reason bound from the current owner. Generation 2 is an in-process `refresh_local_graph(resource_observer=...)` over a rematerialized working copy. (c) After a refused refresh, restoring the source root and refreshing again recovers to a new accepted generation. Generation preservation itself stays owned by LOCAL6. (d) Each step's report is projected and checked. |
| `first_use_server` | `temporary_postgres` and the `mixed-v1` PostgreSQL home helpers used by the lexical round trip | (a) `refresh_graph(resource_observer=...)`, then the CLI context select and pack, and a second accepted generation with the pinned-selection outcome bound from the current owner. (b) An observed lexical build over `core`/`companion`, then a query and a revoke, with the lexical report projected. The CLI JSON/table round trip is not re-asserted. (c) Ranked PostgreSQL expansion stays `backend_unsupported` unless an explicit fallback is given. |
| `first_use_mixed` | The SQLite home with all four bindings, plus the PostgreSQL home only for the lexical refusal | (a) `docs` and `messages` context intents across `core`, `companion`, `feeds` and `mailbox`: alias-qualified provenance, metadata-only `feeds`/`mailbox`, and a canary-free output. (b) A lexical build selecting `feeds` or `mailbox` is refused before body capture. (c) The closed location envelope and canary registry distinguish locators from body authorization. (d) One declared alias publishes generation 1; a changed several-alias set publishes generation 2; both are selected and packed. Empty declarations omit `source_bindings` and reach the legacy config owner's four missing-field diagnostics. This is separate from the empty lexical selection refusal. |

Every packet is projected with `project_compact_context`:

- each counter is within its attributed ceiling;
- `actual_bytes` equals `len(serialize_compact_json(packet))`;
- no report is summed with another.

## Implementation units

### Unit 1: resource view (epic A)

The owned production files are:

- `ops/_portable_worker_terms.py`;
- the `ops/resource_view/` package;
- the attachment edits in `ops/portable_refresh.py`, `ops/local_refresh.py`,
  `ops/refresh.py` and `ops/lexical_service.py`.

The new unit owners are all under `src/test/unit/python/repomap_kg/ops/`:

| File | Covers |
|---|---|
| `resource_view_contracts.unit.test.py` | Vocabulary closure, record validation, basis rules, the payload bound and a sentinel-free payload |
| `resource_view_observer.unit.test.py` | An absent observer is inert. Injected-clock `Exception` degrades without changing the result. Injected `KeyboardInterrupt` and `SystemExit` propagate unchanged, following the rule 7 expectations at each placement boundary. An operation exception keeps its identity, `__context__` and `__cause__`. Covers reuse, cross-thread use, unbegun use, sealing and identical repeat reads, and a mutated payload. |
| `resource_view_projections.unit.test.py` | The Server mapping for every branch in `refresh.py:136–253`. Lexical published and refused, where zeros become `not_reached`. Context over SQLite and PostgreSQL ledgers, and a packet that is not mutated. With and without a caller ledger, the deadline and callback rows come from the ledger or from the owner constants, and the callback row is omitted on PostgreSQL. For `budget_error`, with and without a caller ledger: no limit rows, and every ledger-derived metric is `not_reached`. Worker rows are present only after a launch, and worker metrics are `not_started` for reuse and replay. Staging events that are absent, single, repeated or failed. |
| `resource_view_attachment.unit.test.py` | The default calls of all four owners pass exactly the existing keywords to patched inner callables. With an observer, they forward it. Replay, `cancelled` and `commit_unknown` are recorded through patched seams. |
| `portable_worker_terms.unit.test.py` | Leaf-limit parity in all three cases (explicit limits, an authority deadline, the default), the constant's value, and seam identity: `portable_refresh._worker_references` and the other moved names are the sibling's objects, and module-global patches on `portable_refresh` still take effect. The `_worker_references` categories stay owned by `coordinator/publication_phase.unit.test.py` and are not re-asserted. |

The extended unit owner is
`src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py`.
It adds a fresh guarded child that imports `ops.local_refresh` and
`ops.resource_view` and loads no module from `POSTGRES_IMPLEMENTATION`.

The new integration owners are:

| File | Covers |
|---|---|
| `src/test/int/python/repomap_kg/ops/resource_view_local.int.test.py` | A real worker on `mixed-v1`, run driver-free: the observed and unobserved `family_counts` are equal. Replay through an armed attempt, using the existing reconciliation pattern. A failed refresh. SIGINT in a child after the existing post-ACK readiness byte: the generation is preserved, the report is `not_recorded`, and the next run reconciles. A concurrent pair of child processes, compared against the existing publisher-lock outcome. A canary-free payload. |
| `src/test/int/python/repomap_kg/ops/resource_view_server.int.test.py` | `committed`. `failed`. `commit_unknown` through the existing `run_staged_portable_refresh` seam. SIGINT gives `cancelled`. A spy proves zero `StagingMeasurements` constructions and zero `capture_staging_resources` calls when the caller selects none. A caller-selected `StagingMeasurements` is projected. A concurrent direct pair is bound to the existing owner's outcome. |
| `src/test/int/python/repomap_kg/retrieval/resource_view_lexical.int.test.py` | A published build whose aggregates equal `outcome.plan`. `mailbox`/`feeds` refusals with no binding ID or refusal code in the payload. No accepted publication raises `not_recorded`. |
| `src/test/int/python/repomap_kg/retrieval/resource_view_context.int.test.py` | SQLite and PostgreSQL packets from the existing context fixtures: ceilings, `actual_bytes`, nulls that become `backend_not_applicable`, and `budget_error` |

### Unit 2: first-use workflows (epic B)

The owned files are:

- `src/test/support/python/repomap_test_support/first_use_workflow.py`. It
  composes existing helpers and holds the one piece of pure logic the
  workflows need: `first_use_expectations(declared_aliases)`. That derives
  each binding's expected treatment (full-authorized, metadata-only, or
  lexical-refused) from the fixture's binding policy table, so expected values
  are not hand-copied into three owners. It also has a guard that refuses a
  home or working-copy root outside the test's temporary directory, because
  `materialize_mixed_v1_working_copy` removes and rebuilds its target.
- `docs/ops/first-use-workflows.md` (new), labeled *source-level; installed
  proof pending*;
- cross-links in `docs/ops/sqlite-local.md`, `docs/ops/lexical-search.md` and
  `docs/ops/compact-context.md`;
- `tools/ci/cloe-resource-experience1-exit.md`, which records the SHA-256 of
  every owned file, the selectors and the results.

The unit owner is unconditional:
`src/test/unit/python/repomap_kg/ops/first_use_workflow_support.unit.test.py`.
It covers `first_use_expectations` for each binding class and for one,
several, changed and empty alias sets. It also covers the root guard, which
must refuse a path outside the temporary root, a symlinked escape and the
fixture source directory itself. It needs no database, worker or CLI child. If
the testing standards place unit tests for test-support modules elsewhere,
stop and report rather than inventing a path.

The new integration owners are:

- `src/test/int/python/repomap_kg/ops/first_use_local.int.test.py`
- `src/test/int/python/repomap_kg/ops/first_use_server.int.test.py`
- `src/test/int/python/repomap_kg/ops/first_use_mixed.int.test.py`

### Selectors

Run with `--no-coverage` only. Each unit has its own selectors. The adjacent
existing owners after the new owners in each list were verified to exist.
They guard the extracted seams, publication, staging, lexical and context
regressions, and the first-use paths that the new owners must not duplicate.

Unit 1 (resource view):

```text
python3 tools/run_tests.py --suite unit --no-coverage --
  src/test/unit/python/repomap_kg/ops/resource_view_contracts.unit.test.py
  src/test/unit/python/repomap_kg/ops/resource_view_observer.unit.test.py
  src/test/unit/python/repomap_kg/ops/resource_view_projections.unit.test.py
  src/test/unit/python/repomap_kg/ops/resource_view_attachment.unit.test.py
  src/test/unit/python/repomap_kg/ops/portable_worker_terms.unit.test.py
  src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py
  src/test/unit/python/repomap_kg/ops/sqlite_local_refresh.unit.test.py
  src/test/unit/python/repomap_kg/ops/sqlite_local_reconcile.unit.test.py
  src/test/unit/python/repomap_kg/ops/portable_refresh_routing.unit.test.py
  src/test/unit/python/repomap_kg/coordinator/publication_phase.unit.test.py
python3 tools/run_tests.py --suite int --no-coverage --pg-container-port 55433 --
  src/test/int/python/repomap_kg/ops/resource_view_local.int.test.py
  src/test/int/python/repomap_kg/ops/resource_view_server.int.test.py
  src/test/int/python/repomap_kg/ops/resource_view_fault_custody.int.test.py
  src/test/int/python/repomap_kg/retrieval/resource_view_lexical.int.test.py
  src/test/int/python/repomap_kg/retrieval/resource_view_context.int.test.py
  src/test/int/python/repomap_kg/ops/navigation33_portable_retention_and_local_ops.int.test.py
  src/test/int/python/repomap_kg/retrieval/context_sqlite_publication.int.test.py
  src/test/int/python/repomap_kg/retrieval/context_postgres_publication.int.test.py
  src/test/int/python/repomap_kg/retrieval/lexical_postgres_lifecycle.int.test.py
  src/test/int/python/repomap_kg/ops/multi_source_refresh_guard.int.test.py
  src/test/int/python/repomap_kg/source_ingestion/slice14_staging_lifecycle.int.test.py
  src/test/int/python/repomap_kg/storage/scale13_actual_refresh_path.int.test.py
  src/test/int/python/repomap_kg/storage/arch2c_staging_observability.int.test.py
```

Unit 2 (first-use workflows):

```text
python3 tools/run_tests.py --suite unit --no-coverage --
  src/test/unit/python/repomap_kg/ops/first_use_workflow_support.unit.test.py
python3 tools/run_tests.py --suite int --no-coverage --pg-container-port 55433 --
  src/test/int/python/repomap_kg/ops/first_use_local.int.test.py
  src/test/int/python/repomap_kg/ops/first_use_server.int.test.py
  src/test/int/python/repomap_kg/ops/first_use_mixed.int.test.py
  src/test/int/python/repomap_kg/cli/sqlite_local_operator_workflow.int.test.py
  src/test/int/python/repomap_kg/cli/lexical_cli_roundtrip.int.test.py
```

`retrieval/context_evaluation.int.test.py` is named as a non-duplication
reference only. It is not selected, because it runs evaluation-capability
arms and the scope keeps evaluation unexecuted.

The following are not run:

- any complete unit, integration, smoke, staging, system or combined
  population;
- Python coverage;
- a native parser;
- an image build or acquisition;
- the evaluator, or the held-out tasks.

## Acceptance

1. Both units' selectors pass. These checks pass for changed files: Ruff, mypy,
   compileall, the file-length profile, the retained-Python ratchets, the
   privacy and topology checks, and both diff checks.
2. Output from every existing command, and MCP and packet schemas, are
   byte-identical. No CLI flag, JSON field or refusal is added.
3. Spies on the real staging-resource capture path prove that reporting does
   not activate extra SQL sampling. Source inspection confirms the view never
   constructs `StagingMeasurements`; independently selected events stay opt-in.
4. Local imports no Psycopg, Docker, parser or enrichment module.
5. No test or document sums report values or applies a threshold to them.
6. `portable_refresh.py` is at or below 399 lines and every other owner at or
   below 400, with no retained-debt growth.
7. The exit record binds source hashes and makes no efficiency, W7, W6,
   installed or release claim.

## Stop conditions

Stop and report to the parent, without widening scope, if:

- a hook can only be placed inside an `except` or `finally` block, would
  violate placement rules P1–P4, or would reorder the lock, reconciliation,
  arming, settling or terminal marking;
- an injected interrupt test shows a committed or terminal-accepted
  publication reported, marked or settled as failed or cancelled;
- `portable_refresh.py` cannot reach 399 lines or fewer through this
  extraction, or the extraction would break a patch seam;
- a metric needs SQL, a source or artifact read, a manifest parse, process
  sampling, a worker protocol field, a dependency or a new vocabulary;
- an existing owner test must change its expected output;
- a concurrent or empty-scope expectation has no current owner to bind to;
- a required integration selector is refused or unavailable (a named blocking
  gap);
- the work would need a complete suite, coverage, a native parser, a build or
  an acquisition.

## Source discrepancies recorded, not fixed

- `refresh.py:136–158` labels every converted `KeyboardInterrupt` as
  `rolled_back`, even when it arrives after the staged publisher has
  returned. Likewise, 218–240 labels every failure that is not commit-unknown
  as `not_started`, even when it is raised inside publication. The view copies
  neither label, and fixing them is outside this milestone.
- The design2 ADR stated that a raising staging sink never fails the
  operation. Source contradicts that (see the verified facts).
- Design2 also claimed no sealing cap. In fact, manifest limits exist and are
  checked only after the sealing I/O.
- The design3 producer narrative said `--jobs 1` is absent from the testing
  standards. `docs/contrib/testing-standards.md:72` cites it for the D12
  core-image profile, and the runner default is already `"1"`
  (`tools/runner_arguments.py:129–134`). The selectors omit it as redundant,
  not as unknown.

## Size and coverage forecast

- **Production:** about 850 net lines.
- **Tests:** about 3,500 lines.
- **Docs:** about 300 lines.

That is about 4,700 meaningful lines, below the operator's 10k–100k batching
aim. This is a justified miss, not padding. The parent decides whether to
batch another selected epic before a public campaign.

The new real-boundary owners exercise refresh, staging, lexical and context
branches that count toward the open CI122 deficits:

- unit: 34 branches to 87%;
- integration: 463 branches to 82%.

Thresholds, denominators and inventory are unchanged, and scoped passes prove
no future coverage. This design allocates no campaign, start 34, native
command or transfer.

## What would make this design wrong

- **Monotonic and process-clock spans are not useful.** If they mislead
  without memory data, the view needs a per-operation memory method, which is
  a separate decision.
- **The normal-path-only hooks lose too much.** If operators need durations
  of failed stages, a different contract is needed, and it must re-specify
  exception precedence.
- **Observed hook precedence matters.** Rule 5 uses a separate observed
  wrapper. Default calls preserve the original cancellation owner; observed
  begin/finish interrupts propagate outside it. If that opt-in distinction is
  unsuitable, a new precedence decision is required before broader exposure.
- **The internal-only view is not useful.** If operators need it without a
  contributor, a public CLI contract decision follows.
- **The ledger is not a sufficient proxy for context cost.** If freshness file
  I/O dominates, context cost is under-reported.

## Deferred (parent-owned)

- public exposure of the view;
- numeric budgets, governance or SLOs;
- worker-reported counters and RSS;
- the lexical query, revoke, vector, Rust and coordinator views;
- staging duration projection;
- a sealing I/O cap;
- the namespace19042 int32-ID limit;
- Local Rust and full W6;
- held-out criteria;
- installed or W8 qualification.
