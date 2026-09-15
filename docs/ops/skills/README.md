# RepoMap Operator Skills

This directory holds public AI-agent skills for configuring, operating,
using, or maintaining RepoMap MCP and local folder-backed graph workflows.

Current operator skills:

- `repomap-cli-workflow`: folder-backed graph maintenance, refresh and drift
  gates, canonical CLI readback, backup-first database lifecycle, and source
  ingestion routing.
- `repomap-mcp-configuration`: read-only MCP server configuration, registry
  shape, environment, and resolution rules.
- `repomap-mcp-readback`: read-only MCP query workflow over canonical graph,
  search, source/feed, and summary tools.
- `repomap-mcp-smoke-test`: post-configuration MCP verification checklist.

Contributor and development skills live under `docs/contrib/skills/`. Durable
operations references, such as
[Source Ingestion Operations](../source-ingestion.md), live under
`docs/ops/`. The repository's `.agents/skills` and `.claude/skills` catalogs
are active relative-symlink discovery projections. Canonical skill bodies
remain under `docs/`; projection bodies are never canonical.
