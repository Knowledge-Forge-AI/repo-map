# ADR 0037: Psycopg Runtime Dependency Candidate

## Status

Accepted as a runtime dependency candidate.

DEPS-PSYCOPG0 adds no dependency and changes no package metadata, lockfiles,
production code, tests, imports, exports, SQL, psql behavior, CLI behavior, MCP
behavior, schemas, migrations, storage table shapes, or graph registry behavior.

## Date

2026-07-08

## Context

ADR 0035 accepted a conservative post-refactor dependency stance: REF9 added no
dependencies, and future adoption must be problem-driven. A candidate must be
evaluated for performance impact, correctness, readability and maintainability,
local-code reduction, stability, supply-chain and transitive risk, license
compatibility, runtime footprint, CLI/MCP/storage/smoke/container compatibility,
supported Python versions, deterministic behavior, clear failure behavior, and
ease of removal.

Phase F is now closed by PHASE-F-CLOSE1. The storage SQL split, summary row
split, package cleanup, live smoke, automated smoke hardening, and final Phase F
closeout are complete. That gives the project a clearer view of the remaining
storage transport pressure.

RepoMap still has zero runtime dependencies. The current storage path builds
large SQL scripts and invokes `psql` through `repomap_kg.storage.psql`. Storage
readback modules call that seam and parse JSON from `psql` output. Storage
ingest currently generates SQL text in local builders, including SQL literals
for structured JSON payloads.

The fresh dependency recommendation in
`2026_07_07-repo_map-dependency-recommendation.md` intentionally reconsidered
dependencies with the priority order:

1. performance;
2. readability;
3. reducing lines of code.

It found that discovery and canonical preparation are reasonably fast, while
storage ingestion and transport are the first dependency-worthy pressure point.
The recommendation ranks Psycopg 3 first because it could remove client-side SQL
literalization pressure and enable parameterized statements, prepared
statements, pipeline mode, and eventually COPY or staging-table ingest. It also
recommends preserving the existing `psql` path as a compatibility fallback until
benchmarks and integration tests prove parity.

## Decision

The fresh dependency recommendation materially changes ADR 0035's conservative
conclusion for one narrow problem: PostgreSQL transport and storage readback.
It does not reverse ADR 0035's general stdlib/local-code default.

RepoMap accepts Psycopg 3 as the first runtime dependency candidate.
DEPS-PSYCOPG0 does not add Psycopg, alter package metadata, alter lockfiles, or
change runtime behavior.

All other runtime dependency candidates remain deferred. This includes
Tree-sitter, PyYAML, orjson, msgspec, lxml, SQLAlchemy, NetworkX, igraph,
Polars, PyArrow, DuckDB, Pydantic, attrs, cattrs, pathspec, and any broad
parser, validation, graph, dataframe, ORM, YAML, XML, or JSON dependency.

The project should use a staged Psycopg adoption path:

1. PSYCOPG1 should design or characterize a readback adapter pilot behind the
   existing `psql` fallback.
2. PSYCOPG2 may implement readback through that adapter only after the adapter
   contract and fallback behavior are pinned.
3. PSYCOPG3 must produce benchmark and parity evidence before any path is
   replaced.
4. PSYCOPG4 may design ingest, COPY, or staging-table work only after readback
   is proven.

The first implementation pilot should target readback, not ingest. Readback is
the safer pilot because it can compare existing `psql` JSON output, row parser
results, error behavior, CLI behavior, and MCP behavior without changing write
paths or storage table contents. Ingest should remain design-only until readback
performance, parity, and fallback behavior are proven.

## Dependency Form

The candidate form for local pilot work is:

```text
psycopg[binary]>=3.2,<4
```

That form is acceptable as a pilot target because it is easy to install in local
and smoke environments and keeps the project inside Psycopg 3. It is not yet an
adopted runtime dependency.

Before distribution or commercialization, the project should recheck whether the
final packaging form should be:

- plain `psycopg`, relying on an externally provided `libpq`;
- `psycopg[c]`, using the C optimization package where build/runtime conditions
  make that appropriate;
- `psycopg[binary]`, accepting binary-wheel convenience with additional native
  component and redistribution review; or
- a documented staged choice, such as binary wheels for local/dev pilots and
  plain or C-backed builds for release packaging.

The staged choice is preferred now. `psycopg[binary]>=3.2,<4` remains the
candidate pilot spec, while final release packaging should be decided only after
benchmark, compatibility, and license review gates.

## License Review

This section records public project evidence and high-level obligations. It is
not legal advice.

Public evidence reviewed:

- PyPI `psycopg` reports license expression `LGPL-3.0-only`, Python support
  `>=3.10`, and current Psycopg 3 package metadata.
- PyPI `psycopg-binary` reports license expression `LGPL-3.0-only`, Python
  support `>=3.10`, and the same upstream project URLs.
- PyPI `psycopg-c` also reports license expression `LGPL-3.0-only`; it is
  relevant if the project later evaluates `psycopg[c]`.
- Upstream `LICENSE.txt` in the Psycopg repository contains GNU Lesser General
  Public License version 3 text.
- Upstream README documentation describes the pure Python package, the binary
  extra, the C optimization package, and the system `libpq` dependency for the
  plain package.

Relevant public URLs:

- <https://pypi.org/project/psycopg/>
- <https://pypi.org/project/psycopg-binary/>
- <https://pypi.org/project/psycopg-c/>
- <https://github.com/psycopg/psycopg>
- <https://github.com/psycopg/psycopg/blob/master/LICENSE.txt>

High-level LGPL-3.0-only implications:

- Using an LGPL library as a dependency does not, by itself, require RepoMap's
  own code to be licensed under LGPL.
- Obligations focus on conveying the LGPL-covered library and any modifications
  to that library.
- Distribution should preserve notices, include or point to the LGPL license
  text, and provide source or a compliant offer for the LGPL-covered library and
  modifications when required.
- Distribution should not prevent users from replacing or relinking the LGPL
  library where the license requires that ability.
- Modifications to Psycopg itself would need careful source and notice handling.
- Static or non-replaceable bundling, native binary redistribution, commercial
  packaging, or dual-license distribution should receive counsel review before
  release.

RepoMap should document notices and license-copy handling before adoption. At
minimum, the adoption phase should add a public dependency notice that names
Psycopg, records `LGPL-3.0-only`, links the upstream license, and states whether
the selected packaging form is plain, C-backed, binary-wheel based, or staged.

Counsel review is recommended before any distributed or commercialized release
that includes Psycopg, especially if the release uses `psycopg[binary]`,
bundles native libraries, modifies Psycopg, or combines RepoMap distribution
with a commercial licensing program.

## Required Evidence Before Replacement

Before replacing any existing `psql` path, a later phase must provide:

- characterization tests for adapter input, output, and failure semantics;
- parity tests showing the same row records, JSON shapes, CLI output, MCP
  output, and user-facing error categories as the existing path;
- fallback tests proving `psql` remains available when Psycopg is unavailable,
  misconfigured, or unsuitable for a specific operation;
- benchmark evidence for representative readback commands;
- integration evidence against disposable Postgres only in a phase that
  explicitly authorizes database/container execution;
- deterministic ordering and JSON conversion checks;
- package metadata and lockfile review;
- public license/notice review for the selected packaging form; and
- removal guidance if the pilot fails.

Ingest replacement requires additional evidence and is deferred until readback
is proven. Any ingest proposal must compare generated SQL, parameterized
statements, prepared statements, pipeline mode, COPY, and staging-table
approaches against the current completed-run and table-shape contracts.

## What Remains On `psql`

The existing `psql` path must remain:

- as the compatibility fallback during the Psycopg transition;
- as the comparison oracle for adapter characterization and parity tests;
- for bootstrap or migration paths that are still explicitly psql-oriented;
- for environments where Psycopg, `libpq`, native wheels, or C extensions are
  unavailable or not yet accepted;
- for emergency/manual local operation while the adapter is being evaluated;
  and
- for any operation not explicitly moved by a later ADR-backed implementation
  phase.

## Legacy Command Boundary

DEPS-PSYCOPG0 does not canonicalize storage readback commands. The following
commands remain outside this dependency candidate decision:

- `storage files`;
- `storage entrypoints`;
- `storage file-nodes`.

They remain legacy-default because:

- `storage files` is a stored file-row inventory surface;
- `storage entrypoints` lacks an accepted cross-language canonical entrypoint
  model; and
- `storage file-nodes` is legacy-specific enough that default migration would
  be misleading.

A later LEGACY-CMDS0 or READBACK-CANON0 phase should revisit those command
defaults separately. That phase should not be combined with dependency
adoption.

## Consequences

Positive consequences:

- RepoMap gets a concrete first runtime dependency candidate tied to the
  highest-priority performance pressure.
- The existing conservative dependency policy remains intact for every other
  category.
- The pilot can start with readback, where fallback and parity are easier to
  prove.
- The `psql` seam stays available as a rollback and comparison boundary.

Negative or risky consequences:

- Psycopg introduces the first runtime dependency if a later phase adopts it.
- The LGPL-3.0-only license requires notices and distribution review.
- Binary-wheel convenience may create native-component and redistribution
  questions that plain `psycopg` or `psycopg[c]` handle differently.
- Adapter work can add temporary parallel paths until parity is proven.

Explicit deferrals:

- adding Psycopg to package metadata;
- changing package metadata or lockfiles;
- changing storage readback, ingest, SQL, psql, CLI, MCP, schema, migration, or
  lifecycle behavior;
- implementing COPY, staging tables, prepared statements, or pipeline mode;
- adopting any non-Psycopg runtime dependency;
- canonicalizing the remaining legacy-default storage commands; and
- running discovery, graph refresh, live smoke, or real graph database mutation.
