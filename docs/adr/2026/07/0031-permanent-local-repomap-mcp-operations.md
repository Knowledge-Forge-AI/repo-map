# ADR 0031: Permanent Local RepoMap MCP Operations

## Status

Accepted

Superseded in part by ADR 0032 for local runtime, `REPOMAP_HOME`,
config-folder, ops-config format, containerized Postgres, and integration-test
Postgres harness details. ADR 0031 remains the higher-level architecture for
graph registry, read-only MCP readback, refresh boundaries, server-memory
relationship, operational policy dogfooding, and destructive-operation
exclusions unless a later ADR supersedes those sections.

Superseded in part by ADR 0057 for long-term product delivery, immediate
multi-source graph composition, and separation of logical graph authority from
physical database placement. ADR 0031's local service, privacy, read-only MCP,
and operational safety contracts remain the current/reference local
distribution; local-first is no longer the settled commercial destination.

## Date

2026-07-02

## Authoritative References

- ADR 0001: Graph Identity Model
- ADR 0002: Canonical Key Grammar And Relationship Vocabulary
- ADR 0003: Canonicalization Pipeline, Storage Transition, And Replay Strategy
- ADR 0010: Structured Configuration Graph Model
- ADR 0014: Source Ingestion Architecture
- ADR 0015: Feed Graph Model
- ADR 0023: Bulk Local Corpus Ingestion
- ADR 0024: Documented API Ingestion Architecture
- ADR 0025: GitHub API Provider Architecture
- `docs/status/2026/06/29/00009-m1-mcp-readonly-exit.md`
- `docs/status/2026/06/29/00014-mp1-multi-project-mcp-exit.md`
- `docs/status/2026/06/30/00034-mcp-ing0-read-only-source-feed-mcp-exit.md`
- `docs/status/2026/07/01/00063-py3-python-readback-dogfooding-exit.md`
- `docs/status/2026/07/01/00060-tfhcl2-terraform-readback-polish-exit.md`
- `docs/status/2026/07/01/00058-openapi2-readback-polish-exit.md`
- `docs/status/2026/07/01/00056-js6-framework-readback-polish-exit.md`

## Context

RepoMap has grown from deterministic local repository extraction into a
Postgres-backed knowledge graph with canonical storage, read-only CLI readback,
multi-project MCP readback, configured source ingestion, API acquisition
architecture, and focused summaries for JavaScript, Python, Terraform, OpenAPI,
feeds, and other static evidence.

The existing MCP surface is deliberately small and read-only. M1 exposed
canonical readback over MCP. MP1 added a local multi-project registry so MCP
callers can select named graphs without repeating connection arguments.
MCP-ING0 added read-only source/feed inspection for already-ingested RSS2 data.
These phases proved the local MCP pattern, but RepoMap still lacks a complete
architecture for permanent daily operation as a local knowledge-graph service.

The intended local operating environment includes several configured graph
roots:

- `repo-map`, for product development and dogfooding;
- `codex-vc`, for private operational docs, policies, prompts, and local
  Codex state;
- `codex-memories`, for local memory files and durable user/project context;
  and
- `flakes`, for a useful but intentionally noisy Nix/dotfiles graph.

RepoMap also needs to coexist with the lightweight `server-memory` MCP server
from the official MCP servers repository. In the current local workflow,
server-memory acts as a compact card catalog that points to docs, skills,
policies, and operational reminders. RepoMap should complement that card
catalog with generated evidence-rich graphs over local source trees and
artifacts. It should not declare server-memory obsolete.

Configuration is also becoming a product boundary. RepoMap has historically
used multiple configuration surfaces: JSON for some MCP/project registry
configuration, TOML for project profiles, feeds, and GitHub/API acquisition,
and CLI/environment settings for local storage. Permanent local operation needs
one primary human-authored TOML control plane while preserving compatibility
with existing JSON and source-specific TOML formats until a later migration
phase.

MCP-OPS0 is architecture only. It does not implement service mode, config
loading, graph registry changes, refresh watchers, MCP tools, server-memory
bridges, private-root reads, local service files, tunnel configuration,
destructive database commands, web UI, public default changes, or Phase F
migration.

## Decision

RepoMap will define a future permanent local operations mode centered on:

- a local service process;
- a versioned unified TOML configuration file;
- a config-driven graph registry;
- local Postgres storage;
- manual and eventually automated refresh of configured graphs;
- an expanded read-only MCP product surface;
- an optional read-only server-memory bridge; and
- local-only, privacy-aware defaults.

The future pipeline is:

```text
repomap.local.toml
-> service and Postgres profile validation
-> graph registry validation
-> configured graph refresh or status query
-> existing discovery, extraction, source-ingestion, storage, and readback paths
-> expanded read-only CLI/MCP summaries and explanations
-> optional read-only server-memory catalog linkage
```

This pipeline is local-first and evidence-first. A RepoMap service may update
configured graph data because the user wants local graphs to stay current, but
the service must not mutate source trees, edit operational policy files, expose
secrets, run destructive database administration, or publish a remote interface
by default.

## Scope

In scope:

- permanent local RepoMap service architecture;
- unified TOML configuration architecture;
- migration posture from existing JSON and source-specific TOML configs;
- local Postgres profile and bootstrap posture;
- graph registry model;
- configured local graph roots;
- refresh and watch architecture;
- richer read-only MCP product surface;
- server-memory relationship;
- operational policy dogfooding path;
- network, tunnel, and security posture;
- destructive-operation exclusions;
- development-mode credential posture; and
- future phase plan and test expectations.

Out of scope:

- implementing the persistent service;
- implementing unified TOML config loading;
- removing old config support;
- implementing a new graph registry;
- implementing watchers;
- implementing expanded MCP tools;
- implementing a server-memory bridge;
- editing private operational policy files;
- reading private roots such as `~/.codex` or `~/.flakes`;
- creating tunnels;
- configuring ngrok or any alternative tunnel;
- exposing Postgres remotely;
- adding a web UI;
- adding database wipe, reset, drop, truncate, or clear commands;
- changing public readback defaults; and
- Phase F migration.

## Hard Guardrails

MCP-OPS0 must not:

- implement code;
- modify private codex-vc files;
- read `~/.codex` or `~/.flakes`;
- create or edit live local service files;
- expose secrets;
- add write or destructive MCP tools;
- add database wipe, reset, drop, truncate, or clear commands;
- add web UI scope;
- assume remote access is safe;
- recommend exposing local dev credentials through a tunnel;
- treat server-memory as obsolete;
- assume the `flakes` graph will parse cleanly; or
- remove or break existing JSON or TOML config formats.

Future implementation phases must preserve these boundaries unless a later ADR
explicitly accepts a narrower exception.

## Product Posture

MCP-OPS0 is not "build the whole local operations system." MCP-OPS0 is "draw
the safe architecture boundary for a permanent local RepoMap knowledge-graph
service and unified TOML control plane."

RepoMap should become useful in daily Codex and later ChatGPT operations by
making local project evidence easy to query. It should remain:

- local-first;
- deterministic;
- readback-oriented;
- privacy-aware;
- explicit about configured graph roots;
- conservative around private sources;
- no-fetch unless a configured source-ingestion phase explicitly allows
  acquisition; and
- free of destructive product or MCP database-administration commands.

## Permanent Local Service Model

A future local service mode may look like:

```sh
repomap-kg service run --config <config>
```

The exact command is deferred, but the service model should support:

- local machine operation;
- an explicit config file;
- a local Postgres connection profile;
- a configured graph registry;
- refresh policies;
- read-only MCP serving;
- health and status commands;
- bounded logs suitable for local debugging; and
- no destructive storage actions.

The service model should not require:

- a web UI;
- a cloud service;
- a public tunnel;
- direct remote database exposure;
- package-manager installs at runtime; or
- global mutable state hidden from configuration.

The service should distinguish these operations:

- `status`, which reports configuration, storage, and graph freshness;
- `refresh`, which updates configured graph data through existing RepoMap load
  paths;
- `serve-mcp`, which exposes bounded read-only graph query tools; and
- `diagnose`, which reports config, storage, and extraction issues without
  leaking secrets.

## Unified TOML Configuration

RepoMap should converge on one primary human-authored operations config:

```text
repomap.local.toml
```

`repomap.local.toml` is the preferred private machine-specific control plane
for permanent local operations. It should be gitignored by default and may
contain local paths, local service choices, privacy classifications, and
references to local secret sources.

RepoMap may also support:

```text
repomap.toml
```

`repomap.toml` is appropriate for non-secret project-local configuration that a
repository owner intentionally commits. It should not contain private paths,
literal credentials, or local-only operational policy.

A future committed example should use a safe name such as:

```text
examples/repomap.local.example.toml
```

The example must avoid real secrets, real private paths, and live service
exposure. It may show local-dev placeholders only when clearly marked.

The unified TOML config should eventually cover:

- service settings;
- Postgres connection profile;
- graph registry entries;
- graph root paths;
- graph privacy classifications;
- include and exclude patterns;
- extractor profiles;
- refresh and watch policies;
- MCP visibility flags;
- RSS and feed sources;
- GitHub source configuration;
- documented API source configuration where applicable;
- server-memory bridge settings; and
- logging and status settings.

The config schema must be versioned. Unknown or unsupported sections should
produce clear diagnostics. Unknown secret-bearing fields should be redacted
before display.

## Example Future Config Shape

This example is illustrative architecture, not an implemented format:

```toml
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "admin"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "/path/to/repo-map"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[[graphs]]
id = "codex-vc"
name = "Codex VC"
root_path = "~/.codex/codex-vc"
repository_name = "codex-vc"
privacy = "private-ops"
enabled = false
mcp_visible = false
extractor_profile = "private-ops"
refresh_policy = "manual"

[[graphs]]
id = "codex-memories"
name = "Codex Memories"
root_path = "~/.codex/memories"
repository_name = "codex-memories"
privacy = "private-memory"
enabled = false
mcp_visible = false
extractor_profile = "private-memory"
refresh_policy = "manual"

[[graphs]]
id = "flakes"
name = "Flakes"
root_path = "~/.flakes"
repository_name = "flakes"
privacy = "private-config"
enabled = false
mcp_visible = false
extractor_profile = "nix-config"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"

[[sources.feed]]
id = "example-feed"
graph_id = "repo-map"
url = "https://example.invalid/feed.xml"
enabled = false

[[sources.github]]
id = "example-github"
graph_id = "repo-map"
owner = "example"
repo = "repo"
mode = "public_readonly"
enabled = false
```

Literal passwords should not appear in committed examples. Local development
may use classic dev credentials only in ignored local config, and only while
the database is bound to localhost.

## Config Migration Policy

MCP-OPS0 defines the architecture only.

MCP-OPS1 should implement unified TOML config loading while preserving existing
config formats:

- existing JSON repo/MCP registry config remains compatible;
- existing project profile TOML remains compatible;
- existing feed, GitHub, and documented API TOML configs remain compatible;
- diagnostics may point users toward the unified TOML control plane; and
- no old config support should be removed without explicit later approval.

Migration must avoid silent behavior changes. When both legacy config and
unified config are present, future phases should define deterministic
precedence and diagnostics before implementation.

## Config Security Policy

Configuration display, diagnostics, MCP responses, status output, and logs must
not expose secrets.

Policy:

- `admin/admin` may appear only as a clearly marked local-dev sample;
- prefer `password_env` over literal passwords;
- literal passwords are allowed only in ignored local dev configs, never in
  committed examples;
- secret values should be referenced indirectly through environment variables,
  keychain wrappers, local ignored files, or other user-approved mechanisms;
- committed examples must use fake values and `.invalid` domains;
- config secrets must not appear in MCP responses, readback, diagnostics, logs,
  status docs, raw observations, or canonical metadata; and
- unknown secret-bearing fields must be redacted before display.

Secret-like config keys include names containing:

- `password`;
- `passwd`;
- `secret`;
- `token`;
- `key`;
- `private_key`;
- `access_key`;
- `secret_key`;
- `client_secret`;
- `credential`;
- `connection_string`;
- `auth`;
- `bearer`;
- `session`;
- `cookie`;
- `database_url`; and
- `url` when the value appears credentialed.

## Local Postgres Posture

RepoMap's permanent local service may use a local Postgres database. The
default architecture is:

- Postgres bound to localhost;
- RepoMap configured with explicit host, port, database, and user;
- password supplied by environment reference or ignored local config;
- DBeaver or direct `psql` access treated as user-managed administration; and
- no RepoMap product command for destructive database administration.

Local dev samples may use a user such as `admin` and a password such as
`admin` only when the sample is clearly local-only, ignored, and not exposed
over a network. RepoMap must never recommend exposing those credentials through
a public tunnel.

RepoMap must not add product or MCP commands for:

- dropping a database;
- clearing a database;
- truncating graph tables;
- resetting all data;
- deleting all observations;
- deleting all canonical nodes;
- wiping a configured graph; or
- deleting a configured graph.

Manual destructive database work remains outside RepoMap product behavior and
is the user's responsibility through DBeaver or direct Postgres tools.

## Graph Registry Model

A future local graph registry should be config-driven and explicit. Registry
entries should include:

- graph id;
- display name;
- root path;
- repository or project name;
- privacy classification;
- enabled or disabled flag;
- include patterns;
- exclude patterns;
- extractor profile;
- refresh policy;
- last refresh metadata;
- storage namespace or repository name;
- MCP visibility flag; and
- notes.

Initial graph entries should support:

`repo-map`

- root path: the RepoMap working tree;
- purpose: product graph, dogfooding, development support;
- privacy: `public-dev`;
- refresh: manual or frequent local refresh; and
- MCP visibility: enabled by local config.

`codex-vc`

- root path: `~/.codex/codex-vc`;
- purpose: operational docs, policies, prompts, and server-memory catalog;
- privacy: `private-ops`;
- refresh: manual by default; and
- MCP visibility: disabled until explicitly enabled.

`codex-memories`

- root path: `~/.codex/memories`;
- purpose: local memory files and durable user/project context;
- privacy: `private-memory`;
- refresh: manual by default; and
- MCP visibility: disabled until explicitly enabled.

`flakes`

- root path: `~/.flakes`;
- purpose: messy Nix, dotfiles, and project graph for cleanup and analysis;
- privacy: `private-config`;
- expectation: noisy, incomplete, or partially parsed graph is acceptable;
- refresh: conservative, with exclusions and diagnostics; and
- MCP visibility: disabled until explicitly enabled.

Privacy classifications:

- `public-dev`;
- `private-ops`;
- `private-memory`;
- `private-config`; and
- `sensitive-local`.

Default posture:

- private roots are disabled until explicitly enabled in local config;
- generated graphs remain local;
- MCP access is read-only;
- no upload or sync occurs by default; and
- privacy classification appears in status and MCP responses where practical.

## Refresh And Watch Architecture

Future refresh modes may include:

- manual refresh;
- scheduled local refresh;
- filesystem watch with debounce;
- startup stale-check; and
- targeted graph refresh.

Refresh behavior should:

- detect changed files;
- avoid reprocessing unchanged files when practical;
- keep runs deterministic;
- record run metadata;
- preserve previous evidence unless replaced by newer extraction for the same
  source;
- expose refresh status and diagnostics;
- fail graph-scoped work without bringing down unrelated graphs;
- apply include/exclude rules before reading private trees; and
- avoid destructive cleanup by default.

Allowed automation:

- initiating or updating a graph from configured roots;
- refreshing graphs as underlying folder trees change;
- status reporting; and
- diagnostics for failed parses or skipped files.

Disallowed automation:

- clearing databases;
- dropping databases;
- truncating graph tables;
- deleting all rows;
- overwriting private policy files;
- editing `AGENTS.md` automatically without explicit user instruction; and
- opening network tunnels automatically.

## Expanded Read-Only MCP Surface

RepoMap should grow from a minimal read-only MCP helper into a richer read-only
local product surface.

Possible future MCP tools and resources:

- `list_graphs`;
- `graph_status`;
- `refresh_graph`;
- `refresh_all_enabled_graphs`;
- `search_nodes`;
- `search_edges`;
- `search_observations`;
- `search_files`;
- `file_summary`;
- `neighborhood`;
- `project_summary`;
- `language_summary`;
- `config_summary`;
- `python_summary`;
- `terraform_summary`;
- `openapi_summary`;
- `js_framework_summary`;
- `markdown_summary`;
- `diagnostics_summary`;
- `explain_node`;
- `explain_edge`;
- `explain_observation`;
- `recent_changes`;
- `stale_graphs`; and
- `server_memory_catalog_summary`, if a bridge exists later.

Write boundary:

- refreshing configured graph data is allowed because it updates RepoMap's own
  generated graph from configured roots;
- source-tree mutations are not allowed;
- database destructive actions are not allowed;
- operational policy edits are not allowed through MCP in this phase set; and
- source acquisition remains governed by ADR 0014, ADR 0024, ADR 0025, and the
  relevant source-specific phases.

MCP responses should:

- cite source or evidence ids where practical;
- distinguish canonical facts from raw observations;
- distinguish static declarations from runtime truth;
- expose graph privacy classification;
- avoid raw secret values;
- use bounded results and pagination; and
- make no claim that contracts, routes, config declarations, or source
  summaries are runtime truth without separate evidence.

## Server-Memory Relationship

RepoMap should complement server-memory.

server-memory role:

- card catalog;
- human-maintained or lightweight memory nodes;
- pointers to docs, skills, policies, and project notes;
- compact relationship map for current operational facts; and
- local JSONL storage under `~/.codex/codex-vc/mcp/server-memory`.

RepoMap role:

- generated graph over source trees and local artifacts;
- evidence-rich file, source, config, test, and framework graph;
- readback summaries and neighborhood queries;
- diagnostics for stale, noisy, or partially parsed sources; and
- storage-backed MCP readback over configured graphs.

Future bridge options:

- read server-memory JSONL as a local artifact;
- summarize server-memory entries as memory catalog evidence;
- link memory catalog pointers to RepoMap files or nodes when paths are local
  and repo-contained;
- expose a read-only memory catalog summary through RepoMap MCP; and
- preserve server-memory as the canonical card catalog unless a later phase
  explicitly migrates responsibility.

The bridge must not mutate server-memory JSONL in read-only bridge phases.

## Operational Policy Dogfooding

Future MCP-OPS6 should be the first phase that uses RepoMap and server-memory
evidence to improve private operational policy docs such as codex-vc
`AGENTS.md`.

MCP-OPS6 prerequisites:

- a RepoMap graph for `codex-vc` exists;
- a RepoMap graph for `codex-memories` exists if the user enables it;
- a server-memory bridge or readback exists;
- ChatGPT or Codex can inspect relevant private operational evidence through
  user-approved tooling; and
- the user explicitly asks to update the policy file.

Policy work should:

- compare server-memory card catalog entries with RepoMap graph evidence;
- identify memory boundary conflicts;
- identify duplicate or stale policies;
- propose edits before applying them;
- keep user-authored canon separate from generated graph facts;
- avoid broad memory sprawl; and
- avoid leaking private operational policy content into public RepoMap commits.

MCP-OPS0 does not read private policy docs and does not edit them.

## Network, Tunnel, And Security Posture

The preferred initial deployment is local-only.

Default:

- MCP server bound to stdio or localhost-only transport;
- Postgres bound to localhost;
- no public tunnel;
- no remote exposure;
- no direct remote Postgres access; and
- no dev credentials over a network.

If remote access is later needed:

- require a separate security review phase;
- prefer open-source or self-hostable options over opaque SaaS tunnels;
- consider VPN-style access before public reverse tunnels;
- require authentication, least privilege, and audit logging;
- expose only read-only MCP or API over a controlled channel;
- never expose Postgres directly; and
- never expose dev credentials.

MCP-OPS0 does not implement remote access, tunnel configuration, or network
exposure.

## Web UI

Web UI is explicitly out of scope.

RepoMap may eventually need a UI, but MCP-OPS0 does not start that track. The
next operations phases should focus on local config, registry, refresh, MCP
surface, and server-memory bridging before any browser-based product surface.

## Destructive Operations

RepoMap product and MCP surfaces must not include:

- clear database;
- drop database;
- reset database;
- wipe graph;
- truncate graph;
- delete all observations;
- delete all canonical nodes;
- delete configured graph; or
- similar broad destructive actions.

If graph pruning or data retirement is ever needed, require a separate ADR with:

- dry-run behavior;
- backup or export guidance;
- graph-specific scope;
- explicit confirmation token;
- non-MCP default;
- audit trail; and
- redaction review.

## Future Tests

Future implementation phases should add tests for:

- unified TOML config parsing and schema-version diagnostics;
- safe handling of unknown config sections;
- redaction of secret-like config fields in diagnostics and readback;
- compatibility with existing JSON MCP/project registry config;
- compatibility with existing project/source TOML configs;
- graph registry validation;
- privacy classification behavior;
- disabled private graph defaults;
- MCP visibility flags;
- local Postgres bootstrap/status behavior;
- local-dev credential samples never appearing in committed example secrets;
- refresh status and run metadata;
- watch/debounce behavior where implemented;
- no source-tree mutation through MCP;
- no destructive DB tools;
- expanded MCP summary and search pagination;
- server-memory bridge read-only behavior when implemented;
- no mutation of server-memory JSONL;
- no private policy reads without explicit configuration; and
- no network tunnel or remote database exposure.

## Future Phases

`MCP-OPS1: Unified TOML config loading and local Postgres bootstrap`

- unified TOML config loader;
- local config templates;
- localhost Postgres connection profile;
- dev sample credentials clearly marked local-only;
- DBeaver connection notes;
- compatibility with existing JSON repo config and existing per-source TOML
  configs;
- diagnostics nudging users toward unified TOML;
- no destructive DB commands; and
- service health/status readback.

`MCP-OPS2: Managed graph registry`

- config-driven graph roots for `repo-map`, `codex-vc`, `codex-memories`, and
  `flakes`;
- privacy classifications;
- include/exclude patterns;
- enable/disable flags; and
- graph status readback.

`MCP-OPS3: Incremental refresh/watch mode`

- manual refresh;
- filesystem watch/debounce;
- startup stale-check;
- refresh status and diagnostics; and
- no clearing or wiping.

`MCP-OPS4: Expanded read-only MCP surface`

- graph list/status/search/neighborhood/summary/explain tools;
- bounded pagination;
- privacy labels;
- evidence citations;
- no source mutation; and
- no destructive DB operations.

`MCP-OPS5: server-memory bridge/readback`

- read server-memory JSONL as local artifact;
- summarize the card catalog;
- link local path pointers to RepoMap graph where safe; and
- no mutation of server-memory.

`MCP-OPS6: Operational policy dogfooding`

- inspect codex-vc `AGENTS.md` and related policy docs only when user-approved;
- compare RepoMap graph and server-memory catalog;
- propose memory boundary policy improvements;
- edit only with explicit instruction; and
- avoid private policy leakage into public RepoMap.

## Rejected Alternatives

Rejected:

- keeping JSON as the primary permanent local operations config;
- merging existing feed/GitHub/API TOML configs as unrelated one-off formats
  without a unified control plane;
- removing legacy JSON or per-source TOML support during the first TOML
  migration phase;
- making private roots enabled by default;
- treating server-memory as obsolete;
- exposing Postgres remotely;
- exposing local dev credentials through any tunnel;
- starting with a web UI;
- adding destructive database tools to the product;
- making MCP a source-tree write surface;
- automatically editing private operational policy docs;
- opening tunnels automatically;
- treating noisy `flakes` graph output as a failure; and
- using generated graph facts as a substitute for user-authored operational
  canon.

## Consequences

MCP-OPS0 establishes a safe path for RepoMap to become a permanent local
knowledge-graph service without collapsing configuration, storage, refresh,
MCP, memory, and private-policy work into one implementation slice.

Near-term consequences:

- `repomap.local.toml` becomes the recommended primary local operations config
  name;
- `repomap.toml` remains available conceptually for non-secret project-local
  config;
- existing JSON and per-source TOML formats remain compatible until explicit
  migration phases;
- private graph roots are architecture-approved but disabled by default;
- server-memory remains the lightweight card catalog;
- expanded MCP remains read-only except for refreshing RepoMap-owned graph data;
  and
- destructive database administration remains outside RepoMap product behavior.

## Acceptance

MCP-OPS0 is accepted only if it remains architecture-only, local-first,
privacy-aware, operationally useful, and clearly separates:

- permanent RepoMap local service;
- unified TOML configuration;
- migration from legacy JSON and per-source TOML configs;
- local Postgres/dev access;
- graph registry;
- refresh/watch automation;
- expanded read-only MCP;
- server-memory bridge;
- operational policy dogfooding;
- remote tunnel/security review; and
- destructive DB administration outside RepoMap.
