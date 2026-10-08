---
name: repomap-cli-workflow
description: Use when operating RepoMap outside MCP to maintain folder-backed graph databases, refresh configured graphs, check drift against baselines, query canonical CLI readback, run backup-first database lifecycle commands, or route explicit source ingestion.
---

# RepoMap CLI Workflow

## Overview

Operate RepoMap as a local repository graph builder and readback surface. The
default operating model is folder-backed: graphs configured under
`REPOMAP_HOME` are backed by local folder trees or repositories, and RepoMap
local ops keep each graph database aligned with its root. Extraction, refresh,
ingestion, and database lifecycle operations happen through this CLI workflow;
MCP is a separate read-only query surface.

`REPOMAP_HOME` defaults to `~/.repo-map`. Ops commands also accept
`--repo-map-home <dir>`.

## Non-Goals

- MCP server configuration and registry shape: use `repomap-mcp-configuration`.
- MCP tool-by-tool query procedure: use `repomap-mcp-readback`.
- Post-configuration MCP verification: use `repomap-mcp-smoke-test`.
- Phase, commit, ADR, and status-record conventions: use
  `repomap-phase-hygiene`.

## Folder-Backed Default

1. Configure one or more `[[graphs]]` entries under `REPOMAP_HOME`, each with
   a graph id, root path, repository name, optional graph-specific database,
   privacy level, and `exclude_paths`.
2. Start or verify the local runtime (`repomap-kg local up`,
   `repomap-kg local status --check-containers --json`).
3. Maintain graphs with graph-scoped ops commands.
4. Prefer the configured graph identity over ad hoc root/database arguments.

## Standard Maintenance Flow

```sh
export REPOMAP_HOME=/path/to/repo-map-home
repomap-kg local status --repo-map-home "$REPOMAP_HOME" --check-containers --json
repomap-kg ops config-check --repo-map-home "$REPOMAP_HOME" --json
repomap-kg ops graphs --repo-map-home "$REPOMAP_HOME" --json
repomap-kg ops refresh-preflight --repo-map-home "$REPOMAP_HOME" --graph <graph-id> --json
repomap-kg ops refresh-graph --repo-map-home "$REPOMAP_HOME" --graph <graph-id> --json
repomap-kg ops refresh-status --repo-map-home "$REPOMAP_HOME" --graph <graph-id> --json
repomap-kg ops graph-summary --repo-map-home "$REPOMAP_HOME" --graph <graph-id> --json
```

Refresh one selected graph at a time. Preflight walks the graph root, applies
excludes, and reports bounded counts and safety markers without loading
anything. Treat unexpected preflight drift — file counts, secret-like path
counts, symlink or generated-output counts, missing exclude hits — as a
stop-and-review gate. Use `ops refresh-enabled` only after deliberately
reviewing every enabled graph, its excludes, and its baselines.

Refresh result/status JSON is operator-local output and is not safe to share.
Legacy `public-dev` retains physical root fields; `config_path` is serialized
independently even when a private mode redacts roots. The name `public-dev` is
not a promise of path-free output. See the
[field-by-mode contract](../../operator-local-refresh-output.md) before sharing
any projection. A distinct explicitly selected shareable projection is deferred.

## SQLite Local Homes (Step 4, First Slice)

A home with `[storage] backend = "sqlite"` is a SQLite Local home: no
`[postgres]`, `[runtime]`, credentials, `psql` or Docker. Its supported
maintenance commands (all `--repo-map-home <home>`) are:

- `ops config-check [--check-db]` and `ops graphs [--check-db]`: validation and
  inventory; `--check-db` adds a read-only per-graph readiness state and never
  creates a database;
- `ops sqlite-init --graph <id>`: explicit creation at the current schema
  (v2), never a reinitialization and never an upgrade of an older database;
- `ops refresh-preflight --graph <id>`: source inspection only;
- `ops refresh-graph --graph <id>`: direct mode only; `--mode coordinator` is
  refused by design (`sqlite-local-refresh-rejects-coordinator-mode`);
- `ops refresh-enabled`: every enabled graph in configuration order, each a
  separate direct refresh;
- `ops sqlite-backup --graph <id> --output <new-or-empty-dir>`: a verified
  backup/export (`graph.sqlite3` plus a path-free `manifest.json` bound to the
  exact accepted generation and bundle id), taken online under the publisher
  lock; refuses while a refresh holds the graph;
- `ops sqlite-restore --graph <id> --backup <dir>`: verifies the whole backup,
  then restores only into an absent graph database; it never replaces an
  existing one (that is a separate destructive recovery decision). A v1 backup
  restores as v1 (`schema-behind`) and is not upgraded;
- `ops sqlite-upgrade --graph <id> --backup-output <new-or-empty-dir>`: the
  only schema migration. An exact older schema (`schema-behind` in
  `--check-db`) is backed up and the backup verified before one transaction
  moves it to v2; the accepted generation and bundle are unchanged. A current
  database is `already-current` with no backup. There is no downgrade; restore
  the backup to roll back. On `graph-migration-reconciliation-required`, rerun
  the upgrade with a new empty `--backup-output` instead of restoring;
- `ops sqlite-cleanup --graph <id> [--yes]`: a dry run by default. `--yes`
  removes only expired terminal retained attempts (graph-local and pre-LOCAL3
  shared) and stale or partial orphan `.init-*`/`.restore-*` temporaries, then
  syncs `state/` and the home. Unsettled or record-less attempts and
  recoverable orphans are kept and reported, and any unsafe item refuses the
  whole run. There is no force mode.

These run without the PostgreSQL driver installed and never read a source root
for backup, restore, upgrade or cleanup. Other PostgreSQL-only `ops` commands (including the
PostgreSQL `local db` backup commands) refuse the home with
`sqlite-local-home-requires-local-command`. Never copy a live database file by
hand; use `ops sqlite-backup`. See [SQLite Local](../../sqlite-local.md).

## Setup-Owned Host Readback Authority

With native local mode and direct host PostgreSQL exposure enabled, supported
home-selected readbacks use `repomap_read_status` and its setup-owned private
`runtime/.env` secret. This includes refresh status, graph summary, graph files,
source edges and canonical edge explanations. No manual password export is needed;
readback never creates or rewrites role secrets. Missing or unsafe authority refuses.

For the exact setup-default connection, ambient `PGPASSWORD` and
`REPOMAP_PG_PASSWORD` no longer select admin credentials for these readbacks.
Explicit literal/password-file credentials and custom user/password-environment
configurations retain their configured authority. Remote/custom connections are
not projected to local runtime secrets.

Use `storage edges --repo-map-home "$REPOMAP_HOME" --graph <graph-id> --kind sources`
and `storage explain-canonical-edge --repo-map-home "$REPOMAP_HOME" --graph <graph-id>`
with the edge identity arguments. Graph selection uses the stable configured
repository identity, including refresh publications whose root is `graph:<graph-id>`.

## Baselines And Drift Gates

Use `ops baseline-save --graph <graph-id> --kind both --json` to record the
last accepted stored summary and preflight candidate set under
`$REPOMAP_HOME/status/baselines/<graph>/<stored|preflight>/`. Before a
maintenance refresh, compare with:

```sh
repomap-kg ops drift-check --repo-map-home "$REPOMAP_HOME" --graph <graph-id> \
  --baseline-file "$REPOMAP_HOME/status/baselines/<graph-id>/stored/latest.json" \
  --include-preflight \
  --preflight-baseline-file "$REPOMAP_HOME/status/baselines/<graph-id>/preflight/latest.json" \
  --json
```

`drift-check` exits `0` on match and `2` on drift; it never refreshes
anything. Prune retained baselines with `ops baseline-prune` (dry-run by
default; `--yes` to delete), never with shell `rm` loops. Baseline files are
private local operational state; do not commit them.

## Bounded File Inventory

`ops graph-files --graph <graph-id>` lists bounded canonical file nodes for
one configured graph. It defaults to 50 records, accepts at most 200 per page,
and filters by `--path`/`--path-prefix`, `--language`, `--role`,
`--generated`, `--executable`, `--observation-state`, and `--ambiguity`. Use
`--role entrypoint --observation-state observed` for stored entrypoint-role
inventory. Do not supply absolute roots or direct database arguments.

## Low-Level Developer Path

Manual discovery/load remains useful for disposable tests, fixtures,
debugging, and source development — not for routine folder-backed operation:

```sh
repomap-kg discover <repo-root> --jsonl > <workdir>/observations.jsonl
repomap-kg storage load-files <workdir>/observations.jsonl \
  --repository-name <name> \
  --root-path <repo-root> \
  --pg-database <database>
```

## Canonical CLI Readback

Canonical graph identity is the default output model:

```sh
repomap-kg storage summary --root-path <repo-root> --json
repomap-kg storage nodes --root-path <repo-root> --kind <node-kind> --json
repomap-kg storage edges --root-path <repo-root> --kind <edge-kind> --json
repomap-kg storage neighborhood --root-path <repo-root> --node <canonical-key> --direction both --json
repomap-kg storage file-neighborhood --root-path <repo-root> --path <repo-relative-path> --direction both --json
repomap-kg storage host-mutators --root-path <repo-root> --category <category> --json
repomap-kg storage host-mutators-summary --root-path <repo-root> --category <category> --json
repomap-kg storage explain-canonical-edge --root-path <repo-root> --source-key <key> --kind <kind> --target-key <key> --json
```

Pass `--legacy` on `summary`, `nodes`, `edges`, `neighborhood`,
`file-neighborhood`, `host-mutators`, and `host-mutators-summary` only when a
workflow still needs the older observation-derived stable-key shapes. For
`storage neighborhood`, `--node` expects a canonical key by default; for
`storage file-neighborhood`, `--path` maps to the durable canonical
`file:<path>` node. `storage host-mutators` projects canonical `mutates_host`
and `host_mutation_intent` edges; intent edges are source or configuration
intent, not runtime proof.

Domain summaries provide bounded aggregate readback per extraction family:
`storage ruby-summary`, `js-summary`, `js-framework-summary`,
`openapi-summary`, `terraform-summary`, `python-summary`, `nix-summary`,
`email-summary`, `bulk-summary`, and `api-summary`.

Report canonical keys such as `file:<path>` and `python.module:<module>` as
graph identity. Do not present database integer ids, legacy stable keys, raw
observation source ids, or line numbers as canonical identity; line spans and
extractor versions belong to evidence readback.

## Database Lifecycle Boundary

Database lifecycle commands are local administrative operations scoped to
RepoMap-owned runtime containers:

```sh
repomap-kg local db dump --repo-map-home <home> --database <database>
repomap-kg local db dump-all --repo-map-home <home>
repomap-kg local db backups --repo-map-home <home>
repomap-kg local db backup-info <backup-id-or-path> --repo-map-home <home>
repomap-kg local db backup-inspect <backup-id-or-path> --repo-map-home <home>
repomap-kg local db restore-all --repo-map-home <home> --from-dump <backup-dir>
repomap-kg local db init --repo-map-home <home> --database <database> --from-source
repomap-kg local db upgrade-schema --repo-map-home <home> --database <database> --backup-first --yes
repomap-kg local db drop --repo-map-home <home> --database <database> --backup-first --yes
```

`drop` is backup-first only: RepoMap creates and verifies a dump, manifest,
checksums, and restore note before dropping. There is no unbacked
wipe/reset/clear/truncate operation. Dumps and manifests belong under
`REPOMAP_HOME/backups`. Do not operate on host-installed or unrelated
Postgres.

## Source Ingestion Routing

Explicit, policy-approved source configs acquire non-folder artifacts into
RepoMap-owned locations under the target root. Acquisition commands are
versioned acquisition-only surfaces: they report `graph_mutated=false`, never
mutate final graph state or freshness, and are free of arbitrary
model-selected URLs. Publication into a graph happens separately through the
normal storage/refresh path.

- `sources ingest-feed --config <feed-source.toml> --root-path <root>` — one
  configured feed;
- `sources import-archive --config <config> --root-path <root>` — one local
  saved-page source;
- `sources import-warc --config <config> --root-path <root>` — one local WARC
  source;
- `bulk plan --config <config>` / `bulk import --config <config> --root-path
  <root>` — one local corpus;
- `api plan --config <config>` / `api acquire --config <config> --root-path
  <root>` — one documented REST API source (fixture-only acquisition);
- `github plan --config <config>` / `github acquire --config <config>
  --root-path <root>` — one GitHub REST fixture source.

Detailed current-state procedure, config requirements, and per-family safety
boundaries live in the durable reference
[Source Ingestion Operations](../../source-ingestion.md).

Do not execute target repository code, fetch URLs outside an explicitly
configured ingestion command, resolve credentials, call live provider APIs, or
treat MCP as a write surface.

## Container Image Safety

Until RepoMap implements role/retention image labels and a repository-owned
cleanup command, remove only an exact image reference or ID created by the
current authorized task, after proving no container references it. Do not use
global prune or heuristic deletion of pre-existing RepoMap-like images. Treat
the long-lived deployment cluster and its images as protected unless the
operator explicitly authorizes lifecycle work. See
[Container Lifecycle Requirements](../../container-lifecycle-requirements.md)
for the current audit and future contract.

## Handoff To MCP

Configure the read-only MCP surface only after storage exists and CLI readback
works, using `repomap-mcp-configuration`, then verify with
`repomap-mcp-smoke-test`.
