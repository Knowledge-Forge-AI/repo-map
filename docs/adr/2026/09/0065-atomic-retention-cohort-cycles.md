# ADR 0065: Atomic retention cohort cycles

## Status
Accepted for PR26-STAGING-FIX5-REVISE27 implementation. Narrowly supersedes
ADR 0063's unconditional cross-cohort-cycle prohibition.

## Date
2026-09-09

## Context
Stable cohort IDs and membership prevent admission-order repairs of dependency
cycles. Clean same-root cohorts need an atomic evaluation unit without lineage
erasure or provisional governance.

## Decision
Derive deterministic strongly connected components from the exact candidate
static dependency graph and existing cohort membership. Multi-cohort components
may be evaluated atomically only with one retention root and governing profile.
Every definition must be valid and candidate-bound. Every member requires complete
passing direct Ruff F, mypy and at-most-400-line evidence. Existing import
uncertainty, unresolved imports, file errors, tool failures and unknown attribution
remain blockers. Preserve mypy-attributed external obligations as well as imports.

Internal obligations are satisfied by the complete group only. Every obligation
leaving the group must already be independently governed. Product authority keeps
its existing independent validation. Resolve groups and singleton cohorts to a
fixed point. Governance is contributed atomically only when every constituent
is admitted and clean. No pending cohort may lend governance.

A clean all-pending group may pass diagnostic evaluation without enforcement.
Mixed admitted/pending groups fail with pending constituent IDs recorded; every
failed admitted constituent is a regression. One failing member fails the group.
Cross-root components remain blocked. Acyclic singletons and existing intra-cohort
member semantics remain unchanged. Cohort IDs, membership and transition/history
validation are unchanged.

## Evidence
One deterministic record per multi-cohort component records sorted cohort_ids,
root/profile (or cross-root classification), a versioned identity, internal edge
count and SHA-256 commitment, external obligations, unmet dependencies, blockers,
status and effective_enforcement. Cohort records reference the group. Compact
evidence retains bounded group summaries and commitments without duplicating
member paths or transitive graphs. Existing log and aggregate caps remain fixed.

The evaluator computes the internal-edge commitment from the candidate graph.
Source readback validates its hexadecimal shape, group identity and constituent
contracts; it does not recompute edges from the compact record. The
`make_internal_dependency_sha256` helper constructs test fixtures, not independent
graph verification. A passing all-pending diagnostic records only dependencies
that actually entered the governed closure as `governed_dependencies`.

## Required verification
Focused controls cover two/three-cohort cycles, ordering, pending governance,
direct checker findings, import uncertainty, external governance, cross-root
refusal, admitted regressions, stable membership/history, deterministic commitments,
and malformed evidence. Canonical focused tests do not qualify suite coverage.

## Scope and consequences
Only retention governance closure and its evidence change. No product architecture,
dependency, threshold, suppression, census eligibility or history relaxation.
Rollback requires restoring evaluation and evidence together and dispositioning
any admitted group against the restored policy; do not erase lineage.
