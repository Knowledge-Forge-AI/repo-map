# Remaining Storage Readback Canonical Default Design

Date: 2026-07-05

## Status

Accepted for Phase F9 as a design checkpoint. F9 does not change CLI behavior.

LOCAL32 supersedes the `storage files` decision below by removing that command
and adding the separately named canonical `ops graph-files` contract. LOCAL35
supersedes the `storage entrypoints` decision by removing that command and
mapping its stored inventory purpose to an explicit canonical graph-file role
filter. LOCAL38 supersedes the `storage file-nodes` decision by removing that
command without an alias, fallback, or new evidence command.

## LOCAL32 Migration Update

`storage files --root-path <root>` is removed without an alias, compatibility
mode, or legacy fallback. Migrate callers to:

```text
ops graph-files --graph <graph-id> [filters] [--limit 50] [--offset 0] [--json]
```

The replacement requires an operations graph registration and scopes storage
by its stable repository name. Direct root, host, port, user, and database
arguments are removed. JSON changes from an unbounded bare list to a versioned
envelope with bounded canonical records, pagination, observation state,
ambiguity, and aggregate evidence. Table columns change accordingly. Valid
empty pages still exit zero; graph, configuration, connector, and readback
failures exit one; parser validation failures exit two.

The old role, language, generated, and JSON intentions map to canonical
filters and presentation, but the data contract is intentionally different.
Top-level `files` remains available for explicitly named raw JSONL inventory.
LOCAL35 completes the separate `storage entrypoints` migration described next.

## LOCAL35 Migration Update

`storage entrypoints --root-path <root>` is removed without an alias,
compatibility mode, or legacy fallback. Migrate stored-data callers to:

```text
ops graph-files --graph <graph-id> --role entrypoint --observation-state observed [--limit 50] [--offset 0] [--json]
```

The replacement requires explicit configured graph identity and removes direct
root and database connection arguments. JSON changes from an unbounded bare
list of legacy file rows to the versioned, bounded `graph-files` envelope.
Table output changes to the canonical graph-file columns. Valid empty pages
exit zero; graph, configuration, connector, and readback failures exit one;
parser validation and the removed command exit two.

The `entrypoint` role filter represents observed canonical file inventory. It
does not promote file-role evidence into a cross-language canonical entrypoint
node or edge model. The top-level `entrypoints` command remains available for
explicitly named raw-observation JSONL.

## LOCAL38 Migration Update

`storage file-nodes --root-path <root> [--path <path>]` is removed without an
alias, compatibility mode, or legacy fallback. Migrate file-list callers to:

```text
ops graph-files --graph <graph-id> [--path <repo-relative-path>] [filters] [--limit 50] [--offset 0] [--json]
```

The replacement requires explicit configured graph identity and changes the
old unbounded bare-list or six-column table into the bounded canonical
`graph-files` envelope or table. It does not preserve legacy node stable keys,
evidence stable keys, source identifiers, or the old co-location join between
one legacy file node and every legacy evidence row attached to its file.

Use canonical file neighborhoods or canonical neighborhoods for graph context
and edge explanation for evidence behind a selected canonical edge. Explicit
stored raw-observation lookup remains separately named and bounded through
MCP, with full raw payload inclusion disabled by default. The removed command
and parser validation failures exit two; configured graph, connector, and
readback failures exit one; valid empty canonical pages exit zero.

## Current State After F8

After F8, these storage readback commands are canonical by default:

- `storage summary`;
- `storage nodes`;
- `storage edges`;
- `storage neighborhood`;
- `storage file-neighborhood`;
- `storage host-mutators`;
- `storage host-mutators-summary`.

The only remaining legacy-default storage readback commands are:

- `storage files`;
- `storage entrypoints`;
- `storage file-nodes`.

F9 decides that these commands should not be migrated before the readability
refactor. They remain intentionally legacy by default because their current
meaning is not a simple canonical identity-shape migration.

## Design Problem

The remaining commands expose older observation-derived storage surfaces:

- `storage files` lists stored `FileRecord` inventory rows with role, language,
  generated, executable, and confidence fields.
- `storage entrypoints` filters those same file rows to role `entrypoint` and
  reuses the raw `entrypoints` presentation.
- `storage file-nodes` lists legacy normalized file graph nodes and evidence
  rows attached to file paths.

Canonical storage has durable `file:<path>` nodes and canonical edge/readback
commands, but that does not make these commands equivalent:

- canonical file nodes do not carry every stored file inventory field;
- entrypoint observations do not yet have one durable cross-language canonical
  entrypoint model;
- `file-nodes` names a legacy normalized graph concept directly.

Migrating these defaults now would silently redefine public identity and count
semantics. F9 chooses explicit canonical replacements where they exist, and
defers any broader entrypoint model until after the refactor.

## Decision Summary

### `storage files`

Decision: keep legacy by default.

Rationale:

- The command is a storage inventory/readback surface for stored file rows, not
  just a graph-node listing.
- Its filters (`--role`, `--language`, and `--generated`) mirror the raw
  `files` command and depend on file-row metadata.
- Canonical `file:<path>` nodes are useful durable graph identities, but they
  do not fully replace discovery/load inventory semantics.

Canonical replacements:

- use `storage nodes --kind file` for canonical file nodes;
- use `storage canonical-nodes --kind file` for the explicit canonical-node
  command;
- use `storage file-neighborhood --path <repo-relative-path>` for canonical
  file-centered graph context;
- use `storage neighborhood --node file:<path>` when the durable canonical key
  is already known.

Future work:

- Do not schedule a pre-refactor F10 migration for `storage files`.
- If a later phase wants a canonical file inventory projection, it should use a
  new contract that clearly names omitted legacy file-row fields rather than
  reusing `storage files` as if the shape were identical.

### `storage entrypoints`

Decision: keep legacy by default and defer canonical migration.

Rationale:

- The current command is role-based file inventory: it filters stored
  `FileRecord` rows whose role is `entrypoint`.
- Canonicalization has several language-specific entrypoint-like facts, such
  as JavaScript `node.entrypoint`, server/client entrypoint observations, and
  executable/script/file graph evidence, but there is no accepted
  cross-language canonical `entrypoint` node or edge contract.
- A partial canonical migration would either under-report existing legacy
  entrypoint rows or overstate language-specific facts as a unified model.

Canonical replacements:

- use `storage nodes` and `storage edges` with concrete canonical kinds when a
  known language-specific model is being inspected;
- use `storage canonical-nodes` and `storage canonical-edges` for explicit
  canonical graph readback;
- use `storage file-neighborhood` around a known file path to inspect
  canonical context.

Future work:

- Do not schedule a pre-refactor F10/F11 migration for `storage entrypoints`.
- Revisit entrypoint canonicalization through a future model ADR after the
  readability refactor, when the project can decide whether entrypoint means a
  file role, an executable surface, a framework route/startup point, a test
  runner entry, or multiple separately named concepts.

### `storage file-nodes`

Decision: keep legacy by default and treat it as a legacy-normalized graph
inspection command.

Rationale:

- The command explicitly exposes legacy normalized file graph nodes plus
  evidence stable keys.
- Canonical graph storage already has more durable replacements for most
  inspection needs.
- Changing this command to canonical output would make the name misleading and
  would obscure the distinction between legacy node stable keys and canonical
  graph keys.

Canonical replacements:

- use `storage nodes --kind file` or `storage canonical-nodes --kind file` to
  list durable file nodes;
- use `storage file-neighborhood --path <repo-relative-path>` for depth-1
  canonical graph context around `file:<path>`;
- use `storage neighborhood --node <canonical-key>` for arbitrary canonical
  node neighborhoods;
- use `storage explain-canonical-edge` for evidence behind a specific
  canonical edge.

Future work:

- Do not migrate `storage file-nodes` before the refactor.
- A later cleanup phase may deprecate this command or document it as
  permanently legacy, but F9 does not add warnings or change behavior.

## Roadmap Decision

F9 recommended pausing Phase F behavior migrations after this checkpoint.

No F10 or F11 implementation phase was recommended before the major
readability/refactor phaseset. At that checkpoint the remaining commands were:

- `storage files` as the stored file-row inventory command, superseded by
  LOCAL32;
- `storage entrypoints` as the stored role-based entrypoint file command,
  superseded by LOCAL35;
- `storage file-nodes` as the legacy normalized file-node/evidence inspection
  command, superseded by LOCAL38.

If work continues later, it should start with a post-refactor model/design phase
rather than a direct default flip.

## No-Fallback And Legacy Preservation

For any future migration:

- no hidden canonical-to-legacy fallback;
- no mixed canonical and legacy default output;
- explicit `--legacy` for old shapes if a command is migrated;
- clear diagnostics for unsupported canonical filters;
- no silent reinterpretation of legacy stable keys as canonical graph keys;
- no raw private paths, source snippets, graph dumps, or database receipts in
  docs, tests, or reports.

Because F9 does not migrate these commands, it does not add `--legacy` flags,
does not add `--canonical` aliases, and does not change parser behavior.

## Future Test Requirements

If a future phase revisits `storage files`, it should test:

- the chosen default dispatch;
- legacy file-row preservation;
- canonical file identity fields if a canonical projection is added;
- filter behavior for role, language, and generated files;
- no hidden fallback;
- unrelated canonical-default commands remaining unchanged.

LOCAL35 revisits the stored inventory purpose of `storage entrypoints` without
claiming a canonical entrypoint semantic model. A future semantic-model phase
would still need to define included node and edge kinds, language coverage,
and how inventory roles relate to executable or framework evidence. That would
be a distinct product decision rather than compatibility work for the removed
command.

LOCAL38 removes `storage file-nodes` and intentionally does not preserve its
legacy normalized node/evidence output. Its tests require parser rejection,
removal of the obsolete compatibility symbols, bounded canonical graph-file
replacement behavior, and no misleading equivalence between legacy stable
keys and canonical keys.

## Private-Data Boundary

F9 is docs-only. It uses committed source and docs as design evidence. It does
not read operator graph config, refresh live/private graphs, rebuild local
databases, commit graph data, commit database dumps, commit receipts, include
private source snippets, or include secrets.
