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
- `repomap_server_memory_summary`, `repomap_server_memory_search`
  (read-only server-memory bridge; available only when the bridge is
  configured)

If tools are not visible, first distinguish the cause — server not
configured, agent session has not reloaded its MCP inventory, approval/trust
policy blocking calls, or missing storage connection defaults. Do not infer
graph contents when the tools are unavailable.

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

## Error Handling And Privacy

- MCP storage errors preserve the bounded failure reason but omit
  operational topology (host classification, container identity). Use the
  local ops CLI for authorized runtime diagnosis.
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
