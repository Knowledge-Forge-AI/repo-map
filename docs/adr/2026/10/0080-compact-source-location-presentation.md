# ADR 0080: Compact stored-source location presentation

## Status

Implementation decision for REPOMAP-PRODUCT6-NAVIGATION3-CONSUMER1.
Amended after the dispatcher-owned independent work review; task-scoped
SQLite candidate complete with the inventory limitation recorded in exit 01019.
No second independent review follows revision. Final checkpoint is external;
no commit or release is authorized by this task.

## Date

2026-10-14

## Context

The accepted locator already selects direct evidence before bounded windows.
Agent consumers need a smaller optional representation and a tested way to
verify a supplied location before querying a graph. Eighteen fresh constructed
entry-fixture callable responses measured 1,376–4,127 canonical JSON bytes.
The prior archive's 23 responses measured 1,376–6,746 bytes. Neither set
measures MCP wire size, model tokens, latency, or excessive output.

Repeated binding and publication objects, operational graph display fields,
static safety markers and verbose observation identifiers can be elided or
grouped without changing selection. An evidence key already redacted by the
full route must remain inaccessible.

## Decision

Add `detail="full"|"compact"` to the existing `repomap_node_locations` tool.
`full` is the default and returns the existing payload unchanged. Validate the
selector before I/O. Compact is a deterministic projection of the **same
already bound and sanitized** full payload, with no second query, source read,
sanitizer exception, or backend branch. PostgreSQL stays unsupported.

The compact payload identifies itself with `detail="compact"` and
`schema_version=1`. Preserve graph ID and repository name, canonical and
repository identities, requested role (explicit `all` when omitted), status,
reason, limit, ambiguity, both window bounds, accepted publication and selected
run relationship, node first/last seen runs, nullable ranges, path status,
metadata binding gaps, unverified freshness and native fallback.

`locations` and `historical_locations` retain every selected row in order;
neither is deduplicated. Each row retains basis, link/role, run and publication
relation, path/range statuses, extractor/version/confidence and observation
status/ordinal/kind. The outer row's run ID also identifies its observation.
The top-level `path_namespace` applies to both evidence windows; metadata
retains its separate namespace. A missing source-relative path stays absent;
a withheld one stays null. Missing binding fields stay missing.

`bindings` and `publications` contain distinct sanitized objects in first-use
order, traversing main then historical windows. Row `binding` and `publication`
are zero-based indexes into those tables. Bindings group source metadata except
the per-row `source_relative_path`. An empty binding object exposes missing
provenance. These are presentation indexes, never canonical identities or
dereference endpoints. Conflicting bindings remain separate.

Omit graph operational/display fields, static `safety`, evidence keys and raw
observation payload hashes/source IDs/repeated run IDs. Keep enough provenance
to correlate a lead using graph, accepted publication, row run/ordinal/kind,
binding and publication tables. No history detail is omitted beyond these same
row-field omissions: the historical window and `historical_has_more` retain
their original meaning. Empty history describes the returned window, not an
unbounded census. History and metadata never become current direct evidence.

Expand by repeating the existing locator with the same `graph_id`,
`canonical_key`, `evidence_role` and `limit`, changing `detail` to `full`.
This is another read and may observe a newer publication; no snapshot guarantee
or evidence dereference API is introduced.

## Optional consumer example

The repository-local `tools/source_navigation_consumer.py` example accepts an
explicit handoff record or unresolved node, an explicit binding-to-workspace
mapping, and a caller-provided source
check. A usable handoff causes zero graph calls. Otherwise a selected node uses
direct compact lookup once; unknown nodes may use existing search once first.
Ambiguous, truncated, historical, unbound or failed lookups fall back without a
retry loop. Source verification is a separate bounded caller-side read; stored
publication or binding revisions do not prove working-copy freshness. Paths
are never derived from a canonical key or by stripping a binding prefix.

## Scope, evidence and rollback

No SQL, role/window logic, search behavior, schema, dependencies, ingestion,
live graph reads, runtime services or backend expansion. Use real repository
canonicalization/publication/SQLite fixtures through callable/schema/dispatch
and source verification scenarios. Generic Python observations in the existing
fixture are synthetic; Markdown extraction and publication are real.
Update the guarded stdio integration owner, but do not bypass its container
requirements. Unavailable external infrastructure is an explicit limitation
under this task's authority. Removing the detail selector/projection and
optional example rolls back the slice without storage migration.

The catalog description/schema change requires refreshing both maintained
catalog pins. Register the example and affected test owners in the existing
retention inventory without changing root or quality policy. Global inventory
closure remains a separate gate when unrelated inherited omissions persist;
scoped evidence must disclose that failure rather than imply a global pass.
