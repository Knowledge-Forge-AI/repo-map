# RepoMap Coding Standards

RepoMap code should be idiomatic for the language it is written in, with local
project conventions taking priority over generic style preferences. These are
defaults for new or touched code, not permission for broad rewrites: existing
project style, compatibility contracts, tests, public APIs, documented
behavior, and explicit phase scope take precedence. If a standard conflicts
with the current codebase or a narrow task, preserve behavior and document
the tradeoff.

## General Engineering Defaults

- Prefer small, auditable changes.
- Preserve public behavior unless the accepted scope explicitly authorizes a
  behavior change, and add or update tests for behavior changes.
- Use clear names and simple control flow; prefer deterministic behavior
  over cleverness.
- Prefer bounded output over unbounded output, and explicit data contracts
  over inferred side effects.
- Keep error messages useful, bounded, and sanitized. Do not silently ignore
  failures.
- Never expose secrets, tokens, private paths, local usernames, raw dumps,
  private payloads, private graph data, DB dumps, backup receipts, or local
  runtime details in public outputs.
- Avoid speculative abstractions, and avoid broad cleanup mixed into
  feature, bugfix, extraction, storage, docs, or test phases. Do not
  refactor unrelated code merely because it is nearby.
- Use industry-standard patterns when doing so improves readability and
  maintainability.
- Preserve compatibility facades and public imports unless the phase
  explicitly authorizes narrowing them.

## Python Style

- Write idiomatic Python. Follow PEP 8 and use PEP 20 as a guide for
  judgment.
- Do not turn Python into Java by adding service/repository layers or
  abstract class hierarchies without a concrete RepoMap need.
- Prefer clear functions, small modules, dataclasses, typed dictionaries,
  and ordinary data structures over ceremony. Prefer the standard library
  when it is sufficient.
- Treat maintained handwritten Python files over 400 lines as an
  architectural warning and files over 800 lines as a crisis requiring
  decomposition or an explicit bounded decision. The separate executable
  thresholds are owned by `docs/contrib/file-length-profile.md`.
- Avoid hidden global mutable state.
- Do not catch broad exceptions unless re-raising or returning a clear
  bounded diagnostic.
- Use `pathlib.Path` for filesystem paths when practical.
- Keep private/local paths out of public JSON, tables, logs, docs, reports,
  and tests.
- Keep error messages actionable and specific enough for CLI, MCP, and test
  failures.

Go code follows `docs/contrib/go-standards.md`.

## Project Shape

- Preserve the existing project layout unless an accepted refactor phase
  changes it.
- Prefer existing module patterns and helper APIs over new parallel
  conventions.
- Keep modules focused. Split code when it separates real responsibilities,
  not merely to make a layer diagram look tidy.
- Separate IO, parsing/scanning, domain decisions, storage/query logic, and
  formatting when that reduces coupling or makes tests clearer.
- Keep boundary inputs and outputs explicit. Avoid global mutable state
  unless it is clearly part of a controlled process boundary.

## Abstractions

- Add an abstraction when it removes real complexity, reduces meaningful
  duplication, or makes a boundary easier to test.
- Small duplication is acceptable when a shared abstraction would obscure
  the behavior or force unrelated callers together.
- Keep dependencies between modules loose. Use simple data contracts at
  extractor, canonicalization, storage, readback, CLI, and MCP boundaries.
- Prefer bounded, honest unknowns over false precision in extraction and
  canonicalization.

## Extraction And Safety

- RepoMap extraction is static by default. Do not execute target repository
  code, scripts, shell or PowerShell profiles, tests, package managers,
  generated command strings, or repo-local tools as part of extraction.
- Treat observed source facts as source/configuration/test intent unless
  runtime execution is actually performed by a RepoMap-owned command whose
  scope explicitly allows it.
- Preserve evidence paths and line ranges when available.
- Preserve confidence boundaries: extracted, heuristic, manual, unknown,
  dynamic, or unsupported must not be collapsed into false certainty. Mark
  dynamic or unsupported constructs as bounded unknowns instead of guessing
  graph edges.
- Keep raw extractor output exportable as JSONL, and keep normalized graph
  data stored through the accepted Postgres/storage contracts.
- Redact first. Fixtures, docs, and tests must be public-safe and must not
  include secrets, private source snippets, private graph payloads, DB
  dumps, or operator receipts.
- Keep CLI and MCP behavior bounded, deterministic, and explicit about what
  was observed versus what actually ran.

## PostgreSQL And Storage

- Use parameterized queries when a driver supports them, and keep
  transaction boundaries explicit.
- Avoid generating huge client-side SQL scripts when a safer driver, `COPY`
  path, or staged ingest path is authorized.
- Keep connection details out of logs, reports, committed docs, and public
  errors. Sanitize database names, hosts, usernames, connection strings,
  local paths, and private runtime identifiers in public output.
- Do not change SQL text, schema, migrations, storage behavior, canonical
  graph vocabulary, or readback defaults unless the phase explicitly
  authorizes it.
- Keep legacy and canonical readback behavior compatible unless the accepted
  phase changes that contract.

## Scope Discipline

- Keep phase work scoped to the accepted boundary.
- Do not smuggle unrelated refactors into extraction, storage, testing, or
  docs phases.
- Record intentional deferrals in status docs instead of quietly expanding
  the slice.
