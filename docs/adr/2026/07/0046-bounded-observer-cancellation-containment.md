# ADR 0046: Bounded Observer Cancellation Containment

## Title

Bounded Observer Cancellation Containment

## Status

Accepted — Outcome A, Decision Category A (same-process fixed request and
settlement contract; ADR 0044 and ADR 0045 retained and precisely amended).
Amended additively by SCALE28-ADR4-FIX1 (2026-07-26): request-settlement
clock origin, containment vocabulary, and initial timing-qualification scope
(see the SCALE28-ADR4-FIX1 Additive Clarification section). In this ADR,
"containment" means bounded authority, refusal, classification, and cleanup
attempts — never deterministic thread, connection, process, backend, or
whole-cleanup reclamation.

## Date

2026-07-26

## Context

ADR 0045 reconciled the final-release deadline authorities into one structural
contract: one final-release window, four closed observer operation classes,
acquisition-aware caller budgets, bounded pre-dispatch refusal,
serialization-only no-cancel ownership, an explicit two-sample floor, and a
settlement-owned cancellation-request authority. SCALE28-FIX7 implemented that
structure faithfully and stopped on ADR 0045's own stop condition when the
frozen 120 millisecond cancellation-request bound produced a real
`CancellationTimeout` on mandatory repeat. TEST-COV5F independently confirmed
that the reliability gap is not a candidate artifact: the accepted tree's
40 millisecond bound produced 11 timeouts in 30 operations. TEST-COV5G
stopped truthfully on a red opening gate; TEST-COV5G-FIX1 proved the failure
was a test projection defect and froze the immutable construction-boundary
projection contract; TEST-COV5G-R1 then completed the pre-registered
500-operation configured cancellation-request tail campaign without a single
request timeout, transport failure, censored request, or cleanup failure.

The structural contract is sound and implemented evidence exists for it. What
has never existed is an accepted cancellation-containment architecture: an
answer to what successful `cancel_safe()` completion *means*, which authority
bounds the operation when the request does not settle it, and which platform
the measured evidence actually covers. Four phases have now closed on that
same missing answer. This ADR supplies it.

## Problem

Is successful same-process `cancel_safe()` completion a required correctness
authority backed by one fixed measured request bound and a separately bounded
operation-settlement contract, or is `cancel_safe()` only a best-effort
accelerator that requires a different deterministic containment boundary when
it does not settle?

**Answer: it is a required bounded-evidence authority — with the precise
meaning the primary sources permit.** A `cancel_safe()` return within the
fixed request bound is required for the client fallback to count as a
successfully dispatched interruption request. It is *not* an
operation-interruption guarantee, because the pinned Psycopg source and the
PostgreSQL 18 libpq documentation both state that successful dispatch
guarantees nothing about the server's effect. Operation interruption is owned
by the server (statement timeout primarily, processed cancellation as
fallback) and is observable only through a separately bounded
operation-settlement authority. Request failure within the bound is a closed,
contained, fail-closed outcome — it refuses release and enters bounded failure
settlement; it never becomes success and never corrupts state.

## Evidence Hierarchy

This ADR used the following order and records disagreements rather than
silently resolving them.

1. **Current production source at `ebe8d52d`** —
   `tools/scale28_observer_deadlines.py`,
   `tools/scale28_backend_observer_session.py`,
   `tools/scale14_backend_monitor.py`, `tools/scale28_hybrid_startup.py`,
   `tools/scale28_preparation_policy.py`,
   `tools/scale28_preparation_authority.py`,
   `tools/scale14_actual_refresh_supervisor.py`, and the pinned installed
   Psycopg 3.2.12 implementation the production source executes.
2. **Accepted ADRs and additive amendments** — ADR 0044 with its corrections,
   ADR 0045 with its FIX7/COV5F/COV5G/FIX1/R1 result addenda.
3. **Committed TEST-COV5G-FIX1 and TEST-COV5G-R1 test evidence** — the frozen
   500-operation decision dataset, the 40 same-process schedules, the
   20 process-feasibility cases, and the FIX1 projection suite.
4. **Current executable tests** — the FIX1 and R1 unit suites executed
   unchanged during this phase (55 and 71 passing tests respectively).
5. **Status records and plans** — 00667 through 00672.
6. **Commit patches** — `d3bf10ed`, `1e2862f0`, `bd04eba8`, `043eb43c`,
   `46f826a3`, `ebe8d52d`.
7. **Transient reports.**
8. **Primary external documentation** — PostgreSQL 18 libpq cancellation and
   client-configuration pages; the pinned Psycopg 3.2.12 source and
   docstrings.

Passing tests do not make a test label architecturally correct, and an
empirical maximum is not a deterministic bound. Both principles are applied
below.

### Named evidence conflicts and dispositions

1. **Loaded libpq identity.** Status records 00670–00672 and the R1 protocol
   prose state the runtime as "libpq 18.4". Direct execution of the pinned
   dependency (`psycopg[binary]==3.2.12`) in the synchronized worktree reports
   `pq.__impl__ = "binary"` and `pq.version() = 170006` — bundled libpq 17.6.
   The R1 harness records `str(psycopg.pq.version())`, an integer string, so
   the prose "18.4" cannot have been produced by the recorded field; it most
   plausibly describes a host-installed libpq that the pinned binary wheel
   does not load. **Disposition:** the historical prose is preserved and
   reclassified as unverified environment description. The normative runtime
   identity is what `psycopg.pq.version()` reports for the pinned dependency
   at execution time. TEST-COV5H must record `pq.__impl__` and `pq.version()`
   in its runtime record. No R1 measurement is invalidated: the measured
   stack is the pinned stack, whatever its correct label.
2. **R1 request tail versus FIX7/COV5F request outcomes.** R1 observed 3/500
   requests above 120 ms and zero above 160 ms; FIX7's mandatory repeat
   produced `CancellationTimeout` at 120 ms in a 30-operation cohort, and
   COV5F's accepted-tree cohort produced 11/30 timeouts at 40 ms. These are
   consistent once populations are separated: R1's frozen protocol ran its
   conditions with *bounded, pre-registered* contention, while the FIX7 and
   COV5F cohorts ran inside broader gate executions with unbounded ambient
   host load, and a rate near R1's 0.6 percent one-sided upper estimate
   already fails a 30-consecutive bar roughly one time in six.
   **Disposition:** both records stand. The selected bound below is valid for
   the measured envelope; exceedance under any load remains a closed contained
   outcome, so the envelope bounds availability, not safety.
3. **R1 same-process semantic labels.** The R1 manifest generates 40 distinct
   schedules, but the semantic label rotates `index % 14` independently of the
   generated schedule tuple, so a label alone does not prove the labelled
   behavior was enacted in that case. **Disposition:** the 40 schedules count
   as 40 distinct enacted barrier/publication schedules; the *named* behaviors
   (settlement ceiling, fresh-terminal readback limitation, duplicate close)
   are credited to the retained FIX5/FIX6 tests that enact them by
   construction. FIX8 and TEST-COV5H must bind semantic labels to enacted
   schedule content.
4. **R1 process-case counting.** R1 reports "twenty process cases"; the
   committed generator is `_PROCESS_CASE_SHAPE * 2` — ten semantic shapes with
   one stability repetition each — and the `live_descendant_refusal` case
   sends a channel message and sets a parent-side flag without creating or
   observing a real descendant process tree. **Disposition:** the evidence is
   accepted as 10 distinct semantic process cases plus 10 stability
   repetitions proving basic measured-host feasibility only. It is not
   descendant-tree containment evidence and is scored accordingly in Option C.

## FIX1 Projection Contract

Retained verbatim and not reopened:

- `BackendMonitorError` is an immutable projection of request facts terminal
  and visible at its construction boundary.
- A later session snapshot is an independent immutable projection of later
  session state.
- Request-first construction includes an already-terminal cancellation
  limitation; operation-first construction omits a limitation that becomes
  terminal later.
- A later snapshot never retroactively mutates an already-presented error.

Every contract in this ADR is expressed against that boundary. No deadline in
this ADR changes which facts are visible at construction.

## R1 Measurement Protocol

The decision dataset is the committed TEST-COV5G-R1 campaign, unchanged:
2 cohorts × 5 fixed conditions × 50 operations = 500 measured exact
cancellation requests; 450 ms product client trigger; 2,000 ms test-owned
observation ceiling; nearest-rank percentiles; zero outlier removal; zero
valid-observation removal; zero censored requests; zero cohort restarts.
Conditions: A quiet loopback TCP; B two bounded CPU workers; C bounded
filesystem plus exact-scope container-engine work; D bounded unrelated
connection churn; E the real configured `BackendObserverSession` context.
This phase did not rerun the campaign.

## Request-Tail Evidence

Combined request results (all 500 requests successful):

```text
minimum   1.957 ms      p90    63.101 ms
median    3.728 ms      p95    85.186 ms
                        p99   111.923 ms
                        max   144.905 ms
```

Threshold exceedances: 61 above 40 ms, 30 above 80 ms, 3 above 120 ms, zero
at 160 ms and every higher pre-registered threshold (200, 250, 500, 1,000,
2,000). The smallest zero-exceedance reporting threshold is 160 ms. The
one-sided approximate 95 percent rule-of-three upper failure estimate at the
combined zero-exceedance thresholds is 3/500 ≈ 0.6 percent (1.2 percent per
cohort, 3 percent per condition). The CPU-contention condition dominates the
tail: request median 63.101 ms, p95 111.923 ms, p99 135.079 ms, maximum
144.905 ms. No dynamic per-condition tuning is permitted or performed.

## Operation-Settlement Evidence

Combined operation-settlement observations, measured from operation start
with the 450 ms trigger and cancellation-driven completion:

```text
minimum   452.335 ms    p95   554.784 ms
median    459.686 ms    max   641.411 ms
```

The request bound and the operation-settlement bound are different
authorities. The observed operation maximum (641.411 ms) already exceeds the
naive composition `450 + 160 = 610 ms`, which proves that a settlement
deadline must cover the operation owner's actual terminal behavior — server
cancel processing, error delivery, client readback, and `run()` finalization —
with its own explicit margin, not the request bound's.

SCALE28-ADR4-FIX1 clarification: R1 measured the request tail as
`request terminal time − actual request dispatch time` and established no
bound on `nominal trigger − actual request dispatch`. Any request-settlement
authority anchored at operation dispatch can therefore expire while a
lawfully dispatched request is still inside its own `R` bound whenever the
deadline timer wakes later than the nominal 450 ms trigger. The
request-settlement authority `D_req` consequently begins at actual
`cancel_safe()` dispatch (Normative Deadline Contract below), and timer
lateness never consumes the request owner's authority.

## Evidence Limitations

- All 500 tail observations come from one host, one operating system, one
  Python build, one pinned Psycopg wheel with its bundled libpq, and one
  disposable PostgreSQL 16.14 server over loopback TCP.
- Zero observed exceedances above 160 ms bounds the failure probability only
  to ≈ 0.6 percent one-sided; it proves nothing deterministic.
- The bounded-contention conditions do not cover unbounded ambient host load;
  FIX7 and COV5F show materially worse request tails under such load.
- The process-feasibility evidence proves spawned-child ownership,
  cooperative and forced child termination, exact backend disappearance, and
  parent channel cleanup — and nothing else. It does not prove real
  descendant-tree containment, continuous observer identity, registration or
  freshness continuity, same-connection serialization, TEST-COV4 causality
  across process IPC, or any Windows Job Object behavior.
- The R1 same-process manifest's semantic labels rotate independently of the
  generated schedules (conflict 3 above).

## Primary-Source Review

For the pinned versions (Python 3.13.12, Psycopg 3.2.12, bundled libpq per
`pq.version()`, PostgreSQL client documentation 18, disposable server 16.14):

| Claim | Class | Source |
| --- | --- | --- |
| `cancel_safe()` success means the cancel request was dispatched; "a successful cancel attempt on the client is not a guarantee that the server will successfully manage to cancel the operation" | documented limitation | pinned Psycopg 3.2.12 `connection.py` docstring |
| "Successful dispatch of the cancellation is no guarantee that the request will have any effect"; a too-late cancel produces no visible result at all | documented limitation | PostgreSQL 18 libpq cancellation page |
| `cancel_safe()` on libpq ≥ 17 runs the full cancel-connection lifecycle under one monotonic deadline and raises `CancellationTimeout` on expiry | documented guarantee | pinned Psycopg 3.2.12 `generators.py` `_cancel` |
| `Connection.cancel_safe()` requires libpq ≥ 17; `capabilities.has_cancel_safe()` gates it | documented guarantee | pinned Psycopg 3.2.12 `_capabilities.py` |
| The cancel request travels on a separate connection object that is thread-safe with respect to the original connection | documented guarantee | PostgreSQL 18 libpq cancellation page |
| `statement_timeout` is measured from command arrival at the server until server completion; it covers lock waits; it cannot arm for a command that never arrives | documented guarantee and limitation | PostgreSQL 18 client-configuration page |
| Psycopg connections are thread-safe and not process-safe | documented guarantee and limitation | Psycopg documentation, recorded by R1 |
| Measured request-dispatch tail 1.957–144.905 ms across five conditions | measured local behavior | TEST-COV5G-R1 |
| Measured settlement tail 452.335–641.411 ms from operation start | measured local behavior | TEST-COV5G-R1 |
| Request dispatch success and operation settlement are separate authorities | architectural inference from the two documented limitations above | this ADR |

No guarantee is inferred from silence. The two documented limitations are
load-bearing: they make "mandatory cancellation success" meaningful only as
*mandatory bounded dispatch*, and they make a separate settlement authority
mandatory rather than optional.

## Current Architecture

`BackendObserverSession.run()` executes the operation on the calling thread.
A daemon deadline `Timer` thread fires at the client trigger, creates
operation-timeout and cancellation-request authority under the session
condition, and invokes `cancel_safe(timeout=reserve)` on the exact connection
outside the lock. The request owner records exactly one idempotent terminal
request outcome. The operation owner alone settles operation state in
`run()`'s `finally`. `close()` waits for operation settlement and request
settlement, records settlement and request-settlement limitations when its
budget expires, and closes the exact connection once. Terminal readback uses
a separate connection and is never close authority. The FIX1 projection
boundary governs error construction throughout.

Production policy at `ebe8d52d` remains the FIX4 default
(`2,000 / 400 / 450 / 40 / 500`): the 40 ms request bound is unqualified
since FIX5, and the ADR 0045 structural corrections exist as contract and as
the reverted owner-private FIX7 candidate, not as accepted source.

## Mandatory Analysis 1 — Request-Bound Selection

The five distinct quantities, never conflated:

```text
observed maximum                         144.905 ms
smallest zero-exceedance threshold       160 ms
selected fixed bound                     R = 250 ms
architectural maximum (request)          R_max = 300 ms
unsupported-platform behavior            fail-closed registration refusal
```

**Selection and margin policy.** The selected bound must (a) be a
pre-registered R1 reporting threshold, so that selection granularity cannot be
tuned after observation; (b) carry at least 50 percent margin over the
smallest zero-exceedance threshold (`≥ 240 ms`), because conflict 2 shows the
tail is strongly load-sensitive and FIX7's failure at 120 ms demonstrates the
cost of thin margins; and (c) fit inside the settlement authority derived
below. The smallest pre-registered threshold satisfying all three is
**250 ms**: 1.56 × the zero-exceedance threshold, 1.73 × the observed maximum,
and 105.095 ms above every observed request. The rule-of-three estimate at
250 ms remains ≤ 0.6 percent one-sided at 95 percent confidence — an upper
bound, not a rate. **This is not a deterministic guarantee.** A request
exceeding 250 ms raises `CancellationTimeout`, which is a closed contained
outcome (analysis 3), so bound exceedance affects availability only.

**Statistical honesty for successors.** At the 0.6 percent upper bound, a
30-consecutive-success cohort fails with probability ≈ 16 percent; the point
estimate at 250 ms (zero exceedances in 500) implies a far lower rate that
cannot be proven from this dataset. FIX8's stop condition therefore remains
truthfully fail-closed: a natural `CancellationTimeout` at 250 ms during
qualification is evidence about the envelope, not noise, and must stop the
phase rather than be averaged away.

**`R_max = 300 ms`** is the architectural maximum for the request bound: no
implementation may raise `R` above it without a new ADR, because
`T + R_max + M_s = 950 ms` is the settlement ceiling the close authority is
sized against.

## Mandatory Analysis 2 — Settlement And Cleanup Authorities

Six separate fixed authorities, each with exactly one normative clock
origin, are frozen in the Normative Deadline Contract below: the
cancellation request (`R`), request settlement (`D_req`, from actual
`cancel_safe()` dispatch — corrected by SCALE28-ADR4-FIX1), operation
settlement classification (`D_op`), the coordinated-close attempt budget
(`D_close`), terminal/fresh readback (`D_term`), and the whole failure
cleanup-attempt budget (`D_clean`).

The settlement deadline is **not** `trigger + request bound`. It is:

```text
D_op = T + R + M_s = 450 + 250 + 200 = 900 ms   from operation dispatch
```

where `M_s = 200 ms` is the settlement margin covering the operation owner's
observed terminal behavior after the trigger: the observed worst
post-trigger settlement lag is `641.411 − 450 = 191.411 ms` with request
dispatch inside 145 ms; a request lawfully consuming its full 250 ms bound
shifts the worst composed path to ≈ 746 ms, and 900 ms covers it with ≈ 20
percent margin. The settlement clock origin is **operation dispatch** (the
moment `run()` starts the deadline timer), chosen because the entire observed
settlement distribution is measured from that origin and because it is the
only origin that exists on every path, including operations that never reach
the trigger. `D_op` is an **operation-settlement classification threshold**
(SCALE28-ADR4-FIX1 vocabulary): at every independent settlement-observation
point, if the operation remains active after `D_op`, the observer records the
settlement limitation, the session is `FAILED`, close refuses to touch the
connection, and cleanup proceeds on the limited path — the expiry outcome is
a decision, never a longer wait. `D_op` does not interrupt the operation
thread at 900 ms, does not guarantee the limitation is published at exactly
900 ms (no dedicated watcher thread exists; when no independent observer
executes at expiry, classification occurs at the next safe
settlement-observation point), does not make the connection reclaimable at
900 ms, and does not guarantee process termination. The `T + R + M_s`
composition sizes the threshold for the nominal schedule; a late timer wake
defers actual request dispatch without moving `D_op`, and the resulting
late-settlement case is classified, not raced.

## Mandatory Analysis 3 — Mandatory Success, Precisely Defined

**Selected: the mandatory-success contract**, with "success" given the only
meaning the primary sources permit — successful bounded dispatch.

- `cancel_safe()` must return successfully within `R` for the client fallback
  to count as a successfully dispatched interruption.
- `CancellationTimeout` or transport failure never becomes success, refuses
  release (the trigger has already refused it), records the secondary
  limitation under the FIX1 construction boundary, and enters bounded failure
  settlement under `D_op`/`D_close`/`D_clean`.
- Empirical selection plus bounded failure behavior is sufficient — even
  though zero exceedances prove no future success — because the request
  authority's correctness role is bounded evidence capture, not interruption.
  Interruption is owned by the server and observed through settlement. A
  request failure therefore degrades availability (a refused release, a
  limited cleanup) and can never produce an unsafe state: no release under
  uncertainty, no close under use, no false quiescence, no blind reconnect,
  no external cancellation SQL.

The best-effort alternative is rejected in Option B below because in this
same-process architecture it reduces to waiting longer in the same unbounded
thread, which is explicitly invalid.

## Mandatory Analysis 4 — Same-Process Containment, Stated Honestly

When the request owner reaches its bound, the operation owner remains active,
close cannot touch the connection, and the server timeout has produced no
terminal operation, the remaining fault set is: the command never reached the
server (so `statement_timeout` never armed), *and* the dispatched or
undispatched cancel had no effect, *and* the transport delivered no error to
the blocked read. In that triple fault the operation owner's thread is
blocked inside a C-level libpq socket wait. **No same-process authority can
deterministically reclaim that thread.** This ADR states that plainly rather
than treating "record a limitation and keep waiting" as containment.

What Category A therefore claims, and all it claims — the selected
architecture is, precisely (SCALE28-ADR4-FIX1):

```text
same-process bounded request dispatch
+
bounded fail-closed decision containment
+
bounded close/readback/cleanup attempts
+
explicitly unbounded triple-fault thread-reclamation residual
```

- **Bounded failure classification.** An operation still active past the
  `D_op` threshold is classified as settlement-limited at the first safe
  settlement-observation point at or after expiry; nothing waits past the
  threshold for a decision, and no dedicated watcher thread is created to
  force publication at the threshold instant.
- **Bounded decision containment.** Release is refused at the trigger; the
  session is `FAILED`; the connection is quarantined (never reused, never
  blindly reconnected); close refuses the connection and completes its own
  bounded protocol; terminal readback runs on a separate connection; the
  supervisor's terminal path proceeds under `D_clean` and its own grace.
- **Explicit residuals.** The blocked thread's lifetime is bounded only by
  OS-level TCP behavior. On the final-release path the operation owner is the
  parent main thread, so the triple fault stalls startup itself until the
  transport dies; on the telemetry path it is the non-daemon consumer thread,
  so interpreter exit can block on it after `close_with_timeout` has already
  raised its bounded limitation. Both residuals are accepted, recorded risks
  of the same-process architecture — bounded in probability by the primary
  server-timeout authority and the measured request evidence, not bounded
  deterministically. Deterministic thread reclamation is exactly what process
  isolation would buy and is the named escalation path (analysis 5).
- **Residual-risk statement (SCALE28-ADR4-FIX1).** In the triple fault,
  external process termination or operator intervention may be required.
  This ADR does not identify an already-qualified outer process-reclamation
  authority, and it does not invent one: no outer supervisor deadline over
  the blocked thread, the quarantined connection, the parent process,
  backend disappearance, or interpreter shutdown is established by the
  current repository. Process isolation remains the next architectural
  escalation after a natural request-bound or operation-settlement
  exceedance on the qualified stack.

Non-daemon operation-thread lifetime, request-thread lifetime (daemon timer,
settles within `R` by construction), parent-process lifetime, supervisor
termination, terminal readback, backend disappearance, eventual cleanup, and
application shutdown are each assigned in the State And Ownership Contract.
Cross-platform behavior adds no mechanism (see the platform contract).

## Mandatory Analysis 5 — Process-Isolated Containment

The feasibility evidence establishes exactly: 10 distinct semantic
child-process shapes with 10 stability repetitions; spawn-safe child
creation; cooperative and forced child termination; exact measured backend
disappearance; parent channel cleanup. It does not establish real
descendant-tree containment (the refusal case is simulated by a flag),
continuous parent observer identity, registration continuity,
same-connection serialization continuity, freshness continuity, TEST-COV4
causality over IPC, or Windows process-tree containment.

Selecting process isolation today would require designing every one of those
missing contracts from zero evidence, would supersede ADR 0044's continuous
parent-owned observer — its central preserved authority — and would replace a
measured 0.6-percent-bounded availability risk with an unmeasured protocol
risk before SCALE29. **Rejected now.** It **remains the sole qualified future
fallback**, with this escalation trigger: if TEST-COV5H (or any later
qualification on the supported stack) shows the 250 ms bound or the 900 ms
settlement deadline unreliable under the supported envelope, the successor
phase must be a process-isolation ADR that supplies the missing contracts —
not a fifth tuple search.

## Mandatory Analysis 6 — Platform Scope

*(Corrected by SCALE28-ADR4-FIX1: capability scope is not timing
qualification. The original broad statement — one contract for CPython 3.13,
libpq ≥ 17, PostgreSQL 16–18, POSIX loopback or LAN TCP, with the same
values on Linux and Windows — conflated the two and is superseded; it
existed because Option D's rejection correctly kept one value set and the
capability gate is genuinely platform-neutral, but a single value set is not
evidence that its timing policy is qualified everywhere the API exists.)*

**Selected: one frozen value set, a capability contract, and a
timing-qualified baseline restricted to the exact measured stack.** No
runtime autotuning; no environment-variable timeout selection; no
per-platform value tables.

- **Capability contract.** `capabilities.has_cancel_safe()` returning true
  is necessary for this architecture on any stack. Where it is false the
  existing production gate refuses observer registration fail-closed
  (`backend observer bounded cancellation is unavailable`). Capability
  proves the API exists; it does not qualify the timing contract.
- **Timing-qualified baseline.** Initial timing qualification is limited to
  the exact R1 measured stack: macOS host, CPython 3.13.12,
  `psycopg[binary]==3.2.12`, `pq.__impl__ = "binary"`,
  `pq.version() = 170006` (bundled libpq 17.6), PostgreSQL server 16.14,
  loopback TCP. The exact macOS version and machine architecture were
  omitted from R1's committed records; TEST-COV5H must record them before
  any qualification claim. No timing qualification is claimed for Linux,
  Windows, any other CPU architecture, any other Python patch or minor, any
  other Psycopg release or implementation, any other loaded libpq identity,
  PostgreSQL 17 or 18, or LAN TCP.
- **Requalification triggers.** Any change to the operating-system family or
  version, machine architecture, Python minor or patch of the measured
  stack, Psycopg version or implementation, loaded libpq implementation,
  major, or minor, PostgreSQL server version, or loopback-versus-
  non-loopback transport is a timing-requalification trigger: a
  TEST-COV5G-class characterization must rerun before any qualification
  claim is renewed. A future qualification phase may broaden the qualified
  set; this ADR and ADR4-FIX1 do not. The values themselves never move
  without a new ADR.
- **Product capability versus SCALE qualification.** The implementation may
  possess `cancel_safe` capability on another stack without the
  250/300/900 ms timing policy being qualified there. Only a stack
  explicitly qualified by TEST-COV5H or an equivalent phase may support a
  SCALE29 readiness claim. General product use on an unqualified-but-capable
  stack is not refused solely for missing timing qualification unless an
  existing protected/SCALE boundary already owns that refusal; what is
  required everywhere is runtime-identity recording,
  qualification-identity comparison, and fail-closed SCALE qualification on
  mismatch.
- **Runtime-identity recording.** FIX8 and TEST-COV5H must record
  `platform.system()`, `platform.release()`, `platform.machine()`,
  `platform.python_version()`, `psycopg.__version__`, `pq.__impl__`,
  `pq.version()`, the PostgreSQL server version, and the transport
  classification in their runtime evidence.
- **Windows.** The observer cancellation path is platform-neutral Python
  threading over libpq and carries the same frozen value set as capability
  scope, but its request tail is timing-unqualified on Windows; no Windows
  qualification claim is made or required before SCALE29. The Windows Job
  Object contract remains where ADR 0044 placed it: the preparation worker,
  untouched here.
- **macOS/Linux.** The measured host is macOS. Linux carries the same frozen
  value set as capability scope and is timing-unqualified until a
  qualification phase measures it. TEST-COV5H qualifies exactly the stack it
  actually exercises and records the identity.

## Options Considered

| Criterion | A — larger fixed settlement-owned request bound | B — non-mandatory cancellation in same process | C — process-isolated observer containment | D — static platform-specific contracts |
| --- | --- | --- | --- | --- |
| Safety | fail-closed at every deadline; residuals named | same residuals, plus an undefined success meaning | potentially higher (thread reclamation) if contracts existed | equal to A at best |
| Deterministic boundedness | all decisions bounded; thread reclamation honestly excluded | **fails** — "containment" reduces to the same unbounded thread | claimed but unproven — no descendant-tree or IPC-causality evidence | as A |
| Evidence strength | 500-request frozen dataset; settlement tail; FIX5/FIX6 semantics | same data, but no authority for the unsettled case | 10 shapes + 10 repetitions, feasibility only | one measured stack — no second platform dataset exists |
| Normative consistency | retains ADR 0044/0045 intact; amends values only | contradicts ADR 0045's settlement-owned request authority | supersedes ADR 0044's continuous parent observer | duplicates A's values into unmeasured tables |
| Implementation complexity | low — value and deadline changes on the FIX7 structural pattern | low but incoherent | very high — new identity, IPC, freshness, causality, process-tree, Windows contracts | moderate, with dead per-platform branches |
| Cross-platform | capability gate retained; no new mechanism | same | Windows Job Object process-tree work required | invents unevidenced per-platform values |
| Testability | high — every authority independently qualifiable | poor — success is undefined | poor now — the missing contracts have no harnesses | as A, times platforms |
| Migration risk | low | low | high, pre-SCALE29 | moderate |
| Operational burden | unchanged | unchanged | new process per observer, new supervision | unchanged |
| Maintenance | low | low | high | moderate — table drift risk |
| Risk before SCALE29 | lowest | hidden unbounded path | highest | unjustified surface |
| Verdict | **Selected** | **Rejected** | **Rejected now; sole qualified future fallback** | **Rejected**; its named-stack element is adopted inside A |

Option B is rejected on the assignment's own validity test: a best-effort
contract is invalid when it merely waits longer in the same unbounded thread,
and in this architecture there is nothing else it could do. Option C is
rejected on evidence accuracy (analysis 5). Option D is rejected because
exactly one measured stack exists; a second value table would be invention.
Options A and C are **not** both authorized: A is accepted, C is prohibited
until its escalation trigger fires and a new ADR supplies its contracts.

## Decision

**Decision Category A — same-process fixed request and settlement contract.**

ADR 0044's hybrid preparation architecture and ADR 0045's structural
final-release contract remain accepted and intact. This ADR freezes the
cancellation-containment layer above them:

1. The cancellation-request authority is **mandatory bounded dispatch**:
   `cancel_safe()` must return within `R = 250 ms`, charged to the settlement
   authority, never to any caller budget. Timeout and transport failure are
   closed contained outcomes that refuse release and enter bounded failure
   settlement.
2. Request settlement is an **actively enforceable request-owner authority**
   (corrected by SCALE28-ADR4-FIX1): `D_req = R + M_req = 300 ms` from
   actual `cancel_safe()` dispatch, owning the request terminal outcome and
   its publication under the session condition. It does not begin at
   operation dispatch, is not `T + R + margin`, is not reduced by timer
   lateness, and does not start when no cancellation request is dispatched.
3. Operation settlement is a **separate fixed classification threshold**:
   `D_op = 900 ms` from operation dispatch (sized nominally as
   `T + R + M_s`), with a defined expiry decision taken at the first safe
   settlement-observation point — never enforced thread termination.
4. Coordinated close, terminal readback, and whole-phase cleanup receive the
   fixed attempt budgets and deadline `D_close = 1,000 ms`,
   `D_term = 500 ms`, and `D_clean = 5,000 ms` defined below. `D_close` and
   `D_clean` bound the owners' waits, decisions, and attempts, not
   connection closure or whole-cleanup completion.
5. The platform contract separates the capability contract
   (`has_cancel_safe()`, fail-closed refusal where false) from the
   timing-qualified baseline, which is restricted to the exact R1 measured
   stack, with mandatory runtime-identity recording and requalification
   triggers (analysis 6 as corrected).
6. Process isolation is prohibited as architecture and retained as the sole
   qualified escalation fallback with a defined trigger.

The 600 ms final-release window, 650 ms architectural maximum, 400 ms server
statement timeout, 450 ms client trigger, 500 ms prefinal budget, 420 ms
minimum SQL dispatch budget, 20 ms precedence guard, 50 ms sample floor, four
operation classes, pre-dispatch refusal, acquisition-aware budgeting,
serialization-only no-cancel rule, two-sample authority, FIX1 projection
contract, and TEST-COV4 causality are all retained unchanged.

## Normative Deadline Contract

```text
value                          origin (clock start)        owner                terminal condition                    on timeout                                   category    path
S       400 ms   server statement timeout
                               command arrival at server   server               server error / completion             QueryCanceled(statement timeout) at client   primary     success and failure
T       450 ms   client cancellation trigger
                               operation dispatch          deadline timer       timer fires or is cancelled           operation refused; request authority created primary     failure entry
R       250 ms   cancellation-request bound
                               cancel_safe() dispatch      request owner        recorded terminal request outcome     CancellationTimeout → request_timed_out      secondary   failure settlement
R_max   300 ms   request-bound architectural maximum — no implementation value above it without a new ADR
M_req    50 ms   request-result publication / scheduling margin (after request terminal; request owner / session condition)
D_req   300 ms   request-settlement authority  (= R + M_req; corrected by SCALE28-ADR4-FIX1)
                               cancel_safe() dispatch      request owner        request terminal outcome recorded     request settlement limitation                secondary   failure settlement
                               (actual; does not start                          and published under the session
                               when no request dispatched)                      condition
D_op    900 ms   operation-settlement classification threshold  (= T + R + M_s nominal sizing, M_s = 200 ms)
                               operation dispatch          settlement authority operation settled by its owner        settlement limitation; session FAILED;       secondary   failure settlement
                                                           (close/terminal path)                                      close refuses connection; cleanup limited
D_close 1,000 ms coordinated-close attempt budget
                               close() entry               closing caller       both owners settled and               SETTLEMENT_TIMEOUT, terminal-secondary,      secondary   failure settlement
                                                                                connection closed once                backend_quiescence_timeout
D_term  500 ms   fresh terminal-readback deadline  (= B_pre)
                               readback dispatch           readback caller      readback returned on separate         readback limitation; never close authority   secondary   both
                                                                                connection
D_clean 5,000 ms whole failure cleanup-attempt budget
                               close_with_timeout() entry  monitor closer       stream, session, consumer thread,     bounded cleanup limitation propagated;       secondary   failure settlement
                                                                                descriptor settled                    cleanup reported incomplete, never success
W       600 ms   final-release success window        open_final_readiness()     preparation authority                 (retained, ADR 0045)                         primary     success
W_max   650 ms   final-release architectural maximum (retained, ADR 0044)
B_pre   500 ms   prefinal and active caller budget   (retained, ADR 0045)
B_min   420 ms   minimum SQL dispatch budget = S + G, G = 20 ms (retained, ADR 0045)
GAP      50 ms   sample-separation floor             (retained, ADR 0045)
```

Per-authority meaning and non-claims (SCALE28-ADR4-FIX1 required table):

| Symbol | Value | Clock origin | Owner | Meaning | What it does not prove |
| --- | ---: | --- | --- | --- | --- |
| `S` | 400 ms | server command arrival | server | statement timeout | request dispatch |
| `T` | 450 ms | operation dispatch | timer | create fallback authority | exact request start |
| `R` | 250 ms | actual request dispatch | request owner | `cancel_safe()` bound | server interruption |
| `M_req` | 50 ms | after request terminal | request owner/session condition | publication margin | operation settlement |
| `D_req` | 300 ms | actual request dispatch | request owner | request terminal + publication | thread reclamation |
| `D_op` | 900 ms | operation dispatch | settlement observers | classification threshold | enforced thread stop |
| `D_close` | 1,000 ms | close entry | close owner | close-attempt budget | guaranteed connection closure |
| `D_term` | 500 ms | readback dispatch | readback owner | separate readback deadline | close authority |
| `D_clean` | 5,000 ms | cleanup entry | cleanup owner | cleanup-attempt budget | whole cleanup guarantee |
| `W` | 600 ms | final readiness open | preparation authority | success-path window | failure cleanup |
| `W_max` | 650 ms | architectural | ADR authority | maximum implementation window | permission to consume headroom |

Formula rules (as corrected by SCALE28-ADR4-FIX1): each formula references
only fixed policy values (`D_req = R + M_req`; `D_op = T + R + M_s` as
nominal sizing; `D_term = B_pre`; `B_min = S + G`). `M_req = 50 ms` exists
because the pinned Psycopg cancel generator checks its deadline on poll
wake-ups and the request owner records its outcome under the session
condition, so outcome recording and publication may lawfully trail the raw
`R` bound by scheduling latency. `R` and `D_req` are actively enforceable
request-owner bounds anchored at **actual** `cancel_safe()` dispatch: `D_req`
owns the request terminal return or exception plus the request owner's
publication under the session condition; it does not begin at operation
dispatch, is not `T + R + margin`, is not reduced by timer lateness, and
does not start when no cancellation request is dispatched. No formula
derives from runtime observation. The close-initiated cancellation request
(close arriving while an operation is active and unrequested) uses
`min(R, remaining_close_budget / 2)` as its dispatch bound — the only place a
formula caps `R`, never raises it. The session close waits
`min(caller budget, D_close)`: a larger caller budget never extends the close
authority, and a smaller one still binds. `D_op` expiry and `D_req` expiry
are evaluated at every settlement-observation point (close, terminal wait,
and the operation owner's own error path); no dedicated watcher thread
exists or is permitted, so classification may trail the threshold instant
until the next safe observation point. Ordering invariants, all checkable
statically: `S < T < B_pre ≤ W < W_max` (operation-dispatch-relative
policy); `R < D_req` (shared actual-request-dispatch origin);
`D_op < D_close ≤ D_clean` as a policy-value ordering across their distinct
origins; `T + R_max + M_s = 950 < D_close ≤ D_clean` as nominal-schedule
sizing. Because request dispatch may lawfully trail the nominal trigger, a
`D_req` interval may extend past the `D_op` threshold: the classification
threshold may then be crossed while the request is still lawfully in
flight, close still waits for both owners, and the request-settlement
limitation arises only from `D_req` measured at actual dispatch.

## State And Ownership Contract

One state model, mapped to the existing
`ObserverCancellationState`/`ObserverSessionState` machinery. Owner column is
exclusive: no other actor may perform the transition.

| State | Owner | Entered by | Allowed transitions |
| --- | --- | --- | --- |
| operation running | operation owner (calling thread) | `begin_operation()` at dispatch; starts `T` and `D_op` clocks | → operation timeout created; → operation settled |
| operation timeout created | deadline timer at `T` (or closer via close-initiated request) | `request(CLIENT_CANCEL_FALLBACK)`; request in flight | → request succeeded / timed out / transport failed |
| request started | request owner | `cancel_safe(timeout=R)` outside the lock | → exactly one terminal request outcome |
| request succeeded | request owner | recorded idempotently under the condition | → close eligible (with operation settled) |
| request timed out | request owner | `CancellationTimeout` at `R` | → close eligible (with operation settled); secondary limitation per FIX1 |
| request transport failed | request owner | bounded non-timeout error | same as request timed out, `cancellation_failure` |
| operation settled | operation owner only | `run()` `finally` → `settle_operation()` | → close eligible |
| operation settlement timed out | settlement authority | `D_op` (or close budget) expiry with operation active, classified at a safe settlement-observation point | `record_settlement_limitation`; session FAILED; connection quarantined |
| local close requested | closing caller | `begin_close()`; refuses new operations | → close eligible wait |
| close eligible | derived: `operation_settled AND NOT request_in_flight` | state machine | → connection closed |
| connection closed | closing caller, exactly once | `close()` after eligibility, within `D_close` | terminal for the connection |
| fresh terminal readback | readback caller | separate connection, `sql_bounded`, `D_term` | → cleanup complete / readback limitation |
| cleanup complete | monitor closer | `close_with_timeout` within `D_clean` | terminal |
| cleanup limited | monitor closer | any bounded limitation on the cleanup path | terminal; limitation propagated, never erased |

Thread lifetimes: the deadline timer is a daemon thread that settles within
`R` by construction. The operation owner is the calling thread (parent main
on the final-release path; non-daemon telemetry consumer on the event path);
its reclamation is not guaranteed in the triple fault (analysis 4) and its
stuck state is quarantined behind session FAILED. Duplicate close remains
idempotent; conflicting request outcomes remain fail-closed; child terminal
arrival never implies live-session settlement; late operation settlement
after a recorded limitation still transitions to operation settled, allowing
a later close retry to complete, and never erases the recorded limitation.

SCALE28-ADR4-FIX1 clarifications, binding on this state model: request
settlement is actively bounded by `D_req` from actual request dispatch;
operation settlement is observed against `D_op`; `D_op` expiry creates a
limitation only when a safe settlement observer evaluates the state; close
expiry returns a limitation and quarantine, not connection closure;
cleanup-attempt expiry returns a limitation, not complete cleanup; late
operation and request settlement may permit a later close retry; recorded
limitations are never erased.

## Immutable Projection Contract

Retained from TEST-COV5G-FIX1 verbatim: errors contain facts terminal at
construction; later snapshots may contain later facts; errors never mutate
retroactively. The new deadlines add construction boundaries but change no
projection rule: a settlement or request-settlement limitation appears in
errors constructed at or after the boundary where it became terminal, and in
no earlier error.

## Failure-Causality Contract

TEST-COV4 source sequence remains authoritative. **No category priority
exists.** A later cleanup limitation never overwrites the operation timeout
or any earlier source. Closed categories on this surface and their sequence
positions:

| Category | Position | Primary/secondary |
| --- | --- | --- |
| `observer_budget_insufficient` (pre-dispatch refusal) | at dispatch decision | primary |
| observer operation timeout (`OPERATION_EXECUTION_TIMEOUT`, mechanism server/client) | at operation failure construction | primary |
| cancellation request timeout (`cancellation_timeout`) | limitation on the primary error only if terminal at its construction (FIX1) | secondary |
| cancellation transport failure (`cancellation_failure`) | same rule | secondary |
| operation settlement timeout (settlement limitation) | at `D_op`/close-budget expiry | terminal-secondary |
| request settlement timeout (request-settlement limitation) | at `D_req` expiry from actual request dispatch (observed at a settlement-observation point), or at close-budget expiry with the request in flight | terminal-secondary |
| close timeout (`SETTLEMENT_TIMEOUT`, `backend_quiescence_timeout`) | at `D_close` expiry | terminal-secondary |
| terminal readback limitation | on the separate readback path | secondary, never close authority |
| cleanup limitation | last on the cleanup path | secondary, never overwrites |

## Terminal And Cleanup Contract

Retained: close waits for both owners; the callback never closes; no close
under operation or request use; no blind reconnect; no external cancellation
SQL; terminal readback on a separate connection is never close authority;
child terminal facts remain parent-owned (SCALE25/SCALE16); telemetry
lifetime remains SCALE23's. New: the quarantined-connection rule — after a
settlement limitation the exact connection is **abandoned unclosed** to OS
transport lifetime, exactly as the current close path already behaves: it is
never reused, never blindly reconnected, and never closed under use. Only the
late-settlement path can change this: if the operation owner settles after
the limitation was recorded, a subsequent close retry may then close the
connection once, and the recorded limitation is never erased.

## Cross-Platform Contract

As in analysis 6 (corrected by SCALE28-ADR4-FIX1): one frozen value set; the
capability contract (`has_cancel_safe()`, fail-closed refusal where false)
separated from the timing-qualified baseline, which is the exact R1 measured
stack only; mandatory runtime-identity recording (system, release, machine,
Python, Psycopg, libpq, server, transport); requalification triggers on
every stack-dimension change; fail-closed SCALE qualification on identity
mismatch; no new platform mechanism; the preparation worker's process-group
/ Job Object / refusal contract untouched.

## Compatibility

No public CLI, MCP, coordinator-protocol, SQL, schema, migration, dependency,
or runtime-configuration surface changes. Every value here is private and
fixed; none becomes public configuration. `ObserverDeadlinePolicy` remains a
private frozen dataclass whose field set FIX8 will change — a private break
only. This ADR changes documentation only.

## Consequences

- The four-phase Outcome B/C sequence on the cancellation surface closes with
  one decision: the request bound becomes an evidence-sized 250 ms with a
  stated margin policy, and every failure mode it can produce has a named,
  bounded owner.
- The distinction between dispatch success and operation interruption is now
  normative, which removes the category of future defect in which a request
  "success" is read as proof the operation ended.
- The same-process architecture's true residual — non-reclaimable blocked
  threads in the triple fault — is on record with its probability bound and
  its escalation path, instead of being implied bounded.
- FIX8's blast radius is the three private observer modules plus tests, on
  the already-proven FIX7 structural pattern.
- The deadline set is jointly satisfiable on the nominal schedule
  (reclassified by SCALE28-ADR4-FIX1 from a worst-case claim to
  nominal-schedule sizing): with close arriving at the earliest possible
  moment after dispatch and the timer waking at the nominal trigger, both
  owners settle by the `D_op = 900 ms` threshold and the close authority
  retains 100 ms for its own no-SQL close work before `D_close` expires —
  the `C120-420`-era collision between request settlement and close cannot
  recur. When the timer wakes late, `D_req` follows actual dispatch, the
  classification threshold may be crossed with the request lawfully in
  flight, and close returns its bounded limitation rather than racing.
- Qualification claims become stack-scoped; silent environment drift (the
  "libpq 18.4" prose) can no longer stand in for runtime identity.

## Superseded Statements

This ADR supersedes only the statements listed here; historical records are
not rewritten.

1. **ADR 0045 Deadline And Caller-Budget Contract** — `R = 120 ms` is
   superseded by `R = 250 ms` with `R_max = 300 ms`.
2. **ADR 0045 State And Settlement Contract** — "the settlement authority's
   budget must be at least `T_def + R`" is superseded by the explicit
   authority set `D_req = 750 ms`, `D_op = 900 ms`, `D_close = 1,000 ms`,
   `D_clean = 5,000 ms`. *(The `D_req = 750 ms` member of that set was
   itself superseded by SCALE28-ADR4-FIX1: `D_req = 300 ms` from actual
   `cancel_safe()` dispatch. The other members stand with the FIX1
   vocabulary — classification threshold, attempt budgets.)*
3. **ADR 0045 SCALE28-FIX7 stop condition** — "the 120 ms request bound
   proves unreliable on the configured boundary" is superseded by the FIX8
   stop conditions below.
4. **Status 00670/00671/00672 runtime prose "libpq 18.4"** — reclassified as
   unverified environment description; the normative identity is
   `psycopg.pq.version()` of the pinned dependency at execution time.
5. **Any reading of R1's 40-case manifest as per-label enactment proof** —
   superseded by conflict 3's disposition.
6. **Any reading of "20 process cases" as 20 distinct architectures or
   behaviors** — superseded by conflict 4's disposition.

Not superseded: the FIX4 40 ms production default remains the accepted
*implementation* value until FIX8 lands — it stays unqualified, and its
replacement is authorized, not enacted, by this ADR.

## Rejected Alternatives

Best-effort cancellation in the same process; process isolation as current
architecture; platform-specific value tables; any bound at 144.905 or 160 ms
without margin; `settlement = trigger + request bound`; dynamic, per-call,
per-condition, or environment-variable tuning; raising the final-release
window; lowering the 400 ms server timeout; accepting `CancellationTimeout`
as successful fallback; restarting cohorts for favorable results; treating
the empirical maximum as a deterministic bound; daemonizing the telemetry
consumer to hide the shutdown residual; OS-level TCP keepalive/user-timeout
tuning as a substitute for a containment decision (platform-variable and
outside this decision's authority).

## SCALE28-FIX8 Contract

**Phase objective.** Implement the ADR 0045 structural contract as amended by
this ADR — the accepted cancellation-containment values and authorities — on
the actual configured paths, and qualify it to the bar below.

**Authorized production scope.** `tools/scale28_observer_deadlines.py`,
`tools/scale28_backend_observer_session.py`,
`tools/scale14_backend_monitor.py`, `tools/scale28_hybrid_startup.py`
(final-deadline pass-through only), and the tests and test support required
to prove them. Additive durable records.

**Prohibited scope.** Dependencies; SQL; schema; migrations; public CLI; MCP;
coordinator protocol; publication; lifecycle; the preparation worker,
receipt, observation/ACK, and freshness contracts;
`scale28_preparation_policy.py` values; the 400 ms server timeout; the 650 ms
window maximum; protected source; retained runtime; reading the owner-private
FIX7 candidate patch (reimplement from contract); TEST-COV5H; SCALE29.

**Likely files and symbols.** As ADR 0045's FIX7 contract, plus:
`ObserverDeadlinePolicy` gains the fixed `R = 250 ms` request bound, the
`M_req = 50 ms` publication margin, the `M_s = 200 ms` settlement margin,
and derived `D_req = R + M_req`/`D_op` accessors; `BackendObserverSession`
records both the operation-dispatch and the actual request-dispatch
monotonic timestamps, anchors `R` and `D_req` at the actual request-dispatch
timestamp, and evaluates the `D_op` classification threshold and `D_close`
attempt budget in `close()`; the close-initiated request uses
`min(R, remaining/2)`; runtime-identity recording at registration.

**Exact selected numeric policy.** The Normative Deadline Contract table,
verbatim, as corrected by SCALE28-ADR4-FIX1: `R = 250 ms` and
`D_req = 300 ms` from actual request dispatch; `D_op = 900 ms`
operation-settlement classification threshold from operation dispatch;
`D_close = 1,000 ms` coordinated-close attempt budget; `D_term = 500 ms`
separate terminal-readback deadline; `D_clean = 5,000 ms` cleanup-attempt
budget. No value may move. FIX8 must not claim deterministic thread
reclamation anywhere in code, tests, records, or reports.

**State-machine changes.** None to `PreparationState`; the observer state
model above maps onto the existing `ObserverCancellationState` with the new
deadline enforcement points; `observer_budget_insufficient` as in ADR 0045.

**Ownership.** Request/operation/close ownership, immutable projection,
pre-dispatch behavior, operation classes, final-release behavior exactly as
ADR 0045 and this ADR's state table. Serialization-only operations arm no
timer. Failure settlement and terminal readback per the Terminal And Cleanup
Contract.

**Cross-platform behavior.** Capability refusal retained; no new mechanism.
FIX8 must record `platform.system()`, `platform.release()`,
`platform.machine()`, `platform.python_version()`, `psycopg.__version__`,
`pq.__impl__`, `pq.version()`, the PostgreSQL server version, and the
transport classification. No private host identity enters public output:
the authoritative qualification result is a closed digest or closed
comparison category. No public timeout configuration is added.

**Red tests.** Before the fix: (1) the 40 ms production bound exists and a
measured request above it produces `CancellationTimeout` on the accepted
tree; (2) no production symbol enforces a settlement deadline distinct from
the close budget; (3) the close-initiated request bound is `remaining/2`
uncapped by any fixed value; (4) ADR 0045's four red tests, unchanged, still
red on the accepted tree. Added by SCALE28-ADR4-FIX1: (5) a delayed timer
wake does not consume the request owner's `R` or `D_req`; (6) request
settlement cannot time out before 300 ms from actual request dispatch;
(7) `D_op` classification does not close or reclaim an active operation;
(8) `D_close` expiry leaves the connection quarantined and unclosed;
(9) `D_clean` expiry reports incomplete cleanup rather than success;
(10) late settlement allows exactly one later close retry without erasing
the limitation; (11) runtime capability and timing qualification are
separate; (12) a runtime-identity mismatch blocks SCALE qualification;
(13) `has_cancel_safe()` alone cannot satisfy timing qualification. Every
existing ADR 0045 and ADR 0046 red test is retained.

**Acceptance bar.** Labelled separately; no synthetic grand total; counts are
per group and no group substitutes for another:

```text
distinct semantic cases
  product-default client fallback, quiet ...............  30  (exact connection,
                                                               R = 250, zero
                                                               CancellationTimeout)
  product-default client fallback, bounded contention ..  30  (two CPU workers,
                                                               R1 condition-B
                                                               shape)
  server timeout ........................................ 20
  injected CancellationTimeout containment .............. 20  (test-seam, full
                                                               failure settlement)
  injected transport-failure containment ................ 20
  settlement-deadline expiry decision ................... 12  (held operation,
                                                               D_op expiry,
                                                               quarantine)
  close-initiated request bound ......................... 10  (min(R, remaining/2))
  pre-dispatch refusal .................................. 12  (retained)
  operation-class dispatch ..............................  8  (retained)
  three-party close schedules ........................... 50  (retained)
  close-under-use schedules ............................ 100  (retained)
  source-causality schedules ........................... 200  (retained)
  terminal claims ....................................... 18  (retained)
  reacquisition paths ................................... 36  (retained)
  actual caller contexts ................................  9  (retained, re-derived)
stability repetitions
  final-release window occupancy ........................ 20
  quiet fallback cohort repeat ..........................  1  (unchanged source,
                                                               30 further quiet
                                                               fallbacks)
actual configured executions
  actual owning paths ................................... 50  (SCALE14, SCALE23,
                                                               SCALE28,
                                                               SCALE28-FIX1,
                                                               hybrid; 10 each)
  quiet baseline / bounded contention ...................  2
  mixed campaigns ....................................... 15
fresh-runtime rehearsals
  fresh public rehearsals ...............................  3
  prior-publication cancellation ........................  1
complete gates
  focused acceptance selections ......................... 10
  complete repository gates .............................  4
```

Semantic labels must be bound to enacted schedule content (conflict 3's
correction).

**Prior-publication preservation, compatibility, no drift.** As ADR 0045's
FIX7 contract: no public surface change, no dependency change, prior-state
causality and publication preservation proved by retained suites.

**Stop conditions.** Stop and report Outcome B rather than retune if: a
natural (non-injected) `CancellationTimeout` occurs at `R = 250 ms` in either
fallback cohort or its repeat; any operation fails to settle within `D_op` on
the configured paths without an injected fault; any frozen value must move;
or strict server precedence is lost at any dispatched budget. The bounded
statistical residual recorded in analysis 1 does not soften this: a natural
timeout is envelope evidence and triggers the analysis-5 escalation question,
not a rerun.

**Commit and report requirements.** Exactly one commit; push `main`; prove
parity and a clean tree when the environment permits; combined Git-show and
operational report at the default destination.

## TEST-COV5H Contract

Independent, test-only qualification of the pushed FIX8 source and policy.

TEST-COV5H must:

- freeze the pushed FIX8 source and policy by path-bound digest before any
  assertion; prohibit production changes and any replacement-policy
  selection;
- verify the request origin: `R` and `D_req` begin at actual `cancel_safe()`
  dispatch, proven with deterministic delayed-trigger schedules showing that
  timer lateness does not reduce request authority (SCALE28-ADR4-FIX1);
- qualify the 250 ms request bound on quiet and bounded-ordinary-contention
  configured paths, reporting exact per-cohort exceedance counts against the
  pre-registered threshold ladder;
- prove the containment semantics separately — request dispatch bound,
  request publication bound, operation classification threshold,
  close-attempt bound, terminal-readback deadline, and cleanup-attempt bound
  — never treating all six as execution-containment deadlines; inject the
  triple fault and require release refused, session failed, connection
  quarantined, no close under use, a bounded decision return wherever an
  observer exists, cleanup reported incomplete, no false backend quiescence,
  and no claim of thread or process reclamation (a bounded test-owned
  release may clean up afterward but must not be called production
  containment);
- qualify operation settlement separately against `D_op`, from the recorded
  operation-dispatch origin, with per-condition nearest-rank tails and no
  removal;
- qualify request limitation and operation limitation as contained outcomes:
  injected `CancellationTimeout` and transport failure must produce the exact
  FIX1 construction-boundary projections, refusal of release, quarantine, and
  bounded limited cleanup;
- qualify close (`D_close`), duplicate close, close-initiated request
  capping, and fresh terminal readback (`D_term`) on its separate connection;
- qualify immutable projection ordering (request-first, operation-first,
  transport-first, operation-before-transport) with labels bound to enacted
  schedules;
- qualify the actual final-release caller contexts, including exact remaining
  budget at sample-two dispatch;
- qualify the SCALE14, SCALE23, SCALE28, SCALE28-FIX1, hybrid, and FIX8
  owning paths;
- record and compare the exact runtime identity, including the
  `platform.system()`/`platform.release()`/`platform.machine()` fields R1
  omitted; Outcome A may qualify only the stack TEST-COV5H actually
  exercises — when that stack differs from the R1 measured stack in any
  requalification-trigger dimension, run the required timing
  requalification or select Outcome C; capability alone never inherits the
  R1 timing claim; include unsupported-platform behavior (capability
  refusal, fail-closed);
- treat other-platform tests as supplemental reporting only: they are not
  qualified timing evidence unless they execute the complete request-tail,
  settlement, configured-path, and gate contract;
- include fresh public rehearsals and one prior-state failure rehearsal;
- run proportional complete gates;
- stop before SCALE29 and authorize SCALE29 only on Outcome A.

If TEST-COV5H observes a natural request-bound or settlement-deadline
exceedance under the supported envelope, its outcome must route to the
process-isolation escalation of analysis 5, not to value retuning.

## SCALE29 Boundary

SCALE29 remains **prohibited**. It becomes available only after TEST-COV5H
selects Outcome A on the pushed FIX8 source and that result is committed,
pushed, fetched, synchronized, clean, and independently approved. This ADR
authorizes SCALE28-FIX8 only.

## Simplification Disposition

| Artifact | Disposition |
| --- | --- |
| 40 ms accepted production default | **Consolidate in FIX8** — replaced by the frozen 250 ms bound; deleted with the FIX8 policy change |
| 120 ms ADR 0045 candidate value | **Superseded now** — historical prose retained; no artifact carries it forward |
| `C120-420` helpers (`CANDIDATE_C120_420`, `final_release_envelope`, `FINAL_RELEASE_CAP_MS`, `REQUIRED_SAMPLE_GAP_MS`) | **Deprecate now; delete after TEST-COV5H** — the envelope model was superseded by ADR 0045 and its deletion gate moves from COV5F (which became characterization) to COV5H |
| TEST-COV5G/R1 tail harness | **Retain frozen** as the decision dataset; never rerun for tuning; FIX8 reuses its measurement support only for the new cohorts |
| Process-feasibility harness | **Retain unchanged** as future-fallback evidence; do not extend before FIX8 correctness |
| FIX6 candidate-selection machinery | **Deprecate after FIX8; delete after TEST-COV5H** |
| Duplicated settlement models (close budget vs settlement wait) | **Consolidate in FIX8** — one settlement authority with the `D_op`/`D_close` split |
| Historic xfail/quarantine support | **Retain** — removal is not this contract's work |
| Semantic manifests with label rotation | **Consolidate in FIX8** — labels bound to enacted content |
| Status prose used as policy ("libpq 18.4", "160 ms threshold" as a bound) | **Deprecate as policy now** — superseded by this ADR's normative tables |

No deletion may precede TEST-COV5H Outcome A. This disposition does not
authorize broad cleanup before correctness.

## Protected-Work Boundary

No protected source or retained runtime was accessed. No protected prelaunch,
refresh, publication, MCP exposure, baseline, drift, SCALE closure, or GO24
advice was performed. The owner-private FIX7 candidate patch was not read.
This ADR changes no production source, test, or dependency.

## SCALE28-ADR4-FIX1 Additive Clarification

SCALE28-ADR4-FIX1 (2026-07-26, documentation-only) corrected this ADR before
implementation. ADR 0046 remains Accepted as amended; Decision Category A,
the 250 ms request bound, `R_max = 300 ms`, and every ADR 0044/0045
structural authority are retained unchanged. The correction supersedes
exactly:

1. **`D_req = 750 ms` from operation dispatch (`= T + R + M_r`).** Unsafe
   composition: the deadline timer may start `cancel_safe()` later than the
   nominal 450 ms trigger, so an operation-origin deadline can expire while
   the request is lawfully inside its own 250 ms bound. R1 measured
   `request terminal − actual request dispatch` and bounded nothing about
   `nominal trigger − actual dispatch`. The statement existed because the
   original table derived every request-side authority from the
   operation-dispatch origin used by the settlement evidence. Corrected to
   `D_req = R + M_req = 300 ms` from actual `cancel_safe()` dispatch,
   owning the request terminal outcome plus its publication under the
   session condition, never started when no request is dispatched, and
   never reduced by timer lateness.
2. **Whole cleanup guarantee wording.** "Whole failure-cleanup deadline" for
   `D_clean` read as a completion guarantee. It existed because `D_clean`
   genuinely bounds `close_with_timeout` orchestration and its returned
   decision. Renamed the **whole failure cleanup-attempt budget**: it does
   not bound the blocked operation thread's lifetime, the quarantined
   connection's lifetime, the parent process's lifetime, backend
   disappearance in the triple fault, or interpreter shutdown.
3. **Deterministic containment implications.** Wording such as
   "operation-settlement deadline," "`D_op` expiry records the settlement
   limitation at a fixed time," and the worst-case joint-satisfiability
   consequence could imply deterministic thread, connection, process, or
   whole-cleanup reclamation. The ADR already admitted the triple-fault
   residual; the vocabulary now matches it. The selected architecture is
   same-process bounded request dispatch, plus bounded fail-closed decision
   containment, plus bounded close/readback/cleanup attempts, plus an
   explicitly unbounded triple-fault thread-reclamation residual;
   "containment" in this ADR's title means bounded authority, refusal,
   classification, and cleanup attempts only. In the triple fault, external
   process termination or operator intervention may be required; no
   already-qualified outer process-reclamation authority exists in this
   repository, and none is invented.
4. **Broad initial timing-qualified platform claim.** The analysis-6
   statement covering CPython 3.13 / libpq ≥ 17 / PostgreSQL 16–18 / POSIX
   loopback or LAN TCP with the same values on Linux and Windows conflated
   capability scope with timing qualification. It existed because the value
   set is genuinely single and the capability gate is platform-neutral.
   Corrected: `has_cancel_safe()` is the capability contract; the initial
   timing-qualified baseline is the exact R1 measured stack only (macOS
   host, CPython 3.13.12, `psycopg[binary]==3.2.12`, `pq.__impl__ =
   "binary"`, `pq.version() = 170006` / bundled libpq 17.6, PostgreSQL
   server 16.14, loopback TCP; exact macOS version and machine architecture
   omitted from R1 and required from TEST-COV5H), with the expanded
   requalification-trigger list and the product-capability-versus-SCALE-
   qualification distinction of analysis 6 as corrected.

The historical explanations above are retained; no historical record is
rewritten. The corrected FIX8 and TEST-COV5H contracts (red tests 5–13, the
runtime-identity recording set, the request-origin and containment-semantics
verification duties, and stack-scoped qualification) are part of this
amendment.

## Successors

SCALE28-FIX8 is the sole immediate successor. TEST-COV5H follows a committed,
pushed, synchronized, clean FIX8. SCALE29 remains prohibited.

## SCALE28-FIX9 Additive Outcome

SCALE28-FIX9 reconstructed the exact 23-path FIX8 candidate and reproduced all
fourteen configured failures before editing. The primary defect was terminal
readback composition: the configured reader's minimum one-second polling
sequence could not fit the frozen 500 millisecond authority. A one-read
test-support correction and exact terminal category routing closed that defect
without changing any ADR value.

Outcome A remained prohibited. Repeated SCALE14 owning replays exhausted both
frozen 1,800 millisecond preparation attempts before child release, creating
`resource_reader_unavailable` ahead of the intended active-observer case. The
incomplete corrected candidate was preserved owner-privately and removed from
the committed tree. ADR 0046 remains Accepted as amended; TEST-COV5I proceeds
in characterization mode, protected SCALE remains paused, and SCALE29 remains
prohibited.

## TEST-COV5I Additive Outcome

TEST-COV5I independently froze the accepted source and policy authorities,
the fourteen-case FIX9 manifest, and the closed failure-category vocabulary.
The test-only characterization found no basis to promote FIX9's incomplete
private correction: the required candidate owning, mixed, rehearsal, and
prior-state qualification groups remain blocked by the repeated
preparation-worker deadline exhaustion.

Outcome B is retained without changing an ADR value or accepted production
source. SCALE28-FIX10 owns isolation of the frozen preparation-worker
deadline exhaustion in actual configured observer owning paths. Protected
SCALE remains paused and SCALE29 remains prohibited.

## SCALE28-FIX10 Additive Outcome

SCALE28-FIX10 selected Outcome B before candidate reconstruction because no
complete owner-private corrected-candidate receipt establishes the exact base
and manifest. No observer, cancellation, preparation, deadline, runtime
identity, source category, terminal readback, or cleanup production surface
changed.

The phase adds only public-safe receipt and preparation-trace contracts plus
truthful records. TEST-COV5J proceeds in characterization mode; protected
SCALE remains paused and SCALE29 remains prohibited.

## TEST-COV5J Additive Outcome

TEST-COV5J independently retained the pushed production, deadline, failure,
terminal, receipt, trace, and qualification identities. Candidate-dependent
observer, causality, owning, timing, mixed, and rehearsal groups remain
blocked at zero because corrected-candidate receipt provenance is incomplete.

No cancellation, observer, preparation, timing, runtime identity, terminal, or
cleanup production surface changed. SCALE28-FIX11 is the exact successor;
protected SCALE remains paused and SCALE29 remains prohibited.

## SCALE28-FIX11 Additive Outcome

SCALE28-FIX11 selected Outcome C without changing this ADR's observer,
cancellation, terminal-readback, source-category, runtime-identity, or cleanup
authority. Corrected-candidate provenance is nonunique and candidate execution
remains prohibited.

Accepted-tree tracing retains 40 executions, 29 natural preparation timeouts,
11 successes, 10 controlled first-attempt failures, zero cleanup limitations,
and zero attempt overlap. Existing resource-function probes attribute the
dominant valid work to the required container-RSS resource stage, which exceeds
the selected 1,800 millisecond attempt policy but remains inside ADR 0044's
architectural ceiling.

ADR 0046 remains Accepted as amended. TEST-COV5K was not begun, protected
SCALE remains paused, and SCALE29 remains prohibited pending the narrowly
scoped preparation-policy decision.

## TEST-COV5K-R1 Additive Outcome

The capable-environment retry stopped at its first preparation-policy
authority check before observer-cancellation qualification. The accepted R1
tip still carries 1,800/4,100 milliseconds, while Group A requires the
ADR 0047 3,400/8,900 contract. No cancellation timing source, observer,
terminal, source-category, runtime-identity, or cleanup production owner
changed, and no 500-request campaign or bounded confirmation cohort ran.

ADR 0046 remains Accepted as amended. SCALE29 remains prohibited.

## SCALE28-FIX12-R2 Additive Outcome

The completion phase passed its capable-environment probes and all-suite
opening gate, then stopped before source freeze when the separately required
whole-`src/test` compileall check selected two intentionally invalid syntax
fixtures. No observer, cancellation, request, settlement, close, terminal,
cleanup, timing-source, or runtime-identity production owner changed.

ADR 0046 remains Accepted as amended. No 500-request campaign or qualification
receipt exists, and SCALE29 remains prohibited.

## SCALE28-FIX12-R2-FIX1 Additive Outcome

The retry implements the accepted clock ownership and containment policy:
request authority begins at actual cancellation dispatch; operation settlement
is classification-only; coordinated close never closes under use; a timed-out
close quarantines; late settlement permits exactly one retry; terminal readback
uses separate authority; and cleanup expiry remains incomplete rather than
success. Recorded limitations are never erased.

The complete frozen 500-request protocol and 20-case process-containment
companion pass without changes to cohorts, SQL, thresholds, exclusions, or
acceptance rules. The triple-fault residual remains an honest refusal with no
backend-quiescence or deterministic-reclamation claim. No qualification
receipt is issued; SCALE29 remains prohibited.

## SCALE28-FIX12-R2-FIX2 Additive Correction

Independent review found two evidence defects without changing this ADR's
accepted values. First, terminal readback's `D_term = 500 ms` was a post-hoc
elapsed check around synchronous acquisition, query, fetch, and close. FIX2
now starts one absolute deadline before fresh acquisition and uses
nonblocking libpq polling for acquisition, dispatch, server/result I/O, and
all readiness waits in the one-read operation. A timeout records its exact
stage, reports `backend_quiescent = false`, disposes the exact client
connection, and does not retry. The same deadline checks settlement before
it begins through the last prior authority observation and detects expiry
after settlement returns. Because `PGconn.finish()` is a local same-owner C
call rather than an independently interruptible operation, an abnormal
blocking settlement remains an honest residual; it cannot be reported as
timely success.

Second, R2-FIX1's historical 500-request support compared cancellation request
values with a production policy constant. That oracle could follow an
incorrect product value. FIX2 supersedes the qualification use of that
evidence with an ADR-owned test-support tuple:
`400/450/250/300/50/300/900/1,000/500/5,000/600/650 ms`. Product observations
are compared against that tuple, while policy and production-source digests
are bound separately. Mechanical guards reject product-derived expectations,
positive-value acceptance, authority relabeling, valid removal, and
post-observation threshold changes.

The corrected 500-request cohort retains its historical cohorts, SQL,
thresholds, exclusion rules, and validity rules. It records 500 successes,
zero natural request timeouts, zero transport failures, zero censoring, zero
cleanup failures, and zero valid removals. Its 20-case process-containment
companion records 20 backend disappearances and 20 descriptor cleanups.

The containment audit leaves the accepted semantics unchanged: `D_op` is
classification-only, `D_close` never closes under concurrent use, `D_clean`
expiry remains incomplete, and the triple-fault blocking C-level residual is
quarantined and unqualified. No qualification receipt is issued.
TEST-COV5K-R2 remains required and unauthorized; SCALE29 remains prohibited.
