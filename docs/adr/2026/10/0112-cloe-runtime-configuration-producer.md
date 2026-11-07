# ADR 0112: CLOE runtime configuration producer compatibility

## Status and authority

Accepted before implementation, 2026-10-29, for REPOMAP-CLOE-RUNTIME1 under
the maintainer's instruction to continue the roadmap to the next milestone
and public CI. This is the next bounded W1 slice after CI92-qualified
configuration compatibility at bec838a210f3ffea84986ae85986e4081b2e8291.
The parent selects the runtime producer boundary within that roadmap authority.
It does not authorize live-home mutation or the broad namespace cutover.

## Context

The loader and filename planner understand CLOE configuration, but container
runtime setup still writes repomap.rpl.toml and deliberately refuses every
CLOE home. Compose already mounts the exact config_files selected by the
shared loader; no fixed legacy filename exists in runtime plan records.
Changing the producer can therefore enable an integrated CLOE-format runtime
home while retaining graph, database, service and wire identities.

## Decision

Add local setup --config-format legacy|cloe and the equivalent optional
setup_local_runtime(config_format=...) keyword. Without an explicit format,
use the existing home's single active family; an empty home retains legacy.
An explicit format conflicts with an existing different family and refuses
before runtime/configuration/credential writes. Mixed active families refuse.
Home selection, including CLOE_HOME precedence, remains independent of format.

The generated overlay is repomap.rpl.toml for legacy and
repomap.local.cloe.toml for CLOE: the latter is the existing filename planner's
exact conversion of the former. Reuse the same template payload and preserve
all graph/database identifiers, secret references and runtime identity hashes.
Do not rename, delete, migrate, overwrite or rewrite existing configuration.
Existing user overlays keep their order and values; normal merge semantics
still govern them. Existing generated targets are retained unchanged.
As with legacy bootstrap, creating the full default overlay can override
base-file values. Later-sorting local overlays win; a preconfigured home must
keep its intended overrides there or in its already-converted canonical
target. This producer is not a semantics-preserving configuration migration.

Validate format arguments before creating a home. Actual setup establishes
the existing private-home authority before inspecting its files. Validate
format/family and the generated target before creating runtime directories or
credentials. Generated targets must be ordinary owned files; refuse directories,
symlinks (including broken links) and portable case/normalization aliases.
Create a new target exclusively with no-follow and private permissions. No
transactional home migration or concurrent hostile-writer guarantee is claimed.
Later setup failure retains the existing partial-setup recovery behavior.
This deliberately tightens legacy setup too: existing generated targets that
are symlinks, non-files, foreign-owned files or portable aliases now refuse.
Other legacy base directories/broken links remain inactive discovery entries.
Owned ordinary generated targets keep their existing bytes and permissions,
including broader file modes protected by the private home directory.

For CLOE homes, validate existing TOML/schema and backend declarations before
admitting the new producer; refuse malformed or conflicting configuration.
Container-runtime setup refuses a known SQLite Local backend in either family
before writes. It never changes a home from SQLite to PostgreSQL. Preserve the
legacy setup's existing tolerance of malformed/incomplete legacy configuration
where its backend cannot be established; this is not new migration readiness.
Malformed legacy TOML, bad schema and unknown/non-table storage declarations
retain that tolerance. Read failures wrapped by the existing TOML reader also
retain it; unavailable directory traversal and undecodable input fail with a
bounded preflight refusal. No malformed configuration is certified usable.
No database, container command or source-root access belongs to this preflight.

Dry-run selects and reports the format without creating, chmodding, writing
or generating credentials. It can refuse incompatible format/backend/target
inputs; its runtime plan remains the existing generic template preview.
A broad-permission ordinary home remains inspectable in dry-run, while actual
setup preserves its private-home refusal. Symlink homes are never inspected.
JSON diagnostics name the format/ordinary generated filename, without config
values, credentials or additional private paths.
Every dry-run planned command pins its selected --config-format so replay
cannot silently choose a different family for a previously empty home.
If exclusive target creation fails after writing starts, an incomplete new
target may remain; preserve and inspect it, then remove only that failed
generated file before retry. Setup does not rewrite it automatically.

Runtime setup/status/up/down and Compose continue using the shared loaded
configuration. Prove CLOE setup, config-check, status and a nonexecuting up
plan through the real CLI in the disposable sandbox; inspect the generated
Compose mount for the actual CLOE filename. Existing legacy setup remains the
default on empty homes. Preserve idempotence and secret bytes on repeat setup.

## Ownership and evidence

Put format/target preflight and exclusive configuration creation in one small
runtime owner. Keep local.py within its existing 400-line ceiling and preserve
its public facade imports through private helper aliases. Admit new maintained
product/test owners cleanly through the existing forward-only retention proof;
do not regenerate baselines or increase debt, exclusions or thresholds.

Use exact scoped unit selectors for format selection, legacy compatibility,
no-overwrite, private creation, conflict/SQLite/unsafe-target refusals and dry-run.
Use exact containerized integration selectors for the real CLI and generated
mount/readback boundary. All local tests use --no-coverage; complete populations
and coverage remain hosted. Native independent source review, static/export/
privacy checks, a professional commit and exact-commit local report precede one
public staging publication. A separate fresh campaign grant retains all spent
build observations; CI92 cannot qualify the changed successor.

## Alternatives and boundaries

Keeping the blanket CLOE refusal leaves the loader disconnected from runtime
provisioning. Switching all empty homes to CLOE would combine the producer with
the later default/package/import migration. Automatic legacy conversion would
need the deferred backup/apply/rollback contract. This slice chooses none of
those: it enables explicit new-format setup and existing CLOE homes safely.

No package/import/executable/default-home/repository rename, wire or schema
change, live runtime operation, dependency/pin change, local application/SDK
build, complete local suite, project coverage, main promotion, tag or deployment.
The protected private checkout and its reconciliation decisions remain intact.
