# ADR 0007: Canonical Readback and Explain Query Contracts

## Status

Accepted

## Date

2026-06-29

## Context

ADR 0001 defines the distinction between raw observations, evidence records,
canonical nodes, and canonical edges. ADR 0002 defines graph key version 1,
canonical key grammar, and the canonical edge vocabulary. ADR 0003 and ADR
0004 require canonicalization to remain a tested pure layer before storage
changes. ADR 0005 defines canonical storage, raw observation retention, and the
Phase C plan.

Phase C2 is complete. `repomap-kg storage load-files` now dual-writes legacy
observation-derived storage and canonical storage while preserving existing
public output and legacy readback behavior. The Phase C2 exit status is recorded
in `docs/status/2026/06/29/00006-phase-c2-dual-write-exit.md`.

Phase D is the next possible storage phase. It may add public canonical
readback and explain commands, but it must not migrate existing public query
semantics to canonical graph identity.

## Decision

RepoMap will add new public canonical readback commands in Phase D:

- `repomap-kg storage canonical-nodes`
- `repomap-kg storage canonical-edges`
- `repomap-kg storage canonical-neighborhood`
- `repomap-kg storage explain-canonical-edge`

These commands read from canonical storage produced by Phase C2. Existing
legacy readback commands remain unchanged during Phase D.

Phase D commands use canonical node keys and canonical edge identity fields as
public identifiers. They do not require users to know database integer ids.

## Scope and Non-Scope

Phase D may define and implement canonical readback and explain commands.

Phase D must not:

- change existing legacy storage command output;
- remove or rename legacy `stable_key` fields;
- migrate legacy commands to canonical semantics;
- start Phase E public query migration;
- add MCP;
- add embeddings;
- add parser-backed Python, Nix, or Ruby extraction;
- add graph visualization;
- remove or replace `files`, `nodes`, `edges`, or `evidence`;
- change canonical key grammar.

## Existing Legacy Commands Remain Unchanged

The following commands remain legacy-shape readback during Phase D:

- `storage files`
- `storage entrypoints`
- `storage file-nodes`
- `storage nodes`
- `storage neighborhood`
- `storage file-neighborhood`
- `storage edges`
- `storage host-mutators`
- `storage host-mutators-summary`
- `storage summary`

Their default JSON and table output must not change in Phase D. They continue
to read from observation-derived storage and may continue to expose legacy
`stable_key` fields.

An existing legacy command may gain optional canonical fields only if the Phase
D implementation explicitly adds an opt-in flag. Such fields must be JSON-only
unless a later ADR accepts table output changes. No opt-in canonical field may
change the default output shape.

## New Canonical Readback Commands

All new commands use the existing storage connection arguments:

- `--pg-host`
- `--pg-port`
- `--pg-user`
- `--pg-database`
- `--psql-command`

All commands require `--root-path` to select the repository. All commands accept
`--json`. Without `--json`, commands emit stable table-oriented text output.

All commands accept `--graph-key-version`, defaulting to `1`. Phase D supports
only graph key version 1 unless a later ADR accepts another version.
Unsupported versions fail before querying storage.

Invalid canonical keys fail before querying storage. Error messages must name
the offending argument, such as `--canonical-key`, `--source-key`,
`--target-key`, or `--node`.

Storage or query failures follow existing storage command behavior: return a
non-zero exit status and print a concise error to stderr.

## `storage canonical-nodes`

### Arguments

Required:

- `--root-path`

Optional:

- `--kind`
- `--canonical-key`
- `--path-prefix`
- `--graph-key-version`, default `1`
- storage connection args
- `--json`

`--path-prefix` applies only to file nodes. If used with `--kind` set to a
non-file kind, the command fails with an argument validation error. If `--kind`
is omitted, `--path-prefix` implies file-node filtering.

### JSON Output

JSON output is an array sorted by `canonical_key`:

```json
[
  {
    "canonical_key": "file:bin/tool",
    "graph_key_version": 1,
    "kind": "file",
    "display_name": "bin/tool",
    "confidence": "extracted",
    "conflict": false,
    "metadata": {"role": "script"},
    "first_seen_run_id": 10,
    "last_seen_run_id": 12
  }
]
```

Database integer ids are not exposed.

### Table Output

Table output uses these fields:

- `canonical_key`
- `kind`
- `display_name`
- `confidence`
- `conflict`
- `first_seen_run_id`
- `last_seen_run_id`

Metadata is omitted from table output unless a later ADR accepts a table field
for compact metadata rendering.

### Empty Results

JSON output is `[]`. Table output prints the normal header with no records, or
the existing project convention for empty storage tables if one is already
established.

### Error Behavior

The command fails when:

- `--canonical-key` is present and is not a valid canonical key;
- `--graph-key-version` is unsupported;
- `--path-prefix` is combined with a non-file `--kind`;
- storage lookup fails.

### Examples

```sh
repomap-kg storage canonical-nodes --root-path . --kind file --json
repomap-kg storage canonical-nodes --root-path . --canonical-key tool:nix --json
repomap-kg storage canonical-nodes --root-path . --path-prefix scripts/
```

## `storage canonical-edges`

### Arguments

Required:

- `--root-path`

Optional:

- `--kind`
- `--source-key`
- `--target-key`
- `--graph-key-version`, default `1`
- storage connection args
- `--json`

`--kind` must be one of the ADR 0002 edge kinds for graph key version 1:

- `defines`
- `executes`
- `sources`
- `reads_env`
- `writes_env`
- `mutates_host`
- `imports`
- `exposes_script`
- `depends_on`
- `wraps`
- `tests`

### JSON Output

JSON output is an array sorted by:

1. `source_key`
2. `edge_kind`
3. `target_key`
4. `identity_metadata_hash`

Each record has this shape:

```json
[
  {
    "source_key": "file:bin/tool",
    "edge_kind": "executes",
    "target_key": "tool:nix",
    "graph_key_version": 1,
    "identity_metadata": {},
    "identity_metadata_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "metadata": {"commands": ["nix"]},
    "confidence": "extracted",
    "conflict": false,
    "first_seen_run_id": 10,
    "last_seen_run_id": 12
  }
]
```

Database integer ids are not exposed.

Hash fields are lowercase 64-character SHA-256 hex strings without a `sha256:`
prefix, matching Phase C storage constraints.

### Table Output

Table output uses these fields:

- `source_key`
- `edge_kind`
- `target_key`
- `confidence`
- `conflict`
- `first_seen_run_id`
- `last_seen_run_id`

`identity_metadata_hash` may be included in table output when needed to
distinguish multiple edges that have the same source, kind, and target.

### Empty Results

JSON output is `[]`. Table output prints the normal empty table representation.

### Error Behavior

The command fails when:

- `--source-key` or `--target-key` is present and is not a valid canonical key;
- `--kind` is not an ADR 0002 edge kind;
- `--graph-key-version` is unsupported;
- storage lookup fails.

### Examples

```sh
repomap-kg storage canonical-edges --root-path . --kind executes --target-key tool:nix --json
repomap-kg storage canonical-edges --root-path . --source-key file:scripts/build.sh --kind sources
repomap-kg storage canonical-edges --root-path . --kind reads_env --source-key file:scripts/build.sh --json
```

## `storage canonical-neighborhood`

### Arguments

Required:

- `--root-path`
- `--node`

Optional:

- `--direction both|in|out`, default `both`
- `--depth`, default `1`
- `--graph-key-version`, default `1`
- storage connection args
- `--json`

The first implementation supports only `--depth 1`. Any other depth fails with
an argument validation error unless the implementation includes a tested
recursive query plan.

### JSON Output

JSON output is one object:

```json
{
  "center": {
    "canonical_key": "tool:nix",
    "graph_key_version": 1,
    "kind": "tool",
    "display_name": "nix",
    "confidence": "extracted",
    "conflict": false,
    "metadata": {},
    "first_seen_run_id": 10,
    "last_seen_run_id": 12
  },
  "nodes": [
    {
      "canonical_key": "file:bin/tool",
      "graph_key_version": 1,
      "kind": "file",
      "display_name": "bin/tool",
      "confidence": "extracted",
      "conflict": false,
      "metadata": {},
      "first_seen_run_id": 10,
      "last_seen_run_id": 12
    }
  ],
  "edges": [
    {
      "source_key": "file:bin/tool",
      "edge_kind": "executes",
      "target_key": "tool:nix",
      "graph_key_version": 1,
      "identity_metadata": {},
      "identity_metadata_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "metadata": {},
      "confidence": "extracted",
      "conflict": false,
      "first_seen_run_id": 10,
      "last_seen_run_id": 12
    }
  ]
}
```

`nodes` includes neighbors and may include the center only if doing so is needed
to keep a shared rendering helper simple. If it includes the center, the center
must still be present in the `center` field.

Nodes are sorted by `canonical_key`. Edges are sorted by `source_key`,
`edge_kind`, `target_key`, and `identity_metadata_hash`.

### Table Output

Table output has a center line followed by two sections:

- `Nodes`: `canonical_key`, `kind`, `display_name`, `confidence`, `conflict`
- `Edges`: `source_key`, `edge_kind`, `target_key`, `confidence`, `conflict`

### Empty Results

If the center node does not exist, JSON output is:

```json
{"center": null, "nodes": [], "edges": []}
```

The command exits successfully because an empty neighborhood is a valid query
result. Invalid keys and unsupported graph key versions remain errors.

### Error Behavior

The command fails when:

- `--node` is not a valid canonical key;
- `--direction` is not `both`, `in`, or `out`;
- `--depth` is not `1` in the first implementation;
- `--graph-key-version` is unsupported;
- storage lookup fails.

### Examples

```sh
repomap-kg storage canonical-neighborhood --root-path . --node tool:nix --direction in --json
repomap-kg storage canonical-neighborhood --root-path . --node file:scripts/build.sh --direction out
```

## `storage explain-canonical-edge`

### Arguments

Required:

- `--root-path`
- `--source-key`
- `--kind`
- `--target-key`

Optional:

- `--identity-metadata-json`, default `{}`
- `--graph-key-version`, default `1`
- storage connection args
- `--json`

The edge is identified by canonical edge identity:

- repository selected by `--root-path`;
- graph key version;
- source canonical key;
- edge kind;
- target canonical key;
- identity metadata hash computed from `--identity-metadata-json`.

Users do not provide or receive database integer ids as the primary identity.

### JSON Output

When the edge exists, JSON output is one object:

```json
{
  "edge": {
    "source_key": "file:bin/tool",
    "edge_kind": "executes",
    "target_key": "tool:nix",
    "graph_key_version": 1,
    "identity_metadata": {},
    "identity_metadata_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "metadata": {"commands": ["nix"]},
    "confidence": "extracted",
    "conflict": false,
    "first_seen_run_id": 10,
    "last_seen_run_id": 12
  },
  "evidence": [
    {
      "evidence_key": "evidence:...",
      "link_kind": "supports",
      "raw_observation": {
        "run_id": 10,
        "ordinal": 0,
        "payload_hash": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
        "kind": "shell.command",
        "source_id": "bin/tool#call:nix"
      },
      "path": "bin/tool",
      "start_line": 12,
      "end_line": 12,
      "extractor": "repo-shell",
      "extractor_version": "0.1.0",
      "confidence": "extracted",
      "metadata": {"argv": ["nix", "build"]}
    }
  ]
}
```

When no edge matches, JSON output is:

```json
{"edge": null, "evidence": []}
```

The command exits successfully for a missing edge because the query is valid.

### Table Output

Table output has:

- one edge summary section with `source_key`, `edge_kind`, `target_key`,
  `identity_metadata_hash`, `confidence`, and `conflict`;
- one evidence section with `raw_observation.run_id`,
  `raw_observation.ordinal`, `raw_observation.kind`,
  `raw_observation.source_id`, `path`, `start_line`, `end_line`, `extractor`,
  `extractor_version`, and `confidence`.

### Error Behavior

The command fails when:

- `--source-key` or `--target-key` is not a valid canonical key;
- `--kind` is not an ADR 0002 edge kind;
- `--identity-metadata-json` is not a JSON object;
- `--graph-key-version` is unsupported;
- storage lookup fails.

### Examples

```sh
repomap-kg storage explain-canonical-edge \
  --root-path . \
  --source-key file:bin/tool \
  --kind executes \
  --target-key tool:nix \
  --json

repomap-kg storage explain-canonical-edge \
  --root-path . \
  --source-key file:scripts/build.sh \
  --kind sources \
  --target-key file:lib/common.sh
```

## Identity Naming Policy

RepoMap uses distinct identity names for distinct graph layers:

- Legacy `stable_key` belongs to observation-derived `nodes` and `edges`.
- Canonical `canonical_key` belongs to durable canonical nodes.
- Canonical edge identity is the tuple of repository, graph key version, source
  canonical key, edge kind, target canonical key, and identity metadata hash.
- In-memory `edge_key` is a canonicalizer-local convenience for linking
  evidence to edges before storage. It is not durable database identity.
- Database integer ids are storage implementation details.

Canonical node identity must not be called `stable_key` in public canonical
commands.

Phase D may expose an optional computed edge handle such as
`canonical-edge:<sha>` only as a convenience field. If such a handle is added,
source key, edge kind, target key, graph key version, and identity metadata must
remain the authoritative public identity.

## Compatibility Policy

Phase D must not silently change existing JSON or table output for legacy
commands.

Canonical commands are new public commands. They may evolve under normal
compatibility rules after their initial release, but their first implementation
must include JSON and table output stability tests.

If an existing legacy command gains optional canonical fields, the fields must
be opt-in, JSON-only, and documented. Default legacy output must remain byte-
compatible where current tests assert exact output.

## Query Semantics

Phase D answers canonical queries using canonical rows already produced by C2.
It does not require new extractors.

### Files Executing `tool:nix`

Use `storage canonical-edges --kind executes --target-key tool:nix`.

Each result with `source_key` in the `file:` namespace is a file that executes
the `nix` tool. Evidence can be inspected with `explain-canonical-edge`.

### Files Sourcing `file:lib/common.sh`

Use `storage canonical-edges --kind sources --target-key file:lib/common.sh`.

The command returns files whose static shell source path canonicalized to
`file:lib/common.sh`.

### Env Vars Read by a File

Use `storage canonical-edges --kind reads_env --source-key file:<path>`.

Targets in the `env:` namespace are environment variables read by that file.

### Host Mutation Categories by File

Use `storage canonical-edges --kind mutates_host --source-key file:<path>`.

Targets in the `host.category:` namespace are host mutation categories observed
for that file.

### Explain Why an Edge Exists

Use `storage explain-canonical-edge` with source key, edge kind, target key, and
optional identity metadata. The command joins canonical edge evidence to
canonical evidence and retained raw observations when available. It reports
evidence metadata, raw observation ordinal, raw kind, raw source id, path, line
span, extractor, extractor version, and confidence.

## Tests Required for Phase D Implementation

Phase D implementation must add unit and integration coverage for:

- canonical node readback filters;
- canonical edge readback filters;
- depth-1 canonical neighborhood for `in`, `out`, and `both`;
- `explain-canonical-edge` with multiple evidence records;
- empty results;
- invalid canonical key handling;
- unsupported graph key version handling;
- legacy readback unchanged;
- table and JSON output stability.

Integration tests must load canonical rows through existing Phase C paths,
especially `storage load-files`, rather than inserting isolated rows that skip
the C2 contract.

## Implementation Phases After ADR 0007

Phase D should be implemented in small slices:

- D1: storage query records/helpers for canonical nodes and edges.
- D2: `storage canonical-nodes`.
- D3: `storage canonical-edges`.
- D4: `storage explain-canonical-edge`.
- D5: `storage canonical-neighborhood` depth 1.
- D6: Phase D exit audit and docs update.

No slice may begin Phase E, MCP, embeddings, parser-backed Python/Nix/Ruby
extraction, graph visualization, or public query migration without a later
instruction or ADR.

## Rejected Alternatives

### Change Legacy `storage nodes` to Canonical Semantics Now

Rejected. Phase D adds canonical readback beside existing readback. Migrating
legacy command semantics is Phase E work and would break users depending on
legacy `stable_key` output.

### Expose Database Integer Ids as Public Identity

Rejected. Database ids are implementation details and are not stable across
reloads, exports, or replay. Public canonical identity must use canonical keys
and canonical edge identity fields.

### Add Recursive Graph Traversal Before Depth-1 Readback Is Stable

Rejected for the first implementation. Recursive traversal needs separate
tests for cycle handling, ordering, directionality, and performance. Depth 1 is
enough to validate canonical readback contracts.

### Add Replay Before Explain/Readback

Deferred. Raw observation retention makes replay possible, but users need a
way to inspect current canonical rows and evidence before replay commands are
worth exposing.

### Add MCP Before Canonical CLI Readback Is Stable

Rejected. MCP should consume stable CLI/query semantics rather than becoming
the first public canonical query surface.

### Migrate Public Query Semantics to Canonical Graph Identity in Phase D

Rejected. Phase D introduces canonical commands. Migration of public query
semantics to canonical graph identity belongs to Phase E after compatibility
and output-shape decisions are explicit.
