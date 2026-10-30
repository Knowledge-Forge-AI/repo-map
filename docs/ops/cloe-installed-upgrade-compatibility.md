# CLOE installed upgrade compatibility

The current package, import namespace and command remain `repomap-kg`,
`repomap_kg` and `repomap-kg`. ADR0118 selects their coordinated replacement;
this prerequisite milestone adds diagnostics and service-definition compatibility,
not the package cutover itself.

## Distribution metadata ownership

```sh
repomap-kg identity --installation-check --json
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
uninstall side effects. Both install orders and their uninstall effects still
require disposable-environment proof before the atomic cutover.

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

The current `repomap_kg` module is still current, so ordinary definitions keep
their existing behavior. Tests simulate a future owner using disposable files
and recording manager doubles on Linux/macOS formats. They do not establish
native installed lifecycle qualification after a real package replacement.

## Consumer inventory for the later atomic move

| Current surface | Evidence and disposition |
|---|---|
| `python -m repomap_kg` | Current documented module invocation; command/module compatibility must be settled with entrypoints in the atomic move. |
| `python -m repomap_kg.server.mcp` | Documented host-native MCP launch path; update generated absolute launch configuration and prove transport. |
| `repomap_kg.ops.config_migration` | Explicit documented Python API for apply/rollback/finalize; requires a deliberate compatibility-facade disposition, not an assumed no-library-API policy. |
| `repomap_kg.server.mcp.repomap_node_locations` | Navigation documentation references its implementation; preserve the MCP wire contract and distinguish it from a promised generic Python facade. |
| Generated native service argv | A persisted consumer; retain exact legacy recognition and explicit recovery above. |
| Architecture/complexity references and historical ADR examples | Source-location/evidence references are not automatically executable compatibility consumers. Preserve historical text and classify current links separately. |
| Private W2/W5 experiments | Preserve their owners and use an explicit reviewed module path map; no blind mirroring or deletion. |

No Python facade policy is selected here. The later move must cover distribution,
namespace, entrypoints and resource prefix together, keep SQL/catalog and durable
identities stable, and prove an exact mapping for live runner/retention owners.
Historical authority bytes and numeric debt ceilings must not be rewritten to
make a new namespace appear qualified. Test directory names need not move merely
because product imports change.
