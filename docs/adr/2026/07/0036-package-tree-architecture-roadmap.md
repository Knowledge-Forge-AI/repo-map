# ADR 0036: Package Tree Architecture And Module Size Crisis Policy

## Status

Accepted.

## Date

2026-07-05

## Context

REF3 through REF9 improved several local seams:

- REF3 split CLI parser construction and command dispatch;
- REF4 split storage readback helpers;
- REF5 split local ops and runtime boundaries;
- REF6 extracted small extractor scanner, redaction, and observation helpers;
- REF7 split canonicalization core and dispatch helpers;
- REF8 consolidated the first CLI test-support helpers; and
- REF9 evaluated future dependency categories and added no dependencies.

Those phases helped, but they did not solve RepoMap's broader package-shape
problem. The root `repomap_kg` package is still mostly flat, and several major
subsystems still live as large root-level modules. Current root-module size
inventory still includes:

| Module | Lines | Classification |
| --- | ---: | --- |
| `canonicalization.py` | 13,091 | extreme crisis |
| `config_extractor.py` | 8,148 | extreme crisis |
| `storage_rows.py` | 4,205 | crisis |
| `bash_extractor.py` | 3,555 | crisis |
| `powershell_extractor.py` | 3,377 | crisis |
| `zsh_extractor.py` | 3,113 | crisis |
| `storage_sql.py` | 2,840 | crisis |
| `source_ingestion.py` | 2,450 | crisis |
| `javascript.py` | 2,429 | crisis |
| `python_extractor.py` | 2,150 | crisis |
| `ops_config.py` | 2,024 | crisis |

Large flat modules create review, navigation, ownership, import, and change-risk
problems. A contributor trying to work on one extractor family, one canonical
family, or one storage projection must still page through unrelated code.

Package migration should be planned before source moves begin. PKG0 records the
target architecture and migration order, but it moves no source files.

## Decision

RepoMap will move toward a domain-oriented package tree for `repomap_kg`.

The migration will be behavior-preserving by default. It will use compatibility
facades for current public import paths, move one subsystem at a time, and run
the full source final gate for every source-moving phase.

RepoMap also adopts an explicit source module size policy:

- preferred module size: under 1,000 lines where practical;
- acceptable module size: 1,000-1,500 lines for cohesive complex modules;
- warning threshold: 1,500-2,000 lines;
- crisis threshold: over 2,000 lines;
- extreme crisis threshold: over 5,000 lines.

These are reviewability and maintainability thresholds, not arbitrary formatting
targets. A module can temporarily exceed a threshold for a coherent reason, but
the reason must be explicit and the reduction plan must be tracked.

`canonicalization.py` remains an unresolved extreme crisis after REF7. It must
be driven below 2,000 lines through multiple focused family-split phases.

PKG0 adds no dependencies and changes no package metadata.

## Target Package Tree

This target describes direction, not an exact one-phase implementation. Names
can change during implementation if the source layout reveals a safer seam.

```text
repomap_kg/
  cli/
    __init__.py
    main.py
    parser.py
    dispatch.py
    commands/
      storage.py
      ops.py
      local.py
      mcp.py

  extractors/
    __init__.py
    shell/
      __init__.py
      bash.py
      zsh.py
      awk.py
      bats.py
      zunit.py
      powershell.py
    languages/
      __init__.py
      python.py
      javascript.py
      ruby.py
    documents/
      __init__.py
      markdown.py
      html.py
      css.py
      xml.py
      email.py
    config/
      __init__.py
      generic.py
      openapi.py
      terraform.py
      nix.py
    shared/
      __init__.py
      scanner.py
      redaction.py
      observations.py

  canonicalization/
    __init__.py
    facade.py
    core.py
    dispatch.py
    families/
      __init__.py
      files.py
      shell.py
      languages.py
      config.py
      documents.py
      feeds.py
      tests.py
      api.py

  storage/
    __init__.py
    facade.py
    rows.py
    sql.py
    psql.py
    legacy.py
    canonical.py
    summaries.py
    migrations.py

  ops/
    __init__.py
    config.py
    refresh.py
    preflight.py
    baselines.py
    reports.py

  runtime/
    __init__.py
    local.py
    plan.py
    commands.py
    backup.py

  server/
    __init__.py
    mcp.py
    http.py

  graph/
    __init__.py
    keys.py
    models.py
    diagnostics.py

  observations/
    __init__.py
    raw.py
    io.py
```

The target packages are domain-oriented. They are not Java-style service or
repository layers, and they should not introduce abstract class hierarchies
without a concrete RepoMap problem.

## Compatibility Strategy

Current public imports should keep working during migration through facade
modules and re-exports. Important compatibility surfaces include:

- `repomap_kg.cli`;
- `repomap_kg.storage`;
- `repomap_kg.canonicalization`;
- `repomap_kg.ops_refresh`;
- `repomap_kg.local_runtime`;
- language and extractor modules that tests or downstream users import
  directly.

Internal imports should move gradually to package paths after the target module
exists and tests prove behavior is unchanged.

Compatibility shims are allowed during migration. They must be documented, kept
thin, and removed only in a dedicated cleanup phase after internal imports have
been migrated and downstream compatibility expectations are explicit.

## Migration Principles

Package moves and behavior-sensitive logic splits should not be mixed unless the
slice is tiny and fully characterized.

Each source-moving phase should:

- move one subsystem or one family at a time;
- preserve public behavior and current import compatibility;
- avoid dependency additions;
- avoid package metadata changes unless explicitly required and approved;
- avoid broad formatting churn;
- keep source moves mechanical where possible;
- update tests only to follow moved import paths or preserve compatibility
  assertions;
- run scoped tests during development; and
- run the full final source gate before commit.

PKG0 itself is docs-only and performs none of those source moves.

## Proposed Migration Phases

The package-tree migration should proceed in small phases:

1. PKG1: Introduce package directories and compatibility facade pattern.
2. PKG2: Move CLI modules into `repomap_kg.cli`.
3. PKG3: Move storage modules into `repomap_kg.storage`.
4. PKG4: Move ops and runtime modules into `repomap_kg.ops` and
   `repomap_kg.runtime`.
5. PKG5: Move extractor modules into `repomap_kg.extractors.*`.
6. PKG6: Move graph, observations, diagnostics, and shared model modules.
7. CANON1: Split file, config, document, and feed canonicalization families.
8. CANON2: Split shell-family canonicalization.
9. CANON3: Split source-language canonicalization.
10. CANON4: Split test-framework and API canonicalization.
11. CANON5: Characterize dispatch-table behavior and clean up the
    canonicalization facade.
12. PKG-CLEAN: Remove obsolete compatibility shims after internal imports
    migrate.

This sequence is intentionally conservative. It favors reviewable moves over a
large package flip.

## Canonicalization Crisis Plan

REF7 was only a first split. It moved shared node, edge, evidence, confidence,
metadata, and dispatch support helpers, but it did not solve the
`canonicalization.py` extreme crisis.

Canonicalization reduction should proceed through focused family phases:

- file and graph-key-adjacent canonicalization;
- config, document, feed, API, and archive families;
- shell-family facts, including Bash, Bats, awk, zsh, zunit, and PowerShell;
- source-language facts, including Python, JavaScript, Ruby, and related
  ecosystem facts;
- test-framework and remaining specialized families; and
- dispatch-table characterization after family moves are stable.

Each CANON phase must preserve canonical graph output exactly unless a separate
behavior phase is approved. That includes:

- canonical node and edge kinds;
- canonical keys;
- identity metadata;
- metadata fields;
- confidence values;
- conflict markers;
- evidence links;
- raw-only/deferred observation behavior;
- unsupported diagnostics; and
- canonical output ordering.

Dispatch order is behavior-sensitive and must be characterized before any
rewrite into a table or registry.

## Consequences

This plan creates a larger refactor sequence, but lowers review risk.

Expected benefits:

- better navigation for humans and agents;
- clearer subsystem ownership;
- smaller review surfaces;
- less accidental cross-subsystem coupling;
- explicit compatibility surfaces during migration; and
- a concrete path to reduce crisis-sized modules.

Costs:

- temporary compatibility facades and re-exports;
- more phases before the package tree feels complete;
- a later cleanup phase to remove obsolete shims; and
- careful import choreography to avoid circular imports.

## Non-Goals

PKG0 does not:

- move source files;
- update imports;
- split `canonicalization.py`;
- change production behavior;
- change tests;
- change package metadata;
- change lockfiles;
- add dependencies;
- change test runner policy;
- change runtime behavior;
- change CLI/MCP behavior;
- change extraction, canonicalization, storage, schema, or migrations; or
- remove compatibility imports or shims.

## Private-Data Boundary

This ADR includes only public project structure and maintenance policy. It does
not include private graph data, database dumps, backup receipts, raw private
observations, private repository source snippets, local operator config, secret
values, generated smoke artifacts, or private path examples.
