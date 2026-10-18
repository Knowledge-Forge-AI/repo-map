# ADR 0078: Opt-in stored node source locations

## Status

Implementation candidate amended after the single independent dispatcher
review under REPOMAP-PRODUCT6-NAVIGATION1-SOURCE-LOCATOR1. Final checkpoint
disposition belongs to the dispatcher; no second independent review follows
the revision. No publication is authorized.

## Date

2026-10-14

## Context

Python definition canonicalization persists an `observed` node-evidence link,
even when the canonical node's metadata is empty. SQLite stores that link in
`canonical_node_evidence`, joining `canonical_evidence` to a raw observation by
`(run_id, ordinal)` and to its publication run. Edge explanation exposes
equivalent edge evidence, but requires an edge identity. Observation and file
search do not resolve a selected canonical node. Feed source references describe
feed relations, not general Python symbol provenance.

## Decision and scope

Add the read-only `repomap_node_locations(graph_id, canonical_key, limit=10)`
helper through the existing configured investigation read-store boundary.
SQLite Local supplies accepted-run linked evidence in a deterministic window,
bounded to 1–100 rows with `has_more`. If no accepted-run link exists, the
newest linked historical run supplies that window, explicitly labelled by
`location_scope` and `location_run_id`. Other runs appear separately in
`historical_locations`, bounded by the same limit with `historical_has_more`.
Historical refreshes never consume the main window or determine its ambiguity.
PostgreSQL returns ordinary
`backend_unsupported` without database IO; its existing reads remain unchanged.
No schema, extraction, acquisition, migration or reingestion change is required.

Each evidence row retains the supporting evidence key, link kind, raw observation
identity/hash, stored path/range, extractor/confidence and run/publication
identifiers. Available stored source revision/snapshot facts are bounded and
identified as publication scope rather than inferred per-file attribution.
Source facts come from canonical evidence metadata, respecting canonicalization
overrides. Missing raw observations retain the evidence's stored observation
identity with an explicit unavailable status and null payload hash.
Node `doc_path` metadata is a separately labelled source-relative partial lead,
without a stored source binding, invented lines or supporting raw observation.
Evidence paths are graph source-relative POSIX paths. These namespaces are not
compared for ambiguity; clients must verify the source/logical-root mapping.

Historical evidence remains visible in its own bounded window, explicitly
labelled relative to the accepted run. Neither membership in that run nor a
successful lookup proves filesystem freshness. Multiple rows are preserved,
including contradictory paths/ranges within a run; truncation leaves ambiguity
unresolved. A main window with no usable path and more rows reports `incomplete`,
not a definitive absence. Missing evidence/path/range is ordinary data and
preserves native fallback. Unsafe or redacted paths are unavailable, never a
truncated navigation target.

Graph selection enforces visibility/enabling before binding. SQLite verifies
graph/repository binding in its existing read-only transaction. The helper reads
stored fields only, with existing response sanitization. Search eligibility,
canonical-key ordering, paging, totals and default responses remain unchanged.

## Alternatives

Reusing edge explanation is useful when an edge is already known, but requiring
edge discovery for every selected node leaves the observed navigation gap.
Inferring paths from module names, joining feed references as symbol evidence,
or consulting source trees would invent or acquire provenance. Enriching default
search responses would change an unrelated stable contract.

## Verification and consequences

Small published SQLite fixtures exercise the actual MCP callable/read adapter:
Python evidence, real Markdown extraction/routing, absent and partial facts,
contradictory locations, retained nodes, unchanged/moved symbols across repeated
publications, bounds, privacy and graph/repository isolation.
Legacy search shape/order/paging receives regression assertions. A separate
containerized integration owner covers guarded stdio readback; execution is
deferred when the task prohibits containers. Offline SQLite fixture evidence is
not container qualification or a measured navigation-efficiency gain.

Consumers read a fresh handoff, verify supplied locations directly, use graph
search/locator for unresolved owners, and use native search when no usable lead
is returned. Rollback removes the opt-in helper and its catalog entry; existing
storage and reads need no rollback migration. Result-diversity and backup
interruption follow-ups remain outside this slice.
