# ADR 0044: Bounded Startup Authority Decomposition

## Title

Bounded Startup Authority Decomposition

## Status

Accepted — Outcome A

## Date

2026-07-22

## Context

The accepted startup path blocks the child until storage, observer, resource,
event, failure, ownership, and release authorities are ready. SCALE28-ADR1
proved that the current in-process critical path cannot fit the operator's
3,000 ms architecture guard: its frozen result is 5,850 ms and its dominant
valid component is a 4,144 ms loaded local-resource observation.

The dominant local operation walks the owned PGDATA tree synchronously with
`lstat` and `scandir`. It has no in-process cancellation point. Observer,
event, failure, causality, and atomic release authority remain live parent
state and cannot become authoritative merely because another process reports
them ready.

## ADR1 Decision

ADR 0043 rejects the 5,850 ms current in-process handoff and does not authorize
that value for production. It also preserves that 500 ms is known-defective.
This ADR does not reconsider either result.

## Problem

Slow startup-resource acquisition must leave the short final ownership and
atomic release proof without permitting stale resource evidence, a live setup
connection, an unsettled reader or worker, an observation gap, or a larger
current handoff. Preparation and cleanup must be bounded on POSIX and Windows,
and the parent must remain the sole child-release authority.

## Decision Drivers

Safety equivalence dominates the comparison. A viable architecture must also
provide exact freshness, bounded cancellation, deterministic cleanup, causal
failure priority, atomic release integrity, continuous observation, spawn-safe
cross-platform behavior, a small closed protocol, deterministic testing, and
bounded performance. A simpler or faster option cannot win by weakening an
authority.

## Preserved Authorities

The selected design preserves:

- no child release before every readiness fact passes;
- settled startup resource authority with no deferred reader failure;
- no live setup probe or preparation connection at release;
- zero ambient and unknown clients;
- two new final stable ownership samples;
- one exact parent observer registration identity with fail-closed loss;
- TEST-COV4 source-sequenced failure causality;
- TEST-COV3 parent-owned atomic release;
- SCALE23 telemetry and SCALE25 terminal settlement;
- SCALE28-FIX1 structured categories;
- no blind reconnect, heartbeat, observation gap, dynamic tuning, or public
  timeout configuration; and
- exact worker, connection, reader, descriptor, and disposable-state cleanup.

## Clock Decomposition

The preparation clock begins before one worker spawn. It contains resource
acquisition, strict result transfer, worker exit, process-tree cleanup, reader
and connection cleanup, and parent observation of terminal state.

The final-release clock begins when one complete current-attempt result has
been received. It contains receipt validation, observed process settlement,
freshness and scope revalidation, event and failure readiness revalidation,
transient ownership clearance, two new stable ownership samples, observer
activation, and atomic release.

The storage baseline and parent observer registration, telemetry-reader
readiness, and initial ownership validation may precede the final clock because
they remain live parent authorities. The final window revalidates them. Initial
ownership samples are never reused for release.

## Options Considered

1. **Option A — process-isolated full startup preparation.** Rejected because
   observer, event, failure, and release authority are process-local live
   authorities. Reporting them ready does not transfer them. Re-establishing
   all four in the parent reduces the option to the hybrid with extra protocol.
2. **Option B — two-stage in-process preparation.** Rejected because the
   synchronous PGDATA tree walk cannot be forcibly cancelled and settled in a
   Python thread. Moving the clock without deterministic cancellation is not a
   bounded architecture.
3. **Option C — hybrid isolated resource preparation plus parent final proof.**
   Accepted. The worker owns only slow local and database resource work. The
   parent observer remains continuous and owns result acceptance, worker
   settlement, freshness, final ownership, activation, and release.
4. **Option D — current architecture at 5,850 ms.** Rejected by ADR 0043.
5. **Option E — weaken evidence to fit 500 ms.** Rejected.
6. **Option F — dynamic or environment-specific tuning.** Rejected.

## Prototype Protocol

The comparison protocol froze option elimination, fixed sample counts, cold
and loaded public-safe conditions, 18 fault scenarios, clock boundaries,
freshness and cleanup measurements, maximum-valid-observation aggregation,
numeric derivation, upward rounding, the 3,000 ms guard, and stop rules before
selection measurement.

The first private run was invalidated because its fault harness recorded the
expected causal category without asserting the actual raised category. A
corrected revision 1 run was also invalidated when review found that numeric
cooperative and forced process-settlement sub-bounds had not been frozen in the
plan. The initial revision 2 execution was invalidated during final review
because five process-managed faults still retained the expected category after
cleanup without deriving it from the observed process result. Its corrected-
category rerun was also invalidated: PostgreSQL clearance followed simulated
release, resource paths were serialized despite an overlap-based ceiling, and
the forced-cleanup case lacked a live descendant. The final revision 2 harness
derives every category from observations, overlaps the resource paths, proves
two pre-release clear samples through one stable observer, and exercises a live
descendant. The complete campaign was then rerun. No invalidated run
contributes to the decision.

## Prototype Evidence

Revision 2 completed 20 cold, 30 loaded, and 20 transient private prototype
executions. It completed 10 configured prototype executions for each of
SCALE14, SCALE23, SCALE28, and SCALE28-FIX1, plus 10 disposable PostgreSQL
worker-connection cases. All 10 PostgreSQL cases observed the worker connection
while live, overlapped local and serialized SQL resource work, retained one
observer identity, and obtained two consecutive clear samples after exit and
before release.

The campaign also completed 100 deterministic orderings and 180 fault cases,
10 for each required scenario. Every fault refused child release, retained one
exact first category, retained no stale candidate or partial mutation, and
completed cleanup. All 10 cleanup-timeout cases observed a live descendant and
settled the complete process group. Valid observations removed: **0**.

The maximum private prototype preparation span was 408 ms. The maximum private
prototype final span was 2 ms. These are public-safe prototype measurements,
not production PGDATA bounds or acceptance evidence.

## Failure Matrix

The fixed matrix covers preparation timeout, worker crash, worker signal exit,
partial result, malformed result, duplicate result, stale result, scope
mismatch, runtime restart, resource-reader failure, persistent ambient client,
transient ambient client, unknown client, observer failure, event readiness
failure, child release refusal, parent cancellation, and cleanup timeout.

Failure from any pre-release state enters `refused` and then `settled`. The
first causal category is retained. No failed state returns to ready and no old
receipt becomes eligible for another attempt.

## Freshness Contract

The parent monotonic clock is authoritative; absolute worker and parent clock
values are not compared. Worker-local timestamps prove only internal ordering.
Receipt transfer has a fixed 100 ms reserve, and the parent conservatively
treats evidence as complete 100 ms before complete receipt arrival.

The freshness lease is 1,000 ms. The parent revalidates exact runtime scope,
PostgreSQL and PGDATA generation, graph/control/maintenance topology,
configuration generation, observer generation, event and failure readiness,
worker and reader settlement, cleanup, immutable bytes, and age at receipt
acceptance, before each stable ownership sample, and immediately before
release.

Runtime or PostgreSQL restart, PGDATA change, topology change, observer change
or loss, a new or unresolved setup client, reader or worker cleanup failure,
lease expiry, configuration change, payload mismatch, duplicate result, or
cancellation invalidates the result. Reacquisition creates a new nonce,
attempt, worker, receipt, and state generation. At most two attempts share one
10,000 ms total ceiling.

## Typed Result Contract

`StartupPreparationReceipt` version 1 is one canonical ASCII JSON object no
larger than 65,536 bytes. It has exact fields for schema, run nonce, attempt,
runtime scope, topology, PGDATA generation, configuration generation, observer
generation, resource baseline values, worker-local observation and completion
times, resource-reader settlement, cleanup, worker terminal state, closed
category, and a SHA-256 digest of the canonical payload excluding the digest.

The runtime-scope binding includes the exact PostgreSQL instance generation and
database identity; the PGDATA binding independently covers the storage-root
generation. A restart changes at least one current parent expectation.

IPC framing is bounded while reading, not after unbounded capture: the parent
accepts at most 65,536 payload bytes, detects overflow with one additional byte,
and bounds diagnostic stderr separately. Partial EOF, additional stdout, or
unexpected stderr refuses the attempt.

The contract rejects missing, extra, or duplicate keys; unknown schema;
Boolean numeric values; signed 64-bit overflow; invalid clock order; wrong
scope or generation; unavailable resources; partial or malformed bytes;
unsettled or signaled worker state; live subordinate authorities; stale,
changed, duplicate, or cross-run results; and private values in place of
digests.

Worker terminal and cleanup fields are claims until the parent observes an
exit code, signal state, process-tree settlement, and zero subordinate
resources that exactly match. The receipt never grants launch authority.

## Preparation Ceiling

The worker may run the local-resource path and the two serialized resource SQL
operations concurrently because the whole worker process is the cancellation
boundary. The final campaign exercised that overlap in all 10 PostgreSQL cases.
ADR1 provides a 4,570 ms local-resource budget; two resource SQL operations
total 380 ms, so the controlling parallel work is 4,570 ms. Adding
310 ms resource settlement and a 100 ms result/process margin yields 4,980 ms,
which rounds upward to the existing 5,000 ms internal startup ceiling.

Each resource SQL operation retains ADR1's fixed 150 ms server statement
timeout, 170 ms client cancellation trigger, 20 ms cancellation-request bound,
and 190 ms caller deadline. Safe Psycopg cancellation support is mandatory.
The server timeout and parent-observed connection clearance remain authoritative
even when forced worker termination is required.

One attempt, including cleanup, is bounded by 5,000 ms. Cancellation allows
100 ms cooperative whole-tree termination followed by 100 ms forced whole-
tree kill and settlement. At most two attempts share a 10,000 ms total. No
timeout grows and no value is public configuration.

FIX4 must stop resource work no later than the 4,570 ms resource-work boundary.
The 310 ms settlement budget owns normal settlement or the 100/100 ms
termination path, and the 100 ms result/process margin remains inside the
attempt. It may not wait 5,000 ms and then add cleanup.

## Final Release Ceiling

Revision 2 observed maxima of 1 ms for receipt validation, 1 ms for worker
settlement proof, 1 ms for scope revalidation, 1 ms for activation and release,
and 2 ms for the complete final window. The frozen margins produce budgets of
20, 40, 20, and 20 ms respectively.

Adding 20 ms event/failure revalidation, 50 ms transient settlement, two 190 ms
ownership operations, and the 100 ms scheduling/IPC margin yields a 650 ms
component bound. The measured bound is 102 ms. The formula selects the maximum
of those values and 500 ms, then rounds upward to 50 ms, producing a **650 ms
final release ceiling**.

The 650 ms ceiling is below the 3,000 ms operator guard. The 1,000 ms freshness
lease is 650 ms plus the 100 ms transfer reserve and 250 ms freshness reserve.

## Decision

Select Option C: a hybrid isolated resource-preparation worker with parent-
owned final startup authority.

The worker owns only slow local and database resource acquisition. The parent
owns the continuous observer, strict typed-result acceptance, observed worker
settlement, freshness, event and failure readiness, transient clearance, two
stable ownership samples, observer activation, and atomic release.

Proceed to SCALE28-FIX4 for implementation of the frozen architecture and
contracts. This ADR does not implement or qualify production behavior.

## Selected State Machine

```text
unprepared
→ preparing
→ preparation_result_received
→ preparation_validated
→ preparation_settled
→ final_readiness_open
→ transient_ownership_clear
→ stable_sample_one
→ stable_sample_two
→ ready_to_release
→ child_released
```

Any pre-release failure enters:

```text
refused → settled
```

If one reacquisition is allowed, it starts a new preparation generation from
`settled`; the failed generation never returns to readiness.

## Cancellation And Cleanup

Parent cancellation closes result acceptance, refuses release, requests
whole-tree termination for 100 ms, then forces whole-tree kill and settlement
for 100 ms. Timeout, crash, signal exit, malformed or duplicate result,
subordinate resource, or cleanup failure follows the same fail-closed path.

Cooperative termination requests bounded Psycopg cancellation and closes the
worker connection before process exit. Forced termination does not count as
database settlement by itself; the fixed server timeout must expire and the
continuous parent observer must obtain two clear samples inside the attempt
before any later generation or release can proceed.

The worker must close resource SQL connections and readers before emitting its
single result. The parent must then observe worker exit, no descendants, zero
worker connections in two consecutive ownership samples, no reader or thread,
and no leaked descriptor before stable final proof. The final campaign exercised
a live descendant in all 10 cleanup-timeout cases and proved complete POSIX
process-group settlement.

## Cross-Platform Behavior

Workers use a fresh spawn-safe request and explicit environment; no fork-
inherited mutable state is authority. POSIX uses a new session/process group.
Windows must use a non-breakaway Job Object with kill-on-close and spawn-safe
arguments. If the required whole-tree boundary or settlement proof is
unavailable, startup refuses rather than falling back to an uncontained worker.

The private prototype exercised the POSIX path. SCALE28-FIX4 must implement the
accepted Windows refusal/Job Object contract, and TEST-COV5C must qualify both
platform paths.

## Consequences

- Slow PGDATA and resource SQL work leaves the final release clock.
- The parent retains every live readiness and release authority.
- One strict private receipt and one bounded worker lifecycle are added.
- Preparation may retry once only after exact settlement under a new
  generation.
- Production retains the known-defective current behavior until FIX4.
- Prototype evidence does not remove any expected failure or quarantine.

## Rejected Alternatives

The 5,850 ms current handoff, evidence weakening, fewer stable samples,
accepting a live or recently settled client, in-flight reader acceptance,
clock movement without freshness, dynamic or environment-specific tuning,
public timeout configuration, blind reconnect, heartbeat, fork-only cleanup,
and an external service or dependency are rejected.

## Fallback Triggers

Return to an explicit architecture or prerequisite decision rather than raise
a ceiling if FIX4 cannot prove the 5,000 ms attempt and 10,000 ms total bounds,
the 650 ms final ceiling, 1,000 ms lease, 100/100 ms process cleanup, strict
receipt, continuous observer, or Windows whole-tree settlement. Do not fall
back to Options A, B, or D implicitly.

## SCALE28-FIX4 Contract

FIX4 may implement only the selected hybrid architecture. It must retain the
TEST-COV5A harness; turn all 10 stalled-handshake and six timeout/cancellation
strict expected failures green; pass and remove all four configured-campaign
quarantines; implement the exact receipt, freshness, state, preparation,
cleanup, and final-release contracts; preserve every accepted authority; run
no protected work; and create and push exactly one commit.

## TEST-COV5C Contract

After FIX4, TEST-COV5C must independently complete 30 real bootstrap fault-
matrix passes, 50 real PostgreSQL timeout-hierarchy passes, 500 deterministic
cross-authority permutations, all four formerly quarantined owning paths, 15
consecutive configured mixed campaigns, three fresh public-safe SCALE29-like
dress rehearsals, one selected-architecture failure prior-publication
rehearsal, 10 focused black-box selections, four complete repository gates,
cross-platform process/refusal coverage, exact cleanup, and independent review.
No selected-scope expected failure or quarantine may remain.

## Protected-Work Boundary

No protected source or retained runtime was accessed. No protected prelaunch,
refresh, publication, MCP exposure, baseline, drift, SCALE closure, or GO24
advice was performed. This ADR changes no production source or dependency.

## Successors

SCALE28-FIX4 is the sole immediate successor and is limited to the frozen
hybrid contract. TEST-COV5C follows a committed, pushed, synchronized, clean
FIX4. SCALE29 remains prohibited until TEST-COV5C Outcome A is committed,
pushed, fetched, synchronized, clean, and independently approved.

## SCALE28-ADR2-FIX1 Additive Correction

This correction was accepted on 2026-07-22 after post-acceptance review found
that receipt version 1 did not conservatively bound resource-evidence age.

The following statements supersede only the affected freshness and receipt
parts of this ADR:

- **The hybrid architecture remains selected.** The isolated worker continues
  to own only slow local and database resource acquisition. The parent
  continues to own the live observer, evidence acceptance, process settlement,
  freshness, final ownership proof, activation, and atomic release.
- **Receipt version 1 freshness is superseded.** Its worker-local observation
  and result timestamps prove ordering only, while its parent calculation
  omitted the worker's observation-to-result interval.
- **The 1,000 ms lease is withdrawn.** It is not implementation authority and
  must not reach SCALE28-FIX4.
- **The original FIX4 authorization is suspended until this correction.** FIX4
  is now authorized only for the corrected contract below after the correction
  commit is pushed, synchronized, clean, and independently approved.

The revision-2 architecture-selection evidence above remains historical. It is
not described as if it used the corrected protocol.

### Corrected Freshness Finding

Receipt version 1 accepted this sequence:

```text
resource observation completes
→ result creation is delayed inside the worker
→ the receipt arrives promptly
→ the parent measures only time since receipt
```

Scope and generation revalidation does not refresh allocated PGDATA bytes,
backing free space, or the accepted resource baseline. The 1,000 ms lease was
also smaller than the possible 310 ms resource-settlement budget, 100 ms
result/process margin, and 650 ms final-release ceiling. Increasing only the
lease would not repair the missing parent-observed boundary.

### Corrected Resource Observation Semantics

The current contract uses one baseline freeze. Under an unchanged PGDATA
generation, the worker completes the non-mutating PGDATA walk. After that slow
branch it samples the fast values again: client peak RSS, PostgreSQL container
RSS upper bound, temporary-byte delta, WAL delta, and backing-filesystem free
space. The canonical immutable baseline contains those values plus allocated
PGDATA delta, completed PGDATA-reader duration, schema version, and closed
availability.

The observation-complete boundary exists only after every required value is
available. A PGDATA, runtime, topology, configuration, or observer generation
change invalidates it. Reader and connection settlement occur after
acknowledgement and remain terminal-receipt facts; they are not substituted for
baseline values.

### Corrected Observation And ACK Protocol

`StartupPreparationObservation` version 1 is canonical bounded ASCII JSON no
larger than 4,096 bytes. It contains exactly:

```text
schema_version
frame_kind
run_nonce
attempt
runtime_scope_digest
topology_digest
pgdata_generation_digest
configuration_generation_digest
observer_generation_digest
resource_baseline_digest
observation_started_ns
observation_completed_ns
frame_sequence
frame_digest
```

The digest covers every field except itself. Sequence is exactly one per new
attempt generation. Worker timestamps establish local ordering and duration
only. The worker writes the frame on the private preparation-control channel
without unrelated work after the baseline freeze.

The parent validates the frame, records
`observation_frame_received_parent_ns` using its monotonic clock, and returns a
canonical acknowledgement no larger than 2,048 bytes. The acknowledgement
contains exact schema and kind, run nonce, attempt, sequence, frame digest,
closed `accepted` category, and structural digest. The worker must validate the
exact acknowledgement within the unchanged 100 ms completion-to-ACK reserve.
No accepted terminal receipt follows a missing, malformed, duplicate, stale,
wrong, or timed-out acknowledgement.

### Corrected Receipt Contract

`StartupPreparationReceipt` version 2 supersedes version 1 for FIX4 readiness.
It is canonical bounded ASCII JSON no larger than 65,536 bytes. It binds the
exact run, attempt, five scope and generation digests, canonical resource
baseline and its digest, observation-frame digest, acknowledgement digest,
worker-local observation and acknowledgement order, result completion, reader
settlement, cleanup, terminal claim, closed category, and payload digest.

The receipt must repeat the exact observation start and completion values from
the accepted frame and prove:

```text
observation_started_ns
<= observation_completed_ns
<= observation_acknowledged_ns
<= result_completed_ns

observation_acknowledged_ns - observation_completed_ns <= 100 ms
```

The parent accepts one receipt only after the matching frame and ACK. It
recomputes the canonical baseline digest, requires frame and receipt baseline,
scope, generation, and observation bindings to match, and independently
observes process exit and complete process-tree cleanup. The receipt is
evidence and never launch authority.

### Corrected Parent Freshness Authority

The parent never compares absolute worker and parent clocks. Its exact origin
and age are:

```text
conservative_observation_origin_parent_ns =
    observation_frame_received_parent_ns - 100_000_000

age_ns =
    parent_now_ns - conservative_observation_origin_parent_ns
```

Origin underflow, parent clock reversal, overflow, a missing timestamp, or age
equal to or greater than the lease refuses the attempt. Freshness is checked at
frame acceptance, terminal-receipt acceptance, after process-tree settlement,
before stable sample one, before stable sample two, and immediately before
atomic release. The sample-two check follows sample one, and the release check
follows every other readiness fact.

### Corrected Revision-3 Evidence And Lease

The pre-registered revision-3 private prototype campaign completed 522 valid
records: 20 cold, 30 loaded, 20 transient, 10 configured executions for each of
SCALE14, SCALE23, SCALE28, and SCALE28-FIX1, 100 deterministic orderings, 180
original fault cases, 120 corrected-freshness fault cases, 10 disposable
PostgreSQL cases, and two static process-boundary probes. Zero valid
observations were removed. One development campaign remains physically
separate and contributes no selection evidence.

The accepted maxima were 88 ms preparation, 2 ms parent frame-to-receipt,
15 ms parent frame-to-release, and 2 ms final release. Each disposable
PostgreSQL worker connection was observed while live and absent after worker
settlement. These are private prototype results, not production qualification.

The pre-registered integer-millisecond formula produced:

```text
component margin:                         30 ms
observation-to-receipt budget:           410 ms
freshness component bound:             1,410 ms
measured observation-to-release bound:   115 ms
selected rounded freshness lease:       1,450 ms
```

The corrected current lease is therefore **1,450 ms**. It is private, fixed,
not dynamically tuned, not public configuration, and never substitutes for a
fresh check. The 5,000 ms attempt, 10,000 ms total-preparation, 100 ms transfer,
and 650 ms final-release bounds remain unchanged.

### Corrected Reacquisition And Failure Semantics

A refused or stale generation settles fully. Attempt two requires a new nonce,
worker, attempt identity, frame-sequence generation, baseline, frame, ACK,
receipt, parent frame timestamp, and state-machine generation. No first-attempt
byte, value, digest, or timestamp may re-enter readiness. Both attempts remain
inside the existing 10,000 ms total ceiling.

Closed corrected categories cover missing, invalid, or duplicate observation
frames; acknowledgement failure; receipt/frame mismatch; stale preparation
evidence; duplicate result; scope mismatch; cleanup failure; and unsettled
process state. Source sequence remains authoritative. There is no category
priority. Every failure refuses release and completes exact cleanup.

### Corrected SCALE28-FIX4 Contract

SCALE28-FIX4 may implement only the retained hybrid architecture with the
acknowledged observation frame, receipt version 2, parent-monotonic origin,
1,450 ms lease, unchanged 5,000/10,000 ms preparation bounds, unchanged 650 ms
final-release ceiling, and existing process-group, Job Object/refusal, observer,
causality, ownership, atomic-release, and cleanup authorities.

FIX4 must turn all 10 stalled-handshake and six timeout/cancellation strict
expected failures green, pass and remove all four configured quarantines, and
pass every ADR2-FIX1 freshness test. It runs no protected work and creates one
commit.

### Corrected TEST-COV5C Contract

The existing independent qualification bar remains. TEST-COV5C additionally
requires 30 observation-frame/ACK protocol passes, 50 corrected freshness-age
passes, 100 stale-at-receipt/sample-one/sample-two/release permutations, two
reacquisition generations per supported case, and zero selected-scope expected
failures or quarantines.

SCALE29 remains prohibited until TEST-COV5C Outcome A is committed, pushed,
fetched, synchronized, clean, and independently approved.

## SCALE28-ADR2-FIX2 Additive Correction

This correction closed as Outcome B on 2026-07-22 after post-commit review found that
revision 3 retained mutable accepted mappings, synthesized campaign categories
and cleanup facts, labeled generic model executions as configured owning-area
evidence, received process messages without transport bounds, and used receipt-
version-2 terminal claims that could not be true at emission time.

The following statements supersede only the affected evidence, transport,
receipt, and successor-authority parts of this ADR:

- **The hybrid architecture and parent-anchored observation-frame concept
  remain selected.** The worker continues to own slow resource preparation,
  while the parent owns evidence acceptance, actual process terminal facts,
  freshness, final ownership, activation, and atomic release.
- **Revision-3 campaign acceptance is superseded.** Its results remain
  historical comparison evidence and are not current FIX4 selection evidence.
- **Mutable mapping authority is rejected.** Accepted expectations, baseline,
  frame, acknowledgement, receipt, cleanup, and expected disposition must be
  deeply immutable typed values backed by exact retained canonical bytes and
  verified digests.
- **Application-only size checks are rejected.** Observation, acknowledgement,
  and receipt messages must be bounded at the process transport before
  application decoding.
- **Receipt version 2 terminal and cleanup claims are superseded.** Receipt
  version 3 may state only pre-emission worker facts, subordinate cleanup, an
  intentionally open and excluded terminal-result channel, `ready_to_exit`,
  and the expected post-transmission disposition. The parent independently
  observes every actual terminal fact.
- **FIX4 authorization remains suspended.** Outcome B did not produce the
  complete source-frozen configured-owning-path evidence or revision-4
  campaign required to restore implementation authority.

Historical revision-2 and revision-3 evidence above is not rewritten as if it
used the corrected protocol or campaign authority.

### Immutable Canonical Evidence

The revision-4 candidate test-support model uses
`PreparationAttemptExpectations`, `ResourceBaseline`,
`PreparationObservation`, `PreparationObservationAcknowledgement`,
`PreparationTerminalReceipt`, `PreparationSubordinateCleanup`,
`PreparationExpectedDisposition`, and `AcceptedPreparationEvidence` are
frozen, slotted typed values with no mutable container fields. Constructors
copy and validate caller-owned mappings, and public projections are detached.

The parent retains exact canonical frame and ACK bytes, their complete typed
values, and verified digests. Independent state-owned byte anchors bind the
construction authority, accepted frame, accepted ACK, complete accepted
evidence tuple, and parent freshness authority to the values accepted at each
transition. Receipt validation binds its typed baseline and exact canonical
bytes to those retained frame, ACK, scope, generation, run, attempt, and
observation authorities. Reconstructing from retained bytes must produce the
same typed values and digests at every dependent transition; coherent
whole-object substitution is rejected.

### Receipt Version 3 And Terminal Ownership

The candidate receipt version 3 is canonical ASCII JSON bounded to 65,536
bytes. It repeats
the exact accepted run, attempt, scope and generation digests, resource
baseline, frame and ACK digests, observation interval, and ordered local
completion times. Before emission it may state only:

```text
completion state = ready_to_exit
expected disposition = normal zero exit after receipt transmission
subordinate readers = 0
subordinate database connections = 0
subordinate descendants = 0
subordinate descriptors = 0
subordinate threads = 0
result channel = open for terminal receipt and excluded from subordinate cleanup
```

The parent exclusively observes actual exit code, signal, process-tree
settlement, descendants, worker connections, readers, threads, descriptors,
and channels after receipt transmission. Any mismatch with the expected
disposition refuses the attempt.

### Bounded IPC Contract

The private POSIX test protocol bounds observation messages to 4,096 bytes,
acknowledgements to 2,048 bytes, and receipts to 65,536 bytes with one custom
fixed-header/body reader over the `Connection` descriptor. A parent-monotonic
deadline covers the complete header and body. The reader admits only the
four-byte or documented extended header, rejects a declared length above the
message-specific bound before body allocation, reads exactly that body, and
then requires one-shot channel EOF before success.

Overflow, timeout, zero length, EOF before a message, partial header, partial
body, sender exit during a frame, trailing or second-message data, receiver
close, or application-decoder rejection refuses the attempt and closes the
channel. Held-open partial-header and partial-body processes prove that the
deadline covers the whole frame rather than only initial readability.
Platforms without the required descriptor/select boundary refuse explicitly;
the phase does not claim that this private POSIX prototype is the FIX4
cross-platform implementation.

### Observed Campaign Authority

Campaign flow is exactly:

```text
exercise case
→ observe result and cleanup
→ compare with a separate exact expectation
→ serialize only the observed result
```

`ObservedPreparationCaseResult` contains the actual first causal category,
source boundary, ordered secondaries, release decision, terminal state,
process exit or signal, process-tree settlement, connection, reader, thread,
descriptor/channel counts, derived cleanup result, message counts, attempt,
generation, timing, validity, and optional owning-path identity. Expected
categories are never serialized as observations.

### Revision-4 Evidence And Lease

Iteration 6 froze 32 exact source hashes and a 702-record design before final
selection work. The required all-or-nothing configured report was not
completed. After two invalidated SCALE14 observer-first attempts under
concurrent load, the final authorized launcher completed all ten SCALE14
executions and two SCALE23 executions. SCALE23 invocation 03 then failed closed
with `backend_observer_failed` first, followed by `lifecycle_incomplete` and
`event_transport_eof`, while unrelated APG tests overlapped the run.

The overlap prevents attributing the failure to a specific source defect, but
the no-further-rerun boundary leaves no complete 40-execution configured report.
No partial report was published, and the 702-record revision-4 campaign was not
started. Prior complete runs remain invalidated and contribute no selection
evidence.

Revision 4 therefore produced no accepted maxima and no accepted lease
derivation. The predecessor's 1,450 ms lease and 5,000 ms attempt, 10,000 ms
total-preparation, 100 ms transfer, 650 ms final-release, and two-attempt values
remain historical constraints; FIX2 did not independently revalidate or
authorize them for production implementation.

### Deferred SCALE28-FIX4 Contract After FIX2

SCALE28-FIX4 remains prohibited. SCALE28-ADR2-FIX3 must first obtain complete
source-frozen configured-owning-path evidence and a complete revision-4
campaign, resolve or bound the observer-lifecycle failure, and independently
derive the lease and architecture values.

If a later Outcome A authorizes FIX4, its candidate contract remains the
retained hybrid with deeply immutable typed evidence, exact canonical bytes and
digests, bounded observation/ACK/receipt reads, receipt version 3, parent-owned
actual terminal facts, exact subordinate-cleanup semantics, and the existing
process-group, Job Object/refusal, observer, causality, ownership,
atomic-release, and cleanup authorities. No lease or timing value is selected
by this Outcome B.

### Corrected TEST-COV5C Contract After FIX2

The existing independent qualification bar remains. TEST-COV5C additionally
requires 50 mutation-resistance black-box cases, 30 actual bounded-IPC process
matrices, 20 receipt-v3 terminal-claim matrices, 40 actual configured owning-
area executions, 100 actual-category-versus-expected checks, 30 frame/ACK
passes, 50 corrected-age passes, 100 stale-checkpoint permutations, two
reacquisition generations per supported case, and zero selected-scope expected
failures or quarantines.

TEST-COV5C has not begun. SCALE29 remains prohibited until TEST-COV5C Outcome A
is committed, pushed, fetched, synchronized, clean, and independently approved.

## SCALE28-ADR2-FIX3 Isolated-Host Qualification Disposition

SCALE28-ADR2-FIX3 retained iteration 6 without changing any of its 32 frozen
protocol, transport, state-machine, campaign, test, owning-path, or private
prototype sources. It acquired a clean 90-second interval, started an
independent host-contention monitor outside product causality, and ran the exact
all-or-nothing configured launcher.

The initial attempt completed ten SCALE14, ten SCALE23, and eight SCALE28
executions. SCALE28 invocation 09 then refused publication with
`ambient_client_detected` first, followed by `lifecycle_incomplete`,
`resource_reader_unavailable`, and `terminal_resource_unavailable`. External
pytest and APG workloads had begun before that failure and remained active at
its first causal timestamp. The attempt is therefore invalidated host-
contention evidence, not a source-defect reproducer.

After another clean 90-second interval, the sole authorized replacement was
invalidated when external pytest and APG activity began before configured
completion. The candidate was then cancelled through its owned cleanup path.
No product failure from the replacement is claimed, no third attempt is
authorized, and no partial configured report is accepted.

FIX3 therefore selects Outcome C. It does not revise the hybrid architecture,
immutable canonical evidence, receipt-version-3, bounded-IPC, parent-terminal,
or observed-result requirements, but it also does not accept revision 4. The
702-record campaign did not run, no valid maxima or lease were selected, and
the historical 1,450 ms, 5,000 ms, 10,000 ms, 100 ms, 650 ms, and two-attempt
values were not revalidated. SCALE28-FIX4, TEST-COV5C, and SCALE29 remain
prohibited pending a decision on a dedicated qualification host, VM,
scheduling window, or isolated execution environment.

## SCALE28-FIX4 Implementation

The operator superseded FIX3's pre-implementation dedicated-environment
prerequisite without changing its confounded evidence. FIX4 implements the
retained hybrid architecture: one spawn-context worker owns only bounded slow
resource preparation, while the parent retains the continuous observer,
TEST-COV4 causality, parent-monotonic freshness, final ownership proof, actual
terminal facts, atomic child release, publication, and reconciliation.

The production protocol uses deeply immutable canonical request, observation,
acknowledgement, resource-baseline, receipt-version-3, subordinate-cleanup,
disposition, deadline, and accepted-evidence values. Observation,
acknowledgement, receipt, and failure frames are bounded before allocation.
Receipt version 3 contains only pre-emission worker facts; the parent
independently owns exit, signal, process-tree settlement, channel closure, and
terminal resource facts.

The frozen private policy is 1,800 ms per attempt, 4,100 ms total preparation,
150 ms acknowledgement, 300 ms receipt, 300 ms settlement, 100 ms transfer
reserve, 800 ms freshness, 600 ms final release, and two attempts. The complete
selection campaign retained every valid observation and stayed below the
5,000/10,000/650/100 ms and two-attempt architecture caps.

All ten stalled-bootstrap and six timeout/cancellation expected failures and
all four configured owning-path quarantines pass normally. Focused,
configured-owning-path, mixed, ordering, mutation/IPC, fresh-runtime, and three
complete repository gates pass without timeout retuning, protected access, or
product-contract drift.

FIX4 selects Outcome A. TEST-COV5C must now independently qualify the real
implementation without production-source changes. SCALE29 remains prohibited
until TEST-COV5C Outcome A completes its commit, push, synchronization, clean
tree, independent review, and report closeout.

## TEST-COV5C Independent Qualification

TEST-COV5C qualified the pushed FIX4 implementation without production-source,
policy, timeout, lease, dependency, SQL, schema, or public-contract change.
Independent production-boundary tests covered canonical mutation resistance,
parent freshness and reacquisition, actual bounded process IPC, receipt-v3
worker settlement, actual Psycopg/PostgreSQL bootstrap and timeout hierarchy,
and fail-closed cross-platform containment.

The actual SCALE14, SCALE23, SCALE28, and SCALE28-FIX1 owning areas each passed
ten executions, including quiet and bounded unrelated-contention conditions.
Fifteen consecutive mixed campaigns, three fresh public rehearsals, one
prior-publication failure rehearsal, the 702-record qualification revision, and
four complete repository gates passed without source or policy change.

TEST-COV5C selects Outcome A. ADR 0044's hybrid authority remains accepted
without cap increase or clean-room prerequisite. SCALE29 is authorized as a
separate phase but was not begun by TEST-COV5C.

## SCALE28-FIX5 Post-Commit Review Correction

Post-commit review retains the hybrid isolated preparation worker and every
parent-owned final authority established by FIX4. It supersedes the observer
cancellation-failure close behavior and TEST-COV5C's technical Outcome A.

The FIX4 cancellation exception callback closed the observer connection while
the operation-owning thread could still be active. A failed cancellation
request did not establish operation settlement. FIX5 removes connection close
from that callback, records the cancellation request outcome separately from
operation settlement, preserves the source-created operation timeout as
primary, records cancellation limitation only as secondary evidence, and
allows only coordinated close after the operation owner clears in-flight
state.

TEST-COV5C's 702 records executed one preparation-request serialization and
deserialization operation under several cohort labels. They are request
round-trip stability repetitions, not configured-path, ordering, fault,
freshness, mutation, IPC, PostgreSQL, or cross-platform semantic authorities.
Its 100 reacquisition and 500 cross-authority counts repeated one case, and its
20 worker-terminal count repeated one successful handshake. The PostgreSQL
timeout loop alternated server timeouts with ordinary successful queries and
did not independently exercise client cancellation failure.

FIX5 replaces those claims with truthfully separated semantic groups. Its
close-under-use correction, 50 cancellation/close/settlement cases, 12 terminal
variants, 20 reacquisition combinations, 24 actual release-order permutations,
real server timeout, and real cancellation-limitation cases pass.

The frozen 40 ms exact-connection cancellation-request reserve does not
reliably produce successful client fallback on the disposable local
PostgreSQL boundary. In two bounded direct characterizations it succeeded 9 of
20 and 6 of 10 operations at 40 ms; the latter characterization observed 8 of
10 at 80 ms and 10 of 10 at both 120 ms and 160 ms. These measurements
characterize this environment only and do not select a new deadline.

SCALE28-FIX5 therefore selects Outcome B. The hybrid architecture remains
retained, but protected continuation and SCALE29 authorization are withdrawn.
TEST-COV5D proceeds in characterization mode; a later correction must establish
an accepted cancellation-request reserve or operation-isolation boundary and
then pass independent qualification.

## TEST-COV5D Characterization Result

TEST-COV5D independently preserves the FIX5 Outcome B boundary without
changing production source, dependency authority, deadlines, policy, or
diagnostics. Its typed source-frozen manifest, 100 distinct close-under-use
orders, 200 distinct source-causality schedules, 18 terminal claims, 36
reacquisition paths, real PostgreSQL cancellation cases, focused selection,
and complete repository gate pass.

Twenty additional operations under the unchanged default reserve produced 12
successful cancellation requests and 8 `CancellationTimeout` results. Thirty
real server timeouts and 30 real client fallbacks under an explicitly
test-owned decision-support reserve passed, but the latter are not product
default qualification.

TEST-COV5D therefore selects Outcome B. The exact remaining contract gap is an
evidence-sized product cancellation-request reserve followed by successful
default-policy client-fallback requalification. SCALE29 remains prohibited
pending SCALE28-FIX6 and a later independent Outcome A.

## SCALE28-FIX6 Request-Settlement And Caller-Budget Result

SCALE28-FIX6 adds one further close prerequisite without changing the selected
hybrid architecture: coordinated close now requires both operation settlement
and cancellation-request settlement. Operation settlement does not imply that
a timer-owned `cancel_safe()` request has returned.

The pre-registered 400/420/120/570 millisecond candidate passed isolated real
PostgreSQL fallback, server-timeout, cancellation-limitation, and settlement
cohorts. It was rejected when the configured hybrid path proved that the
remaining budget at later final-release operations could not contain the fixed
trigger and request bound after preceding work. The provisional default and
600 millisecond handoff were rolled back without tuning or restart.

The accepted 400/450/40/500 millisecond product default therefore remains
unchanged and unqualified. FIX6 selects Outcome B. A successor must model the
complete caller sequence, including the second ownership sample, before
selecting another tuple. The 600 millisecond final-release ceiling, 400
millisecond server floor, preparation caps, and two-attempt limit remain
unchanged. SCALE29 remains prohibited.

## TEST-COV5E Product-Default Characterization Result

TEST-COV5E freezes the pushed FIX6 source and independently retains separate
operation and cancellation-request settlement. Fifty new three-party
request/operation/close/terminal/readback schedules pass together with the
retained close, causality, terminal, reacquisition, PostgreSQL, and configured
path groups.

The current default remains unqualified. Its real request outcomes include
bounded timeouts under retained, quiet, and bounded-contention conditions, and
a 440 millisecond remaining caller budget compresses its client trigger to the
400 millisecond server floor. The rejected C120-420 candidate also requires
620 milliseconds after the mandatory sample gap, exceeding the retained
600 millisecond final-release cap.

TEST-COV5E selects Outcome B without changing this ADR's accepted hybrid
architecture or caps. SCALE28-FIX7 must model the complete final-release caller
sequence and select one reliable fitting product default before independent
qualification can reconsider SCALE29.

## Successor — ADR 0045 Final-Release Observer Authority Reconciliation

ADR 0045 (accepted 2026-07-25, Decision Category B) retains this ADR's hybrid
preparation-worker architecture and every preserved authority, and precisely
amends only the final-release deadline derivation and observer operation model.

This ADR's historical text is not rewritten. ADR 0045 supersedes exactly the
following, and nothing else here:

- the description of 600 ms as a final-release **ceiling** or **cap** in the
  SCALE28-FIX6 and TEST-COV5E sections above. The **650 ms final-release
  ceiling** selected in this ADR's "Final Release Ceiling" section remains the
  live architectural maximum; 600 ms is the SCALE28-FIX4 *selected
  implementation default* beneath it, as this ADR's own SCALE28-FIX4
  Implementation section records;
- TEST-COV5E's "required 50 millisecond two-sample gap" and its
  `570 + 50 = 620` final-release envelope, which omit four in-window steps and
  double-charge the cancellation-request reserve. Note that the 50 ms term in
  this ADR's "Final Release Ceiling" formula is a *transient settlement* budget,
  a different quantity from an inter-sample separation;
- within `ObserverDeadlinePolicy` only, SCALE28-FIX4's 40 ms
  cancellation-request bound and its `caller − reserve` client-trigger
  derivation.

Everything else in this ADR — the hybrid selection, the preparation worker,
receipt version 3, the observation and acknowledgement protocol, parent-monotonic
freshness, the preparation state machine, the two new final stable ownership
samples, TEST-COV4 causality, atomic parent-owned release, the 5,000 ms attempt
and 10,000 ms total preparation caps, the two-attempt limit, and the 650 ms
final-release ceiling — remains accepted and unchanged.

SCALE28-FIX7 is authorized under ADR 0045's frozen contract. TEST-COV5F is
required. SCALE29 remains prohibited.

## SCALE28-FIX7 Successor Result

SCALE28-FIX7 implemented ADR 0045's structural candidate while preserving this
ADR's hybrid preparation-worker architecture, freshness, final ownership,
terminal authority, atomic release, and 650 millisecond architectural maximum.

The candidate's first 30-operation product-default fallback cohort passed, but
the mandatory unchanged-candidate repeat produced a real
`CancellationTimeout` under the frozen 120 millisecond request bound. The
candidate was not retuned or accepted and was reverted after preservation as
an owner-private binary patch.

This result does not reopen this ADR's accepted architecture. It isolates the
remaining issue to ADR 0045's frozen cancellation-request reliability
assumption. TEST-COV5F proceeds in characterization mode, and SCALE29 remains
prohibited.

## TEST-COV5F Successor Result

TEST-COV5F preserved this ADR's hybrid architecture and independently observed
19 request successes and 11 bounded request timeouts in a new 30-operation
accepted-tree fallback cohort. Retained startup, settlement, causality,
terminal, publication, and cleanup evidence passed.

The remaining boundary requires an ADR/platform decision, not an architecture
rollback or local timeout retune. A successor must measure and select the
configured cancellation-request tail contract and its settlement authority
before production mutation. The 600 millisecond selected final-release window,
650 millisecond architectural maximum, and 400 millisecond server timeout
remain unchanged. SCALE29 remains prohibited.

## SCALE28-FIX10 Additive Outcome

SCALE28-FIX10 found no complete owner-private receipt for the corrected FIX9
patch. The patch digest, mode, and 23-path count exist, but its exact base and
receipt manifest are unproved. The phase therefore stopped before candidate
reconstruction, tracing, or production mutation.

This outcome does not change the preparation clock origin before worker spawn,
the 1,800/4,100 millisecond implementation policy, the 5,000/10,000
millisecond architecture maxima, or any evidence, freshness, IPC, receipt,
cleanup, or release authority. TEST-COV5J proceeds in characterization mode;
SCALE29 remains prohibited.

## TEST-COV5J Additive Outcome

TEST-COV5J independently froze the pushed FIX10 source, policy, receipt, trace,
causality, terminal, and qualification contracts. Its independently derived
37-event manifest confirms separate parent and worker clocks and the accepted
pre-spawn preparation clock origin.

Qualification remains Outcome B because the corrected candidate's exact base
and receipt manifest are unproved. No preparation component, dominant stage,
timing fork, or candidate cleanup is inferred. SCALE28-FIX11 owns complete
receipt reconstruction and critical-path attribution; SCALE29 remains
prohibited.

## SCALE28-FIX11 Additive Outcome

SCALE28-FIX11 derived the corrected patch manifest from bytes, resolved all
preimage objects, and found five nonidentical full base/result trees that
satisfy every unchanged apply constraint. The provenance result is
`nonunique_base`; no corrected candidate was executed.

Independent accepted-tree evidence also selects Fork B. The required
container-RSS reader had a 1,984.661 millisecond median and 2,035.099
millisecond maximum; the complete concurrent resource group had a 1,988.482
millisecond median and 2,147.613 millisecond maximum. Valid required work
therefore exceeds the selected 1,800 millisecond attempt policy while remaining
within this ADR's 5,000 millisecond architectural ceiling.

This ADR remains Accepted and unchanged. The implementation policy requires a
narrowly scoped ADR or operator decision before another candidate phase.
TEST-COV5K was not begun, protected SCALE remains paused, and SCALE29 remains
prohibited.

## SCALE28-ADR5 Additive Outcome

SCALE28-ADR5 resolved the Fork B implementation-policy question with
ADR 0047 (Accepted, Decision Category A). The selected implementation policy
beneath this ADR's unchanged architecture moves from 1,800/4,100 to
3,400/7,500 milliseconds: A = 3,400 is derived from the required
concurrent-resource allowance (2,200), serial SQL tail (200), spawn/import
margin (400), IPC margin (100), nested settlement bound (300), and
scheduling margin (200); P = 2·A + the 700 millisecond bounded
failed-settlement path.

This ADR's 5,000 millisecond attempt and 10,000 millisecond total
architectural maxima, two-attempt limit, pre-spawn clock origin, resource
ownership, subordinate deadlines, 800 millisecond freshness lease, and
600/650 millisecond final-release authorities are retained unchanged. The
worst-case preparation wall clock, 2 × (3,400 + 700) = 8,200 milliseconds,
remains inside the 10,000 millisecond total ceiling.

SCALE28-FIX12 is authorized under ADR 0047 as a fresh test-first semantic
reimplementation on current `main`; the nonunique corrected patch remains
excluded as implementation authority. TEST-COV5K remains mandatory before
SCALE29, and SCALE29 remains prohibited.

## SCALE28-ADR5-FIX1 Additive Outcome

SCALE28-ADR5-FIX1 amended ADR 0047 additively to close the selected
total-authority ambiguity. The value previously called the total preparation
timeout (7,500 milliseconds) was an attempt-start eligibility gate that
could expire before end-to-end preparation completed; it is superseded by
one true selected end-to-end preparation wall authority of 8,900
milliseconds — 2 × (3,400 attempt + 100 settlement tail + 100 parent-work
allowance + 700 failed cleanup) + 2 × 100 admission + 100 terminal
projection — containing both failed-attempt cleanups.

This ADR's 5,000 millisecond attempt and 10,000 millisecond total
architectural maxima are **not** amended. The amendment freezes a
SCALE28-FIX12 validation rule making the total maximum mechanically
enforceable (`derived_end_to_end_ms ≤ total_timeout_ms ≤ 10,000`); one
recorded consequence is that under two attempts and the retained 300
millisecond settlement bound the jointly feasible attempt timeout caps at
3,950 milliseconds — the derivation rule, not a maxima change, is the
binding constraint. The runtime-qualification status is corrected to Q2:
no stack may be called timing-qualified before TEST-COV5K Outcome A binds
a complete runtime-identity receipt. SCALE29 remains prohibited.

## TEST-COV5K-R1 Additive Outcome

TEST-COV5K-R1 created the required capable environment and passed every host
capability entry probe, but the first valid Group A observation found the
accepted R1 tip still selects the historical 1,800/4,100 millisecond
preparation policy. The required 3,400/8,900 policy and end-to-end
mechanical-enforcement rule remain assigned to the full SCALE28-FIX12
implementation contract.

Outcome B preserves this ADR unchanged. No qualification group after A ran,
no timing receipt was issued, and SCALE29 remains prohibited.

## SCALE28-FIX12-R2 Additive Outcome

R2 entered a capable exact-pinned environment and passed the complete
repository all-suite gate. Its separately mandated opening compileall command
then selected two deliberately malformed tracked extraction fixtures and
failed before source freeze, red tests, or candidate mutation.

Outcome B preserves this ADR's hybrid architecture and every clock, state,
freshness, IPC, cleanup, and release authority unchanged. No qualification
receipt exists, and SCALE29 remains prohibited.

## SCALE28-FIX12-R2-FIX1 Additive Outcome

The retry implements the accepted total-authority contract. The selected
3,400 millisecond attempt and 8,900 millisecond total values are mechanically
linked by the named SIGTERM-join, parent-work, admission, settlement, transfer,
cleanup, and terminal-projection allowances. The independent 5,000/10,000
architectural maxima remain unchanged.

Two attempts remain the maximum. Attempt two is unavailable until attempt one
settles and cleans; cleanup limitation prohibits retry; both possible failed
cleanups remain inside the one total wall; no third attempt or overlap was
observed. The active-boundary idle clock now begins only after the first real
lifecycle event, so pre-event startup delay cannot be mislabeled as between-
boundary inactivity. The complete acceptance campaigns and repository gates
pass. Qualification remains Q2, TEST-COV5K-R2 remains required, and SCALE29
remains prohibited.
