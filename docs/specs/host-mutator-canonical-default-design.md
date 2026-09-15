# Host-Mutator Canonical Default Design

Date: 2026-07-04

## Status

Accepted for Phase F6. Updated after F8 to record that both
`storage host-mutators` and `storage host-mutators-summary` have migrated to
canonical defaults.

## Current State

After F8, these storage readback commands are canonical by default:

- `storage summary`;
- `storage nodes`;
- `storage edges`;
- `storage neighborhood`;
- `storage file-neighborhood`;
- `storage host-mutators`;
- `storage host-mutators-summary`.

The remaining legacy-default commands are:

- `storage files`;
- `storage entrypoints`;
- `storage file-nodes`.

`storage host-mutators --canonical` remains accepted as a compatibility alias
for the default canonical behavior. `storage host-mutators --legacy` preserves
the old observation-derived row shape.
`storage host-mutators-summary --canonical` remains accepted as a compatibility
alias for the default canonical summary behavior.
`storage host-mutators-summary --legacy` preserves the old observation-derived
summary shape.

## Why Host-Mutators Are Different

Legacy host-mutator readback is observation-level. It reconstructs rows from
stored `shell.host_mutation` nodes and their legacy edges, then presents fields
such as path, line, name, target, category, tool, privileged, reason, argv, and
effective_argv.

Canonical host mutation readback is graph-fact-level. Multiple raw observations
can collapse into one durable canonical edge:

```text
file:<path> --mutates_host--> host.category:<category>
```

Zsh startup/config extraction also produces non-executed source-intent host
mutation evidence:

```text
zsh.script:<path> --host_mutation_intent--> host.category:<category>
```

Those two edge kinds are related but not identical. `mutates_host` means the
static source contains host-mutation evidence. `host_mutation_intent` means the
static source contains startup/config/test-source intent metadata that must not
be presented as proof that a shell ran or the host was mutated.

Because canonical edges collapse evidence, legacy row counts, canonical edge
counts, supporting evidence counts, raw observation counts, and file/category
pair counts are all different possible answers. The public default must name
which answer it gives.

## Phase Split

F6 chooses a split migration:

- F7 migrates `storage host-mutators` to canonical by default.
- F8 migrates `storage host-mutators-summary` to canonical by default.

This keeps the row-level output transition separate from the summary
aggregation contract. F7 can establish canonical row identity first, while F8
can separately name counts that would otherwise look deceptively similar to the
legacy observation-level summary.

## F7 Host-Mutators Contract

Default `storage host-mutators` reads canonical host mutation graph facts. The
default edge-kind set is:

- `mutates_host`;
- `host_mutation_intent`.

`network_intent` and `package_intent` remain out of the default host-mutators
view in F7. They are adjacent source-intent facts, but they are not canonical
host-category mutation edges and should not be silently mixed into
host-mutator output.

`--legacy` preserves the old observation-derived row shape and filters.
`--canonical` is retained as a default-compatible alias.

Canonical output should be a host-mutator-specific projection over canonical
edges, not a legacy command-row projection. The JSON/table contract should
include durable graph identity fields:

- source_key;
- edge_kind;
- target_key;
- category derived from `host.category:<category>` when available;
- graph_key_version;
- identity_metadata_hash;
- confidence;
- conflict;
- first_seen_run_id;
- last_seen_run_id.

The projection may include bounded metadata when already present in canonical
edge metadata:

- tool_names or command_names;
- privileged_observed;
- destructive_observed;
- runtime_intent;
- host_mutation_proven;
- static_only;
- shell_executed, zsh_executed, powershell_executed, or related execution
  markers;
- target_redacted_observed.

The default output must not include raw command lines, raw source snippets, raw
private paths, or unbounded argument arrays. If existing canonical edge
metadata stores fields such as `argv_examples`, `effective_argv_examples`, or
raw classifier reasons, F7 should either omit them from the host-mutators
default projection or include only bounded redacted summaries with explicit
tests. Detailed supporting evidence remains available through
`storage explain-canonical-edge`.

### F7 Filters

F7 should preserve filter names where they can be mapped honestly:

- `--category` maps to `host.category:<category>` and applies to both
  `mutates_host` and `host_mutation_intent`.
- `--source-key` remains a canonical source-key filter.
- `--target-key` remains a canonical target-key filter and must be consistent
  with `--category` when both are supplied.
- `--tool` may filter only bounded canonical metadata fields such as `tool`,
  `tools`, `commands`, or `managers`. It must not parse or search raw command
  strings, argv arrays, source snippets, or evidence payloads.

If a requested filter cannot be supported honestly in canonical mode, the CLI
should return a clear diagnostic instead of silently approximating or falling back to
legacy. Valid filters that simply match no canonical rows should return normal
empty output without warnings.

F7 uses a small helper to query both host-mutator canonical edge kinds, because
the generic canonical edge query accepts one edge kind at a time.

### F7 No-Fallback Rule

F7 does not try canonical readback and then silently fall back to legacy
host-mutator rows. It does not mix canonical and legacy rows in default output.
Users who need legacy row identity must pass `--legacy`.

## F8 Host-Mutators-Summary Contract

F8 migrates `storage host-mutators-summary` separately.

The canonical summary groups by:

- category;
- edge_kind.

Canonical summary rows use explicitly named counts:

- source_count: unique canonical source keys;
- canonical_edge_count: unique canonical host mutation edges;
- privileged_edge_count: canonical edges where bounded metadata shows
  privileged evidence;
- intent_edge_count: edges whose `edge_kind` is `host_mutation_intent`;
- proven_edge_count: edges whose `edge_kind` is `mutates_host`.

F8 does not join raw observations into the default canonical summary. If a later
phase adds raw observation counts, the field must be named
`raw_observation_count` and documented as a compatibility bridge, not as the
canonical count. F8 does not reuse the legacy `count` field for canonical edge
counts because that would hide the identity change.

Tool-level canonical summary is intentionally narrowed. It filters only when
bounded canonical metadata represents tool or command names durably enough
without parsing raw commands or evidence payloads. F8 supports `--tool` through
the same bounded metadata fields used by the row-level canonical view, including
tool, tools, command, commands, manager, managers, command_name, and
command_names.

`storage host-mutators-summary --legacy` preserves the old category/tool
aggregation with `count` and `privileged_count`.

## Unsupported And Dynamic Behavior

For both F7 and F8:

- no hidden canonical-to-legacy fallback;
- no mixed canonical and legacy default output;
- no raw command/source text in default summaries;
- no deep shell parsing of command metadata;
- no inference that source-intent edges prove runtime execution;
- no host filesystem checks;
- no live/private graph refreshes.

Unsupported filters should fail clearly. Empty canonical matches should remain
quiet, bounded, and non-fatal.

## Required Tests For F7

F7 should add focused unit and integration coverage for:

- default `storage host-mutators` dispatching to canonical readback;
- `--canonical` remaining accepted if retained;
- `--legacy` preserving old observation-derived output;
- `mutates_host` and `host_mutation_intent` both appearing in canonical default
  when fixture data contains both;
- `network_intent` and `package_intent` not appearing in default
  host-mutators output;
- category, source-key, target-key, and supported tool filters;
- category/target-key mismatch diagnostics;
- no canonical-to-legacy fallback;
- default output excluding raw source snippets and unbounded raw command text;
- `storage host-mutators-summary`, `storage files`, `storage entrypoints`, and
  `storage file-nodes` remaining legacy by default.

## Required Tests For F8

F8 adds focused unit and integration coverage for:

- default `storage host-mutators-summary` dispatching to canonical summary;
- summary rows grouped by category and edge_kind;
- clearly named count fields without the legacy `count` field;
- `--legacy` preserving old `count` and `privileged_count` aggregation;
- tool filter behavior through bounded canonical metadata;
- no hidden fallback or mixed output;
- `storage files`, `storage entrypoints`, and `storage file-nodes` remaining
  legacy by default.

## Remaining Work After F8

Later phases may decide whether to migrate:

- `storage files`;
- `storage entrypoints`;
- `storage file-nodes`.

Those commands are still legacy by default after F8.

## Private-Data Boundary

This design uses committed source, tests, and public docs only. It does not
read operator graph config, refresh live/private graphs, rebuild local
databases, commit graph dumps, commit receipts, or include private source
snippets or secrets.
