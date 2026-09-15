# ADR 0002: Canonical Key Grammar and Relationship Vocabulary

## Status

Accepted

## Date

2026-06-29

## Context

ADR 0001 accepts the long-term distinction between raw observations, evidence
records, canonical nodes, and edges. Raw observations describe what extractors
saw. Evidence records preserve where and how they saw it. Canonical graph keys
must identify durable repository entities, not evidence locations, extractor
versions, or raw observation source IDs.

Good canonical keys identify stable entities:

- `file:bin/tool`
- `tool:nix`
- `env:PATH`
- `python.module:repomap_kg.cli`

Bad canonical keys smuggle evidence or extraction events into identity:

- `file:bin/tool#line:12`
- `shell.command:bin/tool#call:12:nix-build`
- `env:FOO=value:bar`
- `repo-shell:0.1.0:some-source-id`

This ADR defines the first canonical node key grammar, normalization rules,
edge vocabulary, edge identity rules, compatibility plan, examples, and
rejected alternatives.

## Decision

RepoMap will use versioned canonical graph keys with explicit namespaces,
percent-escaped segments, and a registered relationship vocabulary.

Version 1 graph keys use this general shape:

```text
<namespace>:<segment>[:<segment>...]
```

For file paths only, the namespace is followed by a normalized POSIX
repository-relative path:

```text
file:<path-component>[/<path-component>...]
```

Each segment or path component is percent-encoded after normalization. The
separator characters `:` and `/` are structural and are not part of unescaped
segment content. Literal `:`, `/`, `%`, `#`, spaces, quotes, and other reserved
characters inside a segment are encoded.

Canonical edge kinds are registered strings with fixed directionality. Extractors
must map observations into the registry instead of inventing arbitrary edge
kinds in canonical graph output.

## Canonical Node Key Grammar

The following namespaces are accepted for graph key version 1.

### File Keys

```text
file:<repo-relative-posix-path>
```

Examples:

- `file:bin/tool`
- `file:scripts/build.sh`
- `file:lib/common.sh`
- `file:docs/adr/2026/06/0001-graph-identity-model.md`

File keys identify repository files or directories by normalized
repository-relative path. They never include line numbers, columns, excerpts,
content hashes, extractor names, source IDs, or display labels.

### Tool Keys

```text
tool:<tool-name>
```

Examples:

- `tool:nix`
- `tool:python3`
- `tool:ruby`
- `tool:brew`
- `tool:launchctl`

Tool keys identify durable command/tool names, not individual invocations.
Invocation arguments belong in edge metadata or evidence metadata.

### Environment Variable Keys

```text
env:<variable-name>
```

Examples:

- `env:PATH`
- `env:FOO`
- `env:NIX_PATH`

Environment variable keys are case-sensitive. Variable values are never part of
the key. Values, scope, and assignment form belong in edge metadata or evidence
metadata.

### Shell Function Keys

```text
shell.function:<file-key-segment>:<function-name>
```

Examples:

- `shell.function:file%3Ascripts%2Fbuild.sh:main`
- `shell.function:file%3Alib%2Fcommon.sh:log_info`

The first segment after `shell.function:` is the canonical file key encoded as a
segment. This keeps function identity scoped to the file that defines it while
preserving the general `:` segment separator. Function names are shell
identifiers or percent-escaped dynamic names when a parser can determine a
stable name.

### Python Keys

```text
python.module:<qualified-module-name>
python.class:<qualified-module-name>:<qualified-class-name>
python.function:<qualified-module-name>:<qualified-function-name>
python.method:<qualified-module-name>:<qualified-class-name>:<method-name>
```

Examples:

- `python.module:repomap_kg.cli`
- `python.module:repomap_kg.storage`
- `python.class:repomap_kg.storage:StorageSchemaError`
- `python.function:repomap_kg.cli:main`
- `python.method:repomap_kg.storage:StorageSummaryRecord:to_dict`

Python qualified names are case-sensitive and use Python's `.` package/module
separator inside a segment. Nested classes and functions use `.` inside the
class or function segment when the parser exposes a stable qualified name.

### Nix Keys

```text
nix.app:<flake-ref>:<system>:<name>
nix.package:<flake-ref>:<system>:<name>
nix.devShell:<flake-ref>:<system>:<name>
nix.check:<flake-ref>:<system>:<name>
nix.output:<flake-ref>:<output-path>
```

Examples:

- `nix.app:repo-map:aarch64-darwin:tool`
- `nix.package:repo-map:aarch64-darwin:default`
- `nix.devShell:repo-map:aarch64-darwin:default`
- `nix.check:repo-map:aarch64-darwin:unit`
- `nix.output:repo-map:packages%2Faarch64-darwin%2Fdefault`

`flake-ref` is a stable repository or flake identity chosen by the Nix
extractor. For the current repository, the preferred local flake ref is the
repository identity, such as `repo-map`, not an absolute checkout path.

### Ruby Keys

```text
ruby.module:<qualified-module-name>
ruby.class:<qualified-class-name>
ruby.method:<owner-qualified-name>:<method-name>
```

Examples:

- `ruby.module:RepoMap`
- `ruby.class:RepoMap%3A%3ARunner`
- `ruby.method:RepoMap%3A%3ARunner:call`

Ruby qualified names are case-sensitive. Ruby's source-level `::` separator
stays conceptually inside the owner segment and is encoded as `%3A%3A` in graph
keys.

### Host Category Keys

```text
host.category:<category>
```

Examples:

- `host.category:package-management`
- `host.category:service-management`
- `host.category:system-activation`
- `host.category:filesystem-mutation`

Host category nodes represent categories of host mutation, not one command
invocation or one host object.

### Unknown, External, and Dynamic Placeholder Keys

RepoMap must represent unresolved targets without inventing false precision.
Version 1 uses explicit placeholder namespaces:

```text
unknown:<domain>:<reason>
external:<domain>:<stable-name>
dynamic:<domain>:<reason>
```

Examples:

- `unknown:file:missing-profile-context`
- `external:tool:systemctl`
- `dynamic:file:shell-source-expanded-from-variable`
- `dynamic:tool:shell-command-substitution`

Use `unknown` when a target exists conceptually but RepoMap cannot classify it.
Use `external` when the target is outside the indexed repository but has a
stable public name. Use `dynamic` when source code constructs the target at
runtime and static resolution would be dishonest.

## Key Normalization Rules

### Repository-Relative Paths

File paths are normalized before key construction:

- resolve against the repository root;
- reject paths that escape the repository root;
- use repository-relative paths;
- remove `.` path components;
- collapse non-leading `..` only when it remains inside the repository root;
- preserve symlink path spelling as observed unless a future profile explicitly
  declares canonical symlink resolution; and
- use POSIX `/` separators on every host platform.

The root directory itself, if needed, is represented as `file:.`.

### Case Sensitivity

Canonical keys are case-sensitive by default. RepoMap does not fold file paths,
environment variable names, language symbols, Nix names, Ruby constants, or
tool names. A future filesystem profile may add display or alias metadata for
case-insensitive filesystems, but it must not silently rewrite canonical keys.

### Escaping

Graph key version 1 uses uppercase RFC 3986 percent encoding per key segment.
The unescaped safe set inside a segment is:

```text
A-Z a-z 0-9 - . _ ~
```

For file keys, `/` remains the path component separator. Each path component is
escaped independently, so a literal slash in a path component, if a platform or
archive format permits one, is encoded as `%2F`.

For non-file keys, `:` is the segment separator. Any literal `:` inside segment
content is encoded as `%3A`.

Required examples:

- space: `My Tool` becomes `My%20Tool`
- colon: `foo:bar` becomes `foo%3Abar`
- hash: `app#debug` becomes `app%23debug`
- double quote: `"quoted"` becomes `%22quoted%22`
- single quote: `Bob's` becomes `Bob%27s`
- slash inside a non-file segment: `scripts/tool` becomes `scripts%2Ftool`
- percent: `100%` becomes `100%25`

Percent encoders must use uppercase hex digits. Decoders must reject malformed
percent escapes rather than guessing.

### No Evidence Fields in Canonical Keys

Line numbers, column numbers, byte offsets, extractor names, extractor
versions, raw observation `source_id` values, confidence values, excerpts, and
content hashes are not allowed in canonical keys.

Those fields belong in evidence records, node metadata, edge metadata, or run
metadata. A canonical key may include a language-level qualified name that
contains digits as normal source text, but it must not include a source
location merely to force uniqueness.

## Canonical Edge Vocabulary

The initial edge registry is:

| Edge kind | Direction | Meaning |
| --- | --- | --- |
| `defines` | file -> symbol | A file defines a module, class, function, method, shell function, Nix output, or Ruby symbol. |
| `executes` | file -> tool | A file or script executes a durable tool command. |
| `sources` | file -> file | A shell file statically sources another repository file. |
| `reads_env` | file -> env | A file reads an environment variable. |
| `writes_env` | file -> env | A file writes an environment variable. |
| `mutates_host` | file -> host.category | A file contains a command that mutates a host category. |
| `imports` | python.module -> python.module | A Python module imports another Python module. |
| `exposes_script` | nix.app -> file | A Nix app exposes a repository script or executable file. |
| `depends_on` | nix.output -> package/script/file | A Nix output depends on a package, script, or file when statically known. |
| `wraps` | file -> python/ruby/nix symbol or output | A shell wrapper invokes a Python, Ruby, or Nix implementation when statically detectable. |
| `tests` | test file -> source file | A test file tests a source file when known later. |

`package/script/file` in the `depends_on` target column means one of:

- `nix.package:*`
- `file:*`
- `python.module:*`, `python.function:*`, or related implementation symbols
- `ruby.module:*`, `ruby.class:*`, or `ruby.method:*`
- `tool:*` only when the Nix output depends on an external tool by stable name

Extractors may emit raw observation `kind` values that are more specific than
these canonical edge kinds. Canonicalization maps them into this registry.

## Edge Identity Rules

Canonical edge identity is stable when these fields are stable:

- graph key version;
- repository identity;
- source canonical node key;
- edge kind;
- target canonical node key; and
- disambiguating edge metadata, only when the relationship would otherwise
  collapse incorrectly.

Non-disambiguating metadata never participates in edge identity. Examples:

- `writes_env` value metadata does not disambiguate the `file -> env` edge by
  default; multiple assignments to `FOO` collapse onto one edge with multiple
  evidence records and summarized metadata.
- `executes` argv metadata may disambiguate only when RepoMap intentionally
  models different stable subcommands as distinct relationships. For version 1,
  `file:bin/tool --executes--> tool:nix` collapses across `nix build` and
  `nix flake check`; subcommands remain evidence or edge metadata.
- `mutates_host` category is represented by the target
  `host.category:<category>`, so command names and arguments do not
  disambiguate canonical edge identity.

Multiple evidence records collapse onto one canonical edge when they support
the same source node, edge kind, target node, graph key version, repository, and
identity-disambiguating metadata. The edge stores or can derive an evidence set
rather than duplicating the canonical relationship.

When evidence records disagree on confidence, RepoMap summarizes confidence
conservatively:

- `manual` is strongest when the user or profile explicitly asserts the edge;
- `extracted` beats `heuristic` for the same relationship;
- `heuristic` beats `unknown`;
- conflicting evidence should preserve per-evidence confidence and expose the
  edge confidence as the strongest supported confidence plus a conflict flag
  when contradictory evidence exists.

Unknown or dynamic targets must use placeholder nodes. Do not synthesize a
precise-looking `file:*`, `tool:*`, or language symbol key from unresolved
runtime text. For example, a shell source path built from `$ROOT/lib.sh` should
produce an edge to `dynamic:file:shell-source-expanded-from-variable`, not to a
guessed file.

## Versioning and Compatibility

### Graph Key Version

Storage should include `graph_key_version` for canonical nodes and canonical
edges before canonical storage becomes a public compatibility promise. Version
1 is the grammar defined by this ADR.

Raw observations keep their own `schema_version`. Replaying old raw
observations through a newer normalizer may produce newer canonical keys and
edges, because raw observations are extraction facts, not the canonical graph
contract.

### Grammar Changes

Any incompatible key grammar change must create a new `graph_key_version`.
Compatible additions, such as a new namespace or edge kind, may remain in the
same version if existing keys keep the same meaning and parse result.

Examples of incompatible changes:

- changing escaping semantics;
- changing path normalization;
- changing a namespace's required segment order; or
- changing edge identity fields for an existing edge kind.

### Compatibility Views

The current storage shape uses observation-derived nodes such as
`node:<path>:<kind>:<source_id>`. Compatibility views should exist while
canonical storage is introduced:

- an observation-node view exposing current source-node rows for existing
  readback commands;
- a canonical-node view exposing graph version 1 keys when available;
- an edge view that can show both observation-derived edge stable keys and
  canonical edge keys;
- query output fields that distinguish `node_stable_key` from
  `canonical_node_key`; and
- migration or replay tooling that can rebuild canonical graph rows from raw
  observation JSONL.

Compatibility views may be removed only after public commands no longer depend
on observation-derived node identity.

## Examples

### `file:bin/tool` Executes `tool:nix`

Canonical nodes:

- `file:bin/tool`
- `tool:nix`

Canonical edge:

- kind: `executes`
- source: `file:bin/tool`
- target: `tool:nix`
- identity fields: graph key version, repository, source, kind, target
- metadata example: `{"argv":["nix","build",".#checks"],"command":"nix"}`
- evidence example: line 12 in `bin/tool`

### `scripts/build.sh` Sources `lib/common.sh`

Canonical nodes:

- `file:scripts/build.sh`
- `file:lib/common.sh`

Canonical edge:

- kind: `sources`
- source: `file:scripts/build.sh`
- target: `file:lib/common.sh`
- evidence example: `source ../lib/common.sh` in `scripts/build.sh`

### `scripts/build.sh` Reads `PATH`

Canonical nodes:

- `file:scripts/build.sh`
- `env:PATH`

Canonical edge:

- kind: `reads_env`
- source: `file:scripts/build.sh`
- target: `env:PATH`
- metadata example: `{"operation":"read"}`

### `scripts/build.sh` Writes `FOO`

Canonical nodes:

- `file:scripts/build.sh`
- `env:FOO`

Canonical edge:

- kind: `writes_env`
- source: `file:scripts/build.sh`
- target: `env:FOO`
- metadata example: `{"operation":"write","scope":"shell","value":"bar"}`

`bar` is metadata, not key material. The key is `env:FOO`, not
`env:FOO=value:bar`.

### Python Module `repomap_kg.cli` Imports `repomap_kg.storage`

Canonical nodes:

- `python.module:repomap_kg.cli`
- `python.module:repomap_kg.storage`

Canonical edge:

- kind: `imports`
- source: `python.module:repomap_kg.cli`
- target: `python.module:repomap_kg.storage`
- evidence example: `from repomap_kg import storage`

### Python File Defines Module, Class, and Function

For file `src/main/python/repomap_kg/cli.py`:

Canonical nodes:

- `file:src/main/python/repomap_kg/cli.py`
- `python.module:repomap_kg.cli`
- `python.class:repomap_kg.cli:CliError`
- `python.function:repomap_kg.cli:main`

Canonical edges:

- `file:src/main/python/repomap_kg/cli.py --defines--> python.module:repomap_kg.cli`
- `file:src/main/python/repomap_kg/cli.py --defines--> python.class:repomap_kg.cli:CliError`
- `file:src/main/python/repomap_kg/cli.py --defines--> python.function:repomap_kg.cli:main`

Line numbers for the class and function definitions are evidence locations,
not key segments.

### Nix App Exposes `bin/tool`

Canonical nodes:

- `nix.app:repo-map:aarch64-darwin:tool`
- `file:bin/tool`

Canonical edge:

- kind: `exposes_script`
- source: `nix.app:repo-map:aarch64-darwin:tool`
- target: `file:bin/tool`
- metadata example: `{"system":"aarch64-darwin","program":"bin/tool"}`

### Dynamic Shell Source Path

Source:

```sh
source "$LIB_DIR/common.sh"
```

Canonical nodes:

- `file:scripts/build.sh`
- `dynamic:file:shell-source-expanded-from-variable`

Canonical edge:

- kind: `sources`
- source: `file:scripts/build.sh`
- target: `dynamic:file:shell-source-expanded-from-variable`
- confidence: `unknown`
- evidence metadata: `{"raw":"source \"$LIB_DIR/common.sh\""}`

RepoMap must not guess `file:lib/common.sh` unless a profile or parser-backed
resolution step proves it.

### Command Substitution or Variable-Derived Command

Source:

```sh
"$(choose_tool)" build
$RUNNER test
```

Canonical nodes:

- `file:scripts/build.sh`
- `dynamic:tool:shell-command-substitution`
- `dynamic:tool:shell-variable-command`

Canonical edges:

- `file:scripts/build.sh --executes--> dynamic:tool:shell-command-substitution`
- `file:scripts/build.sh --executes--> dynamic:tool:shell-variable-command`

RepoMap preserves evidence for the dynamic command but does not invent
`tool:nix`, `tool:python`, or another precise target.

## Rejected Alternatives

### Use Raw Observation `source_id` as Canonical Identity

Rejected. `source_id` identifies an extractor observation event. It often
contains line-ish, parser-ish, or implementation-specific details. Using it as
canonical identity would make graph keys unstable across extractor revisions
and would duplicate durable entities observed from multiple lines.

### Put Line Numbers in Canonical Keys

Rejected. Line numbers identify evidence locations. They change when files are
edited, even when the durable entity remains the same. Line numbers belong in
evidence records.

### Put Environment Variable Values in Env Node Keys

Rejected. `FOO=bar` and `FOO=baz` both refer to the durable environment
variable entity `env:FOO`. Values are assignment facts and belong in edge or
evidence metadata.

### Use Human Display Names as Stable Keys

Rejected. Display names can be localized, reformatted, truncated, or changed
for readability. Canonical keys must use normalized machine identities. Human
display names belong in metadata or UI formatting.

### Make Every Command Invocation Its Own Durable Tool Node

Rejected. A command invocation is evidence of a relationship from a file to a
tool. Modeling every invocation as a durable tool node would confuse tools with
events, inflate graph size, and make simple queries harder. Invocation details
belong in evidence or edge metadata.

### Allow Arbitrary Edge Kinds from Extractors

Rejected. Arbitrary edge kinds prevent stable query semantics and make
cross-language analysis brittle. Extractors may emit detailed raw observation
kinds, but canonicalization must map them into the registered edge vocabulary
or introduce a reviewed vocabulary addition.
