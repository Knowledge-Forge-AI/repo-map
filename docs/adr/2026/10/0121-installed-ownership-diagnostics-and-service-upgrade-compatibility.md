# ADR 0121: Installed ownership diagnostics and service-upgrade compatibility

## Status and authority

Accepted before implementation, 2026-10-30, for REPOMAP-CLOE-INSTALL1.
The maintainer reports CI passed and requests continuing the accepted roadmap.
This bounded two-part W1 milestone implements necessary upgrade diagnostics
before ADR0118's atomic package/import/resource/entrypoint cutover. It does not
rename the package or repository, install a wheel or touch a live service/home.
The parent checked native read-only design advice against current source;
no reserved operator decision is needed for these source prerequisites.

CI97 qualifies staging `b90fa8e9c8126be2eac73620001c3869b2cf8e33`:
all nine jobs passed, and retained same-attempt smoke/M/A and system artifacts
validate against independently derived committed source. Unit coverage is
88.0%/87.6%, measured integration 90.1%/82.2%; both two-point margins are met.
This does not qualify the successor. Its fourteenth native AMD start stays spent.

## Installation ownership diagnostics

Add an explicit `identity --installation-check` mode, supporting existing
`--json`. Preserve the ordinary identity payload's exact six keys and values.
The new mode reports `cloe-installation-ownership-v1`, the expected distribution,
bounded counts for only `repomap-kg` and `common-lore-index`, categorical state
and diagnostic codes. Counts saturate at two: duplicate metadata is a conflict.
Names are compared using normalized distribution spelling. A single expected
owner is `single-owner`; both names or duplicates are `conflicting`; a sole
other owner is `owner-mismatch`. Missing or unreadable metadata is `unverified`.
Exit 0 only for a single expected metadata owner, otherwise 1; usage errors stay 2.

Use only standard-library metadata discovery. Do not import either distribution's
entrypoints or optional drivers, run installers, inspect source/database material,
probe PATH, or modify the environment. Emit only known distribution names, counts,
states and codes: no metadata contents, versions, locations, exception messages,
environment values or executable paths. A source checkout without metadata is
unverified, not proof of a healthy installation. This is metadata evidence, not
installer/file ownership, entrypoint integrity, wheel contents or runtime health
qualification. It does not claim to prevent pip overwrites or uninstall effects.

## Persisted service definitions

Generated native service argv must derive the module from the existing import
owner constant. Keep service identities, filenames, labels, exact argv shape,
approved executable hashes, environment restrictions and ownership checks stable.
Add one shared module classifier: current import owner, the exact legacy
`repomap_kg` token when different from current, or unrecognized. Do not accept
arbitrary module prefixes, aliases, casing, extra argv or modified definitions.
Adapters first validate the entire closed definition shape; module recognition
alone never establishes ownership or permits mutation.

An exactly recognized legacy definition supports status and explicit uninstall.
Status preserves its JSON keys, returns result
`service_legacy_module_reinstall_required`, installed true, readiness false and
unknown active/enabled state without manager or health calls. Validate, start,
stop, restart and upgrade refuse it with that stable code. Reinstallation is
explicit uninstall followed by install; upgrade cannot silently activate an old
module or roll back into one. Unrecognized definitions remain refused.

Legacy uninstall may stop and disable the exact recognized unit and remove its
owned file using existing custody checks. On failure it may restore the original
file, but must never enable or start the legacy module, including rollback after
stop/disable/removal/reload failure. Return bounded recovery-required/rollback
failure diagnostics and require explicit operator recovery. Current-module
rollback behavior remains unchanged. This phase performs no real host service
manager operation: tests use disposable files and recording native-manager doubles.

Before cutover, `repomap_kg` is still current. Scoped tests simulate the future
owner to exercise persisted legacy definitions; that does not qualify a renamed
installed distribution or native lifecycle after an actual package replacement.

## Consumer and namespace continuity

The documented Python API under `repomap_kg.ops.config_migration` is real consumer
evidence, unlike historical extraction examples. Do not adopt the design assist's
unsupported claim that no library APIs are documented. Inventory/document the
explicit consumer surfaces before choosing future facades. The no-facade policy
is not accepted here. Broad namespace/root projection and immutable retained
history need an exact mechanical path-map proof before the atomic move; historical
authority, SQL/catalog bytes, wire identifiers and debt ceilings stay intact.

## Evidence and exclusions

Add exact unit and containerized integration owners for both changed boundaries,
with --no-coverage. Exercise real metadata files with standard-library discovery,
safe CLI output and unchanged default identity, exact service-definition parsing,
legacy status/refusals/uninstall and failure recovery without legacy activation.
Preserve current adapter, lifecycle and optional-driver characterization.
Require independent resulting-state source/grant review and full static,
suppression/export/topology/length/compile/privacy checks before publication.

Complete local suites, project coverage, local application/SDK builds, wheel or
install campaigns, new dependencies, package metadata/lock/pin changes, workflow
policy changes, live activation, repository rename, package publication, main
promotion and tags are excluded. A later fresh exact-candidate staging campaign
must account for spent starts and bind its own authority; this ADR rearms none.
