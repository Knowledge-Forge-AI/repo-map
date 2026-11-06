# ADR 0159: Resource view and first-use workflows

## Status

Accepted for bounded implementation in phase
`REPOMAP-CLOE-RESOURCE-EXPERIENCE1` under the operator's 2026-11-06 roadmap
continuation. Independent design3 review found no blocker; its seven advisory
corrections and the parent clarifications below are adopted. The operator's
temporary `claude_only` APGR checkpoint route applies to this milestone only.
This record grants no complete local suite, coverage, acquisition, native
parser command, image build, public campaign or release promotion.

### Parent implementation clarifications

- Preserve the default Server exception-handler and return layout. A separate
  observed wrapper may call that owner and finish outside its handlers; do not
  introduce the design draft's default-path interrupt-window change.
- Unbegun reports use null operation/backend with `not_recorded` outcome and
  incomplete/degraded instrumentation; they never invent an operation.
- Worker terms describe the selected supervised invocation, not independent
  proof that an operating-system process started. Reuse/replay omit these rows.
- Manifest caps apply only after the manifest has actually been constructed
  and validated. Before that point their applicability is unknown.
- A context deadline taken from an owner constant is the owner ceiling, not
  evidence of a caller's possibly lower selected deadline. Without its ledger,
  the effective selected deadline remains unknown.
- Pure finish/report construction is split into `_observer_reporting.py` to
  keep each owner within its length limit. Local may import that pure sibling;
  the prohibited driver, Server, parser and enrichment imports remain excluded.
- New exact clean-owner entries require an ownership-digest and retained-set
  update with appended source-backed lineage. Existing ownership rules,
  architecture placement and all numerical debt ceilings are preserved.


## Date

2026-11-06

## Context

W7 covers two goals: measuring and governing actual expensive work, and
qualifying the first useful SQLite Local, PostgreSQL Server and mixed-material
experiences ([roadmap](../../../specs/cloe-roadmap-transition-v1.md)). The
operator selected two connected epics:

- a report-only resource view over current refresh, the existing lexical
  build and bounded context;
- reproducible source-level first-use workflows.

The selection excludes several things: new numeric policy, a public surface,
a dependency, a schema, worker authority and installed qualification.

The [specification](../../../specs/cloe-resource-experience-v1.md) lists the
source facts, with line references. Nine of them shaped this decision:

- **Some controls already exist but bound less than they appear to.** Portable
  worker limits are parent-supplied. Manifest limits (`ArtifactLimits`) are
  checked only after sealing has read and stored every file, so no limit
  bounds sealing I/O. Lexical projection limits and statement timeouts, and
  the context `WorkLedger` ceilings and byte budget, are enforced by their
  owners.
- **Some values already exist and need no new work.**
  `PortableSnapshotManifest.total_files`/`total_bytes`, the validated family
  summaries, the `LexicalBuildOutcome.plan` aggregates and the packet's
  `work_ledger` are all in parent memory. A lexical refusal sets its
  aggregates to the literal 0, which is not a measurement.
- **Staging resource measurement costs SQL.** Constructing `StagingMeasurements`
  selects measured branches and resource queries. WAL and temp values are
  shared upper bounds, backend memory is the max of up to two samples, and
  client memory is a process-lifetime peak.
- **Existing staging sinks propagate `BaseException`.** `_emit` catches only
  `Exception`, the lifecycle emitters re-raise `KeyboardInterrupt`, and
  `timed` emits from `finally`. The design2 claim that a raising sink never
  fails the operation is wrong.
- **Business outcomes are not exceptions.** Server can return `failed`,
  `cancelled` or `commit_unknown` without raising. Local can replay a
  reconciled publication without capture, a worker or publication.
- **`ops/portable_refresh.py` has no room.** It is 399 lines, at the 400-line
  boundary.
- **Context needs no hook.** `build_compact_context` already accepts a
  caller-owned `WorkLedger`. A `budget_error` returns before any ledger is
  used.
- **Handlers can relabel a committed publication.** In
  `execute_portable_refresh`, the `BaseException` handler around the
  publisher marks the attempt failed. In `refresh_graph`, the
  `KeyboardInterrupt` handler returns `cancelled` with `rolled_back`. Either
  handler would reach an interrupt raised after a commit inside its `try`.
- **Existing owners already cover parts of first use.** LOCAL6 covers the
  guarded no-Psycopg Local CLI path. The lexical CLI round trip covers
  `mixed-v1` on PostgreSQL.

## Decision

1. **Internal, call-owned observer and no public surface.** A new
   `ops/resource_view/` package defines `cloe-resource-view-v1`:
   - frozen records with closed vocabularies;
   - a call-owned `ResourceObserver`;
   - pure projections.

   `refresh_local_graph`, `refresh_graph` and `build_graph_lexical_generation`
   gain an optional keyword `resource_observer=None`, and so do the internal
   `execute_portable_refresh` and `capture_portable_candidate`. Owners forward
   it only when it is set, so default calls and patch seams are unchanged.
   Context uses `project_compact_context(packet, work_ledger=None)` without
   changing `build_compact_context`.

   There is no CLI flag, CLI or MCP field, refusal, configuration key, schema,
   vocabulary, worker protocol field, receipt or durable store.

2. **Descriptive, non-additive values only.** The view reports:
   - parent monotonic stage spans;
   - inclusive parent process CPU;
   - accepted-manifest totals;
   - parent-validated bundle totals;
   - lexical plan aggregates;
   - context ledger counters, including one labeled estimate.

   Each value states its basis and availability. Worker CPU and RSS are always
   `not_observed`. Nothing is summed, and there is no total, threshold or
   lifetime-peak delta.

3. **No additional data or resource queries.** Reporting reads only clocks and values already in
   memory. The view never constructs `StagingMeasurements` and has no staging
   tier. A pure `project_staging_resources` projects four resource
   categories, but only from events the caller collected through its own,
   independently selected `staging_measurements`.

4. **Existing controls attributed truthfully.** Limit rows name each existing
   control's owner, enforcement kind and whether it applied in this call. That
   covers:
   - the worker deadline actually passed to the worker, and the worker's
     artifact and bundle caps;
   - the post-capture manifest caps;
   - an `absent` sealing I/O cap;
   - the lexical limits and timeout;
   - the context ceilings and budget.

   Coordinator-only and polling-only limits are never reported for direct
   refresh.

5. **Outcome is separate from instrumentation.** `outcome` is copied only
   from closed owner fields. `instrumentation` is `complete`, `incomplete` or
   `degraded`. Only `published` and `committed` denote a publication made by
   this call. A replay, failure, cancellation, commit-unknown or refusal never
   becomes success.

6. **Exception precedence.** Hooks run only on the normal path, never in
   `except` or `finally` blocks.
   - An operation exception propagates with the same identity and chaining as
     today.
   - Hook bodies catch only `Exception`, which degrades the report.
   - `KeyboardInterrupt` and `SystemExit` are never caught by the view.
     Existing owners' handlers apply unchanged.
   - A hook's interrupt reaches only the handlers that an interrupt at that
     statement boundary reaches today. No hook sits after a commit or a
     terminal-accepted mark inside a `try` whose handler could mark, settle or
     relabel it. The publication span therefore ends at outcome recording,
     outside every owner handler.
   - Server keeps the original handler in `_refresh_graph_call`. The public
     wrapper returns directly through that owner when no observer is supplied.
     For observed calls only, `begin` runs before the owner and `finish_server`
     runs after it returns, outside its cancellation handler. An interrupt in
     that finish hook propagates without relabeling a committed publication.

   Terminal construction happens once, on the first `report()` call, and later
   reads return the identical frozen object. Reuse, use before `begin` and
   cross-thread use degrade the report and never refuse. Degradation clears
   any unsealed outcome to `not_recorded` and limit applicability to unknown;
   a prior call is not current evidence.

7. **A real extraction before instrumentation.** A behavior-preserving step
   moves three things into the new sibling `ops/_portable_worker_terms.py`:
   - `_worker_references`;
   - the leaf-limit derivation;
   - the named artifact-cap constant.

   Its dependencies are verified and create no cycle. The names stay bound in
   `portable_refresh`, so patch seams and the two existing by-name imports of
   `_worker_references` are preserved. The existing owners of those seams are
   adjacent selectors. The planned result is about 375 lines. More than 399 is
   a stop condition.

8. **First-use workflows reuse existing commands.** Local, Server and mixed
   workflows run over public `mixed-v1` homes through existing commands.
   - Local runs with Psycopg unavailable.
   - Server uses core PostgreSQL and native FTS lexical.
   - Email and feed material stays metadata-only.
   - The held-out tasks stay unexecuted.

   Each first-use owner asserts only a stated delta over the existing owners
   and reuses their steps as setup. A delta that an existing owner already
   asserts is dropped and reported, not duplicated. Helpers stay in test
   support. A new operator guide labels its examples *source-level; installed
   proof pending*.

9. **Two units.** Unit 1 is the resource view, with its extraction, unit
   owners and four real-boundary integration owners. Unit 2 is the workflows,
   with one unconditional unit owner for its expectation and root-guard
   helper, three integration owners, the guide and the exit record. Each unit
   has its own exact `--no-coverage` selectors with adjacent existing owners,
   defined in the specification.

## Alternatives considered

- **A `--resource-view` CLI flag or a JSON field.** Rejected, because it would
  need a CLI contract decision.
- **A staging tier, or always constructing `StagingMeasurements`.** Rejected,
  because it adds SQL and changes the measured branches.
- **Hooks in `finally` blocks, or a callback sink.** Rejected, because either
  could replace an in-flight exception or let caller code run inside an
  operation.
- **`RUSAGE_SELF` or `RUSAGE_CHILDREN` sampling, or a lifetime-peak delta.**
  Rejected. Each would be either process sampling or false attribution.
- **Per-entry manifest sizing or an extra parse.** Rejected as unnecessary,
  because the totals already exist.
- **A generic telemetry framework or OpenTelemetry.** Rejected. It needs a
  dependency and invites source-derived attributes.
- **Instrumenting lexical query and revoke, staging durations or vectors.**
  Deferred, because they are outside the selected minimal scope.

## Consequences

- Contributors and tests can read honest, bounded costs and the controls that
  apply. Default work, outputs and enforcement are unchanged.
- Local stays independent of Psycopg, Docker, parsers and enrichment. A
  boundary test enforces this.
- Real-boundary owners add useful coverage toward the CI122 deficits (34 unit
  and 463 integration branches). Thresholds and denominators are unchanged.
- Two existing labels are recorded as discrepancies, and neither is fixed.
  `refresh.py` reports a converted interrupt as `rolled_back`, and every
  failure that is not commit-unknown as `not_started`.
- The forecast is about 4,700 meaningful lines, below the 10k–100k batching
  aim. That is reported as a justified miss. No campaign, start 34, native
  command or publication is allocated.
- Numeric governance, public exposure, worker attribution, the sealing I/O
  cap, the namespace19042 int32 limit, Local Rust, full W6, held-out criteria
  and W8 qualification remain open.
