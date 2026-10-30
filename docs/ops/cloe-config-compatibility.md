# CLOE configuration compatibility

Common Lore Index (CLOE) is RepoMap's selected successor identity. This first
compatibility milestone keeps the existing `repomap-kg` distribution, executable,
import namespace and default home while preparing configuration migration.
It does not move an existing home or database.

## Home selection

An explicit `--repo-map-home` wins. Otherwise a nonempty `CLOE_HOME` wins over
nonempty `REPOMAP_HOME`; the fallback remains `~/.repo-map` for this milestone.
`CLOE_PATH` is unrelated and is ignored. Selecting a home creates nothing.

## Supported files and order

A home uses exactly one family:

| Family | Base files, loaded first | Local overlays, loaded second |
|---|---|---|
| Legacy | `*.rp.toml` | `*.rpl.toml` |
| CLOE | `*.cloe.toml`, excluding local overlays | `*.local.cloe.toml` |

Files sort alphabetically within each group. A local overlay is selected once.
Discovery remains top-level only. A home mixing both families is refused;
previously ignored CLOE-suffixed files now belong to an active family, so a
legacy home containing them must resolve that mixture before loading.
Unrelated TOML files retain ignored-file diagnostics. File suffixes do not
grant permission to publish private configuration.

This precedence applies to all components using the shared home resolver,
including configuration, Local state and MCP. An explicit MCP home also wins
over an ambient CLOE_HOME. An explicitly selected CLOE home supports configured
Local/Server reading, Local state operations and MCP. Keep the existing schema,
backend declaration, graph identities,
source roots and secret references. Other environment-variable names remain
unchanged in this preparatory slice.

Container-runtime setup supports the same family selection:

```sh
repomap-kg local setup --repo-map-home ./new-home --config-format cloe --dry-run --json
repomap-kg local setup --repo-map-home ./new-home --config-format cloe --json
```

An empty home defaults to legacy unless `--config-format cloe` is explicit.
An existing home's active family is detected automatically. An explicit format
must match it; this command does not convert a legacy home. Legacy setup creates
`repomap.rpl.toml`; CLOE setup creates `repomap.local.cloe.toml`, with the same
template payload and stable runtime/graph/database naming. Loaded CLOE files
are mounted by their actual names for the container runtime.

Setup never overwrites an existing generated target. Its default overlay uses
the same bootstrap precedence as legacy setup: it can override base-file values,
while later-sorting local overlays win. Keep intended settings in those later
overlays or an already-converted canonical target. This is not a migration of
an existing effective configuration.

Format conflicts, mixed homes, unsafe generated targets and known SQLite Local
homes are refused before runtime files or credentials are written. Container
runtime setup is for PostgreSQL; continue using the `ops sqlite-*` commands for
SQLite Local. CLOE input receives basic TOML/schema/backend preflight, without
claiming full configuration or database readiness.

Actual setup requires an owned ordinary private home. Generated targets must
be owned ordinary files; directories, symlinks (including broken links),
foreign-owned files and portable case aliases are refused in both families.
This intentionally tightens legacy setup as well. Newly generated targets are
private; existing ordinary targets keep their bytes and permissions under the
private home. Setup does not repair ownership or chmod existing user files.

Dry-run reports its selected family and pins it in the replayable API command.
It creates no files or credentials and does not chmod a home. Its runtime plan
is still a generic template preview. Repeating setup preserves configuration
and existing secret bytes; its JSON setup diagnostics use stable labels and
filenames rather than absolute home paths.
CLI JSON omits replayable commands; the Python result retains an API command
for local replay, including the caller-selected home.

Partial setup is not an atomic home migration. If creating a new generated
target fails partway through, preserve and inspect it before removing only that
failed generated file and retrying. Existing malformed legacy bootstrap
tolerance remains; unavailable traversal and undecodable input are bounded
refusals. No malformed home is thereby certified usable.

## Read-only filename plan

```sh
repomap-kg ops config-migration-plan --repo-map-home ./example-home --json
```

The command reads the selected configuration files and validates the existing
TOML/schema/discovery boundary. It does not connect to a database, read source
contents, write files, rename anything or apply data migration. It needs no
PostgreSQL driver, including when planning a Server home's filenames.

`filename_conversion_ready` describes filename conversion only. It is not a
certificate that a home can safely be moved, that its database is ready, or
that its effective configuration/data has been migrated. `writes_performed` is
zero. `apply_supported` remains `false` in schema v1 and means that the plan
document is not apply input or apply authority. Apply never reads a saved plan;
it revalidates the current home itself (see below). A CLOE home returns an explicit
no-conversion plan. Exit 0 means the filename plan is ready or unnecessary;
exit 1 means a refused plan or invalid input. Invalid input is diagnosed on
stderr; a refused conversion still returns its structured plan with `--json`.

Legacy `.rp.toml` names propose `.cloe.toml`; `.rpl.toml` names propose
`.local.cloe.toml`. The plan refuses target collisions, base-to-local
reclassification and changes to the complete layer/order sequence. In
particular, `x.local.rp.toml` and `x.rpl.toml` collide, and
`base.extra.rp.toml`/`base.rp.toml` reverse order after simple suffix replacement.
Resolve such names explicitly before any later migration. Do not act on a
refused plan by applying its proposed names mechanically.

The output includes filenames, ordering and refusal codes, but no config
values, credentials, source contents or absolute home path. Text output quotes
filenames so control characters are not written directly to the terminal.
Input errors report stable diagnostic codes rather than raw parser/file-I/O
messages. The plan also refuses already occupied target names, including a
directory or broken symlink omitted from configuration-file discovery. This is
a point-in-time filename plan; it is not an apply-time filesystem reservation.
Collision comparisons use NFC normalization and case folding conservatively
so a plan does not assume a case-sensitive destination.

`--config` is accepted only as a directory alias for this command; it does not
plan an individual config file. If both options are supplied, `--repo-map-home`
wins, as in existing ops selection. `REPOMAP_OPS_CONFIG` is an MCP-specific
legacy setting and is not a planner selector. Use an explicit home when
planning a collection different from the current home selection.

## Apply, rollback and finalize

[ADR 0114](../adr/2026/10/0114-cloe-config-migration-apply-recovery.md) adds
three commands that convert a legacy home's configuration filenames to CLOE and
recover from interruptions. They change configuration filenames only. Values,
graphs, databases, source roots and the default home do not change.

```sh
repomap-kg ops config-migration-apply    --repo-map-home ./example-home            # dry run
repomap-kg ops config-migration-apply    --repo-map-home ./example-home --yes --json
repomap-kg ops config-migration-rollback --repo-map-home ./example-home --yes
repomap-kg ops config-migration-finalize --repo-map-home ./example-home --yes
```

Each command needs an explicit `--repo-map-home`. There is no `--config` alias
and no `CLOE_HOME`/`REPOMAP_HOME`/default fallback. Without `--yes` a command is
a dry run: it writes nothing, creates no lock or directory, and chmods nothing.
`--dry-run` and `--yes` cannot be combined.

The Python API is `repomap_kg.ops.config_migration`:
`apply_cloe_config_migration`, `rollback_cloe_config_migration` and
`finalize_cloe_config_migration`. Each takes `(home, *, confirmed=False,
dry_run=False)`. Without either flag it refuses with `confirmation-required`.

### Before you apply

**Quiesce the home.** Stop the local runtime, MCP servers, refresh jobs and
editors that use the home. The migration lock coordinates only these three
commands, and `local setup` refuses while a migration directory exists. Nothing
else takes the lock. Running containers keep their old bind mounts until the
next `local up`.

**Requirements.** The commands support Linux and macOS only. Elsewhere they
refuse with `config-migration-platform-unsupported`.

- The home must be an owned, non-symlink directory with no group or other
  permissions. A `0755` home is refused with `repo-map-home-unsafe`. The
  commands never chmod; run `chmod 700` on the home yourself.
- Every legacy or CLOE-suffixed top-level entry must be an owned regular file
  with one link and no setuid, setgid or sticky bit. Symlinks, directories,
  FIFOs and hardlinked files are refused, not ignored.
- File permission bits such as `0644` are preserved exactly.
- Limits: 64 files, 1 MiB per file, 8 MiB in total, and 255-byte UTF-8 names,
  targets included.

### What apply does

Apply rereads every legacy file through a bounded, non-following descriptor.
It validates TOML, schema and storage declarations without a database, driver
or source-root access. It then recomputes the filename plan with the planner's
refusals, writes private backups and a journal, revalidates the home, and
publishes each file by hard-linking the CLOE name before unlinking the legacy
name.

After publishing, apply proves three things:

- the new names are exactly the planned targets, in the original layer order;
- every file has its original inode, bytes and mode;
- the merged effective configuration is unchanged.

There is no multi-file atomicity. Every intermediate state is durable and
recoverable. A quiescent loader sees one family, or refuses a mixed home.

On success the home keeps `.cloe-config-migration/`, a `0700` directory. It
holds the lock, the journal and `0600` copies of every original file. **These
copies may contain Server credentials or DSNs.** Finalize removes them.

Repeating apply reports `already-applied` until you finalize or roll back.

### Rollback and finalize

**Rollback** restores the exact legacy names, bytes and modes. It handles two
cases:

- an interrupted apply, in any state;
- an unfinalized successful apply.

It classifies every entry from fresh observations before changing anything:

- source only;
- target only;
- both names on one inode;
- restore from backup;
- one of the restore intermediate states.

Any other state is `config-migration-drift`. The command refuses the whole
operation and keeps the journal and backups as evidence.

Before discarding unjournaled restore scratch, rollback proves that the required
backup still has its recorded size and hash. A missing, unsafe or changed backup
refuses without changing the scratch, journal or configuration files.

**Finalize** permanently discards the backups and journal after proving the
converted home is unchanged. **After finalize, rollback is impossible.** Once
finalize has started, rollback is refused with
`config-migration-rollback-unavailable`. Rerun finalize to complete it.

A file restored from backup gets its original permission bits back. It does
not get back its original inode, group, ACLs, extended attributes or
timestamps.

**Repeating commands.** These outcomes all exit 0 with zero writes:

- rollback with no operation directory: `nothing-to-recover`;
- finalize with no operation directory: `nothing-to-finalize`;
- apply on a CLOE home: `already-converted`.

A leftover directory with no journal (only `lock`, `journal.json.tmp`, `probe`
or `probe.link`) is discarded by rollback or finalize.

**Results.** `--json` emits `cloe-config-migration-result-v1`: result,
changes, orders, journal state, refusal codes with basenames,
`rollback_available`, `finalize_pending` and `operation_directory_retained`.
Exit codes:

- 0 for success, a no-op result, or a dry run that would succeed;
- 1 for a refusal or failure;
- 2 for a usage error.

Output never contains values, hashes, inode numbers or absolute paths. Text
output quotes filenames.

### Recovery examples

An interrupted apply (crash, power loss or `failed-recovery-required`):

```sh
repomap-kg ops config-migration-rollback --repo-map-home ./example-home        # inspect
repomap-kg ops config-migration-rollback --repo-map-home ./example-home --yes  # restore legacy names
```

Afterwards you can run apply again. Recovery still works after a reboot. It
matches files by inode number on the home's current device, so a changed
device number does not block it.

A file edited after apply makes rollback and finalize refuse with
`config-migration-drift`, naming the legacy file. Neither command overwrites
the edit. To keep the edit and give up rollback:

1. Inspect the home and `.cloe-config-migration/`.
2. Keep the bytes you want.
3. Remove `.cloe-config-migration/` yourself.

No command deletes data it cannot prove it owns.

## Later transition work

The default `~/.cloe` cutover, package/executable/import rename, compatibility
shim ownership, live database backup/restore, and repository rename remain
coordinated W1 work. Existing wire identifiers, checksummed migrations and
historical receipts remain stable. [ADR 0109](../adr/2026/10/0109-cloe-configuration-compatibility.md)
defines the loader/planner boundary; [ADR 0112](../adr/2026/10/0112-cloe-runtime-configuration-producer.md)
defines runtime producer compatibility; ADR 0114 defines configuration
filename apply/rollback/finalize.
