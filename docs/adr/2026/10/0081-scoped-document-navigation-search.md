# ADR 0081: Scoped source-document navigation search

## Status

Authorized for the SCOPED-SEARCH1 candidate; independent acceptance pending.

## Date

2026-10-14

## Context

Literal canonical search can present many matching sections from one document.
Caller intent cannot be inferred from a broad term. Legacy node pages and
CONSUMER1 locator/handoff behavior must remain compatible.

## Decision

Add the opt-in sibling `repomap_navigation_search` to the existing configured
investigation read-store boundary. A sibling keeps its group/member pagination
and schema independent from legacy node response/count semantics. Raw search
remains unchanged. SQLite Local is supported; PostgreSQL reports a feature-specific
unsupported outcome without querying storage. No migration or new dependency.

Membership uses the existing escaped literal canonical-key/kind/display-name
match. Scope is `all`, `code`, or `docs`, optionally intersected with exact kind
and an explicit binding plus source-relative subtree. Only maintained direct
subject evidence qualifies a path. Unknown kinds stay available through all/raw.

A bounded candidate/evidence scan in one bound read transaction precedes scope,
group membership and page selection. Exhaustion returns incomplete with no
page, has_more=true and no cardinality claim. No raw observation payloads are
loaded. Query-count and cap behavior require fixture evidence.

Group documentation only by a unique, complete, public direct source identity:
selected run, binding, revision, snapshot and source-relative path. Select the
accepted evidence run when present, otherwise the latest historical evidence
run, before filtering evidence roles, as the locator does. Never combine runs.
Missing, conflicting, withheld or unknown linkage remains a separate singleton.
No decoding canonical keys to fabricate locations, no title/basename merging.

Limits/offsets count groups; member_limit bounds matching members independently.
All displayed members retain exact safe canonical keys, kinds and bounded direct
source hints. No unmatched representative or implicit context parent is added.
Expansion uses existing direct/compact locator for a selected exact member or
the ungrouped navigation query; each call may see a newer publication.

## Scope and consequences

No ranking, inferred task intent, source acquisition, graph refresh, provider
experiments, backend expansion, persistent state or extraction changes. Native
navigation remains the fallback. Runtime bounds and the exact public contract
are documented in `docs/ops/scoped-navigation-search.md`. Focused repository
fixtures must cover actual Markdown/Python extraction, ambiguity, history,
isolation, literal paths, caps, catalog pins and entry compatibility.

Rejected: grouping a truncated raw page, silently widening scope, using links
as subject locations, or relaxing catalog/inventory checks.
