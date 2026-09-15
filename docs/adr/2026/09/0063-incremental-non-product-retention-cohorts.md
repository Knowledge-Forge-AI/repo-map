# ADR 0063: Incremental non-product retention cohorts

## Status

Accepted design for PR26-STAGING-FIX5-REVISE25. Implementation and admission
remain subject to measured evidence and the dispatcher-owned checkpoints.

## Date

2026-09-09

## Context

Whole-root enforcement prevented clean non-product groups from acquiring a
ratchet while unrelated modules retained debt. Assignment and diagnostic
cleanliness do not establish effective enforcement.

## Decision

Extend the existing retention inventory JSON with versioned, explicit stable
cohorts for tools, reusable test support, and test owners. Preserve product
retained-ratchet authority and existing conftest/fixture behavior. Cohorts record
sorted membership, root, governing profile, responsibility rationale, and a
pending or admitted state. Each eligible non-product path has one membership.

An admitted cohort earns credit only when every member has complete current
Ruff F, mypy, and at-most-400-physical-line evidence. Pending declarations earn
no credit. Direct debt always blocks. Every repository dependency leaving the
cohort must belong to a currently passing product authority or an admitted
cohort proved effective in this invocation. Cross-cohort circular exemptions
are prohibited. Unknown attribution, aliases, missing stubs, malformed output,
source drift, and tool failures remain blockers. Raw findings remain visible.

Effective root enforcement is the union of passing admitted cohort members;
residual is eligible minus that union. Partial enforcement is an open root.
Residual keeps the global inventory failed. Failure of a previously admitted
cohort additionally reports a hard ratchet regression, distinguishable from
ordinary residual in JSON, compact summaries, and static aggregation. Admitted
regressions exit 2; residual-only failure retains exit 1.

Cohort authority lives in the inventory itself so its existing immutable Git
lineage traversal audits every authority edge. Admission is monotonic; loss,
weakening, reassignment, disappearance, schema rollback, or successor movement
to pending authority fails closed. Rename, decomposition, new helpers, and
empty wrappers cannot create admission credit. Existing decomposition records
are preserved, including their single-use source identities.

An explicit rename or decomposition may replace an admitted member with live
successors in the same admitted cohort. Every branch of the append-only successor
chain must end at a current member of that original cohort; termination, cycles,
silent removal and reassignment remain forbidden. The current membership replaces
the old path, while immutable inventory history retains the old obligation.
Only freshly checked current successors count; absent historical paths earn no
credit. Cross-cohort responsibility transfers require a separate authority design.

Use existing root-batched quality execution with cold mypy caches and exact
source attestation. Derive cohort evidence and dependency closure from these
results without per-cohort subprocesses or persistent cache authority. Bind
source and governing inputs before and after execution. Report shared root
check cost, cohort evaluation time, and total inventory duration. The target
is 180 seconds; the static runner's 300-second timeout is a hard ceiling.

This supersedes ADR 0062's decision that root/profile failures retain zero
effective credit, and its Alternatives rejection of partial root credit, for
the three cohort roots only. All other ADR 0062 protections remain in force.

## Scope

CI maintenance ratchets only. No eligibility reduction, profile weakening,
suppression growth, dependency change, coverage denominator change, or product
architecture work. Independent unit 85/85 and integration 80/80 gates remain;
Go branches remain N/A and smoke/system contribute no coverage.

## Verification

Focused contract, dependency, history, lineage, tamper, reporting, and aggregate
tests; current candidate inventory execution; exact net admission ledger over
pre-existing paths. Fewer than 250 net new effective paths is partial/blocked.
Complete unit, integration, staging, smoke, system, Docker, and QUAL6 remain
outside local scope. Hosted evidence remains separately pending.

## Alternatives

Dynamic groups defined by current findings would conceal unstable boundaries.
A separate cohort registry would escape inventory history traversal. Per-cohort
cold mypy processes would multiply cost; shared persistent caches would require
new freshness authority. Root-batched evidence avoids those costs while
preserving conservative whole-root failure on an unattributable tool failure.
