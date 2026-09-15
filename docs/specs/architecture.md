# RepoMap Architecture

Status: historical design baseline. For the current implemented architecture,
use [RepoMap As-Built Architecture](as-built-architecture.md), ADR 0041, and the
ARCH-CLOSE status record. This document remains useful for original intent but
does not override later source, migrations, tests, or accepted normalization
decisions.

## Purpose

RepoMap builds a deterministic knowledge graph for a source repository. It is
intended for polyglot projects where behavior crosses language boundaries
through scripts, wrappers, configuration, generated files, tests, and host
tooling.

The first proving ground is a mixed Nix, shell, Python, Ruby, awk, and
AppleScript repository. The public design remains general: repository-specific
rules belong in profiles.

## Non-Goals

- RepoMap does not use an LLM to invent graph edges.
- RepoMap is not a replacement for reading source code.
- RepoMap does not execute arbitrary project code during default indexing.
- RepoMap does not try to perfectly resolve all dynamic shell or Nix behavior.
- RepoMap does not require an MCP server for the core product to be useful.

## High-Level Flow

```text
repository checkout
  -> discovery
  -> language extractors
  -> raw observations JSONL
  -> normalization and validation
  -> Postgres graph store
  -> CLI queries, reports, and optional adapters
```

## Components

### Discovery

Discovery walks the repository, applies ignore rules, detects languages, and
classifies high-level roles such as source file, executable script, config file,
test file, generated artifact, or profile-defined entry point.

Detection should use file extension, shebang, executable bit, directory role,
and optional project profile hints.

The initial discovery implementation emits `file` raw observations with
repository-relative path, detected language, role, executable flag, generated
flag, and SHA-256 content hash metadata.

### Extractors

Extractors are deterministic modules that read one language or file family and
emit raw observations. They should preserve file and line evidence whenever
possible.

Initial extractor families:

- Python: imports, modules, classes, functions, calls, CLI-oriented files.
- Shell: shebangs, functions, source/include relationships, command
  invocations, env reads/writes, redirections, and host-mutating operations.
- Nix: imports, flake outputs, packages, apps, checks, dev shells, script
  references, and optional safe evaluation facts.
- Ruby: requires, classes/modules, methods, executable scripts, simple calls.
- Awk and AppleScript: file-level and entry-point facts at first.

### Raw Observation Stream

Extractors write raw JSONL observations before normalization. This keeps the
pipeline inspectable and makes extractor debugging easier.

### Normalizer

The normalizer converts raw observations into canonical nodes, edges, evidence,
and run metadata. It should validate required fields, deduplicate stable facts,
and preserve extractor confidence.

### Storage

The primary store is Postgres. The graph is stored in relational tables with a
property-graph shape: nodes, edges, evidence, runs, files, symbols, test cases,
and metadata.

The inactive portable-worker seam emits a deterministic seven-family bundle
without database credentials. Its inherited staging-row shape uses only the
fixed non-authoritative `stage-unassigned` placeholder. The current staged
PostgreSQL publisher remains the sole graph mutator, and no production route
consumes that bundle before STR-PUB5.

### Query Layer

The CLI should answer common repository questions without forcing users to write
SQL. Examples:

- `repomap-kg entrypoints <raw-observations.jsonl>`
- `repomap-kg files <raw-observations.jsonl>`
- `repomap-kg explain <path>`
- `repomap-kg callers <path-or-symbol>`
- `repomap-kg tests-for <path>`
- `repomap-kg host-mutators`
- `repomap-kg paths <from> <to>`

### Profiles

Profiles describe project conventions outside the generic engine. A profile may
declare user-facing command directories, internal script directories, test
runners, generated artifact locations, or confidence adjustments.

Profiles must not be required for basic indexing, but they are the right place
for project-specific knowledge.

The initial profile schema is documented in
[Project Profile Schema](profile-schema.md).

## Confidence Model

Every graph edge should carry a confidence value:

- `extracted`: parsed directly from source or trusted structured metadata.
- `heuristic`: inferred from names, command text, or conventions.
- `manual`: declared by a profile or user-maintained manifest.
- `unknown`: dynamic behavior was detected but not resolved.

The graph should prefer an honest partial answer over a confident wrong answer.
