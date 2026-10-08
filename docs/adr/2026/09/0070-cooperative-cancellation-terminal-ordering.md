# ADR 0070: Cooperative Cancellation Terminal Ordering

## Status

Accepted for the FIX40 Slice17 publication repair; qualification pending.

## Date

2026-09-23

## Context

The coordinator and worker communicate over independent pipes. Sending cancel
does not imply that progress already written by the worker has been consumed.
The portable worker previously stopped its input reader before terminal emission,
which could discard a complete cancel frame already in its input pipe. Terminal
selection also preceded reader settlement.

## Decision

Preserve protocol version 1 and its existing message schemas. Allow validated
progress and heartbeat frames while awaiting cancel acknowledgement. They do not
acknowledge cancellation or extend its deadline. Duplicate cancel, unsolicited
acknowledgement, malformed messages and post-terminal messages remain errors.

When cancellation is already requested at job dispatch, send job_start followed
by cancel in one flushed batch. Serialize cancellation commitment with terminal
acceptance in the parent. A terminal already accepted wins over a later request.

On worker completion, stop further waiting for input, drain bytes already
available to the reader, and settle both protocol threads before selecting the
effective terminal. A valid cancel received through that boundary overrides the
workload outcome. Incomplete or invalid pending input fails closed. The reader's
empty nonblocking read after stop defines the worker terminal decision boundary;
a cancellation sent later may legitimately race with a completed result.

No new handshake, schema, deadlines, sleep, execution authority or artifact
publication behavior is introduced. Process exit, supervision and cleanup remain
independent requirements; a terminal frame alone does not establish success.

### Publication-safe cancellation disposition

The pending-input override applies to unpublished semantic work. For the refresh
publisher, the durable coordinator contract governs publication independently:
cancellation may stop work at the existing pre-publication gate, but cannot
override a matching committed publication. Such an attempt succeeds with the
existing bounded `cancellation_not_applied` diagnostic. An uncertain publication
requires reconciliation; terminal cancellation requires proved absence or
rollback. Refresh input checks use bounded nonblocking reads at safe points and
defer consumption during the publication-critical section. Protocol version 1,
the flushed start/cancel batch, and accepted-terminal ordering remain unchanged.

The pure reconciliation model accepts keyword-only `absence_proof`, defaulting
to `unproved`. `fenced_absence` represents an already successful durable and
file-gate closure of both job and attempt as `not_started`; it issues no
`WorkerFencingProof` and grants no store mutation authority. A `rolled_back`
model input represents already validated rollback without uncertain job or
attempt evidence. Absent markers and stored `not_started`/`prepared` labels
alone leave requested cancellation unresolved. Non-cancellation retry policy
is preserved. Receipt conflicts quarantine; matching commits still win.

### Recovery and framing limitations

A cancellation with uncertain publication retains the current attempt, lease
and publication evidence. The bounded existing recovery route is replacement
coordinator startup after prior singleton turnover and graph lease expiry:
`recover_startup` re-reads publication, installs the durable graph fence under
currency locks, consumes a one-shot proof to close the file gate, closes both
durable publication states, and reconciles using that earned closure result.
Matching receipt readback takes precedence throughout. Unavailable readback or
failed fencing leaves reconciliation pending. Same-owner periodic recovery
cannot earn replacement-owner fencing while its lease stays active; progress
can therefore wait for an operator-managed restart. Automatic restart, online
recovery redesign and unfenced lease release are outside this repair.

Nonblocking buffered `readline` can return a partial frame before its newline.
At the decision boundary, complete pending cancel is accepted; no pending bytes
or EOF after a valid start permits normal work. Fragmented, unterminated or
malformed pending bytes fail closed with exit 2, without a terminal success or
cancellation and without opening the publication gate. A logically valid frame
whose remainder arrives later is still refused at that boundary. This is the
existing incomplete-input rule and an availability limitation, not proof that
pipe frames cannot split. Readers and descriptors remain owned by their process
or fixture; no sleep, extra timeout or framing/schema expansion is introduced.

### FIX41 natural-completion correction

After accepting a terminal, close coordinator input and allow natural process
exit within the remaining existing overall process deadline. Terminal receipt
does not restart that budget. Termination grace bounds escalation and cleanup,
not normal interpreter teardown. Expiry still synthesizes `completion_timeout`;
nonzero exit, protocol errors and unsettled process/thread cleanup remain
fail-closed, with the original terminal retained separately. No new deadline
setting or Run25 fixture relaxation is introduced.

An accepted terminal also ends cancellation polling. A later cancellation does
not shorten natural completion; a child that remains alive can retain its slot
until the existing overall process deadline expires, then escalation applies.

## Verification

Deterministic subprocess contrasts cover deferred input consumption, in-flight
progress, cancellation during materialized work, late cancellation, malformed
cancel and normal success/failure. Existing completion, capability recovery and
URL-userinfo privacy controls remain required. Full integration is reserved for
the dispatcher closer after independent review.
