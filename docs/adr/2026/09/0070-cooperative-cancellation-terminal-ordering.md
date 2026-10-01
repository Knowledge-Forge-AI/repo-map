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
