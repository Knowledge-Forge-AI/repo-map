# ADR 0062: Retained Python enforcement authorities

## Status

Accepted for PR26-STAGING-FIX5-REVISE19 implementation; measured completion is recorded in the phase exit.

Partially superseded by [ADR 0063](0063-incremental-non-product-retention-cohorts.md):
tools, reusable test support, and test owners now earn effective credit through
passing admitted cohorts. The whole-root zero-credit decision and rejection of
partial root credit below remain historical for those three roots.

## Context

Candidate self-comparison cannot protect committed retention history. Whole-root fail-closed quality credit also obscures incremental repair, and fixture prose alone cannot authorize exclusion.

## Decision

Compare immutable candidate lineage with independent predecessor authorities, using PR merge parents and target merge-base lineage where available. Unsupported history fails closed. Audit protected paths and append-only removal/replacement evidence, including explicitly terminated successor chains.

Keep eligible, assigned, executed, clean-under-profile and effectively-enforced populations distinct. Diagnostic cleanliness requires completed actual profile execution; historical ratchet allowance is not zero findings. Root/profile failures retain zero effective credit.

Use a content-bound fixture manifest with explicit consumers and roles, validated statically without executing fixture code. Reconcile retained selection against longest-prefix type ownership; pending admissions preserve migration rationale and Python obligations. Append specific superseded rules when maintenance ownership changes.

Bind governing inventory, selection/baseline, ownership, fixture, lineage, transition and quality-profile inputs by digest and size, and reject changes during enforcement.

## Scope

Governance and zero-new-debt admissions only. Coverage populations and independent unit 85/85 and integration 80/80 thresholds are unchanged. Go branch coverage remains N/A. No runtime, CLI, MCP, database or product architecture change is authorized by this decision.

The 46 admissions explicitly reclassify the declared Go migration or transitional
Python forecast to retained Python maintenance ownership at T1-future. Admission
requires the real retained profile, no newly grandfathered Ruff/type/import/length
debt, preserved callers, and focused boundary tests. This changes the ownership
manifest's forecast; it does not approve a product architecture relocation or a
language migration. Existing architecture-box values remain future placement
context for coordinator control, service packaging, storage and the other admitted
families. Their exact superseded rules and family-specific rationale remain in
append-only transition evidence. Architectural placement decisions remain reserved
for post-main; enforcement cannot wait for a hypothetical replacement.

## History preservation constraint

Recovered superseded rules currently require their pinned source commits to be
available. A normal merge preserving feature-branch ancestry supports that contract;
a squash/rebase merge or an incomplete object checkout may not. PR #26 must retain
those ancestry objects for this implementation. If the operator selects another
merge strategy, a separately verified durable authority migration is required
before merge. Publication of this checkpoint does not authorize a merge or settle
the operator's strategy. Missing historical authority continues to fail closed.

## Verification

Focused synthetic history, fixture, consistency and profile regressions; actual cohort static checks. Full unit/static requalification remains hosted PR Fast; integration, smoke, system, staging and QUAL6 are not selected locally.

## Alternatives

Comparing against candidate HEAD, equating no diagnostics with clean execution, and granting partial root credit were rejected because each can conceal debt.
