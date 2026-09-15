# ADR 0003: Canonicalization Pipeline, Storage Transition, and Replay Strategy

## Status

Accepted

## Date

2026-06-29

## Context

ADR 0001 accepts the distinction between raw observations, evidence records,
canonical nodes, and canonical edges. ADR 0002 accepts graph key version 1,
canonical key grammar, key normalization rules, and the initial relationship
vocabulary.

RepoMap currently stores an observation-derived graph shape. That storage shape
has been useful for early Postgres loading and readback, but observation-derived
node keys are not the long-term public graph identity. The next decision is how
RepoMap moves from raw observations and observation-derived storage to canonical
graph storage without breaking current commands.

This ADR defines the canonicalization pipeline, raw-observation mapping rules,
canonical key API boundary, storage transition plan, evidence model, raw
observation retention strategy, compatibility phases, query semantics, failure
behavior, and examples.

## Decision

RepoMap will implement canonicalization as a tested pure layer before changing
canonical storage.

The first implementation target is a deterministic transformation like:

```text
list[RawObservation] -> CanonicalGraph
```

That layer will validate raw observations, build canonical keys only through a
small key module, construct canonical nodes, canonical edges, and evidence
links, and summarize confidence. Storage migrations and dual-write behavior
come after the pure canonicalizer has unit tests for representative examples.

When canonical storage is introduced, RepoMap will create canonical graph tables
alongside the current observation-derived tables. Existing commands must keep
working during the transition unless a later ADR explicitly breaks
compatibility.

## Canonicalization Pipeline Stages

The full indexing and readback flow is:

1. Repository discovery
2. Deterministic extractors
3. Raw observations JSONL
4. Raw observation validation
5. Canonical key building
6. Canonical node, edge, and evidence construction
7. Confidence aggregation
8. Storage load
9. Query and readback
10. Compatibility output

### Stage Properties

| Stage | Input | Output | Deterministic or pure | Postgres |
| --- | --- | --- | --- | --- |
| Repository discovery | repository root, profile | candidate files and `file` observations | deterministic for a repository snapshot and profile; reads the filesystem | no |
| Deterministic extractors | file content, path, profile | extractor-specific raw observations | pure over supplied content and profile, except discovery supplies file IO | no |
| Raw observations JSONL | raw observation records | appendable JSONL artifact | deterministic serialization; writes a file or stream | no |
| Raw observation validation | JSONL records | typed `RawObservation` values and diagnostics | pure | no |
| Canonical key building | typed observations and repository context | canonical node keys | pure | no |
| Canonical graph construction | typed observations and canonical keys | `CanonicalGraph` with nodes, edges, evidence links | pure | no |
| Confidence aggregation | evidence confidence values and conflicts | edge and node confidence summaries | pure | no |
| Storage load | canonical graph and raw observations | Postgres rows | effectful | yes |
| Query and readback | canonical graph rows, compatibility rows | result records | effectful when backed by Postgres; pure formatting after records load | yes for storage commands |
| Compatibility output | readback records | legacy and canonical CLI fields | pure formatting | no additional Postgres writes |

The canonicalization package must not require a database connection. Postgres
enters the flow only at storage load and storage-backed query/readback.

## Raw Observation to Canonical Graph Mapping

The canonicalizer maps raw observation kinds into canonical nodes, canonical
edges, and evidence. Extractors may emit richer raw observation kinds, but
canonical output must use the ADR 0002 key and edge registries.

### Mapping Table

| Raw observation kind | Source canonical node | Target canonical node and edge | Evidence fields | Edge metadata and confidence | Missing, malformed, external, unknown, or dynamic behavior |
| --- | --- | --- | --- | --- | --- |
| `file` | `file_key(path)` | No edge by default. The file node receives optional node evidence. | `path`, line span when present, `source_id`, `extractor`, `extractor_version`, `confidence`, selected file metadata. | Node metadata may include language, role, generated, executable, and content hash. Confidence is copied to node evidence; node confidence is summarized from evidence. | Repo-escaping or malformed paths are validation errors. Missing files may still produce a file node if the raw observation is from a retained historical run and metadata marks it missing. |
| `shell.command` | `file_key(path)` | Static command target becomes `tool_key(command)` with edge `executes`. | `path`, `start_line`, `end_line`, `source_id`, extractor fields, raw command text, argv. | Metadata includes `command`, `argv`, optional subcommand and raw text. Evidence confidence is copied; edge confidence is aggregated across command evidence. | Variable-derived or command-substitution commands become `dynamic_key("tool", reason)`. Malformed command names become `unknown_key("tool", reason)`. Stable commands outside the repository remain `tool:*`, not `external:*`, because tools are durable by name. |
| `shell.source` | `file_key(path)` | Resolved repository source path becomes `file_key(resolved_path)` with edge `sources`. | `path`, source line span, `source_id`, extractor fields, raw source text, original source argument, resolved path when known. | Metadata includes `source`, `resolved_path`, argv, and raw text. Confidence is copied and aggregated. | Dynamic source paths become `dynamic_key("file", "shell-source-expanded-from-variable")` or another registered reason. Repo-escaping paths become `external_key("file", stable_name)` only when a stable external path policy exists; otherwise `unknown_key("file", "repo-escaping-source")`. Missing in-repo files use `unknown_key("file", "missing-file")` unless profile policy keeps the intended `file:*` target with a missing flag. |
| `shell.env` with `operation=read` | `file_key(path)` | `env_key(variable)` with edge `reads_env`. | `path`, line span, `source_id`, extractor fields, variable name, operation, raw text. | Metadata includes `operation`, expansion form when known, and raw text. Confidence is copied and aggregated. | Invalid variable names become `unknown_key("env", reason)`. Dynamic variable names become `dynamic_key("env", reason)`. Values are never part of node identity. |
| `shell.env` with `operation=write` | `file_key(path)` | `env_key(variable)` with edge `writes_env`. | `path`, line span, `source_id`, extractor fields, variable name, operation, raw text, optional value. | Metadata includes `operation`, scope, assignment form, optional value, and raw text. Confidence is copied and aggregated. Values summarize as metadata, not key material. | Invalid variable names become `unknown_key("env", reason)`. Dynamic variable names become `dynamic_key("env", reason)`. Missing value is metadata absence, not a different edge. |
| `shell.host_mutation` | `file_key(path)` | `host_category_key(category)` with edge `mutates_host`. | `path`, line span, `source_id`, extractor fields, raw text, argv, effective argv, tool, category, reason. | Metadata includes `tool`, `category`, `argv`, `effective_argv`, `privileged`, `reason`, and raw text. Confidence is copied and aggregated. | Missing or unregistered categories become `unknown_key("host.category", reason)` until the category registry accepts them. Dynamic command targets may still produce a host category edge only when classifier evidence supports the category. |
| Future `python.module` | `file_key(path)` | `python_module_key(module)` with edge `defines`. | `path`, optional module definition span, `source_id`, extractor fields, module name. | Metadata includes package root, importable path, and parser source. Confidence is `extracted` for parser-backed facts or profile confidence for profile facts. | Module names that cannot be derived become `unknown_key("python.module", reason)`. Repo-escaping module paths are validation errors. |
| Future `python.import` | `python_module_key(source_module)` | `python_module_key(target_module)` with edge `imports`; unresolved external modules may target `external_key("python.module", stable_name)`. | `path`, import line span, `source_id`, extractor fields, import statement, import level, alias metadata. | Metadata includes import form, imported names, alias, relative level, and whether resolution was local or external. Confidence is parser-backed `extracted` when static resolution succeeds, otherwise heuristic or unknown. | Relative imports without package context become `unknown_key("python.module", "missing-package-context")`. Dynamic imports become `dynamic_key("python.module", reason)`. Missing local modules become `unknown_key("python.module", "missing-module")`. |
| Future `python.class` | `file_key(path)` | `python_class_key(module, class_name)` with edge `defines`. | `path`, class span, `source_id`, extractor fields, module, class name. | Metadata includes bases when statically known and decorators when useful. Confidence is parser-backed `extracted`. | Malformed or dynamic names become `unknown_key("python.class", reason)`. Nested class names use the ADR 0002 qualified-name segment. |
| Future `python.function` | `file_key(path)` | `python_function_key(module, function_name)` with edge `defines`. | `path`, function span, `source_id`, extractor fields, module, function name. | Metadata includes decorators, async flag, and signature summary when safe. Confidence is parser-backed `extracted`. | Malformed names become `unknown_key("python.function", reason)`. Nested functions use stable qualified names only when the parser exposes them. |
| Future `python.method` | `file_key(path)` | `python_method_key(module, class_name, method_name)` with edge `defines`. | `path`, method span, `source_id`, extractor fields, module, class, method. | Metadata includes decorators, async flag, and signature summary when safe. Confidence is parser-backed `extracted`. | Malformed class or method names become `unknown_key("python.method", reason)`. Methods without resolvable owning class are not fabricated. |
| Future `nix.app` | `file_key(path)` for the defining file; `nix_app_key(flake_ref, system, name)` for the app node | `file_key(program_path)` with edge `exposes_script` when the app exposes a repository script. The defining file may also `defines` the app node. | `path`, Nix attribute span when available, `source_id`, extractor fields, flake ref, system, app name, program path. | Metadata includes program, system, app type, and flake ref. Confidence is `extracted` for evaluator-backed facts and `heuristic` for static text facts. | Dynamic program paths become `dynamic_key("file", reason)`. External programs become `external_key("file", stable_name)` or `tool_key(name)` depending on what the app exposes. Malformed flake attrs become `unknown_key("nix.app", reason)`. |
| Future `nix.package` | `file_key(path)` | `nix_package_key(flake_ref, system, name)` with edge `defines`; package dependencies use `depends_on` from a `nix.output:*` or package node when statically known. | `path`, attribute span, `source_id`, extractor fields, flake ref, system, package name. | Metadata includes attr path, derivation name when known, system, and selected dependency names. Confidence follows extractor source. | Dynamic attrs or evaluator-incomplete packages become `unknown_key("nix.package", reason)`. External dependencies use package or external keys only when stable. |
| Future `nix.devShell` | `file_key(path)` | `nix_dev_shell_key(flake_ref, system, name)` with edge `defines`; shell inputs may use `depends_on` when stable. | `path`, attribute span, `source_id`, extractor fields, flake ref, system, shell name. | Metadata includes attr path, packages, shellHook summary, and system. Confidence follows extractor source. | Dynamic shell inputs become `dynamic_key("nix.package", reason)` or unknown placeholders. |
| Future `nix.check` | `file_key(path)` | `nix_check_key(flake_ref, system, name)` with edge `defines`; check dependencies may use `depends_on` when stable. | `path`, attribute span, `source_id`, extractor fields, flake ref, system, check name. | Metadata includes attr path, runner, system, and dependency summary. Confidence follows extractor source. | Dynamic checks become `unknown_key("nix.check", reason)`. External check runners use stable tool or external keys. |
| Future `ruby.require` | `ruby.module:*`, `ruby.class:*`, or `file_key(path)` depending on available source context | Target Ruby module/class key or `external_key("ruby.module", stable_name)` with edge `imports`. | `path`, line span, `source_id`, extractor fields, require string, resolved path when known. | Metadata includes require form, resolved path, and local or external resolution. Confidence is parser-backed `extracted` or heuristic. | Dynamic require paths become `dynamic_key("ruby.module", reason)`. Missing local requires become `unknown_key("ruby.module", "missing-require")`. |
| Future `ruby.class` | `file_key(path)` | `ruby_class_key(class_name)` with edge `defines`. | `path`, class span, `source_id`, extractor fields, class name. | Metadata includes namespace and superclass when statically known. Confidence is parser-backed `extracted`. | Malformed or dynamic class names become `unknown_key("ruby.class", reason)`. |
| Future `ruby.method` | `file_key(path)` | `ruby_method_key(owner, method_name)` with edge `defines`. | `path`, method span, `source_id`, extractor fields, owner and method name. | Metadata includes singleton or instance method form, visibility when known, and source owner. Confidence is parser-backed `extracted`. | Methods without stable owner become `unknown_key("ruby.method", reason)` rather than a guessed owner. |

## Canonical Key Builder and Parser API

RepoMap will add a small canonical-key module before storage changes. The module
is the only supported implementation boundary for graph key construction and
parsing.

Required API:

```python
file_key(path)
tool_key(name)
env_key(name)
host_category_key(category)
python_module_key(name)
python_class_key(module, class_name)
python_function_key(module, function_name)
python_method_key(module, class_name, method_name)
nix_app_key(flake_ref, system, name)
nix_package_key(flake_ref, system, name)
dynamic_key(domain, reason)
external_key(domain, stable_name)
unknown_key(domain, reason)
parse_key(key)
validate_key(key)
```

Before their corresponding extractors write canonical facts, the same module
should add convenience helpers for the rest of the ADR 0002 grammar, including:

```python
nix_dev_shell_key(flake_ref, system, name)
nix_check_key(flake_ref, system, name)
nix_output_key(flake_ref, output_path)
ruby_module_key(name)
ruby_class_key(class_name)
ruby_method_key(owner, method_name)
```

The first implementation should also include internal helpers for percent
encoding and decoding, namespace registration, path normalization, and error
messages.

Extractors must not hand-format canonical keys except through this module. Raw
observation `target` values are hints or extractor output, not trusted
canonical identity. The canonicalizer must parse and validate target-like raw
fields before reusing them, and must rebuild canonical keys from typed source
data whenever possible.

`parse_key(key)` returns a typed parse result with graph key version 1
namespace and decoded segments. `validate_key(key)` returns success or a
diagnostic without silently repairing malformed keys.

## Storage Transition Plan

RepoMap will introduce canonical storage by creating new canonical graph tables
alongside the current observation-derived `nodes`, `edges`, and `evidence`
tables. The current tables remain compatibility storage during the transition.

### Recommended Storage Shape

The canonical storage shape should include:

- `canonical_nodes`
- `canonical_edges`
- `canonical_edge_evidence`
- `canonical_node_evidence`
- `raw_observations`

The existing `repositories` and `runs` tables can remain the run and repository
anchors.

Recommended uniqueness:

- Canonical node uniqueness: `repository_id`, `graph_key_version`,
  `canonical_key`
- Canonical edge uniqueness: `repository_id`, `graph_key_version`,
  `source_canonical_key`, `edge_kind`, `target_canonical_key`,
  `identity_metadata_hash`
- Raw observation uniqueness: `run_id`, `ordinal` and, for idempotence,
  `payload_hash`

Repository-scoped uniqueness is the first storage promise. A future global
entity catalog can deduplicate shared external tools or packages across
repositories without changing query semantics inside a repository.

Canonical edge rows store:

- graph key version;
- source canonical node reference;
- registered edge kind;
- target canonical node reference;
- identity metadata JSON;
- display or summary metadata JSON;
- confidence summary;
- conflict flags; and
- creation/update timestamps.

Identity metadata is empty for most initial edges. It participates in edge
identity only when ADR 0002 says the relationship would otherwise collapse
incorrectly. Display metadata and evidence metadata do not disambiguate edge
identity.

Many evidence records may support one canonical edge through
`canonical_edge_evidence`. Optional node evidence may support canonical nodes
through `canonical_node_evidence`. A single evidence record may support multiple
canonical facts through those join tables.

### Graph Key Version

Canonical storage must include `graph_key_version` on canonical nodes and
canonical edges before canonical storage becomes part of the public contract.
Version 1 is the grammar accepted in ADR 0002.

Raw observation rows keep their own `schema_version`. Replaying old raw
observations through a newer canonicalizer may produce graph key version 2 rows
if a future ADR changes key grammar incompatibly.

### Migration Ordering

Storage migration order:

1. Implement and test canonical key builders and parsers.
2. Implement and test pure raw-observation-to-canonical-graph mapping.
3. Add raw observation retention table and load records without changing public
   graph readback.
4. Add canonical node, canonical edge, and evidence join tables.
5. Dual-write canonical rows alongside current observation-derived rows.
6. Add canonical readback commands or canonical fields on existing readback.
7. Migrate public queries to canonical graph identity.
8. Retire observation-derived public output only after compatibility windows are
   documented and tests prove equivalent behavior.

### Rollback Strategy

During phases C and D, rollback means disabling canonical writes and readback
while keeping existing observation-derived storage commands. Because canonical
tables are additive, rollback does not require deleting current rows. A later
cleanup migration may drop canonical tables only if no released command depends
on them.

### Rejected Storage Alternatives

Adding canonical columns to existing `nodes` and `edges` is rejected for the
initial transition. It would mix event-derived row identity with domain graph
identity and make uniqueness, evidence joins, and rollback harder.

Replacing observation-derived rows in place is rejected. Existing commands and
tests depend on the current shape, and in-place replacement would make rollback
and compatibility views fragile.

Storing only canonical graph rows immediately is rejected. RepoMap still needs
raw-observation replay, explainability, and compatibility while query behavior
settles.

## Evidence Model

Evidence records explain why RepoMap believes a canonical node or edge exists.

Evidence may link to nodes, edges, or both. A canonical edge can have multiple
evidence records. One evidence record can support multiple canonical facts, for
example a Python class definition observation can support a file-to-class
`defines` edge and node evidence for the class node.

Evidence stores selected fields from the raw observation:

- raw observation id, run id, and ordinal when persisted;
- raw observation schema version, kind, and source id;
- repository path;
- start line, end line, and future span fields when present;
- extractor name and extractor version;
- confidence;
- raw target-like value before canonical validation, when useful;
- selected metadata needed to explain the fact; and
- payload hash.

Source excerpts are deferred for now. The evidence model should allow an
excerpt field later, but the first implementation should avoid storing large or
secret-prone source snippets until redaction and size policy exist.

Raw observation JSON belongs in a separate `raw_observations` table, not inside
every evidence metadata object. Evidence metadata may cache selected fields for
fast explain output, but it should not duplicate the full raw observation JSON
as its primary retention mechanism.

## Raw Observation Retention and Replay

Current raw observations exist as JSONL input. Future normalizers will need to
replay old observations into newer canonical graphs. Existing observation-derived
database rows do not contain enough information to reconstruct full raw
observations.

RepoMap should persist each indexing run's raw observations in Postgres as one
row per raw observation:

- `repository_id`
- `run_id`
- `ordinal`
- `schema_version`
- `kind`
- `source_id`
- `path`
- `payload_json`
- `payload_hash`
- `created_at`

The JSONL artifact may also be kept as an optional compressed artifact path for
debugging, export, or large-run replay, but the table is the replay source of
truth. Evidence rows should reference raw observation rows by id and store
selected explanatory metadata.

This recommendation rejects skipping raw observation retention. Without retained
raw observations, RepoMap could not replay older runs into graph key version 2,
repair canonicalization bugs, compare normalizer output across versions, or
produce faithful explain output after storage changes.

## Compatibility Plan

Existing commands must keep working during the transition unless a later ADR
explicitly breaks compatibility.

### Phase A: Canonical Key Builders and Unit Tests

Implement the canonical-key module and unit tests for:

- every ADR 0002 namespace;
- repository-relative path normalization;
- percent escaping and malformed percent escapes;
- parse and validate behavior; and
- placeholder keys.

No storage changes happen in Phase A.

### Phase B: Pure Canonicalization In Memory

Implement `list[RawObservation] -> CanonicalGraph` in memory. Unit tests should
cover the examples in this ADR and assert canonical nodes, edges, evidence
links, metadata, confidence summaries, and failure diagnostics.

No storage changes happen in Phase B.

### Phase C: Write Canonical Rows Alongside Current Rows

Add raw observation retention and canonical tables. `storage load-files` or its
successor writes both current observation-derived rows and canonical rows. The
current readback commands still use the current tables unless explicitly asked
for canonical fields.

### Phase D: Add Canonical Readback Commands or Fields

Add canonical readback commands or extend existing readback JSON with fields
that distinguish:

- `node_stable_key` for observation-derived identity;
- `canonical_node_key` for graph identity;
- `edge_stable_key` for observation-derived edge identity; and
- `canonical_edge_key` or canonical edge identity fields for graph identity.

Table output may stay conservative; JSON output should expose both identities
where compatibility matters.

### Phase E: Migrate Public Queries to Canonical Graph Identity

Move public query semantics to canonical graph rows after canonical readback is
tested. Existing filters should accept canonical keys where possible and keep
legacy stable-key filters during the compatibility period.

### Phase F: Retire Observation-Derived Public Output When Safe

Observation-derived public output may be retired only after tests, docs, and
release notes identify the replacement fields. Internal compatibility views may
remain longer to help replay and explain older runs.

## Query Semantics After Canonicalization

Canonical graph queries should answer from canonical node and edge rows, then
join evidence only when the user asks for explanation or evidence-rich output.

| Query | Canonical answer |
| --- | --- |
| Files executing `tool:nix` | Find canonical edges where `edge_kind = 'executes'` and target key is `tool:nix`; return source nodes with `file:*` keys. |
| Files sourcing `file:lib/common.sh` | Find `sources` edges targeting `file:lib/common.sh`; return source `file:*` nodes. |
| Env vars read by an entrypoint | Resolve the entrypoint to one or more `file:*` canonical nodes, find outgoing `reads_env` edges, return target `env:*` nodes and summaries. |
| Env vars written by a script | Resolve the script file node, find outgoing `writes_env` edges, return target `env:*` nodes and metadata summaries such as scopes and observed values. |
| Host mutation categories by file | Group outgoing `mutates_host` edges from each `file:*` node by target `host.category:*`, with tool and privileged counts derived from evidence or edge metadata. |
| Python modules importing another module | Find `imports` edges from `python.module:*` to `python.module:*` or external/unknown placeholders. |
| Nix apps exposing scripts | Find `exposes_script` edges from `nix.app:*` to `file:*`, with flake ref, system, and app name parsed from source keys. |
| Blast radius for a file or symbol | Traverse canonical edges from the starting canonical key according to a query profile. Include reverse edges for dependents and forward edges for dependencies. Evidence is optional unless explain mode is requested. |
| Explain why an edge exists | Find the canonical edge by source key, kind, target key, and graph key version; join `canonical_edge_evidence`; return evidence rows with raw observation ids, paths, spans, extractor details, confidence, and selected metadata. |

Compatibility readback may also show observation-derived stable keys, but query
logic should prefer canonical keys once Phase E starts.

## Failure and Ambiguity Behavior

RepoMap must prefer explicit `dynamic:*`, `unknown:*`, or `external:*`
placeholder nodes over fabricated precision.

Malformed canonical keys fail validation with diagnostics. They are not silently
normalized.

Malformed percent escapes fail parsing. Decoders must reject incomplete escapes,
non-hex escapes, lowercase normalization mismatches when strict mode requires
uppercase output, and encoded separators used in invalid positions.

Raw observations with target values that do not pass canonical key validation
must be rebuilt from typed fields when possible. If rebuilding is impossible,
the canonicalizer emits a diagnostic and uses an explicit placeholder only when
the domain and reason are clear.

Dynamic shell commands map to `dynamic:tool:*` targets with `executes` edges
only when the source file and dynamic command evidence are clear.

Dynamic shell source paths map to `dynamic:file:*` targets with `sources` edges
only when the source file and dynamic source evidence are clear.

Unresolved imports map to `unknown:*` or `external:*` placeholders depending on
whether static analysis knows the target is external. RepoMap should not invent
local module keys for unresolved imports.

Missing files map to `unknown:file:missing-file` for relationship targets unless
a profile or retained historical run policy explicitly preserves the intended
`file:*` target with missing-file metadata.

Repo-escaping paths are validation errors for file keys. For observations that
clearly refer to an external file, canonicalization may use
`external_key("file", stable_name)` only when a stable external naming policy is
available. Otherwise it uses `unknown_key("file", "repo-escaping-path")`.

Incompatible graph key versions must be rejected by default. Compatibility
commands may parse old versions through version-specific parsers and replay raw
observations into the requested current graph version.

Conflicting evidence keeps per-evidence details, sets a conflict flag on the
canonical edge or node summary, and reports confidence as the strongest
supported confidence plus the conflict marker. A conflict does not delete
evidence.

## Rejected Alternatives

### Directly Migrate Observation-Derived Node Keys Into Canonical Keys

Rejected. Observation-derived keys contain extractor source ids, raw kinds, and
event-level identity. Canonical keys identify durable domain entities.

### Treat Raw Observation `target` as Trusted Without Validation

Rejected. Raw targets are extractor output and may be old, malformed, dynamic,
or from an earlier key grammar. Canonicalization must parse, validate, or
rebuild keys through the canonical-key module.

### Duplicate a Canonical Edge for Every Evidence Record

Rejected. Evidence multiplicity is not relationship multiplicity. Multiple
evidence records supporting the same source, kind, target, graph version, and
identity metadata collapse onto one canonical edge.

### Create Command-Invocation Nodes for Every Shell Command Line

Rejected for durable graph identity. Command invocations are evidence events.
Durable tool nodes represent tools such as `tool:nix`, and invocation details
belong in edge or evidence metadata.

### Skip Raw Observation Retention

Rejected. Replay, explainability, canonicalization bug repair, and graph key
version upgrades require retained raw observations.

### Change Storage First Before Implementing Canonicalization Tests

Rejected. Canonicalization should be a tested pure layer before storage changes.
The first target is tested examples of `list[RawObservation] -> CanonicalGraph`.

### Add MCP Before Canonical CLI and Query Behavior Is Stable

Rejected for now. MCP can expose RepoMap later, but the CLI, raw-observation
contract, canonicalizer, and storage readback should stabilize first.

## Required Examples

The examples below show raw observation to canonical nodes, canonical edge, and
evidence links. Raw observation JSON is abbreviated to the fields needed for
canonicalization.

### `file:bin/tool` Executes `tool:nix`

Raw observation:

```json
{"schema_version":1,"kind":"shell.command","path":"bin/tool","start_line":12,"end_line":12,"name":"nix build","target":"tool:nix","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","source_id":"bin/tool#call:12:nix-build","metadata":{"command":"nix","argv":["nix","build",".#checks"],"raw":"nix build .#checks"}}
```

Canonical nodes:

- `file:bin/tool`
- `tool:nix`

Canonical edge:

- `file:bin/tool --executes--> tool:nix`
- metadata: `{"command":"nix","argv":["nix","build",".#checks"]}`
- confidence summary: `heuristic`

Evidence:

- raw observation id for run ordinal N
- path `bin/tool`
- lines 12-12
- extractor `repo-shell` version `0.1.0`
- source id `bin/tool#call:12:nix-build`
- supports the canonical edge and may also support node evidence for
  `file:bin/tool`

### `scripts/build.sh` Sources `lib/common.sh`

Raw observation:

```json
{"schema_version":1,"kind":"shell.source","path":"scripts/build.sh","start_line":3,"end_line":3,"name":"source ../lib/common.sh","target":"file:lib/common.sh","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","source_id":"scripts/build.sh#source:3:lib/common.sh","metadata":{"source":"../lib/common.sh","resolved_path":"lib/common.sh","raw":"source ../lib/common.sh"}}
```

Canonical nodes:

- `file:scripts/build.sh`
- `file:lib/common.sh`

Canonical edge:

- `file:scripts/build.sh --sources--> file:lib/common.sh`
- metadata: `{"source":"../lib/common.sh","resolved_path":"lib/common.sh"}`
- confidence summary: `heuristic`

Evidence links to the edge with path `scripts/build.sh`, lines 3-3, extractor
details, source id, and raw source text.

### `scripts/build.sh` Reads `PATH`

Raw observation:

```json
{"schema_version":1,"kind":"shell.env","path":"scripts/build.sh","start_line":8,"end_line":8,"name":"PATH","target":"env:PATH","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","source_id":"scripts/build.sh#env-read:8:PATH","metadata":{"operation":"read","variable":"PATH","raw":"echo \"$PATH\""}}
```

Canonical nodes:

- `file:scripts/build.sh`
- `env:PATH`

Canonical edge:

- `file:scripts/build.sh --reads_env--> env:PATH`
- metadata: `{"operation":"read"}`
- confidence summary: `heuristic`

Evidence links line 8 in `scripts/build.sh` to the edge.

### `scripts/build.sh` Writes `FOO`

Raw observation:

```json
{"schema_version":1,"kind":"shell.env","path":"scripts/build.sh","start_line":9,"end_line":9,"name":"FOO","target":"env:FOO","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","source_id":"scripts/build.sh#env-write:9:FOO","metadata":{"operation":"write","variable":"FOO","value":"bar","scope":"shell","raw":"FOO=bar"}}
```

Canonical nodes:

- `file:scripts/build.sh`
- `env:FOO`

Canonical edge:

- `file:scripts/build.sh --writes_env--> env:FOO`
- metadata: `{"operation":"write","scope":"shell","value":"bar"}`
- confidence summary: `heuristic`

`bar` is not part of the key. Evidence links line 9 to the edge.

### `scripts/maintain.sh` Mutates `host.category:package-management`

Raw observation:

```json
{"schema_version":1,"kind":"shell.host_mutation","path":"scripts/maintain.sh","start_line":5,"end_line":5,"name":"brew install jq","target":"host.category:package-management","confidence":"heuristic","extractor":"repo-shell","extractor_version":"0.1.0","source_id":"scripts/maintain.sh#host-mutation:5:brew-install","metadata":{"tool":"brew","category":"package-management","argv":["brew","install","jq"],"effective_argv":["brew","install","jq"],"privileged":false,"reason":"brew mutating verb","raw":"brew install jq"}}
```

Canonical nodes:

- `file:scripts/maintain.sh`
- `host.category:package-management`

Canonical edge:

- `file:scripts/maintain.sh --mutates_host--> host.category:package-management`
- metadata includes `tool`, `category`, `argv`, `effective_argv`,
  `privileged`, and `reason`
- confidence summary: `heuristic`

Evidence links line 5 to the edge and preserves the classifier reason.

### Python Module `repomap_kg.cli` Imports `repomap_kg.storage`

Raw observation:

```json
{"schema_version":1,"kind":"python.import","path":"src/main/python/repomap_kg/cli.py","start_line":11,"end_line":11,"name":"repomap_kg.storage","target":"python.module:repomap_kg.storage","confidence":"extracted","extractor":"repo-python","extractor_version":"0.1.0","source_id":"src/main/python/repomap_kg/cli.py#import:11:repomap_kg.storage","metadata":{"source_module":"repomap_kg.cli","target_module":"repomap_kg.storage","raw":"from repomap_kg import storage"}}
```

Canonical nodes:

- `python.module:repomap_kg.cli`
- `python.module:repomap_kg.storage`

Canonical edge:

- `python.module:repomap_kg.cli --imports--> python.module:repomap_kg.storage`
- metadata includes import form and raw statement
- confidence summary: `extracted`

Evidence links line 11 in the defining file to the import edge.

### File Defines Python Module and Function

Raw observations:

```json
{"schema_version":1,"kind":"python.module","path":"src/main/python/repomap_kg/cli.py","start_line":1,"end_line":1,"name":"repomap_kg.cli","target":"python.module:repomap_kg.cli","confidence":"extracted","extractor":"repo-python","extractor_version":"0.1.0","source_id":"src/main/python/repomap_kg/cli.py#module:repomap_kg.cli","metadata":{"module":"repomap_kg.cli"}}
```

```json
{"schema_version":1,"kind":"python.function","path":"src/main/python/repomap_kg/cli.py","start_line":40,"end_line":55,"name":"main","target":"python.function:repomap_kg.cli:main","confidence":"extracted","extractor":"repo-python","extractor_version":"0.1.0","source_id":"src/main/python/repomap_kg/cli.py#function:40:main","metadata":{"module":"repomap_kg.cli","function":"main"}}
```

Canonical nodes:

- `file:src/main/python/repomap_kg/cli.py`
- `python.module:repomap_kg.cli`
- `python.function:repomap_kg.cli:main`

Canonical edges:

- `file:src/main/python/repomap_kg/cli.py --defines--> python.module:repomap_kg.cli`
- `file:src/main/python/repomap_kg/cli.py --defines--> python.function:repomap_kg.cli:main`

Evidence links the module observation and function observation to their
respective `defines` edges. Function line numbers are evidence, not key
segments.

### Nix App Exposes `bin/tool`

Raw observation:

```json
{"schema_version":1,"kind":"nix.app","path":"flake.nix","start_line":20,"end_line":24,"name":"tool","target":"nix.app:repo-map:aarch64-darwin:tool","confidence":"extracted","extractor":"repo-nix","extractor_version":"0.1.0","source_id":"flake.nix#app:aarch64-darwin:tool","metadata":{"flake_ref":"repo-map","system":"aarch64-darwin","app":"tool","program":"bin/tool","program_path":"bin/tool"}}
```

Canonical nodes:

- `file:flake.nix`
- `nix.app:repo-map:aarch64-darwin:tool`
- `file:bin/tool`

Canonical edges:

- `file:flake.nix --defines--> nix.app:repo-map:aarch64-darwin:tool`
- `nix.app:repo-map:aarch64-darwin:tool --exposes_script--> file:bin/tool`

Evidence links the Nix app observation to both canonical edges. The app exposes
a script; it is not the same entity as the script file.

### Dynamic Shell Source Path

Raw observation:

```json
{"schema_version":1,"kind":"shell.source","path":"scripts/build.sh","start_line":4,"end_line":4,"name":"source \"$LIB_DIR/common.sh\"","target":"dynamic:file:shell-source-expanded-from-variable","confidence":"unknown","extractor":"repo-shell","extractor_version":"0.1.0","source_id":"scripts/build.sh#source:4:dynamic","metadata":{"source":"$LIB_DIR/common.sh","raw":"source \"$LIB_DIR/common.sh\"","dynamic_reason":"shell-source-expanded-from-variable"}}
```

Canonical nodes:

- `file:scripts/build.sh`
- `dynamic:file:shell-source-expanded-from-variable`

Canonical edge:

- `file:scripts/build.sh --sources--> dynamic:file:shell-source-expanded-from-variable`
- metadata includes raw source text and dynamic reason
- confidence summary: `unknown`

Evidence preserves the dynamic source expression. RepoMap does not guess
`file:lib/common.sh`.

### Variable-Derived Command

Raw observation:

```json
{"schema_version":1,"kind":"shell.command","path":"scripts/build.sh","start_line":10,"end_line":10,"name":"$RUNNER test","target":"dynamic:tool:shell-variable-command","confidence":"unknown","extractor":"repo-shell","extractor_version":"0.1.0","source_id":"scripts/build.sh#call:10:dynamic","metadata":{"raw":"$RUNNER test","dynamic_reason":"shell-variable-command"}}
```

Canonical nodes:

- `file:scripts/build.sh`
- `dynamic:tool:shell-variable-command`

Canonical edge:

- `file:scripts/build.sh --executes--> dynamic:tool:shell-variable-command`
- metadata includes raw command text and dynamic reason
- confidence summary: `unknown`

Evidence links line 10 to the dynamic command edge. RepoMap does not invent a
precise `tool:*` target.
