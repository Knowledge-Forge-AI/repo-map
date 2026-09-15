# ADR 0035: Dependency Evaluation After Initial Refactor Phases

## Status

Accepted.

## Date

2026-07-05

## Context

REF2 defined the initial readability/refactor roadmap. REF3 through REF8 then
reduced several large internal seams without adding runtime dependencies:

- REF3 split CLI parser construction and command dispatch;
- REF4 split storage readback helpers;
- REF5 split local ops and runtime boundaries;
- REF6 extracted small extractor scanner, redaction, and observation helpers;
- REF7 split canonicalization core and dispatch helpers; and
- REF8 consolidated the first CLI test-support helpers.

Those phases make dependency evaluation more concrete. RepoMap now has a better
view of what local code remains hard to read, what is merely large, and what is
better kept explicit because it encodes safety, static-extraction, storage, or
graph-identity policy.

The current project package metadata has no runtime dependencies and only a
small optional test extra. REF9 does not change that dependency surface.

## Decision

REF9 adds no dependencies.

Future dependency proposals require a dedicated ADR or explicitly scoped phase.
Dependency adoption must be problem-driven, not aesthetics-driven. A dependency
may be considered when it improves performance, correctness, maintainability, or
readability enough to justify its packaging, supply-chain, runtime, and review
cost.

RepoMap keeps a strong stdlib/local-code default after REF9. The local refactor
phases showed that many readability issues can be improved by focused module
boundaries, pure helpers, and test support without introducing new packages.

## Evaluation Criteria

Future proposals must use public project criteria only:

- performance impact;
- correctness improvement;
- readability and maintainability improvement;
- reduction of complex local code;
- stability and maintenance health;
- supply-chain and transitive dependency risk;
- license compatibility with RepoMap;
- packaging and runtime footprint;
- compatibility with CLI, MCP, storage, smoke, and containerized test runs;
- supported Python versions;
- deterministic behavior in static extraction and readback;
- clear failure behavior in public and private-safe workflows; and
- ease of removal if the dependency is unsuitable.

Performance claims should be benchmarked or demonstrated where practical.
Correctness claims should identify the specific class of bugs or unsupported
syntax the dependency would address. Readability claims should show why local
helpers or a narrower module split are insufficient.

## Candidate Categories

### Parser Libraries For Static Extraction

Current pain point:

- Several extractors still rely on hand-written scanners for language and
  shell-family syntax.
- Static extraction must remain non-executing and must preserve conservative
  boundaries around dynamic language behavior.

Potential benefit:

- A parser can improve correctness for languages where local scanners are
  approaching grammar complexity.
- It can reduce fragile scanner code if a parser produces stable spans and
  syntax categories.

Risk and cost:

- Parser libraries often add runtime footprint, packaging constraints, syntax
  version choices, transitive dependencies, and platform concerns.
- A parser can tempt the project into overclaiming runtime truth from syntax.
- Parser adoption still requires RepoMap-specific redaction, static-only
  policy, observation modeling, fixtures, and canonicalization contracts.

Recommendation:

- Defer.
- Consider only when a specific extractor family hits a clear
  correctness/maintenance wall and a dedicated ADR can define parser safety,
  packaging, supported syntax, fixture coverage, and fallback behavior.
- Do not add a generic parser dependency merely to shrink scanner code.

### SQL And Query Composition Helpers

Current pain point:

- Storage and readback SQL is extensive, and generated query strings can be
  hard to review.
- REF4 separated SQL helpers and row mapping enough to make many queries easier
  to locate.

Potential benefit:

- A query composition helper could reduce string assembly mistakes and make
  parameter handling more uniform.

Risk and cost:

- Hiding SQL behind a generic abstraction can make graph/readback behavior less
  inspectable.
- Storage migrations and integration tests already exercise real Postgres
  behavior.
- A dependency may add little value unless query construction itself becomes a
  recurring bug source.

Recommendation:

- Defer.
- Keep SQL inspectable and explicit for now.
- Reconsider only if future storage phases show repeated review pain, bug
  density, or genuinely unsafe query assembly that small local helpers cannot
  address.

### CLI Output And Table Helpers

Current pain point:

- CLI output code is verbose in places, especially for JSON/table projection.
- REF3 and later storage splits reduced some dispatch and presentation
  concentration without a formatting dependency.

Potential benefit:

- A table/output helper could reduce formatting boilerplate and improve
  consistency.

Risk and cost:

- CLI output shapes are public behavior and must remain stable.
- Output dependencies can make compact commands harder to reason about and can
  complicate smoke/container behavior.
- The likely performance benefit is low.

Recommendation:

- Avoid for now.
- Prefer small local formatting helpers where they preserve explicit output
  contracts.
- Revisit only if table rendering becomes a clear source of bugs or unreadable
  local code.

### TOML, YAML, And JSON Handling

Current pain point:

- RepoMap extracts structured configuration while avoiding target execution and
  secret capture.
- Python has stdlib support for TOML reading and JSON, but YAML remains more
  complex and currently depends on conservative local parsing choices.

Potential benefit:

- A structured parser can improve correctness for some formats and reduce
  hand-written edge cases.

Risk and cost:

- Format parsers can carry nontrivial transitive risk or surprising behavior.
- The extractor contract still needs bounded redaction, path/line evidence,
  diagnostics, and static-only semantics.
- Convenience alone is not enough reason to add a parser.

Recommendation:

- Avoid or defer.
- Do not add TOML/YAML/JSON dependencies merely for convenience.
- Consider a parser only when a specific format's correctness gap is documented
  and a dedicated ADR defines safety, dependency, fixture, and compatibility
  requirements.

### Graph Algorithm Utilities

Current pain point:

- RepoMap stores graph facts and supports bounded readback, but most current
  traversal and summary needs remain simple database queries.

Potential benefit:

- A graph library could help if future analysis needs real graph algorithms,
  ranking, clustering, or path search outside ordinary SQL.

Risk and cost:

- A graph utility dependency may duplicate Postgres responsibilities or pull
  too much graph state into process memory.
- It could encourage broad, expensive traversals that conflict with bounded
  readback and private-data safety.

Recommendation:

- Defer.
- Reconsider only when a concrete feature requires graph algorithms beyond
  bounded SQL queries and the memory/privacy boundary is explicit.

### Static Analysis And Code Inventory Tools

Current pain point:

- REF2 used small one-off stdlib and shell inventory commands to identify
  large files, functions, and import clusters.

Potential benefit:

- A dedicated static analysis tool could improve repeatability for future
  refactor tracking or contributor reports.

Risk and cost:

- Inventory tooling is not runtime behavior and does not justify runtime
  dependencies.
- Tool output can become noisy if it is not tied to a maintained workflow.

Recommendation:

- Keep as optional local/development tooling for now.
- Consider project-maintained tooling only if a later contributor workflow
  needs repeatable reports and the tool can remain outside runtime
  dependencies.

### Test Helper Libraries

Current pain point:

- REF8 showed repeated CLI/storage test setup, and more test duplication
  remains in large test files.

Potential benefit:

- Test helper libraries can reduce boilerplate for filesystem, subprocess, or
  assertion patterns.

Risk and cost:

- Generic test helper frameworks can hide behavior assertions and make safety
  boundaries harder to see.
- RepoMap's current tests already use pytest/unittest and the local Postgres
  harness.
- REF8 demonstrated that small local helpers are sufficient for the first
  consolidation seam.

Recommendation:

- Avoid for now.
- Continue with small domain-named local test support helpers.
- Reconsider only if a repeated test pattern cannot be made readable with local
  helpers.

## Consequences

RepoMap keeps its dependency surface small after REF9.

This preserves:

- simple container smoke builds;
- straightforward CLI/MCP packaging;
- inspectable static extraction behavior;
- explicit SQL and graph readback contracts;
- low transitive dependency risk; and
- easier review of behavior-preserving refactor phases.

Future proposals remain possible. They must name the concrete problem, compare
local-code alternatives, document public project-fit criteria, and include
verification appropriate to the affected boundary.

## Non-Goals

REF9 does not:

- add dependencies;
- remove dependencies;
- change dependency versions;
- change `pyproject.toml`;
- change lockfiles;
- replace working stdlib code;
- adopt formatting or linting tools;
- implement parser-library migration;
- implement static analysis tooling;
- change source, tests, CLI/MCP behavior, storage, extraction,
  canonicalization, schema, migrations, runtime behavior, smoke behavior, or
  test runner policy; or
- include private dependency preferences or private license commentary.

## Private-Data Boundary

This ADR includes only public project criteria and category-level analysis. It
does not include private graph data, database dumps, backup receipts, raw
private observations, private repository source snippets, local operator config,
secrets, private path examples, or private dependency/license preferences.
