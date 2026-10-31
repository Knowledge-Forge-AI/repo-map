# CLOE installed upgrade compatibility

The distribution is `common-lore-index`, its canonical import namespace is
`common_lore_index`, and installed resources live at `share/common-lore-index`.
The preferred command is `cloe`; `common-lore-index` names the same implementation.
The transitional `repomap-kg` command remains through v0.1.x and prints a bounded
notice on stderr. Version and help use the explicitly selected command name;
identity keeps six keys, with the current distribution/package/CLI values.
MCP wire names and schemas remain unchanged.

## Distribution metadata ownership

```sh
cloe identity --installation-check --json
```

This explicit mode reports `cloe-installation-ownership-v1`. Ordinary
`identity --json` keeps its original six fields. The diagnostic reads only
metadata for the two selected distribution names; it loads no entrypoint or
optional driver and does not inspect a home, database or PATH.

| State | Meaning | Exit |
|---|---|---|
| `single-owner` | One expected distribution's metadata is present. | 0 |
| `conflicting` | Both distributions or duplicate normalized metadata records exist. | 1 |
| `owner-mismatch` | Only the other selected distribution's metadata exists. | 1 |
| `unverified` | Metadata is absent, malformed or unavailable. | 1 |

Usage errors remain exit 2. Counts saturate at two; unavailable observations
are null. Names are normalized for comparison. Output contains only known names,
counts, states and diagnostic codes. Locations, versions, arbitrary metadata,
exception messages and environment values are omitted. A source checkout without
metadata is unverified. Exit 0 confirms metadata consistency only: it does not
qualify installed files, wrappers, resources, importability or runtime health.

Old and new distributions sharing one environment remain unsupported. A fresh
isolated environment, or removal of the old distribution before replacement,
is the supported route. This diagnostic cannot prevent installer overwrites or
uninstall side effects. The disposable offline installed matrix covers both install orders and removing
either owner. Both metadata owners are diagnosed as conflicting; uninstalling
either can remove the shared `repomap-kg` wrapper and all six shared legacy
package files. The matrix verifies their presence before and absence after each
removal. This observed behavior confirms
that overlap is unsupported; it does not certify arbitrary installer versions.

## Persisted native service definitions

Service generation derives its module from the current import owner. Strict
recognition retains the complete v1 definition: exact argv/fields, private owned
file, approved executable hashes, restricted environment, labels and filenames.
The module may be current or the exact legacy `repomap_kg` token when the current
owner changes. Prefixes, arbitrary aliases, extra fields and malformed content
are refused. Existing v1 identifiers and closed fields remain stable during the
package move; do not mechanically replace them as branding text.

A legacy definition's status reports
`service_legacy_module_reinstall_required`, installed true, ready false and unknown
active/enabled state. Status makes no native-manager or health call and changes
no files. Validate/start/stop/restart/upgrade refuse that definition after their
existing configuration preflights. Use explicit
uninstall followed by install after selecting the replacement environment.

Uninstall retains ownership checks and may stop/disable the exact recognized
unit. On failure it restores the prior file when possible, but never starts or
enables the legacy module, including rollback. A
`service_uninstall_legacy_recovery_required` or rollback-failure result requires
operator inspection/recovery; it does not claim the prior active state was restored.
Current-module lifecycle and rollback behavior remain unchanged.

New definitions use `common_lore_index`. Tests explicitly render old `repomap_kg`
definitions before checking status and uninstall with disposable files and
recording manager doubles on Linux/macOS formats. They do not establish
native installed lifecycle qualification after a real package replacement.

## Finite Python compatibility

| Legacy surface | Supported behavior through v0.1.x |
|---|---|
| `python -m repomap_kg` | Delegates the canonical CLI, with explicit legacy branding and a stderr notice. |
| `python -m repomap_kg.server.mcp` | Delegates the canonical read-only stdio server; the notice stays on stderr. |
| `repomap_kg.ops.config_migration` | Reexports `apply_cloe_config_migration`, `rollback_cloe_config_migration` and `finalize_cloe_config_migration` as the identical canonical objects. |
| Root constants/version | Direct canonical reexports, without optional-driver loading. |

Other internal old imports, including `repomap_kg.cli`, `repomap_kg.storage` and
implementation functions under the MCP shim, are unsupported. Use the canonical
namespace. No generic import hook or duplicate canonical implementation is installed.
Generated absolute MCP launches should use the selected environment's Python and
`-m common_lore_index.server.mcp`; no live client configuration is changed here.

SQL catalogs, relative migration paths, changeset IDs/checksums, wire names,
service labels/filenames and recovery journal identities retain their contracts.
Current runner and retention owners follow a complete source map; historical
authority bytes and every numerical ceiling remain intact. Test-directory names
remain unchanged. Private W2/W5 experiments retain their owners and the explicit
module path map; the protected private checkout has not been mirrored or reset.

Fresh isolated installation, or removing the legacy distribution before installing
the replacement, is the supported route. Keep the original explicit home for
rollback to the qualified incumbent in a fresh environment. No data migration or
automatic rollback after subsequent live writes is implied.
