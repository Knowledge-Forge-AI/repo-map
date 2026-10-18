---
name: repomap-mcp-readback
description: Use when querying a loaded RepoMap graph through the read-only RepoMap MCP server, selecting projects or configured graphs, reading canonical nodes, edges, evidence, neighborhoods, search results, source/feed facts, or bounded summaries from an MCP-capable coding agent.
---

# RepoMap MCP Readback

## Overview

Use the RepoMap MCP server as a read-only graph readback layer over storage
databases that local RepoMap ops maintain outside MCP. MCP does not discover
source files, refresh graphs, load observations, mutate storage, run shell
commands, run database lifecycle actions, or change graph identity. This
skill owns the query workflow; registry and environment configuration belong
to `repomap-mcp-configuration`.

## Tool Surface

Storage-family tools accept `project` (or explicit `root_path`/`pg_*`
development arguments):

- `repomap_status`, `repomap_projects`
- `repomap_canonical_nodes`, `repomap_canonical_edges`
- `repomap_explain_canonical_edge`, `repomap_canonical_neighborhood`
- `repomap_ingested_sources`, `repomap_source_summary`,
  `repomap_source_runs`, `repomap_source_feed_items`,
  `repomap_explain_source_feed_item`, `repomap_source_references`

Graph-registry tools accept `graph_id` and serve only enabled, MCP-visible
configured graphs:

- `repomap_list_graphs`, `repomap_graph_status`
- `repomap_search_nodes`, `repomap_search_observations`,
  `repomap_search_files`
- `repomap_neighborhood`, `repomap_project_summary`
- `repomap_python_summary`, `repomap_terraform_summary`,
  `repomap_openapi_summary`, `repomap_js_framework_summary`,
  `repomap_nix_summary`
- `repomap_refresh_status`
- `repomap_node_locations` (opt-in selected-node stored evidence; SQLite Local,
  other backends return `backend_unsupported`; see [source navigation](../../source-navigation.md))
- `repomap_similar_nodes` (experimental optional PostgreSQL stored-seed read;
  requires imported rebuild/profile identities and explicit selection)
- `repomap_embedding_profiles` (read-only current-publication tuple discovery;
  explicit selection, public-safe optional PostgreSQL metadata only)
- `repomap_server_memory_summary`, `repomap_server_memory_search`
  (read-only server-memory bridge; available only when the bridge is
  configured)

If tools are not visible, first distinguish the cause — server not
configured, agent session has not reloaded its MCP inventory, approval/trust
policy blocking calls, or missing storage connection defaults. Do not infer
graph contents when the tools are unavailable.

### SQLite Local Graphs

For a SQLite Local home, all 24 graph-reading tools are supported: the four
canonical tools, legacy `repomap_status` (with a graph-registry `project`),
`repomap_graph_status`, `repomap_refresh_status`, `repomap_project_summary`,
the three searches, `repomap_neighborhood`, the five language/framework
summaries, the six source/feed tools and the opt-in node locator (plus the configuration and
server-memory tools). Source/feed answers come only from the graph's accepted
publication. A graph published without acquired feed observations reads as
empty, not as missing capability, so do not retry against another backend.
Content tools on an initialized but never-published graph return
`graph-publication-absent`.

The catalog also advertises `repomap_similar_nodes` and `repomap_embedding_profiles`. SQLite returns
`sqlite_unsupported` when selected and `disabled` otherwise, without database IO.
For PostgreSQL, use the canonical seed key, qualified source binding when needed,
and the `rebuild_id`, `profile_identity`, and integer `dimensions` explicitly
chosen from `repomap_embedding_profiles(graph_id="public-graph", selected=true,
limit=20)`. Discovery defaults disabled, accepts limits 1–100, and never enables
the optional capability. It reads only current accepted portable-publication
metadata, in rebuild-ID order, with `has_more` for truncation. Multiple rebuilds
remain distinct; no preferred profile is inferred. Returned model/generator
versions, representation, metric, normalization, row count and source scope
describe partial imports, never full publication coverage. No vector, source
content or enrichment principal is exposed. A stale tuple must be rediscovered;
the seed operation still independently checks caller-selected identities.
`has_excluded_rebuilds` flags repository rebuilds excluded by SQL publication or
evidence checks, including partial exclusion alongside valid entries. Profile
digests are checked only in the `limit+1` page; an invalid extra row also refuses
the entire result. Identities beyond that page remain unvalidated, so a larger
limit can expose an identity refusal. The output limit does not cap the work of
checking evidence across all bound rebuilds. No scalability claim is implied.
Results are exact cosine candidates from one accepted publication, with stored
evidence and partial-import limits; they create no canonical edge. See the
[experimental query contract](../../../adr/2026/10/0077-publication-bound-pgvector-candidates.md#decision-and-scope).

Discovery refusals distinguish `disabled`, `sqlite_unsupported`,
`private_graph_unsupported`, `extension_absent`, `extension_unsupported`,
`enrichment_schema_absent_or_unsupported`, `observation_failed`,
`publication_unaccepted`, `stale_publication`, `no_import`, `stale_rebuild`,
`invalid_rebuild`, `invalid_identity`, `ambiguous_identity` and `privacy_refused`. Foreign imports
are excluded before projection; a graph with only foreign imports reports
`no_import` without disclosing another graph's identities. Failures after a
successful probe are bounded query errors, not capability-observation failures.
Ordinary core graph readiness and queries do not depend on these optional facts.
Discovery reports a malformed or missing latest portable receipt as
`publication_unaccepted`, with no historical fallback. The existing seed query
retains its bounded storage error for malformed receipt data. Privacy refusal
also returns no tuples: full private paths remain substring markers, while local
usernames are checked as metadata tokens, excluding opaque digest collisions.

## Selecting A Project Or Graph

1. When the graph registry is active, call `repomap_list_graphs` first and
   use `graph_id` with the graph-registry tools.
2. For storage-family tools, call `repomap_projects`, then pass
   `project="<name>"` (or rely on `default_project`). When no legacy project
   matches, an MCP-visible `graph_id` is accepted as the `project` value.
3. Use explicit `root_path` plus connection arguments only for development
   and disposable test clusters, and do not combine them with `project`.

## Status Contract

`repomap_status` returns a canonical storage summary: `read_only=true`, the
expected repository identity, `graph_key_version=1`,
`storage_model="canonical"`, and counts for `runs`, `files`,
`raw_observations`, `canonical_nodes`, `canonical_edges`, and
`canonical_evidence`. `repomap_graph_status` reads stored status for one
configured graph by `graph_id`. Root paths in responses are display-sanitized
markers, and private graph roots are redacted.

## Query Workflow

Choose the search surface from the caller's question:

- Known source location/handoff: verify source directly with zero graph calls.
- Unresolved indexed subject: node/navigation search matches canonical key,
  kind and display name; optional exact kind and navigation family/source
  filters select the population. A selected node may supply a direct/compact
  locator lead, which still needs source verification.
- Source assignment, comment, string, error message or syntax: use bounded
  native literal-text search in the caller-selected workspace/subtree, then
  inspect source. Such content need not name a node; spelling alone never
  chooses the route.

`repomap_search_files` matches stored path, language and role, with optional
exact path filtering. `repomap_search_observations` matches retained kind,
source ID, path and serialized payload text, with optional exact kind/path
filters; `include_raw` affects output only. Neither is arbitrary workspace
source-body search. A complete empty result establishes no match only in that
tool's indexed fields and selected population/scope, never absence of source
text, behavior, exports, tests or implementation. Incomplete/unavailable/error
responses establish less. Keep native fallback available without retries or
automatic scope widening.

For source navigation, read a fresh handoff and directly verify any supplied
location first. Search and call `repomap_node_locations` only for unresolved
locations. For a selected node whose location is unresolved, request
`evidence_role="direct", detail="compact"` and a small limit to locate the subject; use the
reference/default view to investigate callers, mentions, outgoing links or
containment context. Reference evidence covers either edge endpoint. Role filtering
precedes bounded windows; accepted references cannot promote historical direct
evidence into the accepted run. Unsupported producer roles remain explicitly
unknown; fall back to native search when no usable lead exists. A filtered
`historical_locations_only` reason points to older evidence; metadata-only
ambiguity does not establish a stored location for that role. Verify the
configured path namespace instead of blindly stripping `root/`. No MCP query is
required just to demonstrate tool use. See [the compact workflow](../../source-navigation.md).

Compact is opt-in (`full` remains the default), versioned with `schema_version=1`.
It groups stored bindings/publications into indexed tables and preserves all
selected alternatives, nullable ranges, withheld paths, provenance gaps, both
window bounds and historical relations. Map the explicit binding and stored
source-relative path to the intended source workspace, then verify the file
and range before relying on it. Stored publication/binding revisions do not
verify a working copy. For an unknown node, use existing search and pass its
exact returned canonical key only when this resolves the missing location.
For ambiguity, truncation, metadata without binding, unsupported/absent/broken
helpers or stale/uncertain leads, inspect needed full evidence or use bounded
native search; do not loop through a failed lookup or silently select history.
Expand with the same locator arguments and `detail="full"`; that new read may
observe a newer publication, so it is not guaranteed to share the prior snapshot.
The [tested optional consumer example](../../../../tools/source_navigation_consumer.py)
records handoff/lookup/fallback branches, makes zero graph calls for known
locations or absent helpers, and keeps source verification a caller-side read.

1. Call `repomap_status` (or `repomap_graph_status` for a configured graph)
   and confirm the read-only boundary and expected identity.
2. Call `repomap_canonical_nodes` with a `kind` (for example
   `python.module`, `file`, `doc.page`, `feed.item`), or
   `repomap_search_nodes` with a `graph_id` and query string when hunting for
   a node.
3. Call `repomap_canonical_edges` with an edge `kind` (for example
   `imports`, `references`) and a `source_key` when focusing on one node.
4. Call `repomap_explain_canonical_edge` when evidence matters.
5. Call `repomap_canonical_neighborhood` (or graph-scoped
   `repomap_neighborhood`) for local graph context around one canonical
   node.
6. For already-ingested sources, walk `repomap_ingested_sources` →
   `repomap_source_summary` → `repomap_source_runs` →
   `repomap_source_feed_items` → `repomap_explain_source_feed_item` →
   `repomap_source_references`.

## Pagination And Bounded Output

Canonical node/edge lists, neighborhood node/edge collections, and evidence
lists default to 50 records with `limit` between 1 and 200 and explicit
`offset` windows; search tools default to 20. Filters apply before
pagination. By default (`result_schema_version=1`) list tools return an
object envelope with the result kind, items, and continuation metadata —
use it to page deterministically. Pass `result_schema_version=0` only when a
legacy consumer still needs the older bare shape.

## Canonical Identity Rules

- Report canonical keys (`file:<path>`, `python.module:<module>`,
  `doc.page:...`) and canonical edge identity (source key, edge kind, target
  key, graph key version, identity metadata hash).
- Do not present database integer ids, legacy stable keys, raw observation
  source ids, or line numbers as canonical identity; line spans belong to
  evidence.
- Treat `external:*`, `dynamic:*`, and `unknown:*` reference targets as
  explicit uncertainty, not failures.
- `repomap_neighborhood` (configured graph) sanitizes its payload, and its
  edge `source_key`/`target_key` fields come back as `[REDACTED]`. Use
  `repomap_canonical_neighborhood` with `project="<graph_id>"` when you need
  edge endpoint identities.

## Error Handling And Privacy

- MCP storage errors preserve the bounded failure reason but omit
  operational topology (host classification, container identity). Use the
  local ops CLI for authorized runtime diagnosis.
- Every database-reading tool (canonical, `repomap_status`, graph/refresh
  status, search, project summary, configured neighborhood, the five
  language/framework summaries and the six source/feed tools) reads host-only
  for configured graphs: a stopped or unreachable database is reported, never
  worked around through a container. Graph and refresh status report it in
  `storage.error` or per-graph `error`; the others refuse with bounded text.
- If a call fails, report the exact error and which layer failed:
  configuration, session exposure, approval policy, storage connection, or
  RepoMap query.
- If readback appears stale, repair the configured graph through local ops
  outside MCP (`repomap-cli-workflow`); do not ask for write tools.

## Safety Rules

- Treat the MCP surface as strictly read-only.
- Source/feed tools read already-ingested metadata only; nothing is fetched
  through MCP, and no URL, credential, OAuth, or provider-state operation
  exists on the surface.
- Do not expose credentials, secret values, full feed bodies, or full
  retained artifact bytes in reports.
- Run discovery, loading, ingestion, refresh, and database lifecycle outside
  MCP through the normal CLI workflows.

## Optional task-scoped navigation search

`repomap_navigation_search` is a SQLite Local sibling view; raw search remains
the default. Explicitly choose `scope="code"` (only `python.module`,
`python.class`, `python.function`, `python.method`; not all code text),
`scope="docs"`, or `all`, and optionally an exact `source_binding_id` plus
`source_path_prefix`. `grouping="source_document"` reduces repeated proven
document destinations before group paging. Unknown/ambiguous identities remain
singletons. Incomplete scans report unknown continuation, not an empty corpus.
See the [API, identity, pagination and fallback contract](../../scoped-navigation-search.md).
Use direct/compact locator only for a selected unresolved subject; verify a
useful supplied handoff directly with zero graph calls. On unsupported, broken
or unhelpful optional results, raw/native navigation remains available.
