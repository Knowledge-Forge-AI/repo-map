# RepoMap Go Standards

These are the durable Go engineering standards for RepoMap. They apply to new
or touched Go code in approved Go components; they are not permission for
broad rewrites. Existing project style, compatibility contracts, tests,
public APIs, documented behavior, and explicit phase scope take precedence.

## Toolchain And Validation

- Use the Go version managed by the repository's pinned Nix environment.
- Format all Go source with `gofmt`.
- Before completing a phase, run:
  - `go test ./...`
  - `go vet ./...`
  - `golangci-lint run`
- Do not suppress a linter globally merely to make a phase pass.
- A narrowly scoped lint suppression must include a comment explaining why
  the flagged construct is correct.
- Keep `go.mod` and `go.sum` consistent and committed.
- Prefer the Go standard library. Add a third-party dependency only when it
  provides a demonstrated maintainability, correctness, or interoperability
  benefit.

## Project Structure

The repository uses the following Go layout:

```text
src/main/go/                 Go module and production source root
src/test/int/go/             Integration and system-level Go tests
src/test/support/go/         Shared Go integration-test support
src/test/fixtures/           Language-neutral test fixtures, when applicable
```

The primary Go module must be rooted at `src/main/go/`, with its `go.mod`
and `go.sum` in that directory. Do not create another production Go module
unless an approved architecture decision establishes a genuine independently
versioned or deployed component.

### Production source layout

Within `src/main/go/`, follow standard Go layout:

```text
src/main/go/
├── go.mod
├── go.sum
├── cmd/
│   └── <executable-name>/
│       └── main.go
└── internal/
    └── <package-path>/
```

Use:

- `cmd/<executable-name>/` for executable entrypoints;
- `internal/<package-path>/` for application implementation packages;
- additional top-level package directories only when they represent
  deliberate public Go APIs.

Do not create a top-level `pkg/` directory by default. Add `pkg/` only when
the repository intentionally publishes reusable Go packages for external
import. Code being shared by two internal packages is not, by itself,
justification for `pkg/`.

Keep `main` packages thin. A command entrypoint should primarily:

1. initialize process-level concerns;
2. parse command-line input;
3. construct dependencies;
4. invoke an application operation;
5. translate the result into output and an exit status.

Do not place substantial domain logic, Git logic, filesystem orchestration,
extraction logic, or result formatting in `main.go`.

### Package placement

A production package should live at `src/main/go/internal/<package-path>/`,
for example:

```text
src/main/go/internal/request/
src/main/go/internal/gitworktree/
src/main/go/internal/result/
```

Choose package boundaries according to cohesive responsibility, not
architectural ceremony. Do not reproduce Java-style directory layers
mechanically; avoid structures such as `controller/`, `service/`,
`repository/`, `model/`, or `util/` unless each package represents a real
behavioral or dependency boundary in this project.

Package paths must not repeat the repository or executable name
unnecessarily. Prefer `internal/request` and `internal/result` over names
like `internal/repomaprunnerrequest`.

## RepoMap Go Component Boundaries

Go code in RepoMap must represent an explicitly approved component boundary.
Do not mirror the complete Python package hierarchy merely to create a
parallel Go implementation.

Each Go component must have a documented relationship to the existing Python
implementation and public RepoMap contracts. Before introducing a new Go
package, determine whether it is:

- a standalone executable;
- an internal performance-sensitive implementation;
- a language extractor;
- a protocol adapter;
- a reusable library boundary.

Do not split one conceptual component between Python and Go without an
explicit interoperability contract.

Cross-language communication must use an explicit, versioned format such as:

- JSON;
- JSONL;
- a documented subprocess protocol;
- an accepted database contract.

Do not depend on:

- parsing human-readable logs;
- Python object serialization;
- Go-specific binary serialization;
- undocumented environment variables;
- shared mutable files without an ownership protocol.

Go implementations must preserve RepoMap's existing guarantees for:

- deterministic output;
- static non-executing extraction;
- evidence and provenance;
- bounded diagnostics;
- public-safe fixtures;
- canonical identifiers;
- schema compatibility.

Place ordinary Go unit tests beside their packages. Place cross-language and
end-to-end tests under `src/test/int/go/<component-or-contract>/`.
Cross-language tests should validate the public interchange contract rather
than duplicate the complete private test suite of each implementation
language.

## Unit Tests

Go unit tests must normally be colocated with the production package they
test:

```text
src/main/go/internal/request/request.go
src/main/go/internal/request/request_test.go
```

Do not place ordinary Go unit tests under `src/test/unit/go/`. This
exception to the repository's general language-layout convention is
intentional because colocated `_test.go` files are part of Go's native
package and test model.

Use the same package (`package request`) for focused white-box testing when
access to unexported behavior is justified. Use an external test package
(`package request_test`) for black-box API testing when only exported
behavior should be visible. Do not export implementation details merely so a
test in another directory can access them.

A unit test should not require:

- network access;
- GitHub access;
- a real user repository;
- a live database;
- containers;
- persistent machine state;
- the developer's global configuration.

## Integration Tests

Place cross-package, subprocess, filesystem, Git-repository, container, or
end-to-end tests under `src/test/int/go/<behavior-or-component-path>/`, for
example:

```text
src/test/int/go/runner/
src/test/int/go/gitworktree/
src/test/int/go/resultpublication/
```

Organize integration tests by durable behavior or system boundary, not
necessarily by one production source file. Integration tests may import
production packages through the module path, but they must not rely on
unexported implementation details, and production identifiers must not be
exported solely to support them.

When integration testing requires privileged access to internal packages,
prefer one of:

1. testing through the executable;
2. testing through an existing application-facing API;
3. adding a narrowly scoped internal test harness within the production
   module;
4. reconsidering whether the test is actually a unit test and belongs beside
   the package.

Do not add broad public APIs for test convenience.

## Shared Test Support

Place support used only by external integration tests under
`src/test/support/go/<support-package>/`. Examples include temporary Git
repository builders, subprocess test harnesses, bounded-output assertion
helpers, and fixture loaders.

Shared unit-test helpers should normally remain beside the package that owns
them. Do not create a general-purpose test framework or a dumping-ground
support package. Avoid names such as `helpers`, `utils`, `common`, or
`testutil` unless the package's responsibility truly cannot be named more
precisely; prefer names such as `gitfixture`, `processfixture`, and
`resultfixture`.

## Fixtures And Golden Files

Keep package-specific fixtures in a `testdata/` directory beside the package
or test that owns them:

```text
src/main/go/internal/request/testdata/
src/test/int/go/runner/testdata/
```

Go tooling intentionally ignores `testdata` as a package directory. Use
`src/test/fixtures/` only for fixtures shared across languages or across
several independent test areas.

Golden files must be:

- deterministic;
- reviewable;
- public-safe;
- free of local paths and credentials;
- updated only through an explicit reviewed command.

## Build And Test Commands

Because the Go module is rooted at `src/main/go`, run production-module
validation from that directory:

```sh
cd src/main/go
go test ./...
go vet ./...
golangci-lint run
```

Repository-level scripts may wrap these commands, but must not obscure
failures or silently omit packages.

Integration tests under `src/test/int/go` require an explicit
repository-supported execution mechanism. Use one approved approach
consistently:

- a small integration-test Go module with a repository `go.work`;
- an integration-test command built and run by a repository script;
- executable-level tests invoked by the repository test runner.

Do not introduce multiple competing ways to run the same integration suite.
The standard repository validation command must run both the colocated unit
tests under `src/main/go` and the integration tests under
`src/test/int/go`.

## Import Boundaries

Production code must not import code from `src/test/`. Unit-test-only code
must remain in `_test.go` files or package-local `testdata/`.
Integration-test support may import production code, but production code
must never depend on integration-test support. Avoid circular conceptual
dependencies even when the Go compiler permits the physical import graph.

## Generated Code

Keep generated Go files in the package that consumes them unless the
generator establishes a separately documented package. Generated files must:

- contain the conventional generated-code marker;
- identify the generating command or tool;
- be reproducible;
- not require manual editing.

Do not create a broad repository-level `generated/` package merely to
collect unrelated generated files.

## File Size And Organization

- Keep handwritten `.go` files at or below 400 physical lines when
  practical.
- A handwritten `.go` file above 400 lines is an architectural warning and
  should be reviewed for separation of responsibilities.
- No handwritten `.go` file may exceed 800 physical lines.
- Generated files are exempt only when they contain the conventional
  generated-code marker, are produced by a documented deterministic command,
  and are not edited manually.
- Do not evade the limit by compressing formatting, combining unrelated
  statements, moving code into arbitrarily named helper files, or creating
  vague dumping-ground files such as `utils.go`, `helpers.go`, or
  `common.go`.
- Split files and packages by cohesive responsibility, not merely by line
  count.
- Test files are subject to the same limits as production files. Prefer
  several focused test files organized by behavior over one large test
  suite.

(The repository's executable `file-length` profile in
`docs/contrib/file-length-profile.md` currently scans tracked Python files
only; these Go limits are review standards for Go code.)

## Packages And APIs

- Keep packages cohesive and narrowly scoped.
- Use short, descriptive, lowercase package names; avoid `util`, `utils`,
  `common`, `misc`, and `shared`.
- Do not create a package solely to hold one abstraction unless it
  establishes a meaningful boundary.
- Minimize exported identifiers.
- Document every exported identifier unless its purpose is completely
  obvious and accepted by configured lint rules.
- Keep constructors explicit when a type has invariants or required
  dependencies.
- Return concrete types from constructors unless callers genuinely require
  an interface.
- Define interfaces at the point of use, normally in the consuming package.
- Keep interfaces small and behavior-focused; do not introduce interfaces
  solely to make every type mockable.
- Prefer composition over embedding when embedding would expose or blur an
  implementation detail.
- Avoid mutable package-level state.
- Do not perform operational work in `init`.
- Constants are preferable to repeated magic values. Use typed constants or
  dedicated types when plain strings would allow invalid states.

## Functions And Control Flow

- Keep functions focused on one level of abstraction.
- Prefer early returns to deeply nested conditionals.
- Avoid boolean parameters whose meaning is unclear at the call site; use an
  options type or distinct operation when necessary.
- Avoid long parameter lists. Group cohesive configuration into a validated
  struct.
- Validate external input at the system boundary. Once input has been
  validated, preserve the invariant rather than repeatedly revalidating it
  throughout internal code.
- Make zero values useful when doing so does not weaken required
  invariants.
- Use pointers when mutation, identity, or avoiding a meaningful copy is
  required — not automatically for every struct.
- Avoid cleverness. Prefer explicit control flow that is easy to audit.

## Error Handling

- Check errors immediately and explicitly.
- Never discard an error without documenting why it is safe to do so.
- Wrap returned errors with useful operational context using `%w`.
- Add context that answers what operation failed and, when safe, which
  resource was involved. Do not repeatedly wrap an error with redundant text
  at every call level.
- Use `errors.Is` and `errors.As` rather than comparing error strings.
- Use sentinel or typed errors only when callers need to make a programmatic
  decision.
- Error messages should be lowercase and should not end with punctuation.
- Do not log an error and return the same error unless the current layer
  owns a distinct log boundary. Libraries return errors; application
  boundaries decide how to log and present them.
- Reserve `panic` for unrecoverable programmer errors or violated internal
  invariants. Do not use `panic` for malformed input, filesystem failures,
  Git failures, subprocess failures, or ordinary operational errors.
- The top-level command should translate errors into a concise message and a
  stable exit status.

## Context, Timeouts, And Cancellation

- Accept `context.Context` as the first parameter for operations that may
  block, invoke subprocesses, access the network, wait for resources, or
  perform substantial work.
- Do not store a context in a long-lived struct.
- Do not pass `nil` contexts.
- Propagate cancellation to subprocesses and child operations.
- Establish timeouts at an appropriate orchestration boundary rather than
  scattering arbitrary timeout values through low-level functions. A timeout
  must be configurable or represented by a named constant with a documented
  rationale.
- Do not use `context.Background()` inside an operation merely to evade
  caller cancellation. Cleanup that must survive request cancellation should
  use an explicitly bounded cleanup context.

## Concurrency

- Introduce concurrency only when independent work exists and the benefit is
  meaningful. Keep the initial implementation sequential unless parallelism
  is part of the approved phase.
- Ensure every goroutine has a clear owner, a deterministic termination
  condition, cancellation or completion propagation, and a defined
  error-handling path. Never start a goroutine without determining who waits
  for it.
- Avoid channel leaks, blocked sends, and blocked receives. The sending side
  owns channel closure; receivers must not close channels they do not own.
  Do not close a channel merely to signal cancellation when a context is
  appropriate.
- Use buffered channels only when the required capacity and backpressure
  behavior are understood. Do not use an arbitrarily large channel buffer to
  conceal a blocked consumer.
- Bound worker pools and concurrent subprocess execution.
- Prefer simple synchronization with `sync.WaitGroup`, mutexes, or channels
  according to the ownership model. Protect shared mutable state
  explicitly.
- Run concurrency-sensitive tests with the race detector when practical:
  `go test -race ./...`.
- Do not use `sync.Pool` unless profiling demonstrates a material allocation
  or garbage-collection benefit, and do not optimize allocation-heavy loops
  without profiling or clear evidence that the code is a meaningful hot
  path.

## Filesystem And Resource Ownership

- Make ownership of files, directories, processes, pipes, and temporary
  resources explicit.
- Close resources promptly, normally with `defer` immediately after
  successful acquisition. Check meaningful errors returned by `Close`,
  `Flush`, `Sync`, `Rename`, and similar finalization operations.
- Use `os.CreateTemp` and `os.MkdirTemp` rather than predictable temporary
  paths, and ensure temporary resources are removed on success and failure.
- Do not follow symlinks across a trust boundary without an explicit
  decision to do so.
- Use `filepath` rather than constructing native filesystem paths through
  string concatenation, and validate that externally influenced paths remain
  beneath their approved root.
- Prefer atomic publication: write into a temporary sibling, flush and close
  as appropriate, then rename into the final location.
- Set file and directory permissions deliberately when data may be
  sensitive.

## Subprocesses

- Invoke subprocesses with `exec.CommandContext`.
- Pass arguments as separate values. Do not construct a shell command
  string, and do not invoke `sh -c`, `bash -c`, or an equivalent shell
  unless the approved design explicitly requires shell semantics. Never
  interpolate untrusted input into a shell command.
- Use explicit working directories, and control the subprocess environment
  rather than blindly inheriting ambient variables when reproducibility or
  security matters.
- Capture stdout and stderr separately when their distinction is
  operationally useful, and bound captured output to prevent unbounded
  memory use or oversized logs.
- Include the executable, safe arguments, exit status, and bounded
  diagnostic output when reporting subprocess failures.
- Ensure cancellation terminates the entire intended process tree when child
  processes may outlive their direct parent.
- Tests must not depend on whichever Git or tool configuration happens to
  exist in the developer's home directory.

## Logging

- Prefer `log/slog` for structured application logging.
- Libraries should generally return errors and structured results rather
  than emit logs. Log at orchestration boundaries where the application has
  enough context to describe the event.
- Do not log secrets, tokens, private keys, complete inherited environments,
  or unreviewed file contents.
- Keep machine-readable results separate from human-readable logs, and do
  not make log text part of a programmatic protocol.
- Use stable field names when logs are expected to support troubleshooting.

## Determinism

- Produce deterministic output for identical inputs whenever practical.
- Sort map-derived values before serializing or displaying them. Do not rely
  on filesystem enumeration order or Go map iteration order.
- Inject or isolate clocks when tests depend on time. Use UTC for persisted
  timestamps unless a protocol specifies otherwise.
- Use explicit encodings and line endings for persisted artifacts, and avoid
  including volatile data in authoritative outputs unless required by the
  schema.

## Testing

- Test externally observable behavior and important invariants.
- Prefer table-driven tests when cases share setup and assertions, give test
  cases descriptive names, and use `t.Run` to isolate meaningful cases.
- Use `t.Helper` in reusable test helpers, `t.TempDir` for temporary
  filesystem state, and `t.Setenv` for test-specific environment variables.
- Do not depend on the developer's home directory, global Git configuration,
  shell profile, current working directory, network connectivity, or
  wall-clock timing. Unit tests should not access the public network;
  integration tests must clearly identify external prerequisites.
- Test success, expected failure, malformed input, cancellation, cleanup,
  and partial-operation failure. When fixing a bug, add a regression test
  that fails without the fix.
- Avoid sleeping to coordinate concurrent tests; use synchronization or
  observable state.
- Keep test fixtures small, focused, and understandable. Prefer real
  temporary Git repositories and filesystem structures over elaborate mocks
  when they provide more realistic behavior with little cost.
- Do not weaken assertions merely to accommodate nondeterministic
  implementation behavior.

## Security And Sensitive Data

- Treat request files, repository paths, commit identifiers, subprocess
  output, and configuration as untrusted until validated.
- Use allowlists for operations, profiles, executable entrypoints, and
  configured repository roots. Do not permit external input to supply
  arbitrary executable commands.
- Do not expose secrets in errors, logs, test fixtures, or result
  artifacts, and do not use ambient credentials unless the operation
  explicitly requires them.
- Keep privileged operations outside reusable library packages.
- Fail closed when validation cannot establish that an operation is
  authorized.

## Comments And Documentation

- Comments should explain intent, constraints, invariants, or non-obvious
  tradeoffs; do not narrate straightforward code.
- Preserve comments that explain security boundaries or subtle lifecycle
  requirements.
- Update documentation when behavior, configuration, protocols, or
  operational commands change.
- Use TODO comments only when they include a concrete reason or tracked
  follow-up identifier, and do not leave placeholder implementations
  presented as completed behavior.

## Role Of Go In RepoMap

- Do not introduce Go merely to replace working Python code. Use Go only for
  an approved component with a clear boundary and demonstrated benefit.
- Preserve language-neutral protocols between RepoMap and external
  controllers, and do not make RepoMap's public data model depend on
  Go-specific serialization behavior.

## Extraction And Graph Determinism

- Extraction output must be deterministic for the same repository contents,
  configuration, extractor version, and schema version.
- Sort all graph nodes, edges, findings, and serialized collections by an
  explicit stable key. Do not derive canonical identity from map iteration
  order, goroutine completion order, filesystem order, temporary paths, or
  process IDs.
- Concurrent extraction may improve performance, but concurrency must not
  change canonical output. A parallel implementation must be tested against
  the sequential implementation or stable golden output.
- Avoid timestamps in canonical graph data unless the schema specifically
  requires them.
- Keep parsing, normalization, identity construction, graph mutation, and
  persistence as distinct responsibilities.

## Language Extractors

- Keep language-specific parsing and taxonomy logic within the relevant
  extractor boundary. Shared abstractions must represent genuinely shared
  semantics, not accidental similarities between languages.
- Do not weaken an existing language's model to force multiple extractors
  through one generic interface.
- Unsupported or dynamic syntax must produce explicit bounded behavior
  rather than speculative facts.
- Preserve provenance for extracted facts when the surrounding architecture
  supports it.
- Treat malformed source as an expected input condition and return a bounded
  diagnostic rather than panic.

## Performance

- Benchmark before replacing clear code with low-level optimization, using
  representative repositories and fixture sizes.
- Report elapsed time, allocations, peak or representative memory use when
  relevant, and output-equivalence validation.
- Do not trade deterministic output or safety boundaries for throughput.
- Bound concurrency according to CPU, memory, parser safety, and downstream
  database capacity.
- Avoid loading entire repositories or very large files into memory when
  streaming or bounded reads are practical, and establish explicit maximum
  input sizes where unbounded input could exhaust memory.

## Database And Persistence Boundaries

- Keep SQL and transaction ownership explicit. A function that begins a
  transaction should normally own commit or rollback, and every failure path
  must roll back.
- Do not hide network or database operations behind innocent-looking
  accessors.
- Preserve stable insertion and conflict-handling semantics. Batch writes
  only when correctness, diagnostics, and failure attribution remain clear.
- Do not retry non-idempotent operations without an explicit idempotency
  design.
- Include enough context in database errors to identify the operation
  without exposing credentials or sensitive content.

## Compatibility

Changes to machine-readable output, schema identifiers, canonical IDs, or
public command behavior require an explicit compatibility decision, tests,
documentation, and migration handling when applicable. Do not silently
reinterpret existing stored data. Prefer additive changes to externally
consumed structures, and keep Go implementation details out of public
formats.
