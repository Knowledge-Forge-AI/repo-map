# Go Extraction Design

Status: Accepted for GO2 classification and metadata implementation. Parser
runtime implementation requires a separate authorization before GO3.

Date: 2026-07-12

## Objective

RepoMap will add deterministic, static Go extraction that scales from a small
single-module repository to Kubernetes without executing target code, loading
packages, downloading dependencies, or pretending that syntax-only evidence is
type-resolved behavior.

This design separates two boundaries:

1. Python-owned file classification and module/workspace metadata, approved
   for GO2; and
2. a proposed Go standard-library AST helper for GO3 and later, which is a new
   parser runtime and therefore requires the mandate's architecture stop before
   implementation.

## Existing Contracts

RepoMap discovery remains the owner of sorted repository walking, root and
symlink safety, configured exclusions, generic file observations, and
language routing.

RawObservation schema version 1 remains the extractor interchange:

- kind;
- source_id;
- path;
- confidence;
- extractor and extractor_version;
- optional start_line and end_line;
- optional name and target; and
- metadata.

No raw-schema or storage migration is required for GO2.

Canonical nodes, edges, evidence, and evidence links remain separate from raw
extraction. GO2 through GO8 may add raw Go observations. GO9 owns canonical
identity and edge implementation.

## Syntax Ownership

### Python-Owned GO2 Boundary

Python owns:

- .go, _test.go, generated-header, and filename build-variant
  classification;
- go.mod, go.sum, go.work, and vendor/modules.txt classification;
- conservative go.mod and go.work directive parsing;
- module, Go version, toolchain, require, replace, exclude, retract,
  workspace-use, and workspace-replace observations;
- path, root, exclusion, redaction, and deterministic ordering; and
- conversion into RawObservation.

GO2 does not parse Go source syntax beyond bounded header and filename
classification.

### Proposed GO3+ Boundary

A RepoMap-owned Go executable is the preferred syntax owner. It would use only:

- go/parser;
- go/ast;
- go/token;
- go/build/constraint;
- encoding/json; and
- other ordinary Go standard-library packages.

Official API references:

- https://pkg.go.dev/go/parser
- https://pkg.go.dev/go/ast
- https://pkg.go.dev/go/token
- https://pkg.go.dev/go/build/constraint

parser.ParseFile accepts source bytes and produces an AST, may return a partial
AST with syntax errors, and supports ParseComments, AllErrors, and
SkipObjectResolution. ast.Inspect provides depth-first traversal.
token.FileSet provides physical file positions. constraint.Parse accepts
modern //go:build and legacy // +build lines.

The helper must not import go/types, go/packages, go/build package loading, or
compiler APIs that resolve dependencies. It must not invoke a Go command,
package manager, target binary, generator, test, or repository script.

## File Classification

GO2 extends generic FileInfo behavior:

| Path shape | language | role | generated |
| --- | --- | --- | --- |
| ordinary .go | go | source | false |
| *_test.go | go | test | false |
| standard generated-header .go | go | generated | true |
| generated *_test.go | go | generated | true |
| go.mod | go-module | config | false |
| go.sum | go-checksum | config | false |
| go.work | go-workspace | config | false |
| vendor/modules.txt | go-vendor-manifest | config | false |

Generated role takes precedence over test role. go.file metadata preserves
test_file=true when a generated test file needs both facts.

A standard generated marker is any line matching the Go convention
Code generated ... DO NOT EDIT. within the leading comment/header region
before the package clause. GO2 uses a bounded first-40-line scan. It records
the marker line but never stores the comment text.

Filename variant parsing recognizes:

- _GOOS.go;
- _GOARCH.go;
- _GOOS_GOARCH.go; and
- _test.go after removing any platform suffix.

GOOS and GOARCH names come from a versioned project constant, not host
environment values. Unknown underscore suffixes remain ordinary filenames.
Classification does not decide whether a file is active on the current host.

Vendor means a path component exactly equal to vendor under a module tree. A
substring or unrelated fixture directory is not vendor. GO2 records
vendor=true but does not exclude the file.

## GO2 Module And Workspace Parsing

GO2 uses a small deterministic lexer for go.mod and go.work. It supports:

- line comments;
- quoted and raw-string fields;
- single-line directives;
- parenthesized directive blocks;
- module;
- go;
- toolchain;
- require with optional indirect marker;
- replace;
- exclude;
- retract;
- use; and
- workspace replace.

The parser does not expand environment variables, resolve filesystem targets,
load modules, validate versions against a registry, open referenced paths, or
interpret unknown future directives. Unknown directives emit one bounded
go.metadata_unknown observation per directive. Malformed directives emit
go.metadata_parse_error and parsing continues at the next physical line or
block boundary.

go.sum is classified but not parsed in GO2. Checksums, versions, and module
lines remain file evidence; graphing every checksum would add volume without
an accepted relationship.

vendor/modules.txt is classified but not parsed until GO8 vendor policy.

## Raw Observation Taxonomy

### GO2 Metadata Kinds

| Kind | name | target | Required metadata |
| --- | --- | --- | --- |
| go.file | repository-relative path | none | file_kind, test_file, generated, vendor, goos, goarch |
| go.module | module path | none | directive=module |
| go.module_go_version | version | none | directive=go |
| go.module_toolchain | toolchain | none | directive=toolchain |
| go.module_require | module path | module reference | version, indirect |
| go.module_replace | old module | replacement reference | old_version, replacement_kind, replacement, replacement_version |
| go.module_exclude | module path | module reference | version |
| go.module_retract | interval or version | none | low, high, rationale_present |
| go.workspace | repository-relative go.work path | none | directive=workspace |
| go.workspace_go_version | version | none | directive=go |
| go.workspace_toolchain | toolchain | none | directive=toolchain |
| go.workspace_use | normalized relative directory | file reference | resolved_under_root |
| go.workspace_replace | old module | replacement reference | same replacement fields as module replace |
| go.metadata_unknown | directive name | none | directive, field_count |
| go.metadata_parse_error | directive or document | none | error_kind, bounded_message |

Module targets use go.module-ref:<escaped-module-path>@<version-or-unspecified>.
Local replacement and workspace-use targets use
file:<normalized-repository-relative-directory>. Paths escaping the repository
become external-path:<redacted> with confidence unknown; they are not opened.

GO2 source IDs use:

path#<kind>:<start-line>:<ordinal>

where ordinal is the zero-based occurrence of that kind in the file after
physical-line order. Identity does not include raw secret-like text or an
absolute path.

Module directives include owner_module_path after a valid module directive.
Workspace directives include owner_workspace_path. When the owner is missing
or malformed, the field is absent and confidence is unknown.

### GO3 Declarations

- go.package;
- go.import;
- go.const;
- go.var;
- go.type;
- go.type_alias; and
- go.parse_error.

### GO4 Callables

- go.function;
- go.method;
- go.receiver;
- go.parameter; and
- go.result.

### GO5 Composite Types And Generics

- go.struct;
- go.interface;
- go.field;
- go.embedded_field;
- go.type_parameter;
- go.constraint; and
- go.union_term.

### GO6 References And Expressions

- go.reference;
- go.selector;
- go.call;
- go.method_expression;
- go.construct;
- go.conversion;
- go.type_assertion;
- go.type_switch;
- go.index;
- go.slice;
- go.map_access; and
- go.instantiation.

### GO7 Control And Concurrency

- go.closure;
- go.goroutine;
- go.defer;
- go.send;
- go.receive;
- go.select;
- go.panic;
- go.recover;
- go.return;
- go.break;
- go.continue;
- go.goto; and
- go.dynamic.

### GO8 Build And Test Context

- go.build_constraint;
- go.generated_marker;
- go.cgo;
- go.assembly_companion;
- go.test;
- go.benchmark;
- go.fuzz;
- go.example;
- go.test_main; and
- go.vendor_package.

## AST Observation Contract

Every AST-derived observation includes:

- start_line and end_line for the complete syntax node;
- metadata start_column and end_column, one-based;
- metadata start_offset and end_offset, zero-based byte offsets;
- package_name;
- declaration or expression ordinal within the file;
- test_file and generated flags; and
- static_only=true, code_executed=false, type_checked=false.

Positions use token.File.PositionFor(pos, false) so //line directives do not
replace physical repository evidence. End positions are exclusive byte
offsets; end_line is the physical line containing the final byte.

No observation stores raw source, comments, string literal values except
public-safe import paths and module directives, function bodies, or expression
text.

Definitions use extracted confidence. Direct syntax relationships use
extracted. Locally bounded name resolution uses heuristic. Dynamic, ambiguous,
or build-dependent resolution uses unknown.

## Definition Metadata

go.package:

- name is the package clause name;
- metadata includes external_test_package, main_package, and file_count_known;
- target is absent.

go.import:

- name is the import path;
- target is go.package-ref:<escaped-import-path>;
- metadata includes alias, blank_import, dot_import, and parenthesized.

Package declarations, imports, package-scope constants, variables, types,
functions, and methods receive full-node spans. Grouped declarations also
record spec_index.

go.type and go.type_alias metadata includes declaration_name, exported,
generic, and type_parameter_count.

go.function and go.method metadata includes declaration_name, exported,
variadic, parameter_count, result_count, and type_parameter_count.

go.method additionally records receiver_text_redacted=false only as structured
receiver fields: receiver_name, receiver_base, receiver_pointer, and
receiver_type_parameter_count. It does not store raw receiver source.

Parameters and results record parent_source_id, position, name_present,
variadic, and normalized AST shape. Unnamed results have name absent and stable
position identity.

## Reference And Relationship Honesty

Syntax-only extraction may prove:

- package-qualified selector syntax;
- direct identifier call syntax;
- method-expression syntax;
- composite-literal type syntax;
- explicit send, receive, go, defer, panic, recover, and return syntax;
- declared receiver ownership; and
- explicit embedding syntax.

It may not prove:

- the actual declaration selected by an identifier;
- promoted method resolution;
- interface satisfaction;
- overload-like generic inference;
- whether a call is a conversion without bounded syntactic evidence;
- external module contents;
- runtime reads or writes;
- reflection behavior; or
- build-selected package composition.

Unresolved relationships remain raw with resolution=unresolved or
resolution=syntactic. GO9 must not convert them into stronger canonical edges.
Interface satisfaction is deferred until a separately accepted type-analysis
phase and is not part of GO1-GO17 by default.

## Accepted Canonical Identity

GO12 amends the GO9 version-1 model with an additive two-level identity
contract. The semantic module coordinate remains:

- `go.module:<escaped-module-path>`.

Observed source ownership uses versioned repository-scoped identities:

- `go.source-module.v2:<repository-scope>:<repository-relative-module-root>:<module-path>`;
- `go.source-package.v2:<source-module-key>:<module-relative-directory>:<package-name>`;
- `go.source-package-fallback.v2:<repository-scope>:<repository-relative-directory>:<package-name>`;
- `go.source-type.v2:<source-package-key>:<name>`;
- `go.source-function.v2:<source-package-key>:<name>`;
- `go.source-method.v2:<source-package-key>:<receiver-base>:<name>`;
- `go.source-const.v2:<source-package-key>:<name>`; and
- `go.source-var.v2:<source-package-key>:<name>`.

The owning graph supplies the configured repository name as an explicit
repository scope. Scope is a bounded public-safe identifier and is never
derived from an absolute path, checkout basename, working directory, Git
remote, Git configuration, process state, hostname, temporary directory,
database name, or traversal order. Missing or invalid scope fails closed with
one bounded diagnostic.

There is no separate semantic package coordinate in GO12. Observed package
ownership uses source-package instances, while import path remains semantic
metadata. External imports remain unresolved unless another existing exact
coordinate relationship applies. External test packages remain distinct by
package name. Packages outside a valid module use the repository-scoped
fallback namespace rather than the globally ambiguous GO9
`repo-relative:<directory>` component.

Local variables, parameters, results, fields, closures, labels, and most
expressions remain evidence or metadata unless a later phase proves a durable
query need.

Accepted Go edge kinds:

- declares;
- contains;
- instance_of;
- imports;
- requires_module;
- replaces_module;
- workspace_uses;
- method_of;
- embeds;
- references;
- calls;
- constructs;
- selects;
- instantiates;
- sends;
- receives;
- starts_goroutine;
- defers;
- panics;
- recovers;
- returns;
- tests;
- benchmarks;
- fuzzes; and
- examples.

implements is explicitly excluded.

GO12 assigns packages to the deepest enclosing source-module root. Source
package identity is stable when a source file moves within the same package
directory and when a repository checkout relocates without changing its
explicit scope. Changing repository scope creates distinct source identities.
Type aliases share the `go.source-type.v2` key namespace with defined types
while retaining node kind `go.source_type_alias`; an incompatible defined-
type/alias claim for one key is a collision and fails closed.

Exact module requirements and remote module replacements may create
`go.module` nodes whose metadata records `declaration_observed=false`. GO9 does
not create unresolved external package placeholder nodes. Vendored package
canonical identity remains deferred because merging it with external-module
identity or assigning a repository-local identity requires a dedicated public
model. Build variants do not receive host-specific canonical identities;
same-family declarations merge as ordered duplicate evidence while build
constraints remain raw evidence.

GO12 emits only `declares`, `contains`, `instance_of`, bounded-local `imports`,
`requires_module`, remote `replaces_module`, bounded-local `workspace_uses`,
and exact receiver `method_of` edges. The complete accepted Go edge vocabulary
is storage-compatible, but other syntax remains evidence-only until a later
phase proves a target without type checking or dependency loading.

Every canonical Go node and edge links to its raw observation evidence. One
bounded accounting diagnostic reports canonical nodes, canonical edges,
evidence links, expected duplicate declaration evidence, identity collisions,
and unresolved relationships. Canonical identity errors, incompatible
declaration families, package-directory ambiguity, module-root ambiguity, and
alias-only method ownership produce bounded errors rather than silently
invented identities. Repeated semantic module coordinates across independent
source roots are expected: they produce one semantic node, independent source-
module nodes, and one `instance_of` edge per observed occurrence. Different
module paths at one root, incompatible source claims, duplicate source IDs,
unsafe paths, and invalid repository scope remain fail-closed errors.

### GO12 Compatibility And Rebuild Policy

GO9 `go.module` nodes remain supported as semantic coordinates, including
`declaration_observed=false` dependency coordinates. GO9 package and source-
declaration key builders remain import-compatible, but the Go canonicalizer no
longer emits those nodes for exact source ownership. GO12 emits only v2 source
package and declaration families; consumers do not observe duplicate v1 and
v2 source declarations during a compatibility window.

The global graph-key version remains 1 because GO12 adds explicit namespaces
and `identity_format=go-source-v2` rather than reinterpreting an existing key.
Existing stored Go graphs require a rebuild so obsolete GO9 source nodes are
removed. The authorized dogfood graphs are rebuilt rather than rewritten in
place. Raw observations and semantic dependency coordinates are retained. The
storage migration adds only `instance_of`; rollback restores the complete
pre-GO12 edge-kind allowlist. Rolling application code back also requires
rebuilding affected Go graphs under the GO9 model.

Independent repositories that observe the same module path share the semantic
coordinate but have distinct source-module, package, and declaration
identities. Local imports resolve only within the owning source-module
instance. Workspace uses resolve to exact source-module instances. Module
requirements and remote replacements remain between semantic coordinates.

Changing the configured repository name changes the repository scope and is an
explicit stored-identity migration. A routine refresh must not be used for that
change because additive canonical ingestion can retain old-scope source nodes
and edges. Operators must use the RepoMap-owned backup-first graph rebuild
workflow before loading the new scope, then save new stored/preflight baselines
and verify immediate drift. Changing only the checkout location while keeping
the configured repository name unchanged does not require an identity rebuild.

## Proposed Streaming Protocol

The preferred helper is one long-lived process per repository discovery.
Python starts it with the validated repository root as a separate argument and
sends sorted relative paths over stdin.

Request line:

    {
      "protocol_version": 1,
      "type": "file",
      "sequence": 0,
      "path": "internal/example.go"
    }

Observation response line:

    {
      "protocol_version": 1,
      "type": "observation",
      "sequence": 0,
      "observation": { "schema_version": 1, "...": "RawObservation" }
    }

Diagnostic response line:

    {
      "protocol_version": 1,
      "type": "diagnostic",
      "sequence": 0,
      "severity": "warning",
      "code": "go-parse-error",
      "path": "internal/example.go",
      "line": 12,
      "message": "bounded parser diagnostic"
    }

Completion line:

    {
      "protocol_version": 1,
      "type": "file_end",
      "sequence": 0,
      "path": "internal/example.go",
      "observation_count": 42,
      "diagnostic_count": 1,
      "truncated": false
    }

The helper must emit responses in request order. GO3 starts sequentially and
uses no goroutines. stdout is protocol-only. stderr is bounded process-level
diagnostic output and must not contain source text or absolute roots.

## Protocol Security And Bounds

- root is resolved once;
- request paths must be non-empty UTF-8 repository-relative paths;
- absolute paths, NUL, dot-dot escape, and symlink escape are rejected;
- only regular files ending in .go are accepted;
- maximum path length is 4,096 UTF-8 bytes;
- maximum file size is 32 MiB;
- maximum parse diagnostics is 32 per file;
- maximum observation count is 250,000 per file;
- maximum encoded protocol line is 1 MiB;
- Python bounds stderr capture at 64 KiB;
- unexpected response type, version, sequence, path, count, or JSON is fatal
  for the helper session;
- one file failure emits a bounded diagnostic and file_end when protocol
  integrity remains intact;
- broken protocol terminates the process and fails the extraction run; and
- cancellation closes stdin, terminates the child, waits with a bounded
  cleanup context, and escalates to kill if necessary.

Oversized files remain generic file observations and receive one
go.file_limit diagnostic. Truncation is explicit and never presented as
complete extraction.

## Determinism

- Python supplies sorted paths;
- helper traverses AST children in source order;
- grouped declarations retain spec order;
- observations sort by path, start_offset, end_offset, kind, name, target, and
  source_id before publication;
- map-derived metadata keys are sorted during JSON encoding;
- concurrency is deferred until output equivalence is proved;
- timestamps, process IDs, temporary paths, and host build context never enter
  raw or canonical identity; and
- parser/tool versions are explicit extractor metadata, not identity.

## Malformed And Partial Code

The helper uses ParseComments, AllErrors, and SkipObjectResolution. When
ParseFile returns a partial AST plus errors:

- safe nodes present in the partial AST may emit observations;
- each observation records partial_parse=true;
- at most 32 parser diagnostics are normalized by physical position;
- messages exclude absolute filenames and source excerpts;
- duplicate diagnostics at the same code/position are removed;
- a terminal go.parse_error summarizes truncation when more errors exist; and
- one malformed file does not terminate other files.

If no AST is returned, only bounded parse-error evidence is emitted.

## Build, Generated, Test, Vendor, And Cgo Policy

RepoMap records all syntactically valid files independent of the current host.
Build constraints and filename variants are evidence, not filters.

Generated files are included by default but marked. Dogfood summaries report
generated and non-generated counts separately. Later performance policy may
skip deep expression extraction for generated files only through an explicit
profile and must still preserve file, package, import, and declaration facts.

Test files are included and marked. Test, benchmark, fuzz, example, and
TestMain recognition is syntactic and does not imply execution or pass/fail.
External test packages remain distinct.

Vendor files are included only when the configured graph does not exclude
vendor. They are marked vendor=true and reported separately. They do not
silently merge with first-party package identity.

cgo is recognized from import "C" and #cgo directives in the associated
comment group. No C preprocessor, compiler, pkg-config, generator, or tool is
invoked. Assembly companions are path/package relationships only; assembly is
not parsed in this epic.

## Exact Proposed Files

GO2:

- modify src/main/python/repomap_kg/graph/discovery.py;
- modify src/main/python/repomap_kg/graph/discovery_extractors.py;
- create src/main/python/repomap_kg/extractors/languages/go_metadata.py;
- modify source-language package export and package-structure tests;
- create src/test/fixtures/go/classification;
- create src/test/fixtures/go/module_basic;
- create src/test/fixtures/go/workspace_basic;
- create
  src/test/unit/python/repomap_kg/graph/go_classification.unit.test.py;
- create
  src/test/unit/python/repomap_kg/extractors/languages/go_metadata.unit.test.py;
- create src/test/int/python/repomap_kg/cli/discover_go.int.test.py;
- update focused package-structure inventory tests; and
- add an untracked local dogfood operations overlay outside the repository.

GO3, only after user authorization:

- create src/main/go/go.mod;
- create src/main/go/cmd/repomap-go-extract/main.go;
- create src/main/go/internal/protocol;
- create src/main/go/internal/extraction;
- create src/main/go/internal/pathscope;
- create src/main/python/repomap_kg/extractors/languages/go_protocol.py;
- create src/main/python/repomap_kg/extractors/languages/golang.py;
- create public-safe syntax and malformed fixtures;
- add colocated Go unit tests;
- add one repository-supported cross-language integration mechanism; and
- update tools/run_tests.py only in the accepted helper phase.

GO9:

- create focused Go canonicalization modules;
- update canonical dispatch;
- add canonical golden fixtures and integration tests; and
- add bounded Go readback only if accepted by that phase.

## Exact Proposed Python Interfaces

GO2 data contracts are frozen dataclasses:

- GoFileKind(language: str, role: str, test_file: bool, generated: bool,
  vendor: bool);
- GoFilenameConstraints(goos: str | None, goarch: str | None,
  test_file: bool);
- GoMetadataDirective(kind: str, fields: tuple[str, ...], start_line: int,
  end_line: int, ordinal: int, comment_present: bool); and
- GoMetadataDocument(format: str,
  directives: tuple[GoMetadataDirective, ...],
  diagnostics: tuple[GoMetadataDiagnostic, ...]).

GoMetadataDiagnostic is a frozen dataclass with severity, code, line, and a
bounded path-free message.

GO2:

- detect_go_file_kind(path: PurePosixPath) -> GoFileKind;
- detect_go_filename_constraints(path: PurePosixPath) -> GoFilenameConstraints;
- detect_go_generated_marker(path: Path, max_lines: int = 40) -> int | None;
- extract_go_metadata_observations(content: str, relative_path: str)
  -> list[RawObservation];
- extract_go_metadata_observations_from_file(root: Path, relative_path: str)
  -> list[RawObservation]; and
- parse_go_metadata_document(content: str, relative_path: str)
  -> GoMetadataDocument.

GO3 proposal:

GoProtocolMessage is a frozen tagged record with protocol_version, type,
sequence, path, and exactly one validated observation, diagnostic, or file-end
payload according to type.

- iter_go_protocol_observations(root: Path, relative_paths: Sequence[str],
  command: Sequence[str]) -> Iterator[RawObservation];
- validate_go_protocol_message(payload: Mapping[str, Any],
  expected_sequence: int, expected_path: str) -> GoProtocolMessage; and
- extract_go_repository_observations(root: Path,
  file_infos: Sequence[FileInfo]) -> list[RawObservation].

## Fixture Matrix

All fixtures are synthetic and public-safe:

- ordinary package and command;
- internal package;
- same-package and external-package tests;
- generated ordinary and generated test file;
- modern, legacy, and paired build constraints;
- GOOS, GOARCH, and combined filename variants;
- root and nested modules;
- workspace use and replace;
- require, indirect, replace-local, replace-module, exclude, retract,
  toolchain, and unknown directives;
- vendor module/package;
- grouped declarations;
- functions, methods, pointer/value receivers, unnamed results, variadics;
- structs, interfaces, embedding, generics, unions, and approximation terms;
- calls, selectors, method expressions, literals, assertions, switches, and
  instantiation;
- closures, go, defer, channels, select, panic/recover, and returns;
- tests, benchmarks, fuzz, examples, and TestMain;
- cgo marker and assembly companion;
- malformed and partial syntax;
- path escape and symlink escape; and
- large generated and large test files produced synthetically by test setup,
  not committed as bulk fixtures.

No fixture copies upstream source.

## Test Strategy

GO2 uses TDD:

1. failing classification tests;
2. failing module/workspace lexer tests;
3. minimal implementation;
4. focused unit tests;
5. CLI discovery integration tests;
6. Docker Language Server read-only discovery/dogfood;
7. broader extractor/canonical/observation regressions; and
8. full source gate, compileall, diff checks, and dependency check.

GO3 must additionally run, from src/main/go:

- go test ./...;
- go vet ./...;
- golangci-lint run; and
- go test -race ./... when practical.

The standard repository runner must gain exactly one supported path for
colocated Go unit tests and src/test/int/go integration tests. Production code
must not import test support. Integration tests must use the executable or
protocol, not exported internal details.

Parser regression tests require red-green evidence. Determinism tests shuffle
input order and compare byte-identical normalized output. Protocol tests cover
malformed JSON, wrong version, wrong sequence/path, oversized line/file,
truncated output, child exit, cancellation, and bounded stderr.

## Dogfood Acceptance

Each major milestone records:

- public upstream revision;
- tracked and Go file counts;
- module/workspace/package counts;
- generated, vendor, test, build-tag, platform, cgo, and assembly counts;
- observations by kind;
- canonical nodes/edges when applicable;
- warning, parse-error, unresolved, truncation, and collision counts;
- wall time and approximate peak memory when available;
- full versus incremental refresh;
- graph status and summary;
- lifecycle action and repair outcome;
- source-tree cleanliness; and
- privacy review.

Initial implementation dogfood is Docker Language Server. Argo CD follows for
generated/multi-module pressure, Terraform for nested-module/test density, and
Kubernetes last for scale and vendor/workspace coverage.

## GO13 Performance And Incremental Refresh Assessment

GO13 retains deterministic full refresh as the only implemented refresh mode.
An uncommitted bounded trial cached file-local Go helper observations by
repository scope, helper fingerprint, relative path, and content hash. The
trial preserved byte-identical raw output and equal canonical results, but it
demonstrated no material unchanged-run improvement because Python still
deserialized the complete observation volume and the refresh still rebuilt the
complete raw, canonical, evidence, and storage run.

Parser-output caching is therefore rejected. It must not be reintroduced
without evidence that a materially different representation or workload
improves the complete pipeline.

Useful incremental refresh requires a language-neutral transactional storage
contract rather than a Go-only parser cache. A future design must address at
least:

- content-addressed file extraction generations keyed by extractor identity
  and content hash;
- explicit complete-run membership without copying unchanged payloads;
- deletion and rename reconciliation;
- invalidation closure for module, workspace, package, import, and other
  cross-file relationships;
- module- or repository-slice canonical reconciliation with exact evidence
  ownership;
- latest-run readback and baseline compatibility;
- interruption, rollback, pruning, and full-refresh recovery;
- deterministic equivalence between incremental and forced-full materialized
  graphs; and
- a migration and rebuild policy for existing databases.

That model changes storage and run semantics for every language. It is outside
the authorized Go-only implementation boundary until separately approved.

GO13 Deferral A is accepted. The remainder of this epic uses deterministic
full refresh exclusively. Formal repository evaluations may not describe full
refresh as incremental, reused, or optimized, and incremental-storage work
must begin under a separate cross-language assessment and design mandate.

## Post-GO9 Revised Phase Map

GO10 inventory evidence replaces the provisional GO10 through GO17 sequence.
The added repository set contains two small two-module RepoMap repositories, a
91-module recipes collection, a bounded single-module gorush repository, and a
larger build-tag-heavy Caddy repository. None contains tracked vendor files.

The remaining correctness-first sequence, revised by GO11 collision evidence,
is:

1. GO11 documents the duplicate module-path identity decision and stops before
   implementation.
2. If authorized, GO12 hardens module, workspace, package, and bounded local-
   import resolution with a versioned source-instance model.
3. GO13 establishes performance and incremental-refresh behavior with exact
   equivalence to deterministic full refresh.
4. GO14 through GO18 formally evaluate RepoMap runner, RepoMap controller,
   recipes, gorush, and Caddy in that order.
5. GO19 and GO20 formally evaluate Argo CD and Terraform.
6. GO21 evaluates Kubernetes first-party source without vendor identity.
7. GO22 stops for the vendored-package identity decision before any vendor-
   inclusive Kubernetes claim.
8. GO23 performs cross-repository canonical parity and stability audit.
9. GO24 reviews remaining packaging gaps and closes the Go epic.

An evaluation may open a separate correction phase when the defect is
independently auditable. It may not silently change canonical key version 1,
invent external package placeholders, load dependencies, select host build
variants, or resolve syntax beyond the accepted bounded local model.

## GO11 Duplicate Module Path Evidence

Recipes contains two semantic module paths repeated across independent source
roots. One occurs at 6 roots and creates 14 overlapping derived package
identities; the other occurs at 19 roots and creates 2 overlaps. The roots are
not nested. Treating them as duplicate evidence would merge unrelated exact
declarations, while collision-only suffixes would make identity depend on the
presence and ordering of other roots.

The recommended correction is a two-level model:

- retain `go.module:<module-path>` as a semantic dependency coordinate;
- add a versioned repository-scoped source-module instance using an explicit
  validated repository scope and repository-relative module root;
- derive source-package and declaration ownership beneath that instance; and
- link the source instance to its semantic coordinate with an explicit edge.

The repository scope must come from the owning RepoMap operation. It may not be
derived from an absolute path, ambient Git remote, local directory name,
process state, or host configuration. This adds a public node family, edge,
scope input, and versioned identity format, so GO12 cannot implement it without
an explicit user decision.

## Packaging, Dependency, And Stop Decision

GO2 adds no dependency, Go module, Go toolchain requirement, binary, package
metadata, or runtime behavior outside Python.

The proposed helper uses no third-party Go module, but it still introduces a
new parser runtime, Go toolchain/build path, platform-specific executable, and
Python-to-Go packaging contract. Running go run at extraction time is rejected.
Silently searching ambient PATH is rejected. Committing generated binaries is
rejected.

Preferred eventual distribution is a platform-specific helper built from
RepoMap source during an accepted package/build process and installed beside
the Python distribution, with an explicit deterministic resolver and bounded
unavailable-helper diagnostic. The exact wheel/Nix/source-checkout publication
mechanism is not accepted by GO1.

Therefore:

- GO2 is authorized and independent of the parser runtime;
- GO3 must not begin until the user authorizes the new parser/runtime and
  packaging direction; and
- if authorized, GO3 begins with a focused helper/package design correction if
  the chosen distribution differs from this preferred model.

Rollback is simple through GO2: remove Go-specific classification/metadata
routing while generic file evidence remains. After helper integration, rollback
must preserve file and module metadata and disable only AST enrichment.

## Explicit Exclusions

- type checking;
- go list, go test, go generate, go/packages, or dependency download as
  extraction;
- compiler plug-ins;
- package initialization;
- interface satisfaction;
- runtime data flow;
- reflection resolution;
- external module ingestion;
- assembly parsing;
- C/C++ parsing;
- current-host build selection;
- incompatible raw schema or canonical-key changes;
- background services or scheduling;
- remote ingestion;
- multi-repository federation; and
- another language epic.

## Phase Decision

GO2 may implement only classification and module/workspace metadata under the
existing Python runtime.

The standard-library helper is the recommended high-fidelity parser. It is
also a new parser runtime. The autonomous epic should complete GO2 and its
dogfood evidence, then stop before GO3 for the user to authorize or reject the
new helper and packaging boundary.

## GO23 Closure Addendum

The autonomous Go extraction epic completed through GO23. Later accepted
decisions supersede the provisional phase map and stop points above where they
conflict:

- GO3 accepted the RepoMap-owned standard-library helper and deterministic
  source-build/local-development workflow;
- GO12 accepted Model A semantic coordinates plus repository-scoped source
  instances;
- GO13 rejected the Go-only unchanged-file cache and deferred incremental
  storage to a language-neutral future epic;
- GO14 through GO18 completed formal runner, controller, recipes, gorush, and
  Caddy evaluation;
- GO19 and GO20 corrected discovery defects exposed by Argo CD;
- GO21 identified full-refresh client-memory infeasibility;
- GO22 retained a language-neutral bounded streaming correction and accepted a
  separate per-row storage-throughput scale limit; and
- GO23 closed the epic without Argo CD, Terraform, Kubernetes, or vendor-
  inclusive formal parity.

The durable supported contract and explicit deferrals are recorded in
`docs/status/2026/07/12/00469-go23-go-epic-closure.md`. Any high-scale or
incremental storage redesign, vendored-package identity, incompatible public
identity change, dependency-backed type analysis, or release-platform helper
packaging requires a new mandate.
