# RepoMap

RepoMap is a deterministic knowledge graph system for polyglot software
repositories. Its current implementation is a local PostgreSQL-backed product
and reference environment; its long-term broadly accessible commercial
destination is a cloud-first service. The local distribution remains important
for contributors, qualification, power users, and possible private/self-hosted
operation.

The first goal is to map how a repository actually works: entry points, scripts,
source/include relationships, imports, generated artifacts, tests, coverage
targets, environment contracts, and host-mutating operations. The project is
designed for repositories where behavior crosses language boundaries through
shell wrappers, Nix configuration, Python utilities, Ruby scripts, generated
files, and command-line tools. Its target architecture also composes several
explicitly bound source snapshots into one logical graph; that multi-source
model is planned rather than current as-built behavior.

## Project Identity

- Official name: RepoMap
- Git repository: `repo-map`
- Python distribution: `repomap-kg`
- Python import package: `repomap_kg`
- CLI: `repomap-kg`
- Version: `0.0.2` (staging / in development; latest release `0.0.1` on `main`)
- License: AGPL-3.0-or-later plus commercial licensing
- Canonical database: PostgreSQL; the current reference deployment uses a local container
- CI Workflow: `.github/workflows/repomap-release-qualification.yml`
- Product direction:
  [cloud-first with additive multi-source composition](docs/adr/2026/08/0057-cloud-first-multi-source-architecture-reconciliation.md)

## Design Principles

- Deterministic extractors first; no LLM-guessed graph edges.
- Preserve evidence: graph facts should point back to file paths and lines.
- Mark confidence explicitly: extracted, heuristic, manual, or unknown.
- Treat shell, Nix, and process orchestration as first-class concerns.
- Keep raw extractor output exportable as JSONL.
- Store normalized graph data in Postgres.
- Keep logical graph and source identity independent of checkout, worker,
  container, region, and physical database location.
- Keep project-specific conventions in profiles rather than hardcoding them.
- Make the casual local experience folder-backed: configured databases should
  track the current state of their folder tree or repository through RepoMap
  local ops or an authorized agent, without requiring the user to manually
  stitch together discovery JSONL and storage-load commands.

## Contributing

Contribution standards live under [docs/contrib](docs/contrib/README.md).
They cover coding style, testing, dependency review, PR/review expectations,
and contributor AI-agent skills. Operator/runtime RepoMap skills live under
[docs/ops/skills](docs/ops/skills/README.md); the `.agents/skills` and
`.claude/skills` catalogs are active symlink projections of both canonical
skill roots for agent discovery. Projection bodies are never canonical.

Security vulnerabilities should follow the private reporting process in
[SECURITY.md](SECURITY.md), not the public issue process.

ADRs are organized under `docs/adr/YYYY/MM/`. Release notes and change history
are tracked in [CHANGELOG.md](CHANGELOG.md) and [docs/releases](docs/releases/v0.0.1.md).

## Capabilities

RepoMap constructs a queryable, evidence-backed knowledge graph of code structure,
configurations, dependencies, entry points, and operational side effects across
multiple languages:

- **Deterministic Discovery**: Analyzes checkout trees and produces structured
  JSONL observations for source files, entrypoints, shell commands, includes,
  environment variables, host mutations, Python ASTs, and static Nix expressions.
- **Canonical Graph Storage**: Normalizes raw observations into a relational
  canonical graph model stored in PostgreSQL (`canonical_nodes`, `canonical_edges`,
  `canonical_evidence`).
- **Model Context Protocol (MCP) Server**: Exposes stdio MCP tools (`repomap-kg mcp serve`)
  enabling AI coding assistants to query canonical nodes, inspect edge explanations,
  traverse depth-1 neighborhoods, and search graph facts.
- **Local Container Runtime**: Orchestrates local server and database containers
  via `repomap-kg local up/down/status` with non-standard ports and host isolation.
- **Operational CLI**: Provides commands (`repomap-kg ops`) for refreshing
  graphs, inspecting canonical summaries, and reading graph file inventories.

## Supported Extractor Families

- **Python**: AST extraction, module imports, class/function definitions, calls,
  and packaging metadata (`pyproject.toml`, `setup.py`).
- **Go**: Package definitions, imports, module relationships (`go.mod`).
- **Nix**: Static AST-free scanning of Nix expressions, flake outputs, app programs,
  and file references without evaluation.
- **Shell & Scripting**: Conservative static analyzers for Bash, Bats, Zsh,
  Zunit, Awk, and PowerShell (extracting commands, arguments, pipelines,
  dot-sourcing, environment references, and side-effect intent).
- **Configuration & Infrastructure**: Dockerfiles, Docker Compose files,
  and systemd service definitions.
- **Documentation**: Markdown link graphs, HTML structures, and text-based
  reference documents.

## Maturity & Known Limitations

- **Coordinator Interruption Recovery**: Recovery from mid-flight process
  interruption or container restart during active refresh orchestration is
  experimental in v0.0.1. A clean restart or re-indexing is recommended if
  interrupted.
- **Single-Source Local Engine**: While the target architecture is a cloud-first
  multi-source graph platform
  ([ADR 0057](docs/adr/2026/08/0057-cloud-first-multi-source-architecture-reconciliation.md)),
  the current release operates as a single-source, local-checkout engine.
- **Dynamic Semantics**: Highly dynamic language constructs (dynamic `eval`,
  complex runtime reflections) are recorded conservatively as raw observation
  markers rather than guessed canonical edges.
- **Pre-Publication Versioning (`< 0.1.0`)**: Releases prior to `0.1.0` are
  pre-publication development milestones that are **not** published to public
  package registries (PyPI, npm, crates.io, Go proxy, or public container
  registries). The `main` branch tracks verified source preview releases
  (currently `v0.0.1`), while active development PRs target `staging`
  (currently `v0.0.2`).


## Requirements

- Python 3.12 or newer for local development.
- Docker-compatible container runtime for the local RepoMap runtime and
  storage-backed integration tests. Docker is the currently tested default;
  Podman compatibility is intended where the command surface matches.
- Postgres client tools are not required on the host for the local runtime
  lifecycle commands; RepoMap prefers container exec paths for runtime database
  administration.
- Nix is optional. It is useful for this repository's local development setup,
  but RepoMap also runs directly from a Python checkout.

## Installing `repomap-kg`

For source-tree development, run the CLI without installing:

```sh
PYTHONPATH=src/main/python python3 -m repomap_kg --help
PYTHONPATH=src/main/python python3 -m repomap_kg identity --json
```

For an editable Python install, create a virtual environment with the Python you
actually intend to use, then install the checkout:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
repomap-kg --help
```

When Nix and pyenv are both installed, check the command order before creating a
venv or installing packages:

```sh
which -a python python3 pip
```

If pyenv shims are ahead of Nix and you intend to use Nix Python, adjust `PATH`
before creating `.venv`. A pyenv-managed Python can still be invoked through a
separate local alias or explicit shim path, but avoid accidentally mixing a Nix
environment with a pyenv-created virtualenv.

## `REPOMAP_HOME`

Local operations resolve configuration from `REPOMAP_HOME`, defaulting to
`~/.repo-map`. You can also pass `--repo-map-home <dir>` to local and ops
commands.

The config home is a folder, not one giant config file. RepoMap loads TOML files
matching:

- `*.rp.toml` for project/shareable configuration.
- `*.rpl.toml` for local/private machine configuration.

`*.rp.toml` files load first in lexicographic order. `*.rpl.toml` files load
second and overlay local/private values. The generated local setup file name is
`repomap.rpl.toml`.

Do not commit a real local config home, generated runtime secrets, backups,
status artifacts, or private graph data.

## Local Runtime

RepoMap's intended local runtime is an isolated container cluster:

- a RepoMap server/MCP container;
- a RepoMap-owned Postgres container;
- `REPOMAP_HOME` mounted for config and runtime state;
- localhost-only, configurable, non-standard ports.

Basic lifecycle:

```sh
repomap-kg local setup --repo-map-home ~/.repo-map
repomap-kg local up --repo-map-home ~/.repo-map
repomap-kg local status --repo-map-home ~/.repo-map --json
repomap-kg local down --repo-map-home ~/.repo-map
```

`repomap-kg local up` starts the server container in long-running local runtime
mode. That mode runs:

```sh
repomap-kg server serve --repo-map-home /repo-map-home --host 0.0.0.0 --container-internal-bind
```

The generated Compose file maps the server port to localhost only, so the host
can check `http://127.0.0.1:55880/healthz` and `http://127.0.0.1:55880/status`
by default. The `0.0.0.0` bind is allowed only inside the generated container
command so Docker can forward the localhost-bound host port. Direct host runs of
`repomap-kg server serve` default to `127.0.0.1`.

`repomap-kg mcp serve` is still the stdio MCP command for direct MCP clients.
Do not run stdio MCP as the detached server container command: stdin closes in
that setting, so the process exits cleanly. The container runtime uses
`server serve` for liveness/readiness and keeps stdio MCP compatibility intact
for clients that launch the process directly.

Direct Postgres host-port exposure is disabled by default. The server container
connects to Postgres over the internal container network. DBeaver/manual DB
access is a local dev/debug toggle only; when enabled, it binds localhost and
uses the configured non-standard host port. RepoMap status output redacts the
password and points to the local runtime env file instead of printing secrets.

To check container liveness and the local server health endpoint:

```sh
repomap-kg local status --repo-map-home ~/.repo-map --check-containers --json
```

For local source builds of the server image, run from the RepoMap checkout or
set `REPOMAP_SOURCE_ROOT=/path/to/repo-map` so generated Compose files build the
image from the source tree rather than from an installed package location.

## Host-Side Ops With Containerized Postgres

Direct Postgres host-port exposure remains disabled by default. When host-side
ops commands need database readback or refresh loading, they first try the
normal `psql` path. If that cannot reach a configured internal container host
such as `postgres`, RepoMap can use the running RepoMap-owned Postgres container
through `docker exec` or the configured container runtime. The container must be
owned by the same `REPOMAP_HOME` runtime metadata and labels; RepoMap does not
silently use unrelated Postgres containers.

This means these host-side commands work with the local runtime up and direct DB
debug exposure off:

```sh
export REPOMAP_HOME=/path/to/repo-map-home
repomap-kg ops refresh-status --repo-map-home "$REPOMAP_HOME" --graph repo-map --json
repomap-kg ops graph-summary --repo-map-home "$REPOMAP_HOME" --graph repo-map --json
repomap-kg ops refresh-graph --repo-map-home "$REPOMAP_HOME" --graph repo-map --json
```

`--psql-command` remains available as an explicit override for development and
debugging. Prefer the automatic RepoMap-owned container path over enabling direct
DB host-port exposure. If neither host `psql` nor the owned container path is
available, the command reports that direct DB access is disabled, the host
cannot reach the internal Postgres name, and the local runtime should be started
or the local debug toggle enabled deliberately. Never expose Postgres remotely.

## Database Lifecycle

Database lifecycle commands are local administrative CLI operations scoped to
RepoMap-owned runtime containers. They do not use a host-installed Postgres
server and do not require direct DB host-port exposure.

```sh
repomap-kg local db dump --repo-map-home ~/.repo-map --database repomap
repomap-kg local db dump-all --repo-map-home ~/.repo-map
repomap-kg local db backups --repo-map-home ~/.repo-map
repomap-kg local db backup-info <backup-id-or-path> --repo-map-home ~/.repo-map
repomap-kg local db init --repo-map-home ~/.repo-map --database repomap --from-source
repomap-kg local db init --repo-map-home ~/.repo-map --database repomap --from-dump <backup-dir>
repomap-kg local db drop --repo-map-home ~/.repo-map --database repomap --backup-first --yes
```

`drop` is backup-first only: RepoMap must create and verify a dump, manifest,
checksums, and restore note before dropping a database. There is no unbacked
wipe/reset/clear/truncate command.

## Server-Memory Bridge

RepoMap can read the lightweight MCP `server-memory` JSONL card catalog through
an explicit read-only bridge configured by `[server_memory]`. The bridge is for
bounded summaries/search and does not mutate server-memory, rewrite JSONL, or
replace server-memory as the card catalog.

```toml
[server_memory]
enabled = true
path = "/path/to/server-memory/memory.jsonl"
mode = "read_only"
```

Use server-memory for compact pointers to policies, docs, skills, and operating
notes. Use RepoMap graph evidence for generated source/config/readback facts.

## Graph Configuration

Graphs are configured with `[[graphs]]` entries under `REPOMAP_HOME`:

```toml
[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "/path/to/repo-map"
repository_name = "repo-map"
database = "repomap_repo_map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
exclude_paths = [".git", ".serena", "__pycache__", "node_modules"]
```

`database` is optional. If it is absent, graph-scoped operations fall back to
`[postgres].database`. Use graph-specific database names when one Postgres
container stores separate RepoMap databases for separate configured graphs.

`exclude_paths` are relative to the graph root. They are applied before refresh
reads files and are combined with default discovery excludes.

For one logical graph over several local source snapshots, omit the legacy
graph-level source fields and add repeated binding tables. `binding_id` is
derived from graph ID plus alias when omitted:

```toml
[[graphs]]
id = "modular-flake"
name = "Modular Flake"
database = "repomap_modular_flake"
enabled = true
mcp_visible = true
refresh_policy = "manual"

[[graphs.source_bindings]]
schema_version = 1
source_definition_id = "src1:entry"
alias = "entry"
revision = 1
kind = "git-working-tree"
root_path = "<operator-provided-entry-root>"
repository_name = "entry"
logical_root = "."
privacy = "public-dev"
evidence_retention = "metadata-only"
extractor_profile = "default"
resolution_policy = "allow-declared"
role = "entry"

[[graphs.source_bindings]]
schema_version = 1
source_definition_id = "src1:composition"
alias = "composition"
revision = 1
kind = "git-working-tree"
root_path = "<operator-provided-composition-root>"
repository_name = "composition"
logical_root = "."
privacy = "public-dev"
evidence_retention = "metadata-only"
extractor_profile = "default"
resolution_policy = "allow-declared"
role = "composition"
input_name = "composition"
```

Generate the concrete configuration outside the repository. All bindings must
be enabled and use `folder` or `git-working-tree`; one unavailable, unsupported,
or changing binding refuses the complete refresh. See
[Source Ingestion Operations](docs/ops/source-ingestion.md#local-multi-source-graph-refresh)
and [Static Nix Cross-Source Resolution](docs/specs/nix-cross-source-resolution.md).

## Folder-Backed Graph Tracking

RepoMap's intended casual-user default is a database backed by a configured
folder tree or repository. Once a graph is configured under `REPOMAP_HOME`,
RepoMap local ops or an authorized agent should keep the graph database aligned
with the current source state. The user should not need to manually redirect
`discover` output into a JSONL file and then hand-load that file into storage
for routine operation.

Recommended operating model:

```sh
export REPOMAP_HOME=/path/to/repo-map-home

repomap-kg local status --repo-map-home "$REPOMAP_HOME" --check-containers --json
repomap-kg ops config-check --repo-map-home "$REPOMAP_HOME" --json
repomap-kg ops graphs --repo-map-home "$REPOMAP_HOME" --json
repomap-kg ops refresh-preflight --repo-map-home "$REPOMAP_HOME" --graph repo-map --json
repomap-kg ops refresh-graph --repo-map-home "$REPOMAP_HOME" --graph repo-map --json
repomap-kg ops refresh-status --repo-map-home "$REPOMAP_HOME" --graph repo-map --json
repomap-kg ops graph-summary --repo-map-home "$REPOMAP_HOME" --graph repo-map --json
```

For private or large graphs, keep the preflight and drift-check gates from the
maintenance runbook before refreshing. Use graph-scoped refreshes by default.
Use broader refresh commands only when the configured graph set, excludes, and
baselines have been reviewed for that maintenance run.

If a configured graph database must be recreated or dropped to restore
alignment with its source root, use RepoMap's backup-first database lifecycle
commands. Backup dumps, manifests, checksums, and restore notes belong under
`REPOMAP_HOME/backups`. Do not use unbacked wipe/reset/drop/clear/truncate
operations, and do not operate on host-installed or unrelated Postgres.

## First Refresh Runbook

Populate a fresh local runtime one graph at a time. Start with a public or
non-private graph; refresh private or large graphs only after their preflight
and drift gates look intentional.

Recommended first-refresh order:

1. Start or verify the local runtime.
2. Confirm config and graph database routing.
3. Confirm the long-running server health endpoint.
4. Confirm graph database schemas exist.
5. Refresh the first public graph.
6. Inspect the refresh result and filtered refresh status.
7. Run bounded storage or MCP readback against that graph.
8. Confirm other configured graph databases were not refreshed.
9. Refresh remaining graphs later, one at a time, after their configured
   excludes, preflight counts, and baselines have been reviewed.

Example commands:

```sh
export REPOMAP_HOME=/path/to/repo-map-home
repomap-kg local status --repo-map-home "$REPOMAP_HOME" --check-containers --json
repomap-kg ops config-check --repo-map-home "$REPOMAP_HOME" --json
repomap-kg ops graphs --repo-map-home "$REPOMAP_HOME" --json
curl -fsS http://127.0.0.1:55880/status
repomap-kg ops refresh-graph --repo-map-home "$REPOMAP_HOME" --graph <graph-id> --json
repomap-kg ops refresh-status --repo-map-home "$REPOMAP_HOME" --graph <graph-id> --json
```

When direct DB host-port exposure is disabled, host-side refreshes automatically
fall back to the RepoMap-owned Postgres container if the local runtime is up and
the normal host `psql` path cannot reach the internal container hostname. Do not
enable direct DB exposure just to refresh a graph.

Operational notes:

- graph-specific `database` routing keeps each configured graph in its own
  database when configured;
- `exclude_paths` are enforced before discovery reads files;
- server-memory JSONL is handled by the read-only server-memory bridge, not by
  ordinary folder-tree ingestion;
- do not run `refresh-enabled` casually when private graphs are enabled;
- do not commit live refresh output that contains private paths, source
  snippets, secrets, or raw server-memory content.

## Private Graph Hygiene

Preflight private graphs before refreshing them. Preflight walks one configured
graph root, applies default and configured excludes, and reports bounded counts
for files, skips, languages, roles, and extractor categories. It does not load
observations into storage, run source acquisition, mutate source trees, or read
server-memory through the bridge.

Start with the smallest lower-risk private graph, inspect the result, and only
then decide whether to run an actual refresh. Avoid `refresh-enabled` while
private graphs are enabled unless you have deliberately reviewed every graph.

```sh
export REPOMAP_HOME=/path/to/repo-map-home
repomap-kg ops refresh-preflight --repo-map-home "$REPOMAP_HOME" --graph <private-graph-id> --json

# Review counts, configured exclude hit counts, and safety markers.
# Only with explicit approval:
# repomap-kg ops refresh-graph --repo-map-home "$REPOMAP_HOME" --graph <private-graph-id> --json
```

Refresh exactly one private graph per approval and inspect bounded
`refresh-status` and `graph-summary` before touching any other private graph.
For private graphs, summaries redact the root path and report counts by
language, observation kind, canonical node kind, and canonical edge kind
instead of filenames or source snippets. Confirm unrelated graph databases
remain empty or unchanged, keep server-memory bridge readback separate from
folder-tree ingestion, and never commit raw private output, source snippets,
private local config, server-memory JSONL, dumps, backups, credentials, or
secrets.

For Nix-heavy graphs, review the count-only hazard fields for symlinks,
outside-root symlink skips, Nix-store symlink skips, generated-output skips,
secret-like path-name counts, and `path_examples_included=false`. Confirm
`.direnv`, `result`, `result-*`, cache/build output directories, and Nix-store
targets are skipped or absent before refreshing. If a large private graph's
candidate set is dominated by generated output, vendored trees, caches, or
local tool state, add machine-specific excludes to the private `*.rpl.toml`
overlay and rerun `refresh-preflight` until the included file count and
unknown-role count look intentional.

## Manual Graph Maintenance Refreshes

After the first population of all intended graphs, treat refreshes as manual
maintenance events. Do not start with `refresh-enabled`; pick exactly one
graph, preflight it, compare the candidate set to the last known baseline,
refresh only that graph if the gate still looks safe, and then inspect bounded
readback.

Stop before refreshing if any preflight signal drifts suspiciously:

- included file count or unknown-role count jumps unexpectedly;
- secret-like path-name count, symlink count, or generated-output count grows;
- configured exclude hit counts disappear for paths that should be excluded;
- diagnostics are new or no longer clearly benign;
- private root display is not redacted;
- any safety marker reports storage writes, source acquisition, source tree
  mutation, server-memory mutation, destructive DB actions, remote exposure,
  or a watch daemon.

Use `ops baseline-save` to record the last accepted stored readback and/or
preflight candidate set for one graph, `ops drift-check` to compare current
state against those explicit baselines before a maintenance refresh, and
`ops baseline-prune` for retention. `drift-check` exits `0` on match and `2`
on drift; treat drift as a stop-and-review gate. Baseline files live under
`$REPOMAP_HOME/status/baselines/<graph>/<stored|preflight>/` and are private
local operational state, not public repository artifacts; never store raw
observations, source snippets, dumps, server-memory JSONL, credentials, or
unbounded path lists as baselines.

The detailed maintenance workflow — baseline lifecycle, drift-gate commands,
and per-run hygiene — lives in the `repomap-cli-workflow` skill under
[docs/ops/skills](docs/ops/skills/README.md). For each maintenance run, verify
all other graph databases remain unchanged, keep direct DB host-port exposure
disabled unless deliberately debugging locally, and use the backup-first
lifecycle commands before any destructive database action. Commit only bounded
audit notes; never commit raw private graph output, source snippets, private
local config, DB dumps, backups, credentials, or secrets.

## Development

Run the CLI from the source tree:

```sh
PYTHONPATH=src/main/python python3 -m repomap_kg --version
PYTHONPATH=src/main/python python3 -m repomap_kg identity --json
PYTHONPATH=src/main/python python3 -m repomap_kg discover . --jsonl
PYTHONPATH=src/main/python python3 -m repomap_kg discover . --profile repomap-profile.toml --jsonl
PYTHONPATH=src/main/python python3 -m repomap_kg entrypoints raw-observations.jsonl
PYTHONPATH=src/main/python python3 -m repomap_kg files raw-observations.jsonl --role source
PYTHONPATH=src/main/python python3 -m repomap_kg host-mutators raw-observations.jsonl --category service-management --tool launchctl --json
PYTHONPATH=src/main/python python3 -m repomap_kg host-mutators-summary raw-observations.jsonl --json
PYTHONPATH=src/main/python python3 -m repomap_kg observations normalize raw-observations.jsonl --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage load-files raw-observations.jsonl --repository-name repo-map --root-path . --json
PYTHONPATH=src/main/python python3 -m repomap_kg ops graph-files --graph repo-map --role source --json
PYTHONPATH=src/main/python python3 -m repomap_kg ops graph-files --graph repo-map --role entrypoint --observation-state observed --json
PYTHONPATH=src/main/python python3 -m repomap_kg ops graph-files --graph repo-map --path README.md --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage nodes --root-path . --kind file --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage nodes --legacy --root-path . --kind shell.command --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage neighborhood --root-path . --node tool:nix --direction in --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage neighborhood --legacy --root-path . --node node:bin/tool:shell.command:bin/tool#call:nix-build --direction out --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage file-neighborhood --root-path . --path bin/tool --direction out --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage file-neighborhood --legacy --root-path . --path bin/tool --direction out --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage edges --root-path . --kind executes --target-key tool:nix --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage edges --legacy --root-path . --kind shell.command --target-node tool:nix --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage host-mutators --root-path . --category filesystem-mutation --tool rm --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage host-mutators --legacy --root-path . --category filesystem-mutation --tool rm --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage host-mutators-summary --root-path . --category filesystem-mutation --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage host-mutators-summary --legacy --root-path . --category filesystem-mutation --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage summary --root-path . --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage summary --legacy --root-path . --json
PYTHONPATH=src/main/python python3 -m repomap_kg storage explain-canonical-edge --root-path . --source-key file:bin/tool --kind executes --target-key tool:nix --json
```

`storage summary` is canonical-aware by default; use `--legacy` when the older
observation-derived summary shape is required.
`storage nodes`, `storage edges`, `storage neighborhood`,
`storage file-neighborhood`, `storage host-mutators`, and
`storage host-mutators-summary` are canonical by default; use `--legacy` when
the older observation-derived stable-key output is required. For
`storage neighborhood`, `--node` expects a canonical key by default. For
`storage file-neighborhood`, `--path` maps to the durable canonical
`file:<path>` node by default. `storage host-mutators` now reports canonical
`mutates_host` and `host_mutation_intent` edges by default, excluding adjacent
`network_intent` and `package_intent` edges; `host_mutation_intent` is source
or configuration intent, not runtime proof. `storage host-mutators-summary`
now groups by category and edge_kind and uses named canonical count fields such
as source_count and canonical_edge_count instead of the legacy `count` field.
LOCAL32 removes `storage files`. Use `ops graph-files --graph <graph-id>` for a
bounded canonical file projection selected through operations configuration;
the replacement defaults to 50 records and accepts at most 200 records per
page. LOCAL35 removes `storage entrypoints` without an alias or fallback; use
`ops graph-files --graph <graph-id> --role entrypoint --observation-state
observed` for stored entrypoint-role files. The top-level `entrypoints` command
remains available for explicitly named raw-observation JSONL. LOCAL38 removes
`storage file-nodes` without an alias or fallback. Use `ops graph-files
--graph <graph-id> [--path <repo-relative-path>]` for bounded canonical file
inventory, `storage file-neighborhood` or `storage neighborhood` for canonical
context, and `storage explain-canonical-edge` for evidence behind a selected
canonical edge. Explicit raw-observation access remains separately named and
bounded. The entrypoint-role filter is a canonical file-inventory projection,
not a cross-language canonical entrypoint semantic model.

Run the host-safe test suites with coverage gates:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int --pg-container-port 55433
python3 tools/run_tests.py --suite smoke
python3 tools/run_tests.py --suite staging --hygiene-profile heavy \
  --declared-complete-gates 1 --pg-container-port 55433
```

Add `--report` to retain a static offline HTML report beneath the exact test
run's private evidence root. An explicit `--report-dir` still selects a
caller-owned report destination.

The project runner uses pytest for test execution and coverage.py for serial
line and branch coverage. Unit fails below 85 percent statement or 85 percent branch
coverage (settled in REPOMAP-CI2A-R4D). Integration fails below 80 percent statement or branch coverage.
The staging composition runs substantial smoke first and integration second,
fail-fast; it never reruns unit and has no combined coverage owner.

The testing policy and staged pytest migration plan are documented in
[RepoMap Test Runner Policy](docs/testing/test-runner-policy.md) and
[RepoMap Testing Standards](docs/contrib/testing-standards.md). Development
tasks run proportional local verification (affected unit/integration tests,
compile/static checks, and diff checks). Routine exhaustive correctness
verification is owned by hosted CI (the `staging-integration-gate` job in
`repomap-release-qualification`), while the local
staging composition remains supported for explicit operator diagnostics and
qualification campaigns:

```sh
python3 tools/run_tests.py --suite staging --hygiene-profile heavy \
  --declared-complete-gates 1 --pg-container-port 55433
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

TEST-SMOKE1 adds the containerized smoke suite from
[Containerized Smoke Test Design](docs/testing/containerized-smoke-test-design.md).
`--suite smoke` is pass/fail only and not coverage-tracked. `--suite staging`
fails immediately when smoke is red, then runs integration at its 80/80 gate.
Canonical smoke ensures or reuses a dependency-only
`repomap-test-runtime:*` cache through the repository-owned image manager and
then runs the current checkout from a read-only mount. It initializes and
refreshes two tiny graphs against an exact run-owned PostgreSQL container,
performs product readback, executes backup-first destruction of one graph,
inspects the run-owned dump, proves the other graph remains coherent, and
cleans every exact run-owned Docker and filesystem resource. One monotonic
budget covers the entire lifecycle and bounded cleanup, with a 540-second
configured ceiling. The configured exact
Python repository digest is reused locally or pulled exactly once on a miss
under the image-manager lock; mutable tags and fallback resolution never grant
network authority. No broad prune path is used. An explicit exact image-ID
override remains available for bounded diagnosis.

Image builds and image acquisitions inside a runner process pass through one
canonical authority; the enforced surfaces, the honest limits of that closure,
and the checkout-scoped lock semantics are recorded in
[Managed Docker Mediation Boundary](docs/testing/managed-docker-mediation-boundary.md).

After installing the test and SCALE operational-tooling extras, scoped pytest
arguments can be forwarded through the public runner after `--` for
development checks:

```sh
python3 -m pip install -e '.[test,scale-tools,static-analysis]'
python3 tools/run_tests.py --suite unit -- -k graph_baseline
python3 tools/run_tests.py --suite int --pg-container-port 55433 -- -k postgres
```

The shipped package dependency set remains smaller: `scale-tools` is required
only when repository-owned SCALE resource sampling or its tests are imported.

Scoped runs are not a substitute for the required independent unit and staging
gates before commits. The unit hard gate is 85/85; integration is hard 80/80
and retains advisory warnings below 85 percent.

Unit tests also support opt-in parallel execution for fast development checks:

```sh
python3 tools/run_tests.py --suite unit --jobs auto --no-coverage
```

Parallel runs require `--no-coverage` because pytest-xdist coverage
aggregation is not enabled. Serial coverage.py runs remain authoritative.
Integration and staging parallel runs are disabled until the containerized
Postgres harness and shared integration state are proven safe under xdist.

## Specifications

- [Architecture](docs/specs/architecture.md)
- [Storage Model](docs/specs/storage-model.md)
- [Extractor Strategy](docs/specs/extractor-strategy.md)
- [PowerShell Extraction Design](docs/extraction/powershell-extraction-design.md)
- [Bash Extraction Design](docs/extraction/bash-extraction-design.md)
- [Bats Extraction Design](docs/extraction/bats-extraction-design.md)
- [Awk Extraction Design](docs/extraction/awk-extraction-design.md)
- [Zsh Extraction Design](docs/extraction/zsh-extraction-design.md)
- [Zunit Extraction Design](docs/extraction/zunit-extraction-design.md)
- [Project Profile Schema](docs/specs/profile-schema.md)
- [Raw Observation Schema](docs/specs/raw-observation-schema.md)
- [Roadmap](docs/specs/roadmap.md)

## License

Future RepoMap releases are licensed under the GNU Affero General Public
License v3.0 or later. See [LICENSE](LICENSE).

Commercial licenses are available for proprietary terms, including
closed-source embedding, private SaaS deployments, OEM use, support, warranty,
indemnity, and custom commercial terms. See
[COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

The final Apache-2.0 RepoMap source state is preserved for publication in
[`lair001/repo-map_apache-2.0-final`](https://github.com/lair001/repo-map_apache-2.0-final).
Code released under the Apache License, Version 2.0 remains available under
that license. Those prior grants are not revoked by the later licensing model.
