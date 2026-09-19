# ADR 0068: Configured graph readback repository selection

## Status

Accepted for REPOMAP-DEV-V010-PUBLIC-V002-FIX17-R3 implementation.

## Date

2026-09-19

## Context

Portable publication identifies the current repository with `repo1:<graph_id>`
and stores a logical root. Selecting configured graph summaries by a physical
checkout root can therefore return empty or stale data after publication or
relocation. FIX17 already introduced identity selection for graph search,
project summary, and graph neighborhood, but omitted the five language summaries.

## Decision

Configured graph reads use the shared `build_repository_filter_sql` predicate.
An explicitly supplied, validated repository identity selects exactly one row:
the identity-bearing row wins; otherwise only identity-NULL rows at the requested
root are eligible. Identity matches sort first with explicit PostgreSQL
`DESC NULLS LAST`; ascending repository ID deterministically breaks ties.
Selection happens before language or content filtering. An empty current
repository never causes fallback to legacy content. Unrelated identities,
including those sharing the requested root, are excluded.

PostgreSQL normally places nulls first for descending order; the explicit
`NULLS LAST` therefore matters for nullable identity comparisons. Later sort
keys break ties independently. See the PostgreSQL
[sorting contract](https://www.postgresql.org/docs/18/queries-order.html).

The bounded fallback applies to identity-aware calls. Existing root-only storage
callers retain their historical behavior, including their existing tie handling;
normalizing those interfaces is outside this repair. The configured graph
search, project summary, graph neighborhood, Python, Terraform, OpenAPI,
JavaScript framework, and Nix summary callers supply identity.

Configured `project=<graph_id>` routing supplies identity centrally for status,
canonical list/explanation/neighborhood, and all six source readers. Configured
identity overrides conflicting internal keyword arguments. Explicit connections
and legacy project configurations retain root-only compatibility. Canonical and
source SQL share one repository selection contract; nested source metadata and
references remain bounded to the selected repository even when keys collide.

Reconciliation explicitly orders the nullable identity comparison with
`DESC NULLS LAST`, preserving current identity-owned keeper preference, the
root preference, ascending-ID tie break, and bounded survivor selection.
Existing uniqueness and foreign-identity refusal constraints remain intact.
Publication authority epochs and content keeper repository IDs are non-null;
their ordering needs no null-placement correction.

Summary payload roots remain derived from the requested root, with existing
sanitization and Nix's `[root-path]` marker. They must not be replaced by the
selected repository row's stored physical root.

## Scope and verification

No schema, publication-root, dependency, pagination, vocabulary, or privacy
policy changes. Tests cover identity precedence, deterministic legacy fallback,
relocation, unrelated-row exclusion, empty-current data, identity validation,
and payload root preservation. PostgreSQL execution through the canonical
disposable integration harness owns SQL proof; SQLite is supplemental only.

## Rejected alternatives

Five independent selectors would duplicate the same correctness boundary.
Reverting portable publication to checkout paths would lose stable graph
identity. Merging current and legacy rows would leak stale content.
