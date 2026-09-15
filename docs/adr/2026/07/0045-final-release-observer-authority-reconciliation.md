# ADR 0045: Final-Release Observer Authority Reconciliation

## Title

Final-Release Observer Authority Reconciliation

## Status

Accepted — Outcome A, Decision Category B (ADR 0044 retained and precisely
amended)

## Date

2026-07-25

## Context

ADR 0044 selected a hybrid startup architecture: an isolated worker owns slow
local and database resource preparation, and the parent retains the continuous
observer, evidence acceptance, freshness, final ownership proof, atomic child
release, and terminal authority. SCALE28-FIX4 implemented it. TEST-COV5C
qualified it. SCALE28-FIX5 and SCALE28-FIX6 then corrected two observer
cancellation defects, and TEST-COV5D and TEST-COV5E characterized what remains
broken.

Four consecutive phases have now closed Outcome B on the same surface: the
observer deadline tuple. FIX5 found the 40 ms cancellation-request bound
unreliable. TEST-COV5D confirmed it. FIX6 pre-registered a replacement tuple
(`C120-420`), proved it reliable in isolation, and then rejected it on
configured caller budgets. TEST-COV5E confirmed the rejection and additionally
found that the accepted default loses strict server precedence whenever only
440 ms of caller budget remain.

Each phase treated this as a *tuple selection* problem and searched for better
numbers. This ADR finds that the tuple is not the defect. The defect is that
the final-release path has **two unrelated deadline authorities** and derives
per-operation budgets from neither of them coherently. No tuple can be correct
under that structure, which is why four selection attempts failed.

## Problem

Can ADR 0044's hybrid startup architecture preserve bounded observer
cancellation, strict server/client ordering, independent operation and
cancellation-request settlement, two new final stable ownership samples,
freshness, source-sequenced failure causality, and atomic child release within
one coherent final-release authority?

**Yes** — but only after a bounded amendment. The retained hybrid architecture,
the preparation worker, the receipt and freshness contracts, the state machine,
and every preserved authority remain valid and unchanged. What must change is
the derivation of observer caller budgets and the placement of the
cancellation-request reserve.

## Evidence Hierarchy

This ADR used the following order, and records disagreements rather than
silently resolving them.

1. **Current production source at `110925c3`** — `tools/scale28_observer_deadlines.py`,
   `tools/scale28_backend_observer_session.py`, `tools/scale14_backend_monitor.py`,
   `tools/scale28_hybrid_startup.py`, `tools/scale28_preparation_authority.py`,
   `tools/scale28_preparation_policy.py`, `tools/scale14_actual_refresh_supervisor.py`.
2. **Accepted ADRs and additive amendments** — ADR 0043, ADR 0044 and its five
   additive corrections.
3. **Current executable tests** — the TEST-COV5E characterization support module
   and the FIX6/TEST-COV5E unit and integration selections.
4. **Status records and implementation plans** — 00661, 00663, 00664, 00665, 00666.
5. **Commit patches** — `4c04f6d4`, `dbe49124`, `dfa9f7c2`, `3e5c564a`, `110925c3`.
6. **Commit messages and transient reports.**
7. **External primary documentation** — recorded by SCALE28-FIX6 for Psycopg
   3.2.12, libpq 18.4, PostgreSQL 18. This ADR adds no new external claim and
   relies on FIX6's recorded citations, which remain accurate and sufficient.

Current implementation proves what exists. It does not prove what is normative.
Where source and durable records disagree, the disagreement is named below and
given an explicit disposition.

## Normative Authority Table

| Rule or value | First source | Later sources | Current implementation | Current test expectation | Classification | Consistent or drifted | ADR3 disposition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 500 ms ownership handoff | SCALE15 / TEST-COV3 / SCALE28-FIX1 `_OWNERSHIP_HANDOFF_SECONDS` | Unchanged through FIX6 | `scale14_backend_monitor.py:26` = `0.5`; used as the whole final two-sample window *and* every per-operation caller budget | `CallerContext.maximum_budget_ms = 500`, `handoff_ms=500` | **Historical value** promoted to de facto architecture by reuse | **Drifted** — never derived from any ADR | **Superseded.** Ceases to be an independent authority; final-release budgets derive from the final-release window, prefinal budgets from an explicit prefinal budget |
| 500 ms caller operation deadline | SCALE28-FIX4 `ObserverDeadlinePolicy.caller_operation_timeout_seconds` | Retained by FIX5, FIX6, TEST-COV5E | `0.5` | `caller_operation_ms=500` | **Selected implementation default** | Consistent with itself; coincidentally equal to the unrelated handoff constant | **Retained** as the default *prefinal and active* caller budget only |
| 600 ms final-release policy | SCALE28-FIX4 selected policy (`final_release_timeout_ms=600`) | FIX6 calls it "the 600 ms final-release **ceiling**"; TEST-COV5E calls it "the retained 600 ms final-release **cap**" (`FINAL_RELEASE_CAP_MS = 600`) | `scale28_preparation_policy.py:11` = `600`; enforced by `_assert_final_window` | Treated as an immutable cap | **Selected implementation default** — FIX4's own text says it "stayed below the 5,000/10,000/**650**/100 ms architecture caps" | **Drifted** — reclassified from default to cap by FIX6 and TEST-COV5E without authority | **Retained at 600 ms and reclassified as a selected default**, now independently *derived* (see Deadline Satisfiability). FIX6 and TEST-COV5E's "cap"/"ceiling" wording is superseded |
| 650 ms final-release ceiling | ADR 0044 "Final Release Ceiling" | Restated as a live cap by FIX4's own implementation record; not mentioned by FIX6 or TEST-COV5E | Not represented in source | Not represented in tests | **Architectural maximum** | **Live and never superseded**; silently dropped from later prose | **Confirmed live.** Remains the architectural maximum. Not consumed by this decision |
| 400 ms server statement timeout | SCALE28-FIX4 `server_statement_timeout_ms=400` | Called "the 400 ms server floor" by FIX6 and TEST-COV5E | Applied session-wide via `-c statement_timeout=400ms` at connection creation | `server_statement_ms=400` | **Selected implementation default** that *functions as* a floor only because the strict-ordering invariant requires `trigger > server` | Consistent in value; its "floor" status was never derived | **Retained unchanged.** Classified as a selected default whose floor behaviour is a consequence, not an axiom. FIX7 may not lower it without configured proof and may not raise it without a new ADR |
| 450 ms client cancellation trigger | SCALE28-FIX4 | Retained through TEST-COV5E | `client_cancel_after_seconds=0.45` | `client_trigger_ms=450` | **Selected implementation default** | Consistent | **Retained** as the default trigger for fixed-budget classes |
| 40 ms cancellation-request bound | SCALE28-FIX4 | FIX5: 9/20 and 6/10 successes; TEST-COV5D: 12/20; TEST-COV5E: 15/20, 4/5 quiet, 4/5 contended | `cancel_request_timeout_seconds=0.04` | `request_bound_ms=40` | **Selected implementation default, disproved by measurement** | Consistent in value; **unqualified** since FIX5 | **Superseded.** Replaced by 120 ms (see below) |
| 120 ms cancellation-request bound | SCALE28-FIX5 characterization (10/10 at 120 ms and 160 ms; 8/10 at 80 ms; unreliable at 40 ms) | FIX6 candidate `C120-420`; rejected on caller budgets, not on reliability | Not in production | Test-owned candidate only | **Measurement result** promoted here to selected default | n/a | **Selected.** 120 ms is the smallest evidenced-reliable value and becomes the product cancellation-request bound, charged to the settlement authority |
| 570 ms `C120-420` caller deadline | SCALE28-FIX6 candidate protocol | TEST-COV5E envelope model | Rolled back; not in production | `CANDIDATE_C120_420.caller_operation_ms=570` | **Superseded value** — an artifact of requiring `caller ≥ trigger + request` | n/a | **Rejected and made unnecessary.** Under the amended reserve placement the caller budget need only contain the trigger |
| 600 ms `C120-420` handoff | SCALE28-FIX6 candidate protocol | TEST-COV5E `CANDIDATE_C120_420.handoff_ms=600` | Never applied; production `_OWNERSHIP_HANDOFF_SECONDS` remained `0.5` | Test-owned | **Superseded value** | **Drifted** — FIX6's exit says the path "shares one unchanged 600 ms authority", but production's ownership handoff is 500 ms | **Superseded.** The discrepancy is recorded in Normative Drift Findings |
| 440 ms short caller | TEST-COV5E `MINIMIZED_COMPRESSED_CALLER_MS` | — | Reproduced by `release_when_ready`: `500 − 50 poll wait − preceding execution` | `9` caller-context cases | **Measurement result of a sequencing artifact** | n/a | **Not normative.** It is the arithmetic boundary where `operation_deadlines` first violates strict precedence; the defect is the missing floor, not the number |
| 50 ms inter-sample gap | `_ownership_changed.wait(min(remaining, 0.05))` poll backoff | TEST-COV5E `REQUIRED_SAMPLE_GAP_MS = 50`, described as "the required sample gap" | An *upper bound* on a poll wait, not a guaranteed separation | Treated as a required additive term | **Historical value / sequencing artifact** — ADR 0044's 650 ms formula contains a 50 ms *transient settlement* term and **no** inter-sample gap term | **Drifted** — a poll backoff was reclassified as a required architectural separation, and conflated with a different 50 ms term | **Promoted deliberately** to an explicit 50 ms sample-separation reserve with a stated safety property (below). Value retained; status corrected |
| Two new final stable ownership samples | ADR 0044 Preserved Authorities | Retained by every successor | `release_when_ready` requires two consecutive validator-passing summaries; `mark_stable_samples` records both parent timestamps | Enforced | **Safety invariant** | Consistent | **Retained unchanged and not weakened** |
| Operation settlement | SCALE28-FIX5 | FIX6, TEST-COV5D, TEST-COV5E | `settle_operation()` called only in `run()`'s `finally` by the operation owner | Enforced | **Safety invariant** | Consistent | **Retained unchanged** |
| Cancellation-request settlement | SCALE28-FIX6 | TEST-COV5E | `record_request_outcome()` called only by the cancellation requester; `close_eligible` requires both | Enforced | **Safety invariant** | Consistent | **Retained unchanged** |
| Freshness checks | ADR 0044 + ADR2-FIX1 correction | FIX4 | `_assert_fresh` at receipt, worker settlement, clock open, transient clear, both samples, ready-to-release | Enforced | **Safety invariant** | Consistent | **Retained unchanged** |
| 800 ms freshness lease | SCALE28-FIX4 (superseding the withdrawn 1,000 ms and the unrevalidated 1,450 ms) | — | `freshness_lease_ms=800` | — | **Selected implementation default** | Consistent | **Retained unchanged** |
| 1,800 ms attempt / 4,100 ms total preparation / 2 attempts | SCALE28-FIX4 | — | `scale28_preparation_policy.py` | — | **Selected implementation defaults** below the 5,000/10,000 ms architectural maxima | Consistent | **Retained unchanged; out of scope for FIX7** |

### Explicit answers required of this ADR

- **Is 600 ms a cap or an implementation default?** A **selected implementation
  default**. FIX4 chose it and explicitly recorded that it stayed below the
  650 ms architecture cap. FIX6 and TEST-COV5E reclassified it as a cap without
  authority.
- **Is 650 ms still live architectural authority?** **Yes.** It is the
  architectural maximum. No accepted ADR text supersedes it. This decision does
  not consume it.
- **What makes 400 ms a floor, default, or both?** It is a **selected default**.
  It behaves as a floor only because the strict-ordering invariant requires the
  client trigger to exceed it. It is not itself an architectural constant.
- **Is 50 ms normative, selected, measured, or historical?** It was
  **historical** — a poll backoff bound. This ADR makes it a **selected
  implementation default** with an explicit safety property.
- **Which values may FIX7 change without another ADR?** The cancellation-request
  bound, the sample-separation reserve, the per-class caller budgets, and the
  selected final-release window — each strictly within the frozen invariants and
  with the final-release window `≤ 650 ms`. FIX7 may **not** lower the server
  statement timeout, raise the 650 ms maximum, weaken the two-sample authority,
  relax strict ordering, merge operation and request settlement, or change the
  freshness lease.

## Current Architecture

`BackendOwnershipMonitor` is the sole production owner of
`BackendObserverSession`, which owns exactly one registered observer connection
and serializes every operation on it. `HybridPreparationAuthority` owns the
preparation state machine, freshness, and the final-release window.
`release_prepared_child` composes the two.

Two deadline authorities exist and are **not** related to each other:

- `_OWNERSHIP_HANDOFF_SECONDS = 0.5` (`scale14_backend_monitor.py:26`), a
  SCALE14/15-era module constant, is passed as `timeout_seconds` to almost every
  `BackendObserverSession.run()` call and is *also* used as the total deadline of
  the two-sample loop in `release_when_ready`.
- `final_release_timeout_ms = 600` (`scale28_preparation_policy.py:11`) sets
  `_final_deadline_ns` in `open_final_readiness()` and is checked by
  `_assert_final_window` at `transient_ownership_clear`, `stable_sample_one`,
  `stable_sample_two`, and `ready_to_release`.

Nothing derives one from the other. The 600 ms window only *audits* transitions
after the fact; it never bounds the work that produced them.

## Final-Release Call Graph

Reconstructed from source, not from status prose. `→` denotes program order.

```text
scale14_actual_refresh_supervisor._prepare_startup
→ prepare_parent_startup_authorities                          [PREFINAL]
  → backend_monitor.startup_summary(timeout=attempt_timeout)  [SQL, 1800 ms]
  → validate_startup_summary → session.run(CONTRACT_VALIDATION, 500 ms)
  → startup.mark_backend_observer_ready()
  → prepare_startup_resources → preparation_authority.prepare()
      → worker spawn, observation frame, ACK, receipt v3,
        process settlement, _assert_fresh ×2                  [≤ 4100 ms total]
  → startup.mark_resource_authorities_ready()
  → event_pump.start(...)  → startup.mark_event_receiver_ready()
  → failure_collector check → startup.mark_failure_collector_ready()
→ release_prepared_child                                      [FINAL CLOCK]
  → preparation_authority.open_final_readiness()
        _assert_fresh; _final_deadline_ns = now + 600 ms       ← CLOCK STARTS
  → backend_monitor.pre_release_summary()
        → _live_summary(STARTUP_SUMMARY, require_stable=False)
          own fresh 500 ms deadline; loops until no ambient client,
          polling with _ownership_changed.wait(min(remaining, 0.05))
          → session.run(STARTUP_SUMMARY, remaining)            [SQL]
  → backend_monitor.validate_summary(transient_summary, ...)
        → session.run(CONTRACT_VALIDATION, 500 ms)             [NO SQL]
  → preparation_authority.mark_transient_ownership_clear()
        _assert_final_window; _assert_fresh
  → backend_monitor.release_when_ready(...)
        own fresh 500 ms deadline for the whole two-sample loop
        iteration 1: session.run(STARTUP_SUMMARY, remaining)   [SQL, sample one]
                     summary_validator(summary)
                     first_stable_sample_ns = monotonic_ns()
                     _ownership_changed.wait(min(remaining, 0.05))  ← "gap"
        iteration 2: session.run(STARTUP_SUMMARY, remaining)   [SQL, sample two]
                     summary_validator(summary)
                     stable_samples(first_ns, second_ns)
                       → _assert_final_window ×2, _assert_fresh ×2
                     before_release → mark_ready_to_release()
                       → _assert_final_window; _assert_fresh
                     session.activate_and_release(release)     [NO SQL]
                       → startup.release(); mark_child_released()
```

### Per-step authority

| Step | Owner | Thread | Connection | Serial | Contemporaneous with release? | Freshness consequence | Deadline authority | Caller budget on entry | Bounded duration | Failure category | Cleanup authority |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| preparation evidence acceptance | `HybridPreparationAuthority` | parent main | worker IPC | serial | no — may precede | sets freshness origin | `attempt`/`total` | 1,800 / 4,100 ms | worker categories | worker attempt |
| worker/process settlement | parent | parent main | none | serial | no | required before clock | `process_settlement` | 300 ms | `unsettled_process_state` | process group / Job Object |
| freshness validation | `_assert_fresh` | parent main | none | serial | **yes, repeated** | authoritative | `freshness_lease` | 800 ms | `stale preparation evidence` | refuse → settle |
| event readiness | `event_pump.start` | parent main | pipe | serial | no — revalidated | none | receiver timeout | fixed | `event_transport_*` | pump close |
| failure-collector readiness | supervisor | parent main | none | serial | no | none | none | n/a | `startup readiness` | n/a |
| transient ownership clearance | `_live_summary` | parent main | observer | serial | **yes** | in-window | `_OWNERSHIP_HANDOFF_SECONDS` **(wrong authority)** | 500 ms, independent of the window | `ambient_client_detected`, `backend_observer_failed` | session `run` finally |
| contract validation | `session.run(CONTRACT_VALIDATION)` | parent main | observer (held, unused) | serial | yes | none | `_OWNERSHIP_HANDOFF_SECONDS` **(wrong authority; no SQL)** | 500 ms | `backend_observer_failed` | session `run` finally |
| ownership sample one | `release_when_ready` | parent main | observer | serial | **yes** | `_assert_fresh(at first_ns)` | `_OWNERSHIP_HANDOFF_SECONDS` remaining **(wrong authority)** | ≈ 500 ms | `backend_observer_failed` | session `run` finally |
| inter-sample gap | `_ownership_changed.wait` | parent main | none | serial | yes | none | `min(remaining, 0.05)` | ≤ 50 ms, **not guaranteed** | none | n/a |
| ownership sample two | `release_when_ready` | parent main | observer | serial | **yes** | `_assert_fresh(at second_ns)` | remaining **(compresses)** | ≈ 440–450 ms | `backend_observer_failed` | session `run` finally |
| observer activation | `activate_and_release` | parent main | observer (held, unused) | serial | **yes** | none | none | n/a | `backend_observer_failed` | session state |
| final freshness check | `mark_ready_to_release` | parent main | none | serial | **yes** | authoritative | `freshness_lease` | 800 ms | `stale` | refuse → settle |
| atomic release | `startup.release` inside `activate_and_release` | parent main | none | serial | **yes** | terminal | none | n/a | release failure | `FAILED` state |

### Critical-Path DAG

```text
                 [clock opens: _assert_fresh, deadline = t0 + W]
                                  |
                    transient clearance read  (SQL)
                                  |
                     contract validation      (no SQL)
                                  |
                    mark_transient_ownership_clear
                                  |
                      ownership sample one    (SQL)
                                  |
                    sample-separation reserve
                                  |
                      ownership sample two    (SQL)   <-- binding operation
                                  |
                  mark_stable_samples / mark_ready_to_release
                                  |
                    activate_and_release      (no SQL)
                                  |
                          [child released]
```

There is no parallelism. Every step is serial on the parent main thread over one
serialized observer connection. The only concurrent actor is the deadline
`Timer` thread, which may run `cancel_safe()` against the same connection while
the operation owner is inside `operation(...)`.

## Critical-Path Model

Let:

- `W` = final-release window
- `S` = server statement timeout = 400 ms
- `G` = server-precedence guard
- `T` = client cancellation trigger
- `R` = cancellation-request bound
- `GAP` = sample-separation reserve
- `e_i` = success-path execution of step *i*, including its component margin

### Successful-path equation

```text
W  ≥  e_transient + e_validate + e_sample1 + GAP + e_sample2
      + e_ready_to_release + e_release + scheduling_margin
```

### Dispatch-admissibility equation (the binding one)

Every SQL-bearing in-window operation must be dispatched with enough remaining
window to preserve strict server precedence:

```text
remaining_at_dispatch(op)  ≥  B_min  =  S + G
```

The last such operation is sample two, so:

```text
W  ≥  e_transient + e_validate + e_sample1 + GAP + B_min
      + e_ready_to_release + e_release + scheduling_margin
```

### Cancellation-limitation equation

```text
operation refused at:            T                     (charged to W)
cancellation request settles by: T + R                 (charged to settlement)
close eligible at:  max(operation_settled, request_settled)
```

`R` is **not** charged to `W`, because when `T` fires the release has already
been refused. Cancellation and its settlement are cleanup work owned by
`close_with_timeout` / `wait_quiescent`.

### Remaining caller budget at each observer operation (current source)

| Operation | Budget authority today | Value | Derived trigger | Strict precedence |
| --- | --- | ---: | ---: | --- |
| registration | `connect_timeout` | 2,000 ms | n/a | n/a |
| startup summary | `attempt_timeout_ms` | 1,800 ms | 450 ms | yes |
| identity validation | `_OWNERSHIP_HANDOFF_SECONDS` | 500 ms | 450 ms | yes (but no SQL) |
| active summary | `_OWNERSHIP_HANDOFF_SECONDS` | 500 ms → remaining | 450 → 410 ms | degrades |
| event application | `_OWNERSHIP_HANDOFF_SECONDS` | 500 ms | 450 ms | yes |
| resource read | `_OWNERSHIP_HANDOFF_SECONDS` | 500 ms | 450 ms | yes |
| transient clearance | `_OWNERSHIP_HANDOFF_SECONDS` → remaining | ≤ 500 ms | ≤ 450 ms | degrades |
| ownership sample one | `_OWNERSHIP_HANDOFF_SECONDS` | ≈ 500 ms | ≈ 460 ms | yes |
| ownership sample two | remaining after gap | **≈ 440 ms** | **400 ms** | **no** |
| local/terminal settlement | supervisor remaining | ≤ 5,000 ms | n/a | n/a |

## Deadline Satisfiability

### The compression is invalid by construction

`ObserverDeadlinePolicy.operation_deadlines` has two branches. The
`caller ≥ caller_operation_timeout` branch contains a server-precedence rescue:

```python
if trigger <= self.server_statement_timeout_ms / 1_000:
    trigger = self.client_cancel_after_seconds
```

The `caller < caller_operation_timeout` branch — the branch every final-release
operation takes — contains **no such rescue**:

```python
reserve = min(self.cancel_request_timeout_seconds, caller_seconds / 4)
return caller_seconds - reserve, reserve
```

Direct evaluation against the accepted default confirms unbounded degradation:

```text
caller= 500  trigger=450.00  server=400  strict precedence: True
caller= 441  trigger=401.00  server=400  strict precedence: True
caller= 440  trigger=400.00  server=400  strict precedence: False   <-- boundary
caller= 420  trigger=380.00  server=400  strict precedence: False
caller= 300  trigger=260.00  server=400  strict precedence: False
caller= 100  trigger= 75.00  server=400  strict precedence: False
```

The policy's own `__post_init__` enforces `server < trigger < caller`, but that
invariant is checked **only on the frozen tuple** and never on the values
actually derived per caller. The 440 ms boundary is therefore not a threshold to
tune around; it is the first point at which a monotonic, unbounded, silent
inversion becomes observable. **This is the "silent unsafe compression" that
ADR 0044 and this ADR both prohibit.**

### 440 ms is a sequencing artifact, not a normative value

The exact caller that reaches it is `release_when_ready`'s second sample:

```text
500 ms window
  − ≤ 50 ms poll wait (min(remaining, 0.05))
  − first summary execution and validation
  ≈ 440 ms
```

Nothing selected 440. It is `_OWNERSHIP_HANDOFF_SECONDS` minus a poll backoff.
Because the caller budget is `deadline − now` of a window that is *also* the
per-operation budget, the last operation in any multi-operation window is
guaranteed to be compressed. **Reusing one constant as both a window and a
per-operation budget makes compression structurally unavoidable.**

### The 570 + 50 = 620 equation is incomplete and incorrectly composed

TEST-COV5E computes `required = caller_operation_ms + sample_gap_ms` and
compares it to 600. That model is wrong in three ways:

1. **It omits work.** The window also contains the transient-clearance read, the
   contract validation, sample one's own execution, `ready_to_release`, and the
   atomic release. Only sample two and the gap are counted.
2. **It double-charges the reserve.** `caller_operation_ms = 570` already
   contains the 120 ms cancellation reserve. That reserve is only spent on the
   *failure* path, after release has been refused, yet it is charged against a
   window that must also contain the success path.
3. **It compares against the wrong bound.** It uses 600 ms, a selected
   implementation default, as though it were the architectural cap. The
   architectural maximum is 650 ms.

620 is therefore a lower bound on a wrong model. **Whether 620 ≤ 650 is not the
question**, and selecting 650 because 620 is lower would fix nothing: raising
the window without fixing the derivation leaves the last operation compressed at
a higher number. 30 ms of nominal headroom under a wrong model is not meaningful
margin.

### Can one global tuple satisfy every real caller?

**Under the current model, no.** Requiring `caller ≥ T + R` with a reliable
`R = 120 ms` and `T > S = 400 ms` forces `caller ≥ 521 ms` for *every* SQL
operation. With three SQL operations plus a gap inside one window, the window
would need `≥ 3 × 521 + 50 = 1,613 ms`, far above the 650 ms maximum. This is
exactly why `C120-420` failed: it was reliable in isolation and structurally
impossible in sequence.

**Under the amended model, yes.** Removing `R` from the caller budget reduces the
per-operation requirement from `T + R` to `T`, and only the *last* operation
needs the full `B_min` remaining, because earlier operations are followed by more
window, not less.

### Derivation of the selected window

With `S = 400`, `G = 20` (matching ADR 0043's own 150 → 170 ms guard),
`B_min = 420`, `GAP = 50`, and ADR 0044-style component margins:

```text
transient clearance read (SQL, success path)       20 ms
contract validation (serialization only)           10 ms
ownership sample one (SQL, success path)           20 ms
sample-separation reserve                          50 ms
ownership sample two: minimum admissible budget   420 ms
ready-to-release + atomic release                  20 ms
scheduling / IPC margin                            60 ms
                                                 ------
required final-release window                     600 ms
```

**`W = 600 ms`.** The FIX4-selected implementation default is retained — but it
is now *derived* rather than inherited, and 50 ms of architectural headroom
remains beneath the 650 ms maximum.

### Answers to the remaining satisfiability questions

- **Is work missing from the 620 equation?** Yes — four steps, listed above.
- **Is work double-counted?** Yes — the 120 ms reserve.
- **Would a value between 620 and 650 have defensible margin?** Moot. The
  corrected derivation lands at 600. Raising the window is not required and would
  consume architectural headroom for no safety gain.
- **Can the 600 ms implementation policy remain through resequencing?** Yes —
  not by resequencing, but by relocating the reserve and adding pre-dispatch
  refusal.
- **Must some calls refuse before dispatch?** Yes, exactly when
  `remaining < B_min`. This converts a silent inversion into a bounded,
  categorised refusal.
- **Does each operation need both server timeout and client fallback?**
  SQL-bearing operations: yes — the server timeout bounds server-side execution,
  the client trigger bounds a transport stall the server cannot observe.
  Serialization-only operations: **no**, and arming a cancellation timer for them
  is actively unsafe (see below).

## Observer Operation Classes

Audit of every operation reachable through `BackendObserverSession.run()`:

| Operation | SQL? | Connection | Server precedence | Client fallback | Pre-dispatch refusal | Short-lived separate observer viable | May precede final clock | Must be fresh at release | Class |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| connection creation | startup | own | n/a | n/a | n/a | n/a | yes | no | `connection_startup` |
| registration | yes | observer | required | required | n/a (2 s) | no — identity is the authority | yes | no | `connection_startup` |
| identity validation | **no** | observer (held) | n/a | n/a | no | n/a | yes | no | `serialization_only` |
| startup summary | yes | observer | required | required | yes | no | yes | no | `sql_bounded` |
| active summary | yes | observer | required | required | yes | no | n/a (post-release) | no | `sql_bounded` |
| event application | yes | observer | required | required | yes | no | n/a | no | `sql_bounded` |
| fixed resource read | yes | observer | required | required | yes | no | yes | no | `sql_bounded` |
| transient-clearance read | yes | observer | required | required | yes | no | **no** | yes | `sql_bounded` |
| ownership sample one | yes | observer | required | required | yes | **no** — continuity of observation is the authority | **no** | yes | `sql_bounded` |
| ownership sample two | yes | observer | required | required | yes | no | **no** | yes | `sql_bounded` |
| terminal settlement | close | observer | n/a | n/a | no | n/a | n/a | n/a | `settlement` |
| fresh terminal readback | yes | **separate** | required | required | yes | already separate | n/a | n/a | `sql_bounded` |

The closed vocabulary is exactly four values. No per-call dynamic tuning is
permitted; a call selects a class, and the class selects its behaviour.

```text
connection_startup | sql_bounded | serialization_only | settlement
```

### The serialization-only hazard

`validate_summary` and `activate_and_release` issue no SQL, yet `run()`
unconditionally starts a deadline `Timer` whose expiry calls `cancel_safe()` on
the observer connection. A slow in-process validator can therefore transmit a
cancellation request against a connection with **no query in flight**. Because
the request is asynchronous, it may arrive while a *later* query is executing.
This is a latent correctness hazard, independent of any timeout value, and the
`serialization_only` class exists to remove it.

## Two-Sample And Gap Authority

| Question | Finding |
| --- | --- |
| Safety property of two samples | No transient, ambient, or unknown client exists across two *distinct* observations taken after transient clearance and before release. One sample cannot distinguish "clear" from "momentarily clear". |
| Original source | ADR 0044 Preserved Authorities and Clock Decomposition; implemented in `release_when_ready` and `mark_stable_samples`. |
| Accepted normative status | **Safety invariant.** Retained without change. |
| Is exactly 50 ms required? | **No.** No source derives 50 ms as a separation. It is `min(remaining, 0.05)`, an upper bound on a poll wait that returns *early* whenever `_ownership_changed` is set — so today the separation is not even guaranteed to be nonzero under telemetry activity. ADR 0044's 650 ms formula contains a 50 ms *transient settlement* term, which TEST-COV5E conflated with a sample gap. |
| Does it belong inside the final clock? | **Yes.** Both samples must be inside the window; the separation between them therefore is too. |
| May it overlap another readiness operation? | **No.** Overlapping would let a single observation satisfy both authorities. |
| May sample one move earlier while remaining final? | **No.** It must follow transient clearance and lie inside the final clock. |
| Can one snapshot provide both authorities? | **No.** Explicitly rejected. |
| Does any change require ADR amendment? | Changing the *value* does not. Removing the separation, reducing it to zero, allowing overlap, reusing one snapshot, or dropping sample two **does**. |

**Disposition.** The two-sample authority is retained unweakened. The separation
is promoted from an implicit poll-backoff bound to an explicit
`SAMPLE_SEPARATION_MS = 50` reserve with the stated safety property: *sample two
must be a new observation separated from sample one by at least one full
telemetry poll interval, so that a transient client appearing after sample one is
observable before release.* The reserve is a floor, not a cap; the poll may still
wake early on an ownership change, but the sample must not be taken before the
reserve elapses.

## Options Considered

| Option | Safety equivalence | Boundedness | Normative consistency | Complexity | Protocol surface | Cross-platform | Testability | Migration risk | Maintenance | Risk before SCALE29 | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A** — preserve 600 ms by sequencing alone | equal | unchanged | good | low | none | none | good | low | unchanged | leaves compression | **Rejected alone.** Resequencing cannot create the ~120 ms the reserve consumes from every caller budget. Its *goal* is achieved by the selected decision |
| **B** — use the 650 ms ceiling | equal | unchanged | good | very low | none | none | good | very low | unchanged | **leaves compression intact at a higher number** | **Rejected.** Raising the window does not add a floor to `operation_deadlines`. It consumes all architectural headroom to fix nothing |
| **C** — closed observer operation classes | **higher** — removes the serialization-only cancellation hazard | improved | good | moderate | none (private) | none | **much better** — each class independently qualifiable | low | better | low | **Selected** |
| **D** — split prefinal and final parent authority | equal if freshness revalidated | improved | good | moderate | none | none | good | moderate | better | moderate | **Partially selected** — the prefinal/final budget split is adopted; moving readiness work out of the clock is **not**, because ADR 0044 places transient clearance inside it |
| **E** — revise sample sequencing | equal only if separation is explicit | improved | corrects a drift | low | none | none | better | low | better | low | **Selected in its non-weakening form** — the separation becomes explicit; the two-sample authority is untouched |
| **F** — further observer connection isolation | **lower** — breaks one-identity registration and continuity of observation | similar | conflicts with ADR 0044 | high | new lifecycle | new cleanup paths | worse | high | worse | high | **Rejected** |
| **G** — keep the current default | **fails** — 40 ms bound unqualified since FIX5; strict precedence lost below 441 ms | unchanged | n/a | none | none | none | n/a | none | unchanged | unacceptable | **Rejected** |

### Explicitly rejected mechanisms

Dynamic or per-call timeout tuning; silent unsafe compression; lowering the
server statement timeout without configured proof; dropping sample two; ignoring
cancellation-request failure; closing under an active operation or request; blind
reconnect; external cancellation SQL; raising limits until tests pass; and
treating terminal success as erasing live uncertainty.

## Decision

**Decision Category B — ADR 0044 is retained and precisely amended.**

The hybrid preparation-worker architecture, the isolated worker, receipt version
3, the observation/ACK protocol, parent-monotonic freshness, the preparation
state machine, the two-sample authority, TEST-COV4 causality, atomic parent-owned
release, and every preserved authority in ADR 0044 remain accepted and unchanged.

Six bounded amendments are accepted.

1. **The cancellation-request reserve leaves the caller budget.** A caller budget
   bounds the client cancellation *trigger* only. The cancellation-request bound
   `R` is a separate fixed policy value charged to the settlement authority. When
   the trigger fires the release is already refused; the request and its
   settlement are cleanup.
2. **Pre-dispatch refusal replaces compression.** Every `sql_bounded` operation
   defines `B_min = S + G`. If the caller budget is below `B_min`, the operation
   refuses **before dispatch** with a closed category. A derived trigger at or
   below the server statement timeout is unreachable by construction.
3. **Closed observer operation classes are introduced**, with exactly four
   members: `connection_startup`, `sql_bounded`, `serialization_only`,
   `settlement`. `serialization_only` operations must not arm a cancellation
   timer.
4. **`_OWNERSHIP_HANDOFF_SECONDS` ceases to be a deadline authority.**
   In-window callers derive their budget from the final-release window; prefinal
   and active callers use an explicit prefinal budget. One constant may never
   again serve as both a window and a per-operation budget.
5. **The sample separation becomes explicit** at 50 ms, with a stated safety
   property and floor semantics.
6. **The cancellation-request bound is raised from 40 ms to 120 ms**, the
   smallest value FIX5 observed reliable (10/10 at 120 ms and 160 ms; 8/10 at
   80 ms; unreliable at 40 ms). This is affordable precisely because of
   amendment 1.

**The 600 ms final-release window is retained** and is now derived. **The 650 ms
architectural maximum is confirmed live and is not consumed.** The 400 ms server
statement timeout is retained unchanged.

## Normative Final-Release Contract

- **The clock starts** at `open_final_readiness()`, after a passing
  `_assert_fresh`, and after the preparation generation reaches
  `FRESHNESS_VALIDATED`.
- **The clock stops** at `mark_child_released()`, immediately after
  `startup.release()` returns inside `activate_and_release`.
- **The architectural maximum is 650 ms.** No implementation may exceed it
  without a new ADR.
- **The selected default is 600 ms**, derived above, leaving 50 ms of headroom.
- **Operations inside the clock, in order:** transient-clearance read
  (`sql_bounded`); transient-clearance validation (`serialization_only`);
  `mark_transient_ownership_clear`; ownership sample one (`sql_bounded`);
  sample-separation reserve; ownership sample two (`sql_bounded`);
  `mark_stable_samples`; `mark_ready_to_release`; observer activation and atomic
  release (`serialization_only`).
- **Operations allowed before the clock:** connection creation and registration;
  startup summary; startup identity validation; resource preparation and receipt
  acceptance; worker settlement; event-receiver readiness; failure-collector
  readiness. The window revalidates freshness; it does not re-run these.
- **Freshness revalidation** occurs at clock open, at transient clearance, at
  sample one (`at_ns = first_parent_ns`), at sample two
  (`at_ns = second_parent_ns`), and at `ready_to_release`. Unchanged from FIX4.
- **Two-sample placement:** both samples inside the clock, both after transient
  clearance, sample one never reused from a pre-clock observation.
- **Gap placement and authority:** between the two samples, inside the clock, a
  50 ms floor, never overlapping another operation.
- **Operation classes** are the closed four-member vocabulary. No dynamic tuning.
- **Pre-dispatch refusal** applies to every `sql_bounded` operation when
  `remaining < B_min`.
- **Operation settlement** is recorded only by the operation-owning path, in
  `run()`'s `finally`. Unchanged.
- **Cancellation-request settlement** is recorded only by the cancellation
  requester. Unchanged.
- **Close eligibility** requires operation settlement **and** request settlement.
  Unchanged.
- **Terminal independence:** child terminal arrival never implies live-session
  settlement; fresh terminal readback uses a separate connection and is never
  close authority. Unchanged.
- **Source-causality behaviour:** the source-created operation timeout remains
  primary; cancellation limitation and settlement limitation remain secondary.
  An earlier unrelated failure source is never overwritten. Unchanged.

## Deadline And Caller-Budget Contract

```text
S       = 400 ms      server statement timeout (session-wide, unchanged)
G       =  20 ms      server-precedence guard
B_min   = S + G = 420 ms
T_def   = 450 ms      default client trigger
R       = 120 ms      cancellation-request bound (settlement-charged)
GAP     =  50 ms      sample-separation reserve (floor)
W       = 600 ms      selected final-release window
W_max   = 650 ms      architectural maximum
B_pre   = 500 ms      prefinal and active caller budget
```

For an `sql_bounded` operation with caller budget `B`:

```text
if B < B_min:            refuse before dispatch (closed category)
else:                    trigger = min(B, T_def) if B >= T_def else B
                         reserve = R, charged to the settlement authority
invariant (must hold at every dispatch):   S < trigger <= B
```

The scaling branch, the `caller_seconds / 4` reserve, and the
`caller − reserve` trigger derivation are all removed. `B` for an in-window
operation is `final_deadline_ns − now_ns`; `B` for a prefinal or active operation
is `B_pre`.

`run()` must additionally derive its execution deadline from the budget
**remaining after operation acquisition**, not from the original
`timeout_seconds`. Today the acquisition wait and the execution timer are both
sized from `timeout`, so a contended operation can exceed the caller's declared
bound and silently overrun the final-release window; `_assert_final_window` then
refuses after the fact.

## State And Settlement Contract

The FIX5 and FIX6 corrections are retained verbatim and are not reopened:

```text
operation in flight        / operation settled          — operation owner only
cancellation request in flight / request settled        — requester only
local close requested
close eligible = operation_settled AND NOT request_in_flight
```

The cancellation callback never closes the connection. Coordinated close waits
for every required settlement fact. The settlement authority's budget must be at
least `T_def + R` so that a cancellation request begun at the trigger can settle
within it.

## Freshness Contract

Unchanged from ADR 0044 as corrected by ADR2-FIX1 and implemented by FIX4. The
parent monotonic clock is authoritative; absolute worker and parent clocks are
never compared; the conservative origin is
`observation_frame_received_parent_ns − transfer_reserve`; the lease is 800 ms;
and every listed checkpoint remains mandatory. This ADR adds no freshness change.

## Failure-Causality Contract

Unchanged. Source sequence is authoritative and there is no category priority.
Pre-dispatch refusal introduces exactly one new closed category —
`observer_budget_insufficient` — classified as a **primary** operation-boundary
failure at the `sql_bounded` dispatch point. It never overwrites an earlier
source, and it never appears as a secondary to a cancellation limitation.

## Cross-Platform Contract

Unchanged. The observer connection, deadline `Timer`, and settlement paths are
platform-neutral Python. The worker process-group and Windows Job Object /
fail-closed refusal contract is untouched by this ADR. Pre-dispatch refusal and
the operation classes introduce no platform-specific behaviour, so FIX7 requires
no new cross-platform mechanism — only that existing cross-platform coverage
continues to pass.

## Compatibility

No public CLI, MCP, coordinator protocol, SQL, schema, migration, dependency, or
runtime-configuration surface changes. Every value in this ADR is private and
fixed; none becomes public configuration. `_OWNERSHIP_HANDOFF_SECONDS` is a
private module constant with no external consumer. `ObserverDeadlinePolicy`
remains a private frozen dataclass; its field set changes, which is a private
break only.

## Consequences

- The final-release window becomes the single authority for in-window caller
  budgets, and the 500 ms handoff constant loses its accidental architectural
  role.
- The cancellation-request bound becomes reliable (120 ms) without enlarging any
  caller budget.
- Silent unsafe compression becomes structurally unreachable; short budgets
  produce a bounded, categorised refusal instead.
- A latent hazard — arming `cancel_safe()` for operations that issue no SQL — is
  removed.
- 50 ms of architectural headroom remains under the 650 ms maximum. **No further
  SQL-bearing operation may be added inside the final-release window without a
  new ADR**, because each one costs at least its execution margin and, if it is
  last, the full `B_min`.
- Four Outcome B phases are closed by one decision rather than a fifth tuple
  search.
- FIX7's blast radius is three private modules; no test-only architecture model
  is created to make the ADR appear executable.

## Superseded Statements

This ADR supersedes only the statements listed here. ADR 0044's historical text
is not rewritten.

1. **SCALE28-FIX6 exit and ADR 0044's FIX6 section** — "The 600 millisecond
   final-release **ceiling** … remain unchanged." 600 ms is a selected
   implementation default, not a ceiling. The ceiling is 650 ms.
2. **TEST-COV5E exit and ADR 0044's TEST-COV5E section** — "exceeding the
   retained 600 millisecond final-release **cap**". Same correction.
3. **TEST-COV5E** — "the **required** 50 millisecond two-sample gap". The 50 ms
   was a poll-backoff bound, not a required separation, and was conflated with
   ADR 0044's distinct 50 ms transient-settlement term. It is *made* required by
   this ADR, prospectively.
4. **TEST-COV5E** — "C120-420 requires 620 milliseconds after the mandatory
   sample gap". The equation omits four steps and double-charges the
   cancellation reserve. It is not a valid envelope.
5. **TEST-COV5E** — "A 200 millisecond request minimum cannot fit the retained
   cap: … 601 milliseconds". The impossibility follows from charging the request
   bound to the window. Under the amended contract the request bound is not
   charged to the window, and the conclusion does not hold.
6. **SCALE28-FIX6 exit** — "The successful hybrid final-release path shares one
   unchanged 600 millisecond authority across resource work, two ownership
   samples, and the required sample gap." Production's ownership-handoff
   authority is 500 ms (`_OWNERSHIP_HANDOFF_SECONDS`), and it is a *different*
   authority from the 600 ms `final_release_timeout_ms`.
7. **SCALE28-FIX4's selected policy**, for `ObserverDeadlinePolicy` only — the
   40 ms `cancel_request_timeout_seconds` and the
   `caller_seconds − reserve` trigger derivation are superseded. The 600 ms
   `final_release_timeout_ms`, 800 ms lease, 1,800 ms attempt, 4,100 ms total,
   and two-attempt values are **retained unchanged**.

## Rejected Alternatives

Raising the final-release window to 650 ms; selecting any tuple with
`caller ≥ trigger + request`; a short-lived separate final observer connection;
moving either ownership sample outside the final clock; letting one snapshot
serve both sample authorities; dropping sample two; per-call or environment-
specific tuning; making any of these values public configuration; lowering the
400 ms server statement timeout without configured proof; and retaining the
current default.

## SCALE28-FIX7 Contract

### Phase objective

Implement the amended final-release observer authority and qualify it on the
actual configured paths.

### Authorized scope

`tools/scale28_observer_deadlines.py`, `tools/scale28_backend_observer_session.py`,
`tools/scale14_backend_monitor.py`, and the tests and test support required to
prove them. Additive durable records.

### Prohibited scope

Dependencies; SQL; schema; migrations; public CLI; MCP; coordinator protocol;
publication; lifecycle; the preparation worker, receipt, observation/ACK, or
freshness contracts; the 400 ms server statement timeout; the 650 ms maximum;
`scale28_preparation_policy.py` values other than none; protected source;
retained runtime; SCALE29.

### Likely files and symbols

```text
scale28_observer_deadlines.ObserverDeadlinePolicy          — field set, operation_deadlines
scale28_observer_deadlines.ObserverOperationClass          — new closed enum
scale28_observer_deadlines.ObserverCancellationState       — unchanged
scale28_backend_observer_session.BackendObserverSession.run — class-aware dispatch,
                                                              pre-dispatch refusal,
                                                              acquisition-aware deadline,
                                                              no timer for serialization_only
scale14_backend_monitor._OWNERSHIP_HANDOFF_SECONDS         — demoted to prefinal budget
scale14_backend_monitor.release_when_ready                 — window-derived budgets,
                                                              explicit separation reserve
scale28_hybrid_startup.release_prepared_child              — pass the final deadline through
```

### State-machine changes

None to `PreparationState`. One new closed failure category,
`observer_budget_insufficient`.

### Deadline formulas

As frozen in the Deadline And Caller-Budget Contract.

### Operation-class vocabulary

`connection_startup | sql_bounded | serialization_only | settlement`. Closed,
immutable, selected per callsite, never per call.

### Caller-budget behaviour

In-window callers receive `final_deadline_ns − now_ns`. Prefinal and active
callers receive `B_pre = 500 ms`. `run()` sizes its execution deadline from the
budget remaining after acquisition.

### Pre-dispatch refusal

`sql_bounded` with `B < B_min` refuses before touching the connection, with
`observer_budget_insufficient` as a primary source-sequenced failure.

### Sample and gap behaviour

Two samples, both in-window, separated by a 50 ms floor, never overlapping,
never reusing one snapshot.

### Freshness, settlement, close, causality

Unchanged. FIX7 must prove it did not change them.

### TEST-COV4 ordering

Unchanged. Source sequence remains authoritative; the new category must not
displace an earlier source.

### Cross-platform behaviour

No new mechanism. Existing coverage must continue to pass.

### Compatibility and migration

No public surface change; no migration.

### Red tests

Before the fix, these must fail:

1. `operation_deadlines`-equivalent derivation yields `trigger <= server` for a
   440 ms budget.
2. A `serialization_only` callsite arms a cancellation timer.
3. `run()` overruns its caller budget when acquisition is contended.
4. The final-release window and the per-operation budget are the same constant.

### Acceptance bar

Labelled separately; no synthetic grand total.

```text
distinct semantic cases
  product-default client fallback ....................  30   (exact connection)
  server timeout .....................................  20
  CancellationTimeout ................................  20
  cancellation transport failure .....................  20
  pre-dispatch refusal ...............................  12   (new)
  operation-class dispatch ...........................   8   (new)
  three-party close schedules ........................  50   (retained)
  close-under-use schedules .......................... 100   (retained)
  source-causality schedules ......................... 200   (retained)
  terminal claims ....................................  18   (retained)
  reacquisition paths ................................  36   (retained)
  actual caller contexts .............................   9   (retained, re-derived)
stability repetitions
  final-release window occupancy .....................  20
actual configured executions
  actual owning paths ................................  50   (SCALE14, SCALE23,
                                                              SCALE28, SCALE28-FIX1,
                                                              hybrid; 10 each)
  quiet baseline .....................................   1
  bounded ordinary contention ........................   1
  mixed campaigns ....................................  15
fresh-runtime rehearsals
  fresh public rehearsals ............................   3
  prior-publication cancellation .....................   1
complete gates
  focused acceptance selections ......................  10
  complete repository gates ..........................   4
```

### Stop conditions

Stop and report Outcome B rather than retune if: any tuple value must move
outside this contract; the 600 ms window proves insufficient in configured
execution; `B_min` must fall below `S`; or the 120 ms request bound proves
unreliable on the configured boundary.

### Commit and report requirements

Exactly one commit; push `main`; prove parity and a clean tree; generate the
combined report at the default destination.

## TEST-COV5F Contract

Independent, test-only qualification of the pushed FIX7 source and policy.

TEST-COV5F must:

- freeze the pushed FIX7 source and policy by digest before any assertion;
- prohibit production changes and any replacement-policy selection;
- qualify the complete final-release path end to end;
- qualify the **shortest and longest actual callers**, including the exact
  remaining budget at sample two;
- qualify strict server precedence at every dispatched budget;
- qualify successful client fallback where the server timeout cannot apply;
- qualify cancellation limitation as bounded secondary evidence;
- qualify independent operation and cancellation-request settlement;
- qualify pre-dispatch refusal as a primary source-sequenced category;
- qualify the two samples and the 50 ms separation floor;
- qualify local close, close eligibility, and terminal independence;
- qualify that `serialization_only` operations arm no cancellation timer;
- run the actual SCALE14, SCALE23, SCALE28, SCALE28-FIX1, and hybrid owning
  paths;
- include quiet and bounded ordinary contention;
- include fresh public rehearsals and one prior-state failure rehearsal;
- use semantically distinct evidence, with no group standing in for another;
- run a proportional complete-gate bar;
- stop before SCALE29;
- authorize SCALE29 only on Outcome A.

## SCALE29 Boundary

SCALE29 remains **prohibited**. It becomes available only after TEST-COV5F
selects Outcome A and that result is committed, pushed, fetched, synchronized,
clean, and independently approved. This ADR authorizes SCALE28-FIX7 only.

## Simplification Disposition

| Artifact | Disposition |
| --- | --- |
| Duplicated deadline models (`_OWNERSHIP_HANDOFF_SECONDS` vs `caller_operation_timeout_seconds` vs `final_release_timeout_ms`) | **Consolidate in FIX7** — one window authority, one prefinal budget |
| `ObserverDeadlinePolicy.operation_deadlines` scaling branch | **Delete in FIX7** — superseded by the class contract |
| Obsolete candidate-selection support (`CANDIDATE_C120_420`, `final_release_envelope`, `FINAL_RELEASE_CAP_MS`, `REQUIRED_SAMPLE_GAP_MS`) | **Deprecate after FIX7; delete after TEST-COV5F** — the envelope model is superseded |
| Historical xfail / quarantine support | **Retain** — no selected-scope expected failure remains; removal is not this contract's work |
| Status prose that became de facto policy ("600 ms cap", "required 50 ms gap") | **Deprecate now** — superseded by this ADR; the records are corrected additively |
| Request-round-trip stability helpers | **Retain** — still valid compatibility evidence |
| Semantic-manifest support | **Retain and consolidate in FIX7** — extend rather than replace |
| Final-release work that belongs before the clock | **Retain in place** — the audit found none that may move without weakening ADR 0044's clock decomposition |

This disposition does not authorize a broad cleanup before correctness. No
deletion may precede TEST-COV5F Outcome A.

## Protected-Work Boundary

No protected source or retained runtime was accessed. No protected prelaunch,
refresh, publication, MCP exposure, baseline, drift, SCALE closure, or GO24
advice was performed. This ADR changes no production source, test, or dependency.

## Successors

SCALE28-FIX7 is the sole immediate successor. TEST-COV5F follows a committed,
pushed, synchronized, clean FIX7. SCALE29 remains prohibited.

## SCALE28-FIX7 Implementation Result

SCALE28-FIX7 implemented this ADR's complete structural candidate without
retuning. The candidate used one final deadline, four closed operation classes,
acquisition-aware caller budgeting, bounded pre-dispatch refusal,
serialization-only no-cancel ownership, a non-early-wakeable two-sample floor,
and settlement-owned request authority.

The first frozen 30-operation product-default client-fallback cohort passed.
The mandatory unchanged-candidate repeat produced a real
`CancellationTimeout` within the 120 millisecond request bound. This ADR's
explicit stop condition therefore applies: the result may not be selected by
average, retuned, or restarted as qualification.

SCALE28-FIX7 selects Outcome B. Its incomplete production candidate is
preserved in an owner-private binary patch and reverted from the repository.
The accepted production source and defaults remain those of SCALE28-ADR3.
TEST-COV5F proceeds in characterization mode; SCALE29 remains prohibited.

## TEST-COV5F Characterization Result

TEST-COV5F independently froze the accepted production source and policy and
kept the accepted tree, private candidate, and this ADR's contract distinct.
A new 30-operation accepted-tree client-fallback cohort produced 19 successful
requests and 11 bounded `CancellationTimeout` outcomes. Retained semantic,
PostgreSQL, contention, mixed, and complete-gate evidence passed.

The result confirms that the reliability gap is not confined to one FIX7
candidate run. This ADR's frozen 120 millisecond request bound also timed out
on mandatory FIX7 repeat, while the accepted 40 millisecond bound remains
independently unqualified.

TEST-COV5F selects Outcome C. Before another implementation, a successor ADR
must select a configured cancellation-request tail contract and matching
settlement deadline from measured platform evidence. It must not raise the
final-release window, lower the server timeout, accept `CancellationTimeout`
as successful fallback, or restart cohorts for a favorable result. SCALE29
remains prohibited.

## TEST-COV5G Opening-Gate Result

TEST-COV5G froze the accepted source and policy and pre-registered the required
two-cohort configured measurement. Its mandatory unchanged-source opening gate
failed before measurement in the accepted FIX6 candidate-characterization
integration test.

The operation owner constructed its failure before the cancellation-request
owner published `CancellationTimeout`. A later snapshot reported
`request_timed_out`, while the already-constructed error had no cancellation
limitation. An exact immediate rerun passed, confirming an intermittent
cross-owner publication race.

TEST-COV5G selects Outcome B and routes to TEST-COV5G-FIX1. No configured tail
sample was collected, no request bound was selected, and ADR 0046,
SCALE28-FIX8, and SCALE29 remain unauthorized.

## TEST-COV5G-FIX1 Post-Review Correction

TEST-COV5G correctly stopped on a red opening gate, but its
`cross-owner publication race` root-cause label was not established. FIX1
proved that the failed integration test compared a later terminal session
snapshot with an earlier operation error.

The accepted contract is construction-boundary projection. Request-first
error construction includes an already-terminal request limitation.
Operation-first construction omits a request result that becomes terminal
later. The later snapshot reports eventual session state without
retroactively changing the already-presented error.

Twelve projection semantics, 40 deterministic publication schedules,
30 consecutive corrected real-PostgreSQL repetitions, retained semantic
matrices, five focused selections, and two complete repository gates passed.
No production or policy correction was required. TEST-COV5G-FIX1 selects
Outcome A and authorizes TEST-COV5G-R1 measurement mode only. ADR 0046,
SCALE28-FIX8, and SCALE29 remain unauthorized.

## TEST-COV5G-R1 Decision-Evidence Result

TEST-COV5G-R1 completed the unchanged pre-registered two-cohort,
five-condition, 500-operation configured request-tail protocol. All 500 exact
requests succeeded; no timeout, transport failure, censoring, sample removal,
or cleanup failure occurred. The combined nearest-rank p95 was 85.186
milliseconds, p99 was 111.923 milliseconds, and maximum was 144.905
milliseconds. The smallest reporting threshold with zero observed exceedances
was 160 milliseconds, with an approximate rule-of-three upper failure estimate
of 0.6 percent.

Forty deterministic same-process cases and 20 spawn-safe process-feasibility
cases passed with exact owner settlement and backend cleanup. Process isolation
remains feasibility only and does not preserve ADR 0044's continuous parent
observer.

R1 selects Outcome A as decision evidence for SCALE28-ADR4 only. It does not
select a request bound, change this ADR, write ADR 0046, authorize
SCALE28-FIX8, or authorize SCALE29.

## SCALE28-ADR4 Containment Decision Result

SCALE28-ADR4 accepted ADR 0046 with Decision Category A: the same-process
fixed request and settlement contract. This ADR's structural contract — one
final deadline, four operation classes, acquisition-aware budgets,
pre-dispatch refusal, serialization-only no-cancel ownership, the two-sample
floor, and settlement-owned request authority — is retained intact.

ADR 0046 supersedes exactly three statements here: the 120 millisecond
request bound (now 250 milliseconds with a 300 millisecond maximum), the
`T_def + R` settlement-budget floor (now the explicit 750/900/1,000/5,000
millisecond authority set), and the FIX7 stop condition (now the FIX8 stop
conditions). The 600 millisecond window, 650 millisecond maximum,
400 millisecond server timeout, and every safety invariant remain unchanged.

Successful `cancel_safe()` completion is normatively bounded dispatch, not
operation interruption; operation settlement is a separate authority.
SCALE28-FIX8 is authorized to implement this ADR's structure with ADR 0046's
values; TEST-COV5H must qualify it; SCALE29 remains prohibited.

## SCALE28-ADR4-FIX1 Successor Correction

SCALE28-ADR4-FIX1 corrected ADR 0046 additively before implementation. In
the authority set stated above, the 750 millisecond request-settlement
member is superseded: request settlement is `D_req = 300 ms` measured from
actual `cancel_safe()` dispatch (never from operation dispatch, never
reduced by timer lateness, never started without a dispatched request). The
900/1,000/5,000 millisecond members stand as an operation-settlement
classification threshold, a coordinated-close attempt budget, and a whole
failure cleanup-attempt budget — bounded decisions and attempts, not
deterministic reclamation. Initial timing qualification is restricted to
the exact R1 measured stack. Nothing else in this ADR's structural contract
changes; SCALE28-FIX8 remains authorized under ADR 0046 as amended,
TEST-COV5H remains required, and SCALE29 remains prohibited.

## SCALE28-FIX12-R2 Additive Outcome

R2 stopped at its mandatory opening compileall check before deriving an
observer-owner manifest or changing production. The complete all-suite gate
and capable-environment probes passed, but two deliberately malformed tracked
fixtures cannot satisfy the assignment's whole-`src/test` compileall
selection.

Outcome B changes no operation class, deadline, sample floor, final-window
propagation, or qualification authority in this ADR. SCALE29 remains
prohibited.

## SCALE28-FIX12-R2-FIX1 Additive Outcome

The retry implements the closed four-class operation surface and one
acquisition-aware caller deadline. SQL dispatch below the 420 millisecond
minimum refuses before connection use; 420-449 millisecond callers use their
remaining authority; 450 milliseconds or more retains the cancellation
trigger. Serialization-only work arms no SQL timer.

The validated pre-release ownership summary is sample one of the required
two-sample final decision. Its conservative post-validation timestamp and the
second fresh summary share the same preparation-owned 600 millisecond deadline
and retain the non-early-wakeable 50 millisecond floor. This removes a
redundant third SQL sample without duplicating the deadline or weakening either
sample. The full SCALE23/SCALE28 owning paths and complete gates pass.
Qualification remains Q2 and SCALE29 remains prohibited.

## SCALE28-FIX12-R2-FIX2 Additive Correction

Independent review accepted the R2-FIX1 observer structure but found that the
terminal backend readback enforced its 500 millisecond authority only after
synchronous Psycopg work returned. FIX2 replaces that post-return-only check
with one terminal-owner absolute deadline beginning immediately before
connection acquisition. Nonblocking libpq polling carries only remaining
authority through acquisition, query dispatch, server execution, result
fetch, and all network readiness waits. The same absolute deadline checks the
local settlement result after it returns; `PGconn.finish()` itself is not
asynchronously preemptible.

The one-read and final-release structures remain unchanged. Terminal timeout
is structured, makes no backend-quiescence claim, never retries, and does not
grant another owner close authority. TEST-COV5K-R2 remains required and
unauthorized; SCALE29 remains prohibited.
