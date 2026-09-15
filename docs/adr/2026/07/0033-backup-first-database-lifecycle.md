# ADR 0033: Backup-First Database Lifecycle

## Status

Accepted

## Date

2026-07-02

## Authoritative References

- ADR 0032: Containerized Local Runtime And Config Home
- `docs/status/2026/07/02/00070-mcp-runtime2-containerized-local-runtime-exit.md`
- `docs/status/2026/07/02/00071-mcp-runtime3-containerized-test-postgres-exit.md`
- `docs/status/2026/07/02/00072-mcp-runtime4-exclude-paths-enforcement-exit.md`

## Context

ADR 0032 corrected RepoMap's local operations target from a direct
host-Postgres profile to an isolated local container cluster:

- a RepoMap server/MCP container;
- a RepoMap-owned Postgres container;
- `REPOMAP_HOME` configuration and runtime state;
- persistent local volumes associated with RepoMap; and
- no use of the user's preexisting Postgres server by default.

Earlier runtime architecture forbade destructive database operations. That
remains the safe default for ordinary agent-facing APIs and MCP tools. However,
a local runtime still needs a carefully bounded lifecycle for administrative
work such as dumping, restoring, reinitializing, and eventually dropping a
RepoMap-owned database.

The risk is not that a local admin command can never destroy data. The risk is
that it might destroy data without a restorable backup, without proving it is
scoped to a RepoMap-owned containerized database, or through a casual agent tool
surface. MCP-RUNTIME5 defines the architecture before any such commands are
implemented.

MCP-RUNTIME5 is architecture and documentation only. It does not add code,
start containers, inspect `REPOMAP_HOME`, read private roots, dump real
databases, drop databases, create backups, expose Postgres remotely, mutate
server-memory, or proceed to MCP-OPS6.

## Decision

RepoMap will allow future destructive local runtime database lifecycle commands
only when they are:

- backup-first;
- explicit;
- auditable;
- scoped to RepoMap-owned local runtime containers and databases; and
- restorable.

Ordinary users and agents should continue to interact with RepoMap data through
the RepoMap MCP/server API. Direct Postgres host-port access is a development
and debugging toggle, defaults off, binds to localhost only when enabled, and
must never be exposed publicly.

## Scope

In scope:

- backup-first destructive database lifecycle policy;
- database dump command design;
- dump-all command design;
- drop database behavior with mandatory pre-drop backup;
- database initialization from source;
- database initialization from dump;
- backup storage layout under `REPOMAP_HOME`;
- restore path and safety checks;
- direct Postgres host-port exposure as a dev/debug opt-in;
- MCP/API boundary for destructive lifecycle actions;
- container and database ownership checks;
- failure behavior;
- audit behavior; and
- future implementation phases.

Out of scope:

- implementing commands;
- changing container runtime behavior;
- changing the test harness;
- starting Docker, Podman, or containers;
- dumping real databases;
- dropping databases;
- creating backup files;
- reading private roots;
- reading server-memory;
- opening tunnels;
- adding a web UI;
- exposing Postgres remotely;
- removing JSON extraction or source support; and
- proceeding to MCP-OPS6.

## Design Principles

1. Backup-first

   Any destructive database lifecycle operation must first produce a restorable
   dump unless the operation is already a restore or initialization into a new
   empty database.

2. Explicit

   Destructive operations require explicit local command invocation and
   confirmation. Setup, up, status, refresh, MCP readback, and server-memory
   bridge operations must not trigger destructive database work automatically.

3. Scoped

   Destructive lifecycle commands may operate only on RepoMap-owned local
   runtime containers and databases identified by RepoMap labels and runtime
   metadata.

4. Restorable

   Every backup-first destructive command must produce a backup path, manifest,
   checksum, and restoration instructions before destruction proceeds.

5. API-first

   Agents should use the RepoMap MCP/server API by default. Direct database
   access is for development and debugging only.

## Backup Directory Layout

Future lifecycle commands should store backups under `REPOMAP_HOME`:

```text
$REPOMAP_HOME/backups/<runtime_id>/<database_name>/<timestamp>/
  dump.pgcustom
  manifest.json
  restore.md
```

For all-database dumps:

```text
$REPOMAP_HOME/backups/<runtime_id>/all-databases/<timestamp>/
  globals.sql.gz
  <database-a>.pgcustom
  <database-b>.pgcustom
  manifest.json
  restore.md
```

Backup directories are immutable once written. If a target directory already
exists, the command must fail rather than overwrite.

## Manifest

Every backup directory must include `manifest.json`.

The manifest should include:

- backup format version;
- RepoMap version;
- runtime id;
- container id or name;
- database name or all-databases marker;
- Postgres image and version when available;
- timestamp;
- command invoked;
- dump file names;
- dump format;
- compression;
- checksums;
- redacted connection metadata;
- backup reason or command-supplied reason when provided;
- whether the backup was manual, pre-drop, or dump-all; and
- restore command hints.

The manifest must not include:

- passwords;
- raw credentialed connection strings;
- private graph source contents;
- server-memory contents;
- environment variable values;
- tokens; or
- secrets.

## Backup Format

The preferred single-database backup format is `pg_dump` custom format:

```text
dump.pgcustom
```

Rationale:

- it is compact enough for local backups;
- it is restorable with `pg_restore`;
- it can support selective restore workflows later; and
- it avoids committing to plain SQL as the only restore path.

All-database backups may also include `globals.sql.gz` for roles and global
objects when needed. Future implementation must provide restore commands that
understand the chosen formats. A later implementation may add `--format
pgcustom|sql.gz`, but `pgcustom` is the default target.

Dump commands should run inside the Postgres container or through the container
network where practical, so dumping and restoring do not require direct
localhost Postgres exposure or host-installed Postgres client tools.

## Future Command Shape

Future local administrative CLI commands should use shapes like:

```sh
repomap-kg local db dump --database repomap
repomap-kg local db dump-all
repomap-kg local db drop --database repomap --backup-first
repomap-kg local db init --database repomap --from-source
repomap-kg local db init --database repomap --from-dump <backup-dir-or-file>
repomap-kg local db backups
repomap-kg local db backup-info <backup-id-or-path>
```

Optional future flags:

- `--repo-map-home <dir>`
- `--yes`
- `--dry-run`
- `--reason "<text>"`
- `--format pgcustom|sql.gz`
- `--output <dir>`

MCP-RUNTIME5 does not implement these commands.

## Dump Behavior

`local db dump --database <name>` should:

- verify the target runtime and database are RepoMap-owned;
- dump one database;
- store the backup under `REPOMAP_HOME/backups`;
- write `manifest.json`;
- write `restore.md`;
- record checksums;
- avoid printing passwords; and
- avoid requiring direct host-port exposure when container exec is available.

`local db dump-all` should:

- verify the target runtime is RepoMap-owned;
- dump all RepoMap-owned runtime databases;
- include globals only when needed and safe;
- write one manifest for the set;
- write restore instructions for the set; and
- avoid dumping arbitrary external databases.

## Drop Behavior

`local db drop --database <name> --backup-first` should be the only accepted
drop shape.

Strict behavior:

- require an explicit database name;
- verify the target is a RepoMap-owned runtime database;
- create a pre-drop backup first;
- verify the dump completed;
- verify checksums and manifest were written;
- print the backup path;
- print the restore command;
- refuse to proceed if backup or manifest creation fails;
- never delete backups by default;
- never remove persistent volumes by default;
- never operate on host-installed Postgres;
- never operate on arbitrary connection strings; and
- never be available through ordinary MCP agent tools by default.

No command should invite accidental unbacked full wipe. Avoid names such as:

- `wipe`
- `nuke`
- `reset-all`
- `drop-all-without-backup`

## Initialization And Restore

`local db init --database <name> --from-source` should:

- create or initialize a database from RepoMap migrations/source schema;
- require explicit invocation;
- verify runtime ownership;
- fail if the database already exists unless a later replacement flow is
  accepted;
- print changed resources; and
- avoid silently choosing a dump source.

`local db init --database <name> --from-dump <backup-dir-or-file>` should:

- verify the backup manifest and checksums;
- verify the target runtime is RepoMap-owned;
- create or initialize from the selected dump;
- fail if the database already exists unless a later replacement flow is
  accepted;
- report the restored backup id and target; and
- avoid silently falling back to source migrations.

Restore story:

1. A user runs a backup-first drop command.
2. The command writes a dump, manifest, and restore instructions.
3. The command reports the backup path and restore command.
4. The user runs `local db init --from-dump <backup>` to restore.
5. If restoring into an existing database is ever supported, it must be a
   separate backup-first flow.

## Direct Postgres Dev/Debug Toggle

Direct Postgres host-port mapping is a development and debugging feature. It is
not the ordinary product path.

Future runtime config should support a shape like:

```toml
[runtime.postgres]
direct_host_port_enabled = false
host_port = 55432
bind_host = "127.0.0.1"
```

Rules:

- `direct_host_port_enabled` defaults to `false`;
- bind host defaults to `127.0.0.1`;
- public bind addresses are rejected;
- standard host port `5432` is not the default;
- status output says direct DB access is disabled by default;
- DBeaver connection info is shown only when direct host-port mapping is
  enabled;
- dump and restore commands should use container exec or internal networking
  instead of requiring direct host-port exposure; and
- MCP tools must not expose raw database credentials.

## MCP And Agent Boundary

Ordinary MCP/server tools remain read-only or domain-specific safe operations.

Destructive database lifecycle commands are local administrative CLI operations,
not ordinary agent tools. If a later phase proposes MCP exposure, it requires a
separate ADR with:

- role or capability checks;
- dry-run;
- explicit user confirmation;
- pre-created backup manifest;
- bounded audit output; and
- clear restore instructions.

## Ownership Checks

Lifecycle commands must verify target ownership before touching containers or
databases.

Allowed ownership signals:

- RepoMap container labels;
- runtime id;
- `REPOMAP_HOME` hash;
- expected container and network names;
- expected volume paths or labels;
- runtime manifest metadata; and
- configured database names.

Never operate on:

- arbitrary external Postgres;
- host-installed Postgres;
- a user's preexisting server;
- containers without RepoMap labels;
- containers from another `REPOMAP_HOME` unless explicitly selected and
  verified; or
- arbitrary connection strings.

## Failure Behavior

Required behavior:

- if dump fails, drop does not proceed;
- if checksum or manifest write fails, drop does not proceed;
- if backup directory already exists, fail rather than overwrite;
- if disk space appears insufficient and can be detected, warn or fail before a
  destructive step;
- if restore fails, report partial state clearly and point to diagnostics;
- cleanup must not delete successful backups;
- errors must redact secrets; and
- logs must remain bounded.

## Audit Behavior

Destructive lifecycle commands should write bounded audit records under
`REPOMAP_HOME/status` and in the backup manifest.

Audit fields:

- command;
- timestamp;
- target runtime id;
- target database;
- backup id or path;
- outcome;
- redacted diagnostics;
- reason when supplied; and
- operator/user when available.

Audit records must not contain secrets, passwords, raw credentialed URLs,
private graph contents, server-memory contents, or environment variable values.

## Security And Privacy

All command output, diagnostics, manifests, and audit records must redact values
for secret-like keys, including:

- password
- passwd
- secret
- token
- key
- private_key
- access_key
- secret_key
- client_secret
- credential
- connection_string
- auth
- bearer
- session
- cookie
- database_url
- credentialed URL values

Backups may contain application data by design, so backup directories are local
private runtime artifacts. They must not be committed to RepoMap and must not be
served through ordinary MCP readback.

## Future Implementation Phases

`MCP-RUNTIME5A: Direct DB dev/debug toggle`

- make direct Postgres host-port mapping default off;
- update local runtime compose generation;
- show DBeaver info only when enabled;
- keep MCP/server API as the default access path; and
- avoid exposing Postgres publicly.

`MCP-RUNTIME5B: Dump and backup manifest commands`

- implement `local db dump`;
- implement `local db dump-all`;
- implement `local db backups`;
- implement `local db backup-info`;
- use container exec where practical; and
- avoid destructive commands.

`MCP-RUNTIME5C: Init from source and dump`

- implement explicit database initialization from migrations/source;
- implement initialization from a selected backup dump;
- verify manifests and checksums;
- fail if the database exists unless a later replacement flow is accepted; and
- avoid silent source/dump fallback.

`MCP-RUNTIME5D: Backup-first drop database`

- implement drop only with mandatory pre-drop backup;
- provide no backup bypass;
- print restore path and command;
- enforce strict ownership checks; and
- keep ordinary MCP tools free of destructive DB lifecycle actions.

Then resume:

`MCP-OPS6: Operational policy dogfooding`

## Rejected Alternatives

Reject direct host-Postgres lifecycle management. RepoMap must not create,
drop, or restore databases on a user's preexisting Postgres server by default.

Reject unbacked drop/reset commands. A local admin shortcut is not worth losing
the restore path.

Reject making direct Postgres host-port mapping default-on. The MCP/server API
is the default access path; direct DB access is a dev/debug exception.

Reject exposing destructive lifecycle commands through ordinary MCP tools in
this phase set. Agent-facing destructive database controls need a separate ADR.

## Acceptance

MCP-RUNTIME5 is accepted only if it defines:

- backup-first destructive database lifecycle;
- dump and dump-all design;
- initialization from source and dump;
- drop with mandatory pre-drop backup;
- backup layout and manifest;
- restore path;
- direct DB localhost exposure as dev/debug opt-in default-off;
- ordinary agent access through the MCP/server API by default;
- scoped ownership checks;
- failure and audit behavior; and
- no implementation in this phase.
