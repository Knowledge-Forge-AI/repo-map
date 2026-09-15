# ADR 0010: Structured Configuration Graph Model

## Status

Accepted

## Date

2026-06-30

## Context

RepoMap now extracts and canonicalizes facts from code, shell observations,
Python, Nix, and Markdown documentation. Canonical storage and readback are the
preferred public query model, while Phase F3 pauses further legacy-readback
default migrations before higher-risk commands such as neighborhood and
file-neighborhood.

Structured configuration is the next high-value source of repository knowledge.
Codex and MCP behavior is driven by JSON and TOML configuration. Project graphs
are more useful when they can show settings, registered tools, MCP servers,
model or profile names, path aliases, prompt metadata, and machine-readable
registries. RepoMap should make those facts queryable through the same raw
observation -> evidence -> canonical graph pipeline used elsewhere.

Configuration parsing must remain static and deterministic. RepoMap must not
execute commands found in configuration, expand shell variables, fetch URLs,
validate external schemas, or read/decrypt secrets in order to build graph
facts.

## Decision

RepoMap will model structured configuration through deterministic raw
observations and a compact canonical graph layer.

The first structured configuration graph will cover:

- JSON documents;
- JSONL records;
- JSONC documents when a conservative parser can normalize them safely; and
- TOML documents parsed with the Python standard library where available.

The model adds graph key version 1 namespaces for configuration documents and
configuration paths. It also registers a narrow `references` edge kind for
syntactic references from configuration values to durable targets such as files,
tools, environment variables, external URLs, other configuration paths, or
explicit unknown/dynamic placeholders.

The model does not interpret every application-specific configuration format.
It records structural facts and conservative references, preserving evidence so
later project-specific logic can explain or refine behavior without losing the
original observation.

## Scope

In scope:

- `.json`;
- `.jsonl`;
- `.jsonc`;
- `.toml`;
- selected extensionless config files only when discovery already classifies
  them safely;
- JSON objects, arrays, and scalar leaves;
- JSONL records, one JSON value per line;
- JSONC comments and trailing commas when a conservative scanner can support
  them;
- TOML tables, dotted keys, arrays, arrays of tables, and scalar leaves;
- safe structural paths inside configuration trees; and
- conservative reference detection for files, tools, environment variables,
  external URLs, and related configuration paths.

Out of scope:

- executing commands from config;
- expanding shell variables;
- fetching URLs;
- validating external schemas;
- interpreting every app-specific config format semantically;
- decrypting or reading secrets;
- storing secret values;
- cross-project config resolution;
- changing MCP write behavior;
- Phase F migration;
- Shell/Bats/AWK extraction; and
- storage migrations.

## Raw Observation Kinds

Configuration extractors emit raw observations with the standard schema fields:
`kind`, `source_id`, `path`, optional line span, optional `name`, optional
`target`, `confidence`, `extractor`, `extractor_version`, and `metadata`.

Use `confidence="extracted"` when the value comes from strict deterministic
parsing. Use `confidence="heuristic"` for conservative reference detection or
for JSONC normalization when comments/trailing commas are stripped by a simple
scanner. Use `confidence="unknown"` for parse errors or unresolved references.

### `config.document`

Represents one structured configuration file.

Required fields:

- `kind`: `config.document`
- `path`: repository-relative config file path
- `source_id`: stable extractor-local id such as `<path>#config-document`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `format`: `json`, `jsonl`, `jsonc`, or `toml`;
- `parser`: parser family and mode, such as `stdlib-json`,
  `jsonc-conservative`, or `stdlib-tomllib`;
- `top_level_type`: `object`, `array`, `string`, `number`, `boolean`, `null`,
  or `mixed-jsonl`;
- `document_role`: optional shallow role such as `codex-config`,
  `mcp-config`, `package-metadata`, `tool-config`, `registry`, `log`, or
  `config`;
- `path_count`: optional count of emitted `config.path` observations;
- `record_count`: optional count of parseable JSONL records; and
- `parse_error_count`: optional count of parse errors.

Canonicalization creates a `config.document:*` node and a `file:* --defines-->
config.document:*` edge.

### `config.path`

Represents one stable structural path inside the config tree.

Required fields:

- `kind`: `config.path`
- `path`: repository-relative config file path
- `source_id`: stable extractor-local id such as `<path>#config-path:<pointer>`
- `name`: normalized pointer string
- `target`: the `config.path:*` key when the extractor can build it, otherwise
  omitted or an explicit placeholder
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `format`;
- `pointer`: normalized config pointer;
- `display_path`: human-readable path such as `/mcp_servers/repomap/command`
  or `mcp_servers.repomap.command`;
- `value_type`: `object`, `array`, `string`, `number`, `boolean`, or `null`;
- `container_type`: parent container type when known;
- `redacted`: boolean;
- `redaction_reason`: optional reason when redacted;
- `value_summary`: safe summary for non-secret scalar values;
- `array_policy`: `stable-name`, `index-evidence-only`, `summary-only`, or
  omitted; and
- `stable_member_key`: optional object member key used for array-of-objects
  identity when accepted.

Canonicalization creates a `config.path:*` node and a `file:* --defines-->
config.path:*` edge. The config document may also define or own the path through
metadata, but the first canonical edge remains file-to-path via `defines` for
consistency with documentation and symbol facts.

### `config.reference`

Represents a config value that appears to syntactically reference another
durable target.

Required fields:

- `kind`: `config.reference`
- `path`: repository-relative config file path
- optional `start_line` and `end_line`
- `name`: source pointer or reference label
- `target`: resolved canonical target key or explicit placeholder
- `source_id`: stable extractor-local id such as
  `<path>#config-reference:<pointer>:<ordinal>`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `format`;
- `pointer`: normalized config pointer containing the value;
- `raw_key`: original object key or TOML key segment when useful;
- `reference_kind`: `file`, `tool`, `env`, `external.url`, `config.path`,
  `config.document`, `unknown`, or `dynamic`;
- `raw_value_summary`: safe summarized value, redacted when secret-prone;
- `redacted`: boolean;
- `redaction_reason`;
- `resolution_reason`: how the target was resolved or why it was not;
- `source_document_key`: optional `config.document:*` key; and
- `source_path_key`: optional `config.path:*` key.

Canonicalization creates a `references` edge from the source `config.path:*`
node to the resolved target node. When the source path cannot safely become a
canonical path node, the observation remains raw/evidence only and emits a
diagnostic instead of fabricating precision.

### `config.jsonl_record`

Represents one parseable JSONL record line.

Required fields:

- `kind`: `config.jsonl_record`
- `path`: repository-relative JSONL file path
- `start_line`
- `end_line`
- `source_id`: stable extractor-local id such as `<path>#jsonl-record:<line>`
- `confidence`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `format`: `jsonl`;
- `record_index`: zero-based parseable record index;
- `line_number`: evidence line number, not canonical identity;
- `top_level_type`;
- `safe_keys`: selected safe top-level object keys;
- `redacted_keys`: secret-prone keys redacted from summaries; and
- `value_summary`: optional safe summary for scalar records.

`config.jsonl_record` is raw/evidence oriented in the first implementation. It
may support document metadata and config paths, but RepoMap should not create a
durable `config.record:*` canonical key from line or record number in CFG1.

### `config.parse_error`

Represents a parser failure for a document or JSONL line.

Required fields:

- `kind`: `config.parse_error`
- `path`: repository-relative config file path
- optional `start_line` and `end_line`
- `source_id`: stable extractor-local id such as
  `<path>#config-parse-error:<line-or-document>`
- `confidence`: usually `unknown`
- `extractor`
- `extractor_version`
- `metadata`

Metadata:

- `format`;
- `parser`;
- `error_kind`: `malformed-json`, `malformed-jsonc`, `malformed-jsonl-line`,
  `malformed-toml`, `unsupported-jsonc-construct`, or `unsupported-format`;
- `message_summary`: safe parser error summary;
- `line_number`: evidence only when known;
- `column_number`: evidence only when known; and
- `recovered`: boolean indicating whether other records or paths were still
  emitted.

`config.parse_error` remains raw/evidence only unless a later ADR accepts
diagnostic nodes. It must not create a fake canonical config node.

## Canonical Key Namespaces

The following graph key version 1 namespace additions are accepted:

```text
config.document:<encoded-file-key>
config.path:<encoded-file-key>:<encoded-config-pointer>
```

`<encoded-file-key>` is the percent-encoded canonical `file:*` key string. For
example, the file key `file:.codex/config.toml` becomes one encoded segment
inside the config key.

`<encoded-config-pointer>` is the percent-encoded normalized config pointer.
Pointer strings are durable structural identities, not evidence locations.

Examples:

```text
config.document:file%3A.codex%2Fconfig.toml
config.path:file%3A.codex%2Fconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand
config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fprojects%2Frepo-map%2Fpg_database
```

The following namespace is deliberately deferred:

```text
config.record:<encoded-file-key>:<record-identity>
```

JSONL line numbers and record indexes are evidence locations by default, not
durable entities. A later ADR may accept `config.record:*` when a record has a
stable object key, event id, or schema-defined identity that does not depend on
line number.

Canonical config keys must not include:

- raw values;
- secret values;
- line numbers;
- source ids;
- extractor names or versions;
- content hashes; or
- parser diagnostics.

Adding `config.document:*` and `config.path:*` is a compatible graph key version
1 namespace addition under ADR 0002. It does not require a new graph key
version because it does not change existing namespace grammar or edge identity.

## Pointer And Path Identity

RepoMap will use one normalized pointer grammar for JSON, JSONC, JSONL record
objects when path observations are emitted, and TOML.

The normalized pointer grammar is JSON Pointer style:

```text
/segment/segment/segment
```

Rules:

- the empty pointer identifies the whole document but should usually be modeled
  as `config.document:*`, not `config.path:*`;
- object keys preserve case and exact spelling after parser normalization;
- JSON Pointer escapes `~0` and `~1` are used inside the pointer before graph
  key percent encoding;
- TOML dotted keys and table paths are translated into pointer segments;
- TOML arrays of tables append an array member segment only when the member has
  stable identity as described below;
- pointer strings use POSIX-style `/` separators regardless of platform; and
- malformed pointer escapes produce diagnostics instead of guessed keys.

Array policy:

- ordinary arrays of scalars produce one `config.path` summary for the array
  itself and may include safe scalar summaries in metadata;
- ordinary arrays of objects do not use numeric indexes for canonical path
  identity in CFG1;
- array member line/index positions remain evidence metadata;
- arrays of objects may emit member `config.path` nodes only when a stable
  member key such as `name`, `id`, `key`, or `project` is present and the
  extractor can apply that policy deterministically; and
- when no stable member key exists, nested array entries remain raw/evidence
  only or contribute to array summary metadata.

Numeric array indexes are not allowed in canonical `config.path:*` keys for
ordinary arrays in CFG1. This avoids making durable graph identity depend on
file ordering.

## Edge Vocabulary

Existing `defines` edges are used for structural definitions:

```text
file:* --defines--> config.document:*
file:* --defines--> config.path:*
```

CFG0 also accepts a new registered edge kind:

```text
references
```

Direction:

```text
config.path:* --references--> file:* | tool:* | env:* | external.url:* |
  config.path:* | config.document:* | unknown:* | dynamic:* | external:*
```

Meaning:

A structured configuration value syntactically references another durable
target. The edge does not mean runtime dependency, execution, endorsement,
ownership, or successful resolution. It only records that a deterministic
extractor found a conservative reference at a config path.

Do not reuse Markdown `links_to` for structured config. `links_to` remains the
Markdown/documentation link relationship from ADR 0008. Config references are
broader and less document-specific, so a separate `references` edge keeps query
semantics clear.

If CFG1 cannot implement `references` with enough precision, it may emit
`config.reference` raw observations first and defer canonical `references`
edges. It must not invent a broader edge kind.

## Secret And Value Redaction

RepoMap must never put config values or secret values in canonical keys.

Secret-prone key names include case-insensitive matches and separator variants
for:

- `token`
- `secret`
- `password`
- `passwd`
- `api_key`
- `apikey`
- `credential`
- `private_key`
- `access_key`
- `refresh_token`
- `bearer`
- `auth`

Redaction behavior:

- secret-prone scalar values are redacted from summary metadata;
- secret-prone object or array values are summarized by type and redaction
  reason only;
- metadata may preserve `value_type`, `redacted=true`, `redaction_reason`, and
  safe key names;
- evidence may preserve path, line span, parser, extractor, and confidence, but
  not the secret value;
- non-reversible value hashes are deferred; and
- redaction applies before canonicalization and before serialization of
  expected golden fixtures.

Non-secret values may appear as short `value_summary` metadata only when they
are small, printable, and not under a secret-prone key path. Values never
participate in canonical identity.

## Reference Detection

Reference detection must be conservative. RepoMap should prefer explicit
`unknown:*`, `dynamic:*`, or `external:*` placeholders over fabricated
precision.

### File Paths

Relative paths may reference `file:*` only when they normalize inside the
repository and are not obviously dynamic. Relative path targets should use
repository-relative POSIX paths.

Absolute paths should become `external:*` or `unknown:*` unless a profile
explicitly allows a stable mapping. Repo-escaping paths become unknown
placeholders such as `unknown:file:repo-escaping-config-reference` unless a
stable external path policy exists.

Values that contain shell variables, home-directory expansion, glob patterns, or
template markers should become `dynamic:file:*` or remain raw-only.

### URLs

`http`, `https`, and `mailto` URLs may target `external.url:*` using the
namespace accepted by ADR 0008. RepoMap must not fetch URLs.

Malformed URLs become `unknown:external.url:*` or raw-only diagnostics rather
than guessed targets.

### Commands And Tools

Fields named `command`, `cmd`, `executable`, or `program` may reference
`tool:*` only when the value is a simple static command name or stable path to a
tool. Arrays under fields such as `args` may reference `tool:*` only when the
first element is statically and unambiguously the command.

RepoMap must not execute command values. Shell fragments, command
substitutions, interpolated strings, or compound commands become dynamic or
unknown placeholders.

### Environment Variables

Strings such as `$FOO` and `${FOO}` may reference `env:FOO` when the variable
name is syntactically valid and the surrounding value makes the reference
clear. Object keys named `env`, `environment`, or `env_vars` may contain
environment variable names when the structure is deterministic.

Dynamic variable names or interpolated names become `dynamic:env:*` or
`unknown:env:*`.

### MCP Servers, Models, Profiles, And Project Aliases

MCP server names, model names, profile names, prompt aliases, and project
aliases are useful metadata. They should usually become `config.path:*` nodes
and `config.reference` metadata first.

CFG0 does not add durable namespaces such as `mcp.server:*`, `model:*`, or
`profile:*`. A later ADR may add them if query pressure proves that these are
domain entities rather than configuration paths.

## Format-Specific Rules

### JSON

JSON should be parsed with Python's standard `json` module.

Emit:

- one `config.document`;
- `config.path` observations for stable object keys and safe structural paths;
- `config.reference` observations for conservative references; and
- `config.parse_error` when parsing fails.

### JSONL

JSONL should be parsed line by line. Each non-empty line is one JSON value.

Rules:

- a malformed line emits `config.parse_error`;
- one malformed line must not prevent valid lines from being observed;
- parseable lines emit `config.jsonl_record`;
- object records may emit `config.path` observations only for stable top-level
  structure when doing so does not depend on line number as identity; and
- record line number and record index are evidence, not durable canonical
  identity in CFG1.

### JSONC

JSONC support is intentionally conservative.

The first implementation may strip:

- line comments outside strings;
- block comments outside strings; and
- trailing commas in objects or arrays.

Unsupported constructs, ambiguous comments, malformed string/comment state, or
normalization failures emit `config.parse_error`. RepoMap must not claim full
JSONC compatibility until tests cover the supported behavior.

### TOML

TOML should be parsed with Python standard-library `tomllib` where available.

Rules:

- table paths become pointer segments;
- dotted keys are normalized into the same pointer grammar;
- arrays are summarized according to the array policy;
- arrays of tables may use stable member keys only when deterministic;
- scalar leaves may emit `config.path` observations with safe summaries; and
- parse failures emit `config.parse_error`.

## Docs And Codex-VC Policy

Project graphs should include project-local config files when discovery
classifies them in scope.

The `codex-vc` graph should include Codex library and configuration files such
as MCP registry JSON, Codex config TOML where present in the indexed repository,
skills metadata, prompt metadata, and machine-readable state that is safe to
index.

Duplicate config content across repository-scoped graphs is acceptable.
Repository graphs should be self-contained, while the `codex-vc` graph acts as
Codex's library/catalog graph.

Symlink traversal requires explicit profile policy, consistent with ADR 0008.
RepoMap must not silently follow symlinks out of a repository to harvest config
from another project or from private home-directory state.

## Required Tests For Implementation

CFG1/CFG2 implementation must include:

- unit tests for JSON object and scalar paths;
- unit tests for arrays and the array identity policy;
- unit tests for mixed valid and malformed JSONL lines;
- unit tests for JSONC comments and trailing commas;
- unit tests for TOML tables, dotted keys, arrays, and arrays of tables;
- unit tests for redaction of secret-prone keys and values;
- unit tests for file, environment variable, tool, and URL reference detection;
- canonicalization tests for `config.document` and `config.path`;
- canonicalization tests for `references` if canonical references are
  implemented;
- discovery fixtures containing JSON, JSONL, JSONC, and TOML;
- storage integration readback tests for config nodes and edges; and
- an explain-edge test for one config `references` edge if canonical
  `references` edges are implemented.

Tests must prove that secret values do not appear in canonical keys, node
metadata, edge metadata, golden fixtures, or serialized readback output.

## Rejected Alternatives

### Store Arbitrary Config Values As Canonical Nodes

Rejected. Arbitrary values are not durable domain entities. They are metadata
or evidence, and many values are secrets or environment-specific details.

### Put Values Or Secrets In Canonical Keys

Rejected. Canonical keys identify durable entities, not settings snapshots.
Putting values in keys would leak secrets and create churn for ordinary config
edits.

### Execute Commands Found In Config

Rejected. RepoMap extraction is static and deterministic. Command execution
belongs outside the extractor boundary.

### Use Line Numbers As Config Path Identity

Rejected. Line numbers are evidence locations and change with formatting.
Canonical config identity uses structural pointers.

### Treat All Strings As References

Rejected. Most strings are labels, descriptions, values, or application data.
Reference detection must be conservative and field-aware.

### Fetch URLs To Classify Them

Rejected. URL fetching introduces network dependency, nondeterminism, and
privacy risks. URLs may be modeled as external references without fetching.

### Make The JSONC Parser Too Permissive Without Tests

Rejected. JSONC support should be conservative and explicit. Ambiguous syntax
must produce parse errors instead of guessed graph facts.

### Migrate Phase F As Part Of Config Extraction

Rejected. Structured configuration extraction is a graph-coverage phase. It
does not change public readback defaults, legacy compatibility, MCP behavior,
or storage retirement policy.
