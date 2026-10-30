# ADR 0114: CLOE configuration migration apply, rollback and finalize

## Status

Accepted before implementation for `REPOMAP-CLOE-MIGRATION1`, 2026-10-29,
under the operator's instruction to deliver one usable W1 configuration
migration and recovery epic. This ADR constrains the implementation. Hosted
qualification is a separate later decision.

## Date

2026-10-29

## Context

[ADR 0109](0109-cloe-configuration-compatibility.md) shipped the CLOE-capable
loader and an inert filename planner. [ADR 0112](0112-cloe-runtime-configuration-producer.md)
shipped explicit CLOE runtime setup. Neither converts an existing legacy home.
The planner already refuses order changes, base-to-local reclassification and
case/NFC collisions. Its schema `cloe-config-filename-plan-v1` reports
`apply_supported: false`.

Constraints that shape this decision:

- The ordinary loader follows symlinks and reads files without a size bound.
  The PostgreSQL builder refuses SQLite homes. The Local builder resolves
  source and database paths. Migration therefore cannot reuse
  `load_ops_config_home` as its equivalence proof.
- POSIX offers no multi-file atomic rename. Link-then-unlink publication
  without replacement has a durable intermediate state: both names on one
  inode, with link count 2.
- Advisory locks coordinate only cooperating processes.
  The runtime, MCP, other ops commands and editors do not take this lock.
- Successful conversion would otherwise leave private copies of possibly
  secret-bearing configuration on disk indefinitely.

## Decision

### Commands and API

Add three driver-free ops commands. They dispatch before storage routing, as
the planner does:

```sh
repomap-kg ops config-migration-apply    --repo-map-home HOME [--dry-run | --yes] [--json]
repomap-kg ops config-migration-rollback --repo-map-home HOME [--dry-run | --yes] [--json]
repomap-kg ops config-migration-finalize --repo-map-home HOME [--dry-run | --yes] [--json]
```

- `--repo-map-home` is required. There is no `--config` alias and no fallback
  to `CLOE_HOME`, `REPOMAP_HOME` or the default home.
- `--dry-run` and `--yes` are mutually exclusive, giving argparse exit 2.
- With neither flag the command runs as a dry run, following the
  `sqlite-cleanup` convention, and states that `--yes` is required to change
  anything.

The public API in `repomap_kg.ops.config_migration` consists of
`apply_cloe_config_migration`, `rollback_cloe_config_migration` and
`finalize_cloe_config_migration`. Each has the signature
`(home, *, confirmed=False, dry_run=False)` and returns a result mapping. It
never raises for a refusal.

| Input | Result | Writes |
|---|---|---|
| `home` is `None` or empty | `repo-map-home-required` | none |
| neither `confirmed=True` nor `dry_run=True` | `confirmation-required` | none |
| both `confirmed` and `dry_run` | `confirmation-conflict` | none |

Rollback is one command for two cases: recovering an interrupted apply, and
reverting a successful apply before finalize. Finalize is the explicit,
confirmed discard of retained recovery data for a proven applied journal.

### Planner compatibility

`config-migration-plan` stays read-only. Its v1 schema and every field are
unchanged, including `apply_supported: false`.

That field now means that this plan document is not apply input or apply
authority. It is kept for v1 compatibility. The planner text line changes to:

> Read-only plan; no files or data changed. A plan is not apply authority;
> ops config-migration-apply revalidates the current home.

Apply never consumes a saved plan. It always re-derives the plan from fresh
descriptor reads of the explicit home.

### Platform, home and entries

**Platform.** All three commands, dry runs included, refuse every mode with
`config-migration-platform-unsupported` unless all of these hold:

- `os.name == "posix"`, on Linux or macOS;
- `O_NOFOLLOW` and `O_DIRECTORY` are available;
- `fcntl.flock` is available;
- the descriptor-relative (`dir_fd`) forms of `open`, `stat`, `link`,
  `unlink`, `rename`, `mkdir` and `rmdir` are available, with non-following
  `stat` and `link`;
- `listdir` accepts a descriptor.

These capabilities are probed once, when the module is imported. Durability is
whatever `fsync` provides. macOS `F_FULLFSYNC` is not claimed.

**Home.** The home is opened once with `O_RDONLY | O_DIRECTORY | O_NOFOLLOW`.
That descriptor is the authority for every later operation, so renaming or
swapping the home path cannot redirect a write. The opened directory must be:

- owned by the caller;
- private, meaning `mode & 0o077 == 0`;
- the same inode as the pre-open `lstat`.

The command never chmods or repairs the home. A typical `0755` home is refused
with `repo-map-home-unsafe`. The operator remediates it with `chmod 700`.

**Configuration-classified entries.** Every top-level name whose suffix
classifies as legacy or CLOE must be:

- a regular file, not a symlink;
- owned by the caller;
- link count 1;
- free of setuid, setgid and sticky bits.

Otherwise the result is `config-entry-unsafe` with the basename. This covers a
config-suffixed directory, a symlink (including a broken one) and a hardlinked
file. They are refused, not ignored.

Ordinary permission bits are preserved exactly and never changed. A typical
`0644` legacy file stays `0644`, because normal publication keeps its inode.
Names must be UTF-8 and at most 255 bytes, sources and targets alike.
Otherwise the result is `config-filename-unsupported`.

**Bounds.** Exceeding any of these gives `config-migration-limit-exceeded`:

- at most 64 config files;
- at most 1 MiB per file and 8 MiB in total;
- a journal of at most 256 KiB.

### Bounded descriptor reads and equivalence

Every configuration read opens `name` relative to the home descriptor with
`O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC`. A read is accepted only if:

- the descriptor's `fstat` equals the prior `lstat` in device, inode, size,
  mode, owner, link count and `mtime_ns`;
- at most `size + 1` bytes are read;
- an unchanged `fstat` follows the read.

The same bytes are hashed (SHA-256), decoded as strict UTF-8 and parsed with
`tomllib`. They are then checked with the existing helpers: `validate_file_schema`,
`unknown_top_level_diagnostics`, `unknown_file_field_diagnostics`,
`merge_ops_config_payloads` and `parse_storage_section` on the base storage
table. The same bytes are written as the backup.

Any error-severity diagnostic refuses, with refusal entries
`{code: <stable diagnostic code>, file: <basename or "">}`. Raw messages,
values and paths are never emitted. No backend builder, source-root
resolution, database path, driver import or container command runs.

The effective-configuration digest is the SHA-256 of a canonical JSON
rendering of two things:

- the merged payload, with TOML date and time values tagged by type;
- the ordered `(severity, code)` diagnostic sequence.

Diagnostic paths and messages, which carry filenames, are excluded. The
digest is recorded in the journal. Apply, rollback and finalize prove it from
fresh descriptor reads.

### Operation directory, lock and journal

The fixed operation directory is `HOME/.cloe-config-migration/`. It is created
by `mkdirat` with mode `0700`. Discovery never includes it, because it is a
directory and has no `.toml` suffix. No loader change is required.

Every file in it is created with `O_CREAT | O_EXCL | O_NOFOLLOW`, mode `0600`,
except that the lock is opened-or-created as described below. The only names
allowed in it are:

| Name | Lifetime |
|---|---|
| `lock` | operation |
| `journal.json` | operation |
| `journal.json.tmp` | transient |
| `backup-NNNN.bin` | operation |
| `restore-NNNN.tmp` | transient |
| `probe`, `probe.link` | transient |

`NNNN` is the zero-padded journal entry index.

**Collisions.**

- **Apply.** A home entry that is a portable alias (NFC plus case folding)
  of the directory name, but not the exact name, is refused with
  `config-migration-alias-collision`. An exact-name non-directory is refused
  with `config-migration-residue-unsafe`.
- **Rollback and finalize.** The directory must be a non-symlink directory,
  owned, private, on the home's device, and must contain only allowed names.
  Otherwise the result is `config-migration-residue-unsafe`, and nothing is
  changed or removed.

**Lock.**

- **Acquisition.** The command opens `lock` relative to the operation
  directory with `O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK`, mode `0600`,
  and validates that it is regular, owned and has link count 1. It then takes
  a non-blocking `flock`. Afterwards it checks that the name still resolves to
  the locked inode. If the lock is contended or the name has changed, the
  result is `config-migration-busy`.
- **Dry runs.** A dry run never creates the directory or the lock. If a lock
  exists, the dry run opens it with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` and
  probes it with `LOCK_EX | LOCK_NB`. Contention reports busy, with no writes.
  The probe holds the lock for an instant, so a concurrent confirmed command
  can itself receive `config-migration-busy`. Rerunning it is safe.
- **Lifetime.** The lock lives from apply's directory creation until teardown.
  Teardown removes it last, while it is still held.
- **Who takes it.** Only the three commands take the lock. `local setup` adds
  one guard: it refuses with `config-migration-in-progress` whenever the
  operation directory name exists. It checks this in `prepare_setup_config`,
  dry runs included, before any of its own writes. As a result, after a
  successful apply, setup refuses until the operator finalizes or rolls back.
  A setup that was already running past that guard is caught only by the
  apply revalidation and post-publish listing checks.

**Journal (`cloe-config-migration-journal-v1`).**

It has an exact key set:

- `schema`
- `operation_id`, 32 lowercase hex characters
- `state`
- `home` (`dev`, `ino`)
- `source_format`, always `legacy`
- `source_order` and `proposed_order`
- `effective_sha256`
- `entries`

Each entry has exactly: `index`, `source`, `target`, `layer`, `size`,
`sha256`, `mode`, `dev`, `ino`, and `restored_dev`/`restored_ino`, each either
null or an integer.

It contains basenames only. It never contains absolute paths, configuration
values or merged payloads.

Validation is strict on types, bounds and key sets. In addition:

- the targets and order must equal `plan_cloe_config_filenames(sources)`,
  recomputed with no refusals;
- portable names must be unique;
- the recorded home inode must match the opened home descriptor.

Any failure gives `config-migration-journal-invalid`, with nothing changed.

**Device numbers.** `st_dev` is not stable across a reboot or remount. ADR
0053 records macOS/APFS changing it while inodes stayed stable. Recorded
device numbers (`home.dev`, entry `dev`, `restored_dev`) are therefore
type-checked evidence only. Every persisted identity comparison uses the
recorded inode on the opened home's current device. Names are resolved only
through the home descriptor and the operation directory, which is proved to be
on the home's device. Size, SHA-256, mode, owner and link-count proofs still
apply. A migration interrupted before a reboot stays recoverable after it.

Every journal update writes `journal.json.tmp`, fsyncs it, renames it over
`journal.json` within the operation directory, and fsyncs that directory.

The states are: `preparing`, `prepared`, `publishing`, `applied`,
`rolling-back`, `rolled-back` and `finalizing`.

### Apply invariants

Each numbered step is durable before the next begins.

- **P1. Confirmation, platform and home.** Confirmation, platform qualification
  and the home descriptor are established, and the home identity is recorded.
- **P2. Existing operation directory.** If the directory exists, apply only
  inspects it, read-only:
  - an `applied` journal whose finalize proof holds returns `already-applied`,
    exit 0, with zero writes;
  - any other state returns `config-migration-recovery-required`, exit 1.
- **P3. Listing.** A `listdir` of the home descriptor, with each entry then
  inspected by non-following `lstat`:
  - no config files gives `config-home-empty`;
  - both families gives `config-home-mixed-format`;
  - CLOE only gives `already-converted`, exit 0, with zero writes;
  - every classified entry must also pass the entry rules and bounds above.
- **P4. Reads.** Each source is read by descriptor, hashed, parsed, merged and
  digested as above.
- **P5. Plan.** `plan_cloe_config_filenames(sources, occupied_names=every entry
  name)`. Any planner refusal is returned with the planner's codes.

**Dry run** stops after P5 with `would-apply`. It creates no directory or lock,
performs no chmod and makes zero writes.

- **A1. Operation directory.** `mkdirat` the directory with mode `0700`,
  validate it, and fsync the home.
- **A2. Lock.** Acquire the lock.
- **A3. Link and fsync probe.** Create `probe`, `linkat` it to `probe.link`,
  require link count 2, fsync the operation directory, then unlink both.
  A link count other than 2, or `EPERM`, `ENOTSUP`/`EOPNOTSUPP`, `EXDEV`,
  `EMLINK`, `ENOSYS` or `EINVAL` from any probe call (create, link, fsync or
  unlink), gives `config-migration-link-unsupported`. Any other `OSError`,
  such as `EIO`, is an ordinary failure: `config-migration-io-error`.
- **A4. Journal `preparing`.** Write the journal with the full manifest.
- **A5. Backups.** Write each `backup-NNNN.bin` exclusively, fsync it, read it
  back bounded, require an equal SHA-256, then fsync the operation directory.
- **A6. Journal `prepared`.** In `preparing` and `prepared`, no home
  configuration name has been touched.
- **A7. Revalidation.** A fresh listing must equal the P3 name set plus the
  operation directory. Each source must keep its exact identity tuple and
  re-read hash. Each target, and every portable alias of it, must be absent.
  Any drift discards the operation-owned directory and returns
  `config-migration-stale`, with the home unchanged.
- **A8. Journal `publishing`.** Fsynced before the first link. Only the
  `publishing`, `applied`, `rolling-back` and `rolled-back` states may coexist
  with renamed names.
- **A9. Publish.** For each entry, in plan order:
  1. `lstat(source)` must equal the recorded identity.
  2. `linkat(source, target)` without following, never replacing. An existing
     target is a failure. Neither `rename` nor `replace` is ever used onto a
     configuration name.
  3. `lstat(target)` must show the recorded inode with link count 2.
     Otherwise fail without unlinking the source.
  4. Fsync the home.
  5. Recheck `lstat(source)`, then unlink the source.
  6. Fsync the home.
- **A10. Post-publish proof.** The fresh listing's configuration names must be
  exactly the targets, all CLOE, and in `proposed_order`. Every target must
  re-read with its recorded identity, link count 1, hash and mode. The
  recomputed effective digest must equal the journal's.
- **A11. Journal `applied`.** Release the lock and keep the directory. The
  result is `applied`, exit 0, with `rollback_available: true` and
  `finalize_pending: true`.

Failure handling:

- **An ordinary exception in A1 to A7.** Discard the operation-owned files and
  return a refusal. If the lock was never acquired, remove only the empty
  directory this call created. If discarding fails, a `preparing`/`prepared`
  journal or journal-less residue remains, and rollback discards it.
- **An ordinary exception after A8.** Run the rollback engine in-process while
  still holding the lock:
  - rollback succeeds: `failed-rolled-back`, exit 1, home restored;
  - rollback refuses: `failed-recovery-required`, exit 1, journal and backups
    retained.
- **A `BaseException` or a process crash.** The durable journal remains for an
  explicit rollback.

### Recovery classification

Every rollback decision classifies each entry from fresh `lstat` and
descriptor reads, whatever the journal position. `R` names the entry's
`restore-NNNN.tmp`.

| State | Observed | Action |
|---|---|---|
| source-only | source with original or recorded restored identity, link count 1, hash; target and `R` absent | none |
| target-only | target with original identity, link count 1, hash; source and `R` absent | link target to source, verify link count 2 and identity, fsync, unlink target, fsync |
| owned dual-link | source and target on the original inode, link count exactly 2, hash; `R` absent | verify, unlink target, fsync |
| restore-staged | source and target absent; `R` has the recorded restored identity, link count 1, hash | link `R` to source, verify, fsync, unlink `R`, fsync |
| restored dual-link | source and `R` on the recorded restored inode, link count 2, hash; target absent | unlink `R`, fsync |
| unjournaled restore scratch | source and target absent; `R` is regular, owned, link count 1, but not the recorded restored identity | unlink `R`, then treat as both-missing |
| both-missing | source, target and `R` absent; backup regular, owned, link count 1, with recorded size and hash | restore from backup |
| anything else | any other combination | refuse with `config-migration-drift` (file = basename) |

Restoring from backup:

An unjournaled restore scratch file is discarded only after its required
backup passes the recorded size and SHA-256 checks. A missing, unsafe or changed
backup refuses the whole operation during preflight, preserving the journal,
scratch file and every configuration entry without writes.

1. Exclusively create `R` in the operation directory.
2. Write the backup bytes into it.
3. Apply `fchmod` with the recorded permission bits, then fsync `R` and the
   operation directory.
4. Durably journal `restored_dev`/`restored_ino`.
5. `linkat` `R` to the source name without replacing, verify the result, and
   fsync the home.
6. Unlink `R` and fsync the operation directory.

A restored file is a new inode. Its owner is the caller and its permission
bits are restored. Its group, ACLs, extended attributes, BSD flags and
timestamps are not preserved. Ordinary publication keeps the original inode
and is unaffected.

Drift also covers configuration-family names absent from the journal, and any
non-journal entry that is a portable alias of a journal source or target.
Refusal changes nothing, and the journal and backups are kept as evidence.
Rollback classifies every entry before it acts on any.

### Rollback, discard, finalize and repetition

**Rollback.** States `publishing`, `applied` and `rolling-back` proceed as
follows:

1. Lock.
2. Validate the journal.
3. Classify every entry.
4. Set state `rolling-back`.
5. Act on entries in reverse order, reclassifying each immediately before
   acting.
6. Prove that the names are exactly the sources in `source_order`, with
   matching hashes and the recorded effective digest.
7. Durably set `rolled-back`.
8. Tear down. The result is `rolled-back`.

**Discard.** A `preparing` or `prepared` journal means no home configuration
name was touched, so rollback only tears down. The result is `discarded`.

A journal-less directory is also discarded, by either rollback or finalize,
but only if it contains nothing outside {`lock`, `journal.json.tmp`, `probe`,
`probe.link`}. That covers crashes between A1 and A4, a crash late in
teardown after the journal was removed, and an empty directory. Apply reports
such a directory as `config-migration-recovery-required`. Any backup or restore
file without a journal is `config-migration-residue-unsafe`. All three commands
validate this allowlist before they open or create the lock, so refused residue
is never modified.

**Terminal states.**

- **`rolled-back`.** Rollback verifies that every entry is source-only and
  resumes teardown. Apply and finalize report
  `config-migration-recovery-required`.
- **`finalizing`.** Finalize verifies that every entry is target-only and
  resumes teardown. Rollback is refused with
  `config-migration-rollback-unavailable`, because finalize has started.

**Teardown.**

1. Validate every remaining file as regular, owned and link count 1. The
   single exception is a crash inside the A3 probe: `probe` and `probe.link`
   may remain as one owned inode with link count 2.
2. Unlink the backups, then any transient names, then the journal, then the
   still-held lock.
3. `rmdirat` the operation directory, then fsync the home.

A lost `rmdir` race reports `operation_directory_retained: true`. A later
rollback discards a journal-less directory.

**Finalize.**

- **Requirements.** The journal state is `applied` (or `finalizing` when
  resuming). Every entry is target-only with its original identity, link
  count 1 and hash. The names are exactly the targets in `proposed_order`, the
  effective digest matches, and no foreign configuration-family names exist.
- **Action.** Durably set `finalizing`, then tear down. The result is
  `finalized`.
- **Other states.** Any other state gives `config-migration-recovery-required`.
  Any drift gives `config-migration-drift`, and nothing is removed.

**Repetition.** With no operation directory:

| Command | Result | Exit | Writes |
|---|---|---|---|
| rollback | `nothing-to-recover` | 0 | none |
| finalize | `nothing-to-finalize` | 0 | none |
| apply on a CLOE home | `already-converted` | 0 | none |

That is also what a completed rollback or finalize looks like when repeated.
After a completed rollback, apply may run again from the start.

### Output contract

The JSON schema is `cloe-config-migration-result-v1`, emitted with `sort_keys`
for every outcome, refusals included. Its keys:

- `schema`, `operation`, `result`, `dry_run`
- `writes_performed`, the number of mutating filesystem calls
- `changes[{source, target, layer}]`, `source_order`, `proposed_order`
- `journal_state`, the state after the command, or null
- `refusals[{code, file}]`
- `rollback_available`, `finalize_pending`, `operation_directory_retained`

Hashes, inode numbers, configuration values, absolute paths and raw exception
text are never emitted.

Exit codes:

- 0: success, a no-op result, or a dry run that would succeed;
- 1: refusal, failure, or a dry run that would refuse;
- 2: usage error.

Text output renders filenames with `repr()`. Refusals also print one stable
summary line on stderr through the existing CLI error printer.

### Atomicity and cooperation limits

- There is no multi-file atomicity. Every intermediate state is durable and
  recoverable. A quiescent loader sees one complete family, or refuses
  `config-home-mixed-format`. Partial and dual-link states contain both
  families.
- A reader whose directory listing overlaps a link or unlink can observe an
  incomplete set. The operator must therefore quiesce the home first: stop the
  local runtime, MCP servers, refresh jobs and editors that use it.
- The window between a name check and the following link or unlink cannot be
  closed against an uncooperative writer running as the same user inside a
  private home. No defense against such a writer is claimed. Observed drift is
  refused without clobbering anything.
- A running container keeps its old bind mounts. Stop the runtime first. The
  next `local up` mounts the converted names.
- Until finalize, the operation directory keeps private `0600` copies of every
  original file. They may include Server credentials or DSNs. Finalize
  permanently removes the ability to roll back.
- If a file was edited after apply, rollback and finalize both refuse. They
  also refuse `config-migration-journal-invalid` if the journal no longer
  validates. The documented manual procedure is:
  1. inspect the home;
  2. keep the wanted bytes;
  3. remove `.cloe-config-migration` yourself, accepting the loss of rollback.

  No command deletes data it cannot prove it owns.

## Scope and Non-Scope

**In scope:**

- the three commands and their API;
- the planner text correction;
- the `local setup` guard;
- operator documentation;
- the roadmap status;
- exact unit and containerized integration owners;
- forward-only static retention enrollment.

**Out of scope:**

- default-home, package, import, executable or repository renames;
- graph, schema or MCP vocabulary changes;
- data or database migration;
- container-runtime operations;
- dependency, lock, metadata or runner-policy changes;
- live homes;
- Windows support.

`runtime/local.py` stays at its 400-line ceiling and is not edited.

## Required tests

**Unit**, covering:

- normal conversion of both layers, preserving bytes, mode, inode, order and
  effective digest;
- Local and Server storage preservation;
- the no-op results: already converted, already applied, nothing to recover,
  nothing to finalize;
- a dry run produces an unchanged snapshot, including on `0700` and `0750`
  homes, with no chmod;
- `0755` home refusal without chmod;
- API and CLI confirmation refusals;
- platform refusal;
- every unsafe entry kind, the limits, mixed and empty homes, planner
  collisions and alias collisions, and invalid TOML, schema or storage;
- a crash injected at every mutation boundary of apply, rollback and finalize,
  each followed by successful recovery to the exact pre-state or the finalized
  state;
- `OSError` auto-recovery;
- the complete classification matrix, including both restore intermediates;
- edited-after-failure and edited-after-apply refusal with evidence retained;
- revalidation races;
- a post-link identity mismatch never unlinks the source;
- lock contention;
- journal tampering;
- a device-number change between apply and recovery;
- residue rules;
- the terminal-state teardown resumptions;
- redaction of a secret sentinel and the home path from output and the
  journal;
- escaping of control characters in text output;
- the setup guard.

**Integration**, in the disposable sandbox, running the real CLI and API on
synthetic Server and Local homes, covering:

- dry run, apply, `config-check`, rollback (byte- and mode-identical), apply
  again, finalize, then the repeated no-ops;
- a driver-free guarded process with no source-root or database access;
- a real dual-link recovery;
- edited-after-apply refusal;
- JSON and exit contracts, and redaction;
- the setup guard.

## Rejected alternatives

- **`rename`/`replace` publication.** It can silently replace a concurrently
  created target, and it loses the dual-link recovery evidence.
- **Copy-and-delete.** It changes inode identity and permission ownership for
  every file, and it multiplies the states in which content can diverge.
- **Treating the saved plan JSON as authority.** It would act on stale
  point-in-time observations.
- **Implicit cleanup of backups after apply.** It would remove rollback without
  confirmation.
- **Keeping backups forever.** Secret duplication would have no supported end.
- **Locking inside every loader and editor.** That is out of scope, and it
  could not bind editors anyway.

## Consequences

Operators get a usable, recoverable legacy-to-CLOE configuration filename
conversion with an explicit end of retention. Every state between commands is
either reported as a stable result or refused without change. A later default
or namespace epic can build on a converted home without owning conversion.

The setup guard and the residue rules intentionally make an unfinished
migration visible and blocking.

### What would make this decision wrong

- A qualified filesystem lets `link` succeed without reflecting link count, or
  lets `fsync` silently no-op in a way the A3 probe cannot observe.
- A qualified filesystem renumbers inodes across a reboot or remount. This
  might happen on some network or FUSE filesystems. Recovery would then refuse
  with `config-migration-journal-invalid` or `config-migration-drift` and
  leave only the manual procedure.
- Some loader accepts a mixed-family home.
- The merged payload carries filename-derived values. Today only internal
  ordering keys and diagnostics carry them.
- An existing RepoMap writer creates configuration-family files in a home
  without passing the setup guard, during a migration the operator believed
  quiescent.

Discovering any of these during implementation is a blocker to report. It is
not a reason to weaken the invariants.
