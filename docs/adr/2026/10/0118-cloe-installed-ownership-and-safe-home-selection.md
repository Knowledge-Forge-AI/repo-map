# ADR 0118: CLOE installed ownership and safe default-home selection

## Status and authority

Accepted before implementation, 2026-10-30, for REPOMAP-CLOE-OWNERSHIP1.
The maintainer requests continuing the accepted CLOE roadmap. This decision
instantiates W1's selected names and compatibility requirements; it does not
reopen naming or grant a repository rename, deployment or package publication.
Independent native design review found no reserved operator choice blocking
this bounded sequence. Native assistance is advisory; the parent owns acceptance.

## Installed-file ownership

The atomic package cutover will use distribution `common-lore-index`, canonical
Python namespace `common_lore_index` and resource prefix
`share/common-lore-index`. One distribution owns `cloe`, `common-lore-index`
and the transitional `repomap-kg` command through v0.1.x. They share one command
implementation; compatibility notices use stderr, preserving JSON and MCP stdout.
The command compatibility window does not promise every internal Python module
as a stable API. Inventory documented Python consumers before selecting any
explicit facade; do not install generic import hooks, duplicate module identities
or eager imports of optional drivers. No compatibility distribution is added.

The supported upgrade uses a fresh isolated environment, or removes the legacy
distribution before installing its replacement. Old and new distributions in
one environment are unsupported: their shared command may be overwritten and
uninstalling either may remove it. Runtime/doctor detection can diagnose this;
it cannot claim to prevent installer writes. Separate environments do not prevent
PATH shadowing or establish concurrent mutation safety for one home. Before the
cutover, prove both install orders and uninstall effects in disposable environments.

Distribution metadata, namespace, entrypoints and installed resource prefix move
together. No partial distribution rename ships ahead of the namespace move.
During preparation, the existing distribution, imports and installed paths remain
`repomap-kg`, `repomap_kg` and `share/repomap-kg`. Centralize their ownership now;
do not add an old-resource fallback after the future switch. Preserve SQL subtree
bytes, relative migration paths, changeset IDs and checksums with a golden catalog.

PyPA's [installed-project specification](https://packaging.python.org/en/latest/specifications/recording-installed-packages/)
records files per distribution and describes removing recorded files on uninstall.
Its [entrypoint specification](https://packaging.python.org/en/latest/specifications/entry-points/)
describes generated console wrappers. These explain the collision risk; they do
not qualify any particular installer or installation mode. Both were read on
2026-10-30. This decision adds no dependency or installer integration.

## Safe home selection: first source milestone

All consumers retain one shared selection contract. An explicit invocation home
wins, followed by nonempty `CLOE_HOME`, then nonempty `REPOMAP_HOME`. Explicit
selection does not merge homes or bypass existing command-specific validation.
`CLOE_PATH` remains unrelated and is never read.

When no selector is explicit:

| Observed defaults | Selection |
|---|---|
| Recognizable, owned private `~/.cloe` | Select it without merging the legacy home. |
| New default absent, empty or foreign; recognizable private `~/.repo-map` | Select the legacy home and issue a bounded compatibility notice; a foreign new default is left untouched. |
| Both absent, or private new default empty and legacy absent | Select `~/.cloe` without creating it. Explicit setup initializes it privately using CLOE filenames. |
| Remaining existing, unsafe, unreadable or unrecognized candidates | Refuse with a stable diagnostic suggesting explicit `CLOE_HOME`; do not silently initialize a second home. |

Recognition requires an ordinary owned private directory and ordinary owned
configuration files in one supported filename family, valid schema/layering and
an explicit supported storage or PostgreSQL configuration witness. A directory's
existence, a marker-like filename or arbitrary TOML alone is not ownership proof.
Implicit discovery does not follow symlinks. Existing explicit custom-home routes
retain their validation contracts. Diagnostics identify selector categories, never
home paths, file contents or environment values.

Selection is read-only. No default-home relocation, copying, source ingestion,
database query, writer acquisition or live service operation occurs. Existing
legacy clients keep the selected original home. This does not fence binaries that
ignore future cutover markers, or claim that two already existing homes are one
database. Relocation and recovery after post-cutover writes remain a later slice.

The Path-returning resolver API remains available. CLI notices use stderr and
must not corrupt JSON or MCP transport. Explicit-home requirements on migration
apply/rollback/finalize remain intact. Fresh default setup uses CLOE filenames;
existing families and explicit format requests retain their authority.

## Preparation: second source milestone

Centralize installed resource ownership without moving it. Correct the identity
licence from the stale Apache string to `AGPL-3.0-or-later`, matching LICENSE and
pyproject; this corrects description, not licensing. Keep identity keys, current
distribution/import/executable values and durable identifiers unchanged. Prepare
parser branding through an explicit parameter while preserving the current
entrypoint and its existing no-argument seams. Do not infer branding from argv[0].

Freeze graph/control catalog bytes and durable ledger/table/comment identities.
The canonical namespace move, compatibility-consumer disposition, package metadata
cutover, installed matrix, generated absolute MCP executable and repository-bound
proof migration remain subsequent coordinated work. Private W2/W5 experiments
stay preserved with their owners and will use an explicit module path map.

## Evidence and boundaries

Use canonical exact scoped unit and containerized integration selectors with
`--no-coverage`, including every default-table row, custom homes and spaces,
environment precedence, read-only noncreation, unrelated new-default preservation,
legacy graph readback and migration's explicit-selection rule. Prove default setup
does not create a new home when a recognizable legacy home is selected. Include
JSON/MCP transport and optional-driver import guards. Test resource selection in
source and simulated installed layouts against the frozen catalogs.

Require independent resulting-state review and fresh static/suppression/export/
privacy checks before commitment. Complete local suites, Python project coverage,
local application/SDK builds, wheel/install campaigns, dependencies, lock/pin/
workflow policy changes, debt growth, main promotion, tags, package publication
and live-home mutation are excluded. Public CI remains batched around useful
milestones and requires a fresh exact-candidate campaign binder; this ADR does
not rearm any spent allocation. Preserve the protected checkout and all reported
phase commits. Public author and committer remain Samuel Leighton Lair
<sam.lair@knowledge-forge.ai>.
