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

### Host-native launch (PostgreSQL-backed first slice)

Run MCP as an ordinary host process from any working directory by selecting
the interpreter's console script explicitly. From a checkout virtual
environment (not a wheel or installed-package qualification):

```sh
<checkout>/.venv/bin/repomap-kg mcp serve --repo-map-home <REPOMAP_HOME>
```

Client-neutral stdio entry; map the fields onto the client's own format, and
point `REPOMAP_MCP_CONFIG` at a file containing `{"projects": {}}`:

```json
{
  "command": "/abs/checkout/.venv/bin/repomap-kg",
  "args": ["mcp", "serve", "--repo-map-home", "/abs/repo-map-home"],
  "env": {"REPOMAP_MCP_CONFIG": "/abs/repo-map-home/empty-mcp-registry.json"}
}
```

Tool calls pass `project: "<graph_id>"`. The entry needs no `PYTHONPATH`,
`VIRTUAL_ENV`, `PGPASSWORD`, Docker socket, or container-local executable.
Prerequisites: a setup-owned home with `runtime/.env`,
`[runtime.postgres] direct_host_port_enabled = true` with a reachable
`host_port`, and an already published graph. The database may run in a
container. For that default setup-owned configuration, `--repo-map-home`
reads as the least-privilege `repomap_read_status` role; the credential is
loaded in memory from `runtime/.env` and never exported. Custom PostgreSQL
users or credentials, and `--config <file>`, keep their own configured
credential. For the home's default file loaded through `--config`, that is the
admin `REPOMAP_PG_PASSWORD` if it is exported. Prefer `--repo-map-home`.

Twenty-three database-reading tools use host-only named read-store seams:

- canonical seam: `repomap_canonical_nodes`, `repomap_canonical_edges`,
  `repomap_explain_canonical_edge`, `repomap_canonical_neighborhood`, and the
  legacy `repomap_status` counts (its payload is unchanged);
- investigation seam: `repomap_graph_status`, `repomap_refresh_status`
  (selected and omitted forms), `repomap_search_nodes`,
  `repomap_search_files`, `repomap_search_observations`,
  `repomap_project_summary`, `repomap_neighborhood`, and the five
  language/framework summaries (`repomap_python_summary`,
  `repomap_terraform_summary`, `repomap_openapi_summary`,
  `repomap_js_framework_summary`, `repomap_nix_summary`);
- source seam: `repomap_ingested_sources`, `repomap_source_summary`,
  `repomap_source_runs`, `repomap_source_feed_items`,
  `repomap_explain_source_feed_item`, `repomap_source_references`.

Every configured tool first selects the graph from the parsed config
(`graph_selection.GraphSelection`): unknown, disabled, readback-unsupported
and hidden graphs refuse there with their existing text, before any backend is
bound. Only then does the PostgreSQL binding (`postgres_read_binding`) read
`REPOMAP_PSQL_COMMAND`, name the database and build the store. Selection does
not require bound PostgreSQL connection authority: it opens no connection and
holds no endpoint or credential, although the graph record it keeps may name
the configured database. The configuration file
still needs its `[postgres]` section: parsing is PostgreSQL-only, and
PostgreSQL is the only backend.

For configured graph-registry graphs (`graph_id`, or `project="<graph_id>"`)
these never fall back to `docker`/`podman exec`. A backend outage, missing
database, or unreachable port returns a bounded storage refusal, or a bounded
`storage.error` / per-graph `error` for graph and refresh status. Nothing
starts a container or service, and nothing inspects sources, fetches feeds,
refreshes, initializes, publishes, or repairs the graph. Refresh status reads
only the visible graphs it reports. Legacy JSON-registry projects and explicit
`pg_*` arguments keep their declared ambient libpq authority; they never read
the home's read/status credential.

Outside the setup-owned read/status projection, a configuration that declares
`password_env` or `password_file` reads with that declared credential; ambient
`PGPASSWORD` is used only when the declared variable is unset. A stale or placeholder value in the declared variable is
therefore sent as the password and refused.

`repomap_list_graphs` and `repomap_projects` read configuration only.
`repomap_server_memory_summary` and `repomap_server_memory_search` read the
configured server-memory files through the read-only memory bridge, not the
database. This is a PostgreSQL-backed slice, not the container-free SQLite
Local product, and graph resolution is still PostgreSQL-typed.

Missing-database and failure text depends on the operation and the driver:

- Search (`repomap_search_*`) and graph/refresh status read through the ops
  readback path. With the default Psycopg driver, SQLSTATE `3D000` (or a
  connect-phase catalog probe that finds the database absent) reports
  "…graph database is missing or not initialized…".
- Canonical reads, `repomap_status`, project summary, the configured
  neighborhood, the five language summaries and the six source tools read
  through the shared configured reader. With Psycopg any failure, including a
  missing database, reports the bounded generic
  `psycopg readback failed for <label>`.
- With the non-default `psql` driver and a password (the setup-owned
  read/status credential or a configured `password_env`/`password_file`), a
  failed run reports only `psql readback failed for <label>` on every path.
  Without a password, `psql` shows its bounded error or the missing-database
  mapping.

Run `repomap-kg storage` or the local ops CLI directly when you need the
detailed diagnosis.

## SQLite Local Homes

`mcp serve --repo-map-home <home>` also serves a `[storage] backend = "sqlite"`
home. It needs no PostgreSQL settings, password, `psql` or container; each
graph is read from its own accepted database under
`<home>/state/sqlite-local/graphs/`, opened read-only per tool call. The server
never creates, initializes or refreshes that database; use `ops sqlite-init`
and `ops refresh-graph` first. See [SQLite Local](../../sqlite-local.md).

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
