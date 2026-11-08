# REPOMAP-CLOE-RESOURCE-GOVERNANCE2 Exit: call-owned resource governance

## Disposition

Source implementation and scoped proof candidate; hosted successor NOT
ACCEPTED. CI131 qualified only source parent
`52c60169303458905d11c1f307504ec9ff3ebe4b`; this successor is not qualified by
it. ADR 0173 and its contract were accepted for implementation after two
independent design reviews. The dispatcher-owned independent work review ran
once; its blocker and advisories are dispositioned below and the affected
scoped proofs were re-run. The final integrated candidate is frozen for a separate readonly independent
review after the parent proofs and CI132 binding below. Its acceptance is
recorded in the exact-commit local report before publication.

## Implemented scope

- **Epic 1, sealing accounting and refuse-first governance.** One call-owned
  `SealingMeter` threads through every named reader of the parent sealing
  boundary (traversal, R1-R4 classification and hashing, R5 stable capture,
  R6 copy, W1 store writes, R7/R7c readback and collision comparison, the
  second scan and the manifest). Admission precedes each read, write, open,
  entry and fsync; counters never reset. Observe-only meters keep incumbent
  order and outcomes; governed meters add a metadata preflight with the
  existing inventory predicate, planned `6S+1`/`S` refusal, a finite
  directory-entry ceiling (caller value or 100,000) and bounded retained
  classification text. Default calls retain incumbent I/O: every new keyword is
  forwarded only when set, and required P6/P9 facade seams are preserved.
  The helper-reexport patch limitation is explicitly recorded as F6 below.
- **Epic 2, owned-worker attribution.** Opt-in usage-collecting POSIX launches
  reap the exact child through one `wait4` owner, set `Popen.returncode`, keep
  that pid's rusage and probe the worker's process group. Unknown status after
  `ECHILD` is `ProtocolError("worker_status_unknown")`, never success. Injected
  factories and launch tickets are refused before launch. Only these launches
  get a bounded kill-first interrupt cleanup with one shared deadline, pipes
  closed before joins and the original exception re-raised.
- **Epic 3, controls, plan and v2 delivery.** `cloe-resource-view-v2` is a
  separately versioned record family (16,384 bytes, 48 metrics, 24 limits);
  v1 domains, tables, bytes and bounds are unchanged. New CLI surfaces:
  `--resource-report-schema {1,2}`, `--sealing-max-*` on direct
  `ops refresh-graph`, and read-only `ops sealing-plan`. Server refusals use
  `error_category=resource_budget_exceeded` with diagnostic
  `sealing-budget-exceeded` only for a terminal refusal with positive
  not-entered proof; Local prints `sealing-budget-exceeded:<limit>`.

Narrow behavior-preserving extractions keep the 400-line profile:
classification and traversal selection left `graph/discovery.py` (605 to 323
lines) with same-name re-exports and the `discovery.classify_path` seam; the
`PortableCapture` record and attempt path helpers left `ops/portable_refresh.py`
with rebound names; `ops/refresh.py` ends at 400 lines.

No dependency, configuration key, SQL, DDL, role, image, MCP field, worker
frame, default numeric ceiling or default/ticketed interrupt change is added.

## Recorded discrepancies

- ADR 0162's context says sealing reads roughly one of five body reads; the
  source performs six full reads for a new object and eight on a collision
  (store readback and collision comparison were omitted). ADR 0162's decision
  is unaffected.
- `tools/ci/cloe-resource-report1-exit.md` names `ops resource check/show`;
  the parser (authoritative) defines `ops resource-report check|show`.

## Work-review dispositions

- **B1 (accepted, amended source).** `graph/discovery.py` is a call root of
  the D12 Rust-qualification import closure (`tools/ci/qualification_rust_closure.py`),
  which follows function-body and `TYPE_CHECKING` imports. The feature
  candidate's `TYPE_CHECKING` meter import and in-function metered imports
  reached `artifacts` and then the forbidden `common_lore_index.storage`, so
  the resolver refused (`forbidden_host_import`). The meter-bound walker and
  readers are now chosen by the sealing caller: `discover_repository` takes an
  optional graph-local `io_hooks` protocol, and `_capture_inventory` passes
  `graph._metered_discovery.MeteredDiscoveryHooks(io_meter)` only when a meter
  exists. The dynamic `multi_source_pipeline.discover_repository` seam and the
  `discovery.classify_path` seam are unchanged. The closure now resolves
  without `artifacts` or `ops` paths.
- **D12 manifest refresh (completed by parent).** The exact native source set
  is now 266 paths: 260 host paths and six unchanged guest payloads. The only
  added paths are graph/_discovery_classify.py and graph/_discovery_selection.py.
  Import containment remains unchanged. The two previously held closure
  unit checks and the import-closure integration owner pass after fresh
  CI132 campaign binding; no prior native report is repinned.
- **F2 (accepted).** The waited-grandchild proof now compares against a
  witness written by the worker at its last instant (its own and
  waited-children CPU through a descriptor opened before the authority
  guard). It requires the parent's `wait4` total to be at least their sum, so
  excluding the grandchild cannot pass.
- **F3 (accepted).** The opt-in interrupt handler no longer signals a closed
  boundary, or a reaped leader whose group probe is empty, because that group
  id may be reused. This is the same probe-before-kill rule as incumbent
  `ManagedProcess.cleanup`.
- **F4 (accepted).** The Python budget guard refuses any `ResourceObserver`
  instance (including subclasses) whose schema is not v2. Exact-type feeding
  of notes is unchanged.
- **F5 (accepted).** `--resource-report` help now names v1 unless
  `--resource-report-schema 2`.
- **F6 (recorded residual).** After the P6 move only `discovery.classify_path`
  remains a patch seam for classification. Patching
  `discovery.first_line`, `content_hash`, `is_go_generated_file` or
  `detect_language` no longer affects `classify_path`. No repository test
  depends on those seams.
- **F7 (recorded residual).** The governed preflight checks count, path and
  total-byte limits per file. When several ADR 0162 limits are exceeded at
  once, it can report a different first limit than `_validate_inventory_shape`
  would. The messages are the same, and default mode is unaffected.

## Observed verification

Feature proof used only the canonical wrapper
`tools/run_tests.py --suite unit|int --no-coverage --jobs 1`. Integration ran
in the repository-owned disposable container sandbox with PostgreSQL port
55433. After the work-review revisions, the final exact selectors below passed
794 unit cases (41 owners) and 97 containerized integration cases (15 owners),
with no skip, xfail or deselection, source unchanged during each run and owned
cleanup proven. Earlier scoped runs that exposed test-expectation and typing
defects are retained privately, not relabelled. The two D12 Rust-qualification
closure owners were run separately and fail only on the pending manifest
refresh described under the review dispositions.

Integration proves real behavior, not subject counters alone: exact meter
counters against independently derived tree expectations (including an
in-seal collision, empty files and the `6S+m` / `8S+3m` totals), a sentinel
file after the budget point never passed to `os.open` (witnessed at the test
boundary, independent of user identity), metered and default manifests and
candidates identical, real Local and Server CLI v2 committed, refused (with
unchanged accepted state) and v1-default reports, and a test-support worker
proving the CPU lower bound, a 64 MiB peak RSS, Linux waited-grandchild
inclusion, a flagged remaining group member, rusage after `SIGKILL`,
Popen-compatible return codes and no surviving group member after an injected
parent `KeyboardInterrupt`. Darwin values are labelled platform-defined; no
native Windows or Darwin qualification is claimed.

The retained-Python static owner passed with complete enforcement: 22 new
product modules, 17 test owners and 2 support modules were admitted exactly
(ownership digest, selection and an append-only scope record), the stale
605-line `graph/discovery.py` ceiling was removed after its decrease, and no
debt, ceiling, denominator, gate or suppression was added. Topology,
file-length, suppression-policy, public-export, compileall, whitespace and
diff checks passed.

No complete local unit, integration, smoke, staging, system or combined suite
was selected; no complete-suite override exists. No local coverage,
application/SDK build, image pull, native qualification or live graph
operation ran. Hard unit 85/85 and integration 80/80 gates are unchanged; the
desired 87/82 margins remain pending hosted measurement.

### unit

- `src/test/unit/python/repomap_kg/artifacts/sealing_meter.unit.test.py`
- `src/test/unit/python/repomap_kg/artifacts/metered_io.unit.test.py`
- `src/test/unit/python/repomap_kg/artifacts/store_metered_put.unit.test.py`
- `src/test/unit/python/repomap_kg/artifacts/source_sealer_governance.unit.test.py`
- `src/test/unit/python/repomap_kg/graph/metered_discovery_equivalence.unit.test.py`
- `src/test/unit/python/repomap_kg/coordinator/usage_reaper.unit.test.py`
- `src/test/unit/python/repomap_kg/coordinator/protocol_interrupt_cleanup.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/resource_view_v2_contracts.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/resource_view_v2_observer.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/resource_report_v2_codec.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/sealing_budget_cli.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/sealing_plan.unit.test.py`
- `src/test/unit/python/repomap_kg/artifacts/source_sealing_io.unit.test.py`
- `src/test/unit/python/repomap_kg/artifacts/source_sealer.unit.test.py`
- `src/test/unit/python/repomap_kg/artifacts/source_sealer_admission.unit.test.py`
- `src/test/unit/python/repomap_kg/graph/discovery.unit.test.py`
- `src/test/unit/python/repomap_kg/graph/discovery_package_structure.unit.test.py`
- `src/test/unit/python/repomap_kg/graph/multi_source_capture.unit.test.py`
- `src/test/unit/python/repomap_kg/graph/multi_source_pipeline.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/resource_view_contracts.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/resource_view_observer.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/resource_report_codec.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/resource_report_cli.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/portable_refresh_outcome_custody.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/portable_refresh_routing.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/refresh_outcome_witness.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/sqlite_local_refresh.unit.test.py`
- `src/test/unit/python/repomap_kg/ops/multi_source_refresh_guard.unit.test.py`
- `src/test/unit/python/repomap_kg/coordinator/process_supervision.unit.test.py`
- `src/test/unit/python/repomap_kg/coordinator/protocol.unit.test.py`
- `src/test/unit/python/repomap_kg/coordinator/protocol_core_boundaries.unit.test.py`
- `src/test/unit/python/repomap_kg/coordinator/portable_worker_protocol.unit.test.py`
- `src/test/unit/python/repomap_kg/cli/sqlite_local_refresh_ops.unit.test.py`
- `src/test/unit/python/repomap_kg/cli/main_boundaries.unit.test.py`
- `src/test/unit/python/repomap_kg/cli/context_dispatch.unit.test.py`
- `src/test/unit/python/repomap_kg/cli/core.unit.test.py`
- `src/test/unit/python/repomap_kg/cli/package_structure.unit.test.py`
- `src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py`
- `src/test/unit/python/repomap_kg/coordinator/protocol_boundaries.unit.test.py`
- `src/test/unit/python/repomap_kg/coordinator/portable_worker_protocol_refusals.unit.test.py`
- `src/test/unit/python/tools/ci/retained_python_projection.unit.test.py`

### integration

- `src/test/int/python/repomap_kg/artifacts/sealing_governance.int.test.py`
- `src/test/int/python/repomap_kg/coordinator/usage_reaper.int.test.py`
- `src/test/int/python/repomap_kg/ops/resource_report_v2_local_cli.int.test.py`
- `src/test/int/python/repomap_kg/ops/resource_report_v2_server_cli.int.test.py`
- `src/test/int/python/repomap_kg/ops/sealing_plan_cli.int.test.py`
- `src/test/int/python/repomap_kg/artifacts/source_sealer_admission.int.test.py`
- `src/test/int/python/repomap_kg/artifacts/navigation33_store_stream_and_sealing.int.test.py`
- `src/test/int/python/repomap_kg/ops/resource_view_local.int.test.py`
- `src/test/int/python/repomap_kg/ops/resource_view_server.int.test.py`
- `src/test/int/python/repomap_kg/ops/resource_report_local_cli.int.test.py`
- `src/test/int/python/repomap_kg/ops/resource_report_server_cli.int.test.py`
- `src/test/int/python/repomap_kg/ops/resource_report_offline_cli.int.test.py`
- `src/test/int/python/repomap_kg/ops/first_use_local.int.test.py`
- `src/test/int/python/repomap_kg/ops/first_use_server.int.test.py`
- `src/test/int/python/repomap_kg/ops/first_use_mixed.int.test.py`

## Hosted CI and publication boundary

No push, workflow dispatch, rerun or pull-request change was made. A future
single campaign requires its own parent-owned final-source binding; the
consumed CI131 grant is not reusable. Main and release boundaries are
unchanged. Native Windows, installed, release and full W7/W6 acceptance are
not claimed.


## Parent proof completion and fresh campaign preparation

The parent added real alias/retry tests with independent native read and inode
witnesses, verified canonical inventory deduplication and the sufficient
`8S+m+1` budget for a large aliased body, and proved cumulative charging after
a real signature-change retry. Independent accepted-marker/receipt readbacks
now prove Local and Server publication state unchanged across budget refusal.
Both real report owners assert all worker projections. Two additional guarded
plan CLI cases independently assert exact Local/Server counts and witness no
source-body open, database connection, worker/subprocess, lock or state write.

Passing exact parent integration selectors (no coverage, existing sandbox):

- artifacts/sealing_alias_retry.int.test.py (4 cases);
- ops/resource_report_v2_local_cli.int.test.py (4 cases);
- ops/resource_report_v2_server_cli.int.test.py (1 case);
- ops/sealing_plan_boundary_witness.int.test.py (2 cases).

Paths above are under src/test/int/python/repomap_kg. The first three owners
passed together (9 cases); the guarded plan owner passed both cases separately.
The added Local unit-label expectation was corrected from ns to the closed
report spelling nanoseconds; the earlier failed receipt is retained privately.
Strict test-owner enrollment preserves every prior inventory row and its order.
Static checking passed after these additions. No product source changed for
this parent proof completion; prior source-checkpoint receipts are reconciled
by exact product/support and selected-test hashes before final acceptance.

Independent refreshes allocate new IDs/timestamps, so ordinary-output shape
checks remain distinct from fixed-result/clock v1 byte-compatibility checks.
No identities are normalized away to fabricate byte equality.

ADR0174 defines conditional preparation for one fresh CI132 attempt. The exact
source census, D12 context, 266-path native manifest, approval/reservation,
postbind proof and frozen independent review must be current before the one
staging push. No old native result is repinned. Hosted feedback is still pending.

## Parent post-binding proof and publication candidate

The fresh CI132 candidate has a source-derived 864-file D12 context. Approval,
nonce, reservation, native manifest and all six campaign owners are bound to
this candidate. Every inherited ledger root/list prefix is preserved; the
authenticated CI131 pass is appended before the new reservation. Immediate
predecessor and future campaigns remain refused. The current caps are 43
application starts, 12 native AMD Rust commands and 28 wheel transfers. This
one campaign permits no CI133, automatic retry, second push or main promotion.

Canonical scoped post-binding proof used --no-coverage:

- Unit: 46 passed across tools/ci/d12_system_grant.unit.test.py,
  d12_system_proof_host.unit.test.py, d12_candidate_context.unit.test.py,
  qualification_rust_closure.unit.test.py and qualification_rust.unit.test.py
  (all under src/test/unit/python).
- Containerized integration: 11 passed across the three exact admission nodes
  test_system_hold_proof_capture_and_child_secure_writer,
  test_sandbox_dispatch_blocks_system_suite_without_valid_proof and
  test_cross_process_flock_and_o_excl_race_and_execute_system_run in
  runtime/d12_system_admission.int.test.py, plus
  extractors/rust_pilot/qualification_import_closure.int.test.py and
  runtime/d12_json_report_bounds.int.test.py
  (all under src/test/int/python/repomap_kg).

These diagnostic owners perform no native qualification or application/SDK
build. Source/index preservation and owned cleanup were verified. The feature
checkpoint passed 794 scoped unit cases and 97 containerized integration cases;
the parent added four alias/retry cases and two plan-boundary cases, and
strengthened five existing real CLI cases with independent state readbacks.
The distinct feature integration cohort is 103 cases; repeated passes are
not added together.

Complete local unit, integration, smoke, staging, system and combined suites
were intentionally unselected. No local Python coverage claim is made. The
prior CI131 branch measurements were 86.57% unit and 80.07% integration; the
87%/82% desired margins remain for hosted measurement. Hosted, installed,
release and full W6/W7 acceptance remain separate.

## Nonblocking final-review dispositions

- Exact-size probing readers can consume their available body bytes and then
  refuse the EOF probe. Counters remain bounded; the existing contract and
  size-plus-one tests explicitly retain this conservative behavior.
- Elapsed timing includes capture setup and retention-lock waits as documented
  in ADR0173 and the operational guide; their I/O remains outside the counters.
- The eager capture-to-artifacts import remains outside the native discovery
  closure. Guarded Local and native containment checks pass; lazy import
  cleanup is deferred.
- The exact final source identity is reconciled through the recorded doc and
  test-only amendments; the pre-binding census is not the final tree.

A parent rendering defect split Unicode line separators while preparing the
review patch. The native read audit uses LF-only lines, and a focused second
review receives the three exact affected source/test files and corrected
views. No product or test bytes changed for this review-view correction.
