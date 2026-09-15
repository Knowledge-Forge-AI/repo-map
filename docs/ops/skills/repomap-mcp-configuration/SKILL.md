---
name: repomap-mcp-configuration
description: Use when configuring the read-only RepoMap MCP server, wiring the graph registry or legacy project registry, setting MCP server environment variables, or diagnosing project, graph, and default resolution for RepoMap MCP tools.
---

# RepoMap MCP Configuration

## Overview

Configure RepoMap MCP as a read-only query surface over RepoMap graph
databases that local ops maintain outside MCP. This skill is the sole owner
of the public MCP configuration shape, registry and environment settings,
and resolution behavior. It does not own the query procedure
(`repomap-mcp-readback`) or the post-configuration verification procedure
(`repomap-mcp-smoke-test`).

## Server Launch

The MCP server is the stdio command:

```sh
repomap-kg mcp serve
```

MCP clients launch that command directly (or the equivalent
`python -m repomap_kg.server.mcp` from a source checkout with
`PYTHONPATH=<checkout>/src/main/python`). `repomap-kg server serve` is the
separate long-running HTTP health/status runtime; do not configure it as the
stdio MCP command, and do not run stdio MCP as a detached container command.

## Two Configuration Surfaces

### Graph registry (preferred)

`mcp serve` accepts `--repo-map-home <dir>` and reads the same TOML
configuration as local ops (`REPOMAP_HOME`, default `~/.repo-map`). Each
`[[graphs]]` entry with `enabled = true` and `mcp_visible = true` becomes
visible to the graph-registry MCP tools (`repomap_list_graphs`,
`repomap_graph_status`, search, neighborhood, summaries, refresh status).
Private graphs keep their roots redacted in tool output.

### Legacy JSON project registry

The storage-family tools (`repomap_status`, `repomap_canonical_*`,
source/feed tools) resolve named projects from a JSON registry file:

```json
{
  "default_project": "example",
  "projects": {
    "app": {
      "root_path": "/path/to/app",
      "pg_database": "repomap_app"
    },
    "docs": {
      "root_path": "/path/to/docs",
      "pg_database": "repomap_docs"
    }
  }
}
```

Project entries may also include `pg_host`, `pg_port`, and `pg_user`. Keep
secrets out of this file.

Set `REPOMAP_MCP_CONFIG` in the MCP server environment to select the
registry file explicitly. Always set it for a portable configuration: the
compiled-in default path is a development-machine artifact and is not a
contract.

## MCP Server Environment

- `REPOMAP_MCP_CONFIG`: path to the legacy JSON project registry.
- `REPOMAP_PSQL_COMMAND`: psql executable override when `psql` is not on the
  server path. `psql_command` is intentionally absent from every MCP tool
  schema and must remain a server-side setting, never a model-controlled
  argument.
- `REPOMAP_PG_HOST`, `REPOMAP_PG_PORT`, `REPOMAP_PG_USER`,
  `REPOMAP_PG_DATABASE`: explicit development-mode connection defaults only.

## Resolution Rules

- A tool call with `project` resolves root and database settings from the
  legacy registry; when no legacy project matches, an MCP-visible
  graph-registry `graph_id` is accepted.
- With no `project` and a configured `default_project`, the default applies.
- Explicit `root_path`/`pg_*` arguments without `project` preserve
  development mode for disposable test clusters.
- Missing project names and missing default/root settings fail before any
  storage query.
- Graph-registry tools take `graph_id` and serve only enabled, MCP-visible
  graphs.

## Read-Only Boundary

Do not add discovery, refresh, storage-load, source-ingestion, API
acquisition, credential lookup, scheduler, database lifecycle, or any other
write-capable tool to the MCP configuration. Folder-tree refresh, feed
ingestion, documented API acquisition, and backup-first database lifecycle
are local CLI/ops workflows (`repomap-cli-workflow`). If a graph is stale,
repair it through local ops outside MCP.

## After Configuration

Restart or refresh the MCP-capable agent session if tool discovery is stale,
then run the `repomap-mcp-smoke-test` procedure. This skill intentionally
does not duplicate the smoke checklist. If tools are missing, distinguish
configuration, session exposure, approval policy, storage connection, and
RepoMap query failures.
