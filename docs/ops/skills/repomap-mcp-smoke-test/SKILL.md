---
name: repomap-mcp-smoke-test
description: Use when verifying that an MCP-capable coding agent can connect to a local read-only RepoMap MCP server and query a preloaded RepoMap graph without mutating storage or running discovery through MCP.
---

# RepoMap MCP Smoke Test

## Overview

Verify MCP integration after adding or changing a RepoMap MCP server
configuration. The smoke test proves that an agent can call the read-only
MCP tools against a graph that was loaded outside MCP. This skill is the
sole owner of the smoke checklist; configuration shape belongs to
`repomap-mcp-configuration` and general query procedure to
`repomap-mcp-readback`.

Do not use this workflow to test extraction behavior, load storage through
MCP, run discovery through MCP, or mutate Postgres through MCP.

## Setup Boundary

Prepare storage outside MCP:

1. Start a disposable Postgres cluster or choose a non-production test
   database (or use an existing configured local runtime graph).
2. Apply RepoMap migrations.
3. Load a graph outside MCP: either refresh a configured graph through local
   ops, or run `repomap-kg discover <repo> --jsonl` plus
   `repomap-kg storage load-files <observations.jsonl>` for a disposable
   database.
4. Configure the MCP server with a graph-registry entry
   (`enabled`/`mcp_visible`), a legacy project-registry entry, or explicit
   storage connection arguments for development mode.

The MCP server itself must remain read-only.

## Suggested Agent Prompt

```text
You are performing a RepoMap MCP smoke test.
Do not edit files. Do not run shell commands. Do not use non-RepoMap tools.
Use only the RepoMap MCP tools.
Use project="<name>" (or graph_id="<graph-id>" for graph-registry tools).

Call these tools and summarize whether each call succeeded:
1. repomap_projects
2. repomap_status
3. repomap_canonical_nodes with kind="python.module" (or another known kind)
4. repomap_canonical_edges with kind="imports" and a known source_key
5. repomap_explain_canonical_edge for a known canonical edge
6. repomap_canonical_neighborhood for a known node

If the graph registry is configured, also call:
7. repomap_list_graphs
8. repomap_graph_status with a known graph_id
9. repomap_search_nodes with that graph_id and a known query term

If ingested feed source data is expected, also call:
10. repomap_ingested_sources
11. repomap_source_summary for a known source_id
12. repomap_source_feed_items for that source_id
13. repomap_source_references for that source_id

Do not call any ingestion, fetch, load, discovery, scheduler, source-editing,
or arbitrary URL tool through MCP.

Return a concise report with concrete counts and exact error text for
failures.
```

## Required Checks

The smoke test passes only when all applicable checks succeed:

- `repomap_projects` returns the expected registry, or an intentionally
  empty registry when explicit development mode is being tested.
- `repomap_status` returns `read_only=true`, the expected graph key version,
  `storage_model="canonical"`, and named counts for runs, files, raw
  observations, canonical nodes, canonical edges, and canonical evidence.
- `repomap_canonical_nodes` returns at least one expected canonical node
  kind inside a bounded result envelope.
- `repomap_canonical_edges` returns expected edges for a known source node.
- `repomap_explain_canonical_edge` finds a known edge and returns evidence.
- `repomap_canonical_neighborhood` returns a center node and adjacent
  structure.
- When the graph registry is configured, `repomap_list_graphs` lists the
  expected MCP-visible graphs and `repomap_graph_status` returns stored
  status for a known `graph_id`, with private roots redacted.
- When ingested source data is expected, the source/feed tools return
  stored metadata without fetching anything.

## Approval And Session Gotchas

MCP-capable agents may require tool approval for local MCP calls. Prefer a
server-scoped approval/trust setting for the read-only RepoMap MCP server
over global approval or sandbox bypasses.

If tools do not appear after configuration changes, restart the agent
session or refresh MCP tool discovery before diagnosing the server
implementation.

## Reporting

Record:

- the MCP configuration shape, without secrets;
- how storage was prepared;
- the exact tool sequence;
- pass/fail status for each tool;
- concrete counts or graph facts returned;
- exact failure text, if any;
- whether each failure belongs to MCP configuration, agent approval/session
  behavior, storage connection, or RepoMap query behavior.
