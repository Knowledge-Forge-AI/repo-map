# ADR 0167: Projection admission census repair and CI128

## Status and date

Accepted conditional retry, 2026-11-07, under the operator's current manual
instruction: “ci failed try again”. This selects one fresh campaign after
CI127's executed failure; it does not reuse or automatically rearm ADR0166.

## Context

CI127 attempt 1, run 42398530315, failed one unit assertion for staging
`85f3ea6ba891c4db54acf06f3cfbb8700c51137c`. The other eight jobs passed.
The source-backed resource-report admission was valid and static lineage
enforcement passed, but the unit test's explicit `FORWARD_ADMISSIONS` list
ended at resource-governance. Its exact registry-tail comparison therefore
rejected the new resource-report phase.

The unchanged projection owner reproduced one failure and 48 passes. Adding
the single reviewed `REPOMAP-CLOE-RESOURCE-REPORT1` admission yielded 49 passes
under the canonical scoped unit runner without coverage. The inherited proof
hops, exact registry order, ownership/selection continuity, namespace bridge,
source bindings, adversarial history tests and full lineage audit remain.
No expected history is derived from the subject registry itself.

Retained exact-source artifacts qualify CI127's M/A staging obligations,
all five system scenarios, native D12 and Rust component. They authenticate
actual cumulative application starts 38, native AMD Rust commands 7 and
same-wheel transfers 18. CI127 remains `EXECUTED_FAIL` overall. Unit branches
20,940/24,140 and integration branches 19,344/24,140 pass hard floors; desired
87/82 margins remain 62/451 branches short at that denominator.

## Decision

`REPOMAP-CLOE-CI127REPAIR1` makes this explicit test-census repair. Product
behavior, the projection authority policy and every historical quality record,
comparison, cohort, profile and debt ceiling remain unchanged.

After scoped proof and final independent resulting-state review, permit one
normal staging synchronization on existing open draft PR 23, triggering
CI128 attempt 1. Its before head is
`85f3ea6ba891c4db54acf06f3cfbb8700c51137c`; public main/base remains
`5ad00d162ad8a04430874275246a53227578c533`.

This manual retry allocates only application start 39 after actual 38,
native AMD Rust command 8 after actual 7, and one transfer of each unchanged
parser wheel for cumulative 20 after actual 18. Preserve all historical ledger
roots and list prefixes. Seal fresh authority, ledger-before and reservation
hashes against the actual repaired candidate; reject CI127 and older pins,
nonces, reservations, ordinals, attempts and ceilings. Recompute the live D12
context rather than trusting a previous file count. The Rust manifest retains
its 264-path closure, with only the current grant-guard digest amended and
forward lineage recorded. Older evidence is immutable and never repinned.

## Verification and limits

The public phase exit records feature proof and exact selectors. Grant proof
requires its unit owner and the three established containerized admission
selectors, excluding unrelated dependency-runtime materialization. Final
static, full history/quality continuity, topology/export/length/compile,
privacy and suppression checks precede commit and publication.

No product behavior changed, so separate feature integration is unselected;
grant integration still proves the changed admission binding. All complete
local unit, integration, smoke, staging, system and combined populations and
local Python coverage remain unselected. No local application/SDK build or
native Rust/model qualification is granted. Routine canonical scoped setup
retains its existing policy; observed setup counts are reported separately.

No CI129, start 40, automatic retry, second push, workflow rerun, manual
duplicate dispatch, main/tag/release promotion, live runtime mutation, new
dependency, runner-policy change, suppression, denominator change, new debt,
numeric governance, worker attribution or full W7/W6 acceptance follows.
Hosted state remains operator-set `AVAILABLE`. Scoped proof establishes only
its selected contracts; every required hosted obligation remains pending for
the exact new head/tree until the successor executes and is audited.
