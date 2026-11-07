# CLOE operator resource reports

How to request, inspect and interpret bounded `cloe-resource-view-v1` report
files. The contract is owned by ADR 0165 and the
[resource report specification](../specs/cloe-resource-reports-v1.md).

Reports are descriptive. They add no work limit, enforcement, schema, graph
vocabulary, MCP field or telemetry service, and nothing is written unless you
pass the option.

## Requesting a report

Add `--resource-report FILE` to exactly one of these single operations:

| Command | Backends | Operation in the report |
|---|---|---|
| `cloe ops refresh-graph` (direct mode) | SQLite Local, PostgreSQL | `local_refresh`, `server_refresh` |
| `cloe ops lexical-build` | PostgreSQL | `lexical_build` |
| `cloe ops lexical-query` | PostgreSQL | `lexical_query` |
| `cloe ops lexical-revoke` | PostgreSQL | `lexical_revoke` |
| `cloe ops context-pack` | SQLite Local, PostgreSQL | `compact_context` |

There is no root-global flag. `refresh-enabled`, `context-select`, vector,
Rust and MCP surfaces do not accept it, and `refresh-graph --mode coordinator`
refuses it with `resource-report-refused: coordinator_mode_unsupported`.

```zsh
mkdir -m 700 ~/cloe-reports            # once; the tool never creates directories
cloe ops refresh-graph --repo-map-home ~/.cloe --graph my-graph --json \
  --resource-report ~/cloe-reports/refresh-$(date +%Y%m%dT%H%M%S).json
```

Destination rules, checked after the command's existing refusals and config
resolution but before any database or source work:

- the parent directory must already exist, be owned by you and have no group
  or other permission bits; its final component must not be a symlink;
- the file must not exist (an existing file, symlink, FIFO or directory is
  refused, never followed or overwritten);
- the file may not lie under the configured home (or, with the deprecated
  `--config FILE` shim, that file's directory), any graph or binding source
  root of any configured graph, a configured server-memory path, an explicit
  `--portable-store-root`, or an explicit context `--source-root`. Config-file
  symlinks also protect their resolved control directory. Metadata identity
  checks cover existing case-insensitive and mount aliases;
- a looped, unresolvable or permission-denied protected root refuses.

Refusals print `ERROR: resource-report-refused: <category>` and exit 1 without
naming a path. Without the option, stdout, JSON, stderr, exit codes and Python
seams are unchanged.

## When a report is written

The file is written once, after the command printed its result and fixed its
exit code. A temporary file is created only then, written fully, fsynced and
installed with a same-directory hard link; an existing target makes it fail
rather than overwrite. Installed files are mode `0600`.

- A raised failure that the command's existing handler catches can write
  `not_recorded`. Returned Server failures retain `failed`, `commit_unknown`
  or `cancelled`; a failure is not automatically an unrecorded operation.
- An uncaught exception or an interrupt during the operation writes nothing.
- If writing fails, you see `WARNING: resource-report-not-delivered: <category>`
  and the command's own result and exit code stand.
  Warnings are best-effort: a broken diagnostic stream does not change the
  operation's result or exit code.
- `WARNING: resource-report-incomplete: <category>` means the complete report
  was installed but temporary-name cleanup or the directory fsync failed. The
  file is kept; a leftover `.cloe-resource-report-*.tmp` is a second link to
  the same data and can be removed by you.
- An interrupt during report writing alone may make the exit status reflect
  the interrupt after stdout already showed a committed result. The
  publication is still committed; nothing relabels it as rolled back.

`context-pack` early refusals (budget, request validation, unsupported modes)
write no report, because no owner ledger served them.
Context reporting projects the returned packet and never injects a ledger or
starts another query. Owner controls which the packet cannot establish remain
unknown.

## Inspecting a report offline

```zsh
cloe ops resource-report check --input ~/cloe-reports/refresh.json
cloe ops resource-report show --input ~/cloe-reports/refresh.json
cloe ops resource-report show --input ~/cloe-reports/refresh.json --json
```

These commands take no home or config option and open no configuration,
database, source or worker. They read at most 8193 bytes from a private
regular file you own (a second hard link is accepted; symlinks, FIFOs,
devices and directories are refused unopened). Invalid input prints
`ERROR: resource-report-invalid: <category>`, for example `not_canonical`,
`duplicate_key`, `invalid_domain`, `too_large` or `unsafe_input`.

A valid file is exactly the canonical compact JSON plus one LF. `show --json`
prints those bytes; `show` prints one row per metric and limit.

## Reading the fields

Seven fields: `schema`, `operation`, `backend`, `outcome`, `instrumentation`,
`metrics`, `limits`. No identities, paths, query text, bodies, provenance,
environment or error text are kept.

- Each metric is `measured` with a `basis`, or `unavailable` with a `reason`
  such as `not_started`, `not_reached`, `not_selected`, `invalid_owner_value`
  or `observer_failed`.
- Each limit is an existing owner control. `applies_this_call` is `true`,
  `false` or unknown (`null`); unknown is never a hidden yes.
- `lexical_query`: outcomes `available` and `not_run` are different, and
  `available` does not claim complete scope. Hit and omission counts come from
  the service envelope, not the possibly shortened CLI output. An immediate
  envelope proves the statement timeout did not apply; on the SQL path it is
  unknown.
- `lexical_revoke`: `--dry-run` reports outcome `preview` with every effect
  `not_selected` (its candidate counts are not purges). With purging disabled,
  purge counts are `not_selected`, not measured zeros. The statement timeout
  is the owner's constant, not configuration.
- `compact_context`: a packet whose owner failed after admission reports
  outcome `not_recorded` with no backend and no counters.

## What a report does not prove

Validation proves format and domain validity only. It is not evidence of who
produced the file, that measurements are true, or that a publication or
transaction succeeded; the file carries no signature or identity binding.
Separation checks hold for stable configured roots at admission time; a
same-UID process that renames or mounts directories afterwards is out of
scope, and identity-checked temporary cleanup is not isolation from such a
process. POSIX `fsync` is not macOS `F_FULLFSYNC` and does not guarantee
durability against every power failure.
