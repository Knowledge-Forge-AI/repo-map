# ADR 0047: Preparation Resource-Sampling Deadline Policy

## Title

Preparation Resource-Sampling Deadline Policy

## Status

Accepted — Outcome A, Decision Category A (selected implementation-policy
amendment; ADR 0044's architecture, resource ownership, and 5,000/10,000
millisecond architectural maxima retained unchanged). This ADR amends only the
selected preparation implementation policy: the attempt timeout moves from
1,800 to 3,400 milliseconds and the total preparation timeout moves from 4,100
to 7,500 milliseconds. Every other selected value, every architectural
maximum, and the complete resource-sampling ownership are retained.

## Date

2026-07-27

## Context

ADR 0044 selected the hybrid bounded startup authority: one spawn-context
isolated worker owns only slow resource preparation, while the parent owns the
continuous observer, freshness, causality, terminal facts, and atomic child
release. SCALE28-FIX4 implemented it and froze a private implementation policy
of 1,800 milliseconds per attempt and 4,100 milliseconds total preparation
beneath ADR 0044's 5,000 millisecond attempt and 10,000 millisecond total
architectural maxima.

SCALE28-FIX9 exposed repeated frozen preparation-worker deadline exhaustion in
actual configured SCALE14 owning campaigns. SCALE28-FIX10 and TEST-COV5J froze
public-safe receipt and critical-path trace contracts without inferring a
dominant stage. SCALE28-FIX11 then produced two independent closed results:

- corrected-candidate provenance is `nonunique_base` — five nonidentical
  exact base trees and five nonidentical exact result trees satisfy every
  object, mode, manifest, and unchanged-apply constraint, so no corrected
  candidate tree exists and candidate execution count is zero; and
- accepted-tree evidence selects Fork B — valid required resource work
  exceeds the selected 1,800 millisecond attempt policy while remaining
  within ADR 0044's 5,000 millisecond architectural attempt ceiling.

FIX11's committed successor is exactly one narrowly scoped ADR for the
selected preparation implementation policy. This is that ADR.

## Problem

What selected preparation implementation policy and resource-sampling
authority should replace or retain the 1,800/4,100 millisecond policy, given
that the required container-RSS/concurrent-resource evidence exceeds 1,800
milliseconds but remains under ADR 0044's 5,000 millisecond architectural
attempt ceiling?

The answer must be closed: it must fix the attempt clock origin, attempt
timeout, total two-attempt timeout, resource-stage ownership, container-RSS
authority, other resource readers, observation transfer, acknowledgement,
receipt, process settlement, cleanup, attempt-two eligibility, freshness,
final-release interaction, failure categories, and platform/runtime scope.

## Evidence Hierarchy

This ADR distinguishes four evidence populations and never silently pools
them:

1. **Actual attempt evidence** — the FIX11 accepted-tree trace packet: 40
   controlled executions, 50 attempt records, 29 natural
   `preparation_timeout` terminals, 11 successes, 10 controlled first-attempt
   `worker_failed` terminals, zero cleanup limitations, zero attempt overlap,
   zero third attempts. This is the highest-authority population for policy
   sufficiency frequency.
2. **Successful-subset evidence** — parent start-to-frame durations of
   1,229.168 to 1,390.400 milliseconds observed only on the 11 successful
   attempts. This population is survivorship-conditioned: it contains only
   attempts whose resource work completed inside 1,800 milliseconds.
3. **Diagnostic resource-function evidence** — 40 component probes through
   the exact production reader functions (`read_allocated_tree_bytes`,
   `read_backing_free_bytes`, `read_process_rss_bytes`,
   `read_container_rss_upper_bound`, connection bootstrap,
   `read_database_temporary_bytes`, `read_cluster_wal_bytes`) and through the
   exact four-way concurrent group shape used by `prepare_resources`. These
   are diagnostic re-invocations outside a spawned worker, not in-attempt
   measurements.
4. **Source-derived architectural inference** — facts read directly from the
   accepted source: the pre-spawn clock origin, the nested subordinate
   deadlines, the `<runtime> stats --no-stream` container-RSS mechanism, and
   the bounded failed-attempt settlement path.

Population 1 proves the policy is insufficient at high frequency. Population 3
attributes the insufficiency to one owned stage. Population 2 bounds the
non-resource overhead of a complete successful attempt. Population 4 explains
the latency mechanism and bounds cleanup. No single population is treated as
sufficient alone; the decision below cites each for exactly the claim it can
support.

## Original Policy Basis

SCALE28-FIX4 selected 1,800/4,100 milliseconds as a **measured bound plus
margin policy**, not a derived architectural formula:

- the formal retained FIX4 selection campaign observed maxima of 1,130
  milliseconds worker preparation, 23 milliseconds parent protocol, 2
  milliseconds acknowledgement-to-receipt, 22 milliseconds
  receipt-to-settlement, and 1,255 milliseconds complete parent attempt;
- 1,800 milliseconds is the observed 1,255 millisecond complete-attempt
  maximum plus approximately 43 percent margin, rounded to a policy value;
- 4,100 milliseconds is two attempts plus a 500 millisecond inter-attempt
  reserve (2 × 1,800 + 500).

The original basis therefore embedded one **historical environment
assumption**: that the container-RSS read observed during the FIX4 campaign
(inside the 1,130 millisecond worker-preparation maximum) represented the
stationary behavior of the container engine's statistics path. SCALE28-FIX11
disproves exactly that assumption: the same required reader now shows a
1,984.661 millisecond median and 2,035.099 millisecond maximum across 40
probes, and 29 of 40 accepted-tree executions naturally exhaust the 1,800
millisecond attempt deadline. The FIX4 decision was correct on its campaign
evidence; the campaign evidence did not capture the engine's slow sampling
mode that now dominates.

No other element of the original basis is disproved. The pre-spawn clock
origin, two-attempt limit, subordinate deadlines, freshness lease, and final
release values are untouched by the FIX11 evidence.

## FIX11 Accepted-Tree Evidence

The authoritative committed trace packet reports:

```text
accepted-tree controlled executions:        40
attempt records:                            50
natural preparation timeouts:               29
successful attempts:                        11
controlled first-attempt worker failures:   10
cleanup limitations:                         0
attempt overlap:                              0
third attempts:                               0
candidate executions:                         0
```

Conditions were quiet, bounded CPU contention, bounded filesystem contention,
and bounded connection churn (five each), plus complete-gate prelude and
immediate second-attempt reacquisition (ten each). Every controlled first
attempt settled completely before attempt two. Successful parent
start-to-frame duration ranged from 1,229.168 to 1,390.400 milliseconds.

## FIX11 Component-Probe Evidence

The committed public-safe aggregates over 40 diagnostic probes:

```text
allocated-tree reader:      min 3.887      median 5.842      p95 1,721.692   max 1,833.992
backing-free read:          min 0.025      median 0.143      p95 12.658      max 38.111
client RSS:                 min 3.289      median 4.770      p95 52.076      max 78.971
container RSS:              min 1,041.965  median 1,984.661  p95 2,016.661   max 2,035.099
concurrent resource group:  min 1,042.770  median 1,988.482  p95 2,019.727   max 2,147.613
connection:                 min 4.159      median 8.385      p95 68.780      max 113.644
temporary bytes:            min 0.771      median 1.357      p95 36.554      max 42.125
WAL bytes:                  min 0.204      median 0.362      p95 37.682      max 43.612
```

Container RSS is the dominant owned sub-stage. The required concurrent
resource group exceeds 1,800 milliseconds at its median and remains below
5,000 milliseconds at its maximum.

## Evidence-Population Reconciliation

The 1,229–1,390 millisecond successful start-to-frame observations and the
approximately two-second container-RSS probes are **not one homogeneous
population**, and this ADR does not pool them. They reconcile as follows.

**Probe fidelity.** The component probes invoke the exact production reader
functions with production-shape arguments against the same accepted-gate
container runtime and PostgreSQL container, and the concurrent-group probe
reproduces the exact four-reader `ThreadPoolExecutor` shape of
`prepare_resources`. They are diagnostic re-invocations executed outside a
spawned worker: they exclude worker spawn, interpreter import, request decode,
frame transfer, and parent validation. Because the dominant cost is a
subprocess invocation of the container engine's CLI, worker-versus-harness
invocation context does not change the dominant term. Probe overhead
(subprocess spawn of the CLI) is itself part of the production mechanism, so
it is representative rather than inflationary.

**The bimodal mechanism.** `read_container_rss_upper_bound` shells out to
`<runtime> stats --no-stream --format {{.MemUsage}} <container>` under a fixed
5-second command timeout. This CLI blocks until the engine daemon delivers a
complete statistics frame from its internal sampling cycle, so its latency is
dominated by where the request lands in that cycle — this is source-derived
inference confirmed by the observed distribution, which is strongly bimodal:
a fast mode near 1.0–1.1 seconds (probe minimum 1,041.965 milliseconds) and a
slow mode near 2.0 seconds (median 1,984.661, p95 2,016.661). Nothing in the
distribution suggests a third, slower mode below the 5-second command
timeout.

**Reconciliation.** The 11 successful attempts are exactly the fast-mode
draws: fast-mode group work of roughly 1,042–1,100 milliseconds plus observed
spawn/import/decode/serial-SQL/frame residual of roughly 190–350 milliseconds
yields the observed 1,229–1,390 millisecond start-to-frame range. The 29
natural timeouts are the slow-mode draws: roughly 2,000 milliseconds of group
work plus the same residual exceeds 1,800 milliseconds before the observation
frame can be sent. The 11/29 success/timeout split of the attempt population
and the fast/slow mixture of the probe population are mutually consistent.
The successful subset is therefore survivorship evidence — it proves the
policy is *satisfiable* in the fast mode, not that the policy is
*sufficient*; the 29 natural timeouts prove the slow mode is the common case.

**Condition mixture.** The 40 attempts span six controlled conditions and the
40 probes were collected as one diagnostic series. The mixtures are not
identical, but the group maximum under bounded contention (2,147.613
milliseconds) exceeds the quiet-condition median by only about 160
milliseconds, so condition mixture does not change the conclusion: both
populations show the same dominant two-second mode.

**Sufficiency.** The component evidence alone would not justify a policy
amendment. The amendment rests on the conjunction: 29 of 40 actual attempts
naturally timed out (population 1), the dominant stage is attributed to one
required owned reader (population 3), the mechanism is identified in accepted
source (population 4), and the non-resource overhead is bounded by the
successful subset (population 2). A vague "the stage is slow" claim is
explicitly not the basis of this decision.

## Current Architecture

Retained unchanged from ADR 0044, ADR 0045, and ADR 0046 as amended: the
isolated spawn-context preparation worker; parent-owned attempt and total
authority; maximum two attempts; pre-spawn preparation clock origin; deeply
immutable preparation evidence; bounded observation/ACK/receipt-v3 IPC;
parent-monotonic freshness authority; attempt-one settlement before attempt
two; one global parent event sequence; per-attempt worker-local sequencing;
closed preparation trace variants; TEST-COV4 source-sequenced failure
causality; the one 600 millisecond final-release implementation window under
the 650 millisecond architectural maximum; four observer operation classes;
one acquisition-aware observer caller deadline; the one-read FIX9 terminal
correction; fresh terminal backend quiescence; runtime-identity
qualification; ordered seven-family publication; and sampled RSS and
structural-digest authority.

## Attempt Clock Contents

The attempt clock origin is the parent monotonic reading captured immediately
before `process.start()` in `PreparationWorkerAttempt.run`. Exact stage
disposition, from accepted source:

| Stage                              | Disposition |
| ---------------------------------- | ----------- |
| Parent authority creation          | Outside attempt, inside total authority (runs before the attempt clock starts, after the total clock starts) |
| Process spawn                      | Inside attempt authority |
| Interpreter startup/import         | Inside attempt authority |
| Request decode and validation      | Inside attempt authority |
| PGDATA walk (allocated tree)       | Inside attempt authority (concurrent group) |
| Filesystem observation (backing free) | Inside attempt authority (concurrent group) |
| Container RSS                      | Inside attempt authority (concurrent group; also under the reader's own fixed 5-second command timeout) |
| Client RSS                         | Inside attempt authority (concurrent group) |
| Connection bootstrap               | Inside attempt authority (serial, after the group; 2-second connect timeout, 4,000 ms statement timeout) |
| Temporary bytes                    | Inside attempt authority (serial) |
| WAL bytes                          | Inside attempt authority (serial) |
| Baseline assembly                  | Inside attempt authority |
| Canonical encoding                 | Inside attempt authority |
| Digest                             | Inside attempt authority |
| Observation-frame transfer         | Inside attempt authority (parent waits `A − elapsed`; 100 ms transfer reserve bounds settlement of the read) |
| Parent validation                  | Inside attempt authority |
| ACK round trip                     | Inside attempt authority; worker-side wait separately bounded by the 150 ms acknowledgement timeout |
| Receipt creation and transfer      | Inside attempt authority; parent wait is `min(A − elapsed, 300 ms)` — a nested subordinate deadline, never additive to A |
| Child exit                         | Inside attempt authority (success path) |
| Process-tree settlement (success)  | Inside attempt authority; parent wait is `min(A − elapsed, 300 ms)` — nested, never additive |
| Attempt cleanup (failure path)     | Outside attempt authority, inside the preparation wall clock; bounded by the fixed failed-settlement path (at most ~700 ms: SIGTERM + 100 ms join + SIGKILL + 300 ms join + 300 ms group wait) |

No stage is double charged: the acknowledgement, receipt, and settlement
subordinate deadlines are consumed *within* A via `min()` composition, and the
failed-attempt cleanup path runs only after A has terminated the attempt.

## Resource-Group Ownership

Answers to the required ownership questions, from accepted source:

- **Concurrency.** Container RSS, client RSS, the PGDATA allocated walk, and
  the backing-free read are concurrent (one four-worker
  `ThreadPoolExecutor`). The connection bootstrap and the two SQL reads
  (temporary bytes, WAL bytes) are serial after the group completes.
- **Gating stage.** Resource-baseline completion is gated by the slowest
  group member — in the current evidence, container RSS — plus the serial
  SQL tail.
- **Dominance correctness.** One slow reader correctly dominates the group:
  the group is all-or-nothing because the baseline requires every field, and
  the whole worker process is the cancellation boundary.
- **Reuse from a parent sampler.** No. The accepted architecture forbids
  descriptor, process, connection, channel, or sampler inheritance, and the
  parent samplers are *seeded from* the accepted worker baseline, not the
  reverse. Reusing a parent-owned sample would break exact-attempt binding
  and evidence immutability.
- **Pre-spawn start.** No read may begin before worker spawn without
  breaking exact-attempt binding: every baseline field must be produced under
  the attempt's nonce, attempt identity, and worker-local sequence.
- **Asynchronous container RSS.** Rejected: sampling container RSS outside
  the worker attempt would detach the dominant field from the attempt
  identity, worker-local ordering, and the whole-process cancellation
  boundary, and would require a new freshness authority for one field.
- **Double invocation.** The current implementation invokes each resource
  reader exactly once per attempt. No reader is invoked twice.
- **Intrinsic slowness.** The container-RSS implementation is intrinsically
  slow because of engine startup/sampling behavior: it is one subprocess
  invocation of `<runtime> stats --no-stream`, whose latency is dominated by
  the engine daemon's statistics cycle, not by the worker or by repository
  code.
- **Faster equivalents.** Faster mechanisms exist (for example a one-shot
  engine API statistics call or an in-container cgroup read), but none is
  selected: they change the measurement mechanism and therefore the
  semantic authority ("engine-reported container memory usage upper bound"),
  they would invalidate the qualified timing evidence, and no redesign may be
  selected merely because it is faster. The mechanism is retained; a future
  mechanism change is a requalification trigger, not a policy value.

## Freshness Interaction

The 800 millisecond freshness lease is **retained unchanged**, and the
selected remedy for the longer attempt is **retain the existing policy and
ownership — no reorder, no resample, no lease amendment** — because of the
following source facts:

- freshness age begins at the parent-monotonic observation-frame receipt
  minus the 100 millisecond transfer reserve
  (`observation_received_parent_ns − 100 ms`), not at any worker-side read
  time;
- container RSS is sampled concurrently with the other group reads, before
  the serial SQL reads and before the observation frame, but worker-side
  sampling times never enter the freshness clock: worker-local timestamps
  prove only internal ordering;
- therefore a longer attempt cannot make evidence stale before receipt —
  lease consumption starts only when the frame arrives at the parent, and
  the post-receipt consumers (receipt validation, worker settlement, the
  two stable observer samples, and the 600 millisecond final-release window)
  are unchanged by this ADR;
- receipt creation resets no evidence clock — the origin is fixed at frame
  receipt minus reserve, and every later checkpoint measures against that
  single origin;
- final-release checks can still prove freshness exactly as before: the
  observed post-receipt path (frame-to-receipt maximum 39.035 milliseconds,
  settlement maximum 24.873 milliseconds, FIX4-observed final release 382
  milliseconds) consumes well under 800 milliseconds; and
- no resource must be resampled after a longer preparation: the evidence
  ages from parent receipt, and the lease already assumed nothing about
  attempt length.

The lease is explicitly **not** raised to accommodate the larger attempt: no
evidence shows post-receipt consumption grew, and raising the lease without
evidence would weaken the release proof.

## Subordinate Deadline Interaction

| Subordinate authority              | Disposition |
| ---------------------------------- | ----------- |
| 100 ms observation-transfer reserve | Retained unchanged. It bounds one-shot read settlement and conservatively backdates the freshness origin; it is unrelated to attempt length. |
| 150 ms acknowledgement timeout      | Retained unchanged. Observed acknowledgement-to-receipt maximum is 0.046 milliseconds; the value is worker-side and nested inside A. |
| 300 ms receipt timeout              | Retained unchanged. Nested inside A via `min(A − elapsed, 300 ms)`; observed frame-to-receipt maximum is 39.035 milliseconds. |
| 300 ms process-settlement timeout   | Retained unchanged. Nested inside A on the success path via `min()`; reused as the fixed join/group-wait bound on the failed-cleanup path outside A; observed success-path maximum is 24.873 milliseconds. |

No subordinate deadline is amended, removed, duplicated, or silently
multiplied. All four remain nested consumers of A (or, for failed cleanup,
fixed bounds outside A), exactly as implemented.

## Options Considered

### Option A — amend selected attempt and total policy only

Retain resource ownership and architecture; select new `A` and `P` within
ADR 0044 maxima.

- *Safety*: no production semantics change; the policy dataclass already
  fail-closed-validates the architectural maxima (attempt ≤ 5,000, total ≤
  10,000, subordinates < attempt, exactly two attempts).
- *Availability*: eliminates the dominant natural-timeout mode (slow-mode
  worst attempt ≈ 2,560 milliseconds observed-derived, versus A = 3,400 with
  approximately 33 percent headroom).
- *Margin*: visible component-derived margins (derivation below); no
  observed-max-plus-epsilon.
- *Freshness*: unaffected — lease origin is at parent frame receipt.
- *Cross-platform*: unchanged fail-closed behavior; timing qualification
  remains bound to the named stack below.
- *Implementation complexity*: two integer literals in the private policy
  module plus test updates.
- *Qualification burden*: preparation-policy qualification only; observer
  cancellation timing surfaces untouched by the policy change itself.
- *Risk before SCALE29*: lowest of the four options.

### Option B — amend policy plus a dedicated resource-stage subauthority

Give the concurrent resource group or the container-RSS stage its own
subordinate deadline composed under `A`.

Rejected. The whole worker process is the cancellation boundary (ADR 0044);
a resource-stage deadline inside the worker could not terminate the stage
without terminating the worker, so it would either duplicate A (same expiry
outcome, second authority) or introduce partial-attempt states the trace
contract prohibits. The container-RSS reader already carries its own fixed
5-second command timeout as a fail-closed bound; adding a third layer is
exactly the double-charged deadline multiplication this ADR must reject.

### Option C — change resource-sampling ownership or decomposition

Analyzed examples: reuse a parent-owned authoritative sampler; continuous
sampling with exact attempt binding; move container RSS outside the worker;
replace the measurement mechanism with a semantically equivalent faster
reader.

Rejected. Every variant weakens at least one retained invariant: parent
sampler reuse breaks the no-inheritance rule and exact-attempt binding;
continuous or outside-worker sampling detaches the dominant field from
attempt identity, worker-local ordering, and whole-process cancellation, and
needs a new per-field freshness authority; mechanism replacement changes the
semantic authority and voids the qualified timing evidence. No variant is
required by the evidence — the observed work fits comfortably under the
architectural ceiling — and no redesign may be selected merely because it is
faster.

### Option D — retain 1,800/4,100 and correct the evidence authority

Available only if the FIX11 component probes are proved unrepresentative of
the actual required critical path.

Rejected on the evidence. The probes call the exact production reader
functions and the exact concurrent-group shape; the populations reconcile
(bimodal engine mechanism; successful subset is survivorship-conditioned);
and — decisively — the 29 natural timeouts are population-1 *actual attempt*
evidence that does not depend on the probes at all. There is no population
mismatch to name, so Option D's entry condition fails.

## Decision

Select **Option A**. Amend the selected implementation policy to a 3,400
millisecond attempt timeout and a 7,500 millisecond total preparation
timeout. Retain every other selected value, the complete resource-sampling
ownership, the container-RSS mechanism, and all ADR 0044/0045/0046
architectural authorities unchanged.

## Decision Category

**Category A — selected implementation-policy amendment.** No other category
is authorized. The central choice is closed here and is not deferred to
SCALE28-FIX12.

## Selected Numeric Policy

Symbols:

```text
A          selected attempt timeout
P          selected total preparation timeout
R_group    required concurrent resource-group allowance
R_serial   serial connection + temporary-bytes + WAL-bytes allowance
M_spawn    process spawn / interpreter import / request-decode margin
M_ipc      observation/ACK/receipt transfer margin
M_sched    scheduling/contention margin
M_settle   process-settlement/cleanup margin (success-path nested bound)
C_fail     failed-attempt settlement bound (outside A)
N          maximum attempts = 2
```

Rounding and margin policy (visible, no autotuning, no observed-max-plus-
epsilon): each evidence-derived term is the observed component maximum
rounded **up to the next 100 milliseconds**; margins are dedicated terms, not
epsilons folded into observations.

Derivation:

```text
R_group  = ceil100(2,147.613)                  = 2,200 ms
R_serial = ceil100(113.644 + 42.125 + 43.612)  =   200 ms
M_spawn  = ceil100(1,390.400 − 1,042.770)      =   400 ms
M_ipc    = observation-transfer reserve value  =   100 ms
M_settle = retained settlement subordinate     =   300 ms
M_sched  = ceil100(2,147.613 − 1,988.482)      =   200 ms

A = R_group + R_serial + M_spawn + M_ipc + M_settle + M_sched
  = 2,200 + 200 + 400 + 100 + 300 + 200
  = 3,400 ms

C_fail = 100 (SIGTERM join) + 300 (SIGKILL join) + 300 (group wait)
       = 700 ms

P = 2·A + C_fail = 6,800 + 700 = 7,500 ms
```

Constraint checks:

```text
A = 3,400  ≤ 5,000   (ADR 0044 attempt architectural maximum)      ✓
P = 7,500  ≤ 10,000  (ADR 0044 total architectural maximum)        ✓
N = 2                                                              ✓
worst-case preparation wall clock = 2·(A + C_fail) = 8,200 ≤ 10,000 ✓
attempt-two eligibility after worst attempt-one failure:
  A + C_fail = 4,100 < P = 7,500                                   ✓
subordinate deadlines (150/300/300) < A                            ✓
freshness lease 800 < P                                            ✓
no hidden third-attempt reserve (N = 2, loop-bounded)              ✓
no use of the final-release 650 ms headroom (600 ms window retained,
  outside A and P as before)                                       ✓
```

The M_spawn residual (successful start-to-frame maximum minus fast-mode group
minimum) numerically includes some serial-SQL and frame time already covered
by R_serial and M_ipc; that overlap is retained deliberately as visible extra
margin rather than subtracted, because worker import duration has no
independent closed observation (FIX11).

## Normative Authority Table

| Authority | Value | Clock origin | Owner | Terminal condition | Expiry category | Success/failure path | Relation to A and P |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Attempt timeout | **3,400 ms** (amended) | Parent monotonic, immediately before worker spawn | Parent (`PreparationWorkerAttempt`) | Observation, receipt, and settlement complete; or any wait exhausts remaining A | `preparation_timeout` | Success: evidence accepted. Failure: attempt refused, failed-settlement path runs | Is A |
| Total preparation timeout | **7,500 ms** (amended) | Parent monotonic, at `prepare()` entry, before attempt one | Parent (`HybridPreparationAuthority`) | Accepted generation, or both attempts consumed, or gate reached | Preparation refused (`PreparationAuthorityError`) | Success: prepared sample returned. Failure: REFUSED state | Is P; attempt-two eligibility gate checked before each attempt start; each attempt internally bounded by A |
| Maximum attempt count | 2 (retained) | — | Parent | — | No third attempt exists | — | Bounds P's derivation |
| Attempt clock origin | Pre-spawn (retained) | — | Parent | — | — | — | Defines A's start |
| Resource-group authority | Worker-owned four-way concurrent group + serial SQL tail (retained) | Worker-local, ordering only | Worker | All fields produced or one reader fails | `resource_unavailable` / `resource_reader_failed` / `worker_connection_bootstrap_failed` | Failure notice sent before worker exit | Entirely inside A |
| Container-RSS authority | `read_container_rss_upper_bound` via `<runtime> stats --no-stream`, worker-owned, in-attempt, fixed 5,000 ms command timeout (retained) | Worker-local | Worker | Value parsed or command fails/times out | `resource_unavailable` at `container_rss_read` | Same | Inside A; its 5 s command timeout is a fail-closed reader bound, not an attempt authority |
| Observation-transfer reserve | 100 ms (retained) | Parent monotonic at frame availability | Parent | One-shot read settles | IPC refusal | — | Nested inside A; also backdates freshness origin |
| ACK timeout | 150 ms (retained) | Worker-local at ACK wait start | Worker | ACK received | `acknowledgement` failure terminal | — | Nested inside A |
| Receipt timeout | 300 ms (retained) | Parent monotonic at receipt wait start | Parent | Receipt received | Receipt failure terminal | — | `min(A − elapsed, 300)` — nested inside A |
| Process-settlement timeout | 300 ms (retained) | Parent monotonic at join start | Parent | Worker exit observed, group settled | Settlement failure terminal | Success path nested in A; failure path fixed bound outside A | Nested inside A (success); component of C_fail (failure) |
| Cleanup authority | Failed-settlement path: SIGTERM + 100 ms + SIGKILL + 300 ms + 300 ms group wait (retained) | Parent monotonic at failure | Parent | Process group absent | Cleanup limitation | Failure path only | Outside A, inside preparation wall clock; C_fail = 700 ms bound |
| Freshness lease | 800 ms (retained) | Parent monotonic at observation receipt − 100 ms reserve | Parent | Release or stale checkpoint | Stale refusal + full reacquisition | Checked at receipt, settlement, stable samples, release | Independent of A; must be < P (holds: 800 < 7,500) |
| Final-release window | 600 ms selected / 650 ms architectural maximum (retained) | Parent monotonic at `open_final_readiness` | Parent | Child released | Final-window refusal | — | Outside A and P |
| Architectural maxima | 5,000 ms attempt / 10,000 ms total / 2 attempts (retained, not amended) | — | ADR 0044 | — | Policy construction refuses violating values | — | Upper bounds on A and P, enforced by `PreparationDeadlinePolicy.__post_init__` |

## Attempt And Total State Machine

Retained exactly as implemented, with the two amended values substituted:

1. `prepare()` records the total deadline (`now + P`) and iterates attempts
   1..2. Before each attempt start, if the total deadline has passed, no
   further attempt begins (attempt-two eligibility gate).
2. Each attempt captures its pre-spawn origin, spawns one worker in one
   POSIX process group, and consumes A across observation wait, receipt wait
   (`min` with 300 ms), and settlement join (`min` with 300 ms).
3. A successful attempt validates parent ordering
   (observation ≤ receipt ≤ settlement), accepts evidence, sets the
   freshness origin, and proceeds toward final release.
4. A failed attempt sets the cancellation event, runs the bounded
   failed-settlement path (≤ C_fail), closes all channels, records exactly
   one source-sequenced failure, and — only if fully settled and attempts
   remain and the total gate passes — permits attempt two with a completely
   new nonce, attempt identity, generation, worker, process group, and
   channels.
5. P is an eligibility gate, not a wall-clock truncator of a running
   attempt: the preparation wall clock is bounded by 2·(A + C_fail) = 8,200
   milliseconds, under the 10,000 millisecond architectural total.
6. No third attempt exists; exhaustion transitions to REFUSED and raises.

## Failure Causality

TEST-COV4 source-sequenced first-source categories are retained exactly:

```text
container-RSS source failure        resource_unavailable at container_rss_read
other resource-reader failure       resource_unavailable / resource_reader_failed
                                    at the exact reader boundary
connection bootstrap failure        worker_connection_bootstrap_failed
attempt timeout                     preparation_timeout at boundary worker
total preparation timeout           preparation refused after final attempt
                                    (no synthetic category; last real failure
                                    is causal)
observation transfer failure        bounded-IPC refusal category
ACK failure                         acknowledgement failure terminal
receipt failure                     receipt failure terminal
process-settlement failure          settlement failure terminal
cleanup limitation                  cleanup limitation terminal
freshness failure                   stale refusal (parent authority)
```

Two prohibitions are restated as normative: an attempt timeout must not be
reported as `resource_reader_unavailable` merely because the worker is
terminated while a resource read is active (the parent's `preparation_timeout`
is first-source when A expires); and a real resource-reader failure must not
be hidden as a timeout (the worker's failure notice, when it arrives before A
expires, is first-source). The FIX11 trace contract's source-domain
prohibition (no later work in a failed source domain) is retained.

## Platform And Engine Scope

Selected scope: **one explicitly named qualified stack**.

The 3,400/7,500 millisecond selected policy is timing-qualified only for the
exact local stack on which the FIX11 evidence was produced and which
TEST-COV5J froze by path-bound digest: the operator's local POSIX (macOS)
host, the accepted-gate CPython virtual environment, and the accepted-gate
Docker engine and PostgreSQL container configuration. No Windows, Linux,
Podman, or OrbStack timing qualification is claimed.

On any other stack the existing fail-closed behavior governs: non-POSIX
platforms refuse preparation containment outright; the specification accepts
only the closed `docker`/`podman` runtime vocabulary; an unavailable or
slower engine produces bounded `resource_unavailable` or
`preparation_timeout` refusals within the unchanged two-attempt authority.
Timing insufficiency on an unqualified stack is a requalification event, not
a tuning surface: there is no dynamic tuning and no environment-variable
timeout selection.

## Requalification Triggers

Requalification of the selected policy (a new bounded evidence phase, not a
value edit) is required before relying on the policy after any of:

- container runtime change (docker ↔ podman) or engine major-version change
  on the qualified stack;
- host operating-system or machine-architecture change;
- any change to the `read_container_rss_upper_bound` mechanism or its command
  timeout;
- any change to the `prepare_resources` concurrency shape or reader set;
- recurrence of natural `preparation_timeout` terminals in complete gates or
  configured campaigns on the qualified stack;
- any amendment of the ADR 0044 architectural maxima.

## Corrected-Candidate Provenance Disposition

The FIX11 result `nonunique_base` (five nonidentical exact base trees, five
nonidentical exact result trees, candidate execution count zero) is accepted
as final for the historical corrected patch. Normative dispositions:

- SCALE28-FIX12 is a **fresh test-first semantic reimplementation on current
  `main`**;
- the ambiguous corrected patch is **not implementation authority**;
- private patch bytes are **not copied** into any candidate, test, or
  document;
- committed ADRs (0044, 0045, 0046 as amended, and this ADR), committed
  source, and executable tests define FIX12 behavior;
- arbitrary selection among the five candidate trees is prohibited; no
  phase may designate one of them canonical by date, proximity, or
  convenience.

## Compatibility

- The policy dataclass (`PreparationDeadlinePolicy`) already validates the
  amended values: 3,400 ≤ 5,000, 3,400 ≤ 7,500 ≤ 10,000, subordinates <
  3,400, freshness 800 < 7,500, exactly two attempts. No validation change is
  required or authorized.
- `startup_handoff_timeout_seconds` equals A by existing accepted contract
  and is reused as the pre-preparation backend startup-summary wait. Under
  this amendment that wait moves from 1.8 to 3.4 seconds. This coupling is
  retained deliberately and named here so it is not a silent change; FIX12
  must not decouple it without a successor decision.
- The freshness lease, final-release window, observer deadlines, cancellation
  containment, publication, SQL/schema, dependency, public CLI/MCP,
  coordinator, protected-runtime, and retained-runtime boundaries are
  unchanged.
- The FIX11 characterization module's `decision()` helper compares the frozen
  aggregates against the historical 1,800 millisecond policy; it remains
  correct as a historical record of the FIX11-time decision and is not
  retuned.

## Consequences

- The dominant natural-timeout mode (29 of 40 executions) is removed by
  policy: the observed-derived worst slow-mode attempt (~2,560 milliseconds)
  fits under A = 3,400 with approximately 33 percent headroom.
- Worst-case preparation wall clock rises from 2·(1,800 + 700) = 5,000 to
  2·(3,400 + 700) = 8,200 milliseconds — still under the 10,000 millisecond
  architectural total. Startup latency in genuine failure scenarios increases
  accordingly; success-path latency is unchanged (work completes when the
  engine responds, not at the deadline).
- The pre-preparation backend startup-summary wait rises with A (see
  Compatibility).
- FIX12 carries a small, sharply bounded production diff for the policy
  itself, plus the separately contracted ADR 0045/0046 reimplementation.
- TEST-COV5K must independently qualify the amended policy on the named
  stack before SCALE29.

## Superseded Statements

- ADR 0044's SCALE28-FIX4 Implementation section statement that the frozen
  private policy is "1,800 ms per attempt, 4,100 ms total preparation" is
  superseded by 3,400/7,500 for all successor work; the historical record of
  FIX4's selection stands unedited.
- Any reading of FIX4's campaign maxima (1,130/1,255 milliseconds) as a
  stationary bound on container-engine statistics latency is superseded by
  the FIX11 evidence.

No statement of ADR 0045 or ADR 0046 is amended by this ADR.

## Rejected Alternatives

- Options B, C, and D above, for the reasons stated there.
- Observed-maximum-plus-epsilon values (for example 2,200/4,500): rejected
  by the required visible margin policy.
- Raising the freshness lease alongside A: rejected; no evidence shows
  post-receipt consumption grew.
- Deriving P as exactly 2·A: rejected; it ignores the bounded failed-cleanup
  and inter-attempt costs that the eligibility gate must cover (Mandatory
  audit: attempt-one cleanup is outside A and inside the wall clock;
  attempt-two reacquisition work before spawn is outside A and covered by
  C_fail's margin within P; subordinate transfer/ACK/receipt/settlement
  authorities are nested inside each A and add nothing to P).
- Runtime autotuning or environment-variable timeout selection: prohibited.
- A dedicated in-worker resource-stage deadline: rejected as duplicate
  authority (Option B).

## Simplification Disposition

| Artifact | Disposition |
| --- | --- |
| 1,800/4,100 ms policy values | Superseded in FIX12 (two literals in `scale28_preparation_policy.py`); historical records retained unedited |
| 5,000/10,000 ms architectural maxima | Retain unchanged |
| FIX11 component probes (frozen aggregates) | Retain as historical evidence only; no rerun required or authorized |
| FIX11 accepted-tree trace support (`scale28_fix11_preparation_trace`) | Retain; TEST-COV5K derives expectations from it |
| FIX11 patch-provenance parser | Retain; its `nonunique_base` regression is the executable guard against candidate resurrection |
| Ambiguous corrected patch (private) | Retain as historical evidence only; never implementation authority |
| Original FIX8 patch (private) | Retain as historical evidence only |
| FIX9 fourteen-case failure inventory | Retain; TEST-COV5K executes the fourteen former failures |
| FIX10 receipt verifier | Retain |
| TEST-COV5J characterization path-bound digests | Retain as historical evidence only; they describe the pre-FIX12 tree and must not gate FIX12's changed source |
| Historic candidate-selection helpers | Delete after TEST-COV5K Outcome A, in a separately bounded cleanup phase; no broad cleanup before qualification |

## SCALE28-FIX12 Contract

Implementation-ready contract for Claude Opus 5. SCALE28-FIX12 begins only
from current accepted `main` after this ADR's commit is manually published.

### Authority and provenance

- Fresh test-first semantic implementation. The ambiguous corrected patch and
  all five candidate trees are prohibited as source authority; private patch
  bytes must not be copied. Committed ADRs 0044/0045/0046-as-amended, this
  ADR, committed source, and executable tests define behavior. Stale
  candidate-era documents are not behavior authority.
- FIX12 must implement: (a) ADR 0045's final-release observer authority and
  ADR 0046's bounded cancellation containment as amended; (b) this ADR's
  3,400/7,500 millisecond selected policy; (c) retention of the FIX9 one-read
  terminal correction and source-category fidelity; (d) retention of the
  FIX11 trace variants, one global parent sequence, and per-attempt
  worker-local sequencing.

### Authorized production scope

- `tools/scale28_preparation_policy.py`: exactly the two amended integers in
  `DEFAULT_PREPARATION_DEADLINE_POLICY` (`attempt_timeout_ms=3_400`,
  `total_timeout_ms=7_500`). No other field.
- The observer/terminal production areas that ADR 0045 and ADR 0046 as
  amended define: the parent-owned observer session and its four operation
  classes, acquisition-aware caller deadline, cancellation-request and
  settlement authority, terminal readback (one fresh read inside the frozen
  terminal authority), and structured startup-result retention. Exact file
  boundaries are derived from ADRs and current source, never from the private
  manifest.

### Prohibited scope

- `scale28_preparation_worker.py`, `scale28_preparation_resources.py`,
  `scale28_preparation_authority.py`, `scale28_preparation_values.py`
  semantics (including `PreparationDeadlinePolicy` validation),
  `read_container_rss_upper_bound` and every resource-reader mechanism, the
  freshness lease, final-release window, architectural maxima, receipt v3
  schema, bounded-IPC frame bounds, dependency set, SQL/schema, public
  CLI/MCP, coordinator, protected runtimes, retained runtimes, and SCALE29.

### Required red tests and validation

- Red-first tests asserting the amended default policy values and refusing
  the old values; policy-validation coverage that 3,400/7,500 constructs and
  that maxima violations still refuse.
- Resource-stage tests proving unchanged reader set, concurrency shape, and
  failure categories under the amended policy.
- Freshness tests proving the lease origin and post-receipt consumption are
  unchanged.
- Two-attempt state-machine tests proving attempt-two eligibility after a
  worst-case bounded attempt-one failure and refusal after both attempts.
- Failure-causality tests preserving TEST-COV4 source sequence, including
  timeout-versus-reader-failure non-relabeling.
- Attempt-cleanup tests proving complete settlement before attempt two.
- Observer-integration tests for the ADR 0045/0046 reimplementation,
  retaining the fourteen-case FIX9 manifest semantics.
- Runtime qualification: runtime-identity binding on the named qualified
  stack; fail-closed refusal elsewhere.

### Candidate provenance receipt

Whenever a FIX12 candidate is not accepted, FIX12 itself must generate a
complete owner-private candidate receipt containing: exact current-main base,
patch SHA-256, mode, complete changed-path manifest, purpose, and creation
phase. No repetition of the FIX9 receipt defect (a candidate without a
complete base-plus-manifest receipt).

### Acceptance evidence

Use separately labeled groups — never one synthetic grand total:

- distinct semantic cases;
- stability repetitions;
- actual configured executions across the five configured owning areas
  (SCALE14, SCALE23, SCALE28 long extraction, SCALE28-FIX1, and the frozen
  mixed campaign), with zero natural `preparation_timeout` terminals expected
  on the qualified stack — any occurrence is a stop-and-disposition finding;
- fresh-runtime rehearsals;
- proportional complete gates.

### Timing-surface branch

- If FIX12 leaves every observer cancellation timing surface unchanged:
  reuse the qualified exact-stack evidence by path-bound digest and run
  bounded confirmation cohorts only.
- If FIX12 changes any cancellation timing surface (expected for the
  ADR 0045/0046 reimplementation): run the full frozen 500-request protocol.

### Stop conditions

Stop without acceptance on: any prohibited-scope touch; any policy value
other than the two amended integers; any natural preparation timeout on the
qualified stack; any freshness, causality, ordering, or cleanup regression;
any incomplete candidate receipt; any remote Git action in a local-only
sandbox. Mixed campaigns, fresh rehearsals, and prior-state preservation
follow the FIX4/FIX9-era protocols unchanged.

## TEST-COV5K Contract

Test-only independent qualification contract for Claude Opus 5. TEST-COV5K
begins only after a pushed executable FIX12 Outcome A.

- Freeze by path-bound digest: source, the 3,400/7,500 policy, resource
  authority, runtime identity, trace contract, failure routing, and the
  qualification protocol.
- Derive expectations from ADRs and public contracts, never from private
  candidate values.
- Independently qualify: the selected preparation policy (including that
  natural `preparation_timeout` terminals do not recur on the qualified
  stack across the qualification cohorts); freshness under the longer
  attempt path (origin at frame receipt, unchanged post-receipt
  consumption); attempt-one/attempt-two settlement ordering; TEST-COV4
  source causality including timeout-versus-reader non-relabeling.
- Execute the fourteen former observer failures; qualify the one-read
  terminal authority; qualify all five configured owning areas; run mixed
  campaigns, fresh public rehearsals, prior-state preservation, and
  proportional complete gates.
- 500-request campaign rule: if FIX12 changed only preparation policy and
  left observer timing unchanged, do not rerun the full 500-request
  cancellation campaign; if any observer timing surface changed, the
  500-request campaign is mandatory.
- TEST-COV5K Outcome A alone may authorize SCALE29.

## SCALE29 Boundary

SCALE29 remains prohibited. The only authorized successor sequence is:
manual publication of this ADR's commit → SCALE28-FIX12 under the contract
above → TEST-COV5K under the contract above → SCALE29 only on TEST-COV5K
Outcome A.

---

## SCALE28-ADR5-FIX1 Amendment — Total Authority And Runtime Qualification

### Amendment Status

Accepted 2026-07-27. This amendment is additive: it corrects and supersedes
exactly the statements listed in "Statements Superseded By This Amendment"
below and leaves every other statement of this ADR in force. The ADR number
is unchanged. Decision Category A is unchanged. The 3,400 millisecond attempt
timeout, the pre-spawn attempt origin, worker-owned resource sampling, all
subordinate deadlines, the 800 millisecond freshness lease, the 600/650
millisecond final release, the 5,000/10,000 millisecond architectural maxima,
and the maximum of two attempts are all retained exactly as selected.

### Corrected Problem

The original acceptance left three implementation-blocking ambiguities:

1. **Total-authority ambiguity.** A value named `total preparation timeout`
   (7,500 milliseconds) was simultaneously described as the selected total
   and defined as an attempt-start eligibility gate that can expire before
   the stated worst-case end-to-end preparation wall clock (8,200
   milliseconds) completes. One name carried two meanings with different
   clock semantics.
2. **Enforcement ambiguity.** The ADR compared the 8,200 millisecond wall
   clock against ADR 0044's 10,000 millisecond total architectural maximum
   while claiming the maxima are "enforced by
   `PreparationDeadlinePolicy.__post_init__`". Current source validates only
   `attempt_timeout_ms ≤ 5,000` and
   `attempt_timeout_ms ≤ total_timeout_ms ≤ 10,000`. No mechanical check
   proves the end-to-end wall clock — attempts plus both failed cleanups plus
   bounded parent work — stays within 10,000 milliseconds.
3. **Runtime-identity category error.** The ADR called one stack
   "timing-qualified" "as frozen by TEST-COV5J path-bound digests".
   Path-bound digests freeze repository files; they do not identify a running
   host, engine daemon, engine backend, API endpoint, image, or PostgreSQL
   server. No complete executable runtime identity of the FIX11 evidence
   stack was durably captured.

### Source-Audit Findings

The audit of `scale28_preparation_authority.py`,
`scale28_preparation_worker.py`, `scale28_preparation_ipc.py`,
`scale28_preparation_values.py`, `scale28_preparation_policy.py`, and
`scale28_hybrid_startup.py` at commit `458d797a` establishes:

- **F1 — the total is a gate, not a wall.** `prepare()` records
  `total_deadline_ns` at entry and consults it only at the top of the
  attempt loop (`if self._clock_ns() >= total_deadline_ns: break`). Once an
  attempt is admitted, nothing consults the total deadline again: the
  attempt runs under A, and a failed attempt's cleanup runs under its own
  fixed bounds. The field named `total_timeout_ms` therefore bounds
  attempt *admission*, not preparation wall time.
- **F2 — no end-to-end validation exists.**
  `PreparationDeadlinePolicy.__post_init__` contains no term for cleanup,
  admission, or parent work; the claim that the architectural total maximum
  is mechanically enforced was false as written.
- **F3 — the failure-branch reads are formally additive to A.** The
  parent's timed waits recompute `_remaining(started)` at each wait start
  and raise `preparation_timeout` when A is exhausted; that part matches the
  "nested, never additive" claim. However,
  `_receive_success_or_failure` captures `timeout_seconds` once and reuses
  the stale value for (i) the failure-notice `receive_one_bounded`, (ii) the
  post-`sender_exit_before_message` re-wait, and (iii) the final payload
  `receive_one_bounded`. Each `receive_one_bounded` call sets a **fresh**
  deadline of `now + timeout_seconds`. In a degenerate schedule (a worker or
  dying runtime that signals readiness, writes a partial frame, and stalls),
  one call is therefore bounded by approximately three times the remaining
  budget, not by A. The committed "nested, never additive" table row is
  contradicted by source for these three callsites. All such schedules end
  in the existing failure path and bounded cleanup; no new terminal category
  exists.
- **F4 — untimed bounded parent work exists.** Per attempt: admission work
  before the pre-spawn origin (state transition, nonce, canonical request,
  four pipes, event, process construction) and in-attempt parent computation
  between timed waits (frame decode, acknowledgement construction and send
  of ≤ 2,048 bytes, receipt decode, terminal-fact validation, evidence
  canonicalization). After the final failure: channel closure, refusal
  transition, and exception projection. None of this is timer-bounded; all
  of it is small bounded work that an honest wall formula must carry as
  explicit allowances, not omit.
- **F5 — failed-cleanup composition is exactly serial.**
  `_settle_failed_process` runs, in order: conditional `SIGTERM` to the
  process group; unconditional `process.join(timeout=0.1)` (a **hardcoded**
  100 millisecond bound, not a policy field); conditional `SIGKILL`;
  unconditional `process.join(timeout=process_settlement_timeout_ms)`
  (300 milliseconds); then `_wait_process_group_settled` for up to another
  `process_settlement_timeout_ms` (300 milliseconds). The three waits are
  strictly serial maxima: C_fail = 100 + 2 × 300 = 700 milliseconds. Signal
  syscalls are negligible. Channel closure, `process.close()`, and
  attempt-two setup are **not** inside this path and carry their own
  allowance terms. Overrun of the final waits raises the cleanup-limitation
  terminal.
- **F6 — the handoff coupling is real and bounded.**
  `HybridPreparationAuthority.startup_handoff_timeout_seconds` returns
  `attempt_timeout_ms / 1_000`; `prepare_parent_startup_authorities`
  (`scale28_hybrid_startup.py`, called by the SCALE14 supervisor) passes it
  to `backend_monitor.startup_summary(timeout_seconds=…)`, which validates
  `0 < timeout_seconds ≤ 5.0` (`_STARTUP_TIMEOUT_SECONDS`). The wait runs
  strictly before `prepare()` is called, so it is outside the preparation
  wall authority. Because A ≤ 5,000 milliseconds architecturally, the
  coupled value can never violate the monitor's ceiling.

### Four-Path Timeline

Parent-monotonic timelines from `prepare()` entry (t = 0), using the symbols
defined in the next section. The total clock origin is `prepare()` entry;
each attempt's clock origin is its own pre-spawn reading.

**Path S1 — attempt one succeeds.** Admission (≤ M_adm): PREPARING
transition, nonce, canonical request, channels, process construction.
Pre-spawn origin t₁ ≤ M_adm. Attempt phase ≤ A (timed waits: observation
wait, receipt wait `min(remaining, 300)`, settlement join
`min(remaining, 300)`), plus at most one trailing EOF-settlement tail
(≤ M_tail) and untimed parent computation (≤ M_work). Evidence acceptance,
freshness-origin fixing, and caller-visible return complete by
t ≤ M_adm + A + M_tail + M_work ≈ 3,700 milliseconds.

**Path F1-S2 — attempt one fails and fully cleans; attempt two succeeds.**
Attempt-one failure classified by first source at
t ≤ M_adm + A + M_tail + M_work; cancellation event set; failed-settlement
path ≤ C_fail; channel closure and failure recording inside the next
admission allowance; attempt-two eligibility check at loop top
(t ≈ 4,400 ≪ W_total, always admitted in bounded schedules); attempt-two
admission ≤ M_adm; new nonce, generation, worker, process group, channels;
attempt-two success as in S1. Caller-visible return by
t ≤ 2·M_adm + 2·(A + M_tail + M_work) + C_fail ≈ 8,100 milliseconds.

**Path F1-F2 — both attempts fail and fully clean.** As F1-S2 through
attempt-two admission; attempt-two failure and complete cleanup by
t ≤ N·(A + M_tail + M_work + C_fail) + N·M_adm; final REFUSED transition and
`PreparationAuthorityError` projection (chained from the last real failure)
inside M_term. Maximum parent wall from `prepare()` entry through the final
terminal cleanup state and caller-visible exception:

```text
W_worst = N·(A + M_tail + M_work + C_fail) + N·M_adm + M_term
        = 2·(3,400 + 100 + 100 + 700) + 2·100 + 100
        = 8,900 ms
```

The second failed attempt's cleanup is explicitly inside this bound.

**Path G — the gate prohibits attempt two.** Loop-top check finds
`now ≥ total deadline`. In bounded schedules this path is unreachable: the
loop-top instant after a worst-case attempt-one failure is approximately
4,400 milliseconds, far below the deadline. It is reachable only under
injected clocks or after a stage-bound violation (which already produced a
cleanup-limitation or equivalent terminal). Behavior: no attempt-two
authority is created; REFUSED transition; the last real failure is causal
(no synthetic category); in the degenerate no-attempt case the error is
raised without a cause. The gate is retained as a defensive subordinate
check, not as the total authority.

### Time-Authority Classification

One symbol, one meaning:

| Symbol | Value | Clock origin | Owner | Terminal condition | Expiry action | Failure category | Truncates a running operation | Permits another attempt | Includes cleanup |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 3,400 ms | Parent monotonic, pre-spawn | Parent attempt (`PreparationWorkerAttempt`) | Observation, receipt, settlement complete; or a timed wait exhausts remaining A | Attempt fails; failed-settlement path runs | `preparation_timeout` | Yes — no timed wait starts after exhaustion | Yes (attempt one only, after full cleanup) | No |
| M_tail | 100 ms (= observation-transfer reserve) | Completion of the last bounded payload read | Parent attempt | Sender EOF observed | IPC settlement failure | Transport terminal | No — a fixed post-read bound | — | No |
| M_work | 100 ms allowance | — (allowance, not a timer) | Parent attempt | Bounded computation completes | — (covered work: decode, ACK send, receipt decode, validation) | — | No | — | No |
| C_fail | 700 ms = 100 (hardcoded SIGTERM join) + 2 × 300 (settlement) | Parent monotonic, at attempt-failure classification | Parent attempt | Process group absent and process joined | Cleanup-limitation terminal | Cleanup limitation (secondary) | No — it is the bounded termination path | Precondition for attempt two | Is the cleanup |
| M_adm | 100 ms allowance per attempt | — (allowance) | Parent authority | Admission work completes (nonce, request, channels, process; prior-attempt closes) | — | — | No | — | No |
| M_term | 100 ms allowance | — (allowance) | Parent authority | REFUSED transition and exception projection complete | — | — | No | No | No |
| G_retry | Subordinate check against the W_total deadline; **no independent value** | `prepare()` entry (shares W_total's origin) | Parent authority | Loop-top comparison | No attempt-two admission; REFUSED | Last real failure is causal | No — checked only between attempts | Decides it | No |
| W_total | **8,900 ms** (`total_timeout_ms`, amended) | Parent monotonic at `prepare()` entry | Parent authority (`HybridPreparationAuthority`) | Caller-visible return or exception after terminal cleanup | Containment is derivation-enforced (below); the stored deadline also drives the subordinate gate | Preparation refused | No — containment by construction, not truncation | — | Yes — both failed cleanups |
| N | 2 | — | Parent authority | — | No third attempt | — | — | — | — |
| A_max | 5,000 ms | — | ADR 0044 | — | Policy construction refuses | — | — | — | — |
| W_max | 10,000 ms | — | ADR 0044 | — | Policy construction refuses (rule below) | — | — | — | — |
| H | = A (derived), currently 3,400 ms → 3.4 s | Parent monotonic at `startup_summary` call, pre-preparation | Parent supervisor phase | Backend ownership summary settles | `BackendMonitorError` (fail-closed startup refusal) | `ambient_client_detected` / `backend_ownership_unknown` / `backend_quiescence_timeout` | Yes — bounds the summary wait | — | No; outside W_total |

### Total-Authority Model Selection

**Model A — one true selected end-to-end total authority. Selected.**
`total_timeout_ms` keeps its name and field but its normative meaning is
corrected: it is the selected end-to-end preparation wall authority W_total,
whose value must contain attempt one, attempt-one failed cleanup, attempt
two, attempt-two failed cleanup, and all bounded parent work from
`prepare()` entry through the caller-visible terminal. Containment is
enforced by derivation (mechanical rule below), not by a runtime truncator:
because every stage carries its own bound, the wall is provably inside the
value whenever the stages respect their bounds, and any stage-bound
violation already has its own terminal (cleanup limitation). The loop-top
check is retained as a subordinate defensive gate reading the same deadline;
it is no longer the definition of the total. The naive candidate 8,200
milliseconds (2·(A + C_fail)) was **rejected** after the source audit: it
omits the settlement tails, the untimed parent work, the admission work, and
the terminal projection (findings F3–F5). The selected value is 8,900
milliseconds.

**Model B — separate retry gate plus separate wall field. Rejected.** It
adds a second independent deadline value for a distinction the state machine
does not need: with N = 2 and per-stage bounds, one derivation-enforced wall
value subsumes the gate. Model B's honest scope (a new policy field, new
validation, new documentation authority, and a gate rename) is strictly
larger than Model A's for no additional guarantee.

**Model C — prove cleanup occurs at most once. Rejected on source.**
`prepare()` invokes the attempt unconditionally on both iterations and every
failed attempt runs `_settle_failed_process`; FIX11 recorded complete
cleanup on all fifty attempt records, including both-fail executions. C_fail
is incurred once **per failed attempt**, up to twice per preparation.

### Selected Values And Formulas

```text
A       = 3,400 ms                       (retained)
M_tail  =   100 ms  (= observation_transfer_reserve_ms)
M_work  =   100 ms  (per-attempt untimed parent-work allowance)
C_fail  =   700 ms  (= 100 hardcoded SIGTERM join + 2 × process_settlement_timeout_ms)
M_adm   =   100 ms  (per-attempt admission allowance)
M_term  =   100 ms  (terminal projection allowance)
N       = 2

W_total = N·(A + M_tail + M_work + C_fail) + N·M_adm + M_term
        = 2·(3,400 + 100 + 100 + 700) + 2·100 + 100
        = 8,900 ms

Checks:
A       = 3,400 ≤ 5,000  = A_max                                  ✓
W_total = 8,900 ≤ 10,000 = W_max                                  ✓
attempt-two admission after worst attempt-one failure:
  loop-top instant ≈ M_adm + A + M_tail + M_work + C_fail
                   = 4,400 < 8,900                                ✓
freshness lease 800 < W_total                                     ✓
subordinate deadlines (150/300/300) < A                           ✓
handoff H = A = 3,400 ms ≤ 5,000 ms monitor ceiling               ✓
```

All allowance terms follow the visible-margin policy of this ADR: fixed
100 millisecond dedicated terms, not epsilons folded into observations, no
dynamic tuning, no environment-variable selection. The 7,500 millisecond
total selected in the original acceptance is superseded by 8,900.

**Joint-feasibility consequence (maxima unchanged).** Under the corrected
derivation with N = 2 and the retained 300 millisecond settlement bound, the
largest attempt timeout for which any valid W_total ≤ 10,000 exists is
3,950 milliseconds. ADR 0044's independent 5,000 millisecond attempt maximum
is **not** amended by this fact; the derivation rule is simply the binding
constraint. A = 3,400 retains 550 milliseconds of headroom to the joint
bound.

### Mechanical Enforcement Rule

Selected rule (the second form offered): **W_total is derived from A,
C_fail, N, and bounded parent overhead, and both the derived value and the
selected field must satisfy the architectural maximum.** The production
validation change frozen for SCALE28-FIX12, in
`PreparationDeadlinePolicy.__post_init__`
(`tools/scale28_preparation_values.py`), is:

```text
new named module constants (values frozen by this amendment):
  SIGTERM_JOIN_MS                     = 100   # must equal the worker's hardcoded join bound
  PARENT_WORK_ALLOWANCE_MS            = 100
  ATTEMPT_ADMISSION_ALLOWANCE_MS      = 100
  TERMINAL_PROJECTION_ALLOWANCE_MS    = 100

derived_end_to_end_ms =
    maximum_attempts × (
        attempt_timeout_ms
        + observation_transfer_reserve_ms
        + PARENT_WORK_ALLOWANCE_MS
        + SIGTERM_JOIN_MS
        + 2 × process_settlement_timeout_ms
        + ATTEMPT_ADMISSION_ALLOWANCE_MS
    )
    + TERMINAL_PROJECTION_ALLOWANCE_MS

validation (added to the existing checks):
    derived_end_to_end_ms ≤ total_timeout_ms ≤ 10_000
```

With the selected values, `derived_end_to_end_ms = 8,900` and
`total_timeout_ms = 8,900` (equality selected; any policy whose field
undercuts its own derived wall is refused, so the name can never lie again).
`scale28_preparation_worker.py` must reference `SIGTERM_JOIN_MS` for its
join bound so the constant cannot drift from the source it models. Until
FIX12 lands, mechanical enforcement of the architectural total **does not
exist**, and no phase may claim it does.

### Bounded-Read Correction (FIX12-Authorized)

To make the "nested, never additive" contract true (finding F3), FIX12 is
authorized to make exactly one semantic correction in
`scale28_preparation_worker.py`: in `_receive_success_or_failure`, replace
the stale `timeout_seconds` reuse with freshly recomputed remaining attempt
time at each of the three callsites (failure-notice read, post-sender-exit
re-wait, final payload read). After the correction every nested wait and
read is bounded by the remaining attempt budget, and the attempt phase is
strictly bounded by A plus one trailing settlement tail (M_tail). No other
worker semantics may change. Required red test: a stalled partial-frame
writer must produce a bounded failure within A + M_tail, not within a
multiple of A.

### Failed-Cleanup Authority (Corrected Statement)

C_fail = 700 milliseconds covers exactly the three strictly serial waits of
`_settle_failed_process` (finding F5). It is incurred once per failed
attempt — up to twice per preparation. It does **not** cover channel
closure, `process.close()`, failure recording, or attempt-two setup; those
carry the M_adm and M_term allowances. The signal sends are conditional and
negligible. If the final waits exhaust without settlement, the
cleanup-limitation terminal is raised; C_fail's bound is then the amount of
bounded waiting that was performed, and no total settlement is claimed.

### Startup-Handoff Disposition

**Retain the coupling and qualify it.** `startup_handoff_timeout_seconds`
remains a derived property equal to A (no independent field). Owner: the
parent supervisor phase (`scale14_actual_refresh_supervisor` →
`prepare_parent_startup_authorities` →
`backend_monitor.startup_summary(timeout_seconds=H)`). Clock origin: the
`startup_summary` call, strictly before `prepare()` entry — H is outside
W_total and consumes none of it. Expiry: fail-closed startup refusal via
`BackendMonitorError` with the monitor's own ownership categories; it
changes only how long the parent will wait for backend ownership quiescence
before refusing startup — it is an upper bound, not a sleep, so success-path
latency is unchanged. It is **not** an observer cancellation timing surface:
it participates in no cancel-safe dispatch, publication, settlement, close,
or terminal readback path. Under this amendment H moves from 1.8 to 3.4
seconds as a **named, qualified** consequence, not an incidental integer
side effect: the monitor's 5.0 second ceiling admits every architecturally
legal A, and TEST-COV5K must measure that backend startup summaries settle
well inside H on the qualification stack. Decoupling would require a
successor decision; none is taken here.

### Runtime Qualification Identity Contract

Path-bound digests freeze repository files; they do not identify a running
stack. The complete runtime qualification identity required before any
timing-qualification claim consists of, at minimum:

```text
operating-system family and release        (e.g. macOS + exact version)
machine architecture
Python version (exact)
container command family                   (closed vocabulary: docker | podman)
container client version
container engine/server implementation
container engine/server version
container context or endpoint transport class
actual backend implementation              (engine-reported; a Docker-compatible
                                            CLI proves nothing about the backend —
                                            Docker Desktop, OrbStack, Docker
                                            Engine, Podman, and others all present
                                            a `docker` executable; the backend must
                                            come from the engine's own reported
                                            server identity, never from the
                                            executable name)
PostgreSQL image reference
PostgreSQL image digest when available
PostgreSQL server version
container-RSS command shape                (the exact stats --no-stream argument
                                            vector)
container-RSS command timeout              (5.0 s)
prepare_resources reader set and concurrency-shape digest
relevant source and policy digests
```

FIX12 implements the capture of this identity within its already-contracted
runtime-identity/qualification-comparison area; TEST-COV5K binds it into the
qualification receipt.

### Qualification Status — Q2

**Status Q2 — evidence-derived selected policy pending qualification.**
Q1 is unavailable: the exact FIX11 runtime identity (engine implementation,
engine version, backend, OS release, image digest) was not durably captured,
and no durable artifact can reconstruct it. Consequences:

- this ADR remains Accepted as a **policy selection**: the FIX11 attempt
  frequencies and stage attribution justify the values independently of
  engine-version identity;
- SCALE28-FIX12 may implement the candidate policy;
- TEST-COV5K must establish the **first** exact-stack timing qualification
  under the identity contract above; and
- **no phase may call any stack timing-qualified before TEST-COV5K
  Outcome A.** The phrases "named qualified stack" and "timing-qualified"
  in the original Platform And Engine Scope section are superseded
  accordingly; that section's fail-closed behavior statements remain in
  force.

### Behavior Outside The Qualified Identity

| Situation | Product execution behavior | SCALE29 readiness behavior | Requalification trigger |
| --- | --- | --- | --- |
| Unsupported containment capability (non-POSIX; runtime outside the closed docker/podman vocabulary) | Preparation containment refused outright (existing fail-closed refusals) | Not claimable | — |
| Supported but unqualified runtime identity | Normal product execution under the unchanged fail-closed bounded authorities; timeouts and reader failures refuse exactly as specified. A merely unqualified local development stack is **not** an arbitrary product failure | Not claimable; no timing-qualification statement may be made | Qualification requires a TEST-COV5K-grade campaign on that exact identity |
| Qualified runtime identity (post TEST-COV5K Outcome A, receipt-bound) | Normal product execution | Claimable per the TEST-COV5K contract | Any identity-field change (engine, backend, OS, architecture, image, mechanism, reader set, policy) voids the receipt |
| Qualified identity with a natural preparation timeout | The single occurrence refuses fail-closed as specified | Readiness claims suspended | Mandatory: a natural `preparation_timeout` on the qualified identity is a stop-and-disposition finding and a requalification trigger |

SCALE qualification remains fail-closed throughout: absence of a receipt
means absence of qualification, never a default pass.

### Timing-Campaign Branch (Normative)

- The full frozen 500-request cancellation protocol is **mandatory**
  whenever SCALE28-FIX12 changes any observer cancellation timing surface
  (cancel_safe request dispatch, request publication, request settlement,
  operation settlement, close, terminal readback, observer transport
  identity). The ADR 0045/0046 observer/terminal reimplementation is
  expected to change such surfaces; "expected" is not the rule — the rule is
  the change test.
- Bounded confirmation cohorts are permitted **only** when path-bound
  comparison proves all observer cancellation timing surfaces
  byte-identical.
- The preparation policy values themselves and the startup-handoff coupling
  are not observer cancellation timing surfaces; changing only them does not
  trigger the full campaign.

### Freshness And Final Release (Reconfirmed)

Reconfirmed against source at `458d797a`: the freshness origin is
`observation_received_parent_ns − observation_transfer_reserve_ms` (parent
frame receipt minus the 100 millisecond reserve); attempt duration consumes
no lease; receipt creation resets no clock; post-receipt settlement,
stable samples, and the final-release window assert against the single
origin. The corrected W_total consumes none of the 650 millisecond
final-release headroom: the final-release window opens after preparation
success, outside A and W_total, exactly as before. Preparation failure
cleanup (C_fail) and the success-only final-release window remain disjoint
authorities. The 800 millisecond lease is retained; 800 < 8,900 holds.

### Failure Causality At Expiry (Corrected First-Source Rules)

- **A expires while a resource read is active** — the parent's
  `preparation_timeout` is first-source; it must not be relabeled
  `resource_reader_unavailable`.
- **A resource read fails before A expires** — the worker's failure notice
  category (for example `resource_unavailable` at `container_rss_read`) is
  first-source; a later timeout must not hide it.
- **The retry gate expires before attempt two** — no synthetic category;
  the last real failure is causal; REFUSED projection.
- **The end-to-end total authority "expires" while cleanup is active** —
  impossible in bounded schedules by derivation; reachable only when a
  stage bound was already violated, which is the cleanup-limitation
  terminal. On cleanup limitation: the exception propagates as the
  attempt's terminal, no post-hoc unbounded reaper exists, the process
  group may outlive `prepare()`, and **total settlement is not claimed** —
  the record states exactly what bounded cleanup was performed.
- **Both attempts fail with different source categories** — each attempt
  retains its own first-source record in the attempt-failure history; the
  preparation-level exception chains from the final attempt's failure; the
  first attempt's category is never rewritten.
- **Final cleanup reaches its bound** — cleanup limitation is a terminal
  secondary fact and never erases the attempt's first source.

TEST-COV4 source sequencing and the FIX11 source-domain prohibition are
retained unchanged. No new terminal category and no new trace variant is
introduced by this amendment.

### Corrected Normative Authority Table

This table supersedes the original Normative Authority Table rows for the
total authority and adds the corrected authorities; retained rows are
restated for closure.

| Authority | Value or formula | Clock origin | Owner | Terminal condition | Expiry category | Interrupts | Success path | Failure path | Relationship |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 3,400 ms | Pre-spawn, parent monotonic | Parent attempt | Frame + receipt + settlement, or wait exhaustion | `preparation_timeout` | Yes (no wait starts after exhaustion) | Evidence accepted | Failed-settlement path | Nested inside W_total |
| C_fail | 700 ms = 100 + 2·300, strictly serial | Attempt-failure classification | Parent attempt | Process group absent | Cleanup limitation | No | — | Runs once per failed attempt | Inside W_total, outside A |
| G_retry | Subordinate loop-top check; no independent value | `prepare()` entry (W_total's origin and deadline) | Parent authority | Loop-top comparison | Last real failure causal | No | — | Blocks attempt two | Reuses W_total's deadline |
| W_total | 8,900 ms = 2·(A + 100 + 100 + 700) + 2·100 + 100 | `prepare()` entry, parent monotonic | Parent authority | Caller-visible return/raise after terminal cleanup | Preparation refused | No (derivation-enforced containment) | Return ≤ ~3,700 | Raise ≤ 8,900, both cleanups inside | Bounded by W_max |
| N | 2 | — | Parent authority | — | No third attempt | — | — | — | Multiplies W_total terms |
| Attempt clock origin | Pre-spawn | — | Parent attempt | — | — | — | — | — | Defines A |
| Total clock origin | `prepare()` entry | — | Parent authority | — | — | — | — | — | Defines W_total and the gate |
| Resource group | Four-way concurrent + serial SQL tail | Worker-local (ordering only) | Worker | All fields or one failure | `resource_unavailable` family | — | Frame sent | Failure notice | Inside A |
| Container RSS | `stats --no-stream`, fixed 5,000 ms command timeout | Worker-local | Worker | Parsed or failed | `resource_unavailable` at `container_rss_read` | — | — | — | Inside A; reader bound is not an attempt authority |
| Observation transfer | 100 ms reserve | Frame availability | Parent | One-shot read settles | IPC refusal | — | — | — | Nested in A; sources M_tail; backdates freshness |
| ACK | 150 ms | Worker ACK-wait start | Worker | ACK received | ACK terminal | — | — | — | Nested in A |
| Receipt | 300 ms | Receipt-wait start | Parent | Receipt received | Receipt terminal | — | — | — | `min(remaining, 300)` in A |
| Process settlement | 300 ms | Join start | Parent | Exit + group settled | Settlement terminal | — | Nested in A | Component of C_fail | Dual use, single value |
| Failed cleanup | See C_fail | — | Parent | — | — | — | — | — | — |
| Freshness | 800 ms | Frame receipt − 100 ms | Parent authority | Release or stale checkpoint | Stale refusal | — | Checked at each checkpoint | Full reacquisition | Independent of A; < W_total |
| Startup handoff H | = A (derived) | `startup_summary` call | Parent supervisor | Ownership summary settles | `BackendMonitorError` | Yes | — | Startup refusal | Outside W_total; ≤ 5.0 s monitor ceiling |
| Final release | 600 ms selected / 650 ms max | `open_final_readiness` | Parent authority | Child released | Final-window refusal | — | — | — | Outside A and W_total |
| A_max | 5,000 ms | — | ADR 0044 | — | Construction refused | — | — | — | Caps A |
| W_max | 10,000 ms | — | ADR 0044 | — | Construction refused via derived rule (post-FIX12) | — | — | — | Caps W_total and the derived wall |

### Corrected State Machine (Executable Behavior)

1. **Attempt-one success**: admission → pre-spawn origin → bounded attempt
   phase → parent ordering validation → evidence acceptance → freshness
   origin → caller return. One global parent sequence spans the whole
   preparation; the attempt owns its worker-local sequence.
2. **Attempt-one failure and cleanup**: first-source classification →
   cancellation event → C_fail settlement path → channel closure → exactly
   one recorded source-sequenced failure. Cleanup must reach its terminal
   before any attempt-two work.
3. **Attempt-two admission**: only after complete attempt-one cleanup, only
   if attempts remain, only if the subordinate gate passes. New nonce,
   generation, worker, process group, channels, and connection; no
   inherited descriptors or sampler; the worker-local sequence may reset;
   the global parent sequence never resets.
4. **Attempt-two success**: as attempt-one success.
5. **Attempt-two failure and cleanup**: as attempt-one failure; the second
   C_fail is inside W_total.
6. **Retry-gate refusal**: no attempt-two authority created; REFUSED; last
   real failure causal.
7. **End-to-end wall expiry**: cannot occur in bounded schedules
   (derivation-enforced); any apparent expiry implies a stage-bound
   violation already carrying its own terminal.
8. **Cleanup limitation**: terminal secondary fact; first source retained;
   no unbounded reaper; total settlement not claimed.
9. **Final REFUSED projection**: REFUSED transition, exception chained from
   the last real failure, inside M_term. No third attempt exists.

### Statements Superseded By This Amendment

Within this ADR only; historical records elsewhere stand unedited:

1. Every statement selecting or citing **7,500 milliseconds** as the total
   preparation timeout is superseded by the selected end-to-end
   **8,900 milliseconds** (`P = 2·A + C_fail = 7,500` in the Selected
   Numeric Policy; the constraint-check lines using P = 7,500; the
   Normative Authority Table total row; state-machine item 5's framing of P
   as gate-only).
2. The description of the total as *only* an eligibility gate is superseded
   by the Model A wall authority with a subordinate gate.
3. The claim that the architectural maxima are "enforced by
   `PreparationDeadlinePolicy.__post_init__`" is superseded by the
   Mechanical Enforcement Rule: end-to-end enforcement does not exist until
   FIX12 lands the frozen validation change.
4. The Compatibility statement "No validation change is required or
   authorized" is superseded: the validation change and the bounded-read
   correction are authorized exactly as frozen above.
5. The Attempt Clock Contents rows claiming the receipt and settlement
   waits are "nested, never additive" are corrected per finding F3: true
   for the timed wait starts, false for the three stale-timeout nested
   reads until the FIX12 correction lands.
6. The Platform And Engine Scope language "timing-qualified" / "one
   explicitly named qualified stack" is superseded by Qualification Status
   Q2; the section's fail-closed behavior statements remain.
7. The FIX12 contract's authorized-scope item "`total_timeout_ms=7_500`"
   is superseded by `total_timeout_ms=8_900`, and its prohibited-scope
   entries for `scale28_preparation_values.py` validation and
   `scale28_preparation_worker.py` are narrowed exactly as stated in the
   corrected FIX12 contract below.

### Corrected SCALE28-FIX12 Contract (Delta)

The FIX12 contract above remains in force with these corrections. FIX12
begins only from the manually published ADR5-FIX1 commit, as a fresh
test-first semantic implementation on current `main`; the ambiguous
historical patch remains prohibited as authority.

**Authorized production scope (complete, corrected):**

1. `tools/scale28_preparation_policy.py`: `attempt_timeout_ms=3_400`,
   `total_timeout_ms=8_900`. No other field.
2. `tools/scale28_preparation_values.py`: exactly the Mechanical
   Enforcement Rule — the four named constants and the
   `derived_end_to_end_ms ≤ total_timeout_ms ≤ 10_000` validation. No other
   semantic change to the module.
3. `tools/scale28_preparation_worker.py`: exactly the Bounded-Read
   Correction (three callsites; plus referencing `SIGTERM_JOIN_MS` for the
   hardcoded join bound). No other semantic change to the module.
4. The ADR 0045/0046 observer/terminal reimplementation areas exactly as
   already contracted (including runtime-identity capture per the identity
   contract and qualification comparison).

**Additional red-first requirements** (before production mutation, each must
fail deterministically against the old tree):

- old 1,800 millisecond attempt policy refused;
- incorrect selected-total value **or meaning** (a policy whose
  `total_timeout_ms` undercuts its derived end-to-end wall must refuse);
- second failed-attempt cleanup falling outside the claimed total
  authority;
- attempt two before attempt-one cleanup completion; any third attempt;
- incorrect timeout/resource causality (both relabeling directions);
- stalled partial-frame writer exceeding A + M_tail (bounded-read
  correction);
- missing exact runtime identity fields; any qualified-stack claim without
  a qualification receipt;
- startup-handoff coupling drift (H ≠ A, or H exceeding the monitor
  ceiling).

**Preparation qualification measurements** (actual configured attempts under
quiet, bounded CPU contention, bounded filesystem contention, bounded
connection churn, complete-gate prelude, and immediate second-attempt
reacquisition), measured separately, no valid observation removed:

- successful attempt wall;
- first failed attempt plus cleanup;
- first failure plus second success;
- two failed attempts plus both cleanups;
- end-to-end `prepare()` wall.

Any natural preparation timeout on the intended qualification stack is a
stop-and-disposition finding. The candidate-receipt requirement is
unchanged: any unaccepted FIX12 candidate requires a complete owner-private
receipt (exact base, patch SHA-256, mode, complete changed-path manifest,
purpose, creation phase).

### Corrected TEST-COV5K Contract (Delta)

TEST-COV5K remains a test-only independent qualification phase for Claude
Opus 5. Corrected entry conditions — TEST-COV5K begins only after **all**
of: FIX12 Outcome A; one executable FIX12 commit exists; the operator has
confirmed that commit as the shared authoritative tip; the FIX12 report
packet exists; and the local worktree is clean.

TEST-COV5K must independently qualify: selected A; the subordinate gate
behavior (no independent G_retry value); selected W_total = 8,900 including
**both** failed-cleanup paths; the mechanical architectural-maximum
enforcement (derived rule refuses violating policies); the startup-handoff
coupling (H = A, settles inside H on the qualification stack); freshness;
attempt settlement and reacquisition ordering; failure causality (both
non-relabeling directions); the complete runtime identity; the runtime
qualification receipt; the fourteen former observer failures; the one-read
terminal authority; the five actual owning areas; mixed campaigns; fresh
rehearsals; prior-state preservation; and proportional complete gates.
Independent tests derive expectations from ADRs and public contracts, never
from FIX12 private values.

**Runtime qualification receipt** — one exact-stack receipt containing or
digest-binding: all runtime identity fields of the contract above; policy
values; source and protocol identities; condition set; attempt counts;
valid-observation count; timeout/failure counts; cleanup results; and the
qualification outcome. Only this receipt, bound to TEST-COV5K Outcome A,
permits calling the stack timing-qualified.

**Cancellation timing** — the full frozen 500-request campaign is required
whenever FIX12 changed any observer cancellation timing source; otherwise
source-identity proof plus bounded confirmation cohorts.

TEST-COV5K Outcome A alone may authorize SCALE29; SCALE29 remains
prohibited until then.

---

## SCALE28-FIX12 Additive Finding — Engine Identity Is Not Yet Discriminating

SCALE28-FIX12 (status 00684) closed as a bounded stop without implementing
any part of this decision: the executing environment could collect no test
and reach no container plane, so the phase contract's opening-gate rule
stopped production mutation. No value in this ADR moved, and the mechanical
enforcement rule above remains frozen-but-unimplemented. The architectural
total maximum is therefore still **not** mechanically enforced in production.

The phase did isolate one defect in the runtime identity contract stated
above, recorded as finding FIX12-F1 and left unresolved for operator
decision.

This ADR requires the engine-reported backend and forbids inferring it from
the `docker` executable name. That requirement is necessary but **not
sufficient**. On the host examined by SCALE28-FIX12, the container engine
reports its own server platform name as `Docker Engine - Community` while
reporting its operating system as `OrbStack`; the engine is OrbStack, not
Docker Engine. An identity that binds the container engine implementation to
the engine's self-reported platform name would therefore compare equal
between an OrbStack host and a genuine Docker Engine host, producing a false
`timing_qualification_match` across two materially different engines — the
exact outcome the qualification receipt exists to prevent.

Consequence for the successor: before any exact-stack qualification receipt
is bound, the identity contract needs a field set that actually discriminates
the engine implementation, and the choice of discriminating fields must be
justified rather than assumed. Until that is settled, a receipt produced
under the contract as currently written cannot be relied on to distinguish
qualification stacks. No qualification claim is made by this ADR or by
SCALE28-FIX12.

## Additive Note — SCALE28-FIX12-DIAG1 Measurement Evidence (2026-07-28)

Recorded additively. This note does not reopen or amend the accepted
3,400 / 8,900 preparation policy or the Q2 qualification decision, and does not
authorize production work.

### Disposition for finding FIX12-F1

FIX12-F1 held that the engine's self-reported platform name cannot discriminate
the container engine implementation, so a qualification receipt bound to it
could match falsely across two materially different engines.

The premise is confirmed on the examined host: the server platform name and the
server operating-system string are not equal, and they disagree in shape — a
multi-token vendor string against a single token naming a different
implementation.

The finding is now dispositionable. Read through the Docker Engine API, the
engine exposes a component-level field set the CLI summary does not surface:
four server components, each with a name, a version, and a details digest, with
all four digests distinct and more than one distinct component version. That
set, combined with the operating-system string, discriminates the engine
implementation where the platform name alone does not.

Recommendation carried to `SCALE28-ADR5-FIX2`: bind engine identity to the
component field set plus the operating-system string, never to the platform
name alone. No qualification claim is made and no receipt is bound here.

### Resource-sampling mechanism evidence

Measured on one exact disposable container per condition, 90 CLI and 90 Engine
API observations, no observation removed:

- the existing `docker stats --no-stream` reader has a median of roughly
  2,000 ms per sample and is bimodal, clustering near 1,040 ms and near
  2,000 ms; it spawns one external process per sample;
- an in-process `stats(..., stream=False, one_shot=True)` call has a median of
  roughly 3 ms and spawns none;
- under cgroup v2 the CLI's displayed memory usage is reproduced byte for byte
  by `memory_stats.usage - memory_stats.stats.inactive_file`. Raw
  `memory_stats.usage` is **not** that quantity and must not be substituted for
  it.

One scope correction relevant to any successor decision: the container-RSS
reader lives in `tools/scale12_resource_sampling.py`. `tools/` is not packaged
— `[tool.setuptools.packages.find] where = ["src/main/python"]` — and no module
under `src/main/python` imports it. `docker stats` is therefore not on any
production runtime path, and replacing that reader would not add a production
runtime dependency.

## Additive Note — SCALE28-FIX12-DIAG1-FIX1

Recorded additively on 2026-07-28. This note does not amend the decision. The
3,400 / 8,900 preparation policy and the Q2 qualification stand as accepted.

`SCALE28-FIX12-DIAG1-FIX1` established, from callgraph and executed evidence
rather than packaging location, that the preparation resource sampler is on the
actual operational SCALE preparation path. One measured preparation attempt
spawns two external host processes: `ps`, through `read_process_rss_bytes`, and
the container runtime, through `read_container_rss_upper_bound`. Preparation
fails closed when either reader is unavailable.

Two consequences for any successor that revisits the resource-sampling
mechanism:

- The container-RSS reader and the process-RSS reader are independent failure
  domains. In the phase's execution boundary the container reader worked and
  the process reader did not, because `/bin/ps` could not be executed. A
  decision that replaces one must not assume it addresses the other.
- `read_process_rss_bytes` returns `None` only on a nonzero return code. When
  `/bin/ps` cannot be executed at all it raises `PermissionError`, so
  preparation surfaces a raw exception instead of the intended
  `PreparationResourceError("resource_unavailable", "client_rss_read")`. Its
  sibling `read_container_rss_upper_bound` routes through
  `_run_bounded_text_command` and degrades to `None` correctly. This asymmetry
  is recorded, not repaired: operational SCALE source was outside that phase's
  authorized scope.

---

## SCALE28-ADR5-FIX2 Amendment — In-Process Runtime Data Plane

### Amendment Status

Accepted 2026-07-30 — Outcome A. This amendment is additive: it owns exactly
the runtime data-plane mechanism and its explicit boundary with
administrative and lifecycle CLI use, and it leaves every other statement of
this ADR in force. It does not reopen hybrid worker/parent ownership, the
freshness lease, the final-release window, observer operation classes,
cancellation request/settlement ownership, receipt-v3 framing, bounded IPC,
the 5,000/10,000 millisecond architectural maxima, or the selected
3,400 millisecond attempt and 8,900 millisecond end-to-end preparation wall
values. Qualification Status Q2 stands. The amendment base is the accepted
`SCALE28-FIX12-DIAG1-REVIEW1` commit
`d6e90f185732243c6e85bbe46623b6aded690c8a`.

### Evidence

The following accepted records are frozen as this amendment's evidence and
are not rerun or reinterpreted here:

- **Status 00685 (`SCALE28-FIX12-DIAG1`)** — the engine-identity component
  finding (the engine's self-reported platform name does not discriminate
  the engine implementation; the component field set plus the
  operating-system string does), and the frozen exact-stack mechanism
  campaign: 90 `docker stats --no-stream` observations at roughly two
  seconds and one host subprocess each, against 90 Docker Engine API
  one-shot observations at single-digit milliseconds and zero host
  subprocesses, with the cgroup-v2 semantic mapping
  `CLI memory usage = memory_stats.usage − memory_stats.stats.inactive_file`
  reproduced byte for byte. Raw `memory_stats.usage` alone is not that
  quantity. The dataset is retained by digest.
- **Status 00686 (`SCALE28-FIX12-DIAG1-FIX1`)** — callgraph and executed
  evidence that the resource sampler is on the actual operational SCALE
  preparation path: one measured preparation attempt spawns two external
  host processes (`/bin/ps` via `read_process_rss_bytes` and the container
  runtime via `read_container_rss_upper_bound`); the two readers are
  independent failure domains; and the recorded error asymmetry
  (`PermissionError` raised raw where
  `PreparationResourceError("resource_unavailable", "client_rss_read")` is
  intended).
- **Status 00687 (`SCALE28-FIX12-DIAG1-FIX2`)** — the exact nine-node
  former-ps inventory and the hardened scratch lifecycle under which the
  review evidence was produced.
- **Status 00690 (`SCALE28-FIX12-DIAG1-REVIEW1`)** — the accepted
  capable-environment complete gate: 5,585 passed, 10 skipped, 1 strict
  xfail, 92.7% line coverage, 85.1% branch coverage, container smoke passed.
  All nine former ps nodes passed; that proves the prior Claude failures
  were sandbox `EPERM` environment attribution, not architectural approval
  of `/bin/ps`. The process-boundary semantics are accepted: one host
  process creation is one observation, `argv[0]` is the host executable,
  and nested command intent is a separate evidence axis. The hidden-psql
  strict xfail remains exactly once in the gate.
- **Hidden-fallback source evidence** — in
  `src/main/python/repomap_kg/ops/readback.py`, `execute_ops_json_readback`
  with the Psycopg driver selected and `mode="host_then_container"` reacts
  to a class-08 (or operational) connection failure by silently re-executing
  the same read as `docker exec -i <container> psql`: a host `docker`
  process with nested `psql` command intent that the caller never selected.

Interpretation boundaries retained from the accepted records: the evidence
does not prohibit every explicit `psql` operation, and the 90/90 dataset is
mechanism-selection evidence, never post-change qualification evidence.

### Problem

Three accepted defects sit on the active runtime data plane:

1. A caller-selected Psycopg runtime read can silently change transport to a
   nested container `psql` command on connection failure, hiding both the
   failure and the transport from the caller's evidence.
2. One preparation resource read — repeated on the observer/preparation
   critical path — spawns `/bin/ps` for process RSS, with a raw-exception
   error asymmetry, and depends on host sandbox permission to execute an
   external binary.
3. The same read spawns the container runtime CLI for container RSS, whose
   engine-statistics blocking dominates the attempt policy (the accepted
   bimodal ~1.0/2.0 second mechanism) where an Engine API one-shot read of
   the same semantic quantity costs single-digit milliseconds and zero host
   processes.

The decision must select the implementation policy for runtime data-plane
operations, the exact boundary where external CLI processes remain
permissible, and the dependency, timeout, failure, identity, qualification,
and migration contracts — without retuning any accepted timing value.

### Option Analysis

Options scored against: semantic fidelity, boundedness, failure isolation,
process count, sandbox independence, cross-platform support, dependency and
packaging scope, testability, operational complexity, migration risk, and
qualification burden.

| Criterion | A — in-process data plane, explicit CLI plane | B — partial no-CLI (keep `/bin/ps`) | C — wrapped subprocesses | D — handwritten native/protocol | E — retain and enlarge budgets |
| --- | --- | --- | --- | --- | --- |
| Semantic fidelity | Strong: same quantities (current RSS bytes; CLI-equivalent container memory via accepted cgroup-v2 mapping) | Strong for container, unchanged for process | Unchanged | At risk: hand-rolled semantics must be re-proved | Unchanged but hidden fallback persists |
| Boundedness | Strong: library timeouts under existing deadlines; no watcher threads | Mixed: `ps` keeps its subprocess bound | Improved but still subprocess-bound | Unproven | Weak: budgets grow to cover slowness |
| Failure isolation | Strong: structured exceptions per authority; fail-closed mapping | Mixed: `ps` asymmetry needs separate repair | Improved wrappers, same domains | New failure modes | Unchanged, incl. silent transport change |
| Process count | 0 per runtime read | 1 (`ps`) per preparation read | ≥ 2 per preparation read | 0 | ≥ 2, plus hidden psql |
| Sandbox independence | Strong: no exec permission needed on the data plane | Weak: `/bin/ps` exec permission still required | Weak | Strong | Weak |
| Cross-platform | psutil/docker SDK cover the POSIX scope; fail closed elsewhere | `ps` output varies by platform | As today | Per-platform code required | As today |
| Dependency/packaging scope | Two established deps in an operational tooling group; shipped package unchanged | One dep | None | None new, but native build or helper toolchain | None |
| Testability | Strong: exceptions and fakes at library seams | Mixed | Mixed: still argv/stdout parsing | Weak | Unchanged |
| Operational complexity | Low: fewer moving host processes | Low-medium | Medium: more wrapper code | High | Low now, higher forever |
| Migration risk | Bounded: three readers and one fallback branch, contracts preserved | Lower but leaves defect 2 | Lowest, fixes nothing structural | Highest | None, defects retained |
| Qualification burden | One TEST-COV5K campaign on the new stack (already mandatory) | Same campaign, less benefit | Requalification with no mechanism gain | Large | Requalifies known-bad mechanism |

- **Option B** is rejected: it leaves the process-RSS subprocess, its sandbox
  dependence, and its error asymmetry on the critical path while paying the
  same qualification cost as Option A.
- **Option C** is rejected: stricter wrappers cannot remove the engine-CLI
  two-second sampling mode, the per-observation host process, or the exec
  permission requirement; it spends migration effort without changing any
  defect's mechanism.
- **Option D** is rejected: manual Mach/procfs code, hand-rolled Unix-socket
  HTTP, or a C/Rust helper reimplements what psutil and the Docker SDK
  already provide with mature failure semantics, and adds an unbounded
  correctness and maintenance surface for zero semantic gain.
- **Option E** is rejected: the accepted 3,400/8,900 policy already
  accommodates the slow mechanism; enlarging budgets to preserve a hidden
  transport change and avoidable subprocesses inverts the evidence.

### Decision

Select **Option A**, closed:

```text
active runtime data plane:
in-process/library APIs only — Psycopg for PostgreSQL reads, psutil for
process RSS, the Docker Engine API through the maintained Python Docker SDK
for container RSS

explicit administrative/lifecycle plane:
bounded fixed-argv CLI remains permissible under the conditions below
```

A Psycopg-selected runtime read never becomes `psql`. No runtime data-plane
operation may fall back to any external CLI automatically. Every remaining
CLI owner is explicit, bounded, and outside the automatic runtime fallback
path. "No-CLI runtime data plane" does not mean "no CLI anywhere in
RepoMap".

### Runtime Data Plane

An operation is on the runtime data plane when it is executed by product or
operational-preparation code as part of serving or preparing the active
runtime — especially when repeated on observer or preparation critical
paths. Runtime data-plane operations must use in-process/library APIs only:

| Operation | Classification | Selected authority |
| --- | --- | --- |
| MCP canonical readback (`server/ops.py`) | Runtime data plane | Psycopg (or the explicitly selected psql compatibility path below) |
| Configured graph status/readback (`ops/config.py`, `ops/graph_files.py`) | Runtime data plane | Psycopg, same rule |
| Refresh hot-path readback (`ops/refresh.py` status/summary readbacks) | Runtime data plane | Psycopg, same rule |
| Observer database operations | Runtime data plane | Psycopg (existing contract) |
| Preparation process RSS | Runtime data plane | psutil (in-process) |
| Preparation container RSS | Runtime data plane | Docker Engine API one-shot stats |
| Backup | Administrative/lifecycle | Bounded fixed-argv CLI permitted |
| Restore | Administrative/lifecycle | Bounded fixed-argv CLI permitted |
| Schema migration | Administrative/lifecycle | Bounded fixed-argv CLI permitted (Liquibase/psql tooling) |
| Database initialization/removal | Administrative/lifecycle | Bounded fixed-argv CLI permitted |
| Bulk or streaming load (`_load_file_observations_with_ops_psql` and the refresh psql-native chain) | Administrative/lifecycle | Explicit psql-native path retained |
| Container build/start/stop/remove (`runtime/local.py`, smoke harness) | Administrative/lifecycle | Bounded fixed-argv CLI permitted |
| Test-harness lifecycle (`tools/run_tests.py`, disposable Postgres) | Administrative/lifecycle | Bounded fixed-argv CLI permitted |
| Operator diagnostics (scale12/scale18 campaign tools, explicit CLI stats/inspect readers, `read_container_growth_bytes`) | Administrative/diagnostic | Bounded fixed-argv CLI permitted, explicitly invoked |

### Administrative And Lifecycle Plane

External CLI processes remain permissible exactly when all of the following
hold:

1. the caller or operator selects the operation explicitly (a named CLI
   command, configuration value, environment variable, or campaign
   invocation — never a silent branch of a runtime read);
2. the operation is classified administrative, lifecycle, migration,
   packaging, bulk/streaming, diagnostic, or a separately named
   compatibility path;
3. the child uses a fixed argument vector with `shell=False` and a bounded
   timeout;
4. the host executable and any nested command intent are visible in
   evidence on the accepted axes (`argv[0]` host executable; nested intent
   separate);
5. existing privacy, redaction, and causality rules apply; and
6. the operation is not reachable as an automatic fallback from any runtime
   data-plane operation.

### PostgreSQL Authority

Required invariant, normative:

```text
driver = psycopg
→ Psycopg only
→ transport/connection failure is a structured fail-closed result
→ no implicit psql or docker-exec fallback
```

Driver selection is unchanged: `REPOMAP_STORAGE_READBACK_DRIVER` (closed
vocabulary `psycopg` | `psql`, default `psycopg`) and the PG-connector
consistency check in `storage/readback_driver.py`.

Name dispositions:

- **`psycopg`** — retained; names the in-process runtime read authority.
- **`psql`** — retained; names the explicitly selected compatibility/
  administrative driver. Explicit selection means
  `REPOMAP_STORAGE_READBACK_DRIVER=psql` or a non-`None` `psql_command`
  (`REPOMAP_PSQL_COMMAND`). Under explicit selection the host and nested
  command intent are visible in evidence, fixed argv and bounded timeouts
  apply, and the operation is classified as a named compatibility path.
- **`host_only`** — retained; meaning unchanged (never any container
  fallback).
- **`host_then_container`** — retained **for the psql driver only**, where
  the name states exactly the topology chain it performs (host psql, then
  RepoMap-owned container psql on connection-shaped failure). After
  `SCALE28-FIX12-R1`, the Psycopg path never consults the mode: the mode
  parameter of `execute_ops_json_readback` is re-scoped to the explicit
  psql path, and no configuration or parameter name remains whose behavior
  silently changes transport.

Backward compatibility and deprecation: both environment variables retain
their names and meanings; no configuration value changes meaning silently.
The one behavioral change is the correction itself and is named here as
such: a Psycopg-selected read that today silently falls back now returns
the structured fail-closed error
(`psycopg connection failed for <label>` plus the existing topology hint
text guiding the operator to start the local runtime or enable direct
exposure). The hint text is retained as guidance; the fallback execution is
removed. The psql-native refresh chain
(`run_storage_readback_with_ops_psql`, `_ops_psql_executions`) is retained
unchanged as an explicitly psql-selected administrative path; its
host-to-container topology chain stays within the one explicitly selected
psql driver and is visible on both evidence axes.

### Process RSS Authority

Selected authority: **psutil**, evaluated under
`docs/contrib/dependency-standards.md` (mature, widely maintained,
BSD-licensed, cross-platform, no transitive runtime dependencies) and
preferred over every rejected substitute below.

Contract for `read_process_rss_bytes(process_id)`:

- **Exact API and field**: `psutil.Process(process_id).memory_info().rss` —
  current resident set size, in **bytes**, of exactly the requested PID.
- **PID ownership and identity**: input validation is retained (reject
  `bool`, non-`int`, and values below 1 with `ResourceSamplingError`).
  Callers pass only explicitly selected owned PIDs (for preparation, the
  specification's `client_pid`). `psutil.Process` construction verifies
  existence; the PID-reuse race window is unchanged from the `/bin/ps`
  mechanism and remains bounded by caller ownership.
- **Failure disposition**: `psutil.NoSuchProcess`, `psutil.AccessDenied`,
  and `psutil.ZombieProcess` all map to `None`, which the preparation
  caller converts to
  `PreparationResourceError("resource_unavailable", "client_rss_read")`.
  This also repairs the recorded FIX1 asymmetry: no raw exception escapes
  where `None` is the contract.
- **Current versus peak**: current RSS only. `resource.getrusage` maximum
  RSS is peak, current-process-only, and platform-unit-ambiguous; it is
  prohibited as a substitute.
- **Units, overflow, negatives**: the returned value must be a
  non-negative `int` in bytes; negative or non-integral values are refused
  to `None`, never clamped to zero.
- **Elapsed-time observation**: the preparation caller captures
  parent-of-read monotonic before/after timestamps around the read as
  worker-local ordering evidence only — never a freshness input.
- **Deadline ownership**: the read is a direct in-process call owned by the
  preparation worker's existing attempt deadline. No watcher thread is
  added merely to time a local call, and no external child process exists
  in the selected preparation resource read.
- **Platforms**: psutil supports the POSIX scope this ADR already limits
  containment to (macOS qualification stack; Linux containers). On an
  unsupported platform or missing capability the behavior is fail-closed
  refusal (dependency import failure or mapped `None`), never a zero RSS.

`read_process_tree_rss_bytes` (campaign diagnostics) is migrated in the
same slice via `psutil.Process(root).children(recursive=True)` plus
per-process `memory_info().rss`, removing the host-wide
`/bin/ps -axo` enumeration so no accepted test node requires `ps`
execution after R1. `process_tree_rss_bytes` row summation stays available
for its existing tests.

### Container RSS Authority

Selected authority: the **Docker Engine API through the maintained Python
Docker SDK (`docker` package), low-level client interface**, evaluated
under `docs/contrib/dependency-standards.md` (Docker-maintained, Apache-2.0,
stable low-level API, requests-based transport already compatible with the
local containerized test environments).

Contract for `read_container_rss_upper_bound(runtime, container_name)`:

- **Call shape**: one `docker.APIClient` one-shot statistics call for the
  exact configured container name —
  `APIClient.stats(container_name, stream=False, one_shot=True)` — with
  streaming disabled. No generic inventory: no container list, no
  enumeration of unrelated objects.
- **Client and timeout**: the client is constructed inside the reader
  invocation with an explicit HTTP timeout of **2.0 seconds** (below the
  3,400 millisecond owning attempt budget) and `version="auto"` (one
  bounded version negotiation whose result feeds the identity receipt);
  the endpoint resolves from the standard Docker environment (the default
  Unix socket or `DOCKER_HOST`), and the transport class is recorded in
  the receipt.
- **Client lifetime and thread ownership**: the client is created and
  closed (`finally`) within the single reader call, executed on the
  preparation group's existing worker thread. No module-global client, no
  cross-attempt reuse (the no-inheritance invariant), no new thread or
  process.
- **cgroup-v2 field mapping**: the returned value is
  `memory_stats.usage − memory_stats.stats.inactive_file`, the accepted
  CLI-equivalent quantity. Raw `memory_stats.usage` is not CLI-equivalent
  and must not be substituted.
- **Missing/invalid fields**: absence of `memory_stats.usage` or
  `memory_stats.stats.inactive_file`, a non-integral value, or a negative
  subtraction result refuses to `None` — never zero, never a raw-usage
  substitute. The observed stats field shape is classified and recorded in
  the identity receipt; an engine or cgroup configuration outside the
  qualified field shape (for example cgroup v1) fails closed.
- **Connection and daemon errors**: SDK/transport errors (daemon
  unreachable, API error, not-found, HTTP timeout) map to `None`, which the
  preparation caller converts to
  `PreparationResourceError("resource_unavailable", "container_rss_read")`.
- **CLI disposition**: `docker stats` is prohibited as an automatic runtime
  fallback. An explicit diagnostic CLI reading (campaign tooling,
  TEST-COV5K equivalence checks) remains permissible outside the runtime
  acceptance path under the administrative-plane conditions.

### Dependency Boundary

Dependency ownership is selected per category:

| Category | Disposition |
| --- | --- |
| Installed `repomap_kg` package dependencies | **Unchanged** (`psycopg[binary]`, `typing-extensions`). psutil and the Docker SDK must not be forced into the shipped package merely because `tools/` imports them. |
| Operational SCALE tooling dependencies | **New optional-dependencies group `scale-tools`** in `pyproject.toml` (`[project.optional-dependencies]`), containing exactly `psutil` and `docker`, exact-pinned by R1 following the repository's shipped-dependency pin convention. This mirrors the existing `test` group precedent: an extras group serving unpackaged repository code. |
| Test-only dependencies | Unchanged (`test` group). Tests exercise the new authorities through fakes at library seams; the real packages are present in developer/CI environments via `pip install -e .[test,scale-tools]`. |
| Container/runtime image dependencies | None added: the Engine API is reached over the engine's existing endpoint; the PostgreSQL image is untouched. |
| Developer environment dependencies | Documented install becomes `.[test,scale-tools]` where SCALE operational tooling is exercised. |

Fail-fast capability behavior: `tools/scale12_resource_sampling.py` imports
psutil and the Docker SDK at module import. A missing operational
dependency therefore fails at import time — before any preparation attempt
— as an environment-capability defect. Dependency absence is never mapped
to `None`, never to zero RSS, and never to `resource_unavailable`.

### Timeout And Failure Contract

The accepted 3,400 millisecond attempt policy, 8,900 millisecond selected
end-to-end preparation wall, and 5,000/10,000 millisecond architectural
maxima are retained unchanged. No global retune is invented; per-authority
budgets are:

- **Psycopg**: the existing connection/query/cancellation contract remains
  authoritative (preparation bootstrap: 2 second connect timeout, 4,000
  millisecond statement timeout; ops readback and observer contracts
  unchanged).
- **Docker Engine API**: the explicit 2.0 second client timeout above,
  strictly below the owning attempt budget; expiry is a reader-owned
  fail-closed `None`, not an attempt authority.
- **Process RSS**: a direct in-process read owned by the preparation
  worker's existing deadline, with before/after elapsed evidence; no
  watcher thread; fail-closed exception mapping as specified.
- **No external child process** exists in the selected preparation resource
  read.

Structured failure categories preserve the current resource-reader
contract: reader-level failures surface as `None` and become
`resource_unavailable` at the exact reader boundary (`client_rss_read`,
`container_rss_read`); connection bootstrap failures remain
`worker_connection_bootstrap_failed`; attempt and total authorities,
first-source causality, and both non-relabeling prohibitions are retained
exactly. Dependency absence, permission denial, process disappearance,
engine transport failure, and unsupported field shape are each structured
failures — never zero RSS.

### Process-Count Contract

Expected post-R1 counts, on the accepted evidence axes (host executable =
`argv[0]`; nested command intent separate):

```text
one Psycopg-selected runtime read:
  host external process count = 0
  nested psql intent count    = 0

one process-RSS read:            host external process count = 0
one container-RSS read:          host external process count = 0
one preparation resource-read attempt (four-way group + serial SQL):
                                 host external process count = 0
```

No claim is made that an entire refresh, campaign, or gate run has zero
external processes: the explicit administrative/lifecycle plane
legitimately creates bounded fixed-argv children (container lifecycle,
psql-native load, test harness, diagnostics), each visible on both axes.

### Runtime Identity

The qualification receipt binds, at minimum:

```text
Python implementation and version
RepoMap source/commit identity
Psycopg package version
loaded libpq runtime version
PostgreSQL server version
process-telemetry package/version        (psutil)
host operating system and kernel identity
Docker client package/version            (docker SDK)
Docker API version                       (negotiated)
engine server version
engine component field set               (each component name, version,
                                          details digest)
engine-reported operating-system string
engine OSType
engine architecture when relevant
cgroup version
container image digest
container stats field-shape classification
transport class                          (Unix socket | TCP)
command/operation shape                  (one-shot stats; no subprocess)
```

Engine identity binds to the component field set plus `OSType` and the
engine-reported operating-system string — never to the single marketing
platform name, which the frozen DIAG1 finding proved non-discriminating
(a `Docker Engine - Community` platform string on an OrbStack engine).

### Qualification

- **Status Q2 is retained.** This phase qualifies nothing: no new
  dependency stack, engine, or mechanism is timing-qualified here.
- **TEST-COV5K** establishes the first exact-stack qualification of the
  post-R1 mechanism under the identity contract above, binding one receipt
  to TEST-COV5K Outcome A.
- **Exact-stack equality**: a receipt matches only on equality of every
  bound identity field. **No patch drift is allowed**: any identity-field
  change — including psutil or Docker SDK version, engine component set,
  API version, cgroup version, image digest, OS/kernel, Python, libpq, or
  reader mechanism — voids the receipt and is a requalification trigger.
- **Unsupported stack refusal**: absence of a receipt means absence of
  qualification, never a default pass; unsupported capability refuses
  outright per the existing fail-closed rules.
- **Receipt redaction**: receipts contain public-safe identity only — no
  usernames, home paths, hostnames, credentials, or private configuration;
  component details bind by digest.
- The mechanism change enacted by R1 is itself a requalification trigger
  under the existing trigger list; TEST-COV5K is that requalification.

### Migration And Compatibility

- One bounded implementation slice (`SCALE28-FIX12-R1`) performs the
  cutover; no dual-mode transition period, no runtime mechanism selection
  switch, and no environment-variable mechanism toggles are introduced.
- Reader names, signatures, byte units, `None`-on-failure semantics, and
  input-validation errors of `read_process_rss_bytes`,
  `read_process_tree_rss_bytes`, and `read_container_rss_upper_bound` are
  preserved; only the mechanism changes.
- `REPOMAP_STORAGE_READBACK_DRIVER` and `REPOMAP_PSQL_COMMAND` retain
  their names and meanings. `OpsJsonReadbackMode` values are retained and
  re-scoped as specified; callsites are updated in the same commit so no
  name silently changes meaning.
- The Psycopg no-fallback correction is a named behavioral change:
  previously-hidden fallback executions become structured fail-closed
  errors carrying the existing topology hint.
- Historic CLI mechanisms remain available only as explicit
  administrative/lifecycle/diagnostic paths under the conditions above.
  The frozen 90/90 dataset, the FIX11 aggregates, and all prior campaign
  evidence remain historical selection evidence.
- Evidence and test dispositions: the hidden-psql strict xfail becomes a
  required passing R1 regression (Psycopg-selected reads never invoke
  psql); the process-boundary helper remains test support; the nine former
  ps nodes remain behavioral tests and must no longer require `ps`
  execution after R1; representative process-count tests gain the exact
  zero-count regressions above; the DIAG1/FIX1/FIX2/REVIEW1 records stand
  unedited as accepted history.

### SCALE28-FIX12-R1 Contract

Implementation-ready contract, frozen. R1 is the runtime data-plane slice;
it does not implement the separately contracted FIX12 observer/terminal
reimplementation, policy literals, or mechanical-enforcement validation,
which remain governed by the corrected FIX12 contract above.

**Authorized scope (exact owners from current callgraph):**

1. `src/main/python/repomap_kg/ops/readback.py` — remove the
   Psycopg-to-psql container fallback branch of
   `execute_ops_json_readback`; re-scope the mode parameter to the
   explicit psql path; retain the topology hint text in the structured
   Psycopg failure.
2. `src/main/python/repomap_kg/server/ops.py`,
   `src/main/python/repomap_kg/ops/config.py`,
   `src/main/python/repomap_kg/ops/refresh.py`,
   `src/main/python/repomap_kg/ops/graph_files.py` — caller updates for
   the re-scoped mode only; the psql-native refresh chain's semantics are
   unchanged.
3. `src/main/python/repomap_kg/storage/readback_driver.py` — signature
   accommodation only; driver vocabulary, selection, and validation
   unchanged.
4. `tools/scale12_resource_sampling.py` — replace `read_process_rss_bytes`
   and `read_process_tree_rss_bytes` with the psutil authority; replace
   `read_container_rss_upper_bound` with the Engine API authority;
   import-time dependency fail-fast; preserve names, signatures, units,
   and failure contracts.
5. `tools/scale28_preparation_resources.py` — before/after elapsed
   evidence for the client-RSS and container-RSS reads; failure categories
   unchanged.
6. `pyproject.toml` — exactly one new `[project.optional-dependencies]`
   group `scale-tools` with exact-pinned `psutil` and `docker`.
7. Tests — turn the hidden-psql strict xfail into a passing no-fallback
   regression; add the exact process-count regressions; add the
   psutil/docker failure matrices (through fakes at the library seams);
   add identity-receipt field coverage; keep the nine former ps nodes
   passing without `ps` execution.

**Additionally authorized**: runtime-identity capture for the fields this
amendment adds, within the already-contracted FIX12
runtime-identity/qualification-comparison area.

**Prohibited in R1:**

```text
manual C/Rust or ctypes telemetry implementation
unbounded fallback chains
automatic CLI fallback of any kind
global Docker inventory or enumeration of unrelated objects
new public CLI/MCP write surface
schema/SQL changes
graph-vocabulary changes
timeout retuning (3,400/8,900 and all maxima retained)
observer/cancellation/freshness/terminal/release contract changes
dependency changes outside the scale-tools group
SCALE29
```

**Required red-first tests** (each failing deterministically against the
old tree): Psycopg-selected read with class-08 failure produces the
structured error and zero psql intent; process-RSS read spawns zero host
processes and maps NoSuchProcess/AccessDenied/zombie to `None`; missing
psutil/docker fails at import, not as `resource_unavailable`; container-RSS
read spawns zero host processes, applies the cgroup-v2 subtraction, and
refuses raw-usage substitution, missing fields, and negative results;
Engine API timeout maps to `None` within its 2.0 second bound; identity
receipt contains every field of this amendment.

**Stop conditions**: any prohibited-scope touch; any automatic CLI
fallback surviving; any zero-RSS-on-failure path; any silently changed
configuration meaning; any natural preparation timeout on the intended
qualification stack during R1 verification; any remote Git action in a
local-only sandbox.

### TEST-COV5K Contract

TEST-COV5K remains mandatory after R1 and begins only after R1 Outcome A
with operator confirmation of the shared tip. In addition to the corrected
TEST-COV5K contract above, it must qualify — with real semantics per group,
never repeated labels over one case:

1. **Psycopg no-fallback semantics** — connection-failure matrices across
   modes and drivers proving zero psql intent under Psycopg selection.
2. **Process RSS semantic parity and failure matrix** — psutil parity
   with the accepted byte semantics on live owned processes;
   NoSuchProcess/AccessDenied/zombie/invalid-input dispositions.
3. **Container RSS CLI-equivalence on the selected exact stack** — fresh
   bounded CLI-versus-API equivalence evidence under the accepted
   cgroup-v2 mapping (the frozen 90/90 dataset remains selection
   evidence and is not reused as qualification).
4. **Zero runtime-data-plane host process count** — the exact
   process-count contract, on both evidence axes.
5. **Deadline and failure-category preservation** — 3,400/8,900 behavior,
   reader budgets, first-source causality, both non-relabeling
   prohibitions.
6. **Engine/runtime identity receipt** — every bound field captured,
   discriminating (component set, OSType, OS string), redacted, and
   equality-matched.
7. **Configured observer/preparation integration** — the configured owning
   areas exercising the new authorities end to end.
8. **Cleanup and no-residue** — no leaked clients, sockets, threads,
   containers, or scratch.
9. **Administrative CLI separation** — explicit psql/lifecycle/diagnostic
   paths still function, remain explicitly selected, and remain outside
   every automatic runtime path.

SCALE29 remains prohibited until TEST-COV5K Outcome A and the shared-tip
guard.

### Rejected Alternatives

- Options B, C, D, and E, for the scored reasons above.
- `resource.getrusage` maximum RSS: peak not current, current-process-only,
  unit-ambiguous across platforms.
- Any current-process-only API for an arbitrary owned PID.
- Shelling out to `ps` in any form on the runtime data plane.
- Manual ctypes/Mach/procfs or hand-rolled Docker Unix-socket HTTP, and any
  new C/Rust helper: no compelling scope justifies reimplementing
  established, maintained authorities.
- Raw `memory_stats.usage` as CLI-equivalent container memory.
- `docker stats` as an automatic runtime fallback.
- Placing psutil or the Docker SDK in the shipped `repomap_kg`
  dependencies.
- A watcher thread to time the in-process RSS read.
- Retaining any configuration name whose behavior silently changes
  transport, or a dual-mode migration period.

### Consequences

- The runtime data plane becomes zero-external-process and
  sandbox-independent: no exec permission is required to read process or
  container RSS, and the class of environment failures that produced the
  nine-node `EPERM` residue cannot recur on that path.
- A Psycopg-selected read failure is now visible and structured instead of
  silently changing transport; operators keep the topology hint guidance.
- The dominant ~2 second engine-CLI sampling mode leaves the preparation
  critical path; the 3,400/8,900 policy is retained unchanged and gains
  headroom rather than being retuned.
- Two established dependencies enter a dedicated operational tooling
  group; the shipped package is unchanged.
- The FIX1 error asymmetry is repaired within the preserved reader
  contract.
- R1 carries a bounded production and tooling diff with exact owners;
  TEST-COV5K must qualify the new stack before SCALE29; the 90/90 dataset
  and all prior campaign evidence remain frozen historical selection
  evidence.

## TEST-COV5K-R1 Additive Outcome

TEST-COV5K-R1 established the first phase-owned capable environment requested
after R1: the exact-pinned scale tooling imported, `/bin/ps` and `vm_stat`
executed through shell-false subprocess probes, the Docker endpoint and
loopback worked, disposable PostgreSQL was readable through Psycopg, one-shot
stats succeeded, complete unqualified runtime identity was captured, and exact
cleanup passed.

Qualification nevertheless stopped at the first valid Group A observation.
`DEFAULT_PREPARATION_DEADLINE_POLICY` remains 1,800/4,100 milliseconds on the
accepted R1 tip, not this ADR's selected 3,400/8,900 contract. This result
confirms the distinction already frozen here: SCALE28-FIX12-R1 implemented
only the runtime data-plane amendment; the corrected SCALE28-FIX12 contract
still owns the policy literals, end-to-end validation, bounded-read
correction, and separately contracted observer/terminal work.

Outcome B changes no selected value or production owner. No timing
qualification receipt exists, Q2 stands, and SCALE29 remains prohibited.

## SCALE28-FIX12-R2 Additive Outcome

R2 accepted TEST-COV5K-R1's policy mismatch and created the required fresh
capable environment. All host probes and the complete repository all-suite
gate passed. The separately required exact compileall command then failed on
two deliberately malformed tracked extraction fixtures beneath `src/test`.

The opening-gate rule required Outcome B before source freeze, red tests, or
production/test mutation. The selected 3,400/8,900 policy, named allowance
constants, mechanical derivation, bounded-read correction, and ADR 0045/0046
completion therefore remain unimplemented. R1's runtime data plane is
unchanged, Q2 stands, and SCALE29 remains prohibited.

## SCALE28-FIX12-R2-FIX1 Additive Outcome

The bounded retry implements the selected 3,400/8,900 millisecond policy and
derives the exact 8,900 millisecond total mechanically. The three stale nested
reads now recompute remaining absolute attempt authority; SIGTERM join uses its
named 100 millisecond constant; cleanup inability is a non-retryable cleanup
limitation. Six 30-attempt condition sets and the 160-case causality matrix
pass with zero natural preparation timeout, overlap, third attempt, or valid
observation removal.

R1's in-process runtime data plane remains intact: Psycopg has no implicit
psql fallback, psutil owns process readers, the Docker Engine API owns one-shot
container stats, runtime host-process and nested-psql-intent counts remain
zero, the 90/90 selection evidence is frozen, and runtime identity remains
complete but unqualified. TEST-COV5K-R2 is required after operator acceptance;
SCALE29 remains prohibited.

## SCALE28-FIX12-R2-FIX2 Additive Correction

FIX2 changes no preparation value, reader, retry, cleanup, runtime data-plane,
or runtime-identity owner. The 3,400/8,900 millisecond policy, two-attempt
maximum, freshness 800, Psycopg no-fallback behavior, psutil process readers,
Docker Engine API container reader, zero runtime host-process count, zero
nested-psql intent, and complete unqualified identity remain intact.

The correction is limited to enforcing the already-selected terminal
500 millisecond authority and replacing a product-derived cancellation
evidence oracle with an ADR-owned test oracle. TEST-COV5K-R2 remains required
and unauthorized; SCALE29 remains prohibited.

## REPOMAP-CI0B-FIX9 Additive Worker-Activation Observation

REPOMAP-CI0B-FIX9 changes no production preparation value. The selected
3,400/8,900 millisecond policy, two-attempt maximum, freshness 800, subordinate
150/300/300 bounds, and the pre-spawn attempt clock origin of the "Attempt
Clock Contents" table are all retained. `tools/scale28_preparation_policy.py`
is untouched.

Two additions are made to the worker lifecycle.

**One-shot activation channel.** `PreparationWorkerAttempt` gains a fifth
one-shot channel, `worker_readiness` (256-byte bound). The child emits exactly
one readiness message carrying the attempt run nonce, after request decode and
digest validation and immediately before the semantic preparation operation.
The parent's readiness wait is bounded by `A − elapsed`; it introduces no new
allowance and nothing additive to A. A readiness token not bound to the
attempt nonce is refused, and sender EOF without a message is treated as "not
activated" so a pre-readiness child failure still classifies from the failure
channel rather than as a timeout.

**Optional nested semantic bound.** `PreparationDeadlinePolicy` gains
`semantic_operation_timeout_ms` (S), defaulting to `None`. When unset — the
production case — every deadline and failure classification is identical to
the pre-FIX9 lifecycle and readiness is pure evidence carrying no authority.
The lifecycle itself is not unchanged in production: the fifth channel, the
readiness message, the parent readiness wait, and the two added result fields
are present there too. When set, the observation-frame wait uses
`min(A − elapsed, ready + S)`. This is the same nested-subordinate composition
already used by the receipt and success-path settlement bounds in the
"Subordinate Deadline Interaction" table: strictly tighter than A, never
additive, and consumed within A.

Interval disposition, extending the "Attempt Clock Contents" table:

| Stage                          | Disposition |
| ------------------------------ | ----------- |
| Worker activation signal       | Inside attempt authority; parent wait is `A − elapsed` |
| Semantic preparation operation | Inside attempt authority; when S is set the wait is `min(A − elapsed, ready + S)` — nested, never additive |

No elapsed time is excluded from A or from the total wall clock. Bootstrap
remains charged to the attempt and to the total exactly as before; the only
new capability is that the parent can now *attribute* an overrun rather than
merely detect one. A worker that never activates within A still fails closed
as `preparation_timeout`/`worker`, now additionally recording
`activation_observed = False`. No failure category is added, removed, or
relabelled.

**Group-A test policy.** The TEST-COV5K-R2 Group-A policy previously selected
A = 1,000 milliseconds, which stripped this ADR's derived 400 millisecond
`M_spawn` term while retaining the ADR's requirement that spawn, interpreter
startup, and import be charged to the attempt. On a sufficiently slow host the
result was that ordinary worker bootstrap consumed the entire attempt budget,
so scenarios expecting `attempt_success`, `hard_failure`, and `ipc_error`
observed `preparation_timeout` instead. Group A now uses the ADR-qualified
A = 3,400 with S = 1,000 as its semantic bound, and its totals are derived
mechanically to 8,800 (retry gate) and 9,100 (ordinary). The deliberate
1.5-second timeout fault continues to classify as `preparation_timeout`,
now against the semantic bound rather than incidentally against A.
