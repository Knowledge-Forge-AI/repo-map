# ADR 0143: Unpublished staging campaign ordinal reconciliation

## Status

Accepted parent reconciliation under the standing roadmap publication instruction.
This transfers the unspent ADR0142 allocation; it adds no build or publication.

## Date

2026-11-03

## Context

The reviewed implementation commit `7120be2c6317d50d70d42d36c0452041e204efe5`
has not been pushed. Its exact-commit report and source evidence remain intact.
Fresh remote preflight found that three Dependabot pull requests consumed
qualification workflow ordinals110–112 while public staging remained at
`e012f0180b7e2b85112e46a361fc4cd7fcd66472`. Each failed promotion policy;
the system/native jobs were skipped and no application start occurred.

## Decision

Preserve the implementation commit and add a forward metadata correction for
one ordinary staging synchronization, expected CI113 attempt1. Revoke the
unpublished CI110 nonce/reservation and issue fresh candidate-bound authority,
nonce and reservation against the observed ledger. Append a zero-slot
supersession; never rewrite the old reservation or consumption prefix.

The same single native AMD allocation remains: at most start26 after25 actual
starts, cumulative/per-platform26. The three unrelated policy failures add zero
application starts. Legacy0-total/1-per-platform STOP fields remain unchanged.
The remote event's `before` remains public staging e012, although the local
correction commit follows7120. No history rewrite or additional trigger follows.

Require owning scoped unit/containerized integration checks without coverage,
current static/privacy/hygiene evidence and independent resulting-state review.
Before the sole push, query the identified qualification workflow's current
counter rather than treating all repository workflow counters as interchangeable.
If another event invalidates the binding, refuse publication and reconcile it.

## Boundaries

No product/runtime/D12 context, SDK, dependency, workflow, threshold, scientific
criterion, model/corpus/query/gold, main/tag/PR state, complete local suite or
local application/SDK build change. Existing calibration, explicit formatting
bridge and measured limits remain immutable. No automatic retry or additional
application start, model run or publication is granted by this reconciliation.
