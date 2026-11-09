# CLOE worker custody contract v1

Phase: `REPOMAP-CLOE-RESOURCE-GOVERNANCE3`. Source parent:
`efdb5286b8a0bc40e242cdfc89a37b99dec89e18`.

Status: parent-selected for bounded source implementation. Three independent
design checkpoints informed this selection. The third left a narrowed B1
finding; the parent resolves it below by specifying provenance and explicitly
migrating the fake unit models. That correction has not received a further
independent design review. Fresh independent resulting-source review and exact
scoped proof are mandatory before publication. No readiness is claimed here.

## Scope and decision

Handle exceptions escaping the worker's own guarded Python supervision after
the managed launch returns. Cover native default, canonical facade and ticketed
launches; keep opt-in usage behavior and its compatibility entry. Ticketed
coordinator coverage means synchronous exceptions in its executor thread.
Main-thread cancellation or signal delivery is not changed (X9).

No dependencies, images, runner/admission classes, worker frames, CLI/MCP
fields, default usage collection, global limits, live/installed mutation or
complete local suites/coverage are selected. Ordinary W7 implementation is
authorized by the current task and parent disposition, not by this document.

## Native provenance and factory matrix

Capture the original launch function and Popen class at import. Resolve the
effective launch callable from the explicit argument or current module global.
Canonical intent means that callable is the captured original function.
Preserve runtime-patched Popen forwarding so fake unit tests cannot unexpectedly
launch a real process. Record genuine native launch provenance only when the
original Popen factory created an original Popen instance and owned boundary.

| Mode | Effective factory / Popen | Abnormal entry | Native proof eligible |
|---|---|---|---|
| default, explicit None | original / original real child | generic outcome | yes |
| facade, explicit original | original / original real child | generic outcome | yes |
| ticketed, explicit None | original / original real child | generic outcome | yes |
| default | patched/custom callable | incumbent injected behavior | no |
| default | original / patched or fake Popen | no new native handler | no |
| usage | original / original real child | interrupt_cleanup shim | yes |
| usage, explicit None | patched module callable or fake object | incumbent T0 shim simulation | no |
| usage | explicit injected callable or ticket | reject before launch | no |
| ticketed | any explicit callable | reject before launch | no |

Both canonical intent and recorded genuine native provenance are required for
new default/ticketed custody and normal-path ticket proof. Claimed pids, return
codes or a None argument do not establish ownership. A real POSIX group signal
from ManagedProcess must be refused without native provenance. Dummy boundary
methods may simulate calls in T0 tests; they never constitute native evidence.

## One selected wait owner

On supported POSIX original-Popen launches install one wait4 reaper, including
default launches. Retain rusage and the post-reap usage probe only when
collect_usage=True. Default resource_usage stays None. Preserve the old
ChildUsageReaper import name as an alias/compatibility entry.

States are LIVE, REAPED and STATUS_UNKNOWN. Record the actual owner-returned
status and set Popen.returncode using waitstatus_to_exitcode. A prior foreign
return code, ECHILD or wrong returned pid fails closed with worker_status_unknown.
An in-flight marker makes a lost post-wait record unknown; it never invents 0.
Existing usage reason vocabulary stays closed. A later foreign reap after an
interrupted syscall can remain imprecisely labelled not_observed (X8).

ManagedProcess.reap_state returns live/reaped/status_unknown without reaping.
Without the POSIX reaper, retained returncode yields live/reaped under the
existing platform wait owner. Quiet poll/wait used by cleanup suppress only
worker_status_unknown; ordinary boundary errors retain their documented behavior.
Normal protocol supervision keeps the raising poll/wait API.

## Group signals and cleanup

The POSIX probe returns MEMBERS, EMPTY or UNPROBEABLE (EPERM). Legacy/Windows
boundaries without group_state map tree_exists True/False to MEMBERS/EMPTY;
ordinary errors propagate. Windows qualification remains open.

Signal only the exact open owned group/job. Never signal an individual pid or
after release. A live known native leader or fresh MEMBERS probe permits the
owned signal; EMPTY/UNPROBEABLE does not. Probe-to-signal reuse remains X1.

ManagedProcess.cleanup must handle STATUS_UNKNOWN without calling a raising
poll that prevents settlement. While genuinely live, retain incumbent bounded
TERM/wait/KILL behavior. Independently probe members, kill the owned group when
permitted, and bound the wait for absence. Attempt boundary close in finally.
Return clean only with known owner status, empty group and successful release.
Unknown status is never clean. A close failure is unproven. A closed boundary
is never signalled again; a second cleanup may use retained earlier facts.

## Guard and abnormal settlement

Guard ticket bind/validation, stream assertions, reader start, protocol loops,
normal settlement and result/observer delivery after launch returns. Keep one
algorithm settle_abnormal_exit and a frozen CustodyOutcome with status-known,
returncode, group-empty, release, readers-joined, streams-closed, proven/reason
and the existing immutable UsageSettlement projection.

The algorithm shares a monotonic deadline of twice the existing termination
grace: kill first under ownership rules; bounded owner wait; cleanup with zero
TERM grace and at most half remaining budget per incumbent kill wait; close
pipes; join readers with remaining time. Successful proof requires every fact.
Ordinary secondary failures become path-free/type-only notes on the primary.
A guarded second BaseException is noted, remaining work is abandoned except
guarded stream-close attempts, and custody is unproven. Re-raise the original
exception object. X2/X7 prohibit hard wall-time or absolute interrupt guarantees.

For collect_usage=True, execution still calls its module-global interrupt_cleanup
entry. That shim delegates to the shared algorithm and returns UsageSettlement,
preserving current usage-A lifecycle owner labels and existing observer validation.
Default/ticketed native calls use the full outcome. No new observer API is added.
Observer settlement remains once-only; secondary callback failures cannot mint
success, replace the primary or cause a second notification.

## Ticket custody

Bind custody to the real process before subsequent bind validation can raise.
Every release must require the exact registered ticket and launch.process is
process. Abnormal release additionally requires native owner status and proven
group/reader/stream/release facts. Pop only the matching in-memory registration;
retain no result capable of earning fencing proof. Never consume the durable
supervisor registration digest here. Unproven custody retains registration.
Normal reaped-result recording requires genuine native provenance and actual
selected-owner status, not Popen.poll or a fabricated passive returncode.

Keep coordinator reconciliation_required and publication truth. Committed or
commit-unknown publication is not relabelled as an ordinary failed publication.
Root-removal and durable retention boundaries remain incumbent; X5 is not solved.

## Unit model migration and ownership

Update protocol_usage_observation's _Process/_InterruptedProcess and related
interrupt-cleanup fake models to implement the new process-free simulation
surface: reap_state from their simulated returncode, _wait_quiet calling their
simulated wait and recording integer status, and group_state from tree_exists.
For a simulated LIVE leader kill-first still precedes cleanup even if the fake
tree probe says empty. Their -9/proven callback assertions remain T0 simulations,
with native eligibility false. Do not add a production duck-type fallback or
claim these fake callbacks as kernel proof.

Keep execution.interrupt_cleanup patch tests on the opt-in shim. The old
test_default_supervision_never_calls_the_opt_in_handler uses a patched module
launch wrapper; rename it to characterize that noncanonical wrapper, remove
the obsolete _reaper-is-None assertion, and assert no default usage is retained.
New governance3_owned_launch_matrix and governance3_custody_dispatch unit owners
cover positive canonical row-1 wiring and every negative factory/Popen cell.
T0 spies may simulate a predicate but never establish native proof; M fixtures
below prove actual canonical/default/facade behavior.

Add focused owners for reaper states/in-flight loss, quiet unknown-status
cleanup, deadlines/secondary failures, exact ticket mismatch/refusal and primary
identity. Preserve adjacent protocol, process supervision, usage and fencing
contracts. New/modified files stay within 400 lines; new owners target 350.

## Required real integration proof

Use the existing nine-argument refresh_worker command, valid sealed capability
and disposable refresh/PostgreSQL fixtures. These maintained worker nodes remain
ordinary M outside the portable usage command population. Existing usage-A
declarations, command admission, receipts and validators remain unchanged.

- Default and canonical facade: after real hello, an extra job_context key
  causes actual invalid_job_context before job_start is sent. Require exact
  group ESRCH, known reaped status, released boundary, closed streams/readers.
- Primary/secondary exceptions: inject Python BaseException at established
  parent seams while supervising the real maintained child; preserve identity.
  An interrupted cleanup remains unproven, with exact test-finally cleanup.
- worker_input_closed: after hello, terminate/wait the owned maintained child
  through its owner, then let the real job_start write/flush encounter the
  closed pipe. Assert the real ProtocolError and settled/closed native facts.
- Ticketed synchronous failure: use existing run_refresh_worker/registration
  fixtures; prove exact-child settlement, no earned reaped-result proof and
  the durable digest unconsumed. The coordinator case must record real
  reconciliation_required and preserve publication truth.
- Unknown status: after real hello, deliberately foreign-reap that exact child
  as fault injection, then invoke its real owner poll from the supervising
  thread inside an existing job-start seam. Actual kernel ECHILD must propagate
  through protocol abnormal settlement and ticket handling. Require closed
  boundary, false proof, held registration and no reaped/fencing result. A
  direct manual-owner variant may supplement it but cannot replace this wiring.
- Existing usage/grandchild cases regress the same shared algorithm and group
  boundary under their unchanged A/M roles. They give no new M coverage credit.

Actual execution and population reconciliation are required. Unexpected admission
refusal is a blocking proof gap; do not relabel M/A or modify policy. Each new
runtime branch needs meaningful measured M proof where feasible; keep pure
invalid-value matrices in unit tests. No local coverage claim is possible.

## Decisions, deferrals and residuals

D1 selects the guarded worker-own scope above. D2 preserves primary exceptions
for guarded secondary failures, superseding ADR0173 B1. D3 fails closed on
unknown status. D8/D9 retain incumbent attempt-root handling and held unproven
registrations without a new retention/sweep API. D10 defers OS-delivered SIGINT
to a new parent helper and SIGCHLD-ignored-parent scenarios; they are not selected
acceptance tests, and must appear as unexecuted deferrals in the phase exit.

- X1: POSIX group reuse between probe and signal.
- X2: escaped descendants may retain pipes; native calls/stream close are not preempted.
  After a second interrupt, a live child may leave a reader holding a buffered
  stream lock, so closing that stream may wait for child exit. The SystemExit
  fixture relies on the maintained worker exiting when its stdin closes.
- X3: Windows remains unqualified.
- X4: worker-side capture still performs discarded discovery hashing.
- X5: surviving writers may recreate deterministic attempt roots; same-authority
  adoption and orphan pruning remain unproved. No harmlessness claim is made.
- X6: normal or abnormal unproven launches may retain registrations/zombies;
  no deferred sweep/relaunch contract is selected.
- X7: asynchronous exceptions between guards or during note delivery can escape.
- X8: interrupted-wait usage reason precision is limited as described above.
- X9: coordinator main-thread interrupt does not enter its executor's handler;
  interpreter-exit join behavior remains a separate runtime precondition.
- X10: the narrow post-Popen/pre-managed-return window is outside the protocol guard.
- X11: CPython finalizers may later reap an unticketed unproven child after its
  owner record is released; single-owner claims apply while that record is held.
- X12: a wrapped Popen factory returning a real child is non-native under this
  contract. Group signals are refused and the injecting caller keeps cleanup
  custody. No current coordinator caller uses that factory pattern.
- X13: original launch/Popen identities are captured at first import. Importing
  under a preexisting Popen-class replacement is outside native qualification.

Rollback is source reversion; no migration/configuration change. Final acceptance
requires scoped unit/containerized integration, exact clean enrollment of new
quality owners with all existing policies and debt ceilings preserved,
fresh independent resulting-source review, final campaign binding and hosted
qualification. Hard 85/85 and 80/80 floors and desired 87/82 margins stay unchanged.
