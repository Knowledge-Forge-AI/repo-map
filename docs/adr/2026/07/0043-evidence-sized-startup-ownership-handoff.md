# ADR 0043: Evidence-Sized Startup Ownership Handoff

## Title

Evidence-Sized Startup Ownership Handoff

## Status

Accepted — Outcome B

## Date

2026-07-22

## Context

SCALE28-FIX3 and TEST-COV5B established that the current 500 ms ownership
handoff cannot simultaneously contain configured observer SQL, strict
server/client/cancellation/caller reserves, transient ownership settlement,
and two final stable ownership samples. TEST-COV5B left a decision between an
evidence-sized in-process ceiling and a bounded revised or process-isolated
startup authority.

SCALE28-ADR1 pre-registered one public-safe fixed measurement campaign and one
integer-millisecond derivation before collecting decision data. Raw timing
observations and runtime identities remain owner-private. This ADR records only
bounded aggregate counts, rounded maxima, the frozen derivation, and the
architecture disposition.

## Problem

Increasing the current handoff without a fixed evidence rule would permit
post-failure tuning and would not establish whether the resulting in-process
window remains within the operator's architecture guard. Retaining 500 ms
would leave the known defects unresolved. The decision therefore requires one
reproducible candidate, explicit margins, a separate guard, and no weakened
ownership or resource fact.

## Decision Drivers

- no child release before all startup authorities are ready;
- settled resource-reader authority with no deferred failure;
- exact refusal of ambient and unknown clients;
- two new final stable ownership samples;
- one exact serialized observer connection;
- TEST-COV4 source-sequenced failure causality;
- SCALE25 terminal settlement and fresh terminal readback;
- deterministic fixed-campaign evidence with no valid observation removal;
- bounded internal deadlines without dynamic or public configuration; and
- a final in-process architecture result at or below the separate 3,000 ms
  operator guard.

## Pre-Registered Protocol

The valid campaign required 30 cold and 30 loaded connection bootstraps, at
least 50 cold and 50 loaded observations for each resource and ownership SQL
category, 30 transient settlements, 30 complete cold handoffs, 30 complete
loaded handoffs, and 15 configured executions for each of SCALE14, SCALE23,
SCALE28, and SCALE28-FIX1.

Cold executions used a new disposable runtime and a one-file public-safe
fixture. Loaded executions used a new disposable runtime and a deterministic
512-file public-safe fixture with representative reference state. Transient
executions first proved an ambient client visible, closed it, then required a
clear sample and a second consecutive clear sample. Every counted configured
execution required publication, child and backend quiescence, and exact
cleanup.

The decision rule retained every valid observation, used maximum valid fixed-
campaign evidence rather than an average or selected percentile, added the
pre-registered margins, rounded upward, and applied the 3,000 ms operator guard
only after deriving the smallest candidate.

## Invalidated First Attempt

The first full instrumentation attempt was invalidated wholesale before any
complete handoff measurement. A just-closed prior observer connection was
correctly reported as transient ambient ownership during the next direct-
session setup. The original harness had not established setup settlement
before its first timed sample.

No duration from that attempt contributes to this decision. The clarified
protocol added an untimed two-consecutive-clear setup barrier, reset the
barrier on any blocked observation, retained all margins and counts, and
restarted the complete campaign from exact cleanup and a fresh record.

## Valid Campaign

The valid campaign completed:

| Evidence class | Complete count |
| --- | ---: |
| Cold complete handoffs | 30 |
| Loaded complete handoffs | 60 |
| Transient settlements | 30 |
| SCALE14 configured executions | 15 |
| SCALE23 configured executions | 15 |
| SCALE28 configured executions | 15 |
| SCALE28-FIX1 configured executions | 15 |

Valid outliers removed: **0**.

The private evidence set was validated for inventory, ownership, permissions,
JSON consistency, aggregate reproduction, invalidated-run separation, and
cleanup, then copied byte-for-byte into owner-private durable storage with a
manifest and validated archive. The exact temporary source was removed only
after durable validation.

## Critical Path

Connection establishment, registration, telemetry-reader readiness, and the
initial two stable ownership samples occur before the measured outer span. The
initial samples are not reused as release evidence.

The measured span starts immediately before startup resource capture and
contains local resource sampling, two serialized resource SQL reads,
settlement of the one already-started asynchronous storage reader, event
readiness, transient ownership clearance, two new final stable ownership
samples, observer activation, and atomic child release. The storage reader is
the only parallel branch and is counted once. Observer operations remain
serialized on one exact connection.

## Aggregate Evidence

The frozen public-safe maxima are:

| Component | Rounded maximum |
| --- | ---: |
| Connection bootstrap | 60 ms |
| Resource/ownership SQL tail | 111 ms |
| Loaded local-resource overhead | 4,144 ms |
| Resource settlement | 280 ms |
| Event readiness | 1 ms |
| Transient clearance | 5 ms |
| Complete outer handoff | 4,524 ms |

The 4,144 ms loaded local-resource maximum is a valid fixed-campaign
observation and is not a removable outlier.

## Derivation

All arithmetic uses integer milliseconds and rounds upward. The frozen inner
result is:

| Authority | Derived bound |
| --- | ---: |
| Connection establishment | 90 ms |
| Server statement timeout | 150 ms |
| Client cancellation trigger | 170 ms |
| Cancellation request | 20 ms |
| Caller operation deadline | 190 ms |
| Observer settlement | 190 ms |
| Local resource work | 4,570 ms |
| Resource settlement | 310 ms |
| Event readiness | 20 ms |
| Transient settlement | 50 ms |

The critical-path component sum is 5,810 ms. The measured complete-handoff
maximum plus the frozen 100 ms scheduling and IPC margin is 4,624 ms. The
accepted 990 ms TEST-COV5B value remains a modeled floor, not a candidate.

The formula selects the largest of the component sum, measured handoff bound,
and 991 ms, then rounds upward to 50 ms. Its result is **5,850 ms**.

## Operator Guard

The 3,000 ms value is an operator architecture guard, not measured evidence.
Measurement instrumentation also used it as bounded internal authority for the
backend monitor's ownership-handoff deadline and direct/transient setup loops,
with a separate 2,500 ms observer statement timeout. It did not install one
wall-clock abort around the complete resource-capture-to-release span.
Therefore the valid 4,524 ms complete span remains decision evidence.

Outcome B follows independently from each controlling comparison:

```text
component-derived bound: 5,810 ms > 3,000 ms
measured handoff bound:   4,624 ms > 3,000 ms
frozen rounded result:    5,850 ms > 3,000 ms
```

## Options Considered

1. **Evidence-sized in-process handoff.** Measured and rejected because the
   frozen 5,850 ms result exceeds the guard.
2. **Process-isolated startup authority.** Retained for SCALE28-ADR2 analysis;
   it may isolate slow preparation and return one typed settled result.
3. **Two-stage revised in-process authority.** Retained for SCALE28-ADR2
   analysis; it requires an immutable scope-bound preparation result and an
   explicit freshness lease before final proof.
4. **Hybrid isolated preparation and in-process final proof.** Retained for
   SCALE28-ADR2 analysis; it separates slow resource work while leaving final
   ownership and release with the parent.

## Decision

Do not adopt a 5,850 ms in-process ownership handoff.

The frozen evidence-sized result exceeds the operator's 3,000 ms architecture
guard. The fixed 500 ms handoff remains known-defective, but increasing it to
the measured value is also rejected.

Proceed to SCALE28-ADR2 to select a bounded process-isolated, two-stage, or
hybrid startup authority. No production timeout value is authorized by this
ADR.

## Safety Invariants

This rejection does not authorize early release, ignored ambient or unknown
clients, fewer stable samples, unsettled resource work, a timed-out SQL result,
observer loss, blind reconnect, dynamic tuning, or a public timeout setting.
The child remains blocked until the existing readiness chain succeeds or a
future accepted architecture replaces it without weakening these facts.

## Consequences

- Option 1 is closed as measured and rejected.
- Production retains the known-defective 500 ms behavior until an explicitly
  authorized implementation phase changes the architecture.
- The 5,850 ms value is decision evidence and is not a production setting.
- Protected SCALE remains paused.
- SCALE29 remains prohibited.
- Startup-authority decomposition requires a separate bounded decision.

## Rejected Alternatives

Retaining 500 ms by reducing stable evidence, ignoring a recently closed
client, skipping resource settlement, or accepting operation timeout is
rejected. Dynamic, adaptive, retry-grown, environment-specific, and public
configuration is rejected. Re-running or removing the dominant valid maximum
to obtain a smaller value is rejected.

## Fallback

SCALE28-ADR2 owns comparison of process-isolated, two-stage, and hybrid startup
authority. Any viable successor must separate slow preparation from the final
atomic release proof, bind preparation to exact scope and generation, preserve
freshness, bound cancellation and cleanup, and keep the final release authority
at or below 3,000 ms.

## Implementation Boundary

This ADR authorizes no production implementation and creates no SCALE28-FIX4
contract for the rejected in-process option. Production constants, known-
defect annotations, dependencies, public configuration, SQL, schemas,
publication, lifecycle, CLI, MCP, and coordinator behavior remain unchanged.

## Qualification Boundary

TEST-COV5C remains a later independent qualification phase for whatever
architecture SCALE28-ADR2 selects and SCALE28-FIX4 implements. No selected-
scope expected failure or configured quarantine may be removed before the
implementation makes it pass. This ADR itself is decision support, not
production qualification.

## Protected-Work Boundary

No protected source or retained runtime was accessed. No protected prelaunch,
refresh, publication, MCP exposure, baseline, drift, closure, or GO24 advice is
authorized or performed.

## Successors

SCALE28-ADR2 is the sole immediate successor and owns bounded startup-authority
decomposition. SCALE28-FIX4, TEST-COV5C, and SCALE29 remain prohibited until
their respective predecessor decisions and qualifications are committed,
pushed, synchronized, clean, and independently approved.

## Post-Acceptance Successor — SCALE28-ADR2

ADR 0044 selects a hybrid isolated resource-preparation worker with parent-
owned final startup authority. It freezes a 5,000 ms per-attempt and 10,000 ms
total preparation ceiling, 650 ms final-release ceiling, and 1,000 ms freshness
lease. This successor does not rewrite ADR1's rejection or authorize 5,850 ms.
