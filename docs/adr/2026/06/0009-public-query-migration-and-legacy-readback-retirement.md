# ADR 0009: Public Query Migration and Legacy Readback Retirement

## Status

Accepted

## Date

2026-06-30

## Context

ADR 0001 defines RepoMap's durable graph model: raw observations are extractor
facts, evidence records are provenance, canonical nodes are durable domain
entities, and canonical edges are durable domain relationships. ADR 0002 defines
graph key version 1 and the canonical edge vocabulary. ADR 0003 defines the
Phase E and Phase F transition from observation-derived public queries to
canonical graph identity. ADR 0007 defines the canonical readback and explain
contracts. ADR 0008 adds structural Markdown documentation facts to the same
canonical graph pipeline.

RepoMap now has:

- raw observation retention;
- canonical graph storage;
- public canonical readback commands from Phase D;
- canonical facts for shell-family, Python, Nix, and Markdown documentation;
- read-only MCP tools over canonical readback; and
- Phase E1 opt-in `--canonical` modes for selected legacy public readback
  commands.

Observation-derived `stable_key`, `node_stable_key`, and `edge_stable_key`
fields remain compatibility artifacts for the legacy storage shape. They are not
long-term graph identity.

This ADR is a transition and compatibility contract for completing ADR 0003
Phase E and Phase F. It does not change canonical key grammar, add graph key
namespaces, add edge kinds, add extractors, change MCP behavior, or implement
code.

## Decision

Canonical graph identity becomes RepoMap's preferred public query model.

Target public identity fields are:

- nodes: `canonical_key`;
- edges: `source_key`, `edge_kind`, `target_key`, `graph_key_version`, and
  `identity_metadata_hash`; and
- evidence records: line spans, extractor details, raw source ids, raw
  observation references, confidence, and metadata that explain why a canonical
  fact exists.

Legacy `stable_key`, `node_stable_key`, and `edge_stable_key` fields may remain
available during a compatibility window. They must not be presented as durable
public graph identity, and commands must not silently reinterpret legacy stable
keys as canonical keys.

## Phase E Policy

### E1: Opt-In Canonical Modes

E1 adds opt-in `--canonical` modes for selected existing public readback
commands. It does not change default behavior.

E1 is complete for:

- `storage summary`;
- `storage nodes`;
- `storage edges`;
- `storage neighborhood`; and
- `storage file-neighborhood`.

When `--canonical` is absent, these commands keep legacy query semantics and
legacy output shape.

### E2: Remaining Public Readback With Clear Canonical Equivalents

E2 should evaluate and migrate remaining public readback or query commands that
have clear canonical equivalents. Host-mutator-oriented readback is the leading
candidate because canonical `mutates_host` edges already model host mutation
categories by file.

E2 should keep canonical behavior opt-in unless a later ADR or phase plan
explicitly accepts a default behavior change. E2 does not require changing every
command at once.

### E3: Canonical Defaults for Selected Commands

E3 may make canonical identity the default for selected commands only after
tests and docs prove compatibility. If a command's default output changes, an
explicit legacy mode such as `--legacy` or an equivalent compatibility flag must
preserve the old behavior during the compatibility window.

E3 should be piloted on one or two commands with simple, well-tested canonical
contracts before broader default migration.

## Phase F Policy

Phase F retires observation-derived public output when safe. Retirement means
moving users away from legacy public identity fields, not deleting provenance or
replay data.

Acceptable Phase F retirement actions include:

- hiding legacy-only fields from default JSON after a canonical replacement is
  documented and tested;
- moving legacy fields behind `--legacy` or `--include-legacy`;
- deprecating legacy filter names in favor of canonical filters; and
- retaining internal compatibility views or tables for replay, debugging, and
  old-run analysis.

Rejected Phase F retirement actions include:

- deleting raw observations;
- deleting evidence;
- deleting canonical explainability;
- removing legacy compatibility before replacement tests and docs exist; and
- breaking read-only MCP canonical behavior.

## Command Policy

### A. Canonical-First Commands

These commands are already canonical public readback surfaces:

- `storage canonical-nodes`;
- `storage canonical-edges`;
- `storage canonical-neighborhood`; and
- `storage explain-canonical-edge`.

They use canonical node keys, canonical edge identity fields, and evidence
records. They must not expose database integer ids as public identity.

### B. Legacy Commands With E1 Canonical Opt-In

These commands remain legacy by default and support canonical mode from E1:

- `storage summary`;
- `storage nodes`;
- `storage edges`;
- `storage neighborhood`; and
- `storage file-neighborhood`.

Default JSON and table output remain legacy-shaped until a later phase changes
that command intentionally.

### C. Commands To Evaluate In E2

E2 should evaluate:

- host-mutator readback commands; and
- any remaining public readback command that exposes observation-derived
  identity and has a clear canonical equivalent.

Commands with unclear canonical semantics should remain unchanged until a later
decision defines their replacement behavior.

### D. Internal Or Compatibility Commands

Commands used only for debugging, replay, old-run analysis, or compatibility may
remain legacy-named if documentation clearly marks their purpose. They should
not be promoted as the preferred public graph query surface.

## Filter Policy

Canonical mode accepts canonical keys and canonical edge identity fields.
Legacy mode accepts legacy stable-key filters.

Incompatible filter combinations fail loudly before querying storage:

- canonical-only filters in legacy mode must fail;
- legacy-only filters in canonical mode must fail;
- a command must not reinterpret a legacy stable key as a canonical key;
- a command must not reinterpret a canonical key as a legacy stable key; and
- conflicting identity filters must fail instead of being silently ignored.

Canonical filters include fields such as `--canonical-key`, `--source-key`,
`--target-key`, `--node`, `--graph-key-version`, and edge kind filters over the
registered canonical vocabulary. Legacy filters include fields such as
`--stable-key`, `--source-node`, `--target-node`, `node_stable_key`, and
`edge_stable_key`.

## Output Policy

Default legacy output remains unchanged until a specific phase changes it.

Canonical output must:

- expose canonical node identity as `canonical_key`;
- expose canonical edge identity through `source_key`, `edge_kind`,
  `target_key`, `graph_key_version`, and `identity_metadata_hash`;
- avoid database integer ids as public identity;
- use field names that clearly distinguish legacy and canonical identity when
  both are present; and
- keep evidence output separate unless an explain command or explicit evidence
  mode requests it.

Table output may be conservative. JSON output in canonical mode must expose the
canonical identity fields needed for stable machine use.

## MCP Policy

MCP remains read-only. It should continue to prefer canonical graph readback and
should not use legacy stable keys as canonical identity.

Phase E and Phase F do not introduce write, discovery, or load tools through
MCP. The multi-project MCP registry remains a readback selection layer for
choosing a configured project graph; it is not a mutation surface.

## Storage Policy

Raw observations are retained. Evidence is retained. Canonical tables remain the
public graph source of truth.

Observation-derived tables may remain as compatibility storage until explicitly
retired. Phase F does not mean deleting data needed for replay, explainability,
debugging, or old-run analysis.

## Compatibility Gates

Before any default command changes from legacy to canonical behavior, RepoMap
must have:

- tests proving the old default behavior still exists behind `--legacy` or an
  equivalent compatibility flag;
- tests proving canonical default output has the expected shape;
- a docs/status exit note for the migration phase;
- user-facing examples for the changed command;
- no loss of evidence or explainability; and
- no database integer ids exposed as public identity.

If a command cannot satisfy these gates, it should keep legacy defaults and
offer canonical behavior only behind `--canonical`.

## Rejected Alternatives

### Immediate Hard Switch To Canonical Defaults For All Commands

Rejected. A hard switch would break users and tests that depend on legacy output
shape before replacement examples and compatibility flags exist.

### Delete Legacy Storage Immediately

Rejected. Observation-derived tables still support compatibility, debugging,
and old-run analysis. Raw observations and evidence are also required for replay
and explainability.

### Treat Legacy Stable Keys As Aliases For Canonical Keys

Rejected. Stable keys and canonical keys identify different layers. Aliasing
them would blur the model ADR 0001 deliberately separated.

### Add New Graph Vocabulary In Phase E Or Phase F

Rejected. Phase E and Phase F migrate public query semantics and retire legacy
output. They do not add graph key namespaces, edge kinds, or extractor models.

### Change MCP Into A Write Or Load Surface

Rejected. MCP remains read-only. Discovery, loading, mutation, and repair flows
stay outside the MCP surface unless a later ADR explicitly changes that
boundary.

### Remove Raw Observation Retention

Rejected. Raw observations are needed for replay, canonicalizer bug repair,
auditability, and evidence-rich explanation.

## Exit Plan

Expected next phases:

- E2: migrate remaining public readback and query commands with clear canonical
  equivalents, especially host-mutator-oriented readback if the command
  contracts are straightforward.
- E3: pilot canonical-default behavior for one or two selected commands if
  tests, docs, examples, and compatibility flags make the change safe.
- F1: perform a legacy-output retirement audit and document which public fields
  or filters are ready to gate or deprecate.
- F2: hide or gate legacy fields behind explicit legacy or include flags where
  safe.

Each phase should remain small, preserve evidence and replay data, and stop if
it needs new canonical vocabulary or new extractor behavior.
