# ADR 0109: CLOE configuration compatibility and filename migration planning

## Status

Accepted for `REPOMAP-CLOE-CONFIG1` under the operator's 2026-10-29 instruction
to advance the reviewed roadmap to the next implemented public-CI milestone.
This decision precedes implementation. Publication is a separate final action.

## Date

2026-10-29

## Context

Preview v0.0.3 is public main at `5ad00d1`, qualified by CI87 attempt 1.
The operator selected Common Lore Index (CLOE) as the successor identity and
authorized the next roadmap milestone. The first compatibility slice prepares
configuration before a broad package/import/repository rename. The qualified
public staging checkout is its implementation baseline. The protected private
checkout and its independently mapped concurrent changes remain intact; this
does not claim private-line reintegration complete or begin namespace churn.

Existing homes load all `*.rp.toml` base files before `*.rpl.toml` local
overlays, alphabetically within each group. Straight suffix replacement can
change order or collapse distinct files. For example `x.local.rp.toml` and
`x.rpl.toml` both map to `x.local.cloe.toml`; `base.extra.rp.toml` precedes
`base.rp.toml`, while their converted names sort in the opposite order.

## Decision

1. An explicit invocation home remains highest priority. A nonempty
   `CLOE_HOME` next overrides nonempty `REPOMAP_HOME`. Empty values fall through.
   `CLOE_PATH` is unrelated and ignored. The existing `~/.repo-map` default
   remains during this preparatory slice; default-home cutover is a later
   coordinated migration decision. Resolution alone creates no directories.
2. A home can contain either legacy configuration or CLOE configuration.
   CLOE base files end in `.cloe.toml` excluding `.local.cloe.toml`; local
   overlays are classified first and load once after all base files. Each
   group sorts alphabetically. Top-level discovery and existing merge/backend
   selection semantics remain. A mixed legacy/CLOE home is refused explicitly.
   Unrelated TOML files keep their existing ignored-file diagnostics. CLOE
   suffixes cease to be unrelated: a legacy home that previously ignored such
   a file now explicitly refuses the mixture. This is intentional.
3. Add `repomap-kg ops config-migration-plan` with an optional explicit home
   and `--json`. It reads configuration files only, validates their existing
   TOML/schema/discovery boundary, and returns a filename-conversion plan.
   It never reads source roots, accesses a database, resolves external credentials,
   renames a file or creates a destination. It needs no PostgreSQL driver.
   A plan is not permission to apply migration or proof of data-cutover safety.
4. Plan names map `.rp.toml` to `.cloe.toml` and `.rpl.toml` to
   `.local.cloe.toml`. Refuse unresolved target collisions, base-to-overlay
   reclassification and any change to the complete existing layer/order
   sequence. Report the old and proposed filename order without config values,
   secrets, absolute home paths or effective payloads. Stable diagnostic codes
   replace raw parser/I/O error messages. Already occupied target names,
   including non-file entries, are refused. This is a point-in-time plan,
   not a filesystem reservation. Valid CLOE homes yield
   an explicit no-conversion plan. Exit 0 means filename conversion is ready
   or unnecessary; exit 1 means a refused plan or invalid input.
   Collision comparisons conservatively use NFC normalization and case folding.
   The planner's `--config` alias requires a directory; `--repo-map-home` wins
   when both are supplied. `REPOMAP_OPS_CONFIG` is not a planner selector.

Container-runtime setup remains a legacy filename producer. Actual setup of
an owned CLOE-format home is refused before runtime/configuration/credential
writes with `cloe-runtime-setup-deferred`; dry-run remains its existing generic
legacy-template preview. Template conversion is a later W1 slice. The shared
loader, Local state operations and MCP support the new family.

Test isolation clears the newly recognized ambient CLOE_HOME before collection
and before each test;
tests may select it explicitly. Existing guarded child-launch helpers also
scrub it before explicit per-child overrides. This preserves test-owned state
without changing gate populations, coverage authority or runner permissions.

## Scope and non-scope

This is implemented compatibility preparation, not a cosmetic docs milestone.
Keep the distribution, console command, Python namespace, version, wire names,
persisted identities, migration catalogs and checksums unchanged. No new
dependencies, lock/pin changes, live-home mutation, repository rename, deployed
runtime change or schema migration is included. There is no new optional
service. SQLite Local must retain driver-free configuration and planning.

Every old test/build observation stays bound to its original candidate.
Seven native AMD application starts are spent. This ADR does not reset that
ledger or authorize an eighth start. One eventual new candidate requires
fresh hosted admission before publication; no known-red stale grant is used.

## Required evidence

Scoped unit owners cover environment precedence without creation, exact legacy
and CLOE layer order, mixed-format refusal, collision and reclassification,
suffix-induced order reversal, valid no-op plans, invalid schema and redaction.
Scoped containerized integration owners exercise the real CLI and loader for
both backends, including driver-free Local, JSON/exit behavior, unchanged
source bytes, no source-root reads and no home/destination writes.

New code is enrolled under existing clean/ratcheted ownership with no new debt,
threshold or exclusion. Run canonical scoped owners with `--no-coverage`,
changed-source static checks, export/privacy checks and independent source
review. Hosted qualification remains pending for the successor candidate.

## Alternatives and consequences

A broad search/replace or immediate default-home switch couples naming with
data cutover and can reorder configuration. Deferring all compatibility work
until the namespace move makes those defects harder to isolate. This slice
offers usable new-format configuration and an inert, explicit planning
surface first. Full rebranding and apply/rollback remain roadmap W1 follow-ups.
