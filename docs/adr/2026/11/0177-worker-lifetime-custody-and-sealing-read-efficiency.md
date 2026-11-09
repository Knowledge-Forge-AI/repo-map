# ADR 0177: Worker lifetime custody and sealing read efficiency

Status: accepted by the parent for bounded source implementation; proof pending.
Date: 2026-11-09. Phase: `REPOMAP-CLOE-RESOURCE-GOVERNANCE3`.
Source parent: `efdb5286b8a0bc40e242cdfc89a37b99dec89e18`. Public base: `5ad00d162ad8a04430874275246a53227578c533`.

## Context

The source parent cleans interrupted workers only on the opt-in usage route.
Default and ticketed exceptions can leave a child alive. Registration/reaping
must not fabricate success from ECHILD or drop durable reconciliation authority.
Sealing also repeats discovery hashing/classification whose results never enter
its snapshots; existing-object puts compare and then read the target again.

CI134 passed all unit/integration/system cases but failed integration coverage
by one branch and two setup downloads with HTTP504. It is not whole-candidate
qualification. The current roadmap-continuation request permits ordinary W7
source advancement while fresh combined qualification remains pending.

## Decision

Implement two epics under the [governance3 contract](../../../specs/cloe-resource-governance3-v1.md).

1. Worker custody follows the [worker contract](../../../specs/cloe-worker-custody-v1.md).
   Canonical intent is the effective original launch callable, including the
   canonical facade. Genuine original-Popen/boundary provenance is separately
   required for new native cleanup, real POSIX signals and ticket proof. Fakes
   and custom factories cannot establish native ownership. One selected wait
   owner fails closed on unknown status. A shared abnormal-settlement algorithm
   preserves the opt-in interrupt_cleanup shim and its current strict A owners.
   The scope is exceptions escaping guarded worker-own supervision after launch
   returns; ticketed coordinator coverage means synchronous executor-thread
   exceptions, not main-thread cancellation (D1/X9).
2. Capture-only sealing scans remove unused discovery/classification reads.
   Ordinary discovery stays unchanged. A graph-local leaf owns the canonical
   path expression. The collision branch combines comparison and verification
   while preserving descriptor identity, version, digest, size and temporary
   content evidence. New-object verification and the second content scan stay.
   Real read totals become4S+C+m+m_c+r and the lower bound4S+1; plan factors4/1/3.
   Closed report fields remain, with truthful zero reader values and the
   classification limit applies=false.

Connected Local/Server/mixed first-use and refusal proof is part of this batch.
No dependencies, images, test-runner/admission classes, protocol frames, DDL,
roles, global limits, default usage collection or installed/live mutation is
selected. Source implementation authority comes from the current task and
parent disposition; this ADR allocates no builds, native campaign or remote action.

## Parent dispositions and review state

Three independent design checkpoints informed the decision. E2 had no blocker
in the full final review. The E1 delta review resolved B2/B3 in substance but
left a narrowed B1: fake-model compatibility, an obsolete Scope predicate and
missing row-1 ownership tests. The parent resolves those by the explicit mode
matrix, native signal guard, test-model migration and named positive/negative
owners in the worker contract. The parent also restores concrete native cleanup
postconditions, actual-kernel unknown-status protocol wiring, worker_input_closed
proof, residuals and M-leg coverage ownership.

These final parent corrections have not received a further independent design
review. They are authorized for source implementation with a publication hold:
fresh scoped proof and independent review of the resulting code must challenge
them. No consensus, BLOCKERS:NONE review or source-readiness claim is inferred.

D1 selects the narrow guarded worker-own scope above. D2 preserves primary
identity across guarded secondary failures, superseding ADR0173 B1. D3 fails
closed on unknown owner status. D4 accepts documented sealing race-category
shifts. D5 selects truthful counts/factors. D6 migrates tests to the real sealing
scan and amends ADR0173 P9 for sealing. D7 selects evidence-preserving single-pass
collision verification. D8/D9 defer new retention/sweep APIs. D10 explicitly
defers the new OS-delivered SIGINT-parent and SIGCHLD-ignored-parent scenarios;
they must be recorded as unexecuted, not claimed qualification.

## Residuals and limits

Corrective source review also closes the post-lstat FIFO open window: both
metered and shared incumbent stable-capture readers use `O_NONBLOCK` where
available before their identity/type checks. The shared reader serves worker
capture too; worker discovery/classification and regular-file content identity
remain intact. Native device calls are not generally preempted. Diagnostic
note delivery is best-effort: ordinary diagnostic failure cannot abandon
cleanup, and a second BaseException still selects the close-only policy.

- X1: POSIX group reuse between probe and signal.
- X2: escaped descendants/pipes and non-preempted native calls or stream close.
  A second interrupt with a live child can leave buffered-reader close waiting
  for child exit; the maintained SystemExit fixture exits on stdin closure.
- X3: Windows remains unqualified.
- X4: worker-side discarded discovery hashing remains.
- X5: surviving writers may recreate deterministic attempt roots; same-authority
  adoption and orphan pruning remain unproved. No harmlessness claim is made.
- X6: normal or abnormal unproven launches may retain registrations/zombies.
- X7: asynchronous exceptions between guards or during note delivery can escape.
- X8: interrupted-wait usage-reason precision remains limited.
- X9: coordinator main-thread interrupts do not enter executor supervision;
  interpreter-exit joining is a separate runtime precondition.
- X10: the post-Popen/pre-managed-return window is outside the protocol guard.
- X11: CPython finalizers can later reap an unticketed unproven child after its
  owner record is released; single-owner claims apply while that record is held.
- X12: wrapped Popen factories returning real children are non-native; group
  signals are refused and the injecting caller retains cleanup custody.
- X13: native identity capture assumes an unpatched Popen class at first import.

The deadline is cooperative, not a hard wall-time guarantee. Full W6/W7,
physical PostgreSQL/hard RSS governance, native Windows, installed/release/main
acceptance and deferred startup-timeout work remain open.

## Alternatives and rollback

Retaining the current default leak was rejected. Removing integrity readback
or the second content scan was rejected. A production algorithm fork when tests
patch a symbol was rejected; tests migrate to the actual seam. New runner-policy
classes are unnecessary for the selected maintained-worker proof route.
Source reversion rolls back the change; stored formats/configuration are unchanged.

## Acceptance

Require exact scoped unit and real containerized integration with --no-coverage,
unchanged quality/debt/receipt/coverage gates, fresh independent resulting-source
review and final binding before one staging milestone publication. Hosted CI
owns whole-population coverage and native qualification. No design-only push,
main/tag/release or automatic retry follows this record.
