# ADR 0004: Canonicalizer Implementation Contract and Golden Fixture Strategy

## Status

Accepted

## Date

2026-06-29

## Context

ADR 0001 accepts RepoMap's graph identity model: raw observations are extractor
interchange and audit records, evidence records are provenance, canonical nodes
are durable entities, and canonical edges are durable relationships.

ADR 0002 accepts graph key version 1, canonical key grammar, normalization
rules, and the initial canonical relationship vocabulary.

ADR 0003 accepts the canonicalization pipeline, storage transition, replay
strategy, and the rule that canonicalization must be implemented as a tested
pure layer before canonical storage changes.

This ADR defines the exact near-term implementation contract for that in-memory
canonicalizer and the golden fixture tests that should pin its behavior.

## Decision

RepoMap will implement an in-memory canonicalizer with explicit Python module
boundaries, immutable-ish records, structured diagnostics, deterministic
serialization, evidence links, confidence aggregation, and golden fixtures.

The canonicalizer returns a result object:

```python
CanonicalizationResult(graph=CanonicalGraph(...), diagnostics=(...))
```

Diagnostics are not encoded as fake graph facts. Recoverable ambiguity can
produce warnings, explicit placeholder nodes, and a usable graph. Fatal
diagnostics make the result unsuccessful without requiring callers to infer
failure from partial graph rows.

This ADR does not authorize code changes by itself. It is the contract for the
next implementation slice.

## Scope and Non-Scope

This ADR covers:

- canonical key builder module boundaries;
- canonicalizer input and output data structures;
- diagnostics;
- deterministic ordering;
- evidence-link model in memory;
- confidence aggregation;
- metadata merge behavior;
- golden fixture layout; and
- compatibility expectations for current CLI behavior.

This ADR does not cover:

- Postgres DDL;
- storage migrations;
- MCP;
- parser-library selection;
- Nix evaluation;
- query UI;
- graph visualization; or
- embeddings.

## Proposed Python Modules

### `repomap_kg.graph_keys`

Responsibility:

- build graph key version 1 canonical keys;
- parse graph key version 1 canonical keys;
- validate graph key version 1 canonical keys;
- percent-encode and decode key segments;
- normalize repository-relative file paths; and
- expose key-specific exceptions or validation result records.

Allowed imports:

- Python standard library only, such as `dataclasses`, `os`, `pathlib`, and
  `typing`.

Must not import:

- `repomap_kg.observations`;
- `repomap_kg.canonical`;
- `repomap_kg.canonicalization`;
- `repomap_kg.storage`;
- CLI modules;
- database helpers; or
- third-party packages.

Extractors must not hand-format canonical keys except through this module.

### `repomap_kg.canonical_diagnostics`

Responsibility:

- define `CanonicalizationDiagnostic`;
- define diagnostic severity and category constants or enums;
- define the result status helper used to decide whether a result has fatal
  diagnostics; and
- keep diagnostic serialization deterministic.

Allowed imports:

- Python standard library only.

Must not import:

- `repomap_kg.storage`;
- `repomap_kg.cli`;
- parser or extractor modules; or
- third-party packages.

### `repomap_kg.canonical`

Responsibility:

- define the in-memory canonical graph dataclasses;
- define canonical graph serialization;
- define deterministic sort helpers for graph records; and
- define metadata normalization helpers that are independent of raw observation
  mapping.

Allowed imports:

- Python standard library;
- `repomap_kg.graph_keys`; and
- `repomap_kg.canonical_diagnostics`.

Must not import:

- `repomap_kg.storage`;
- `repomap_kg.cli`;
- Postgres or psql helpers;
- concrete extractor modules such as shell, Python, Nix, or Ruby extractors; or
- third-party packages.

### `repomap_kg.canonicalization`

Responsibility:

- map `RawObservation` records into canonical graph records;
- assign raw observation ordinals;
- build canonical keys through `repomap_kg.graph_keys`;
- create evidence records;
- create node and edge evidence links;
- aggregate confidence;
- merge metadata;
- emit diagnostics; and
- return `CanonicalizationResult`.

Allowed imports:

- Python standard library;
- `repomap_kg.observations`;
- `repomap_kg.graph_keys`;
- `repomap_kg.canonical`; and
- `repomap_kg.canonical_diagnostics`.

Must not import:

- `repomap_kg.storage`;
- Postgres or psql helpers;
- CLI modules;
- MCP code;
- third-party packages; or
- parser libraries not already part of the raw observation boundary.

### Unit Test Modules

Near-term unit tests should live under `src/test/unit/python/repomap_kg/`:

- `test_graph_keys.unit.test.py`
- `test_canonical.unit.test.py`
- `test_canonicalization.unit.test.py`
- `test_canonicalization_fixtures.unit.test.py`

The fixture test module should load JSONL and expected JSON from
`src/test/fixtures/canonicalization/` and compare exact canonical
serialization.

## Canonical Key API Contract

The graph key module owns every graph key builder, parser, and validator.
Builders return canonical key strings. Builders raise a graph key error on
invalid input. Parsers raise a graph key parse error on invalid input.
Validators return a validation result instead of raising.

### Common Rules

Graph key version 1 is not embedded as a prefix in key strings. Version 1 is
the parser and builder contract, and parsed keys include `graph_key_version =
1`. Storage and serialized graph records carry `graph_key_version` separately.

All canonical keys are case-sensitive. Builders do not lowercase or uppercase
source content except percent-escape hex digits, which must be uppercase.

All key segment inputs except `file_key(path)` accept non-empty `str` values.
`file_key(path)` accepts `str`, `pathlib.PurePath`, and `os.PathLike[str]`
values. Invalid input types raise a graph key error.

Builders percent-encode each key segment using UTF-8 bytes and uppercase RFC
3986 percent escapes. The unescaped safe set is:

```text
A-Z a-z 0-9 - . _ ~
```

For file keys, `/` is the path component separator. Each path component is
encoded independently. For non-file keys, `:` is the segment separator. Literal
`/`, `:`, `%`, `#`, spaces, quotes, and other reserved characters inside a
segment are encoded.

Malformed percent escapes fail parsing. Decoders reject:

- incomplete percent escapes;
- non-hex percent escapes;
- lowercase percent escape hex digits;
- percent-encoded bytes that are not valid UTF-8; and
- unescaped reserved characters.

Parsed key components preserve source order. `parse_key(key).segments` is a
tuple in canonical grammar order. File key parsed path components are ordered
from repository root to leaf.

### Required Functions

| Function | Accepted inputs | Return type | Invalid input behavior |
| --- | --- | --- | --- |
| `file_key(path)` | `str`, `PurePath`, or `os.PathLike[str]` | `str` like `file:bin/tool` | Raises on empty, absolute, repo-escaping, or non-path-like input. |
| `tool_key(name)` | non-empty `str` | `str` like `tool:nix` | Raises on empty or non-string input. |
| `env_key(name)` | non-empty `str` | `str` like `env:PATH` | Raises on empty or non-string input. |
| `host_category_key(category)` | non-empty `str` | `str` like `host.category:package-management` | Raises on empty or non-string input. |
| `python_module_key(name)` | non-empty `str` | `str` like `python.module:repomap_kg.cli` | Raises on empty or non-string input. |
| `python_class_key(module, class_name)` | two non-empty `str` values | `str` like `python.class:repomap_kg.cli:CliError` | Raises on empty or non-string input. |
| `python_function_key(module, function_name)` | two non-empty `str` values | `str` like `python.function:repomap_kg.cli:main` | Raises on empty or non-string input. |
| `python_method_key(module, class_name, method_name)` | three non-empty `str` values | `str` like `python.method:repomap_kg.storage:Record:to_dict` | Raises on empty or non-string input. |
| `nix_app_key(flake_ref, system, name)` | three non-empty `str` values | `str` like `nix.app:repo-map:aarch64-darwin:tool` | Raises on empty or non-string input. |
| `nix_package_key(flake_ref, system, name)` | three non-empty `str` values | `str` like `nix.package:repo-map:aarch64-darwin:default` | Raises on empty or non-string input. |
| `nix_dev_shell_key(flake_ref, system, name)` | three non-empty `str` values | `str` like `nix.devShell:repo-map:aarch64-darwin:default` | Raises on empty or non-string input. |
| `nix_check_key(flake_ref, system, name)` | three non-empty `str` values | `str` like `nix.check:repo-map:aarch64-darwin:unit` | Raises on empty or non-string input. |
| `nix_output_key(flake_ref, output_path)` | two non-empty `str` values | `str` like `nix.output:repo-map:packages%2Faarch64-darwin%2Fdefault` | Raises on empty or non-string input. |
| `ruby_module_key(name)` | non-empty `str` | `str` like `ruby.module:RepoMap` | Raises on empty or non-string input. |
| `ruby_class_key(class_name)` | non-empty `str` | `str` like `ruby.class:RepoMap%3A%3ARunner` | Raises on empty or non-string input. |
| `ruby_method_key(owner, method_name)` | two non-empty `str` values | `str` like `ruby.method:RepoMap%3A%3ARunner:call` | Raises on empty or non-string input. |
| `dynamic_key(domain, reason)` | two non-empty `str` values | `str` like `dynamic:file:shell-source-expanded-from-variable` | Raises on empty or non-string input. |
| `external_key(domain, stable_name)` | two non-empty `str` values | `str` like `external:python.module:requests` | Raises on empty or non-string input. |
| `unknown_key(domain, reason)` | two non-empty `str` values | `str` like `unknown:file:missing-file` | Raises on empty or non-string input. |
| `parse_key(key)` | non-empty `str` | `ParsedGraphKey` | Raises on invalid grammar, namespace, segment count, path normalization, or percent escaping. |
| `validate_key(key)` | any value | `GraphKeyValidation` | Never raises for ordinary invalid input; returns `valid=False` with an error string. |

### Path Normalization

`file_key(path)` normalizes paths by:

- converting platform separators to POSIX `/`;
- rejecting absolute paths;
- removing empty and `.` components;
- resolving `..` only when it stays inside the repository-relative path;
- rejecting paths that escape the repository;
- preserving spelling and case of remaining components;
- representing the repository root as `file:.`; and
- encoding each path component independently.

`parse_key("file:...")` rejects file keys with empty components, `.` components
other than the complete root key, `..` components, absolute-looking paths, or
malformed escapes.

## Canonical Graph In-Memory Model

The first implementation should use frozen dataclasses or equivalently
immutable records. The graph should be easy to serialize deterministically and
should not require database identity.

### `CanonicalNode`

Required fields:

- `canonical_key: str`
- `graph_key_version: int`
- `kind: str`
- `display_name: str`
- `metadata: Mapping[str, Any]`
- `confidence: str`
- `conflict: bool`

`kind` is the parsed namespace, such as `file`, `tool`, `env`, or
`host.category`. `display_name` is presentation metadata and never identity.

### `CanonicalEdge`

Required fields:

- `edge_key: str`
- `graph_key_version: int`
- `source_key: str`
- `kind: str`
- `target_key: str`
- `identity_metadata: Mapping[str, Any]`
- `metadata: Mapping[str, Any]`
- `confidence: str`
- `conflict: bool`

`edge_key` is a deterministic computed key for serialization and joins inside
the in-memory result. It is derived from graph key version, source key, edge
kind, target key, and canonicalized identity metadata. It is not the old
observation-derived `stable_key` concept. The source, kind, target, version,
and identity metadata remain the authoritative edge identity.

### `CanonicalEvidence`

Required fields:

- `evidence_key: str`
- `raw_observation_ordinal: int`
- `raw_schema_version: int`
- `raw_kind: str`
- `raw_source_id: str`
- `path: str`
- `start_line: int | None`
- `end_line: int | None`
- `extractor: str`
- `extractor_version: str`
- `confidence: str`
- `metadata: Mapping[str, Any]`

The evidence key is deterministic from ordinal, path, line range, extractor,
and raw source id. It is evidence identity, not canonical graph identity.

### `CanonicalNodeEvidenceLink`

Required fields:

- `canonical_key: str`
- `evidence_key: str`
- `link_kind: str`

Initial `link_kind` values:

- `observed`
- `defined_by`
- `inferred_from_edge`

### `CanonicalEdgeEvidenceLink`

Required fields:

- `edge_key: str`
- `evidence_key: str`
- `link_kind: str`

Initial `link_kind` values:

- `supports`
- `conflicts`

### `CanonicalGraph`

Required fields:

- `graph_key_version: int`
- `nodes: tuple[CanonicalNode, ...]`
- `edges: tuple[CanonicalEdge, ...]`
- `evidence: tuple[CanonicalEvidence, ...]`
- `node_evidence_links: tuple[CanonicalNodeEvidenceLink, ...]`
- `edge_evidence_links: tuple[CanonicalEdgeEvidenceLink, ...]`
- `raw_observation_count: int`

`CanonicalGraph` contains graph facts and evidence records. It does not own
success/failure state; that belongs to `CanonicalizationResult`.

### `CanonicalizationDiagnostic`

Required fields:

- `severity: str`
- `category: str`
- `message: str`
- `raw_observation_ordinal: int | None`
- `raw_source_id: str | None`
- `path: str | None`
- `field: str | None`
- `value: Any | None`
- `placeholder_key: str | None`

### `CanonicalizationResult`

Required fields:

- `graph: CanonicalGraph`
- `diagnostics: tuple[CanonicalizationDiagnostic, ...]`
- `ok: bool`

`ok` is false when any diagnostic has severity `error`. Warnings and info
diagnostics do not make `ok` false.

## Return Shape

The canonicalizer should return `CanonicalizationResult`, not bare
`CanonicalGraph`.

Recommendation:

```python
def canonicalize_observations(
    observations: Sequence[RawObservation],
) -> CanonicalizationResult:
    ...
```

This shape keeps warnings and recoverable ambiguity out of graph facts. It also
lets CLI and tests display diagnostics without fabricating nodes or edges that
do not represent repository knowledge.

Convenience wrappers may return `result.graph` only in tests or internal helper
paths, but the public pure-layer API should expose the result object.

## Diagnostic Taxonomy

### Severities

- `error`: the canonicalizer cannot safely include the observation or the
  result violates an invariant. The result has `ok = false`.
- `warning`: the canonicalizer can continue, possibly with a placeholder node
  or skipped observation.
- `info`: the canonicalizer records expected ambiguity, such as a dynamic
  target that is represented honestly.

### Categories

Initial diagnostic categories:

- `malformed_raw_observation`
- `unsupported_raw_observation_kind`
- `invalid_canonical_key`
- `malformed_percent_escape`
- `repo_escaping_path`
- `dynamic_target`
- `unknown_target`
- `missing_required_metadata`
- `conflicting_evidence`
- `graph_key_version_mismatch`
- `canonicalization_bug`

Accepted category refinements for the first implementation:

- `unsupported_operation`: a supported raw observation kind has an operation
  value outside the implemented vocabulary, such as a `shell.env` operation
  other than `read` or `write`;
- `unregistered_category`: a supported raw observation kind has a category
  value outside the current registry, such as an unknown
  `shell.host_mutation` category; and
- `secret_prone_value`: an environment variable value was intentionally
  redacted from summary/evidence metadata because the variable name is
  secret-prone.

These refinements are deliberately narrower than
`missing_required_metadata` or `unknown_target`. They let diagnostics explain
why the canonicalizer skipped, placeholdered, or redacted an otherwise
well-formed observation without overloading broader categories.

### Behavior Rules

Fail the entire result when:

- a raw observation is malformed and cannot be converted into `RawObservation`;
- a source file path for an observation escapes the repository;
- graph key version is incompatible with the parser;
- canonical graph invariants fail after construction; or
- an implementation bug is detected, such as an edge referencing a missing
  node.

Emit a warning and continue when:

- a raw observation kind is unsupported;
- optional metadata is missing and the observation can still be represented;
- a raw `target` is malformed but trusted metadata can rebuild the target;
- a target is unknown and an explicit placeholder can represent it;
- evidence conflicts with other evidence; or
- a dynamic target prevents static precision but can be represented honestly.

Create placeholder nodes when:

- dynamic source code constructs the target and a `dynamic:*` domain is known;
- a target concept exists but cannot be resolved and an `unknown:*` domain is
  known; or
- a target is external and has a stable external name.

Skip an observation when:

- the observation kind is unsupported in the current implementation subset;
- required metadata is missing and no honest placeholder can be built;
- the source canonical node cannot be built; or
- including the observation would fabricate precision.

RepoMap must prefer explicit `unknown:*`, `dynamic:*`, or `external:*`
placeholder nodes over fabricated precision.

## Deterministic Ordering

The same input observations in the same order must produce byte-stable JSON
fixture output.

Raw observation ordinals are zero-based indexes into the input sequence. For a
JSONL file, line number is `raw_observation_ordinal + 1`.

Sort order:

- canonical nodes: `graph_key_version`, `canonical_key`;
- canonical edges: `graph_key_version`, `source_key`, `kind`, `target_key`,
  canonicalized `identity_metadata`, `edge_key`;
- evidence records: `raw_observation_ordinal`, `evidence_key`;
- node evidence links: `canonical_key`, `evidence_key`, `link_kind`;
- edge evidence links: `edge_key`, `evidence_key`, `link_kind`;
- diagnostics: `raw_observation_ordinal` with `None` last, severity rank
  `error`, `warning`, `info`, then category, path, field, message;
- metadata maps: lexicographic key order when serialized; and
- metadata arrays: first-seen order after deduplication.

Reordering input observations may change evidence ordinals, evidence keys, link
ordering, and diagnostics ordering. It must preserve the same canonical node
and edge sets when the observations describe the same facts.

## Confidence Aggregation

Confidence aggregation is pure and deterministic.

Rank order:

1. `manual`
2. `extracted`
3. `heuristic`
4. `unknown`

Multiple evidence records collapse onto one canonical edge when they share:

- graph key version;
- source canonical key;
- edge kind;
- target canonical key; and
- canonicalized identity metadata.

Edge confidence is the highest ranked confidence among supporting evidence
records. Node confidence is the highest ranked confidence among node evidence
links plus any edge evidence that caused the node to be inferred.

Unknown and dynamic placeholder targets do not automatically lower confidence.
The confidence summary reflects the evidence that the source contains a dynamic
or unknown relationship. For example, parser-backed evidence may confidently
show that a shell script sources a dynamic path, even though the target is
`dynamic:file:*`.

Contradictory evidence is evidence that cannot be true at the same time for the
same canonical identity. Initial contradiction rules:

- the same file node in one run has multiple content hashes;
- the same file node in one run has conflicting generated or executable flags;
- the same canonical edge has conflicting identity metadata;
- a valid raw target disagrees with metadata-derived target from the same
  observation; or
- future negative evidence denies a relationship supported by positive
  evidence.

Repeated command argv, shell source strings, env assignment values, or host
mutation reasons are not contradictory by themselves. They are metadata
diversity unless they conflict with identity metadata.

Set `conflict = true` on the affected node or edge when contradictory evidence
exists. Preserve all evidence records and add a `conflicting_evidence`
diagnostic. The confidence remains the strongest supported confidence, with
the conflict flag carrying the warning.

## Metadata Merge Policy

Metadata has two classes:

- identity metadata, which participates in canonical edge identity; and
- summary/display metadata, which helps readback and explanation but does not
  disambiguate the canonical fact.

For the first implementation subset, identity metadata is empty for all current
edge kinds. Source key, edge kind, target key, and graph key version identify
the canonical relationship. Future ADRs or registry updates may add
identity-disambiguating metadata for specific edge kinds.

Summary metadata is deterministic:

- repeated scalar values become sorted-by-first-seen arrays when more than one
  distinct value is observed;
- repeated arrays are deduplicated by JSON value while preserving first-seen
  order;
- metadata object keys are sorted during serialization;
- raw source text belongs in evidence metadata by default, not summary
  metadata;
- summary metadata may include small non-secret examples when useful; and
- full raw observation JSON is excluded until raw observation retention exists.

Secret-prone values are excluded from summary metadata. Env values whose
variable names contain `SECRET`, `TOKEN`, `PASSWORD`, `PASS`, `KEY`,
`CREDENTIAL`, or `AUTH` are secret-prone. Evidence metadata may record
`value_present: true` and an assignment shape, but should not store the literal
secret-prone value.

Current observation merge behavior:

| Observation metadata | Summary metadata behavior | Evidence metadata behavior |
| --- | --- | --- |
| `shell.command` `command` | Deduplicated `commands` array. | Preserve `command`. |
| `shell.command` `argv` | Deduplicated `argv_examples` array, capped by implementation constant. | Preserve full argv from the observation. |
| `shell.command` `raw` | Excluded from summary. | Preserve raw command text. |
| `shell.source` `source` | Deduplicated `sources` array. | Preserve source argument. |
| `shell.source` `resolved_path` | Deduplicated `resolved_paths` array. | Preserve resolved path. |
| `shell.source` `raw` | Excluded from summary. | Preserve raw source text. |
| `shell.env` `operation` | Edge kind encodes read/write; optional `operations` array may mirror it. | Preserve operation. |
| `shell.env` `scope` | Deduplicated `scopes` array for write edges. | Preserve scope. |
| `shell.env` `value` | Deduplicated `values` array only when not secret-prone; otherwise value count/redaction metadata. | Preserve non-secret literal value; redact secret-prone literal value. |
| `shell.host_mutation` `tool` | Deduplicated `tools` array. | Preserve tool. |
| `shell.host_mutation` `category` | Target key encodes category; optional category mirror allowed. | Preserve category. |
| `shell.host_mutation` `argv` | Deduplicated `argv_examples` array, capped by implementation constant. | Preserve argv. |
| `shell.host_mutation` `effective_argv` | Deduplicated `effective_argv_examples` array, capped by implementation constant. | Preserve effective argv. |
| `shell.host_mutation` `privileged` | `privileged_observed` true if any evidence is privileged. | Preserve boolean. |
| `shell.host_mutation` `reason` | Deduplicated `reasons` array. | Preserve reason. |
| `file` `language` | Scalar if one value, array plus conflict when contradictory. | Preserve language. |
| `file` `role` | Scalar if one value, array when multiple non-conflicting roles are observed. | Preserve role. |
| `file` `content_hash` | Scalar if one value; conflict if multiple values in one run. | Preserve content hash. |
| `file` `executable` | Scalar if one value; conflict if contradictory in one run. | Preserve executable. |
| `file` `generated` | Scalar if one value; conflict if contradictory in one run. | Preserve generated. |

## Raw Observation Mapping Implementation Details

The first canonicalizer implementation supports current observation kinds only:

- `file`;
- `shell.command`;
- `shell.source`;
- `shell.env` read;
- `shell.env` write; and
- `shell.host_mutation`.

Python, Nix, and Ruby raw observation kinds are deferred. Fixture stubs may
exist for future language examples, but they should currently expect
`unsupported_raw_observation_kind` warnings unless the implementation phase has
explicitly added support.

### `file`

Required fields:

- `path`
- `source_id`
- `confidence`
- `extractor`
- `extractor_version`

Optional metadata:

- `language`
- `role`
- `content_hash`
- `executable`
- `generated`

Canonical mapping:

- source node: `file_key(path)`
- target node: none
- edge kind: none
- evidence: one `CanonicalEvidence`
- node evidence link: `observed`

Diagnostics:

- repo-escaping or malformed `path`: `error`, skip observation;
- conflicting file metadata: `warning`, keep node with `conflict = true`.

### `shell.command`

Required metadata:

- `command`, or `argv[0]`, or a valid placeholder target plus
  `dynamic_reason`.

Optional metadata:

- `argv`
- `raw`
- `dynamic_reason`

Canonical mapping:

- source node: `file_key(path)`
- target node: `tool_key(command)` for static command;
- placeholder target: `dynamic_key("tool", reason)` or
  `unknown_key("tool", reason)` when static command is unavailable;
- edge kind: `executes`;
- evidence: path, line range, extractor, raw kind, raw source id, confidence,
  and command metadata;
- edge evidence link: `supports`.

Diagnostics:

- malformed raw target but valid command metadata: `warning`, rebuild target
  from metadata;
- missing command and no placeholder reason: `warning`, create
  `unknown:tool:missing-command`;
- dynamic command: `info` or `warning` depending on whether extractor supplied
  an explicit dynamic reason.

### `shell.source`

Required metadata:

- `resolved_path` for static in-repository sources; or
- `dynamic_reason`; or
- a valid `dynamic:file:*`, `unknown:file:*`, or `external:file:*` target.

Optional metadata:

- `source`
- `raw`
- `argv`

Canonical mapping:

- source node: `file_key(path)`
- target node: `file_key(resolved_path)` for static repository source;
- placeholder target: dynamic, unknown, or external file key;
- edge kind: `sources`;
- evidence: path, line range, extractor, raw kind, raw source id, confidence,
  and source metadata;
- edge evidence link: `supports`.

Diagnostics:

- repo-escaping `resolved_path`: `warning`, use
  `unknown:file:repo-escaping-source`;
- dynamic source: `info`, use `dynamic:file:*`;
- missing static and placeholder data: `warning`, use
  `unknown:file:unresolved-shell-source`.

### `shell.env` Read

Required metadata:

- `operation = "read"`
- `variable`

Optional metadata:

- `raw`
- expansion form metadata when available

Canonical mapping:

- source node: `file_key(path)`
- target node: `env_key(variable)`
- edge kind: `reads_env`
- evidence: path, line range, extractor, raw source id, confidence, variable,
  operation, and selected metadata.

Diagnostics:

- missing operation: `warning`, skip observation;
- unsupported operation: `warning`, skip observation;
- missing variable: `warning`, use `unknown:env:missing-variable`.

### `shell.env` Write

Required metadata:

- `operation = "write"`
- `variable`

Optional metadata:

- `scope`
- `value`
- `raw`
- assignment form metadata when available

Canonical mapping:

- source node: `file_key(path)`
- target node: `env_key(variable)`
- edge kind: `writes_env`
- evidence: path, line range, extractor, raw source id, confidence, variable,
  operation, scope, value policy, and selected metadata.

Diagnostics:

- missing operation: `warning`, skip observation;
- unsupported operation: `warning`, skip observation;
- missing variable: `warning`, use `unknown:env:missing-variable`;
- secret-prone value: `info`, redact literal value from summary metadata.

### `shell.host_mutation`

Required metadata:

- `category`

Optional metadata:

- `tool`
- `argv`
- `effective_argv`
- `privileged`
- `reason`
- `raw`

Canonical mapping:

- source node: `file_key(path)`
- target node: `host_category_key(category)`
- placeholder target: `unknown:host.category:missing-host-category` if category
  is absent;
- edge kind: `mutates_host`;
- evidence: path, line range, extractor, raw source id, confidence, category,
  tool, argv, privilege, and reason metadata.

Diagnostics:

- missing category: `warning`, use placeholder target;
- unregistered category: `warning`, use placeholder target until registry is
  updated;
- dynamic command with supported host category: keep the host mutation edge if
  classifier evidence supports the category.

## Golden Fixture Strategy

Golden fixtures live under:

```text
src/test/fixtures/canonicalization/
  files_basic/
    raw_observations.jsonl
    expected_canonical_graph.json
  shell_basic/
    raw_observations.jsonl
    expected_canonical_graph.json
  shell_dynamic/
    raw_observations.jsonl
    expected_canonical_graph.json
  shell_conflicts/
    raw_observations.jsonl
    expected_canonical_graph.json
  unsupported_kind/
    raw_observations.jsonl
    expected_canonical_graph.json
```

Fixture format:

- `raw_observations.jsonl` is UTF-8 JSONL, one raw observation per line, using
  the existing raw observation schema.
- `expected_canonical_graph.json` is UTF-8 deterministic JSON produced by
  `CanonicalizationResult.to_dict()`.
- Expected JSON uses two-space indentation, sorted object keys, trailing
  newline, and sorted top-level arrays according to this ADR.

Expected graph JSON must include:

- summary counts;
- nodes;
- edges;
- evidence;
- node evidence links;
- edge evidence links; and
- diagnostics.

Golden files are checked by exact JSON equality after canonical serialization.
The fixture harness should parse raw JSONL, canonicalize, serialize with the
canonical serializer, and compare the serialized JSON bytes or strings to the
expected file. Semantic assertions can supplement golden tests, but they do not
replace exact golden equality.

## Required First Golden Fixtures

The first fixture set must cover:

- file observation only;
- one shell command executing `tool:nix`;
- two shell commands in one file collapsing to one `executes` edge with two
  evidence links;
- shell source to static repository file;
- shell dynamic source path;
- env read;
- env write;
- multiple writes to the same env var with different values collapsing to one
  edge;
- host mutation `package-management`;
- malformed target rebuilt from metadata;
- malformed target replaced with placeholder and diagnostic;
- repo-escaping source path;
- unsupported raw observation kind; and
- conflicting evidence.

Recommended fixture directories:

```text
files_basic/
shell_executes_nix/
shell_executes_collapse/
shell_source_static/
shell_source_dynamic/
shell_env_read/
shell_env_write/
shell_env_write_collapse/
shell_host_mutation/
malformed_target_rebuilt/
malformed_target_placeholder/
repo_escaping_source/
unsupported_kind/
conflicting_evidence/
```

## Public Serialization

`CanonicalizationResult.to_dict()` should produce the public canonical fixture
shape.

Top-level fields:

- `graph_key_version`
- `ok`
- `summary`
- `nodes`
- `edges`
- `evidence`
- `node_evidence_links`
- `edge_evidence_links`
- `diagnostics`

Summary fields:

- `raw_observations`
- `nodes`
- `edges`
- `evidence`
- `node_evidence_links`
- `edge_evidence_links`
- `diagnostics`
- `errors`
- `warnings`
- `infos`

Node fields:

- `canonical_key`
- `graph_key_version`
- `kind`
- `display_name`
- `confidence`
- `conflict`
- `metadata`

Edge fields:

- `edge_key`
- `graph_key_version`
- `source_key`
- `kind`
- `target_key`
- `identity_metadata`
- `metadata`
- `confidence`
- `conflict`

Evidence fields:

- `evidence_key`
- `raw_observation_ordinal`
- `raw_schema_version`
- `raw_kind`
- `raw_source_id`
- `path`
- `start_line`
- `end_line`
- `extractor`
- `extractor_version`
- `confidence`
- `metadata`

Node evidence link fields:

- `canonical_key`
- `evidence_key`
- `link_kind`

Edge evidence link fields:

- `edge_key`
- `evidence_key`
- `link_kind`

Diagnostic fields:

- `severity`
- `category`
- `message`
- `raw_observation_ordinal`
- `raw_source_id`
- `path`
- `field`
- `value`
- `placeholder_key`

Use `canonical_key` for node identity. Do not use the old
observation-derived `stable_key` terminology for canonical nodes. Edge
identity is represented by `graph_key_version`, `source_key`, `kind`,
`target_key`, and `identity_metadata`; `edge_key` is a deterministic computed
handle for serialization and evidence links.

Raw observation ordinals are exposed on evidence and diagnostics so golden
fixtures and explain output can tie canonical facts back to input JSONL order.

## Compatibility With Current Code

This pure layer coexists with current observation-derived normalization and
storage code.

Requirements:

- no existing CLI command behavior changes in this ADR;
- no Postgres schema changes in this ADR;
- no removal of current observation-derived normalization yet;
- new tests can run with `python3 tools/run_tests.py --suite unit`;
- canonicalizer code must not require third-party packages unless separately
  approved; and
- the canonicalizer must not import storage or Postgres code.

An `observations canonicalize` CLI command may be added later as a developer
readback convenience, but only after the pure key builder, canonical dataclass,
mapping, and fixture tests pass.

## Implementation Phases After This ADR

### Phase A1: Implement Graph Keys and Tests

Create `repomap_kg.graph_keys` and `test_graph_keys.unit.test.py`. Test every
builder, parser, validator, path normalization case, percent escape case, and
malformed input case from this ADR.

### Phase A2: Implement Canonical Dataclasses and Serialization Tests

Create `repomap_kg.canonical`, `repomap_kg.canonical_diagnostics`, and
`test_canonical.unit.test.py`. Test deterministic sorting, `to_dict()`, summary
counts, edge key computation, evidence links, and diagnostic serialization.

### Phase B1: Implement Canonicalization for `file`

Create the first mapping in `repomap_kg.canonicalization`. Add unit tests and
the `files_basic` golden fixture.

### Phase B2: Implement Canonicalization for Current Shell Observation Kinds

Add mappings for `shell.command`, `shell.source`, `shell.env` read,
`shell.env` write, and `shell.host_mutation`. Add focused unit tests before
or with implementation.

### Phase B3: Add Golden Fixture Tests

Add `test_canonicalization_fixtures.unit.test.py` and the required first
fixtures. The fixture runner must compare exact deterministic JSON output.

### Phase B4: Add Developer CLI Command If Useful

After the pure layer and fixtures pass, add a developer-oriented command such
as `repomap-kg observations canonicalize <raw-observations.jsonl> --json`.
This phase is optional and must not change existing command behavior.

### Phase C: Storage Planning Later

Canonical storage DDL, migrations, dual writes, and replay commands come later,
after the pure layer is tested and stable.

## Rejected Alternatives

### Jump Directly to Canonical Postgres Tables

Rejected. ADR 0003 requires a tested pure canonicalization layer before storage
changes. Storage-first work would make bugs harder to isolate and would couple
identity decisions to migration details too early.

### Use Current `NormalizedGraph` as the Canonical Graph Model

Rejected. The current `NormalizedGraph` is observation-derived and keeps
source-node identity tied to raw observation kind and source id. It remains
useful compatibility code, but it should not become the canonical domain graph
model.

### Encode Diagnostics as Fake Graph Nodes

Rejected. Diagnostics are processing facts, not repository graph facts. They
belong in `CanonicalizationResult.diagnostics`.

### Rely Only on Ad Hoc Unit Assertions Without Golden Fixtures

Rejected. Unit assertions are useful, but canonicalization needs byte-stable
fixtures that lock down ordering, metadata, evidence links, diagnostics, and
serialization together.

### Allow Nondeterministic Ordering

Rejected. Canonicalization output must be stable across runs for review,
replay, debugging, and future migration comparisons.

### Put Full Raw Source Excerpts Into Canonical Summary Metadata

Rejected for the first implementation. Raw source text and excerpts can be
large or secret-prone. Keep raw text in evidence metadata when already emitted
by extractors, and defer source excerpt storage policy.

### Use Raw Observation Target Without Rebuilding or Validation

Rejected. Raw `target` is extractor output, not trusted canonical identity.
The canonicalizer must rebuild from typed metadata when possible and validate
any raw target before reuse.

### Require Parser-Backed Shell Extraction Before Canonicalization

Rejected. The current raw shell observations are enough to implement and test
the canonicalization contract. Parser improvements can improve raw observation
quality later without blocking the pure canonicalizer.

## Required Examples

The examples below show abbreviated expected canonical output. Full golden
fixtures should include every serialized field defined above.

### `file:bin/tool --executes--> tool:nix`

Raw observation:

```json
{"schema_version":1,"kind":"shell.command","source_id":"bin/tool#call:12:nix-build","path":"bin/tool","start_line":12,"end_line":12,"name":"nix build","target":"tool:nix","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","metadata":{"command":"nix","argv":["nix","build",".#checks"],"raw":"nix build .#checks"}}
```

Expected canonical output excerpt:

```json
{
  "nodes": [
    {"canonical_key": "file:bin/tool", "kind": "file"},
    {"canonical_key": "tool:nix", "kind": "tool"}
  ],
  "edges": [
    {"source_key": "file:bin/tool", "kind": "executes", "target_key": "tool:nix", "confidence": "heuristic", "conflict": false}
  ],
  "edge_evidence_links": [
    {"link_kind": "supports"}
  ],
  "diagnostics": []
}
```

### Two Nix Command Observations Collapse to One Edge

Raw observations:

```json
{"schema_version":1,"kind":"shell.command","source_id":"bin/tool#call:1:nix-build","path":"bin/tool","start_line":1,"end_line":1,"target":"tool:nix","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","metadata":{"command":"nix","argv":["nix","build"]}}
```

```json
{"schema_version":1,"kind":"shell.command","source_id":"bin/tool#call:2:nix-flake-check","path":"bin/tool","start_line":2,"end_line":2,"target":"tool:nix","confidence":"manual","extractor":"repo-shell","extractor_version":"0.1.0","metadata":{"command":"nix","argv":["nix","flake","check"]}}
```

Expected canonical output excerpt:

```json
{
  "summary": {"raw_observations": 2, "edges": 1, "edge_evidence_links": 2},
  "edges": [
    {"source_key": "file:bin/tool", "kind": "executes", "target_key": "tool:nix", "confidence": "manual", "conflict": false}
  ]
}
```

### `file:scripts/build.sh --sources--> file:lib/common.sh`

Raw observation:

```json
{"schema_version":1,"kind":"shell.source","source_id":"scripts/build.sh#source:3:lib/common.sh","path":"scripts/build.sh","start_line":3,"end_line":3,"target":"file:lib/common.sh","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","metadata":{"source":"../lib/common.sh","resolved_path":"lib/common.sh","raw":"source ../lib/common.sh"}}
```

Expected edge:

```json
{"source_key": "file:scripts/build.sh", "kind": "sources", "target_key": "file:lib/common.sh"}
```

### `file:scripts/build.sh --sources--> dynamic:file:shell-source-expanded-from-variable`

Raw observation:

```json
{"schema_version":1,"kind":"shell.source","source_id":"scripts/build.sh#source:4:dynamic","path":"scripts/build.sh","start_line":4,"end_line":4,"target":"dynamic:file:shell-source-expanded-from-variable","confidence":"unknown","extractor":"repo-shell","extractor_version":"0.1.0","metadata":{"source":"$LIB_DIR/common.sh","dynamic_reason":"shell-source-expanded-from-variable","raw":"source \"$LIB_DIR/common.sh\""}}
```

Expected edge and diagnostic:

```json
{
  "edges": [
    {"source_key": "file:scripts/build.sh", "kind": "sources", "target_key": "dynamic:file:shell-source-expanded-from-variable"}
  ],
  "diagnostics": [
    {"severity": "info", "category": "dynamic_target", "placeholder_key": "dynamic:file:shell-source-expanded-from-variable"}
  ]
}
```

### `file:scripts/build.sh --reads_env--> env:PATH`

Raw observation:

```json
{"schema_version":1,"kind":"shell.env","source_id":"scripts/build.sh#env-read:8:PATH","path":"scripts/build.sh","start_line":8,"end_line":8,"target":"env:PATH","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","metadata":{"operation":"read","variable":"PATH","raw":"echo \"$PATH\""}}
```

Expected edge:

```json
{"source_key": "file:scripts/build.sh", "kind": "reads_env", "target_key": "env:PATH"}
```

### `file:scripts/build.sh --writes_env--> env:FOO`

Raw observation:

```json
{"schema_version":1,"kind":"shell.env","source_id":"scripts/build.sh#env-write:9:FOO","path":"scripts/build.sh","start_line":9,"end_line":9,"target":"env:FOO","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","metadata":{"operation":"write","variable":"FOO","value":"bar","scope":"shell","raw":"FOO=bar"}}
```

Expected edge:

```json
{"source_key": "file:scripts/build.sh", "kind": "writes_env", "target_key": "env:FOO", "metadata": {"scopes": ["shell"], "values": ["bar"]}}
```

### `file:scripts/maintain.sh --mutates_host--> host.category:package-management`

Raw observation:

```json
{"schema_version":1,"kind":"shell.host_mutation","source_id":"scripts/maintain.sh#host-mutation:5:brew-install","path":"scripts/maintain.sh","start_line":5,"end_line":5,"target":"host.category:package-management","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","metadata":{"tool":"brew","category":"package-management","argv":["brew","install","jq"],"effective_argv":["brew","install","jq"],"privileged":false,"reason":"brew mutating verb","raw":"brew install jq"}}
```

Expected edge:

```json
{"source_key": "file:scripts/maintain.sh", "kind": "mutates_host", "target_key": "host.category:package-management", "metadata": {"tools": ["brew"], "privileged_observed": false, "reasons": ["brew mutating verb"]}}
```

### Malformed Target Diagnostic

Raw observation:

```json
{"schema_version":1,"kind":"shell.command","source_id":"bin/tool#call:1:nix","path":"bin/tool","start_line":1,"end_line":1,"target":"tool:nix%2","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","metadata":{"command":"nix","argv":["nix","build"]}}
```

Expected behavior:

- rebuild target from metadata as `tool:nix`;
- emit `warning` diagnostic with category `malformed_percent_escape` or
  `invalid_canonical_key`;
- keep `file:bin/tool --executes--> tool:nix`.

Expected diagnostic excerpt:

```json
{"severity": "warning", "category": "malformed_percent_escape", "raw_source_id": "bin/tool#call:1:nix", "field": "target"}
```

### Unsupported Observation Kind Diagnostic

Raw observation:

```json
{"schema_version":1,"kind":"python.import","source_id":"src/main/python/repomap_kg/cli.py#import:storage","path":"src/main/python/repomap_kg/cli.py","start_line":11,"end_line":11,"target":"python.module:repomap_kg.storage","confidence":"extracted","extractor":"repo-python","extractor_version":"0.1.0","metadata":{"source_module":"repomap_kg.cli","target_module":"repomap_kg.storage"}}
```

Expected behavior for the first implementation subset:

- skip the observation;
- emit a warning diagnostic;
- produce no Python canonical edge until a later phase adds Python support.

Expected diagnostic excerpt:

```json
{"severity": "warning", "category": "unsupported_raw_observation_kind", "raw_source_id": "src/main/python/repomap_kg/cli.py#import:storage"}
```
