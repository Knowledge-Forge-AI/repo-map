# RepoMap Refactor Roadmap

REF2 is the readability and refactor architecture checkpoint. It does not
change production code. It records the current pressure points and defines an
incremental, behavior-preserving path toward a more comprehensible RepoMap code
base.

This roadmap follows:

- [coding standards](coding-standards.md);
- [testing standards](testing-standards.md);
- [dependency standards](dependency-standards.md);
- [review standards](review-standards.md).

## Goals

RepoMap should become easier for human contributors and AI coding agents to
understand without losing its current behavior.

The refactor goals are:

- make module responsibilities easier to see;
- reduce oversized files and oversized functions;
- separate parsing, scanning, query construction, domain decisions, storage
  row mapping, command dispatch, and output formatting when that makes tests
  clearer;
- preserve public CLI, MCP, storage, extraction, canonicalization, and
  readback behavior unless a later phase explicitly accepts a behavior change;
- keep Python idiomatic, functional where appropriate, and light on ceremony;
- avoid generic service/repository layers and abstract class hierarchies that
  do not solve a concrete RepoMap problem.

## Non-Goals

The refactor phaseset is not a license to change behavior under the word
"cleanup."

Do not mix refactor phases with:

- CLI output changes;
- MCP tool contract changes;
- storage schema or migration changes;
- canonical graph vocabulary changes;
- extraction semantics changes;
- test runner behavior changes;
- new dependencies;
- broad formatting churn;
- private graph refreshes or private data capture.

Any phase that intentionally changes behavior must say so before implementation
starts and must use source-change verification.

## Inventory Method

REF2 used stdlib and shell inventory only. No new tools or dependencies were
added.

Commands used:

```sh
find src/main/python tools -type f -name '*.py' -print0 | xargs -0 wc -l | sort -n | tail -40
find src/test/unit/python src/test/int/python -type f -name '*.py' -print0 | xargs -0 wc -l | sort -n | tail -40
```

REF2 also used a small `ast` script to list the largest functions/classes by
source line span, and a small `ast` script to count local import clusters. The
scripts were one-off inventory commands and were not committed.

## Inventory Findings

The current source tree is functional, well-tested, and increasingly difficult
to navigate by file size.

Largest source/tool modules observed in REF2:

| File | Lines | Main pressure |
| --- | ---: | --- |
| `src/main/python/repomap_kg/canonicalization.py` | 13,254 | family-specific canonicalizers and orchestration live in one file |
| `src/main/python/repomap_kg/config_extractor.py` | 8,148 | many config formats, summaries, and scanners share one module |
| `src/main/python/repomap_kg/storage.py` | 7,635 | SQL, load prep, row parsing, legacy readback, canonical readback, summaries, and formatting support are concentrated |
| `src/main/python/repomap_kg/cli.py` | 3,633 | parser construction, dispatch, command implementation, and output decisions are concentrated |
| `src/main/python/repomap_kg/bash_extractor.py` | 3,564 | scanner logic and observation construction are intertwined |
| `src/main/python/repomap_kg/powershell_extractor.py` | 3,377 | scanner logic and side-effect classification are intertwined |
| `src/main/python/repomap_kg/zsh_extractor.py` | 3,120 | scanner logic, dialect rules, and observation construction are intertwined |
| `src/main/python/repomap_kg/ops_refresh.py` | 2,923 | preflight, refresh orchestration, baselines, drift checks, and reports share one module |
| `src/main/python/repomap_kg/source_ingestion.py` | 2,450 | source acquisition planning, matching, ingestion, and persistence are coupled |
| `src/main/python/repomap_kg/javascript.py` | 2,429 | broad language extraction logic is concentrated |

Largest function/class spans observed in REF2:

| Function or class | Lines | File |
| --- | ---: | --- |
| `main` | 1,511 | `cli.py` |
| `build_parser` | 1,370 | `cli.py` |
| `canonicalize_observations` | 1,245 | `canonicalization.py` |
| `extract_javascript_file_observations` | 899 | `javascript.py` |
| `extract_ruby_file_observations` | 488 | `ruby.py` |
| `python_web_framework_observations` | 319 | `python_extractor.py` |
| `_side_effect_observations_for_command` | 271 | `powershell_extractor.py` |
| `tool_definitions` | 238 | `mcp_server.py` |

Largest test files observed in REF2:

| File | Lines | Main pressure |
| --- | ---: | --- |
| `src/test/int/python/repomap_kg/test_storage.int.test.py` | 12,464 | storage integration contracts and helpers are concentrated |
| `src/test/unit/python/repomap_kg/test_cli.unit.test.py` | 7,644 | parser, dispatch, formatting, and command behavior tests share one file |
| `src/test/int/python/repomap_kg/test_cli.int.test.py` | 5,011 | integration CLI scenarios are concentrated |
| `src/test/unit/python/repomap_kg/test_storage.unit.test.py` | 4,985 | storage helper and projection tests are concentrated |
| `src/test/unit/python/repomap_kg/test_canonicalization.unit.test.py` | 4,702 | broad canonicalization contracts are concentrated |
| `src/test/int/python/repomap_kg/test_canonical_contract.int.test.py` | 4,312 | cross-family canonical contracts are concentrated |

Import inventory found two especially central dispatch modules:

- `cli.py` imports 23 local modules and 176 imported names or modules overall.
- `discovery.py` imports 22 local extractor/profile modules.

These modules are legitimate orchestration points, but their current size makes
it hard to distinguish stable contracts from implementation detail.

## Refactor Boundaries

Future refactor phases should move one responsibility boundary at a time.

Good first moves:

- extract pure helpers before changing call sites;
- preserve old public module import paths with thin wrappers when a package
  split would otherwise break callers;
- move tests alongside the boundary they protect;
- keep output formatting separate from query or domain decisions;
- keep scanner/tokenizer code separate from observation construction when the
  split improves readability.

Avoid:

- "cleanup" commits that touch unrelated areas;
- package reshuffles that move many files before tests pin behavior;
- generic interface layers with no concrete caller;
- simultaneous behavior migration and refactor;
- canonical-to-legacy fallback changes hidden inside refactor phases.

## Target Structure

The target structure is incremental. It describes direction, not a requirement
to move every file immediately.

### CLI

Keep the public `repomap_kg.cli` import path stable at first. Split from the
inside out:

```text
repomap_kg/
  cli.py                  # compatibility wrapper and process entrypoint
  cli_parser.py           # parser construction and shared argument helpers
  cli_dispatch.py         # command dispatch only
  cli_output.py           # JSON/table/error presentation helpers
  cli_storage.py          # storage command handlers
  cli_ops.py              # ops/local command handlers
```

If this grows, a later phase can evaluate a `repomap_kg/cli/` package with a
compatibility wrapper. Do not start with a package flip.

### Storage And Readback

Split `storage.py` by behavior boundary, not by fashionable layers:

```text
repomap_kg/
  storage.py              # public compatibility facade
  storage_sql.py          # SQL builders and query text
  storage_rows.py         # row records and row-to-dict helpers
  storage_load.py         # raw/canonical load preparation
  storage_legacy.py       # legacy readback queries
  storage_canonical.py    # canonical readback queries
  storage_summaries.py    # summary projections
```

Keep SQL tests focused on generated queries and row mapping tests focused on
shape. Integration tests continue to prove the real Postgres path.

### Extraction

Language-specific modules may remain direct modules, but shared utilities
should be easier to find:

```text
repomap_kg/
  extractor_scanner.py        # small scanner/token utilities shared by extractors
  extractor_observations.py   # observation builder helpers
  extractor_redaction.py      # shared redaction helpers
```

Future package splits can group shell-family extractors only after shared
utilities are stable. Do not flatten Bash, Bats, awk, zsh, or zunit dialect
facts into a generic shell abstraction.

### Canonicalization

Keep `repomap_kg.canonicalization` stable while extracting family-specific
helpers:

```text
repomap_kg/
  canonicalization.py             # compatibility facade and orchestration
  canonical_core.py               # shared node/edge builder helpers
  canonical_extractors.py         # observation dispatch table
  canonical_shell.py              # shell-family canonicalization
  canonical_config.py             # config/document/API/feed canonicalization
  canonical_languages.py          # language extractor canonicalization
  canonical_tests.py              # Bats/zunit/test framework canonicalization
```

The first useful split is likely a dispatch table plus family helper modules,
not a class hierarchy.

### Local Ops And Runtime

Keep local operational behavior explicit:

```text
repomap_kg/
  ops_config.py          # config parsing and diagnostics
  ops_refresh.py         # public orchestration facade
  ops_preflight.py       # root scans and candidate planning
  ops_baselines.py       # baseline save/prune/drift support
  ops_reports.py         # JSON report projections
  local_runtime.py       # runtime plan facade
  local_runtime_plan.py  # container/runtime plan records
  local_runtime_cmds.py  # Docker/Podman command construction
  local_db_backup.py     # backup lifecycle facade
```

Do not hide destructive operations behind vague abstractions. Backup-first
database lifecycle boundaries must remain obvious in code and tests.

### Tests

The tests should stay behavior-focused while becoming easier to navigate:

```text
src/test/support/python/repomap_kg/
  cli_fakes.py
  storage_fixtures.py
  canonical_fixtures.py
  ops_fixtures.py
  extractor_assertions.py
```

Use shared test helpers only where they remove repeated setup or clarify
contracts. Avoid test helper frameworks that make assertions harder to read.

## Future Phase Roadmap

Each phase below is expected to be behavior-preserving unless it explicitly
says otherwise.

### REF3: CLI Parser And Dispatch Split

Goal:

- reduce `cli.py` by extracting parser construction and command dispatch into
  focused modules while preserving the `repomap_kg.cli` entrypoint.

Likely files:

- `src/main/python/repomap_kg/cli.py`
- new `cli_parser.py`
- new `cli_dispatch.py`
- `src/test/unit/python/repomap_kg/test_cli.unit.test.py`
- `src/test/int/python/repomap_kg/test_cli.int.test.py`

Out of scope:

- changing CLI flags, output, exit codes, storage defaults, or MCP behavior.

Tests:

- focused CLI parser/dispatch unit tests;
- existing CLI integration tests;
- final source gate.

Acceptance:

- `build_parser` and `main` shrink materially;
- public CLI behavior and help text remain stable except for intentionally
  updated module provenance in tests if needed;
- no storage or extraction behavior changes.

Risk: medium, because CLI dispatch touches many commands.

REF3 implementation note: REF3 split parser construction into
`cli_parser.py` and command-selection flow into `cli_dispatch.py` while keeping
`repomap_kg.cli` as the public entrypoint and compatibility export surface.
Command handler extraction remains deferred to later REF phases.

### REF4: Storage Readback Helper Split

Goal:

- split SQL builders, row parsing, canonical projections, legacy projections,
  and summary helpers out of `storage.py`.

Likely files:

- `src/main/python/repomap_kg/storage.py`
- new storage helper modules;
- storage unit and integration tests.

Out of scope:

- schema changes;
- canonical edge vocabulary changes;
- command default changes;
- new readback modes.

Tests:

- storage unit tests for generated row shapes;
- storage integration tests through the containerized Postgres harness;
- final source gate.

Acceptance:

- public storage functions remain import-compatible or are wrapped;
- canonical and legacy readback outputs remain byte-for-byte or
  field-for-field compatible where tests pin them;
- SQL generation and row mapping are testable without CLI setup.

Risk: high, because `storage.py` is large and central.

REF4 implementation note: REF4 kept `repomap_kg.storage` as the compatibility
facade and split storage helpers into focused modules for row/projection
mapping, SQL builders, psql execution, legacy readback, canonical readback,
summary readback, and storage errors. Load orchestration and migration
discovery remain on the facade for now.

### REF5: Local Ops And Runtime Boundary Cleanup

Goal:

- split preflight, baseline, drift, runtime command construction, and report
  formatting helpers from the operational orchestration modules.

Likely files:

- `ops_config.py`
- `ops_refresh.py`
- `local_runtime.py`
- `local_db_backup.py`
- local ops tests.

Out of scope:

- changing `REPOMAP_HOME` behavior;
- changing backup-first lifecycle semantics;
- changing Docker/Podman command behavior;
- changing private graph maintenance policy.

Tests:

- ops config and refresh unit tests;
- integration tests that already exercise temporary runtime/config homes;
- smoke if runtime command construction changes.

Acceptance:

- destructive database operations remain clearly guarded;
- report payloads stay compatible;
- local runtime command construction is easier to unit-test.

Risk: medium-high, because local ops touches private-runtime safety boundaries.

REF5 implementation note: REF5 kept `repomap_kg.ops_refresh` and
`repomap_kg.local_runtime` as compatibility facades while extracting
`ops_reports.py`, `ops_baselines.py`, `ops_preflight.py`,
`local_runtime_plan.py`, and `local_runtime_cmds.py`. It deferred
`local_db_backup.py` because its backup-first lifecycle boundaries are
safety-sensitive and did not have an equally low-risk seam.

### REF6: Extractor Shared Scanner And Observation Helpers

Goal:

- pull small shared scanner, redaction, and observation construction helpers
  out of repeated extractor code.

Likely files:

- shell-family extractors;
- `config_extractor.py`;
- language extractors with large scanner functions;
- new shared helper modules.

Out of scope:

- changing extraction coverage;
- adding parser/runtime dependencies;
- executing target code;
- merging dialect-specific observations into generic kinds.

Tests:

- affected extractor unit tests;
- fixture dogfood tests where present;
- final source gate.

Acceptance:

- observation payloads remain stable;
- secret redaction and static-only metadata stay intact;
- helper names describe actual scanner/observation jobs rather than generic
  architecture layers.

Risk: medium.

REF6 implementation note: REF6 extracted a deliberately small Bash/Zsh helper
seam into `extractor_scanner.py`, `extractor_redaction.py`, and
`extractor_observations.py`. The shared scanner helper is limited to
identifier-part token splitting used by redaction; command scanners, parser
heuristics, observation kinds, payload shapes, and dialect-specific semantics
remain in the dialect extractor modules.

### REF7: Canonicalization Family Split

Goal:

- split `canonicalize_observations` into a clear dispatch table and
  family-specific canonicalization helpers.

Likely files:

- `canonicalization.py`
- new canonical helper modules;
- canonicalization unit tests;
- canonical contract integration tests.

Out of scope:

- new canonical node or edge kinds;
- schema changes;
- storage load changes;
- readback behavior changes.

Tests:

- canonicalization unit tests;
- canonical contract integration tests;
- storage canonical load tests if helper imports move.

Acceptance:

- canonical result payloads remain stable;
- unsupported/raw-only observation diagnostics remain stable;
- family-specific code can be read without paging through unrelated families.

Risk: high, because canonicalization is large and cross-cutting.

REF7 implementation note: REF7 established the first behavior-preserving
canonicalization split by moving shared node, edge, evidence, confidence, and
metadata merge helpers into `canonical_core.py`, plus dispatch state, result
construction, and unsupported-kind diagnostics into `canonical_dispatch.py`.
`canonicalization.py` remains the compatibility facade and still owns the
top-level observation order and family-specific canonicalization functions;
larger family module extraction remains deferred.

### REF8: Test Support Consolidation

Goal:

- reduce large repeated test setup while keeping assertions direct and
  behavior-focused.

Likely files:

- `src/test/support/python/repomap_test_support/`
- large CLI, storage, canonicalization, ops, and extractor tests.

Out of scope:

- changing test runner policy;
- weakening coverage;
- replacing behavior assertions with over-generic fixtures.

Tests:

- the focused tests touched by the helper migration;
- final source gate.

Acceptance:

- repeated setup shrinks;
- test names and assertions remain readable;
- fixtures stay public-safe and temporary.

Risk: medium.

REF8 implementation note: REF8 kept production code untouched and established
the first test-support consolidation in the existing
`repomap_test_support` package. Shared CLI/module invocation, repo/source-root
constants, environment construction, and public-safe text fixture writing now
live in `repomap_test_support.cli`; the large CLI and storage integration tests
use those helpers while keeping behavior assertions at the call sites. Broader
storage fixture, canonical graph, and ops-runtime helper extraction remains
deferred.

### REF9: Dependency Evaluation ADR

Goal:

- evaluate whether a small number of dependencies would materially improve
  performance, readability, or maintenance burden after the first refactor
  splits show what local code remains.

Candidate categories:

- parser libraries for languages where stdlib scanners are no longer adequate;
- SQL/query composition helpers if string assembly remains hard to review;
- CLI output/table helpers if formatting logic remains noisy;
- TOML/YAML/JSON handling if a specific format reaches a documented
  correctness wall;
- static code inventory tools if refactor tracking becomes manual;
- graph algorithm utilities if traversal logic expands beyond simple queries.
- test helper libraries if small local support helpers stop being sufficient.

Out of scope:

- adding dependencies in REF9 unless a later accepted ADR explicitly approves
  one;
- replacing working stdlib code without evidence.

Tests:

- not applicable for an ADR-only phase unless executable metadata changes.

Acceptance:

- dependency candidates are evaluated using project-public criteria:
  performance, readability, maintenance burden, health, security, license
  compatibility, packaging, footprint, transitive risk, and project fit;
- private dependency preferences are not included.

Risk: low if ADR-only.

REF9 implementation note: REF9 added ADR 0035, "Dependency Evaluation After
Initial Refactor Phases." The ADR keeps RepoMap stdlib/local-code first after
REF3-REF8, adds no dependencies, leaves package metadata and lockfiles
untouched, and defers every evaluated category unless a later dedicated ADR or
explicit phase proves a concrete performance, correctness, maintenance, or
readability need.

## Package Tree Architecture Roadmap

PKG0 adds ADR 0036, "Package Tree Architecture And Module Size Crisis Policy."
It records that REF3-REF9 improved local seams but did not solve the flat
package structure or the largest module crises.

PKG0 adopts these source module size thresholds:

- preferred: under 1,000 lines where practical;
- acceptable: 1,000-1,500 lines for cohesive complex modules;
- warning: 1,500-2,000 lines;
- crisis: over 2,000 lines;
- extreme crisis: over 5,000 lines.

`canonicalization.py` remains an unresolved extreme crisis after REF7 and must
be driven below 2,000 lines through focused canonicalization family phases.

The package-tree target is domain-oriented rather than layer-oriented:

- `repomap_kg.cli`;
- `repomap_kg.extractors`;
- `repomap_kg.canonicalization`;
- `repomap_kg.storage`;
- `repomap_kg.ops`;
- `repomap_kg.runtime`;
- `repomap_kg.server`;
- `repomap_kg.graph`;
- `repomap_kg.observations`.

Future package migration phases should preserve public import compatibility
through thin facades, move one subsystem at a time, avoid dependency additions,
avoid broad formatting churn, and run the full final source gate.

Proposed package migration phases:

- PKG1: introduce package directories and compatibility facade pattern;
- PKG2: move CLI modules into `repomap_kg.cli`;
- PKG3: move storage modules into `repomap_kg.storage`;
- PKG4: move ops and runtime modules into `repomap_kg.ops` and
  `repomap_kg.runtime`;
- PKG5: move extractor modules into `repomap_kg.extractors.*`;
- PKG6: move graph, observations, diagnostics, and shared model modules;
- CANON1-CANON5: reduce `canonicalization.py` by family and characterize
  dispatch behavior;
- PKG-CLEAN: remove obsolete compatibility shims after internal imports migrate.

PKG1 implementation note: PKG1 establishes only import-safe package
skeletons. It creates non-conflicting namespaces for extractors, local ops,
runtime, server, and graph work. It deliberately defers `repomap_kg.cli`,
`repomap_kg.storage`, `repomap_kg.canonicalization`, and
`repomap_kg.observations` package directories because same-named root modules
currently provide public compatibility imports and Python would resolve a
same-named package ahead of the module file.

PKG2 implementation note: PKG2 resolves the `repomap_kg.cli` package/module
conflict by moving `cli.py`, `cli_parser.py`, and `cli_dispatch.py` into
`repomap_kg.cli.main`, `repomap_kg.cli.parser`, and
`repomap_kg.cli.dispatch`. The `repomap_kg.cli` package remains the public
compatibility surface, root `cli_parser` and `cli_dispatch` facades remain for
old imports, and command-handler package splits are deferred to a later
behavior-preserving phase.

PKG3 implementation note: PKG3 resolves the `repomap_kg.storage`
package/module conflict by moving storage implementation modules into
`repomap_kg.storage.*`. The `repomap_kg.storage` package remains the public
compatibility surface, root `storage_*` helper facades remain for old imports,
and storage schema/readback/load behavior stays unchanged.

PKG4 implementation note: PKG4 moves local operations and runtime
implementations into `repomap_kg.ops` and `repomap_kg.runtime`. The old root
modules remain compatibility facades that alias the package implementations, and
CLI, MCP, server-memory, local-server, and moved sibling modules import the
package paths directly.

PKG5 implementation note: PKG5 starts the extractor package migration by moving
the shell-family extractors and shared extractor helpers into
`repomap_kg.extractors.shell` and `repomap_kg.extractors.shared`. The old root
modules remain thin compatibility facades, and production discovery imports the
moved shell extractor implementations through the package path.

PKG5-LANG implementation note: PKG5-LANG continues the extractor package
migration by moving Python, JavaScript, and Ruby source-language extractor
implementations into `repomap_kg.extractors.languages`. The old root modules
remain thin compatibility facades, and discovery, source ingestion, and bulk
ingestion import moved language implementations through the package path.

PKG5-CONFIGDOC implementation note: PKG5-CONFIGDOC continues the extractor
package migration by moving configuration and document/content extractor
implementations into `repomap_kg.extractors.config` and
`repomap_kg.extractors.documents`. The old root modules remain thin
compatibility facades, and discovery, source ingestion, and bulk ingestion
import moved config/document implementations through the package path.

PKG6 implementation note: PKG6 moves graph keys, project profiles, raw
observations, and observation normalization into `repomap_kg.graph` and
`repomap_kg.observations`. The old root modules remain compatibility facades,
production imports use the moved package paths, and `discovery.py` is deferred
because classifier/routing behavior deserves a dedicated package move.

PKG6-DISCOVERY implementation note: PKG6-DISCOVERY moves discovery
classification and extractor routing into `repomap_kg.graph.discovery`. The old
`repomap_kg.discovery` module remains a `sys.modules` compatibility facade so
existing imports and patch targets continue to touch the package implementation,
and production ingestion, CLI, and ops modules import the package path directly.

CANON1 implementation note: CANON1 starts the canonicalization crisis reduction
by resolving the `repomap_kg.canonicalization` package/module conflict and
moving the file, configuration, document/web-content, and feed family handlers
into `repomap_kg.canonicalization.*` modules. The package root remains the
public compatibility surface, `canonicalize_observations` keeps the same
orchestration and dispatch order, and shell/language/test/API family splits are
deferred to later CANON phases.

CANON2 implementation note: CANON2 continues canonicalization crisis reduction
by moving the shell-family handlers into
`repomap_kg.canonicalization.shell_family`. The extracted slice includes
generic shell, Bash, Zsh, PowerShell, Bats, Zunit, and Awk canonicalization
handlers plus shell-only helpers. `canonicalize_observations` remains in
`main.py`, keeps the same dispatch order, and imports moved shell handlers back
through the package path.

CANON3 implementation note: CANON3 continues canonicalization crisis reduction
by moving Python, Ruby, and JavaScript source-language handlers into
`repomap_kg.canonicalization.language_family`. The extracted slice includes
source-language definition, reference, import, key, display, and metadata
helpers while preserving the `repomap_kg.canonicalization` compatibility
surface. `canonicalize_observations` remains in `main.py`, keeps the same
dispatch order, and Nix, email, API, and test-family canonicalization remain
deferred to later CANON phases.

CANON4 implementation note: CANON4 continues canonicalization crisis reduction
by moving the remaining obvious Nix and email handlers into
`repomap_kg.canonicalization.nix_family` and
`repomap_kg.canonicalization.email_family`. `canonicalize_observations` remains
in `main.py`, keeps the same dispatch order, and imports moved Nix/email
handlers back through the package path. A standalone API/test-family module is
deferred because remaining API/test canonicalization is already owned by the
earlier document, language, and shell family modules rather than a separate
remaining block in `main.py`.

CANON5 implementation note: CANON5 checkpoints the canonicalization package
migration by removing mechanical blank-line debris from
`repomap_kg.canonicalization.main`, recording module line counts, and
documenting the remaining helper-inversion path. `main.py` now contains
dispatch/orchestration plus shared helper and compatibility import surfaces,
but remains just above the ADR 0036 crisis threshold. `shell_family.py` remains
an extreme-crisis module and `document_family.py` remains crisis-sized, so
future CANON work should invert shared helpers before removing temporary
scaffolding and then split shell/document subfamilies where behavior can remain
fully characterized.

CANON-SHARED0 implementation note: CANON-SHARED0 begins canonicalization helper
dependency inversion by moving dependency-light metadata, diagnostic, and file
node merge helpers into package-local shared modules under
`repomap_kg.canonicalization`. `main.py` imports those helpers back to preserve
the package compatibility surface, family modules import the moved helpers
directly where safe, and the temporary `sys.modules` scaffolding remains for
the broader not-yet-inverted surface. This brings `main.py` below the ADR 0036
crisis threshold while leaving dispatch order, canonical graph output, storage,
CLI/MCP behavior, dependencies, and package metadata unchanged.

CANON-SHARED1 implementation note: CANON-SHARED1 continues helper dependency
inversion by adding `repomap_kg.canonicalization.evidence_helpers`, moving the
shell evidence metadata omit-key constants there, and routing
`_evidence_from_observation` plus `_evidence_key` through the package-local
shared module. `main.py` imports these names back for compatibility, family
modules import `_evidence_from_observation` directly where safe, and
`shell_family.py` also imports the moved omit-key constants directly. The
temporary family-module scaffolding remains in place for unresolved
dependencies. Dispatch order, canonical graph output, evidence semantics,
storage, CLI/MCP behavior including MCP-DB0 reachability fallback, dependencies,
and package metadata remain unchanged.

CANON-SHARED2 implementation note: CANON-SHARED2 continues helper dependency
inversion by adding package-local value/confidence and node/edge route modules
for helpers already implemented in `repomap_kg.canonical_core`.
`repomap_kg.canonicalization.value_helpers` routes confidence and metadata merge
helpers, while `repomap_kg.canonicalization.node_edge_helpers` routes node/edge
upsert and graph-key display/kind helpers. `main.py` imports those names back
for compatibility, `file_helpers.py` imports value helpers through the
canonicalization package, and family modules import node/edge helpers directly
where safe. The temporary family-module scaffolding remains in place for
unresolved dependencies. Dispatch order, canonical graph output, helper
semantics, storage, CLI/MCP behavior including MCP-DB0 reachability fallback,
dependencies, and package metadata remain unchanged.

CANON-DISPATCH0 implementation note: CANON-DISPATCH0 characterizes the current
canonicalization dispatch shape before shell/document subfamily splits. It adds
focused dispatch tests for representative mapped families, raw-only evidence
handling, unsupported diagnostics, observation ordinal preservation, and Zsh
branch precedence for an ambiguous shell observation. It also introduces
`repomap_kg.canonicalization.dispatch_helpers` as a data-only package-local home
for raw-only and mapped-kind dispatch constants plus a dispatch-order descriptor.
`canonicalize_observations` remains in `main.py`, and the production dispatch
loop, branch order, raw-only behavior, unsupported diagnostics, canonical graph
output, storage, CLI/MCP behavior including MCP-DB0 reachability fallback,
dependencies, package metadata, and test-runner policy remain unchanged.

CANON-SHELL-SPLIT0 implementation note: CANON-SHELL-SPLIT0 begins reducing the
extreme-crisis `repomap_kg.canonicalization.shell_family` module by moving the
cohesive AWK canonicalization subfamily into
`repomap_kg.canonicalization.shell_awk_family`. AWK was chosen first because
its predicate, handlers, evidence metadata, target-key helpers, and
static-only runtime metadata are contiguous and already covered by focused AWK
canonicalization tests. `shell_family.py` imports the moved AWK names back for
compatibility, `canonicalize_observations` continues to dispatch through the
same shell family surface, and dispatch order, Zsh/Bats/Bash/AWK/Zunit
precedence, raw-only handling, unsupported diagnostics, canonical graph output,
storage, CLI/MCP behavior including MCP-DB0 reachability fallback, dependencies,
package metadata, and test-runner policy remain unchanged.

CANON-SHELL-SPLIT1 implementation note: CANON-SHELL-SPLIT1 continues reducing
`repomap_kg.canonicalization.shell_family` by moving the cohesive Zunit
canonicalization subfamily into
`repomap_kg.canonicalization.shell_zunit_family`. Zunit was chosen next because
its predicate, mapped handlers, raw-only evidence path, graph-key helpers, and
static-only test metadata are contiguous and already covered by focused Zunit
canonicalization and extractor tests. `shell_family.py` imports the moved Zunit
names back for compatibility, `canonicalize_observations` continues to dispatch
through the same shell family surface, and AWK before Zunit, Zunit before Zsh,
Zsh before Bats, Bats before Bash, and Bash before legacy shell precedence,
raw-only handling, unsupported diagnostics, canonical graph output, storage,
CLI/MCP behavior including MCP-DB0 reachability fallback, dependencies, package
metadata, and test-runner policy remain unchanged.

CANON-SHELL-SPLIT2 implementation note: CANON-SHELL-SPLIT2 continues reducing
`repomap_kg.canonicalization.shell_family` by moving the cohesive Bats
canonicalization subfamily into
`repomap_kg.canonicalization.shell_bats_family`. Bats was chosen next because
its predicate, mapped handlers, raw-only evidence path, graph-key helpers, and
static-only test metadata are contiguous and already covered by focused Bats
canonicalization and extractor tests. `shell_family.py` imports the moved Bats
names back for compatibility, `canonicalize_observations` continues to dispatch
through the same shell family surface, and AWK before Zunit, Zunit before Zsh,
Zsh before Bats, Bats before Bash, and Bash before legacy shell precedence,
raw-only handling, unsupported diagnostics, canonical graph output, storage,
CLI/MCP behavior including MCP-DB0 reachability fallback, dependencies, package
metadata, and test-runner policy remain unchanged.

CANON-SHELL-SHARED0 implementation note: CANON-SHELL-SHARED0 moves the generic
shared edge upsert helper `_upsert_config_edge` out of
`repomap_kg.canonicalization.config_family` into
`repomap_kg.canonicalization.edge_helpers`. Inspection confirmed the helper is
not config-specific: it builds a canonical edge key with empty identity
metadata, delegates merge/confidence behavior to `_upsert_edge`, and returns
the resulting edge key. `config_family.py` imports the helper back for
compatibility, while document, feed, shell, AWK, Zunit, and Bats canonicalizers
import it directly from the shared module where safe. Handler logic, edge key
construction, edge metadata, dispatch order, shell precedence, raw-only
handling, unsupported diagnostics, canonical graph output, storage, CLI/MCP
behavior including MCP-DB0 reachability fallback, dependencies, package
metadata, and test-runner policy remain unchanged.

CANON-DOC-SPLIT0 implementation note: CANON-DOC-SPLIT0 begins reducing the
crisis-sized `repomap_kg.canonicalization.document_family` module by moving the
cohesive WARC document canonicalization subfamily into
`repomap_kg.canonicalization.document_warc_family`. WARC was chosen first
because it is the smallest low-risk document/web-content group: two handlers
plus WARC-only source/target key and metadata helpers, with shared edge and
node/evidence helpers already routed through package-local helper modules.
`document_family.py` imports the moved WARC names back for compatibility,
`canonicalize_observations` continues to dispatch through the same document
family surface, and document/web branch precedence, raw-only handling,
unsupported diagnostics, canonical graph output, storage, CLI/MCP behavior
including MCP-DB0 reachability fallback, dependencies, package metadata, and
test-runner policy remain unchanged.

CANON-DOC-SPLIT1 implementation note: CANON-DOC-SPLIT1 continues reducing
`repomap_kg.canonicalization.document_family` by moving the cohesive XML
canonicalization subfamily into
`repomap_kg.canonicalization.document_xml_family`. XML was chosen next because
it is a self-contained document/web-content group with two handlers, XML-only
source/target key helpers, XML-only node/edge metadata helpers, and strong
existing unit and canonical-contract coverage. CSS selector matching and HTML
target helpers remain deferred. `document_family.py` imports the moved XML
names back for compatibility, `canonicalize_observations` continues to dispatch
through the same document family surface, and document/web branch precedence,
raw-only handling, unsupported diagnostics, canonical graph output, storage,
CLI/MCP behavior including MCP-DB0 reachability fallback, dependencies, package
metadata, and test-runner policy remain unchanged.

CANON-DOC-SPLIT2 implementation note: CANON-DOC-SPLIT2 continues reducing
`repomap_kg.canonicalization.document_family` by moving the cohesive HTML
canonicalization subfamily into
`repomap_kg.canonicalization.document_html_family`. HTML was chosen next
because the HTML handlers and target/key/metadata/upsert helpers form a compact
HTML-only group with existing unit, canonical-contract, storage, and CLI/MCP
coverage, while CSS selector matching remains more helper-coupled. The moved
HTML names are imported back through `document_family.py` for compatibility,
`canonicalize_observations` continues to dispatch through the same document
family surface, and document/web branch precedence, raw-only handling,
unsupported diagnostics, canonical graph output, storage, CLI/MCP behavior
including MCP-DB0 reachability fallback, dependencies, package metadata, and
test-runner policy remain unchanged.

CANON-DOC-SPLIT3 implementation note: CANON-DOC-SPLIT3 continues reducing
`repomap_kg.canonicalization.document_family` by moving the cohesive CSS
canonicalization subfamily into
`repomap_kg.canonicalization.document_css_family`. CSS was chosen after WARC,
XML, and HTML because the remaining CSS handlers and CSS selector/source/target
key plus metadata helpers form an isolated web-content group with existing CSS,
HTML matching, canonicalization, canonical-contract, storage, and CLI/MCP
coverage. `_upsert_css_edge` now routes through the existing shared
`repomap_kg.canonicalization.edge_helpers` module because it is also used by
non-CSS families. The moved CSS names are imported back through
`document_family.py` for compatibility, `canonicalize_observations` continues
to dispatch through the same document family surface, and CSS selector
matching, document/web branch precedence, raw-only handling, unsupported
diagnostics, canonical graph output, storage, CLI/MCP behavior including
MCP-DB0 reachability fallback, dependencies, package metadata, and test-runner
policy remain unchanged.

CANON-SHELL-SPLIT3 implementation note: CANON-SHELL-SPLIT3 reassesses Bash and
Zsh coupling after the AWK, Zunit, Bats, and shared-edge-helper splits, then
moves the cohesive Bash canonicalization subfamily into
`repomap_kg.canonicalization.shell_bash_family`. Bash was chosen because its
handlers and Bash-only helper functions are a narrower, self-contained group,
while Zsh still owns the broader ambiguous `shell.command` precedence surface
and remains deferred. The moved Bash names are imported back through
`shell_family.py` for compatibility, `canonicalize_observations` continues to
dispatch through the same shell family surface, and AWK/Zunit/Zsh/Bats/Bash/
legacy-shell branch precedence, Zsh ambiguous shell-command behavior,
raw-only handling, unsupported diagnostics, static-only/no-execution shell
safety metadata, canonical graph output, storage, CLI/MCP behavior including
MCP-DB0 reachability fallback, dependencies, package metadata, and test-runner
policy remain unchanged.

CANON-SHELL-SPLIT4 implementation note: CANON-SHELL-SPLIT4 reassesses Zsh after
the Bash split and moves the cohesive Zsh canonicalization subfamily into
`repomap_kg.canonicalization.shell_zsh_family`. Zsh was safe enough to split
because the whole Zsh predicate/handler/helper group is contiguous, now imports
only shared canonicalization helpers and Zsh graph-key builders directly, and
does not require moving generic shell or PowerShell logic. The moved Zsh names
are imported back through `shell_family.py` at the same point between Zunit and
Bats, so `canonicalize_observations` continues to dispatch through the same
shell family surface and AWK/Zunit/Zsh/Bats/Bash/legacy-shell branch
precedence, ambiguous `shell.command` with `dialect: zsh`, Zunit exclusion,
Bats/Bash behavior, raw-only handling, unsupported diagnostics,
static-only/no-execution shell safety metadata, canonical graph output,
storage, CLI/MCP behavior including MCP-DB0 reachability fallback,
dependencies, package metadata, and test-runner policy remain unchanged.

CANON-SHELL-SHARED1 implementation note: CANON-SHELL-SHARED1 inspects the
remaining shell-family coupling after AWK, Zunit, Bats, Bash, and Zsh splits
and moves the identical safe relative shell target resolver body into
`repomap_kg.canonicalization.shell_shared_helpers`. The dialect-specific
wrappers `_awk_safe_relative_target`, `_bash_safe_relative_target`, and
`_zsh_safe_relative_target` remain in their subfamily modules and remain
imported back through `shell_family.py` for compatibility. The move preserves
the existing root-relative normalization behavior, Bash-as-default-sh policy,
explicit Zsh dialect matching, AWK/Zunit/Zsh/Bats/Bash/legacy-shell branch
precedence, raw-only handling, unsupported diagnostics, static-only/no-execution
shell safety metadata, canonical graph output, storage, CLI/MCP behavior
including MCP-DB0 reachability fallback, dependencies, package metadata, and
test-runner policy. Temporary family-module scaffolding remains intentionally
unchanged; wrapper/scaffold cleanup is deferred.

CANON-SHELL-SPLIT5 implementation note: CANON-SHELL-SPLIT5 reassesses the
remaining shell-family code after AWK, Zunit, Bats, Bash, Zsh, and shared shell
helper splits, then moves the cohesive PowerShell canonicalization subfamily
into `repomap_kg.canonicalization.shell_powershell_family`. PowerShell was
chosen over legacy generic shell because its file/function/command/env/host
mutation/reference handlers and PowerShell-only helper functions are contiguous,
self-contained, and covered by existing PowerShell canonicalization and
extractor tests. The moved PowerShell names are imported back through
`shell_family.py` for compatibility, `canonicalize_observations` continues to
dispatch through the same shell family surface, and AWK/Zunit/Zsh/Bats/Bash/
legacy-shell/PowerShell branch precedence, Bash-as-default-sh behavior,
explicit Zsh dialect matching, raw-only handling, unsupported diagnostics,
PowerShell static-only/no-execution metadata, canonical graph output, storage,
CLI/MCP behavior including MCP-DB0 reachability fallback, dependencies, package
metadata, and test-runner policy remain unchanged. Temporary family-module
scaffolding remains intentionally unchanged; wrapper/scaffold cleanup is
deferred.

CANON-SHELL-SPLIT6 implementation note: CANON-SHELL-SPLIT6 reassesses the
remaining legacy generic shell canonicalization after AWK, Zunit, Bats, Bash,
Zsh, PowerShell, and shared shell helper splits, then moves the cohesive
legacy `shell.command`, `shell.source`, `shell.env`, and
`shell.host_mutation` handlers plus their legacy target/metadata helpers into
`repomap_kg.canonicalization.shell_legacy_family`. The move leaves
`shell_family.py` as the compatibility facade and temporary scaffold holder,
imports the moved legacy names back for existing dispatch and package
compatibility, and preserves AWK/Zunit/Zsh/Bats/Bash/legacy-shell/PowerShell
branch precedence, Bash-as-default-sh behavior, explicit Zsh dialect matching,
raw-only handling, unsupported diagnostics, dynamic/unknown/redaction behavior,
static-only/no-execution shell safety metadata, canonical graph output,
storage, CLI/MCP behavior including MCP-DB0 reachability fallback,
dependencies, package metadata, and test-runner policy unchanged.
Wrapper/scaffold cleanup remains explicitly deferred.

CANON-DOC-SPLIT4 implementation note: CANON-DOC-SPLIT4 reassesses the
remaining document-family code after WARC, XML, HTML, and CSS splits, then
moves the cohesive Markdown canonicalization subfamily into
`repomap_kg.canonicalization.document_markdown_family`. The moved Markdown
boundary includes the Markdown document, heading, ADR metadata, skill metadata,
link, frontmatter, and code-fence canonicalization handlers plus Markdown-only
target/key, node metadata, edge metadata, and edge upsert helpers. The move
leaves `document_family.py` as the compatibility facade, generic document
fallback owner, and temporary scaffold holder, imports the moved Markdown names
back for existing dispatch and package compatibility, and preserves
Markdown/config/HTML/XML/CSS/feed/WARC/document fallback branch precedence,
Markdown ADR and skill metadata behavior, link/reference placeholder behavior,
raw-only handling, unsupported diagnostics, dynamic/unknown/redaction behavior,
canonical graph output, storage, CLI/MCP behavior including MCP-DB0
reachability fallback, dependencies, package metadata, and test-runner policy
unchanged. Wrapper/scaffold cleanup remains explicitly deferred.

CANON-CLEAN0 implementation note: CANON-CLEAN0 inventories the remaining
temporary `sys.modules["repomap_kg.canonicalization.main"]` family-module
scaffolds, then removes that scaffold from the two lowest-risk modules:
`feed_family.py` and `nix_family.py`. These modules were selected because their
remaining dependencies are compact and explicit after the prior shared-helper
and subfamily splits, and they are not broad compatibility facades. The cleanup
adds direct canonical record, diagnostic, raw observation, and graph-key imports
to those two files only, preserving their existing handlers and helper bodies.
`config_family.py`, `document_family.py`, `email_family.py`, `file_family.py`,
`language_family.py`, and `shell_family.py` remain scaffolded for later
review. Package-root and `main.py` compatibility, dispatch order, branch
precedence, raw-only handling, unsupported diagnostics, canonical graph output,
storage, CLI/MCP behavior including MCP-DB0 reachability fallback,
dependencies, package metadata, lockfiles, and test-runner policy remain
unchanged.

CANON-CLEAN1 implementation note: CANON-CLEAN1 performs the next targeted
import audit and removes the temporary `main` scaffold from `file_family.py`
and `config_family.py`. `file_family.py` was selected after routing the pure
`FILE_METADATA_KEYS` tuple into `file_helpers.py`; `main.py` imports it back
from there so the existing `main.py` and package-root compatibility surfaces
remain intact. `config_family.py` was selected because its remaining
dependencies are compact canonical record, diagnostic, raw observation, graph
key, and package-local helper imports. `document_family.py`, `email_family.py`,
`language_family.py`, and `shell_family.py` remain scaffolded for later
review because they still act as facades or broad dependency owners. Dispatch
order, branch precedence, raw-only handling, unsupported diagnostics,
canonical graph output, storage, CLI/MCP behavior including MCP-DB0
reachability fallback, dependencies, package metadata, lockfiles, and
test-runner policy remain unchanged.

CANON-CLEAN2 implementation note: CANON-CLEAN2 removes the temporary `main`
scaffold from `email_family.py` and `document_family.py` after a targeted
import audit. `email_family.py` was selected because its dependencies are
compact canonical record, diagnostic, raw observation, graph key, evidence,
metadata, node/edge, and shared edge-helper imports. `document_family.py` was
selected because it now owns only the generic document fallback plus
document-subfamily compatibility imports, and its direct graph-key/helper
surface remains readable. `language_family.py` and `shell_family.py` remain
scaffolded for later phases because language still has a broad graph-key
surface and shell is still a compatibility facade. No helper ownership changes
landed. Dispatch order, branch precedence, raw-only handling, unsupported
diagnostics, canonical graph output, storage, CLI/MCP behavior including
MCP-DB0 reachability fallback, dependencies, package metadata, lockfiles, and
test-runner policy remain unchanged.

CANON-CLEAN3 implementation note: CANON-CLEAN3 removes the temporary `main`
scaffold from `language_family.py` after assessing both remaining scaffolded
modules. `language_family.py` was selected because its broad graph-key surface
is explicit and manageable as direct imports: canonical record classes,
diagnostics, raw observations, graph key builders, shared edge helpers,
evidence helpers, metadata helpers, and node/edge helpers. `shell_family.py`
remains scaffolded because it is the final shell compatibility facade over the
split shell subfamilies and is better handled as the last cleanup slice. No
helper ownership changes landed. Dispatch order, branch precedence, raw-only
handling, unsupported diagnostics, canonical graph output, Bash-as-default-sh
behavior, explicit Zsh dialect behavior, storage, CLI/MCP behavior including
MCP-DB0 reachability fallback, dependencies, package metadata, lockfiles, and
test-runner policy remain unchanged.

CANON-CLEAN4 implementation note: CANON-CLEAN4 removes the final family-module
temporary `main` scaffold from `shell_family.py` after a targeted shell facade
import audit. `shell_family.py` was safe because it now owns no local handler
bodies and already explicitly imports the shell compatibility surface from AWK,
Zunit, Zsh, Bats, Bash, PowerShell, legacy shell, shared shell helpers, and
package-local canonicalization helpers. Shell dispatch constants previously
reachable through the scaffold are now imported directly from
`dispatch_helpers.py`. No shell subfamily modules changed, and package-root
facade cleanup remains deferred. Dispatch order, branch precedence, raw-only
handling, unsupported diagnostics, canonical graph output,
Bash-as-default-sh behavior, explicit Zsh dialect behavior, storage, CLI/MCP
behavior including MCP-DB0 reachability fallback, dependencies, package
metadata, lockfiles, and test-runner policy remain unchanged.

CANON-FACADE0 implementation note: CANON-FACADE0 inventories the package-root
canonicalization facade after all family-module scaffolds were removed. The
package root still imports `repomap_kg.canonicalization.main` and preserves
the existing broad compatibility surface; `main.py` remains the orchestration
module and compatibility source for family and subfamily names. The only
package-root cleanup is making the current public facade surface explicit for
star imports by adding a computed `__all__` over existing non-underscore root
attributes. No compatibility names are removed, and family/subfamily facades
continue to import as before. Dispatch order, branch precedence, raw-only
handling, unsupported diagnostics, canonical graph output,
Bash-as-default-sh behavior, explicit Zsh dialect behavior, storage, CLI/MCP
behavior including MCP-DB0 reachability fallback, dependencies, package
metadata, lockfiles, and test-runner policy remain unchanged.

CANON-FACADE1 implementation note: CANON-FACADE1 assesses the package-root
canonicalization facade's dynamic compatibility export copying and replaces the
generated `_COMPATIBILITY_EXPORT_NAMES` expression with a static tuple captured
from the current `main.py` non-module-dunder surface. The package root still
imports `repomap_kg.canonicalization.main`, still copies those preserved names
with `globals().update(...)`, and still computes `__all__` from current
non-underscore package-root attributes. No compatibility names are removed;
`canonicalize_observations`, `main.py` orchestration compatibility,
family/subfamily facades, dispatch order, branch precedence, raw-only handling,
unsupported diagnostics, canonical graph output, Bash-as-default-sh behavior,
explicit Zsh dialect behavior, storage, CLI/MCP behavior including MCP-DB0
reachability fallback, dependencies, package metadata, lockfiles, and
test-runner policy remain unchanged.

CANON-FACADE2 implementation note: CANON-FACADE2 keeps the static
`_COMPATIBILITY_EXPORT_NAMES` tuple as the package-root canonicalization
compatibility ledger and adds `tools/canonicalization_facade_inventory.py` as a
small stdlib-only check/report tool for accidental drift. The tool reports the
static ledger count, generated current `main.py` non-module-dunder surface
count, missing package-root/main names, public `__all__` count and drift, and
family modules retaining the old scaffold. It is report/check-only, mutates no
files, generates no import-time code, adds no runtime import complexity, and
adds no dependencies. No compatibility names are removed; `canonicalize_observations`,
`main.py` orchestration compatibility, family/subfamily facades, dispatch
order, branch precedence, raw-only handling, unsupported diagnostics,
canonical graph output, Bash-as-default-sh behavior, explicit Zsh dialect
behavior, storage, CLI/MCP behavior including MCP-DB0 reachability fallback,
dependencies, package metadata, lockfiles, and test-runner policy remain
unchanged.

CANON-FACADE3 implementation note: CANON-FACADE3 closes the package-root
canonicalization facade cleanup track by recording the long-term
compatibility-control decision. `_COMPATIBILITY_EXPORT_NAMES` remains the
canonical package-root compatibility ledger for now, and
`tools/canonicalization_facade_inventory.py --check` is the drift detector to
run before changing the facade ledger or `main.py` compatibility surface.
Generated update mode is deliberately not added; compatibility-name removals
require a separate later phase with explicit proof, tests, and user approval.
The only test refinement locks in that the inventory tool has no `--update`
mode. No compatibility names are removed; `canonicalize_observations`,
`main.py` orchestration compatibility, family/subfamily facades, dispatch
order, branch precedence, raw-only handling, unsupported diagnostics,
canonical graph output, Bash-as-default-sh behavior, explicit Zsh dialect
behavior, storage, CLI/MCP behavior including MCP-DB0 reachability fallback,
dependencies, package metadata, lockfiles, and test-runner policy remain
unchanged.

CONFIG-REF0 implementation note: CONFIG-REF0 inventories
`src/main/python/repomap_kg/extractors/config/generic.py` as a dedicated
configuration-extractor refactor track. The module is 8,148 lines, which is an
ADR 0036 extreme-crisis module, and currently contains 65 constants, 13
classes, and 269 functions. The inventory identifies handler clusters for
JSON/JSONC/JSONL/TOML/YAML entry routing, Python requirements/pyproject,
JavaScript package/profile config, OpenAPI, Terraform JSON/HCL/tfvars,
Kubernetes/Argo CD/Liquibase/Docker profiles, plist/generic XML, and generic
structure/reference helpers. CONFIG-REF0 lands no production code split and
changes no extraction behavior, observation kinds, metadata keys, ordering,
source ids, confidence, redaction, dynamic/unknown handling, canonicalization,
storage, CLI/MCP behavior, dependencies, package metadata, lockfiles, or
test-runner policy. Proposed follow-up order is a small shared-helper seam,
then Python ecosystem, JavaScript/package profiles, Terraform, OpenAPI, YAML,
XML/plist, infrastructure profiles, and final generic facade cleanup.

CONFIG-REF1 implementation note: CONFIG-REF1 creates the first source split in
the generic config extractor track by moving only the pure JSON pointer helper
seam into `src/main/python/repomap_kg/extractors/config/paths.py`. The moved
helpers are `json_pointer`, `_pointer_segments`, and
`_escape_pointer_segment`; `generic.py` imports all three names back to preserve
the existing root facade and module-level reachability. No parser bodies,
dispatcher logic, domain handlers, graph-key construction, redaction logic,
observation construction, observation kinds, metadata keys, source ids,
ordering, confidence, dynamic/unknown handling, canonicalization, storage,
CLI/MCP behavior, dependencies, package metadata, lockfiles, or test-runner
policy change. This establishes the CONFIG-REF compatibility pattern for later,
larger domain splits.

CONFIG-REF2 implementation note: CONFIG-REF2 creates the first cohesive domain
split in the generic config extractor track by moving only the Python
ecosystem config extraction group into
`src/main/python/repomap_kg/extractors/config/python.py`. The new module owns
the Python requirements/constraints predicates and handlers, the
`_PythonRequirement` dataclass, pyproject metadata/build-system/dependency
group/entry-point/tool-config helpers, Python reference helpers, Python parse
diagnostics, and Python redaction helpers. `generic.py` imports every moved
Python name back, keeps `extract_config_file_observations`, requirements-file
routing, TOML/pyproject routing, and dispatcher order in place, and leaves JSON,
YAML, XML/plist, Terraform, OpenAPI, JavaScript/package, infrastructure
profiles, generic walkers, canonicalization, storage, CLI/MCP behavior,
dependencies, package metadata, lockfiles, and test-runner policy unchanged.

CONFIG-REF3 implementation note: CONFIG-REF3 creates the next cohesive domain
split in the generic config extractor track by moving only the
JavaScript/package ecosystem config extraction group into
`src/main/python/repomap_kg/extractors/config/javascript.py`. The new module
owns the package.json/package-lock helpers, npm dependency groups, package
script summaries and secret-prone script redaction predicate, framework hints,
TypeScript config references, Angular profile helpers, and Playwright profile
helper. `generic.py` imports every moved JavaScript/package name back, keeps
`extract_config_file_observations`, JSON/JSONC routing, package profile
selection, inline Nest/Jest profile handling, and dispatcher order in place,
and leaves Python, Terraform, OpenAPI, YAML, XML/plist, infrastructure
profiles, generic walkers, canonicalization, storage, CLI/MCP behavior,
dependencies, package metadata, lockfiles, and test-runner policy unchanged.

CONFIG-REF4 implementation note: CONFIG-REF4 splits the larger Terraform
domain by moving only the Terraform JSON/HCL/tfvars extraction group into
`src/main/python/repomap_kg/extractors/config/terraform.py`. The new module
owns Terraform HCL constants and limits, `_TerraformHclBlock`,
`_TerraformHclAttribute`, Terraform JSON and tfvars observation helpers, the
shallow HCL scanner, Terraform block/profile helpers, reference helpers,
expression-summary helpers, parse-error helpers, and Terraform-specific
redaction helpers. `generic.py` imports every moved Terraform name back, keeps
`extract_config_file_observations`, `.tf` before tfvars routing, JSON-family
profile detection/routing, and dispatcher order in place, and leaves Python,
JavaScript/package, OpenAPI, YAML, XML/plist, infrastructure profiles, generic
walkers, canonicalization, storage, CLI/MCP behavior, dependencies, package
metadata, lockfiles, and test-runner policy unchanged.

CONFIG-REF5 implementation note: CONFIG-REF5 splits the larger OpenAPI domain
by moving only the OpenAPI/Swagger extraction group into
`src/main/python/repomap_kg/extractors/config/openapi.py`. The new module owns
OpenAPI constants and limits, profile observation helpers, document/info/server/
path/operation/parameter/request/response/tag/component/security helpers,
reference helpers, example and redaction helpers, OAuth/scope/text/url metadata
helpers, OpenAPI parse-error helpers, and OpenAPI file/document predicates.
`generic.py` imports every moved OpenAPI name back, keeps JSON/JSONC/YAML
parsing and routing, YAML multi-document handling, YAML OpenAPI reference
helpers, generic hash and URL helpers, generic walkers, and dispatcher order in
place, and leaves Python, JavaScript/package, Terraform, XML/plist,
infrastructure profiles, canonicalization, storage, CLI/MCP behavior,
dependencies, package metadata, lockfiles, and test-runner policy unchanged.

CONFIG-REF6 implementation note: CONFIG-REF6 splits the YAML parser/profile
boundary by moving only the conservative YAML parser, YAML profile metadata,
YAML redaction, and YAML reference helpers into
`src/main/python/repomap_kg/extractors/config/yaml.py`. The new module owns the
YAML constants and limits, `YamlParseError`, `_YamlLine`, `_YamlValue`,
`_YamlParseState`, YAML document splitting, mapping/sequence/inline/scalar
parsing, custom tag/anchor/alias handling, duplicate-key diagnostics,
multi-document wrapping, YAML profile metadata, stable-array metadata, YAML
redaction helpers, and YAML string reference helpers. `generic.py` imports every
moved YAML name back, keeps `extract_config_file_observations`, `.yaml`/`.yml`
routing, OpenAPI YAML routing, infrastructure profile handlers, generic
walkers, and dispatcher order in place, and leaves Python, JavaScript/package,
Terraform, OpenAPI, XML/plist, canonicalization, storage, CLI/MCP behavior,
dependencies, package metadata, lockfiles, and test-runner policy unchanged.

CONFIG-REF7 implementation note: CONFIG-REF7 splits the XML/plist boundary by
moving only the XML safety pre-scan, plist XML, generic XML, Java/Spring/Maven
XML profile metadata, XML reference, XML redaction, and XML diagnostic helpers
into `src/main/python/repomap_kg/extractors/config/xml.py`. The new module owns
the XML/plist constants, `PlistXmlSafetyError`, `PlistXmlParseError`,
`GenericXmlSafetyError`, plist parsing helpers, generic XML document/element/
attribute walkers, namespace and document-role helpers, XML domain metadata,
reference detection, file-reference helpers, and XML parse-error observation
helper. `generic.py` imports every moved XML/plist name back, keeps
`extract_config_file_observations`, `.xml` routing, plist-looking XML routing
before generic XML, dispatcher order, generic walkers, and shared helper
implementations in place, and leaves Python, JavaScript/package, Terraform,
OpenAPI, YAML, infrastructure profiles, canonicalization, storage, CLI/MCP
behavior, dependencies, package metadata, lockfiles, and test-runner policy
unchanged.

CONFIG-REF8 implementation note: CONFIG-REF8 splits the remaining
infrastructure profile helper boundary by moving only Kubernetes resource
helpers, Docker/Docker Compose image helpers, Argo CD helpers, Liquibase
helpers, Grafana/Kubernetes/Docker Compose profile predicates, and Kubernetes
secret-data redaction detection into
`src/main/python/repomap_kg/extractors/config/infrastructure.py`. `generic.py`
imports every moved infrastructure name back, keeps `extract_config_file_observations`,
JSON/YAML/XML/TOML routing, profile detection order, shared JSON profile
dispatch, generic walkers, generic reference construction, generic redaction
helpers, and shared metadata helpers in place, and leaves Python,
JavaScript/package, Terraform, OpenAPI, YAML, XML/plist, canonicalization,
storage, CLI/MCP behavior, dependencies, package metadata, lockfiles, and
test-runner policy unchanged.

CONFIG-REF9 implementation note: CONFIG-REF9 closes the current CONFIG-REF
domain-split track with a docs-only remaining-pressure assessment. The chosen
path is a no-move final assessment because the remaining `generic.py` surface
is now intentionally the shared config extractor facade: `extract_config_file_observations`,
JSON/JSONC/JSONL/TOML parsing and routing, JSON profile dispatch, generic
document/path/reference observation construction, shared value/path/hash/URL
helpers, shared redaction and dynamic/unknown helpers, and compatibility
imports from the split modules. No handlers, helpers, classes, constants, or
compatibility names move in CONFIG-REF9; Nix extraction is already separate in
`src/main/python/repomap_kg/extractors/config/nix.py`, and moving generic
walkers or rewriting dispatch is deferred to a separate documented phase if it
is ever justified. Extraction behavior, observation contracts, dispatcher
order, parser behavior, profile detection, canonicalization, storage, CLI/MCP
behavior, dependencies, package metadata, lockfiles, and test-runner policy
remain unchanged.

STORAGE-ROWS0 implementation note: STORAGE-ROWS0 inventories
`src/main/python/repomap_kg/storage/rows.py` as the next storage pressure point.
The module is 4,205 lines, exports 161 compatibility names, contains 38 frozen
dataclasses, and exposes 123 top-level public functions. It has no private
functions and no uppercase module constants beyond the export tuple. The
inventory identifies write-row dataclasses and builders, raw/canonical row
conversion, stable-key/hash helpers, readback payload decoders, JSONable
projection helpers, table formatters, summary record families, manifest
payload helpers, and low-level payload/metadata normalization helpers.
STORAGE-ROWS0 lands no source or test changes. Proposed follow-up order is
characterization tests for uncovered row contracts, a pure payload/metadata
helper split, legacy file/relationship row splits, canonical raw/node/edge/
evidence row splits, core and canonical readback decoder splits, source and
summary row-family splits, and a final `rows.py` facade cleanup.

STORAGE-ROWS1 implementation note: STORAGE-ROWS1 adds focused characterization
coverage in
`src/test/unit/python/repomap_kg/test_storage_rows_contracts.unit.test.py`
before any storage row source split. The tests pin the 161-name export surface
and compatibility facades, critical write-row dataclass field order and frozen
status, representative stable keys, payload and identity metadata hashes,
canonical JSON normalization, raw/canonical row ordering and ordinals,
null/false/zero/empty-value handling, representative payload decoder errors,
manifest helper coercion behavior, formatter edge cases, and SQL-facing row
field compatibility. No production source, schema, migrations, package
metadata, lockfiles, dependencies, or test runner policy change. STORAGE-ROWS2
should now split only pure shared payload, metadata, hash, and canonical JSON
helpers into a small compatibility-preserving helper module.

STORAGE-ROWS2 implementation note: STORAGE-ROWS2 adds
`src/main/python/repomap_kg/storage/row_helpers.py` and moves only pure shared
payload, metadata, manifest, hash, and canonical JSON helper functions out of
`rows.py`. `rows.py` imports the moved helper names back by name and keeps its
161-name `__all__` compatibility surface stable, so imports through
`repomap_kg.storage.rows`, `repomap_kg.storage`, `repomap_kg.storage.main`, and
`repomap_kg.storage_rows` remain intact. No row dataclasses, row builders,
readback decoders, JSONable projection helpers, table formatters, storage SQL,
schema files, migrations, package metadata, lockfiles, dependencies, or test
runner policy change. STORAGE-ROWS3 should split legacy file and relationship
write rows only after helper compatibility remains green.

STORAGE-ROWS3 implementation note: STORAGE-ROWS3 adds
`src/main/python/repomap_kg/storage/legacy_rows.py` and moves only legacy
file/relationship write-row dataclasses, builders, stable-key helpers, and
SQL-facing metadata helpers out of `rows.py`. `rows.py` imports the moved names
back by name and keeps its 161-name `__all__` compatibility surface stable, so
imports through `repomap_kg.storage.rows`, `repomap_kg.storage`,
`repomap_kg.storage.main`, and `repomap_kg.storage_rows` remain intact. Raw
observation rows, canonical rows, readback decoders, JSONable projection
helpers, table formatters, storage SQL, schema files, migrations, package
metadata, lockfiles, dependencies, and test runner policy remain unchanged.
STORAGE-ROWS4 should split raw observation and canonical write rows only after
legacy compatibility remains green.

STORAGE-ROWS4 implementation note: STORAGE-ROWS4 adds
`src/main/python/repomap_kg/storage/canonical_rows.py` and moves only raw
observation and canonical write-row dataclasses, conversion helpers, and the
canonical edge evidence link helper out of `rows.py`. `rows.py` imports the
moved names back by name and keeps its 161-name `__all__` compatibility surface
stable, so imports through `repomap_kg.storage.rows`, `repomap_kg.storage`,
`repomap_kg.storage.main`, and `repomap_kg.storage_rows` remain intact. Legacy
file/relationship rows, readback decoders, JSONable projection helpers, table
formatters, source-ingestion rows, summary rows, storage SQL, schema files,
migrations, package metadata, lockfiles, dependencies, and test runner policy
remain unchanged. STORAGE-ROWS5 should split core graph readback row decoders
only after raw/canonical write-row compatibility remains green.

STORAGE-ROWS5 implementation note: STORAGE-ROWS5 adds
`src/main/python/repomap_kg/storage/readback_rows.py` and moves only core
legacy graph readback record dataclasses and payload decoder helpers out of
`rows.py`. `rows.py` imports the moved names back by name and keeps its
161-name `__all__` compatibility surface stable, so imports through
`repomap_kg.storage.rows`, `repomap_kg.storage`, `repomap_kg.storage.main`, and
`repomap_kg.storage_rows` remain intact. Write rows, canonical readback rows,
JSONable projection helpers, table formatters, source-ingestion rows, summary
rows, storage SQL, schema files, migrations, package metadata, lockfiles,
dependencies, and test runner policy remain unchanged. STORAGE-ROWS6 should
split canonical readback row decoders only after core readback compatibility
remains green.

STORAGE-ROWS6 implementation note: STORAGE-ROWS6 adds
`src/main/python/repomap_kg/storage/canonical_readback_rows.py` and moves only
canonical readback record dataclasses and payload decoder helpers out of
`rows.py`. `raw_observation_reference_from_storage_payload` moves with this
module because it is directly paired with canonical edge evidence decoding and
uses canonical edge evidence error labels. `rows.py` imports the moved names
back by name and keeps its 161-name `__all__` compatibility surface stable, so
imports through `repomap_kg.storage.rows`, `repomap_kg.storage`,
`repomap_kg.storage.main`, and `repomap_kg.storage_rows` remain intact. Write
rows, core legacy readback rows, JSONable projection helpers, table formatters,
source-ingestion rows, summary rows, storage SQL, schema files, migrations,
package metadata, lockfiles, dependencies, and test runner policy remain
unchanged. STORAGE-ROWS7 should split source-ingestion and summary row families
only after canonical readback compatibility remains green.

STORAGE-ROWS7 implementation note: STORAGE-ROWS7 adds
`src/main/python/repomap_kg/storage/source_rows.py` and
`src/main/python/repomap_kg/storage/summary_rows.py`. It moves only
source-ingestion record dataclasses and payload decoders, summary record
dataclasses and payload decoders, and summary-family manifest payload helpers
out of `rows.py`. `rows.py` imports the moved names back by name and keeps its
161-name `__all__` compatibility surface stable, so imports through
`repomap_kg.storage.rows`, `repomap_kg.storage`, `repomap_kg.storage.main`, and
`repomap_kg.storage_rows` remain intact. Write rows, legacy/core readback rows,
canonical readback rows, JSONable projection helpers, table formatters,
storage SQL, schema files, migrations, package metadata, lockfiles,
dependencies, and test runner policy remain unchanged. STORAGE-ROWS8 should
assess remaining `rows.py` pressure and decide whether JSONable projections,
table formatters, the host-mutator decoder, or final facade cleanup should be
next.

STORAGE-ROWS8 implementation note: STORAGE-ROWS8 adds
`src/main/python/repomap_kg/storage/jsonable_rows.py` and moves only JSONable
projection helpers out of `rows.py`. `rows.py` imports the moved projection
names back by name and keeps its 161-name `__all__` compatibility surface
stable, so imports through `repomap_kg.storage.rows`, `repomap_kg.storage`,
`repomap_kg.storage.main`, and `repomap_kg.storage_rows` remain intact. Table
formatters stay in `rows.py`; `host_mutator_record_from_storage_payload` stays
in `rows.py`; storage SQL, schema files, migrations, package metadata,
lockfiles, dependencies, and test runner policy remain unchanged.
STORAGE-ROWS9 should decide whether table formatters deserve a final small
split or whether final facade cleanup should close the storage rows track.

STORAGE-ROWS9 implementation note: STORAGE-ROWS9 adds
`src/main/python/repomap_kg/storage/table_rows.py` and moves only storage table
formatter helpers out of `rows.py`. `rows.py` imports the moved formatter names
back by name and keeps its 161-name `__all__` compatibility surface stable, so
imports through `repomap_kg.storage.rows`, `repomap_kg.storage`,
`repomap_kg.storage.main`, and `repomap_kg.storage_rows` remain intact.
`host_mutator_record_from_storage_payload` stays in `rows.py`; compatibility
imports and `__all__` are not pruned; storage SQL, schema files, migrations,
package metadata, lockfiles, dependencies, and test runner policy remain
unchanged. STORAGE-ROWS10 should close the storage rows track with a final
facade assessment unless inspection proves a tiny host-mutator decoder split is
cleaner.

STORAGE-ROWS10 closeout note: STORAGE-ROWS10 closes the STORAGE-ROWS track
with an explicit no-move final facade assessment. `rows.py` remains the storage
compatibility facade containing compatibility imports, the stable 161-name
`__all__`, and `host_mutator_record_from_storage_payload`. Root compatibility
exports through `repomap_kg.storage.rows`, `repomap_kg.storage`,
`repomap_kg.storage.main`, and `repomap_kg.storage_rows` are intentionally
retained. SQL, schema, migration, database write, canonicalization,
extraction, CLI, MCP, package metadata, lockfile, dependency, and test runner
behavior were not changed by the STORAGE-ROWS track. The track is closed unless
future work discovers a concrete compatibility or maintainability issue.

MCP-SMOKE0 inventory note: MCP-SMOKE0 records a read-only local MCP smoke
inventory after the CONFIG-REF and STORAGE-ROWS tracks. It adds synthetic unit
characterization for four current MCP issues without changing production
behavior: private-root redaction gaps in project/domain summaries, legacy-only
`repomap_projects` behavior under graph-registry deployments, complete-run
status with null finished timestamps, and `include_raw=false` observation
search semantics that omit full payloads while retaining metadata. Follow-up
fix phases should proceed in that order: MCP-SMOKE1 root redaction,
MCP-SMOKE2 projects compatibility/deprecation, MCP-SMOKE3 run timestamp
semantics, and MCP-SMOKE4 raw/metadata flag semantics.

MCP-SMOKE1 implementation note: MCP-SMOKE1 fixes only the private-root
redaction gap in MCP project and domain summary payloads. `mcp_ops.py` now uses
a graph-aware summary-root redaction helper for `project_summary_payload` and
`summary_payload`, preserving public graph root output while returning
`[private-root]` for private summary root fields. MCP tool names, read-only
safety flags, graph listing/status behavior, discovery, refresh, database
mutation, SQL, schema, migrations, extraction, canonicalization, CLI, package
metadata, lockfiles, dependencies, and test-runner policy remain unchanged.
MCP-SMOKE2 should clarify or fix `repomap_projects` behavior under
graph-registry mode.

MCP-SMOKE2 implementation note: MCP-SMOKE2 keeps `repomap_projects`
compatible with legacy MCP project-config clients while adding additive
graph-registry hint fields: `graph_registry_available`, `graph_count`,
`graphs`, and `message`. Legacy `projects`, `default_project`, and
`allow_project_overrides` fields are preserved. Graph hints are concise and
reuse the graph payload redaction boundary, so private graph roots remain
`[private-root]`; `repomap_list_graphs` remains the primary graph inventory
surface. Discovery, refresh, database mutation, SQL, schema, migrations,
extraction, canonicalization, CLI, package metadata, lockfiles, dependencies,
and test-runner policy remain unchanged. MCP-SMOKE3 should inspect and
normalize or document complete run status with null `latest_run_finished_at`.

MCP-SMOKE3 implementation note: MCP-SMOKE3 preserves stored run status and
timestamp values exactly, including `latest_run_status="complete"` with
`latest_run_finished_at=null`, and adds an MCP-only
`latest_run_consistency` field to `repomap_refresh_status` graph entries and
`repomap_graph_status.storage`. The field reports
`complete_without_finished_at=true` plus a short diagnostic only for the
complete/null combination and reports false otherwise. No timestamps are
invented or backfilled, and discovery, refresh, database mutation, SQL, schema,
migrations, extraction, canonicalization, CLI, package metadata, lockfiles,
dependencies, and test-runner policy remain unchanged. MCP-SMOKE4 should
tighten, rename, or document `include_raw=false` semantics for observation
metadata.

MCP-SMOKE4 implementation note: MCP-SMOKE4 keeps
`repomap_search_observations(include_raw=false)` storage behavior unchanged:
the full top-level raw observation `payload` remains omitted, while bounded
observation `metadata` remains included and sanitized. The MCP response now
adds `raw_payload_policy` for observation searches, and the tool schema
clarifies that `include_raw` controls the full raw payload field only.
SQL, schema, migrations, storage table shape, discovery, refresh, graph
registry behavior, extraction, canonicalization, CLI, package metadata,
lockfiles, dependencies, and test-runner policy remain unchanged. The
MCP-SMOKE0 deferred issue set is closed; future MCP behavior changes should
begin with a fresh read-only smoke assessment.

MCP-HARDEN0 inventory note: MCP-HARDEN0 starts a fresh automated MCP
smoke-hardening track after the MCP-SMOKE issue series. It is docs-only and
maps MCP-SMOKE1 through MCP-SMOKE4 to current synthetic unit coverage, notes
that the container smoke suite currently imports the package and runs CLI help
rather than MCP JSON-RPC/storage contracts, and proposes narrow follow-up
phases for reusable synthetic MCP fixtures, read-only payload contracts,
privacy/redaction invariants, graph-registry compatibility, observation
`include_raw` policy checks, and an optional synthetic Postgres-backed MCP
smoke fixture. No production behavior, tests, SQL, schema, migrations,
extraction, canonicalization, graph registry TOML schema, CLI behavior,
package metadata, lockfiles, dependencies, or test-runner policy changed.

MCP-HARDEN1 implementation note: MCP-HARDEN1 centralizes repeated synthetic
MCP unit-test setup and contract assertions in
`src/test/unit/python/repomap_kg/test_mcp_server.unit.test.py`. It adds shared
helpers for synthetic visible graph-registry config, empty legacy MCP project
config, environment patching, public/private graph payload checks, read-only
safety markers, synthetic private-root serialization checks, synthetic refresh
status construction, observation raw-payload policy checks, and unsafe tool
schema argument checks. The phase refactors existing MCP-SMOKE1 through
MCP-SMOKE4 regression tests and representative graph-backed MCP tests without
broadening into table-driven coverage. No production behavior, MCP response
shape, SQL, schema, migrations, discovery, refresh, graph registry TOML schema,
extraction, canonicalization, CLI behavior, package metadata, lockfiles,
dependencies, or test-runner policy changed. MCP-HARDEN2 should use these
helpers for table-driven read-only MCP payload contract tests.

MCP-HARDEN2 implementation note: MCP-HARDEN2 adds table-driven unit tests for
representative graph-backed read-only MCP payload contracts using the
MCP-HARDEN1 helpers. Coverage now spans `repomap_list_graphs`,
`repomap_graph_status`, `repomap_project_summary`,
`repomap_js_framework_summary`, `repomap_neighborhood`,
`repomap_search_nodes`, `repomap_search_observations`, and
`repomap_search_files` with patched synthetic storage responses. The tests
assert shared read-only safety markers, public graph root visibility, private
graph root redaction, absence of synthetic private roots in serialized
payloads, status consistency fields, summary root behavior, bounded search
metadata, sanitized search results, and observation `raw_payload_policy`.
MCP-SMOKE1 through MCP-SMOKE4 targeted regression tests remain intact. No
production behavior, MCP response shape, SQL, schema, migrations, discovery,
refresh, graph registry TOML schema, extraction, canonicalization, CLI
behavior, package metadata, lockfiles, dependencies, or test-runner policy
changed. MCP-HARDEN3 should deepen privacy/redaction invariant coverage across
private graph payload families.

MCP-HARDEN3 implementation note: MCP-HARDEN3 adds deeper unit-level
privacy/redaction invariant tests across private graph MCP payload families
using the MCP-HARDEN1 helpers and MCP-HARDEN2 table-driven pattern. Coverage
now checks `repomap_list_graphs`, `repomap_projects`, `repomap_graph_status`,
`repomap_neighborhood`, `repomap_search_files`, private Python/Terraform/OpenAPI
and JavaScript framework summaries, and node/observation/file search payloads.
The tests assert that serialized payloads do not contain synthetic private root
tokens, that private summary roots are redacted to `[private-root]`, and that
secret-like metadata and credentialed synthetic URLs are redacted. MCP-SMOKE1
through MCP-SMOKE4 targeted regression tests, MCP-HARDEN1 helpers, and
MCP-HARDEN2 contract tests remain intact. No production behavior, MCP response
shape, SQL, schema, migrations, discovery, refresh, graph registry TOML schema,
extraction, canonicalization, CLI behavior, package metadata, lockfiles,
dependencies, or test-runner policy changed. MCP-HARDEN4 should add
graph-registry compatibility smoke tests for legacy-only, graph-registry-only,
mixed, hidden, disabled, private-visible, unavailable-registry, and stable
`repomap_projects` compatibility-field behavior.

MCP-HARDEN4 implementation note: MCP-HARDEN4 adds unit-level graph-registry
compatibility tests for MCP project/listing behavior. Coverage now pins
legacy-only, graph-registry-only, and mixed `repomap_projects` modes; stable
legacy fields (`projects`, `default_project`, `allow_project_overrides`);
additive graph hint fields (`graph_registry_available`, `graph_count`,
`graphs`, `message`); `repomap_list_graphs` as the primary graph inventory
surface; hidden and disabled graph rejection across project summary, graph
status, neighborhood, and search wrappers; private-visible graph root redaction
and structured warnings; and safe unavailable-registry diagnostics. MCP-SMOKE1
through MCP-SMOKE4 targeted regression tests and MCP-HARDEN1 through
MCP-HARDEN3 tests remain intact. No production behavior, MCP response shape,
SQL, schema, migrations, discovery, refresh, graph registry TOML schema,
extraction, canonicalization, CLI behavior, package metadata, lockfiles,
dependencies, or test-runner policy changed. MCP-HARDEN5 should promote
observation-search raw payload policy checks into reusable contract tests.

MCP-HARDEN5 implementation note: MCP-HARDEN5 adds reusable unit-level contract
tests for `repomap_search_observations` raw payload policy behavior. Coverage
pins `include_raw=false` and `include_raw=true` query dispatch, full raw
payload omission/inclusion, metadata retention, `raw_payload_policy` flags,
tool-schema wording for full raw payload semantics, bounded observation search
fields, and synthetic secret/credentialed-URL redaction while safe synthetic
metadata remains visible. MCP-SMOKE4 targeted regression tests and
MCP-HARDEN1 through MCP-HARDEN4 tests remain intact. No production behavior,
MCP response shape, SQL, schema, migrations, discovery, refresh, graph registry
TOML schema, extraction, canonicalization, CLI behavior, package metadata,
lockfiles, dependencies, or test-runner policy changed. MCP-HARDEN6 should
evaluate whether a small synthetic Postgres-backed MCP smoke fixture is still
justified, starting as an evaluation/design phase unless a safe fixture path is
already obvious.

MCP-HARDEN6 evaluation note: MCP-HARDEN6 stays docs-only and evaluates the
remaining mocked-versus-real MCP coverage gap after MCP-HARDEN1 through
MCP-HARDEN5. The existing integration suite already has a disposable Postgres
harness plus storage-backed direct MCP wrapper and in-process JSON-RPC coverage,
while the container smoke suite remains package import plus CLI help. The
worthwhile remaining gap is narrow: real-storage observation
`include_raw=false`/`include_raw=true` semantics, private summary-root
redaction after storage decoding, and optionally one small JSON-RPC
`tools/list`/`tools/call` assertion. MCP-HARDEN7 should implement the smallest
safe integration-level synthetic storage-backed MCP smoke extension using the
existing harness, without discovery, refresh, real graph databases,
long-running MCP servers, or container-smoke expansion.

MCP-HARDEN7 implementation note: MCP-HARDEN7 extends the existing
storage-backed MCP integration test in
`src/test/int/python/repomap_kg/test_storage.int.test.py` using the disposable
Postgres harness and synthetic fixture JSONL already present in the suite. It
pins real-storage `repomap_search_observations` `include_raw=false` and
`include_raw=true` behavior, private `repomap_project_summary` root redaction
after storage decoding, and one tiny in-process JSON-RPC `tools/list` safety
assertion. No production behavior, MCP tool names or schemas, SQL, schema,
migrations, storage table shape, discovery, refresh, graph registry TOML
schema, extraction, canonicalization, CLI behavior, package metadata,
lockfiles, dependencies, test-runner policy, container smoke, or real graph
database access changed. MCP-HARDEN8 should close out the MCP-HARDEN track with
a concise summary/status doc unless a new protocol-level gap appears.

MCP-HARDEN8 closeout note: MCP-HARDEN8 closes the automated MCP-HARDEN track
after MCP-HARDEN0 through MCP-HARDEN7. The final state includes reusable
synthetic MCP helpers, table-driven read-only payload contracts,
privacy/redaction invariants, graph-registry compatibility coverage,
observation raw payload policy contracts, a docs-only Postgres smoke
evaluation, and the tiny storage-backed MCP integration smoke extension. The
track intentionally defers long-running MCP server smoke, container-smoke MCP
expansion, broad domain-summary matrices, refresh/discovery-backed setup, real
private graph readback, new SQL/schema/storage behavior, and broad JSON-RPC
protocol matrices. Future MCP hardening should start with a fresh inventory
phase when a concrete new MCP tool family, graph-registry behavior, privacy
incident, raw-payload semantic, storage readback path, or CI/container
requirement appears. This closeout is docs-only and changes no production
behavior, tests, MCP behavior, SQL, schema, migrations, extraction,
canonicalization, CLI behavior, package metadata, lockfiles, dependencies, or
test-runner policy.

LIVE-OPS1 implementation note: LIVE-OPS1 fixes the live smoke bug where
successful `ops refresh-graph` runs returned an operation-level `finished_at`
timestamp while stored run readback still showed `latest_run_status="complete"`
with `latest_run_finished_at=null`. The fix is in the storage SQL write path:
completed ingest scripts now finalize the run row with `finished_at=now()`
before commit, while CLI and MCP readback continue reporting stored truth. The
phase adds focused unit SQL-builder coverage plus disposable-Postgres
integration assertions for CLI refresh-status and in-process MCP graph/refresh
status. It does not change MCP field names or schemas, add migrations, alter
schema/storage table shape, change extraction/canonicalization behavior, or
touch configured/private graph databases.

LIVE-OPS2 implementation note: LIVE-OPS2 resolves the live smoke gap where
graph-registry MCP tools accepted `graph_id="codex-memories"` but legacy
project-scoped tools rejected `project="codex-memories"` as an unknown legacy
project. Legacy MCP project config still resolves first. When no legacy
project matches, the legacy storage readback tools now route `project=<name>`
through the existing graph-registry context if the graph exists, is enabled,
and is MCP-visible. Private graph status keeps using the real root internally
for storage filtering but returns `[private-root]` in the legacy status
payload. The phase adds synthetic unit coverage for routing, legacy precedence,
disabled/hidden rejection, safe diagnostics, private-root redaction, and schema
wording. It does not change graph-id MCP tools, SQL, schema, migrations,
storage table shape, extraction, canonicalization, graph registry TOML schema,
CLI behavior, package metadata, lockfiles, dependencies, test-runner policy, or
configured graph databases.

LIVE-OPS3 implementation note: LIVE-OPS3 fixes the live smoke diagnostic gap
where graph readback after an authorized database drop could report a missing
graph database while also claiming no running RepoMap-owned Postgres container
was available. The ops psql error path now classifies PostgreSQL
`database ... does not exist` failures separately and returns a sanitized
missing-or-not-initialized graph database diagnostic without appending runtime
availability guidance. Runtime/container-unavailable diagnostics remain
distinct. The phase adds synthetic unit coverage for missing-database
classification, MCP `repomap_graph_status` propagation, private-path/raw-command
omission, and runtime-unavailable separation. It does not change MCP schemas,
SQL, migrations, storage table shape, graph registry TOML schema, lifecycle
semantics, extraction, canonicalization, CLI behavior beyond diagnostic
wording, package metadata, lockfiles, dependencies, test-runner policy, or
configured graph databases.

LIVE-OPS4 implementation note: LIVE-OPS4 clarifies the live smoke ambiguity
where repeated refresh/load runs accumulate raw observations while canonical
node and edge counts remain stable. The existing `raw_observations` field is
preserved as the compatibility historical total, and status/summary/storage
readback now adds explicit `raw_observations_total` and
`latest_run_raw_observations` fields. Graph summary readback also adds
`latest_run_observation_kind_counts`, and human-readable ops labels now use
`raw_total` and `raw_latest`. The phase derives latest-run counts from the
existing `raw_observations.run_id` relationship, adds unit coverage plus a
disposable-Postgres repeated-run integration test, and does not change raw
retention, canonicalization, schema, migrations, graph registry TOML schema,
package metadata, lockfiles, dependencies, test-runner policy, or configured
graph databases.

LIVE-OPS5 implementation note: LIVE-OPS5 tightens the high-level local
lifecycle JSON/table boundary after the codex-memories live smoke showed that
successful lifecycle commands exposed low-level Docker/Postgres command plans
and local runtime paths. Default JSON now preserves operator-facing result,
backup, checksum, restore-support, safety, and bounded count fields while
omitting raw planned commands, runtime home paths, backup paths, manifest paths,
restore paths, dump paths, command environment details, and raw manifest restore
hints. Tests keep validating lower-level execution details through internal
result objects and mocked command runners. The phase does not change lifecycle
semantics, backup-first behavior, runtime orchestration, MCP behavior, SQL,
schema, migrations, graph registry TOML schema, extraction, canonicalization,
package metadata, lockfiles, dependencies, test-runner policy, or configured
graph databases.

LIVE-OPS6 implementation note: LIVE-OPS6 adds the bounded high-level
`repomap-kg local db backup-inspect` command after the codex-memories live
smoke needed separate dump TOC inspection to validate backup contents.
`backup-inspect` reuses manifest/checksum verification, performs bounded
custom-format dump TOC listing through the existing owned-runtime boundary, and
reports public-safe table counts, table-data counts, expected RepoMap table
presence, and explicit safety booleans without exposing raw dump contents,
local paths, environment details, or raw Docker/Postgres command arrays.
`backup-info` remains manifest-only with `dump_contents_read=false`. The phase
adds unit coverage plus a CLI-level synthetic integration smoke and does not
change backup format, backup creation, restore behavior, lifecycle semantics,
MCP behavior, SQL, schema, migrations, graph registry TOML schema, extraction,
canonicalization, package metadata, lockfiles, dependencies, test-runner
policy, or configured graph databases.

LIVE-HARDEN0 inventory note: LIVE-HARDEN0 is a docs-only inventory that maps
LIVE-OPS1 through LIVE-OPS6 escaped live-deployment issues to current
automated coverage and the smallest remaining smoke-hardening increments
before the local flakes live smoke. The inventory finds strong targeted
coverage already exists: LIVE-OPS1 and LIVE-OPS4 have disposable-Postgres
storage/MCP integration, LIVE-OPS2 and LIVE-OPS3 are intentionally unit-level
for MCP routing and diagnostic classification, and LIVE-OPS5 and LIVE-OPS6
have lifecycle CLI integration with temporary homes and mocked runners. The
remaining pre-flakes hardening should stay narrow: a lifecycle CLI smoke chain
around backup-first drop and bounded backup-inspect, a storage-backed
refresh/status smoke combining persisted `finished_at` with latest-vs-total raw
counts, a graph-registry/legacy routing smoke using synthetic config, and a
short readiness closeout before starting flakes. This inventory changes no
production behavior, tests, MCP behavior, lifecycle behavior, SQL, schema,
migrations, storage table shape, graph registry TOML schema, extraction,
canonicalization, CLI behavior, package metadata, lockfiles, dependencies,
test-runner policy, configured local graphs, or real graph databases.

LIVE-HARDEN1 implementation note: LIVE-HARDEN1 adds one CLI-level lifecycle
smoke chain in `src/test/int/python/repomap_kg/test_cli.int.test.py` using a
synthetic temporary RepoMap home, a synthetic database name, and mocked
lifecycle command runners. The smoke chains local setup, backup-first local DB
drop, bounded `backup-inspect` JSON/table output, and `backup-info` readback
against the produced synthetic backup artifact. It asserts high-level
backup-first safety fields, manifest/checksum verification, bounded TOC/table
summaries, `raw_dump_contents_exposed=false`,
`planned_command_exposed=false`, and `backup-info` manifest-only compatibility.
It also checks public outputs do not expose temporary paths, backup paths,
manifest paths, dump paths, restore paths, raw dump bytes, raw command forms,
or environment details. The phase changes no production behavior, backup
format, restore behavior, lifecycle semantics, MCP behavior, SQL, schema,
migrations, graph registry TOML schema, extraction, canonicalization, package
metadata, lockfiles, dependencies, test-runner policy, configured local graphs,
or real graph databases. LIVE-HARDEN2 should add the storage-backed repeated
refresh/status smoke that composes LIVE-OPS1 and LIVE-OPS4 expectations.

LIVE-HARDEN2 implementation note: LIVE-HARDEN2 adds one storage-backed
repeated refresh/status smoke in
`src/test/int/python/repomap_kg/test_storage.int.test.py` using synthetic
fixture data and disposable Postgres. The smoke loads the same fixture twice
through the storage `load-files` path, then verifies persisted `finished_at`,
MCP `complete_without_finished_at=false` consistency, historical
`raw_observations`/`raw_observations_total` accumulation, one-run
`latest_run_raw_observations`, stable canonical node and edge counts, and MCP
graph/refresh status readback of the clarified fields. The phase changes no
production behavior, SQL, schema, migrations, storage table shape, extraction,
canonicalization, MCP behavior, lifecycle behavior, graph registry TOML schema,
package metadata, lockfiles, dependencies, test-runner policy, configured
local graphs, or real graph databases. LIVE-HARDEN3 should add the
graph-registry/legacy MCP routing smoke with synthetic config, hidden/disabled
rejection, and private-root redaction.

LIVE-HARDEN3 implementation note: LIVE-HARDEN3 adds one in-process MCP
routing smoke in `src/test/unit/python/repomap_kg/test_mcp_server.unit.test.py`
using synthetic graph-registry config and patched storage responses. The smoke
proves graph-id tools and legacy `project=<graph_id>` fallback work together
for the same enabled MCP-visible graph, asserts same-named legacy project
config still takes precedence, rejects hidden and disabled graph ids before
storage query, and verifies private visible graph routes use the real root
internally while public routing/readback payloads return `[private-root]` and
do not expose private-root, local-home, username, config-path, command, token,
or secret markers. The phase changes no production behavior, SQL, schema,
migrations, storage table shape, extraction, canonicalization, MCP tool names
or schemas, lifecycle behavior, graph registry TOML schema, package metadata,
lockfiles, dependencies, test-runner policy, configured local graphs, or real
graph databases. LIVE-HARDEN4 should be a docs-only readiness closeout for the
local flakes live smoke.

LIVE-HARDEN4 closeout note: LIVE-HARDEN4 closes the pre-flakes
LIVE-HARDEN sequence as a docs-only readiness checkpoint. The closeout
summarizes LIVE-HARDEN0 through LIVE-HARDEN3, records the automated net now
covering lifecycle backup/output safety, storage refresh/status semantics, and
MCP graph-registry/legacy routing, and provides the safe checklist for the next
live smoke against the local `flakes` graph. It explicitly defers unrelated
refactors, broad protocol matrices, long-running server/container smoke
expansion, real dump restore verification, unrelated graph refreshes, schema
or migration changes, extraction/canonicalization changes, and package or test
runner changes. The next phase should be a live smoke report such as
LIVE-FLAKES0, not a code/test phase unless the flakes run finds a concrete
missing hardening gap.

LIVE-FLAKES0 smoke note: LIVE-FLAKES0 ran the bounded live smoke against the
local private `flakes` graph through high-level RepoMap CLI, MCP, and
lifecycle/status surfaces. The phase performed read-only registry/runtime
checks, a graph-scoped refresh preflight, one graph-scoped `flakes` refresh,
post-refresh status/summary readback, bounded domain/search/neighborhood
probes, and legacy `project="flakes"` fallback probes. It did not run broad
`refresh-enabled`, operate on unrelated graphs beyond read-only inventory,
run direct Postgres/container commands, perform destructive lifecycle actions,
produce backups, save baselines, or change source/tests. Final graph-id status
readback was healthy after refresh: the completed run persisted
`finished_at`, MCP readback showed `complete_without_finished_at=false`, and
total/latest raw counts were distinct. The smoke found follow-up gaps:
host-side legacy `project="flakes"` canonical readback fails through a
container-internal `postgres` host name, `config.path` observation metadata can
expose a local username for a private graph, CLI status/summary does not
surface the same populated consistency object as MCP, and no Nix/flakes
domain summary exists yet. Follow-up should use narrow LIVE-OPS-style phases
before aggressive refactoring resumes.

LIVE-OPS7 implementation note: LIVE-OPS7 fixes the LIVE-FLAKES0 host-side
legacy fallback bug where `project="flakes"` status/canonical readback could
try a container-internal Postgres host directly even though graph-id MCP tools
worked for the same graph. Graph-registry fallback connections now carry the
resolved ops graph context, and legacy storage readback dispatches through the
same ops-aware psql/container fallback strategy used by graph-id MCP tools.
Legacy JSON project config precedence, hidden/disabled rejection, explicit
connection override rejection, and private-root redaction are preserved. The
phase adds synthetic unit coverage for an unresolved `postgres` host with
simulated container fallback and does not change MCP schemas, SQL, schema,
migrations, storage table shape, graph registry TOML schema, extraction,
canonicalization, lifecycle behavior, package metadata, lockfiles,
dependencies, test-runner policy, configured real graphs, discovery, refresh,
or real graph databases. LIVE-OPS8 should fix the `config.path` observation
metadata privacy leak for private graphs unless a more severe adjacent issue
appears first.

LIVE-OPS8 implementation note: LIVE-OPS8 fixes the LIVE-FLAKES0 private graph
`config.path` observation metadata leak at the public readback serialization
boundary. Private graph observation search now redacts path-shaped metadata and
raw payload strings that contain private graph roots, graph config paths, local
home markers, or local usernames, including with both `include_raw=false` and
`include_raw=true`. Public/dev graph metadata remains compatible when safe,
and the phase adds synthetic unit coverage for private redaction, raw payload
redaction, public metadata preservation, bounded pagination, and diagnostic
safety. The phase does not change MCP schemas, SQL, schema, migrations,
storage table shape, graph registry TOML schema, extraction, canonicalization,
lifecycle behavior, package metadata, lockfiles, dependencies, test-runner
policy, configured real graphs, discovery, refresh, or real graph databases.
LIVE-OPS9 should address the CLI `latest_run_consistency` consistency gap
found during LIVE-FLAKES0; NIX-SUMMARY0 remains a later design follow-up for
Nix/flakes domain summaries.

LIVE-OPS9 implementation note: LIVE-OPS9 aligns CLI/ops JSON readback with MCP
graph/refresh status by adding `latest_run_consistency` to refresh-status graph
rows and graph-summary graph payloads. The object uses the same completion
timestamp semantics as MCP: complete runs with null `latest_run_finished_at`
report `complete_without_finished_at=true` plus the existing diagnostic, and
all other combinations report false. Existing JSON fields, table output, MCP
tool behavior, storage semantics, SQL, schema, migrations, storage table shape,
graph registry TOML schema, extraction, canonicalization, lifecycle behavior,
package metadata, lockfiles, dependencies, test-runner policy, configured real
graphs, discovery, refresh, and real graph databases remain unchanged. The
phase adds synthetic unit coverage plus storage-backed disposable Postgres
assertions in the existing LIVE-HARDEN2 smoke. LIVE-FLAKES1 should re-smoke the
fixed flakes paths before NIX-SUMMARY0 begins Nix/flakes domain-summary design.

LIVE-FLAKES1 re-smoke note: LIVE-FLAKES1 re-smoked the local private `flakes`
graph without discovery, refresh, lifecycle actions, backups, baselines, direct
manual Postgres/container commands, unrelated graph mutation, or raw private
payload capture. Graph-id MCP status and refresh-status remained healthy, and
CLI/ops refresh-status plus graph-summary JSON now expose
`latest_run_consistency.complete_without_finished_at=false` for the complete
latest run. The current checkout's high-level MCP function path also validates
the LIVE-OPS7 legacy fallback fix and the LIVE-OPS8 private `config.path`
metadata redaction. The already-running live MCP connector still fails legacy
`project="flakes"` fallback with the old unresolved internal Postgres host
behavior, so the next phase should be LIVE-OPS10 to restart/reload or otherwise
verify the live MCP connector runtime and rerun only the stale connector checks
before NIX-SUMMARY0 proceeds.

LIVE-OPS10 verification note: LIVE-OPS10 confirmed the already-running RepoMap
MCP connector was stale relative to the approved checkout: exact MCP server
processes predated the current commit and still failed legacy
`project="flakes"` fallback with the old internal-Postgres-host behavior, while
the current checkout's high-level MCP function path succeeded. The local Codex
MCP configuration points at the current checkout, but the available `codex mcp`
surface has no restart/reload command. Terminating the exact connector
processes closed the MCP transport and Codex did not respawn a fresh connector
inside the thread, so post-reload live connector validation remains blocked by
an operational lifecycle gap. No source, tests, discovery, refresh, graph
database mutation, direct Postgres/container commands, backups, baselines, or
raw private output capture were performed. LIVE-OPS11 should document or add a
safe connector lifecycle/version-reporting path before retrying the
connector-only checks and before NIX-SUMMARY0 proceeds.

LIVE-OPS11 lifecycle note: LIVE-OPS11 documented the safe connector lifecycle
procedure instead of changing MCP schemas. The current RepoMap MCP surface
already reports package/server version through existing status/initialize
paths, but that is not enough to prove commit freshness for a long-running
connector when the package version is unchanged. Future connector-only smokes
should reload Codex Desktop or start a fresh connector-bearing session after
source changes, confirm the connector is callable through sanitized high-level
checks, then rerun only the blocked legacy fallback and private observation
redaction checks. If a fresh connector still fails legacy `project="flakes"`
fallback, split a new LIVE-OPS source phase; if it passes, proceed to
LIVE-FLAKES2 and then NIX-SUMMARY0.

LIVE-FLAKES2 validation note: LIVE-FLAKES2 attempted the connector-only fresh
validation, but the current session exposed RepoMap MCP tool metadata while the
underlying connector transport remained closed and no RepoMap MCP server process
was running. No graph-id, legacy fallback, or observation privacy payloads could
be read through the live connector, and the phase intentionally skipped
`include_raw=true` observation readback. The result is an operational connector
lifecycle gap, not a product behavior verdict. LIVE-OPS12 should provide a more
reliable connector lifecycle/status recovery path that distinguishes discovered
tools from a callable server transport before retrying the connector-only
flakes checks.

LIVE-OPS12 lifecycle/status note: LIVE-OPS12 documented the connector state
ladder for future live smokes: tools discovered in Codex metadata, transport
callable, server process running, runtime plausibly fresh, and source behavior
validated. The safe recovery path for `Transport closed` is to stop the smoke,
avoid `include_raw=true`, avoid killing MCP processes inside the thread, record
the state as discovered-but-closed, perform an app/session-level Codex reload or
start a new connector-bearing session, then retry a harmless liveness probe
before graph validation. No MCP schema, CLI behavior, source tests, discovery,
refresh, storage mutation, direct Postgres/container command, or raw private
output capture changed. LIVE-FLAKES3 should retry only the connector-blocked
flakes checks once a truly callable fresh connector is available.

LIVE-FLAKES3 validation note: LIVE-FLAKES3 retried the connector-only flakes
checks from the LIVE-OPS12 liveness-first procedure, but the first harmless
`repomap_graph_status(graph_id="flakes")` probe returned `Transport closed`.
The phase stopped immediately and did not run refresh status, legacy fallback,
observation search, `include_raw=true`, discovery, refresh, database/container
commands, source/test changes, or raw private output capture. The result
remains an unresolved operational connector lifecycle gap rather than a
RepoMap product behavior verdict. Unless live connector validation must be
unblocked first, proceed to NIX-SUMMARY0 using graph-id/source-checkout
validation as sufficient design context.

NIX-SUMMARY0 design note: NIX-SUMMARY0 inspected the existing static Nix
extractor, Nix/config canonicalization, domain-summary plumbing, tests,
fixtures, and sanitized flakes status notes, then documented a docs-only
design for first-class Nix/flakes summary support. The proposed first summary
is a count-only `nix` domain summary over existing raw observations and
canonical graph records, with no Nix evaluation, fetches, flake-lock
resolution, path values, raw payloads, SQL/schema changes, extraction changes,
or MCP behavior changes in this phase. Follow-up work should start with
NIX-SUMMARY1 characterization tests, then add storage/CLI summary readback,
MCP `repomap_nix_summary(graph_id=...)`, private redaction coverage, and a
bounded flakes smoke in separate phases.

NIX-SUMMARY1 implementation note: NIX-SUMMARY1 added focused characterization
tests for the current Nix/flakes and related config evidence before any
summary implementation. The tests pin `nix_flake_basic` raw counts for
`nix.import`, `nix.path_ref`, `nix.app`, `nix.package`, `nix.devShell`, and
`nix.check`; canonical output node counts; `defines`, `sources`, and
`exposes_script` edge counts; and the current raw-only behavior for
`nix.path_ref`. The phase also characterizes generic config document, path,
reference, parse-error, and canonical edge counts using existing synthetic YAML
fixtures. No production behavior, fixtures, discovery, refresh, storage,
schema, MCP, CLI, lifecycle, package metadata, lockfile, dependency, or private
data boundary changed.

NIX-SUMMARY2 implementation note: NIX-SUMMARY2 added the first count-only
storage and CLI readback surface for a Nix/flakes summary. The new
`repomap-kg storage nix-summary` command and storage helpers summarize existing
raw Nix observations, canonical Nix output nodes, Nix-backed canonical edges,
program/path-reference buckets, generic config evidence, diagnostics,
limitations, and safety markers. The output is path-free: `root_path` is a
bounded marker, and the summary omits import paths, app program paths, config
value summaries, raw payloads, source snippets, command strings, flake input
URLs, environment values, tokens, and secrets. No MCP tool, extraction,
canonicalization, schema, migration, lifecycle, package metadata, lockfile,
dependency, discovery, refresh, or real graph database behavior changed.

NIX-SUMMARY3 implementation note: NIX-SUMMARY3 exposed the count-only
Nix/flakes summary through graph-scoped MCP as
`repomap_nix_summary(graph_id=...)`. The tool follows the existing domain
summary payload pattern, resolves graph ids through graph-registry visibility
gates, and uses the same ops-aware storage readback path as the Python,
Terraform, OpenAPI, and JS framework summaries. The MCP payload preserves the
NIX-SUMMARY2 path-free contract and private-root redaction; no extraction,
canonicalization, storage SQL/count contract, schema, migration, lifecycle,
package metadata, lockfile, dependency, discovery, refresh, or real graph
database behavior changed. NIX-SUMMARY4 should add synthetic private
storage-backed integration coverage.

NIX-SUMMARY4 implementation note: NIX-SUMMARY4 added storage-backed
integration and private redaction coverage for the count-only Nix/flakes
summary. A disposable Postgres test now loads the synthetic `nix_flake_basic`
fixture through `storage load-files`, verifies direct storage and CLI
`nix-summary` JSON/table readback, and exercises MCP
`repomap_nix_summary(graph_id=...)` for public and synthetic private graph
wrappers. The test asserts the characterized Nix observation, canonical node,
canonical edge, program, path-reference, diagnostics, limitations, and safety
counts while proving private roots and path-shaped values stay redacted or
omitted. No extraction, canonicalization, storage SQL/count contract, schema,
migration, lifecycle, package metadata, lockfile, dependency, discovery,
refresh, real graph database, or private-data behavior changed. NIX-SUMMARY5
should run a bounded source-checkout flakes smoke for the new Nix summary.

NIX-SUMMARY5 smoke note: NIX-SUMMARY5 validated the count-only Nix/flakes
summary against the stored private `flakes` graph through the source-checkout
graph-id readback path. The smoke confirmed read-only behavior, private-root
redaction, path-free serialization, Nix import/path-reference counts, generic
config counts, safety markers, and static-summary limitation markers without
discovery, refresh, direct database/container commands, Nix execution, or raw
private output capture. Live connector validation remained blocked by the known
`Transport closed` lifecycle gap and was not treated as a Nix summary product
failure. The real graph reported Nix imports and path references, but static
flake output counts remained zero; NIX-SUMMARY6 should close out or design the
next safe flake-file/output summary refinement.

NIX-SUMMARY6 closeout note: NIX-SUMMARY6 accepted NIX-SUMMARY0 through
NIX-SUMMARY5 as a complete first count-only/path-free Nix summary increment.
The closeout records that the current summary is useful for Nix
import/path-reference and generic config counts on the real private `flakes`
graph, while richer real flake output shape remains a feature gap. The next
recommended implementation is NIX-SUMMARY7: refine `flake_files` to count
observed flake files independently from extracted output observations and add
a count-only diagnostic for observed flake files without extracted outputs,
without changing extraction, canonicalization, schema, lifecycle, package
metadata, dependencies, discovery, refresh, or the private-data boundary.

NIX-SUMMARY7 implementation note: NIX-SUMMARY7 refined the Nix summary
`flake_files` count to use observed `flake.nix` file observations rather than
only files that emitted static flake output observations. It added the
count-only diagnostic `flake_files_without_output_observations`, kept raw and
canonical output counts unchanged, preserved CLI/MCP path-free serialization,
and updated unit plus disposable-storage integration coverage. No extraction,
canonicalization, MCP schema, SQL schema, migration, lifecycle, package
metadata, dependency, discovery, refresh, real graph database, or private-data
behavior changed. NIX-SUMMARY8 should run a bounded source-checkout flakes
smoke for the refined flake-file semantics, with NIX-EXTRACT0 still available
as the follow-up design phase for richer real-flakes static extraction.

NIX-SUMMARY8 smoke note: NIX-SUMMARY8 validated the refined count-only Nix
summary against the stored private `flakes` graph through the source-checkout
graph-id path. The smoke confirmed `flake_files=1`,
`flake_files_without_output_observations=1`, unchanged zero raw/canonical
flake output counts, read-only safety markers, static-summary limitation
markers, private-root redaction, and path-free serialization. No discovery,
refresh, direct database/container commands, Nix execution, connector recovery,
source/test changes, or raw private output capture occurred. The next useful
phase is NIX-EXTRACT0 to design richer static extraction for real flake
outputs, inputs, modules, overlays, packages, dev shells, and checks while
preserving count-only/path-free summary defaults.

NIX-EXTRACT0 design note: NIX-EXTRACT0 inspected the current static Nix
extractor, Nix canonicalization, synthetic fixtures, and NIX-SUMMARY real
flakes findings, then designed a safe roadmap for richer real-flakes evidence.
The design recommends characterization fixtures first, then additive raw
observations for flake inputs, output sections, dynamic output shapes, and
unsupported flake shapes before any canonicalization or summary expansion. It
keeps Nix evaluation, Nix CLI, flake input fetches, lock resolution, store
inspection, path values, URLs, source snippets, command strings, secrets, and
private graph data out of scope. NIX-EXTRACT1 should add synthetic
real-flake-shape fixtures and characterization tests only.

NIX-EXTRACT1 implementation note: NIX-EXTRACT1 added synthetic
real-flake-shape fixtures for nested output sections, helper-framework
generated outputs, flake inputs, module/overlay sections, merged attrsets,
imported outputs, and unsupported shapes. Characterization tests now pin the
current extractor behavior: imports and path references are still emitted where
the existing extractor recognizes them, but richer real-flake output shapes do
not fabricate `nix.app`, `nix.package`, `nix.devShell`, or `nix.check`
observations and no new future observation kinds are emitted yet. NIX-EXTRACT2
should use these fixtures to add static input and output-section observations
without Nix evaluation, CLI execution, fetches, lock resolution, store
inspection, or path/value exposure in public readback.

NIX-EXTRACT2 implementation note: NIX-EXTRACT2 added additive raw
`nix.flake_input` and `nix.output_section` observations for `flake.nix` files.
Input observations store only alias names, booleans, source categories, and
redaction markers; output-section observations store only section, family,
scope, shape, and confidence metadata. Literal URLs, path input values, source
snippets, command strings, and private/local values remain out of the new
payloads. Existing import, path-reference, and direct dotted app/package/dev
shell/check extraction remains stable, and dynamic or unsupported shapes still
do not fabricate concrete output observations. NIX-EXTRACT3 should add dynamic
and unsupported-shape diagnostics such as `nix.dynamic_output_shape` and
`nix.unsupported_flake_shape`.

NIX-EXTRACT3 implementation note: NIX-EXTRACT3 added additive raw
`nix.dynamic_output_shape` and `nix.unsupported_flake_shape` diagnostics for
`flake.nix` files. Dynamic diagnostics count helper-generated output sections
such as `eachDefaultSystem`, `genAttrs`, and `forAllSystems`; unsupported
diagnostics count imported outputs, merged attrsets, inherited output
sections, nested attrsets without direct identities, and count-only
template/legacy sections. The diagnostics store only pattern, section, reason,
counted-only, and confidence metadata; they do not store raw expressions,
paths, URLs, command strings, source snippets, or private/local values.
Existing input, section, import, path-reference, and direct dotted output
extraction remains stable. NIX-SUMMARY10 should extend the count-only Nix
summary to count the new input, section, dynamic, and unsupported evidence, or
NIX-CANON0 can design canonicalization first if that boundary needs to be
settled before summary expansion.

NIX-SUMMARY10 implementation note: NIX-SUMMARY10 extended the count-only
Nix/flakes summary to count `nix.flake_input`, `nix.output_section`,
`nix.dynamic_output_shape`, and `nix.unsupported_flake_shape`. The storage SQL
now emits nested count maps for input source categories, output sections by
section/family/shape, dynamic output-shape patterns, and unsupported-shape
patterns. CLI JSON/table output and MCP `repomap_nix_summary(graph_id=...)`
expose the same count-only maps through the existing summary path. The summary
remains path-free and does not expose input names, URLs, source snippets, raw
expressions, command strings, private roots, usernames, tokens, or secrets. No
extraction, canonicalization, schema, lifecycle, package/dependency, discovery,
refresh, or real graph database behavior changed. NIX-LIVE0 should run a
bounded source-checkout smoke against the stored private flakes graph, or
NIX-CANON0 can first design canonicalization for the new Nix evidence if that
boundary needs to be settled.

NIX-LIVE0 smoke note: NIX-LIVE0 validated
`repomap_nix_summary(graph_id="flakes")` through the source-checkout graph-id
path against the stored private `flakes` graph. Existing Nix counts remained
present and safe: 158 Nix observations, 64 Nix files, 1 observed flake file,
50 imports, 108 path references, and one flake file without extracted output
observations. The new NIX-SUMMARY10 maps for flake inputs, output sections,
dynamic output shapes, and unsupported flake shapes were present and
path-free, but all were zero in the current stored graph. That is a stored
graph freshness gap, not a summary-readback product bug, because the graph was
not refreshed in this no-refresh smoke after NIX-EXTRACT2 and NIX-EXTRACT3.
Next, run an explicitly authorized graph-scoped refresh/smoke if the new
extractor evidence should be loaded into `flakes`, or proceed to NIX-CANON0
with synthetic fixtures if canonicalization design should come first.

NIX-LIVE1 refresh/smoke note: NIX-LIVE1 ran the explicitly authorized
graph-scoped refresh for only the private `flakes` graph, then re-smoked
`repomap_nix_summary(graph_id="flakes")` through the source-checkout graph-id
path. The refresh succeeded with 335 files and 10095 observations in the latest
run. Existing Nix summary counts increased to 241 Nix observations, 96 Nix
files, 75 imports, and 162 path references, with the observed flake-file count
still 1 and concrete output/canonical output counts still zero. The expanded
NIX-SUMMARY10 maps are present and safe; flake input counts are now nonzero
with 4 redacted inputs, while output-section, dynamic-shape, and
unsupported-shape maps remain zero. Classify this as partial live success plus
a real-flakes extractor/source-shape coverage gap rather than a summary
readback bug. Next, use synthetic fixtures or sanitized source-checkout
findings to improve static flake output-shape extraction, or run NIX-CANON0 if
canonicalization boundaries should be designed first.

NIX-EXTRACT4 analysis note: NIX-EXTRACT4 analyzed the refreshed real-flakes
output-shape gap without changing code, tests, fixtures, storage, CLI, or MCP
behavior. The current flake input scanner works because it uses a small
brace-depth pass over visible `inputs = { ... }` attrsets, while the
output-section scanner still depends on line-start section assignments matched
by `OUTPUT_SECTION_PATTERN`. Sanitized source-shape classification for the
private graph found one flake file with four safe input categories but zero
section-line matches, zero concrete output attr matches, and generic categories
including `outputs-wrapper-multiline`, `let-wrapped-output-attrset`,
`nested-under-outputs-function`, `no-visible-section-line-found`, and
`scanner-pattern-too-strict`. Next, NIX-EXTRACT5 should add public synthetic
fixtures for that shape and characterize current zero behavior, then
NIX-EXTRACT6 should implement a narrow brace-aware/static output-body scanner
that remains count-only, path-free, and non-evaluating.

NIX-EXTRACT5 implementation note: NIX-EXTRACT5 added public synthetic fixtures
for the sanitized real-flakes output-shape gap:
`wrapped_multiline_outputs_sections`, `inline_open_brace_output_sections`, and
`wrapper_generated_output_sections`. The characterization tests pin current
behavior: these fixtures may emit safe flake-input counts, but they emit zero
`nix.output_section`, zero `nix.dynamic_output_shape`, zero
`nix.unsupported_flake_shape`, and zero concrete app/package/dev-shell/check
observations under the existing scanner. The fixtures intentionally avoid raw
private material, real URLs, path input values, source snippets, command
strings, token/secret markers, and relative path payloads. NIX-EXTRACT6 should
use these fixtures to implement a narrow brace-aware/static output-body scanner
without adding Nix evaluation, canonicalization, storage, CLI, MCP, schema, or
lifecycle changes.

NIX-EXTRACT6 implementation note: NIX-EXTRACT6 added a narrow static
output-body scanner for visible section keys inside obvious `outputs = ...`
returned attrsets, bounded by surrounding brace depth. The scanner detects
recognized sections after line start, `{`, `in {`, or `;`, and reuses the
existing safe output-section and diagnostic helpers. The NIX-EXTRACT5 gap
fixtures now emit count-friendly
`nix.output_section` observations and counted-only unsupported diagnostics, but
still do not fabricate concrete app/package/dev-shell/check output identities.
The change keeps the extractor non-evaluating and avoids canonicalization,
storage, CLI, MCP, schema, lifecycle, Nix CLI, fetch, lock, store, discovery,
refresh, or private-data changes. NIX-LIVE2 should run a graph-scoped flakes
refresh/smoke to validate the improved scanner against the stored private graph.

NIX-LIVE2 refresh/smoke note: NIX-LIVE2 ran an explicitly authorized
graph-scoped refresh for only the private `flakes` graph after NIX-EXTRACT6.
The refresh succeeded and public payloads remained private-root redacted,
path-free, and count-only. Existing Nix evidence increased again
(`nix_observations` +83, `nix_files` +32, raw imports +25, raw path refs +54),
and flake input counts increased from 4 to 8. Output sections, dynamic output
shapes, unsupported flake shapes, and concrete output observations remained
zero after refresh. This classifies the result as a remaining
extractor/source-shape gap rather than a refresh or summary-readback failure.
NIX-EXTRACT7 should add a more targeted public-safe fixture and scanner
follow-up based on sanitized real-shape findings.

NIX-EXTRACT7 implementation note: NIX-EXTRACT7 added a targeted public-safe
`let_bound_output_attrsets` fixture for the remaining real-flakes source-shape
gap and refined the Nix output-section scanner to recognize interpolated
attr-path suffixes such as `packages.${...}` in output-shaped bodies. The
extractor now emits counted-only `nix.output_section`,
`nix.dynamic_output_shape`, and `nix.unsupported_flake_shape` evidence for the
safe visible categories, while continuing to avoid concrete app/package/dev
shell/check fabrication. Existing direct dotted outputs and the NIX-EXTRACT5/6
fixtures remain stable. The slice made no canonicalization, summary, storage,
CLI, MCP, SQL/schema, lifecycle, discovery, refresh, Nix execution, fetch,
lock, store, or private-data changes. NIX-LIVE3 should run the next authorized
graph-scoped flakes refresh/smoke to validate the targeted scanner on the real
private graph.

NIX-LIVE3 refresh/smoke note: NIX-LIVE3 ran an explicitly authorized
graph-scoped refresh for only the private `flakes` graph after NIX-EXTRACT7.
The refresh succeeded, public payloads stayed private-root redacted and
path-free, and the targeted scanner produced real count-only output-shape
evidence: output sections increased from 0 to 3, dynamic output-shape
diagnostics increased from 0 to 3, and unsupported flake-shape diagnostics
increased from 0 to 3. The visible categories were bounded to safe summary
labels such as `packages`, `checks`, and `legacyPackages`, with dynamic
`string_interpolation` and unsupported counted-only diagnostics. Concrete
app/package/dev-shell/check observations and canonical output counts remained
zero by design because the scanner must not fabricate exact identities from
dynamic/helper-returned shapes. NIX-CANON0 should design whether and how this
counted-only output-section evidence should participate in canonical graph
modeling.

NIX-CANON0 design note: NIX-CANON0 inspected the current Nix canonicalization
boundary after NIX-LIVE3 validated real `nix.output_section`,
`nix.dynamic_output_shape`, and `nix.unsupported_flake_shape` evidence. The
design keeps `nix.flake_input`, dynamic shape diagnostics, and unsupported
shape diagnostics raw-only/summary-only for now because input aliases, URLs,
path inputs, and diagnostic patterns are not stable public graph identities.
It recommends treating `nix.output_section` as the only near-term
canonicalization candidate, and only as weak section-category `nix.output`
nodes with `defines` edges from the source flake file. These nodes must not
imply concrete app/package/dev-shell/check identities and must not use private
paths, URLs, input aliases, raw expressions, module names, overlay names, or
output names as key material. NIX-CANON1 should add synthetic
canonicalization characterization tests for section evidence before
implementation.

NIX-CANON1 characterization note: NIX-CANON1 added the synthetic
`nix_output_sections_basic` canonicalization fixture and tests for the
NIX-CANON0 weak section-category boundary. The phase keeps production
canonicalization unchanged: passing tests assert that section evidence does
not fabricate concrete app/package/dev-shell/check nodes, flake inputs and
diagnostics remain raw-only, and the fixture/payload is public-safe. Two
future-contract tests are intentionally skipped until NIX-CANON2 implements
weak `nix.output` section nodes and `defines` edges. NIX-CANON2 should
implement that narrow behavior and unskip those contract tests.

NIX-CANON2 implementation note: NIX-CANON2 implemented the weak
`nix.output` section-category canonicalization contract for
`nix.output_section` observations. Section evidence now creates safe
section-category `nix.output` nodes and `defines` edges from the source flake
file, while flake inputs, path refs, dynamic diagnostics, unsupported
diagnostics, modules, overlays, and exact concrete app/package/dev-shell/check
identities remain raw-only unless they have their existing concrete evidence.
The phase unskipped the NIX-CANON1 future-contract tests, updated the
canonicalization compatibility ledger, and left extraction, storage, summary,
CLI, MCP, SQL/schema, lifecycle, package, and dependency behavior unchanged.
NIX-LIVE4 should run the next authorized graph-scoped refresh/smoke against
`flakes` to validate the section-category nodes and edges on the private graph
with sanitized counts only.

NIX-LIVE4 refresh/smoke note: NIX-LIVE4 ran the authorized graph-scoped
refresh for only the private `flakes` graph after NIX-CANON2. The refresh
succeeded and validated the weak canonical section contract on real stored
evidence: canonical `nix.output` nodes increased from 0 to 3 and incoming
`defines` edges to those nodes increased from 0 to 3, while concrete
`nix.app`, `nix.package`, `nix.devShell`, and `nix.check` nodes remained zero
by design. The Nix summary continued to report concrete output `defines`
separately from weak section-category edges, and bounded canonical readback
still contains repo-relative canonical source file identity that was not
copied into the public report. NIX-SUMMARY11 should clarify the summary and
private canonical-readback semantics for weak section-category evidence before
the canonicalization increment is closed.

NIX-SUMMARY11 implementation note: NIX-SUMMARY11 clarified weak Nix
section-category summary/readback semantics after NIX-LIVE4. The Nix summary
now exposes `canonical.output_sections` and `edges.output_section_defines` for
weak `nix.output_section` canonical facts, while keeping
`edges.output_defines` concrete-only for app/package/dev-shell/check output
identities. A limitation marker, `weak_output_sections_are_not_concrete_outputs`,
makes the boundary explicit in JSON, table, CLI, and MCP summary payloads.
Detailed canonical readback remains an expert/internal surface that may expose
repo-relative canonical source file identity; private graph reports should
prefer the count-only summary, and any future detailed-readback redaction
should happen at graph-id serialization rather than by mutating stored
canonical keys. NIX-LIVE5 can re-smoke these summary fields if needed, or
NIX-CANON3 can close out the section-category canonicalization increment.

NIX-CANON3 closeout note: NIX-CANON3 closed the Nix section-category
canonicalization increment as docs-only after NIX-CANON0 through
NIX-SUMMARY11. The accepted boundary is weak `nix.output` section-category
nodes plus source-file `defines` edges for `nix.output_section`, with no exact
app/package/dev-shell/check identity inference. Flake inputs, path refs,
dynamic diagnostics, unsupported diagnostics, modules, and overlays remain
raw-only or deferred. The count-only Nix summary is the safe default private
reporting surface, while detailed canonical readback remains expert/internal
and may expose repo-relative canonical source file identity. NIX-LIVE5 should
run the final read-only source-checkout smoke against `flakes`; after that the
roadmap can return to the storage/refactor line: split `storage/sql.py`, split
`storage/summary_rows.py`, run STORAGE-PKG, smoke the local `repo-map` graph,
harden automated smokes, and finish Phase F.

NIX-LIVE5 closeout smoke note: NIX-LIVE5 performed the final read-only
source-checkout smoke against the already-refreshed private `flakes` graph.
The NIX-SUMMARY11 fields are present on real stored data:
`canonical.output_sections` is 3, `edges.output_section_defines` is 3,
`edges.output_defines` remains 0 and concrete-only, and
`weak_output_sections_are_not_concrete_outputs` is true. Concrete
app/package/dev-shell/check canonical counts remain 0 by design, while the
count-only summary stays private-root redacted, path-free, read-only, and free
of raw private payload capture. This closes the Nix section-category
canonicalization and summary increment as a good stopping point. The roadmap
returns to the storage/refactor line: split `storage/sql.py`, split
`storage/summary_rows.py`, run STORAGE-PKG, smoke the local `repo-map`
self-knowledge graph, harden automated smokes, and finish Phase F.

STORAGE-SQL0 design note: STORAGE-SQL0 inventoried the 3,193-line
`src/main/python/repomap_kg/storage/sql.py` module and designed a low-risk
split strategy. The recommended path keeps `storage/sql.py` as the stable
compatibility facade, preserving `repomap_kg.storage.sql`, the
`repomap_kg.storage_sql` alias, `storage.main` star imports, storage facade
exports, and row-facing symbols currently asserted by compatibility tests.
Implementation should move code into sibling modules rather than converting
`storage/sql.py` into a package: start with pure helpers in `sql_core.py`, then
split load/upsert SQL, legacy readback SQL, canonical readback SQL,
source/feed SQL, and domain summary SQL in separate phases. STORAGE-SQL1
should perform the first helper extraction without changing SQL strings,
imports, schemas, lifecycle behavior, or runtime output.

STORAGE-SQL1 implementation note: STORAGE-SQL1 added the sibling
`src/main/python/repomap_kg/storage/sql_core.py` module and moved only the pure
SQL helper/core utilities into it. `storage/sql.py` remains the compatibility
facade and imports the helpers back by name, preserving `repomap_kg.storage.sql`,
the `repomap_kg.storage_sql` alias, `storage.main` star imports, storage facade
exports, and row-facing compatibility symbols. The phase did not change SQL
query strings, helper outputs, schemas, migrations, lifecycle behavior,
discovery, graph refresh, real database state, package metadata, lockfiles, or
dependencies. STORAGE-SQL2 should move load/ingest orchestration and row upsert
SQL builders into `storage/sql_load.py` behind the same facade.

STORAGE-SQL2 implementation note: STORAGE-SQL2 added the sibling
`src/main/python/repomap_kg/storage/sql_load.py` module and moved load/ingest
orchestration plus row upsert SQL builders into it. `storage/sql.py` remains the
compatibility facade and imports the moved builders back by name, preserving
`repomap_kg.storage.sql`, the `repomap_kg.storage_sql` alias, `storage.main`
star imports, package-root exports for existing `storage.sql.__all__` names, and
row-facing compatibility symbols. The phase did not change SQL text,
insert/upsert conflict behavior, ingest ordering, load summary behavior,
schemas, migrations, lifecycle behavior, discovery, graph refresh, real database
state, package metadata, lockfiles, or dependencies. STORAGE-SQL3 should move
legacy file/node/edge/neighborhood/host readback SQL into `storage/sql_readback.py`
behind the same facade.

STORAGE-SQL3 implementation note: STORAGE-SQL3 added the sibling
`src/main/python/repomap_kg/storage/sql_readback.py` module and moved legacy
file, node, edge, neighborhood, file-neighborhood, and host-mutator readback SQL
builders into it. `storage/sql.py` remains the compatibility facade and imports
the moved builders back by name, preserving `repomap_kg.storage.sql`, the
`repomap_kg.storage_sql` alias, `storage.main` star imports, package-root exports
for existing `storage.sql.__all__` names, and row-facing compatibility symbols.
The phase did not move canonical readback SQL, source/feed SQL, or domain summary
SQL, and did not change SQL text, limit handling, root/path filtering,
neighborhood center joins, host mutator semantics, schemas, migrations,
lifecycle behavior, discovery, graph refresh, real database state, package
metadata, lockfiles, or dependencies. STORAGE-SQL4 should move canonical
node/edge/neighborhood/explanation readback SQL into `storage/sql_canonical.py`
behind the same facade.

STORAGE-SQL4 implementation note: STORAGE-SQL4 added the sibling
`src/main/python/repomap_kg/storage/sql_canonical.py` module and moved canonical
node, edge, neighborhood, edge-explanation, and canonical storage-summary
readback SQL builders into it. `storage/sql.py` remains the compatibility facade
and imports the moved builders back by name, preserving `repomap_kg.storage.sql`,
the `repomap_kg.storage_sql` alias, `storage.main` star imports, package-root
exports for existing `storage.sql.__all__` names, and row-facing compatibility
symbols. The phase did not move source/feed SQL or general/domain summary SQL,
and did not change SQL text, graph key version checks, canonical key/path-prefix
filtering, canonical edge explanation semantics, canonical neighborhood
semantics, private/readback semantics, schemas, migrations, lifecycle behavior,
discovery, graph refresh, real database state, package metadata, lockfiles, or
dependencies. STORAGE-SQL5 should move source/feed readback SQL and
`source_observations_cte` into `storage/sql_sources.py` behind the same facade.

STORAGE-SQL5 implementation note: STORAGE-SQL5 added the sibling
`src/main/python/repomap_kg/storage/sql_sources.py` module and moved source/feed
readback SQL builders plus `source_observations_cte` into it. `storage/sql.py`
remains the compatibility facade and imports the moved builders back by name,
preserving `repomap_kg.storage.sql`, the `repomap_kg.storage_sql` alias,
`storage.main` star imports, package-root exports for existing
`storage.sql.__all__` names, and row-facing compatibility symbols. The phase did
not move general/domain summary SQL, and did not change SQL text, source/feed
query output contracts, source/feed filtering semantics, source observation CTE
semantics, feed item explanation semantics, private/readback semantics, schemas,
migrations, lifecycle behavior, discovery, graph refresh, real database state,
package metadata, lockfiles, or dependencies. STORAGE-SQL6 should move general
and domain summary SQL builders into `storage/sql_summaries.py` behind the same
facade; if that proves too large, split the summary move into a design or staged
subseries instead of forcing a risky all-at-once phase.

STORAGE-SQL6 design note: STORAGE-SQL6 inspected the remaining
`storage/sql.py` summary-only facade after STORAGE-SQL5. The file has 1485 lines
and contains only `__all__`, facade imports, and eleven general/domain summary
builders. The selected strategy is a staged move into one eventual sibling
`src/main/python/repomap_kg/storage/sql_summaries.py`, rather than one large
all-at-once summary move or several permanent summary submodules. STORAGE-SQL7
should create `sql_summaries.py` and move the lowest-risk
`build_storage_summary_query_sql`, `build_ruby_summary_query_sql`, and
`build_js_summary_query_sql` first. Later phases should move JS framework and
Python summaries, then OpenAPI/Terraform/Email summaries, then Bulk/API
manifest summaries, and finally move the large Nix summary builder by itself to
preserve its recent count-only, path-free, weak-section semantics.

STORAGE-SQL7 implementation note: STORAGE-SQL7 added the sibling
`src/main/python/repomap_kg/storage/sql_summaries.py` module and moved only the
storage, Ruby, and JavaScript summary SQL builders into it. `storage/sql.py`
remains the compatibility facade and imports those builders back by name,
preserving `repomap_kg.storage.sql`, the `repomap_kg.storage_sql` alias,
`storage.main` star imports, package-root exports for existing
`storage.sql.__all__` names, and row-facing compatibility symbols. The phase did
not move JS framework, OpenAPI, Terraform, Python, Nix, Email, Bulk, or API
summary builders, and did not change SQL text, summary payload contracts,
summary privacy/path-free semantics, schemas, migrations, lifecycle behavior,
discovery, graph refresh, real database state, package metadata, lockfiles, or
dependencies. STORAGE-SQL8 should move `build_js_framework_summary_query_sql`
and `build_python_summary_query_sql` into `storage/sql_summaries.py` behind the
same facade.

STORAGE-SQL8 implementation note: STORAGE-SQL8 continued the staged summary
split by moving only `build_js_framework_summary_query_sql` and
`build_python_summary_query_sql` into `storage/sql_summaries.py`. `storage/sql.py`
remains the compatibility facade and imports the moved builders back by name,
preserving `repomap_kg.storage.sql`, the `repomap_kg.storage_sql` alias,
`storage.main` star imports, package-root exports for existing
`storage.sql.__all__` names, and row-facing compatibility symbols. The phase did
not move OpenAPI, Terraform, Nix, Email, Bulk, or API summary builders, and did
not change SQL text, summary payload contracts, summary privacy/path-free
semantics, MCP/CLI redaction behavior, schemas, migrations, lifecycle behavior,
discovery, graph refresh, real database state, package metadata, lockfiles, or
dependencies. STORAGE-SQL9 should move `build_openapi_summary_query_sql`,
`build_terraform_summary_query_sql`, and `build_email_summary_query_sql` into
`storage/sql_summaries.py` behind the same facade.

STORAGE-SQL9 implementation note: STORAGE-SQL9 continued the staged summary
split by moving only `build_openapi_summary_query_sql`,
`build_terraform_summary_query_sql`, and `build_email_summary_query_sql` into
`storage/sql_summaries.py`. `storage/sql.py` remains the compatibility facade
and imports the moved builders back by name, preserving
`repomap_kg.storage.sql`, the `repomap_kg.storage_sql` alias, `storage.main`
star imports, package-root exports for existing `storage.sql.__all__` names,
and row-facing compatibility symbols. The phase did not move Nix, Bulk, or API
summary builders, and did not change SQL text, summary payload contracts,
summary privacy/path-free semantics, MCP/CLI redaction behavior, OpenAPI,
Terraform, or Email count semantics, schemas, migrations, lifecycle behavior,
discovery, graph refresh, real database state, package metadata, lockfiles, or
dependencies. STORAGE-SQL10 should move `build_bulk_summary_query_sql` and
`build_api_summary_query_sql` into `storage/sql_summaries.py` behind the same
facade.

STORAGE-SQL10 implementation note: STORAGE-SQL10 continued the staged summary
split by moving only `build_bulk_summary_query_sql` and
`build_api_summary_query_sql` into `storage/sql_summaries.py`. `storage/sql.py`
remains the compatibility facade and imports the moved builders back by name,
preserving `repomap_kg.storage.sql`, the `repomap_kg.storage_sql` alias,
`storage.main` star imports, package-root exports for existing
`storage.sql.__all__` names, and row-facing compatibility symbols. The phase did
not move `build_nix_summary_query_sql`, and did not change SQL text, summary
payload contracts, manifest/provenance semantics, summary privacy/path-free
semantics, MCP/CLI redaction behavior, Bulk/API count semantics, schemas,
migrations, lifecycle behavior, discovery, graph refresh, real database state,
package metadata, lockfiles, or dependencies. STORAGE-SQL11 should move
`build_nix_summary_query_sql` into `storage/sql_summaries.py` by itself behind
the same facade, preserving its recent count-only, path-free, weak-section
semantics.

STORAGE-SQL11 implementation note: STORAGE-SQL11 completed the staged summary
SQL builder extraction by moving only `build_nix_summary_query_sql` into
`storage/sql_summaries.py`. `storage/sql.py` now contains the compatibility
facade imports and `__all__`, with row-facing compatibility imports still
available through the facade. The phase preserved `repomap_kg.storage.sql`, the
`repomap_kg.storage_sql` alias, `storage.main` star imports, package-root
exports for existing `storage.sql.__all__` names, and row-facing compatibility
symbols. It did not change SQL text, Nix summary payload contracts,
NIX-SUMMARY10/NIX-SUMMARY11 semantics, count-only/path-free behavior, weak
section-category semantics, safety markers, limitation markers, MCP/CLI
redaction behavior, schemas, migrations, lifecycle behavior, discovery, graph
refresh, real database state, package metadata, lockfiles, or dependencies.
STORAGE-SQL12 should close out the `storage/sql.py` split series by documenting
the final facade shape, remaining compatibility exports, module layout, and the
recommended next step: begin the `storage/summary_rows.py` split.

STORAGE-SQL12 closeout note: STORAGE-SQL12 documented the completed
`storage/sql.py` split series without changing source code or tests. The final
shape keeps `storage/sql.py` as the compatibility facade, with implementation
bodies split across `sql_core.py`, `sql_load.py`, `sql_readback.py`,
`sql_canonical.py`, `sql_sources.py`, and `sql_summaries.py`. The closeout
preserves the compatibility policy for `repomap_kg.storage.sql`,
`repomap_kg.storage_sql`, `storage.main` star imports, package-root exports,
and row-facing compatibility symbols, and records that compatibility alias
cleanup remains deferred to a separately scoped phase if it is ever desired.
STORAGE-SUMMARY-ROWS0 should design the split of
`src/main/python/repomap_kg/storage/summary_rows.py`.

STORAGE-SUMMARY-ROWS0 design note: STORAGE-SUMMARY-ROWS0 inventoried
`storage/summary_rows.py` as a 2,059-line summary row parser/record surface
with 32 compatibility exports spanning generic storage records, language and
domain summaries, Nix parsing, Bulk/API manifest provenance helpers, JSON
serialization dependencies, and table-rendering dependencies. The recommended
split keeps `storage/summary_rows.py` as the compatibility facade and moves
implementation bodies into focused sibling modules over staged phases:
`summary_rows_core.py`, `summary_rows_storage.py`,
`summary_rows_languages.py`, `summary_rows_domains.py`,
`summary_rows_manifest.py`, and `summary_rows_nix.py`. The design explicitly
defers code movement, table/jsonable splits, source/feed row movement,
compatibility alias cleanup, discovery, graph refresh, and real database
mutation. STORAGE-SUMMARY-ROWS1 should perform the first low-risk extraction
by moving shared payload validation and count-map helper utilities into a
helper module while preserving the facade.

STORAGE-SUMMARY-ROWS1 implementation note: STORAGE-SUMMARY-ROWS1 started the
summary row split with the lowest-risk helper extraction, moving only
`_count_from_mapping` and `_required_count_map_from_mapping` into the new sibling module
`storage/summary_rows_core.py`. `storage/summary_rows.py` remains the
compatibility facade and imports those private helpers back without adding them
to `summary_rows.__all__` or widening `storage.rows`, `storage.main`, or
package-root exports. The phase intentionally left public summary dataclasses,
public parser functions, manifest/provenance helpers, and Nix-specific helpers
in `summary_rows.py`, and it did not change payload contracts, JSON/table
rendering, CLI/MCP behavior, SQL, schemas, migrations, lifecycle behavior,
discovery, graph refresh, real database state, package metadata, lockfiles, or
dependencies. STORAGE-SUMMARY-ROWS2 should move the generic storage and load
summary records into `summary_rows_storage.py` behind the same facade.

STORAGE-SUMMARY-ROWS2 implementation note: STORAGE-SUMMARY-ROWS2 continued the
staged summary row split by moving only the generic storage/load summary dataclasses
`LoadSummary`, `CanonicalLoadSummary`, `StorageSummaryRecord`, and
`CanonicalStorageSummaryRecord`, plus their four parser functions, into the
new sibling module `storage/summary_rows_storage.py`. `storage/summary_rows.py`
remains the compatibility facade and imports the moved public names back with
the same `summary_rows.__all__`, preserving `storage.rows`, `storage.main`,
`repomap_kg.storage_rows`, and package-root exports. The phase did not move
language, domain, Nix, Email, Bulk, API, manifest, or provenance summaries, and
did not change dataclass fields, parser signatures, payload validation,
exception messages, `to_dict()` shapes, JSON/table rendering, CLI/MCP behavior,
SQL, schemas, migrations, lifecycle behavior, discovery, graph refresh, real
database state, package metadata, lockfiles, or dependencies.
STORAGE-SUMMARY-ROWS3 should move language summary records and parsers into
`summary_rows_languages.py` behind the same facade.

STORAGE-SUMMARY-ROWS3 implementation note: STORAGE-SUMMARY-ROWS3 continued the
staged summary row split by moving only the language summary dataclasses `RubySummaryRecord`,
`JSSummaryRecord`, `JSFrameworkSummaryRecord`, and `PythonSummaryRecord`, plus
their four parser functions, into the new sibling module
`storage/summary_rows_languages.py`. `storage/summary_rows.py` remains the
compatibility facade and imports the moved public names back with the same
`summary_rows.__all__`, preserving `storage.rows`, `storage.main`,
`repomap_kg.storage_rows`, and package-root exports. The phase did not move
OpenAPI, Terraform, Email, Bulk, API, or Nix summaries, and did not change
dataclass fields, parser signatures, payload validation, exception messages,
`to_dict()` shapes, JSON/table rendering, CLI/MCP behavior, SQL, schemas,
migrations, lifecycle behavior, discovery, graph refresh, real database state,
package metadata, lockfiles, or dependencies. STORAGE-SUMMARY-ROWS4 should move
OpenAPI, Terraform, and Email summary records and parsers into
`summary_rows_domains.py` behind the same facade.

STORAGE-SUMMARY-ROWS4 implementation note: STORAGE-SUMMARY-ROWS4 continued the
staged summary row split by moving only the OpenAPI, Terraform, and Email summary dataclasses
`OpenAPISummaryRecord`, `TerraformSummaryRecord`, and `EmailSummaryRecord`,
plus their three parser functions, into the new sibling module
`storage/summary_rows_domains.py`. `storage/summary_rows.py` remains the
compatibility facade and imports the moved public names back with the same
`summary_rows.__all__`, preserving `storage.rows`, `storage.main`,
`repomap_kg.storage_rows`, and package-root exports. The phase did not move
Bulk, API, manifest/provenance, or Nix summaries, and did not change dataclass
fields, parser signatures, payload validation, exception messages, `to_dict()`
shapes, JSON/table rendering, CLI/MCP behavior, SQL, schemas, migrations,
lifecycle behavior, discovery, graph refresh, real database state, package
metadata, lockfiles, or dependencies. STORAGE-SUMMARY-ROWS5 should move
Bulk/API manifest and provenance records/helpers into
`summary_rows_manifest.py` behind the same facade.

STORAGE-SUMMARY-ROWS5 implementation note: STORAGE-SUMMARY-ROWS5 continued the
staged summary row split by moving only `BulkSummaryRecord`, `APISummaryRecord`, the Bulk/API
manifest/provenance helper functions, and the Bulk/API parser functions into
the new sibling module `storage/summary_rows_manifest.py`.
`storage/summary_rows.py` remains the compatibility facade and imports the
moved public names back with the same `summary_rows.__all__`, preserving
`storage.rows`, `storage.main`, `repomap_kg.storage_rows`, and package-root
exports. The phase did not move Nix records, parsers, or Nix-specific helpers,
and did not change dataclass fields, helper or parser signatures,
manifest/provenance payload behavior, malformed manifest handling, redaction
counts, payload validation, exception messages, `to_dict()` shapes, JSON/table
rendering, CLI/MCP behavior, SQL, schemas, migrations, lifecycle behavior,
discovery, graph refresh, real database state, package metadata, lockfiles, or
dependencies. STORAGE-SUMMARY-ROWS6 should move the Nix summary records,
parser functions, and Nix-specific helpers into `summary_rows_nix.py` by itself
behind the same facade.

STORAGE-SUMMARY-ROWS6 implementation note: STORAGE-SUMMARY-ROWS6 completed the
staged summary row implementation split by moving only `NixSummaryRecord`, the Nix-specific
helper functions, and `nix_summary_from_storage_payload` into the new sibling
module `storage/summary_rows_nix.py`. `storage/summary_rows.py` is now the
compatibility facade for summary row records and imports all implementation
modules back with the same `summary_rows.__all__`, preserving `storage.rows`,
`storage.main`, `repomap_kg.storage_rows`, and package-root exports. The phase
preserved NIX-SUMMARY10/NIX-SUMMARY11 count-only and path-free behavior,
weak output-section semantics, safety markers, limitation markers, payload
validation, exception messages, `to_dict()` shapes, JSON/table rendering,
CLI/MCP behavior, SQL, schemas, migrations, lifecycle behavior, discovery,
graph refresh, real database state, package metadata, lockfiles, and
dependencies. STORAGE-SUMMARY-ROWS7 should close out the
`storage/summary_rows.py` split series by documenting the final facade shape,
implementation module layout, verification history, and deferred compatibility
cleanup.

STORAGE-SUMMARY-ROWS7 closeout note: STORAGE-SUMMARY-ROWS7 closes the staged
`storage/summary_rows.py` split after STORAGE-SUMMARY-ROWS0 through
STORAGE-SUMMARY-ROWS6. The final layout keeps `storage/summary_rows.py` as the
compatibility facade and
places implementation bodies in `summary_rows_core.py`,
`summary_rows_storage.py`, `summary_rows_languages.py`,
`summary_rows_domains.py`, `summary_rows_manifest.py`, and
`summary_rows_nix.py`. The closeout records the preserved facade/export policy,
behavior boundary, verification history, and explicit deferrals without source,
test, fixture, import, payload, JSON/table, SQL, schema, migration, lifecycle,
CLI/MCP, package metadata, lockfile, dependency, discovery, refresh, or real
database behavior changes. STORAGE-PKG0 should design the package-structure
cleanup series now that both `storage/sql.py` and `storage/summary_rows.py`
have been split into focused sibling modules.

STORAGE-PKG0 design note: STORAGE-PKG0 inventories the storage package after
the SQL and summary row split closeouts. It identifies `storage/__init__.py`,
`storage/main.py`, `storage/rows.py`, `storage/sql.py`,
`storage/summary_rows.py`, and the top-level `storage_*` modules as deliberate
compatibility surfaces to preserve for now, while documenting the focused
implementation modules underneath them. The recommended cleanup strategy is to
strengthen package/facade ownership tests and documentation before any internal
import rewiring, and to defer alias removal, broad facade removal, table/json
splits, summary query orchestration splits, and compatibility deprecations
until separately scoped phases find a direct maintainability or safety benefit.
STORAGE-PKG1 should start with low-risk package/facade test hardening or
facade ownership documentation rather than changing imports.

STORAGE-PKG1 implementation note: STORAGE-PKG1 hardens storage package/facade
ownership tests before any internal import rewiring. It adds representative
identity assertions for `repomap_kg.storage` as the package-root compatibility
layer over `storage.main`, `storage.main` as the broad legacy facade,
`storage.rows`, `storage.sql`, and `storage.summary_rows` as compatibility
facades over focused implementation modules, and the seven top-level
`storage_*` aliases as intentional module-identity aliases. The phase does not
change production imports, public exports, CLI/MCP import paths, payload
contracts, JSON/table behavior, SQL, schemas, migrations, lifecycle behavior,
graph registry behavior, package metadata, lockfiles, dependencies, discovery,
refresh, or real database state. STORAGE-PKG2 should perform the first narrow
internal import cleanup only if the facade boundary remains explicit,
preferably in `storage/jsonable_rows.py` or `storage/table_rows.py`.

STORAGE-PKG2 implementation note: STORAGE-PKG2 performs the first narrow
internal import cleanup by rewiring `storage/jsonable_rows.py` summary record
imports from the broad `storage.summary_rows` facade to focused summary row
implementation modules. It adds a package-structure import-topology test for
the JSONable module while preserving all JSON conversion helper names,
signatures, `__all__`, output shapes, package-root exports, `storage.main`,
`storage.rows`, `storage.sql`, `storage.summary_rows`, top-level aliases,
CLI/MCP import paths, payload contracts, table behavior, SQL, schemas,
migrations, lifecycle behavior, graph registry behavior, package metadata,
lockfiles, dependencies, discovery, refresh, and real database state.
STORAGE-PKG3 should evaluate the next narrow internal import cleanup,
preferably `storage/table_rows.py` or a very small, explicitly scoped part of
`storage/summaries.py`.

STORAGE-PKG3 implementation note: STORAGE-PKG3 performs the next narrow
internal import cleanup by rewiring `storage/table_rows.py` summary record
imports from the broad `storage.summary_rows` facade to focused summary row
implementation modules. It extends the package-structure import-topology tests
to cover table formatting while preserving all formatter names, signatures,
`__all__`, table headers, ordering, output strings, package-root exports,
`storage.main`, `storage.rows`, `storage.sql`, `storage.summary_rows`,
top-level aliases, CLI/MCP import paths, JSON behavior, payload contracts, SQL,
schemas, migrations, lifecycle behavior, graph registry behavior, package
metadata, lockfiles, dependencies, discovery, refresh, and real database state.
STORAGE-PKG4 should evaluate query orchestration modules, especially
`storage/legacy.py`, `storage/canonical.py`, and `storage/summaries.py`, and
decide whether any focused import rewiring is worth doing before live smoke
hardening.

STORAGE-PKG4 implementation note: STORAGE-PKG4 inspected the query
orchestration modules `storage/legacy.py`, `storage/canonical.py`, and
`storage/summaries.py` and chose no production import rewiring. These modules
currently use the broad `storage.rows` and `storage.sql` facades while invoking
`run_psql`, parsing psql JSON, returning row/parser records, and in
`storage/summaries.py` assembling Bulk/API manifest and redaction payloads.
Because that surface is closer to query execution, parser behavior, summary
payload contracts, CLI/MCP behavior, and live storage smoke coverage than the
projection-only modules cleaned in STORAGE-PKG2 and STORAGE-PKG3, the safer
pre-smoke boundary is to keep the broad facades explicit. The phase is
docs-only and preserves public exports, package-root exports, `storage.main`,
`storage.rows`, `storage.sql`, `storage.summary_rows`, top-level aliases,
query/psql behavior, SQL text, parser behavior, table/JSON output, payload
contracts, schemas, migrations, lifecycle behavior, graph registry behavior,
package metadata, lockfiles, dependencies, discovery, refresh, and real
database state. STORAGE-PKG5 should close the package-structure cleanup series
and recommend moving to live smoke hardening.

STORAGE-PKG5 closeout note: STORAGE-PKG5 closes the storage package-structure
cleanup series after STORAGE-PKG0 through STORAGE-PKG4. The final policy keeps
`repomap_kg.storage`, `storage.main`, `storage.rows`, `storage.sql`,
`storage.summary_rows`, and the top-level `storage_*` alias modules as
intentional compatibility surfaces; preserves package-root exports and CLI/MCP
import paths; records that only projection-module summary record imports were
rewired in `storage/jsonable_rows.py` and `storage/table_rows.py`; and defers
query orchestration rewiring in `storage/legacy.py`, `storage/canonical.py`,
and `storage/summaries.py` until after live smoke hardening. The closeout is
docs-only and does not change production code, tests, imports, exports,
query/psql/SQL/parser/payload behavior, JSON/table output, schemas,
migrations, lifecycle behavior, graph registry behavior, package metadata,
lockfiles, dependencies, discovery, refresh, or real database state. LIVE-SMOKE0
should design the live deployment smoke test against the local repo-map
self-knowledge graph with strict privacy boundaries and no committed generated
smoke output.

LIVE-SMOKE0 design note: LIVE-SMOKE0 designs, but does not execute, the live
deployment smoke test for the local repo-map self-knowledge graph after the
STORAGE-SQL, STORAGE-ROWS, and STORAGE-PKG refactor series. The plan targets
the configured `repo-map` graph, separates read-only import/facade, ops, CLI
storage, MCP, privacy, error, and latency checks from the optional later
graph-scoped refresh path, and requires generated smoke output to remain
uncommitted. The design permits only sanitized high-level status notes, counts,
and failure categories in committed docs; forbids private roots, local
usernames, private paths, raw snippets, dumps, secrets, tokens, state files,
and MCP payloads containing private graph content; and makes LIVE-SMOKE1 the
execution phase for the designed smoke with strict privacy boundaries. Automated
smoke hardening should follow LIVE-SMOKE1 findings rather than being bundled
into the design phase.

LIVE-SMOKE1 execution note: LIVE-SMOKE1 executed the designed live smoke
against the configured `repo-map` self-knowledge graph and recorded only
sanitized high-level results. Import/facade smoke, read-only ops graph status,
refresh preflight, MCP graph-id status/project/domain summaries, bounded MCP
searches, and MCP neighborhood readback passed without graph mutation. The
phase deliberately skipped `refresh-graph`, broad refreshes, baselines,
destructive lifecycle actions, direct database/container commands, discovery,
and generated-output commits. The result is partial because direct storage CLI
summary/readback commands failed through a host-resolution storage-connection
boundary, and MCP graph metadata included root-path fields in live payloads;
those values were omitted from committed docs and classified by field family
only. SMOKE-HARDEN0 should design automated smoke hardening with public-safe
fixtures, synthetic private-looking strings, and mocked storage responses, not
private live graph data.

SMOKE-HARDEN0 design note: SMOKE-HARDEN0 designs automated smoke hardening from
the LIVE-SMOKE1 `live-smoke-partial` findings without using private live graph
data. The plan prioritizes mocked storage CLI connection-boundary tests with
synthetic private-looking connection values, then MCP graph metadata
privacy/redaction tests, followed by targeted Bulk/API manifest, Nix
path-free/weak-section, and source/feed empty-result hardening only where
existing tests leave smoke-shaped gaps. The phase is docs-only and does not
change source code, tests, fixtures, imports, public exports, SQL, schemas,
CLI/MCP behavior, package metadata, lockfiles, dependencies, discovery,
refresh, or real database state. SMOKE-HARDEN1 should start with the storage
CLI connection-boundary tests.

SMOKE-HARDEN1 implementation note: SMOKE-HARDEN1 adds a unit-level storage CLI
connection-boundary smoke test for representative direct storage summary,
readback, canonical readback, language/domain summary, manifest summary, and
Nix summary commands. The test uses mocked query failures and committed-safe
synthetic private-looking values, asserts nonzero exit, empty stdout in JSON
mode, bounded useful stderr, and no leakage of synthetic host/database/user/root
URL/token/path values. A localized CLI error sanitizer preserves useful
`ERROR:` classifications while redacting connection strings, private-looking
absolute paths, synthetic private values, and secret-like tokens. The phase
does not use real databases, live graph data, discovery, refresh, direct
database/container commands, generated smoke output, or SQL/parser/payload
changes. SMOKE-HARDEN2 should harden MCP graph metadata privacy with synthetic
graph config and mocked query responses.

SMOKE-HARDEN2 implementation note: SMOKE-HARDEN2 adds MCP graph metadata
privacy tests using synthetic ops graph configuration and mocked refresh,
project summary, and domain summary responses. The tests cover graph listing,
graph status, refresh status, project summary, and JS framework domain summary
envelopes, asserting private roots render as `[private-root]`, private graph
database metadata renders as `[private-database]`, and synthetic
host/database/user/root/path/connection-string/token values do not appear in
serialized MCP payloads. The localized MCP metadata change preserves public
graph output while redacting private graph database values in graph and refresh
status payloads. The phase does not use live graph data, discovery, refresh,
direct database/container commands, generated smoke output, SQL/parser changes,
or CLI behavior changes. SMOKE-HARDEN3 should inspect and harden Bulk/API
manifest and redaction smoke coverage if gaps remain.

SMOKE-HARDEN3 implementation note: SMOKE-HARDEN3 inspected Bulk/API manifest
and redaction coverage after the direct CLI path was blocked during
LIVE-SMOKE1 by the storage connection boundary. Existing tests already covered
manifest aggregation counts, malformed manifests, escaped manifest-root
rejection, query merge behavior, CLI JSON/table output for mocked records, and
table formatting. The phase added one fixture-backed CLI JSON smoke guard using
temporary synthetic Bulk/API manifests and mocked CLI query responses to assert
high-level counts and diagnostics survive while synthetic private roots,
usernames, artifact paths, host/database values, connection strings,
secret-like tokens, and raw response bodies do not appear in serialized Bulk/API
summary output. No production code changed, no live graph data was used, and no
MCP Bulk/API summary surface was added because none currently exists.
SMOKE-HARDEN4 should inspect Nix summary path-free and weak-output-section
coverage before deciding whether another smoke selector is needed.

SMOKE-HARDEN4 implementation note: SMOKE-HARDEN4 inspected the Nix summary
coverage added across the NIX-SUMMARY, STORAGE-SQL, STORAGE-ROWS, live-smoke,
and smoke-hardening work. Existing storage query, SQL builder, summary row,
JSONable, table, CLI, MCP, package/facade, and integration tests already pin
the count-only/path-free contract, root placeholder behavior, absence of raw
path/URL/flake-input/raw-expression markers, safety and limitation markers,
`canonical.output_sections`, `edges.output_section_defines`, concrete-only
`edges.output_defines`, and
`limitations.weak_output_sections_are_not_concrete_outputs`. Because the smoke
shape is already well covered, SMOKE-HARDEN4 was docs-only and added no source
or test changes. SMOKE-HARDEN5 should evaluate source/feed empty-result and
missing-source smoke hardening next.

SMOKE-HARDEN5 implementation note: SMOKE-HARDEN5 inspected source/feed
readback coverage after LIVE-SMOKE1 could not exercise source/feed detail probes
because the target graph returned no ingested sources. Existing tests already
covered populated source/feed SQL, parser, storage query, MCP, row facade, and
integration paths, including secret-like feed content omission. The phase added
one mocked MCP unit smoke guard for empty ingested-source lists, missing-source
zero-count summaries, empty run/item/reference lists, bounded feed-item
explanations, and no leakage of synthetic private-looking roots, usernames,
host/database values, connection strings, tokens, or raw source snippets. No
production code changed, no live graph data was used, and no discovery, refresh,
or real database mutation occurred. SMOKE-HARDEN6 should close out the automated
smoke hardening series and update the live-smoke playbook expectations.

SMOKE-HARDEN6 closeout note: SMOKE-HARDEN6 closes the automated smoke hardening
series after the LIVE-SMOKE1 `live-smoke-partial` findings. The closeout
summarizes the CLI connection-boundary tests and sanitizer, MCP graph metadata
privacy tests and private database redaction, Bulk/API synthetic manifest JSON
smoke, Nix coverage decision, and source/feed empty-result and missing-source
MCP smoke. It preserves the future live-smoke privacy/artifact policy: no
generated smoke output, private roots, local usernames, private paths, raw
snippets, dumps, secrets, tokens, state files, or raw private MCP/CLI payloads
in commits. Remaining checks are manual/live-only: actual host-resolution
behavior, private source/feed data availability, latency categories, optional
graph-scoped refresh validation, and future direct storage CLI live rechecks.
PHASE-F-CLOSE0 should design the final Phase F closeout criteria and decide
whether another bounded live smoke rerun is needed.

PHASE-F-CLOSE0 design note: PHASE-F-CLOSE0 reviews the roadmap state after the
STORAGE-SQL, STORAGE-ROWS, STORAGE-PKG, LIVE-SMOKE, and SMOKE-HARDEN series.
It classifies the remaining LIVE-SMOKE1 items as follow-up/manual runtime work
rather than Phase F blockers: direct storage CLI host-resolution behavior,
private live source/feed availability, stale-graph timestamp state, optional
graph-scoped refresh validation, and future direct CLI live rechecks. Because
the stable live-smoke findings now have synthetic automated hardening or
documented coverage, PHASE-F-CLOSE0 recommends PHASE-F-CLOSE1 close Phase F as
a docs-only final closeout without another required live smoke rerun. Any later
rerun should be explicitly bounded, read-only by default, and should not commit
generated smoke output or private live graph data.

PHASE-F-CLOSE1 final closeout note: PHASE-F-CLOSE1 closes Phase F. The final
closeout records that STORAGE-SQL0 through STORAGE-SQL12,
STORAGE-SUMMARY-ROWS0 through STORAGE-SUMMARY-ROWS7, STORAGE-PKG0 through
STORAGE-PKG5, LIVE-SMOKE0 and LIVE-SMOKE1, SMOKE-HARDEN0 through
SMOKE-HARDEN6, and PHASE-F-CLOSE0 are complete. No further live smoke rerun is
required for Phase F closeout. The remaining items are deferred as separately
scoped follow-up/manual/runtime work:
direct storage CLI host-resolution behavior, optional bounded live reruns,
optional graph-scoped refresh validation, query orchestration import rewiring,
alias cleanup, facade narrowing, and compatibility deprecations. Future live
smokes must remain explicitly scoped, privacy-preserving, read-only by default,
and free of committed generated smoke output or private live graph payloads.

DEPS-PSYCOPG0 design note: DEPS-PSYCOPG0 refreshes the dependency ADR position
after Phase F closeout and accepts Psycopg 3 as the first runtime dependency
candidate, without adding it. ADR 0037 narrows the fresh dependency
recommendation to PostgreSQL transport and readback pressure, keeps ADR 0035's
problem-driven stdlib/local-code default for every other category, records the
LGPL-3.0-only license and notice review boundary, and recommends a staged
PSYCOPG1 through PSYCOPG4 pilot. The first pilot should design or characterize
a readback adapter behind the existing `psql` fallback; benchmark and parity
evidence must precede replacement, and ingest/COPY design should wait until
readback is proven. DEPS-PSYCOPG0 leaves Tree-sitter, PyYAML, JSON/XML/graph/
dataframe/ORM/validation dependencies, package metadata, lockfiles, source
code, tests, discovery, graph refresh, live smoke, and real database mutation
unchanged. The legacy-default `storage files`, `storage entrypoints`, and
`storage file-nodes` commands remain a separate LEGACY-CMDS0 or READBACK-CANON0
design topic.

PSYCOPG1 design note: PSYCOPG1 designs the readback adapter pilot without
adding Psycopg, dependencies, package metadata, lockfiles, source code, tests,
SQL, parser, CLI/MCP payload, discovery, refresh, live-smoke, or real database
behavior. The future adapter should live as a narrow internal sibling to the
current `storage/psql.py` compatibility seam, execute one read-only SQL string
that returns one JSON value, preserve `StorageSchemaError` behavior, and keep
psql as the default fallback. The first PSYCOPG2 target should be
`query_storage_summary`, because it is compact, representative, reachable from
CLI `storage summary --legacy`, used by MCP project summary, and avoids
source/feed, ingest, ops mutation, and legacy-default command migration
complexity. PSYCOPG2 should add the psql-backed seam plus characterization
tests before any Psycopg dependency; PSYCOPG3 should benchmark psql versus
Psycopg across summary, canonical node/edge/neighborhood, domain, Nix, and
Bulk/API readback categories.

PSYCOPG2 implementation note: PSYCOPG2 adds the first internal psql-backed
readback adapter seam in `storage/readback_driver.py` and wires only
`query_storage_summary` through it. The adapter accepts one SQL string, existing
psql args, a psql command, a privacy-safe label, and an expected JSON object or
array shape; it delegates to existing `run_psql` and `parse_psql_json`, returns
decoded JSON only, and raises `StorageSchemaError` for adapter-visible failures.
Focused tests cover object and array success, last nonblank psql JSON parsing,
empty and malformed output, shape mismatches, psql failures, no Psycopg import
attempts, and unchanged `StorageSummaryRecord` conversion. The existing CLI
sanitizer coverage now includes `storage summary --legacy`. No dependency,
package metadata, lockfile, SQL, parser, payload, schema, discovery, refresh,
real database mutation, ingest, COPY, staging-table, prepared-statement, or
pipeline-mode behavior changes. The next implementation slice should consider
`query_canonical_storage_summary`; benchmark/parity work should follow only
after legacy and canonical summary adapter wiring are stable.

PSYCOPG3 implementation note: PSYCOPG3 reuses the PSYCOPG2 psql-backed
readback adapter for the default canonical `storage summary` path by wiring
only `query_canonical_storage_summary` through `execute_json_readback(...)`.
The function still uses `build_canonical_storage_summary_query_sql(root_path)`
and `canonical_storage_summary_from_payload(...)`, preserving SQL, parser,
`CanonicalStorageSummaryRecord`, CLI, MCP/status, sanitizer, and
`StorageSchemaError` behavior. Focused tests characterize the adapter call and
canonical/raw summary field conversion while existing adapter tests continue to
cover malformed JSON, shape mismatches, psql failures, and absence of Psycopg
imports. No dependency, package metadata, lockfile, schema, migration,
discovery, refresh, real database mutation, ingest, COPY, staging-table,
prepared-statement, pipeline-mode, or broader readback-family behavior changed.
PSYCOPG4 should design benchmark/parity expectations for the adapter-backed
legacy and canonical summary paths before adding Psycopg, or explicitly design
a very small next readback-family expansion plan if implementation continues
first.

PSYCOPG4 design note: PSYCOPG4 narrows the first benchmark/parity harness to
the two adapter-backed summary paths, `query_storage_summary` and
`query_canonical_storage_summary`, and keeps every broader readback family,
ingest/write path, ops/lifecycle path, discovery, refresh, real graph database,
and live-smoke path out of scope. The recommended PSYCOPG5 implementation is a
small disposable-Postgres parity harness using existing synthetic storage
loading patterns, not private live graphs or checked-in private benchmark
output. CI should gate on decoded payload, row dataclass, `to_dict()`, CLI JSON,
optional table-column smoke, shape, error-boundary reuse, and privacy/artifact
policy. Timing should be optional/local psql-baseline metadata only, with no
absolute elapsed-time gate until a later Psycopg implementation exists to
compare.

PSYCOPG5 implementation note: PSYCOPG5 adds the first disposable-Postgres
parity harness for the two adapter-backed summary paths only. The synthetic
fixture loads public-safe file, `shell.command`, and `python.import`
observations through the existing storage integration helpers, then compares
direct adapter decoded JSON, row dataclass conversion, `to_dict()`/JSONable
output, CLI JSON, and stable table-column smoke coverage for both legacy
`storage summary --legacy` and default canonical `storage summary`. It keeps
timing out of CI gates, adds no Psycopg or dependency, and preserves package
metadata, lockfiles, SQL, parser behavior, CLI/MCP payload contracts,
discovery, refresh, live smoke, real graph databases, and broader readback
families. PSYCOPG6 should choose between a local-only psql timing baseline
helper and the first actual Psycopg implementation plan.

PSYCOPG6 design note: PSYCOPG6 decides to proceed next with the first actual
Psycopg adoption slice rather than adding a standalone psql-only timing helper.
The recommended PSYCOPG7 slice is `psycopg[binary]>=3.2,<4` for the local/dev
pilot, a dedicated third-party notice entry for the `LGPL-3.0-only` dependency,
and an opt-in Psycopg implementation behind the existing
`execute_json_readback(...)` seam. The driver switch should be
`REPOMAP_STORAGE_READBACK_DRIVER` with accepted values `psql` and `psycopg`,
defaulting to `psql` with no Psycopg import attempted unless explicitly
enabled. The first Psycopg target remains only `query_storage_summary` and
`query_canonical_storage_summary`; broader readback families, ingest, COPY,
staging tables, prepared statements, pipeline mode, timing gates, discovery,
refresh, live smoke, real graph databases, and defaulting any path to Psycopg
remain deferred.

PSYCOPG7 implementation note: PSYCOPG7 adds the first actual
`psycopg[binary]>=3.2,<4` runtime dependency, records third-party notice
coverage for the `LGPL-3.0-only` package, and keeps psql as the default
readback driver. `execute_json_readback(...)` remains the single internal
adapter entry point, with `REPOMAP_STORAGE_READBACK_DRIVER=psycopg` as the only
way to select the new Psycopg helper. The opt-in driver is limited to the two
adapter-backed summary paths, `query_storage_summary` and
`query_canonical_storage_summary`, and preserves SQL builders, parser
contracts, row dataclasses, CLI/MCP payloads, and sanitizer boundaries. Focused
unit tests cover driver selection, psql argument conversion, Psycopg result
decoding, sanitized error behavior, and no-fallback semantics; the
disposable-Postgres parity harness now runs in both psql and explicit Psycopg
modes for the summary paths. Broader readback families, ingest, COPY, staging
tables, prepared statements, pipeline mode, timing gates, discovery, refresh,
live smoke, real graph databases, and defaulting any path to Psycopg remain
deferred. PSYCOPG8 should evaluate the Psycopg-mode parity results and decide
whether to add local-only psql-vs-Psycopg timing comparison, expand one small
readback family, or refine opt-in error/connection handling.

PSYCOPG8 evaluation note: PSYCOPG8 reviews the first opt-in Psycopg summary
driver and decides that PSYCOPG7 satisfied the adoption-pilot acceptance
criteria for the two object-shaped summary paths. The explicit
`REPOMAP_STORAGE_READBACK_DRIVER=psycopg` path has disposable-Postgres parity
for legacy and canonical storage summaries, while psql remains the default and
the comparison oracle. PSYCOPG8 recommends PSYCOPG9 as a local-only
psql-vs-Psycopg timing comparison for those same two summary paths before any
broader readback-family expansion. Defaulting to Psycopg, `auto` driver
selection, canonical node/edge/neighborhood migration, source/feed migration,
ingest, COPY, staging tables, prepared statements, pipeline mode, discovery,
refresh, live smoke, real graph databases, and private benchmark output remain
deferred.

PSYCOPG9 implementation note: PSYCOPG9 adds a local-only timing comparison
harness for the same two adapter-backed summary paths, `query_storage_summary`
and `query_canonical_storage_summary`. The harness reuses the synthetic
disposable-Postgres fixture, measures psql mode and explicit
`REPOMAP_STORAGE_READBACK_DRIVER=psycopg` mode through the query functions, and
asserts only record schema, non-negative elapsed values, payload byte sizes,
psql/Psycopg payload parity, privacy-safe serialized timing records, and
environment restoration. It does not commit generated timing output, add
absolute elapsed-time gates, change dependency metadata, default any path to
Psycopg, move broader readback families, or touch ingest, COPY, staging,
prepared statements, pipeline mode, discovery, refresh, live smoke, real graph
databases, or private benchmark data. PSYCOPG10 should evaluate local timing
evidence and choose whether to expand one small array-shaped readback family,
improve opt-in connection/error handling, or keep the pilot limited while more
timing evidence is collected.

PSYCOPG10 evaluation note: PSYCOPG10 decides that PSYCOPG9 satisfied the
PSYCOPG8 recommendation by adding a local-only timing comparison baseline for
the two object-shaped summary paths without absolute elapsed-time gates or
private timing artifacts. The baseline is sufficient to proceed cautiously, but
it is not a performance verdict and does not justify defaulting to Psycopg.
PSYCOPG11 should choose Option A and expand the explicit opt-in
`REPOMAP_STORAGE_READBACK_DRIVER=psycopg` adapter to
`query_canonical_node_records` only. That first array-shaped target is
read-only, canonical, deterministic by existing SQL ordering, already covered
by CLI/MCP surfaces, and less complex than canonical edges, neighborhoods,
source/feed readback, or edge explanations. Connection/error hardening remains
available as a follow-up if PSYCOPG11 parity exposes a concrete gap; broader
readback movement, default-to-Psycopg behavior, auto driver selection, ingest,
COPY, staging, prepared statements, pipeline mode, discovery, refresh, live
smoke, real graph databases, and private benchmark output remain deferred.

PSYCOPG11 implementation note: PSYCOPG11 wires only
`query_canonical_node_records` through `execute_json_readback(...)` with
`expected_shape="array"`, preserving psql as the default driver and explicit
`REPOMAP_STORAGE_READBACK_DRIVER=psycopg` opt-in for Psycopg. The existing SQL
builder, filters, `ORDER BY canonical_nodes.canonical_key` behavior, row
dataclass conversion, CLI JSON shape, and MCP wrapper contracts are preserved.
Focused unit coverage proves adapter call shape and filter pass-through, while
the disposable-Postgres synthetic fixture proves psql/Psycopg canonical-node
parity, deterministic ordering, dataclass conversion parity, environment
restoration, and compact CLI JSON parity for `storage canonical-nodes
--path-prefix src/ --json`. Default-to-Psycopg behavior, broader readback
movement, canonical edge/neighborhood/source/feed migration, ingest, COPY,
staging, prepared statements, pipeline mode, discovery, refresh, live smoke,
real graph databases, generated timing output, private graph data, and
dependency/package metadata changes remain deferred. PSYCOPG12 should evaluate
canonical node parity and choose whether to expand next to
`query_canonical_edge_records`, improve array-shaped parity/ordering coverage,
or pause expansion for more timing/parity evidence.

PSYCOPG12 evaluation note: PSYCOPG12 decides that PSYCOPG11 satisfied the
PSYCOPG10 recommendation by adapting only `query_canonical_node_records` as the
first array-shaped Psycopg readback family. The node slice preserved psql as
default, kept Psycopg explicit opt-in, preserved SQL ordering and filters,
proved dataclass and CLI JSON parity with the disposable-Postgres fixture, and
did not expose a concrete ordering/filter/CLI gap that would block the next
small expansion. PSYCOPG13 should choose Option A and wire only
`query_canonical_edge_records` through `execute_json_readback(...)` with
`expected_shape="array"`, preserving existing SQL ordering, edge filters, row
conversion, psql default behavior, and explicit Psycopg opt-in. Defaulting to
Psycopg, auto driver selection, canonical neighborhood migration, edge
explanation migration, source/feed migration, legacy readback migration,
ingest, COPY, staging, prepared statements, pipeline mode, discovery, refresh,
live smoke, real graph databases, generated benchmark output, private graph
data, and dependency/package metadata changes remain deferred.

PSYCOPG13 implementation note: PSYCOPG13 wires only
`query_canonical_edge_records` through `execute_json_readback(...)` with
`expected_shape="array"`. The slice preserves psql as the default driver,
keeps Psycopg explicit opt-in, preserves the existing canonical-edge SQL
builder, ordering, filters, row conversion, and CLI/MCP payload contracts, and
adds focused unit coverage plus disposable-Postgres psql/Psycopg parity for
bounded canonical edge readback. The parity test covers deterministic ordering,
kind/source/target filters, dataclass `to_dict()` parity, environment
restoration, and compact CLI JSON parity for `storage canonical-edges --kind
... --source-key ... --json`. MCP wrappers were not touched. Defaulting to
Psycopg, auto driver selection, broader readback movement, canonical
neighborhood migration, edge explanation migration, source/feed migration,
legacy readback migration, ingest, COPY, staging, prepared statements,
pipeline mode, discovery, refresh, live smoke, real graph databases, generated
benchmark output, private graph data, and dependency/package metadata changes
remain deferred. PSYCOPG14 should evaluate canonical edge parity and choose
whether to expand to canonical neighborhood or edge explanation readback, pause
for more timing/parity data, or improve array-shaped connection/error coverage.

PSYCOPG14 evaluation note: PSYCOPG14 decides that PSYCOPG13 satisfied the
PSYCOPG12 recommendation by adapting only `query_canonical_edge_records` as the
second array-shaped canonical Psycopg readback family. The edge slice preserved
psql as default, kept Psycopg explicit opt-in, preserved SQL ordering and
filters, proved dataclass and compact CLI JSON parity with the
disposable-Postgres fixture, and did not expose a concrete ordering, fixture,
timing, or connection/error gap that should pause expansion. PSYCOPG15 should
choose Option B and wire only `query_canonical_edge_explanation` through
`execute_json_readback(...)`, preserving existing SQL text, edge identity
parameters, nested evidence ordering, payload conversion, psql default
behavior, and explicit Psycopg opt-in. Canonical neighborhood migration should
wait until the narrower edge-explanation payload is characterized. Defaulting
to Psycopg, auto driver selection, broader readback movement, source/feed
migration, legacy readback migration, ingest, COPY, staging, prepared
statements, pipeline mode, discovery, refresh, live smoke, real graph
databases, generated benchmark output, private graph data, and
dependency/package metadata changes remain deferred.

PSYCOPG15 implementation note: PSYCOPG15 wires only
`query_canonical_edge_explanation` through `execute_json_readback(...)` with
`expected_shape="object"`. The slice preserves psql as the default driver,
keeps Psycopg explicit opt-in, preserves the existing edge-explanation SQL
builder, edge identity parameters, nested evidence ordering, missing-edge
object shape, payload conversion, and CLI/MCP payload contracts, and adds
focused unit coverage plus disposable-Postgres psql/Psycopg parity for bounded
canonical edge explanation readback. The parity test covers selected-edge
identity, nested evidence payload equivalence, deterministic evidence ordering,
missing-edge behavior, environment restoration, and compact CLI JSON parity for
`storage explain-canonical-edge --source-key ... --kind ... --target-key ...
--identity-metadata-json ... --json`. MCP wrappers were not touched.
Defaulting to Psycopg, auto driver selection, broader readback movement,
canonical neighborhood migration, source/feed migration, legacy readback
migration, ingest, COPY, staging, prepared statements, pipeline mode,
discovery, refresh, live smoke, real graph databases, generated benchmark
output, private graph data, and dependency/package metadata changes remain
deferred. PSYCOPG16 should evaluate canonical edge explanation parity and
decide whether to expand to canonical neighborhood, improve nested payload
parity/ordering coverage, pause for more timing/parity data, or improve
explicit driver connection/error coverage.

PSYCOPG16 architecture note: PSYCOPG16 pivots the Psycopg pilot from ad hoc
readback-driver helpers toward a formal PostgreSQL connector facade. RepoMap
should maintain two official JSON-readback connector plugins: `psql` for the
existing custom psql-process path and `psycopg` for the Psycopg path. Storage
callers should continue to use one facade entry point while SQL builders,
row/payload conversion, and CLI/MCP rendering stay in their current layers.
`REPOMAP_STORAGE_READBACK_DRIVER` remains the compatibility selection variable
for now, with `psql` still default and `psycopg` explicit opt-in; any future
connector-named env var should be additive and handled in a separate phase.
The first connector registry should be static and internal, with capability
metadata limited to `json_readback`; dynamic third-party plugin loading, COPY,
prepared statements, pipeline mode, pooling, ingest/write paths, additional
readback-family movement, and any default-to-Psycopg decision remain deferred.
PSYCOPG17 should implement the no-behavior-change connector facade around the
existing psql and Psycopg JSON readback helpers, preserve all current parity
tests, and add focused unit coverage for registry selection, capability
metadata, sanitized errors, and no-fallback semantics.

PSYCOPG17 implementation note: PSYCOPG17 implements the PostgreSQL JSON
readback connector facade around the existing psql-process and Psycopg helper
paths while preserving `execute_json_readback(...)` for current storage
callers. `readback_driver.py` now defines the `PgJsonReadbackConnector`
protocol, official `PsqlJsonReadbackConnector` and
`PsycopgJsonReadbackConnector` classes, a static `CONNECTORS` registry with
`psql` and `psycopg`, and `json_readback` capability metadata for both
connectors. `REPOMAP_STORAGE_READBACK_DRIVER` remains the compatibility
selector, `psql` remains the default, and Psycopg remains explicit opt-in with
lazy import and no fallback after explicit connector failures. The phase adds
focused unit coverage for registry membership, connector selection,
capability metadata, psql command construction, Psycopg delegation, sanitizer
behavior, and no-fallback behavior while preserving existing PSYCOPG7/9/11/13/15
parity and timing tests. New readback families, canonical neighborhood
migration, connector-named env vars, dynamic plugin loading, third-party
connector discovery, default-to-Psycopg decisions, ingest/COPY/staging/
prepared/pipeline work, discovery, refresh, live smoke, real graph database
mutation, generated benchmark output, private graph data, and dependency/
package metadata changes remain deferred. PSYCOPG18 should evaluate the
connector facade implementation and decide whether to expand connector
parity/timing coverage, add an additive connector-named env var, resume
readback-family expansion with canonical neighborhood, or improve connector
registration/capability documentation.

PSYCOPG18 evaluation note: PSYCOPG18 evaluates the PSYCOPG17 connector facade
and accepts it as the official psql-vs-Psycopg comparison boundary. The current
comparable readback surface is `query_storage_summary`,
`query_canonical_storage_summary`, `query_canonical_node_records`,
`query_canonical_edge_records`, and `query_canonical_edge_explanation`.
Existing parity coverage spans those families, selected CLI JSON paths,
environment restoration, sanitizer behavior, and no-fallback semantics, while
timing coverage still spans only the two summary paths. PSYCOPG19 should add
local-only timing comparison across all currently adapted readback families
using the official connector names `psql` and `psycopg`, without private live
graphs, generated timing output, absolute timing gates, a default connector
change, or new readback-family movement. Additive connector-named environment
variables, canonical neighborhood expansion, dynamic plugin loading,
third-party connector registration, ingest/COPY/staging/prepared/pipeline
work, and any default-to-Psycopg decision remain deferred.

PSYCOPG19 implementation note: PSYCOPG19 expands the local-only connector
timing harness from summary-only coverage to all currently adapted JSON
readback families: `query_storage_summary`,
`query_canonical_storage_summary`, `query_canonical_node_records`,
`query_canonical_edge_records`, and `query_canonical_edge_explanation`. The
timing test uses the official connector facade by selecting `psql` and
`psycopg` through `REPOMAP_STORAGE_READBACK_DRIVER`, records connector-labeled
timing schema fields, compares psql/Psycopg payloads for every operation, keeps
one normal-suite iteration, restores `REPOMAP_STORAGE_READBACK_DRIVER` and
`PGPASSWORD`, and asserts that serialized records omit private fixture values,
raw SQL, psql args, generated timing output, and absolute timing thresholds.
Defaulting to Psycopg, adding connector-named env vars, moving canonical
neighborhood or other readback families, dynamic plugin loading, third-party
connector registration, ingest/COPY/staging/prepared/pipeline work, discovery,
refresh, live smoke, real graph database mutation, private graph benchmarking,
generated artifacts, and dependency/package metadata changes remain deferred.
PSYCOPG20 should evaluate the expanded timing evidence before any connector
default or naming decision.

PSYCOPG20 decision note: PSYCOPG20 evaluates the expanded PSYCOPG19 connector
timing matrix and confirms parity and timing now both cover the currently
adapted JSON readback surface: storage summary, canonical storage summary,
canonical node records, canonical edge records, and canonical edge explanation.
The project is not ready to choose a default connector yet because the normal
integration harness intentionally uses one iteration, commits no generated
timing output, and does not summarize median/min/max or local variance.
PSYCOPG21 should add a local-only official connector comparison report helper
for `psql` and `psycopg`, preferably as a small privacy-safe `tools/` command
with configurable iterations, aggregate timing fields, parity results, and
explicit output control. Defaulting to Psycopg, adding connector-named env
vars, resuming canonical neighborhood expansion, dynamic plugin loading,
third-party connector registration, ingest/COPY/staging/prepared/pipeline
work, discovery, refresh, live smoke, real graph database mutation, private
graph benchmarking, generated artifacts, and dependency/package metadata
changes remain deferred.

PSYCOPG21 implementation note: PSYCOPG21 adds
`tools/compare_pg_connectors.py`, a local-only official connector comparison
helper for `psql` and `psycopg` across the currently adapted JSON readback
families: storage summary, canonical storage summary, canonical node records,
canonical edge records, and canonical edge explanation. The helper uses
disposable Postgres synthetic fixtures, selects connectors through
`REPOMAP_STORAGE_READBACK_DRIVER`, calls the same query functions that route
through `execute_json_readback(...)`, preserves psql/Psycopg parity checks,
supports configurable iterations, emits connector-labeled aggregate timing
fields, writes files only with an explicit `--output`, and keeps report output
limited to privacy-safe counts, payload sizes, operation names, connector
names, parity, and a fixed synthetic fixture label. Defaulting to Psycopg,
adding connector-named env vars, adding new readback families, dynamic plugin
loading, third-party connector registration, ingest/COPY/staging/prepared/
pipeline work, discovery, refresh, live smoke, real graph database mutation,
private graph benchmarking, generated report artifacts, and dependency/package
metadata changes remain deferred. PSYCOPG22 should evaluate the helper and
choose the next evidence, naming, readback-expansion, or documentation step
without making an implicit default connector decision.

PSYCOPG22 evaluation note: PSYCOPG22 runs the PSYCOPG21 local-only official
connector comparison helper with five iterations against disposable Postgres
and confirms that both official connectors, `psql` and `psycopg`, are compared
across storage summary, canonical storage summary, canonical node records,
canonical edge records, and canonical edge explanation. Parity passes for every
operation, output remains privacy-safe, no generated report artifact is
committed, and the local median timing pattern favors Psycopg across the
currently adapted surface while remaining machine-local evidence only.
PSYCOPG23 should be a docs-only default-connector decision design phase that
records decision criteria, local variance interpretation, rollback policy,
migration/release-note requirements, and compatibility policy for keeping
`psql` available as an official connector. Defaulting to Psycopg, adding
connector-named env vars, adding new readback families, dynamic plugin loading,
third-party connector registration, ingest/COPY/staging/prepared/pipeline
work, discovery, refresh, live smoke, real graph database mutation, private
graph benchmarking, generated report artifacts, and dependency/package metadata
changes remain deferred.

PSYCOPG23 decision-design note: PSYCOPG23 reviews the PSYCOPG22 local helper
evidence and recommends switching the default PostgreSQL JSON readback
connector to `psycopg` in a later explicit implementation phase. The
recommendation is based on parity passing for every currently adapted readback
family, privacy-safe helper output, and local median timing favoring Psycopg
across the adapted surface, while documenting that the timing evidence is
machine-local rather than a universal performance guarantee. The required
rollback and compatibility policy is that `psql` remains official, tested,
supported, and selectable through `REPOMAP_STORAGE_READBACK_DRIVER=psql`.
PSYCOPG24 should be the narrow implementation phase that changes only the
default connector selection if approved, preserving explicit `psql` and
`psycopg` selection, no-fallback behavior, and existing payload contracts.
Adding connector-named env vars, adding new readback families, dynamic plugin
loading, third-party connector registration, ingest/COPY/staging/prepared/
pipeline work, discovery, refresh, live smoke, real graph database mutation,
private graph benchmarking, generated report artifacts, and dependency/package
metadata changes remain deferred.

PSYCOPG24 implementation note: PSYCOPG24 changes only the default PostgreSQL
JSON readback connector for the unset `REPOMAP_STORAGE_READBACK_DRIVER` case:
the default is now `psycopg` instead of `psql`. The official `psql` connector
remains supported, tested, and available as the rollback path with
`REPOMAP_STORAGE_READBACK_DRIVER=psql`; explicit
`REPOMAP_STORAGE_READBACK_DRIVER=psycopg` also remains supported. Tests now
prove the new unset-env default, explicit `psql` rollback, explicit Psycopg
selection, sanitized unsupported values, no-fallback behavior, the static
registry, and `json_readback` capability metadata for both official
connectors. The migration note is that users relying on `psql` process
behavior can pin `psql`; performance may vary by environment, and regression
reports should include only connector, operation, and sanitized environment
details. Connector-named env vars, auto selection, dynamic plugin loading,
third-party connector registration, new readback families, canonical
neighborhood/source/feed/legacy migration, ingest/COPY/staging/prepared/
pipeline work, discovery, refresh, live smoke, real graph database mutation,
generated timing artifacts, and dependency/package metadata changes remain
deferred. PSYCOPG25 should evaluate the default switch and decide whether to
add an additive connector-named env var, resume canonical-neighborhood
readback expansion, improve connector comparison/reporting documentation, or
monitor the default change before expanding further.

PSYCOPG25 evaluation note: PSYCOPG25 confirms that PSYCOPG24 completed the
default PostgreSQL JSON readback connector switch for the unset
`REPOMAP_STORAGE_READBACK_DRIVER` case while preserving explicit `psql`
rollback, explicit Psycopg selection, the official connectors, the static
registry, no-fallback semantics, existing SQL/parser/payload/CLI/MCP contracts,
and dependency/package metadata boundaries. The PSYCOPG24 connector comparison
helper and full source gate passed after the switch. PSYCOPG25 recommends
PSYCOPG26 as an additive connector-named selector phase for
`REPOMAP_STORAGE_PG_CONNECTOR`, preserving `REPOMAP_STORAGE_READBACK_DRIVER`,
default Psycopg behavior, accepted values `psql` and `psycopg`, and explicit
`psql` rollback. The preferred future precedence is conflict-safe: use the new
selector when only it is set, use the compatibility selector when only it is
set, accept matching values, raise a sanitized error if both selectors disagree,
and default to Psycopg when neither is set. Canonical-neighborhood expansion,
connector reporting documentation, auto selection, dynamic plugin loading,
third-party connector registration, discovery, refresh, live smoke, real graph
database mutation, new readback families, and dependency/package metadata
changes remain deferred.

PSYCOPG26 implementation note: PSYCOPG26 adds
`REPOMAP_STORAGE_PG_CONNECTOR` as an additive connector-named selector while
preserving `REPOMAP_STORAGE_READBACK_DRIVER` for compatibility. The default
remains Psycopg when neither selector is set, explicit `psql` rollback is
available through either selector, matching dual-selector values are accepted,
and conflicting selector values raise a sanitized `StorageSchemaError` without
echoing raw environment values. Accepted connector values remain `psql` and
`psycopg`; the official connectors, static registry, `json_readback`
capability metadata, no-fallback semantics, and existing SQL/parser/payload/
CLI/MCP contracts are preserved. The connector comparison helper continues to
use the compatibility selector for explicit per-connector runs while clearing
the additive selector inside its managed comparison environment. PSYCOPG27
should evaluate the additive selector and decide whether to resume canonical
neighborhood readback expansion, improve connector comparison/reporting
documentation, add connector selection documentation, or monitor connector UX
before expanding. Auto selection, dynamic plugin loading, third-party connector
registration, new readback families, discovery, refresh, live smoke, real graph
database mutation, ingest/COPY/staging/prepared/pipeline work, generated timing
artifacts, and dependency/package metadata changes remain deferred.

PSYCOPG27 evaluation note: PSYCOPG27 confirms that PSYCOPG26 completed the
additive connector selector cleanup. `REPOMAP_STORAGE_PG_CONNECTOR` works as a
connector-named selector, `REPOMAP_STORAGE_READBACK_DRIVER` remains supported
for compatibility, default Psycopg behavior and explicit `psql` rollback remain
available, conflict-safe precedence is tested, and the connector comparison
helper still uses explicit compatibility-selector runs while clearing the
additive selector inside its managed environment. PSYCOPG27 recommends
PSYCOPG28 as a narrow canonical-neighborhood readback phase: wire only
`query_canonical_neighborhood` through `execute_json_readback(...)`, preserve
SQL text, depth and direction validation, center/node/edge payload shapes,
nested ordering, selector behavior, no-fallback semantics, and add bounded
`psql`/Psycopg parity plus compact CLI JSON coverage where practical.
Connector reporting docs, source/feed readback, legacy readback, Nix,
Bulk/API, domain summaries, ops paths, auto selection, dynamic plugin loading,
third-party connector registration, discovery, refresh, live smoke, real graph
database mutation, ingest/COPY/staging/prepared/pipeline work, generated timing
artifacts, and dependency/package metadata changes remain deferred.

PSYCOPG28 implementation note: PSYCOPG28 wires only
`query_canonical_neighborhood` through `execute_json_readback(...)` while
preserving the existing canonical-neighborhood SQL builder, depth validation,
direction validation, center/node/edge payload shape, nested ordering, default
Psycopg behavior, explicit `psql` rollback through both connector selectors,
and selector conflict behavior. Focused unit coverage verifies adapter call
shape and parameter pass-through, and disposable-Postgres parity coverage
compares default Psycopg, explicit Psycopg, and explicit `psql` outputs for a
bounded synthetic canonical neighborhood, including compact CLI JSON parity.
The connector comparison helper remains on its existing adapted-operation
matrix and passes as a regression check. PSYCOPG29 should evaluate canonical
neighborhood parity and decide whether to expand source/feed readback, expand
one legacy readback family, improve connector comparison/reporting
documentation, or collect more parity/timing evidence. Source/feed readback,
legacy readback, Nix, Bulk/API, domain summaries, ops paths, auto selection,
dynamic plugin loading, third-party connector registration, discovery, refresh,
live smoke, real graph database mutation, ingest/COPY/staging/prepared/pipeline
work, generated timing artifacts, and dependency/package metadata changes
remain deferred.

PSYCOPG29 evaluation note: PSYCOPG29 confirms that PSYCOPG28 completed the
canonical-neighborhood adapter step cleanly. The facade-backed readback surface
now includes storage summary, canonical storage summary, canonical node
records, canonical edge records, canonical edge explanation, and canonical
neighborhood. PSYCOPG29 recommends PSYCOPG30 as a docs-only source/feed
readback design phase before implementation, because the inspected source/feed
surface includes object, array, and nested raw-dictionary payloads with source
IDs, run IDs, artifact paths, artifact hashes, URL summaries, HTTP metadata,
feed item metadata, evidence paths, extractor metadata, and MCP wrappers that
need explicit privacy, fixture, parity, and contract rules. Legacy readback,
source/feed implementation, connector reporting changes, Nix, Bulk/API, domain
summaries, ops paths, auto selection, dynamic plugin loading, third-party
connector registration, discovery, refresh, live smoke, real graph database
mutation, ingest/COPY/staging/prepared/pipeline work, generated timing
artifacts, and dependency/package metadata changes remain deferred.

PSYCOPG30 design note: PSYCOPG30 inventories the source/feed readback family
and selects `query_source_summary` as the PSYCOPG31 implementation target. The
source/feed surface remains direct `psql` readback today and includes
`query_ingested_source_records`, `query_source_summary`,
`query_source_run_records`, `query_source_feed_item_records`,
`query_source_reference_records`, and
`query_source_feed_item_explanation`, backed by the `sql_sources` builders and
MCP wrappers. `query_source_summary` is chosen first because it is
object-shaped, scoped to one source ID, uses `SourceSummaryRecord`, has
existing public-safe fixture coverage, and avoids list pagination or nested raw
evidence. PSYCOPG31 should wire only that function through
`execute_json_readback(...)` with `expected_shape="object"`, `psql`/Psycopg
parity, and source/feed privacy-safe synthetic fixture coverage. Source/feed
implementation beyond `query_source_summary`, legacy readback, CLI surface
changes, dynamic plugin loading, third-party registration, discovery, refresh,
real graph mutation, ingest/COPY/staging/prepared/pipeline work, generated
timing artifacts, and dependency/package metadata changes remain deferred.

PSYCOPG31 implementation note: PSYCOPG31 wires only
`query_source_summary` through `execute_json_readback(...)` with
`expected_shape="object"` while preserving the existing source summary SQL
builder, source ID handling, `SourceSummaryRecord` conversion, MCP payload
shape, default Psycopg behavior, explicit `psql` rollback through both
connector selectors, explicit Psycopg selection, conflict-safe selector
behavior, and no-fallback semantics. Focused unit coverage verifies adapter
call shape and parameter pass-through, and disposable-Postgres parity coverage
compares explicit `psql`, unset-default Psycopg, and explicit Psycopg source
summary output for a public-safe source/feed fixture, including missing-source
behavior and `repomap_source_summary` MCP wrapper shape. No source/feed CLI
surface is added because no dedicated storage CLI source/feed readback command
exists. PSYCOPG32 should evaluate source summary parity and decide whether to
adapt `query_ingested_source_records`, adapt `query_source_run_records`,
improve source/feed fixture coverage, or pause source/feed migration for more
parity/privacy evidence. Additional source/feed functions, legacy readback,
CLI surface changes, dynamic plugin loading, third-party registration,
discovery, refresh, real graph mutation, ingest/COPY/staging/prepared/pipeline
work, generated timing artifacts, and dependency/package metadata changes
remain deferred.

PSYCOPG32 evaluation note: PSYCOPG32 confirms that PSYCOPG31 completed the
first source/feed adapter migration cleanly. Source summary parity held across
explicit `psql`, unset-default Psycopg, and explicit Psycopg modes; missing
source behavior remained equivalent; `repomap_source_summary` output stayed
consistent with direct storage readback; and the full-feed-body privacy
boundary remained intact. PSYCOPG32 recommends PSYCOPG33 as a narrow
implementation phase for `query_ingested_source_records` only, using
`execute_json_readback(...)` with `expected_shape="array"` while preserving SQL
text, `source_type` and `policy_status` filters, positive-limit behavior,
ordering by configured source ID, `IngestedSourceRecord` conversion,
`ingested_source_records_to_jsonable(...)`, `repomap_ingested_sources` MCP
payload shape, default Psycopg behavior, explicit `psql` rollback through both
selectors, and conflict-safe selector behavior. Source run records, feed item
records, source references, feed item explanation, source/feed CLI commands,
legacy readback, dynamic plugin loading, third-party registration, discovery,
refresh, real graph mutation, ingest/COPY/staging/prepared/pipeline work,
generated timing artifacts, and dependency/package metadata changes remain
deferred.

PSYCOPG33 implementation note: PSYCOPG33 wires only
`query_ingested_source_records` through `execute_json_readback(...)` with
`expected_shape="array"` while preserving the existing ingested source SQL
builder, `source_type` and `policy_status` filters, positive-limit behavior,
ordering by configured source ID, `IngestedSourceRecord` conversion,
`ingested_source_records_to_jsonable(...)`, `repomap_ingested_sources` MCP
payload shape, default Psycopg behavior, explicit `psql` rollback through both
connector selectors, explicit Psycopg selection, conflict-safe selector
behavior, and no-fallback semantics. Focused unit coverage verifies adapter
call shape and parameter pass-through, and disposable-Postgres parity coverage
compares explicit `psql`, unset-default Psycopg, and explicit Psycopg ingested
source output for a public-safe source/feed fixture, including filters, limit,
ordering, empty-list behavior, and `repomap_ingested_sources` MCP wrapper
shape. No source/feed CLI surface is added because no dedicated storage CLI
source/feed readback command exists. PSYCOPG34 should evaluate ingested source
parity and decide whether to adapt `query_source_run_records`, adapt
`query_source_feed_item_records`, improve source/feed fixture coverage, or
pause source/feed migration for more parity/privacy evidence. Additional
source/feed functions, legacy readback, CLI surface changes, dynamic plugin
loading, third-party registration, discovery, refresh, real graph mutation,
ingest/COPY/staging/prepared/pipeline work, generated timing artifacts, and
dependency/package metadata changes remain deferred.

PSYCOPG34 evaluation note: PSYCOPG34 confirms that PSYCOPG33 completed the
second source/feed adapter migration cleanly. Ingested source parity held
across explicit `psql`, unset-default Psycopg, and explicit Psycopg modes;
`source_type` and `policy_status` filters, limit behavior, deterministic
source ID ordering, empty-list behavior, `IngestedSourceRecord` conversion,
`ingested_source_records_to_jsonable(...)`, and `repomap_ingested_sources` MCP
wrapper shape remained equivalent; and the full-feed-body privacy boundary
remained intact. PSYCOPG34 recommends PSYCOPG35 as a narrow implementation
phase for `query_source_run_records` only, using `execute_json_readback(...)`
with `expected_shape="array"` while preserving SQL text, required `source_id`
behavior, positive-limit behavior, ordering by acquisition time and source run
ID, `SourceRunRecord` conversion, `source_run_records_to_jsonable(...)`,
`repomap_source_runs` MCP payload shape, default Psycopg behavior, explicit
`psql` rollback through both selectors, and conflict-safe selector behavior.
Feed item records, source references, feed item explanation, source/feed CLI
commands, legacy readback, dynamic plugin loading, third-party registration,
discovery, refresh, real graph mutation, ingest/COPY/staging/prepared/pipeline
work, generated timing artifacts, and dependency/package metadata changes
remain deferred.

PSYCOPG35 implementation note: PSYCOPG35 wires only
`query_source_run_records` through `execute_json_readback(...)` with
`expected_shape="array"` while preserving the existing source run SQL builder,
required `source_id` behavior, positive-limit behavior, ordering by
`source_acquired_at DESC NULLS LAST, source_run_id DESC`,
`SourceRunRecord` conversion, `source_run_records_to_jsonable(...)`,
`repomap_source_runs` MCP payload shape, default Psycopg behavior, explicit
`psql` rollback through both connector selectors, explicit Psycopg selection,
conflict-safe selector behavior, and no-fallback semantics. Focused unit
coverage verifies adapter call shape and parameter pass-through, and
disposable-Postgres parity coverage compares explicit `psql`, unset-default
Psycopg, and explicit Psycopg source run output for a public-safe source/feed
fixture, including source ID scoping, limit behavior, missing source behavior,
ordering, source run field shape, and `repomap_source_runs` MCP wrapper shape.
No source/feed CLI surface is added because no dedicated storage CLI
source/feed readback command exists. PSYCOPG36 should evaluate source run
parity and decide whether to adapt `query_source_feed_item_records`, adapt
`query_source_reference_records`, improve source/feed fixture coverage, or
pause source/feed migration for more parity/privacy evidence. Additional
source/feed functions, legacy readback, CLI surface changes, dynamic plugin
loading, third-party registration, discovery, refresh, real graph mutation,
ingest/COPY/staging/prepared/pipeline work, generated timing artifacts, and
dependency/package metadata changes remain deferred.

PSYCOPG36 evaluation note: PSYCOPG36 confirms that PSYCOPG35 completed the
third source/feed adapter migration cleanly. Source run parity held across
explicit `psql`, unset-default Psycopg, and explicit Psycopg modes; required
`source_id` scoping, limit behavior, missing-source behavior, deterministic
source run ordering, `SourceRunRecord` conversion,
`source_run_records_to_jsonable(...)`, and `repomap_source_runs` MCP wrapper
shape remained equivalent; and the full-feed-body privacy boundary remained
intact. PSYCOPG36 recommends PSYCOPG37 as a narrow implementation phase for
`query_source_feed_item_records` only, using `execute_json_readback(...)` with
`expected_shape="array"` while preserving SQL text, required `source_id`
behavior, optional `source_run_id` filtering, positive-limit behavior,
ordering by `published_at DESC NULLS LAST, item_key`,
`SourceFeedItemRecord` conversion,
`source_feed_item_records_to_jsonable(...)`, `repomap_source_feed_items` MCP
payload shape, default Psycopg behavior, explicit `psql` rollback through both
selectors, and conflict-safe selector behavior. Source references, feed item
explanation, source/feed CLI commands, legacy readback, dynamic plugin loading,
third-party registration, discovery, refresh, real graph mutation,
ingest/COPY/staging/prepared/pipeline work, generated timing artifacts, and
dependency/package metadata changes remain deferred.

PSYCOPG37 implementation note: PSYCOPG37 wires only
`query_source_feed_item_records` through `execute_json_readback(...)` with
`expected_shape="array"` while preserving the existing source feed item SQL
builder, required `source_id` behavior, optional `source_run_id` filtering,
positive-limit behavior, ordering by `published_at DESC NULLS LAST, item_key`,
`SourceFeedItemRecord` conversion,
`source_feed_item_records_to_jsonable(...)`, `repomap_source_feed_items` MCP
payload shape, default Psycopg behavior, explicit `psql` rollback through both
connector selectors, explicit Psycopg selection, conflict-safe selector
behavior, and no-fallback semantics. Focused unit coverage verifies adapter
call shape and parameter pass-through, and disposable-Postgres parity coverage
compares explicit `psql`, unset-default Psycopg, and explicit Psycopg source
feed item output for a public-safe source/feed fixture, including required
source ID scoping, optional source run ID filtering, limit behavior, missing
source behavior, published/item ordering, feed item field shape, and
`repomap_source_feed_items` MCP wrapper shape. No source/feed CLI surface is
added because no dedicated storage CLI source/feed readback command exists.
PSYCOPG38 should evaluate feed item parity and decide whether to adapt
`query_source_reference_records`, adapt `query_source_feed_item_explanation`,
improve source/feed fixture coverage, or pause source/feed migration for more
parity/privacy evidence. Additional source/feed functions, legacy readback,
CLI surface changes, dynamic plugin loading, third-party registration,
discovery, refresh, real graph mutation, ingest/COPY/staging/prepared/pipeline
work, generated timing artifacts, and dependency/package metadata changes
remain deferred.

PSYCOPG38 evaluation note: PSYCOPG38 confirms that PSYCOPG37 completed the
fourth source/feed adapter migration cleanly. Source feed item parity held
across explicit `psql`, unset-default Psycopg, and explicit Psycopg modes;
required `source_id` scoping, optional `source_run_id` filtering, limit
behavior, missing-source behavior, deterministic published timestamp and item
key ordering, `SourceFeedItemRecord` conversion,
`source_feed_item_records_to_jsonable(...)`, and
`repomap_source_feed_items` MCP wrapper shape remained equivalent; and the
full-feed-body privacy boundary remained intact. PSYCOPG38 recommends
PSYCOPG39 as a narrow implementation phase for
`query_source_reference_records` only, using `execute_json_readback(...)` with
`expected_shape="array"` while preserving SQL text, required `source_id`
behavior, optional `source_run_id` filtering, optional `target_kind` filtering,
positive-limit behavior, ordering by `source_item_key, target_key`,
`SourceReferenceRecord` conversion,
`source_reference_records_to_jsonable(...)`, `repomap_source_references` MCP
payload shape, default Psycopg behavior, explicit `psql` rollback through both
selectors, and conflict-safe selector behavior. Feed item explanation,
source/feed CLI commands, legacy readback, dynamic plugin loading, third-party
registration, discovery, refresh, real graph mutation,
ingest/COPY/staging/prepared/pipeline work, generated timing artifacts, and
dependency/package metadata changes remain deferred.

PSYCOPG39 implementation note: PSYCOPG39 wires only
`query_source_reference_records` through `execute_json_readback(...)` with
`expected_shape="array"` while preserving the existing source reference SQL
builder, required `source_id` behavior, optional `source_run_id` filtering,
optional `target_kind` filtering, positive-limit behavior, ordering by
`source_item_key, target_key`, `SourceReferenceRecord` conversion,
`source_reference_records_to_jsonable(...)`, `repomap_source_references` MCP
payload shape, default Psycopg behavior, explicit `psql` rollback through both
connector selectors, explicit Psycopg selection, conflict-safe selector
behavior, and no-fallback semantics. Focused unit coverage verifies adapter
call shape and parameter pass-through, and disposable-Postgres parity coverage
compares explicit `psql`, unset-default Psycopg, and explicit Psycopg source
reference output for a public-safe source/feed fixture, including required
source ID scoping, optional source run ID filtering, optional target kind
filtering, limit behavior, missing source behavior, source item/target key
ordering, reference field shape, and `repomap_source_references` MCP wrapper
shape. No source/feed CLI surface is added because no dedicated storage CLI
source/feed readback command exists. PSYCOPG40 should evaluate source
reference parity and decide whether to design
`query_source_feed_item_explanation` migration before implementation, adapt it
directly if risk is clearly bounded, improve source/feed fixture coverage, or
pause source/feed migration for more parity/privacy evidence. Feed item
explanation, additional source/feed functions, legacy readback, CLI surface
changes, dynamic plugin loading, third-party registration, discovery, refresh,
real graph mutation, ingest/COPY/staging/prepared/pipeline work, generated
timing artifacts, and dependency/package metadata changes remain deferred.

PSYCOPG40 design/evaluation note: PSYCOPG40 confirms that PSYCOPG39 completed
the source reference adapter migration and that the typed source/feed readback
surface is now fully facade-backed. The only remaining source/feed readback
function on the direct `psql` path is
`query_source_feed_item_explanation`, which returns a nested raw dictionary
with top-level `item`, `source`, `evidence`, `references`, and
`content_policy` fields. The current SQL builder enforces a top-level object
shape, preserves required `item_key` behavior and optional `source_id`
filtering, orders evidence by raw observation ordinal, orders references by
target key, and emits the literal content policy `full feed bodies are not
exposed`. PSYCOPG40 recommends PSYCOPG41 as a narrow implementation phase for
that single function using `execute_json_readback(...)` with
`expected_shape="object"` while preserving SQL text, the raw dictionary
payload contract, nested item/source/evidence/reference/content-policy shape,
MCP wrapper shape, full-feed-body exclusion, default Psycopg behavior,
explicit `psql` rollback through both connector selectors, explicit Psycopg
selection, conflict-safe selector behavior, and no-fallback semantics.
PSYCOPG41 should add adapter-shape unit coverage plus disposable-Postgres
`psql`/Psycopg parity for public-safe nested explanation payloads, including
item/source fields, evidence and reference ordering, missing item/source
behavior, content policy, privacy checks, and
`repomap_explain_source_feed_item` MCP wrapper shape. Legacy readback,
source/feed CLI commands, SQL/payload/MCP contract changes, dynamic plugin
loading, third-party registration, discovery, refresh, real graph mutation,
ingest/COPY/staging/prepared/pipeline work, generated timing artifacts, and
dependency/package metadata changes remain deferred.

PSYCOPG41 implementation note: PSYCOPG41 wires only
`query_source_feed_item_explanation` through `execute_json_readback(...)` with
`expected_shape="object"` while preserving the existing source feed item
explanation SQL builder, required `item_key` behavior, optional `source_id`
filtering, raw dictionary payload contract, top-level `item`, `source`,
`evidence`, `references`, and `content_policy` shape, evidence ordering by raw
observation ordinal, reference ordering by target key,
`repomap_explain_source_feed_item` MCP wrapper shape, full-feed-body
exclusion, default Psycopg behavior, explicit `psql` rollback through both
connector selectors, explicit Psycopg selection, conflict-safe selector
behavior, and no-fallback semantics. Focused unit coverage verifies adapter
call shape and raw dictionary pass-through, and disposable-Postgres parity
coverage compares explicit `psql`, unset-default Psycopg, and explicit
Psycopg explanation output for a public-safe source/feed fixture, including
optional source ID filtering, missing item/source behavior, nested evidence
and reference arrays, content policy, privacy checks, and MCP wrapper output.
No source/feed CLI surface is added because no dedicated storage CLI
source/feed readback command exists. PSYCOPG42 should evaluate completion of
the source/feed readback migration and decide whether to begin legacy graph
readback migration design, improve connector comparison/helper coverage to
include source/feed operations, improve source/feed connector documentation,
or pause migration for more parity/timing evidence. Legacy readback,
Nix/Bulk/API/domain summaries, ops refresh/status paths, CLI surface changes,
dynamic plugin loading, third-party registration, discovery, refresh, real
graph mutation, ingest/COPY/staging/prepared/pipeline work, generated timing
artifacts, and dependency/package metadata changes remain deferred.

PSYCOPG42 evaluation note: PSYCOPG42 confirms that PSYCOPG41 completed the
final source/feed readback migration by adapting
`query_source_feed_item_explanation` through `execute_json_readback(...)`.
The full source/feed readback surface is now facade-backed, including source
summary, ingested source records, source run records, source feed item records,
source reference records, and source feed item explanation. The overall
facade-backed readback surface now also includes storage summary, canonical
storage summary, canonical node records, canonical edge records, canonical edge
explanation, and canonical neighborhood. PSYCOPG42 records that the nested raw
dictionary explanation contract, `repomap_explain_source_feed_item` MCP
wrapper shape, default Psycopg behavior, explicit `psql` rollback through both
connector selectors, explicit Psycopg selection, conflict-safe selector
behavior, no-fallback semantics, and full-feed-body exclusion remained intact.
The remaining direct `psql` readback areas are legacy graph readback, Nix
summary readback, Bulk/API summary readback, domain summary readback, and
ops/status paths. PSYCOPG42 recommends PSYCOPG43 as a docs-only legacy graph
readback migration design phase to inventory `query_file_records`,
`query_file_node_records`, `query_node_records`, `query_edge_records`,
`query_neighborhood`, `query_file_neighborhood`, and
`query_host_mutator_records`, identify payload shapes, validation behavior,
CLI/MCP surfaces, privacy-sensitive fields, synthetic fixture requirements,
and choose the smallest safe PSYCOPG44 implementation target. Helper expansion
for source/feed operations, source/feed connector documentation, legacy
implementation, Nix/Bulk/API/domain summary migration, ops/status migration,
dynamic plugin loading, third-party registration, discovery, refresh, real
graph mutation, ingest/COPY/staging/prepared/pipeline work, generated timing
artifacts, and dependency/package metadata changes remain deferred.

PSYCOPG43 design note: PSYCOPG43 inventories the legacy graph readback family
still using direct `psql`: `query_file_records`, `query_file_node_records`,
`query_node_records`, `query_edge_records`, `query_neighborhood`,
`query_file_neighborhood`, and `query_host_mutator_records`. The design records
payload shapes, adapter shape expectations, SQL builders, row and JSONable
conversion helpers, CLI surfaces, lack of direct MCP wrappers, validation,
filter, limit, and ordering behavior, privacy-sensitive fields, and
public-safe synthetic fixture requirements. PSYCOPG43 recommends PSYCOPG44 as a
narrow implementation phase for `query_file_records` only, using
`execute_json_readback(...)` with `expected_shape="array"` while preserving SQL
text, `FileRecord` conversion, `records_to_jsonable`, `storage files`, derived
`storage entrypoints`, default Psycopg behavior, explicit `psql` rollback
through both selectors, explicit Psycopg selection, conflict-safe selector
behavior, no-fallback semantics, and CLI payload contracts. File-node, node,
edge, neighborhood, file-neighborhood, host-mutator, Nix/Bulk/API/domain/ops
readback migration, helper expansion, connector documentation, dynamic plugin
loading, third-party registration, discovery, refresh, real graph mutation,
ingest/COPY/staging/prepared/pipeline work, generated timing artifacts, and
dependency/package metadata changes remain deferred.

PSYCOPG44 implementation note: PSYCOPG44 wires only `query_file_records`
through `execute_json_readback(...)` with `expected_shape="array"` while
preserving `build_file_query_sql(root_path)`, root-path scoping, SQL ordering
by file path, `FileRecord` conversion, `records_to_jsonable`, `storage files`
JSON/table output, derived `storage entrypoints` JSON/table output, default
Psycopg behavior, explicit `psql` rollback through both connector selectors,
explicit Psycopg selection, conflict-safe selector behavior, no-fallback
semantics, and CLI payload contracts. Focused unit coverage verifies adapter
call shape, SQL builder use, `psql_args` and `psql_command` pass-through,
label `file records`, `expected_shape="array"`, and adapter-returned
`FileRecord` conversion. Disposable-Postgres parity coverage compares explicit
`psql`, unset-default Psycopg, and explicit Psycopg query output for
public-safe synthetic file records, including deterministic path ordering and
`records_to_jsonable`, and compares compact `storage files --json` and
`storage entrypoints --json` output across explicit `psql` and default
Psycopg. No MCP surface is added because no direct MCP wrapper exists for
`query_file_records`. File-node, node, edge, neighborhood, file-neighborhood,
host-mutator, Nix/Bulk/API/domain/ops readback migration, helper expansion,
connector documentation, dynamic plugin loading, third-party registration,
discovery, refresh, real graph mutation, ingest/COPY/staging/prepared/pipeline
work, generated timing artifacts, and dependency/package metadata changes
remain deferred. PSYCOPG45 should evaluate legacy file record parity and decide
whether to adapt `query_file_node_records`, adapt `query_node_records`, improve
legacy graph fixture coverage, or pause migration for more parity/privacy
evidence.

PSYCOPG45 evaluation note: PSYCOPG45 evaluates PSYCOPG44 legacy file-record
parity and confirms that default Psycopg, explicit Psycopg, and explicit
`psql` parity held for `query_file_records`, file path ordering,
`records_to_jsonable`, `storage files --json`, and derived
`storage entrypoints --json`. The phase records that psql rollback failure
coverage remains explicit by selecting the `psql` connector before exercising
failing synthetic `psql` commands, and that public-safe synthetic file paths
and metadata preserved the privacy boundary. PSYCOPG45 chooses PSYCOPG46 as a
narrow implementation phase for `query_file_node_records` only, using
`execute_json_readback(...)` with `expected_shape="array"` while preserving SQL
text, root-path handling, optional file path filtering, ordering by file path,
node stable key, and evidence stable key, `FileNodeRecord` conversion,
`file_node_records_to_jsonable`, `storage file-nodes` JSON/table output,
default Psycopg behavior, explicit `psql` rollback through both selectors,
explicit Psycopg selection, conflict-safe selector behavior, no-fallback
semantics, and CLI payload contracts. Node, edge, neighborhood,
file-neighborhood, host-mutator, Nix/Bulk/API/domain/ops readback migration,
fixture hardening beyond the file-node slice, helper expansion, connector
documentation, dynamic plugin loading, third-party registration, discovery,
refresh, real graph mutation, ingest/COPY/staging/prepared/pipeline work,
generated timing artifacts, and dependency/package metadata changes remain
deferred.

PSYCOPG46 implementation note: PSYCOPG46 adapts only
`query_file_node_records` through `execute_json_readback(...)` with
`expected_shape="array"`, preserving `build_file_node_query_sql(root_path,
path=path)`, root-path scoping, optional file-path filtering, ordering by file
path, node stable key, and evidence stable key, `FileNodeRecord` conversion,
`file_node_records_to_jsonable`, and `storage file-nodes` JSON/table output.
The phase adds focused unit adapter coverage and disposable-Postgres
connector parity for explicit `psql`, unset-selector default Psycopg, explicit
Psycopg, optional path filtering, file-node JSON projection, and compact
`storage file-nodes --json` parity. It adds no MCP surface, no dependency or
package metadata changes, no SQL/schema/migration changes, no new environment
variables, no additional legacy graph function migration, no dynamic plugin
loading, no ingest/COPY/staging/prepared/pipeline work, and no
discovery/refresh/real graph mutation. PSYCOPG47 should evaluate file-node
parity before selecting a single next legacy graph target or pausing for more
fixture evidence.

PSYCOPG47 evaluation note: PSYCOPG47 confirms that PSYCOPG46 satisfied the
PSYCOPG45 recommendation by adapting only `query_file_node_records` through
`execute_json_readback(...)` while preserving default Psycopg behavior,
explicit `psql` rollback through both selectors, explicit Psycopg selection,
conflict-safe selector behavior, no-fallback semantics, optional file-path
filtering, ordering by file path, node stable key, and evidence stable key,
`FileNodeRecord` conversion, `file_node_records_to_jsonable(...)`, and
`storage file-nodes` JSON/table output. The evaluation records that explicit
`psql`, unset-selector default Psycopg, and explicit Psycopg parity held for
legacy file-node records and compact `storage file-nodes --json` output with
public-safe synthetic paths, node/evidence keys, raw source IDs, extractor
metadata, and line metadata. PSYCOPG47 chooses PSYCOPG48 as a narrow
implementation phase for `query_node_records` only, using
`execute_json_readback(...)` with `expected_shape="array"` while preserving
kind, path, and stable-key filters, ordering by file path, node kind, and node
stable key, `NodeRecord` conversion, `node_records_to_jsonable(...)`,
`storage nodes --legacy` JSON/table output, and canonical default behavior for
`storage nodes` without `--legacy`. The new AGENTS.md opportunistic
test-refactor authorization may be used in PSYCOPG48 only for directly touched
oversized legacy graph tests, with assertions, coverage, pytest discovery,
public-safe fixtures, and final gates preserved. Edge, neighborhood,
file-neighborhood, host-mutator, Nix/Bulk/API/domain/ops readback migration,
test moves in PSYCOPG47, broad fixture refactors, connector documentation,
dynamic plugin loading, third-party registration, discovery, refresh, real
graph mutation, ingest/COPY/staging/prepared/pipeline work, generated timing
artifacts, and dependency/package metadata changes remain deferred.

PSYCOPG48 implementation note: PSYCOPG48 adapts only `query_node_records`
through `execute_json_readback(...)` with `expected_shape="array"` while
preserving `build_node_query_sql(root_path, kind=kind, path=path,
stable_key=stable_key)`, root-path scoping, optional kind, path, and stable-key
filtering, ordering by file path, node kind, and node stable key,
`NodeRecord` conversion, `node_records_to_jsonable(...)`,
`storage nodes --legacy` JSON/table output, and canonical default behavior for
`storage nodes` without `--legacy`. The phase adds focused unit adapter
coverage and disposable-Postgres connector parity for explicit `psql`,
unset-selector default Psycopg, explicit Psycopg, optional kind/path/stable-key
filters, node JSON projection, compact `storage nodes --legacy --json`
parity, and canonical/default `storage nodes --json` preservation. No existing
tests are moved. It adds no MCP surface, no dependency or package metadata
changes, no SQL/schema/migration changes, no new environment variables, no
additional legacy graph function migration, no dynamic plugin loading, no
ingest/COPY/staging/prepared/pipeline work, and no discovery/refresh/real
graph mutation. PSYCOPG49 should evaluate legacy node-record parity before
selecting a single next legacy graph target or pausing for more fixture
evidence.

PSYCOPG49 evaluation note: PSYCOPG49 confirms that PSYCOPG48 satisfied the
PSYCOPG47 recommendation by adapting only `query_node_records` through
`execute_json_readback(...)` while preserving default Psycopg behavior,
explicit `psql` rollback through both selectors, explicit Psycopg selection,
conflict-safe selector behavior, no-fallback semantics, optional kind, path,
and stable-key filtering, ordering by file path, node kind, and node stable
key, `NodeRecord` conversion, `node_records_to_jsonable(...)`,
`storage nodes --legacy` JSON/table output, and canonical/default
`storage nodes --json` behavior. The evaluation records that explicit `psql`,
unset-selector default Psycopg, and explicit Psycopg parity held for legacy
node records and compact `storage nodes --legacy --json` output with
public-safe synthetic paths, node kinds, node names, node stable keys, line
numbers, and metadata. PSYCOPG48 used the AGENTS.md opportunistic
test-refactor authorization conservatively by moving no existing tests, adding
focused pytest-discovered node-record test files, and updating directly
touched rollback tests in place. PSYCOPG49 chooses PSYCOPG50 as a narrow
implementation phase for `query_edge_records` only, using
`execute_json_readback(...)` with `expected_shape="array"` while preserving
kind, source-node, and target-node filters, ordering by edge kind and edge
stable key, `EdgeRecord` conversion, `edge_records_to_jsonable(...)`,
`storage edges --legacy` JSON/table output, and canonical default behavior for
`storage edges` without `--legacy`. Neighborhood, file-neighborhood,
host-mutator, Nix/Bulk/API/domain/ops readback migration, test moves in
PSYCOPG49, broad fixture refactors, connector documentation, dynamic plugin
loading, third-party registration, discovery, refresh, real graph mutation,
ingest/COPY/staging/prepared/pipeline work, generated timing artifacts, and
dependency/package metadata changes remain deferred.

PSYCOPG50 implementation note: PSYCOPG50 adapts only `query_edge_records`
through `execute_json_readback(...)` with `expected_shape="array"` while
preserving `build_edge_query_sql(root_path, kind=kind,
source_node=source_node, target_node=target_node)`, root-path scoping,
optional kind, source-node, and target-node filtering, ordering by edge kind
and edge stable key, `EdgeRecord` conversion,
`edge_records_to_jsonable(...)`, `storage edges --legacy` JSON/table output,
and canonical default behavior for `storage edges` without `--legacy`. The
phase adds focused unit adapter coverage and disposable-Postgres connector
parity for explicit `psql`, unset-selector default Psycopg, explicit Psycopg,
optional kind/source-node/target-node filters, edge JSON projection, compact
`storage edges --legacy --json` parity, and canonical/default
`storage edges --json` preservation. No existing tests are moved. It adds no
MCP surface, no dependency or package metadata changes, no SQL/schema/
migration changes, no new environment variables, no additional legacy graph
function migration, no dynamic plugin loading, no ingest/COPY/staging/
prepared/pipeline work, and no discovery/refresh/real graph mutation.
PSYCOPG51 should evaluate legacy edge-record parity before selecting a single
next legacy graph target or pausing for more fixture evidence.

PSYCOPG51 evaluation note: PSYCOPG51 confirms that PSYCOPG50 satisfied the
PSYCOPG49 recommendation by adapting only `query_edge_records` through
`execute_json_readback(...)` while preserving default Psycopg behavior,
explicit `psql` rollback through both selectors, explicit Psycopg selection,
conflict-safe selector behavior, no-fallback semantics, optional kind,
source-node, and target-node filtering, ordering by edge kind and edge stable
key, `EdgeRecord` conversion, `edge_records_to_jsonable(...)`,
`storage edges --legacy` JSON/table output, and canonical/default
`storage edges --json` behavior. The evaluation records that explicit `psql`,
unset-selector default Psycopg, and explicit Psycopg parity held for legacy
edge records and compact `storage edges --legacy --json` output with
public-safe synthetic paths, node keys, edge keys, evidence keys, line
numbers, extractor names, and metadata. PSYCOPG50 used the AGENTS.md
opportunistic test-refactor authorization conservatively by moving no existing
tests, adding focused pytest-discovered edge-record test files, and updating
directly touched rollback tests in place. PSYCOPG51 chooses PSYCOPG52 as a
narrow implementation phase for `query_neighborhood` only, using
`execute_json_readback(...)` with `expected_shape="object"` while preserving
required node behavior, direction behavior for `in`, `out`, and `both`,
depth-1 validation, nested center/nodes/edges shape, nested node and edge
ordering, `NeighborhoodRecord` conversion, `neighborhood_to_jsonable(...)`,
`storage neighborhood --legacy` JSON/table output, and canonical default
behavior for `storage neighborhood` without `--legacy`. File-neighborhood,
host-mutator, Nix/Bulk/API/domain/ops readback migration, test moves in
PSYCOPG51, broad fixture refactors, connector documentation, dynamic plugin
loading, third-party registration, discovery, refresh, real graph mutation,
ingest/COPY/staging/prepared/pipeline work, generated timing artifacts, and
dependency/package metadata changes remain deferred.

PSYCOPG52 implementation note: PSYCOPG52 adapts only `query_neighborhood`
through `execute_json_readback(...)` with `expected_shape="object"` while
preserving `build_neighborhood_query_sql(root_path, node=node,
direction=direction)`, root-path scoping, required node behavior, direction
behavior for `in`, `out`, and `both`, depth-1 validation, nested
center/nodes/edges shape, missing-center payloads, nested node and edge
ordering, `NeighborhoodRecord` conversion, `neighborhood_to_jsonable(...)`,
`storage neighborhood --legacy` JSON/table output, and canonical default
behavior for `storage neighborhood` without `--legacy`. The phase adds
focused unit adapter coverage and disposable-Postgres connector parity for
explicit `psql`, unset-selector default Psycopg, explicit Psycopg, direction
behavior, depth handling, missing-center behavior, neighborhood JSON
projection, compact `storage neighborhood --legacy --json` parity, and
canonical/default `storage neighborhood --json` preservation. No existing
tests are moved. It adds no MCP surface, does not change MCP
`repomap_neighborhood`, and makes no dependency or package metadata changes,
SQL/schema/migration changes, new environment variables, additional legacy
graph function migrations, dynamic plugin loading, ingest/COPY/staging/
prepared/pipeline work, or discovery/refresh/real graph mutation. PSYCOPG53
should evaluate legacy neighborhood parity before selecting a single next
legacy graph target or pausing for more fixture evidence.

PSYCOPG53 evaluation note: PSYCOPG53 confirms that PSYCOPG52 satisfied the
PSYCOPG51 recommendation by adapting only `query_neighborhood` through
`execute_json_readback(...)` while preserving default Psycopg, explicit
Psycopg, explicit `psql`, direction behavior for `in`, `out`, and `both`,
depth-1 behavior and unsupported-depth rejection, missing-center behavior,
nested node and edge ordering, `NeighborhoodRecord` conversion,
`neighborhood_to_jsonable(...)`, compact
`storage neighborhood --legacy --json` parity, and canonical/default
`storage neighborhood --json` behavior. Public-safe paths, node keys, edge
keys, evidence keys, line numbers, extractor names, and metadata preserved the
privacy boundary. No existing tests were moved; the focused integration file
is scoped correctly but remains in the file-length warning band. PSYCOPG53
chooses PSYCOPG54 as a narrow implementation phase for
`query_file_neighborhood` only, using `expected_shape="object"` and focused
public-safe parity for the returned path, multiple centers, nested nodes and
edges, all directions, depth validation, missing-file or empty-center behavior,
ordering, JSON projection, and compact legacy CLI JSON output. Host-mutator,
Nix/Bulk/API/domain/ops migration, broad fixture or test reorganization,
dependency or environment changes, SQL/parser/payload/CLI/MCP changes,
runner/control-plane integration, discovery, refresh, live smoke, and real
graph mutation remain deferred.

PSYCOPG54 implementation note: PSYCOPG54 adapts only
`query_file_neighborhood` through `execute_json_readback(...)` with
`expected_shape="object"` while preserving root/path scoping, required
repo-relative path behavior, the returned path, direction behavior for `in`,
`out`, and `both`, depth-1 validation, missing-file empty arrays, nested
path/centers/nodes/edges shape, deterministic center/node/edge ordering,
`FileNeighborhoodRecord` conversion, `file_neighborhood_to_jsonable(...)`,
legacy CLI JSON/table output, and canonical/default CLI behavior. Focused unit
tests prove the adapter call and conversion boundary. Disposable-Postgres
coverage proves equivalent default Psycopg, explicit Psycopg, and explicit
`psql` output through both selectors, including compact
`storage file-neighborhood --legacy --json` parity and public-safe synthetic
fields. No tests are moved. No MCP surface, dependency/package metadata,
environment variable, SQL/schema/migration, parser/payload, runner/control-plane,
discovery/refresh, or real graph behavior changes are included. PSYCOPG55
should evaluate file-neighborhood parity before choosing host-mutator migration,
fixture/privacy work, broader legacy graph fixture work, or a migration pause.

PSYCOPG55 evaluation note: PSYCOPG55 confirms that PSYCOPG54 satisfied the
PSYCOPG53 recommendation. Default Psycopg, explicit Psycopg, and explicit
`psql` parity held through both selector surfaces for all directions, depth 1,
unsupported-depth rejection, missing-file output, deterministic center/node/edge
ordering, JSON projection, legacy CLI JSON, and canonical/default behavior.
The focused PSYCOPG54 unit and integration files remain within the file-length
profile's pass band. Existing public-safe host-mutator unit, CLI, and
disposable-Postgres fixtures adequately cover record fields, category/tool
filters, privilege state, arguments, summary projection, and canonical/default
separation. PSYCOPG55 therefore recommends PSYCOPG56 adapt only
`query_host_mutator_records` through `execute_json_readback(...)` with
`expected_shape="array"`, connector parity through both selectors, compact
legacy record and summary CLI JSON parity where practical, and no new CLI or
MCP surface. Broader fixture reorganization, other readback families,
dependency or environment changes, runner/control-plane integration,
discovery, refresh, and real graph mutation remain deferred.

PSYCOPG56 implementation note: PSYCOPG56 adapts only
`query_host_mutator_records` through `execute_json_readback(...)` with
`expected_shape="array"` while preserving repository-root scoping, optional
category/tool filters, path/line/name ordering, the exact eleven-field
`HostMutatorRecord` contract, record and summary JSON projections, both legacy
CLI command families, and both canonical defaults. Focused unit coverage proves
the adapter call, conversion, empty-array behavior, and absence of a direct
psql call. Disposable-Postgres coverage proves equivalent explicit `psql`,
unset-default Psycopg, and explicit Psycopg output through both selectors,
including record and summary CLI JSON parity on public-safe synthetic fields.
No tests are moved, and both new focused files remain within the file-length
pass band. No MCP surface, dependency/package metadata, environment variable,
SQL/schema/migration, non-legacy readback, runner/control-plane,
discovery/refresh, or real graph behavior change is included. PSYCOPG57 should
evaluate host-mutator parity and the legacy graph migration completion state
before selecting any later readback family or pause.

PSYCOPG57 evaluation note: PSYCOPG57 confirms that PSYCOPG56 satisfied the
PSYCOPG55 recommendation. Default Psycopg, explicit Psycopg, and explicit
`psql` parity held through both selector surfaces for unfiltered,
category-only, tool-only, and combined filtering; deterministic path/line/name
ordering; both privilege states; the exact eleven-field record contract;
record and summary projections; both legacy CLI JSON commands; and both
canonical defaults. Public-safe synthetic paths, commands, targets, reasons,
arguments, and metadata preserved the privacy boundary. No tests were moved;
the new 157-line unit and 400-line integration files remain in the file-length
pass band. All seven legacy graph readback functions are now facade-backed, so
PSYCOPG57 declares that migration complete and recommends a docs-only
PSYCOPG58 completion closeout. The connector helper currently omits the legacy
family, but focused disposable-Postgres parity makes that a bounded
post-closeout strategy candidate rather than a completion blocker. Non-legacy
readback implementation, dependency or environment changes, runner/control-
plane integration, discovery, refresh, and real graph mutation remain
deferred.

PSYCOPG58 completion note: PSYCOPG58 formally closes the seven-function legacy
graph readback migration and inventories 19 facade-backed operations across
core/canonical, source/feed, and legacy graph families. It preserves the
default Psycopg, explicit rollback through both selectors, conflict-safe and
no-fallback connector policy, all legacy CLI contracts, canonical defaults,
public-safe fixture boundaries, and current test/file-length evidence. Current
direct psql use is classified into pure typed summaries, hybrid Bulk/API
summaries, operational/status and MCP search, and deliberate migration/load/
write paths rather than one mechanical backlog. The connector helper still
covers five operations and omits canonical neighborhood, source/feed, and the
legacy family. PSYCOPG58 selects PSYCOPG59 as a bounded helper expansion for
legacy file, file-node, node, and edge record operations only. That subset can
reuse the existing synthetic fixture, increases the one-iteration comparison
matrix from 10 to 18 aggregate rows, and defers nested neighborhoods,
host-mutators, non-legacy summaries, ops/status, dependency or environment
changes, runner/control-plane integration, discovery, refresh, and real graph
mutation.

PSYCOPG59 implementation note: PSYCOPG59 adds exactly four foundational legacy
list readbacks to `tools/compare_pg_connectors.py`: file records, file-node
records, node records, and edge records. The helper reuses its existing four-
observation public-safe disposable-Postgres fixture, applies each established
public JSON projection, and compares complete projected payloads through psql
and Psycopg. The deterministic matrix now contains nine operations and emits 18
bounded aggregate rows at one iteration; the real helper run reported parity
for every row without emitting raw payloads. Focused unit and integration
coverage preserves operation and connector ordering, mismatch diagnostics,
timing and report semantics, privacy validation, and generated-output policy.
No tests were moved. Nested neighborhoods, host-mutators, source/feed and non-
legacy summaries, dependencies, environment variables, connector defaults,
CLI/MCP behavior, and runner/control-plane integration remain deferred.
PSYCOPG60 should evaluate this bounded expansion before selecting one further
helper subset or a docs-only non-legacy readback strategy.

PSYCOPG60 evaluation note: PSYCOPG60 confirms that PSYCOPG59 added exactly the
approved four legacy list readbacks and preserved the deterministic nine-
operation, connector-major matrix, complete projected-payload equality, 18-row
one-iteration parity, non-empty synthetic results, bounded aggregate output,
privacy validation, diagnostic-only role, and unchanged four-observation
fixture. The helper now provides useful consolidated parity evidence without
replacing focused integration coverage. At 628 lines it is in the repository
warning band; growth is concentrated in the 108-line operation factory, but no
immediate refactor is warranted while expansion stops. PSYCOPG60 selects Option
D. PSYCOPG61 should be a docs-only design phase for `query_nix_summary(...)`
only, covering its object-shaped typed contract, SQL builder, projections,
CLI/MCP consumers, fixtures, privacy fields, and future connector parity scope.
Canonical and legacy neighborhoods, source/feed and host-mutator helper
coverage, helper refactoring, all implementation, dependencies, environment
changes, discovery/refresh, real graph mutation, and runner/control-plane
integration remain deferred.

PSYCOPG61 design note: PSYCOPG61 confirms that `query_nix_summary(...)` is a
pure direct-psql, object-shaped typed readback using
`build_nix_summary_query_sql(root_path)`, the fixed `nix summary` parse label,
`nix_summary_from_storage_payload(...)`, and the 18-field frozen
`NixSummaryRecord` projection. The contract is count-only and path-free, with
fixed nested count, diagnostic, limitation, and safety maps; an unknown root
still returns a complete zero/default object. `storage nix-summary` exposes
JSON and table output without canonical/legacy modes, and the direct
`repomap_nix_summary(graph_id=...)` MCP wrapper requires later parity coverage.
Existing public-safe unit and disposable-Postgres fixtures already cover all
nested field families, CLI/MCP output, and public/private sanitization. The
remaining gaps are focused adapter, selector parity, empty-object, and
malformed nested-field tests. PSYCOPG61 selects Option A: PSYCOPG62 should
adapt only `query_nix_summary(...)` through `execute_json_readback(...)` with
`expected_shape="object"`, preserving SQL, the exact payload, CLI/MCP behavior,
and privacy boundaries. Other summaries, helper work, dependencies,
environment changes, discovery/refresh, real graph mutation, and runner/
control-plane integration remain deferred.

PSYCOPG62 implementation note: PSYCOPG62 adapts only
`query_nix_summary(...)` through `execute_json_readback(...)` with
`expected_shape="object"`. The exact SQL builder, 18-field typed contract,
nested normalization and validation, unknown-root defaults, CLI JSON/table
behavior, direct MCP wrapper, public/private root sanitization, and privacy
boundaries remain unchanged. Focused adapter tests and disposable-Postgres
coverage prove complete direct, JSONable, CLI, and MCP parity for default
Psycopg and explicit psql, including both selector surfaces; no existing tests
were moved. PSYCOPG63 should be a docs-only Nix parity evaluation before any
other summary migration. Helper expansion, other summaries, dependencies,
environment changes, discovery/refresh, real graph mutation, and runner/
control-plane integration remain deferred.

PSYCOPG63 evaluation note: PSYCOPG63 confirms that PSYCOPG62 satisfies the
PSYCOPG61 design and declares the Nix summary connector migration complete.
The exact object adapter, 18-field contract, fixed nested maps, unknown-root
defaults, malformed conversion failures, both selector surfaces, invalid-psql
Psycopg proof, CLI JSON/table behavior, direct MCP wrapper, root sanitization,
and count-only privacy boundary remain intact. Focused tests stay in the pass
band; the existing 800-line Nix unit file remains warning-band but below the
failure threshold. After inventorying the seven remaining direct-psql typed
summaries, PSYCOPG63 selects Option A: PSYCOPG64 should be a docs-only design
phase for `query_ruby_summary(...)` only. Ruby has one sorted count map,
otherwise scalar counts and one safety boolean, mature public-safe direct/CLI
fixtures, no direct MCP wrapper, and lower coupling/privacy risk than the
remaining candidates. Implementation, other summaries, Bulk/API hybrids,
helper work, dependencies, environment changes, discovery/refresh, real graph
mutation, and runner/control-plane integration remain deferred.

PSYCOPG64 design note: PSYCOPG64 confirms that `query_ruby_summary(...)` is a
pure direct-psql, object-shaped readback using
`build_ruby_summary_query_sql(root_path)`, the fixed `ruby summary` label, and
the 20-field frozen `RubySummaryRecord`. The contract preserves root and
repository identity, 16 scalar counts, a required arbitrary-label count map
with deterministic key sorting, and the strict `no_execution` boolean. Unknown
or Ruby-empty roots still produce complete default objects. `storage
ruby-summary` has stable JSON/table/error behavior, while neither the dedicated
MCP tools nor the generic summary router exposes Ruby. The public-safe
`ruby_basic` fixture is sufficient for complete connector parity; focused new
test files can avoid growing the existing 480-line unit and 418-line
integration warning-band files. PSYCOPG64 selects Option A: PSYCOPG65 should
adapt only `query_ruby_summary(...)` through `execute_json_readback(...)` with
`expected_shape="object"`, preserving the exact SQL, typed conversion, CLI,
absence of MCP exposure, and existing path/profile privacy boundary. Other
summaries, Bulk/API hybrids, helper work, dependencies, environment changes,
discovery/refresh, real graph mutation, and runner/control-plane integration
remain deferred.

PSYCOPG65 implementation note: PSYCOPG65 adapts only
`query_ruby_summary(...)` through `execute_json_readback(...)` with the exact
Ruby SQL builder, fixed label, and object shape. The complete ordered 20-field
record, scalar `int(...)` coercion, arbitrary sorted profile counts, strict
`no_execution`, unknown-root and Ruby-empty defaults, direct and JSONable
projections, CLI JSON/table/error behavior, and established path-bearing
identity boundary remain unchanged. Complete payload parity passed through
unset-selector Psycopg and explicit psql/Psycopg on both selector surfaces;
invalid psql executables proved the Psycopg modes, and Ruby remains absent from
MCP. Focused unit and disposable-Postgres tests are in new pass-band files; no
existing test moved, the helper was not expanded, and dependencies,
environment, fixtures, SQL, schemas, migrations, discovery/refresh, live
graphs, and runner/control-plane repositories remain untouched. PSYCOPG66
should be a docs-only Ruby summary parity evaluation before another summary
migration.

PSYCOPG66 evaluation note: PSYCOPG65 satisfies the PSYCOPG64 design and the
Ruby summary connector migration is complete. Current source and focused
evidence preserve the exact object-shaped adapter call, complete ordered
20-field record, scalar coercion, arbitrary sorted profile labels, strict
`no_execution`, unknown-root and Ruby-empty defaults, CLI behavior, aggregate
privacy boundary, and absence of Ruby MCP exposure. Complete parity covers
default Psycopg and explicit psql/Psycopg through both selector surfaces, with
invalid psql executables proving the Psycopg modes. The focused 255-line unit
and 258-line integration files are pass band; existing 484-line shared unit
and 418-line language integration files remain warning band without requiring
immediate reorganization. PSYCOPG66 selects Option A: PSYCOPG67 should be a
docs-only design phase for only `query_js_summary(...)`, whose current flat
scalar-count, arbitrary profile-map, strict safety, public-safe fixture, CLI,
and non-MCP structure remains the smallest bounded follow-on. No source, test,
fixture, dependency, environment, helper, runner, or control-plane change is
included.

PSYCOPG67 design note: PSYCOPG67 confirms that `query_js_summary(...)` is a
pure direct-psql readback using `build_js_summary_query_sql(root_path)`, the
fixed `js summary` label, and one unconditional top-level object. The frozen
`JSSummaryRecord` has exactly 25 ordered fields: root and repository identity,
21 scalar counts converted through `int(...)`, an arbitrary-label count map
with deterministic lexical sorting, and strict scalar `no_execution`. Unknown
roots and JavaScript-empty repositories retain complete default objects.
`storage js-summary` preserves stable JSON/table/error behavior, while plain
JavaScript remains absent from dedicated and generic MCP summary routes. The
public-safe `js_basic` fixtures are sufficient for complete connector parity;
focused new pass-band unit and integration files should avoid enlarging the
existing 484-line shared unit and 418-line integration warning-band files.
PSYCOPG67 selects Option A: PSYCOPG68 should adapt only
`query_js_summary(...)` through `execute_json_readback(...)` with
`expected_shape="object"`, preserving exact SQL, conversion, projection, CLI,
non-MCP behavior, profile semantics, and the established identity/count-only
privacy boundary. Other summaries, helper work, dependencies, environment
changes, discovery/refresh, live graphs, and runner/control-plane integration
remain deferred.

PSYCOPG68 implementation note: PSYCOPG68 adapts only
`query_js_summary(...)` through `execute_json_readback(...)` with the exact
JavaScript SQL builder, fixed label, and object shape. The complete ordered
25-field record, scalar `int(...)` coercion, arbitrary sorted profile counts,
strict `no_execution`, unknown-root and JavaScript-empty defaults, direct and
JSONable projections, CLI JSON/table/error behavior, and established
path-bearing identity boundary remain unchanged. Complete payload parity
passed through unset-selector Psycopg and explicit psql/Psycopg on both
selector surfaces; invalid psql executables proved the Psycopg modes, and
plain JavaScript remains absent from MCP. Focused unit and disposable-Postgres
tests are in new pass-band files; no existing test moved or warning-band file
grew, the helper was not expanded, and dependencies, environment, fixtures,
SQL, schemas, migrations, discovery/refresh, live graphs, and runner/control-
plane repositories remain untouched. PSYCOPG69 should be a docs-only
JavaScript summary parity evaluation before another summary migration.

PSYCOPG69 evaluation note: PSYCOPG68 satisfies the PSYCOPG67 design, and the
plain JavaScript connector migration is complete. Current source and focused
evidence preserve the exact object-shaped adapter call, ordered 25-field
record, scalar `int(...)` coercion, arbitrary sorted profile labels, strict
`no_execution`, ignored extra fields, unknown-root and JavaScript-empty
defaults, CLI behavior, identity/profile privacy boundary, and absence of a
plain-JavaScript MCP route. Complete parity covers default Psycopg and explicit
psql/Psycopg through both selectors, with invalid psql executables proving the
Psycopg modes; JavaScript-framework MCP routing remains separate and
unchanged. The focused 301-line unit and 286-line integration files are pass
band; no existing test moved or warning-band file grew. PSYCOPG69 selects
Option A: PSYCOPG70 should be a docs-only design phase for only
`query_js_framework_summary(...)`, whose mature dedicated fixture, exact
13-field fixed-map contract, CLI coverage, direct MCP route, graph routing,
and private-root sanitization evidence support a bounded design. No source,
test, fixture, dependency, environment, helper, runner, or control-plane
change is included.

PSYCOPG70 design note: PSYCOPG70 confirms that
`query_js_framework_summary(...)` is a pure direct-psql database readback using
`build_js_framework_summary_query_sql(root_path)`, the fixed
`js framework summary` label, and one unconditional top-level object. The
frozen record has exactly 13 ordered fields: root/name identity, one scalar
count, nine required fixed count maps containing 41 required count slots, and
one four-Boolean safety map. Unknown roots and framework-empty repositories
retain complete zero/true objects; fixed-map conversion, extra-key behavior,
CLI JSON/table/errors, the direct MCP wrapper, generic-router graph selection,
operational psql/container routing, and public/private root sanitization are
fully inventoried. The mature public-safe `js5_frameworks` fixture is
sufficient for complete connector, CLI, MCP, and privacy parity; synthetic
unit payloads should cover defaults and malformed maps. PSYCOPG70 selects
Option A: PSYCOPG71 should adapt only `query_js_framework_summary(...)`
through `execute_json_readback(...)` with `expected_shape="object"`, using new
focused pass-band unit and integration files rather than enlarging current
warning-band or near-threshold tests. No source, test, fixture, dependency,
environment, helper, runner, or control-plane change is included.

PSYCOPG71 implementation note: PSYCOPG71 adapts only
`query_js_framework_summary(...)` through `execute_json_readback(...)` with
the unchanged SQL builder, `js framework summary` label, and object shape. It
preserves the exact ordered 13-field record, nine fixed count maps with 41
required count slots, four-Boolean safety map, scalar and nested coercion,
unknown-root and framework-empty defaults, CLI JSON/table/error behavior,
direct MCP wrapper, configured routing, and public/private root sanitization.
Focused pass-band unit and integration files prove complete parity through both
selector surfaces, invalid-psql avoidance in Psycopg modes, CLI equality,
public/private MCP equality, and the aggregate privacy boundary; no existing
test moved and the connector helper was not expanded. PSYCOPG72 should be a
docs-only JavaScript framework parity evaluation that confirms completion and
selects exactly one next summary-migration strategy without moving another
summary.

PSYCOPG72 evaluation note: PSYCOPG71 satisfies the PSYCOPG70 design, and the
JavaScript framework connector migration is complete. Current source and
focused evidence preserve the exact object adapter, ordered 13-field record,
nine fixed count maps with 41 required slots, four-Boolean safety map, scalar
and nested coercion, extra-key behavior, unknown-root and framework-empty
defaults, CLI JSON/table/errors, direct MCP and generic routing, operational-
routing distinction, public/private root sanitization, and aggregate privacy
boundary. Complete parity covers default Psycopg and explicit psql/Psycopg
through both selector surfaces, with invalid executables proving the Psycopg
modes. The focused 321-line unit and 393-line integration files remain pass
band; no existing test moved or weakened. PSYCOPG72 selects Option A:
PSYCOPG73 should be a docs-only design phase for only
`query_openapi_summary(...)`, whose pure 12-field object contract, seven fixed
count maps, five-Boolean safety map, mature fixture, CLI/direct-MCP coverage,
and established privacy sanitization support a bounded next design. No source,
test, fixture, dependency, environment, helper, runner, or control-plane
change is included.

PSYCOPG73 design note: PSYCOPG73 confirms that
`query_openapi_summary(...)` is a pure direct-psql database readback using
`build_openapi_summary_query_sql(root_path)`, the fixed `openapi summary`
label, and one unconditional top-level object. The frozen record has exactly
12 ordered fields: root/name identity, two scalar counts, seven fixed count
maps containing 41 required count slots, and one five-Boolean safety map.
Unknown roots produce complete zero/true objects; an OpenAPI-empty existing
repository retains its name and may retain repository-wide `generic_config`
or OpenAPI-specific generic parse-error counts. Fixed-map conversion, scalar
coercion, extra-key behavior, CLI JSON/table/errors, the direct MCP wrapper,
generic-router graph selection,
operational psql/container routing, and public/private root sanitization are
fully inventoried. The mature public-safe OpenAPI 3, Swagger 2, and malformed-
document fixture family is sufficient for connector, CLI, MCP, and privacy
parity; synthetic unit payloads should cover malformed/default boundaries.
PSYCOPG73 selects Option A: PSYCOPG74 should adapt only
`query_openapi_summary(...)` through `execute_json_readback(...)` with
`expected_shape="object"`, using new focused pass-band unit and integration
files rather than enlarging current warning-band or near-threshold tests. No
source, test, fixture, dependency, environment, helper, runner, or control-
plane change is included.

PSYCOPG74 implementation note: PSYCOPG74 adapts only
`query_openapi_summary(...)` through `execute_json_readback(...)` with the
unchanged SQL builder, `openapi summary` label, object shape, and typed
converter. Complete parity preserves all 12 fields, seven fixed count maps and
41 required slots, five-Boolean safety map, scalar and nested coercion,
unknown-root and OpenAPI-empty behavior, CLI JSON/table/errors, direct and
generic MCP routing, configured graph selection, public/private root handling,
recursive sanitization, and the operational-routing boundary. Focused
pass-band unit and integration files cover both selector surfaces, invalid-
psql Psycopg proof, complete CLI and public/private MCP parity, malformed and
extra-key behavior, and aggregate-only privacy assertions. PSYCOPG75 should be
a docs-only OpenAPI summary parity evaluation that confirms completion and
selects exactly one next summary-migration direction.

PSYCOPG75 evaluation note: PSYCOPG75 confirms that PSYCOPG74 satisfies the
PSYCOPG73 design and declares the OpenAPI summary connector migration
complete. Evidence preserves the exact object adapter, 12 fields, seven fixed
count maps and 41 slots, five-Boolean safety map, scalar and extra-key
semantics, unknown-root and OpenAPI-empty behavior, CLI parity, direct/generic
MCP routing, public/private root handling, keyed MCP redaction, operational-
routing separation, privacy boundary, and focused pass-band test placement.
The remaining pure typed candidates are Terraform, Python, and email.
PSYCOPG75 selects Terraform as the smallest bounded next target because its
12-field object, mixed three-key `tfvars` map, nine-Boolean safety map, direct
MCP route, and HCL/TFJSON fixtures are explicit and mature. PSYCOPG76 should be
a docs-only design phase for only `query_terraform_summary(...)`; it must not
implement another summary migration.

PSYCOPG76 design note: PSYCOPG76 confirms that
`query_terraform_summary(...)` is a pure direct-psql database readback using
`build_terraform_summary_query_sql(root_path)`, the fixed `terraform summary`
label, and one unconditional top-level object. The frozen record has exactly
12 ordered fields: root/name identity, two scalar counts, six fixed count maps
containing 40 required slots, one mixed three-key `tfvars` map, and one nine-
Boolean safety map. Unknown roots produce complete zero/false/true objects;
Terraform-empty repositories retain stored identity and may retain repository-
wide `generic_config` counts. Fixed-map validation, mixed-map extra-key
behavior, scalar coercion, CLI JSON/table/errors, direct and generic MCP
routing, operational psql/container selection, public/private root handling,
and keyed sanitization are fully inventoried. Mature public-safe HCL and TFJSON
fixtures are sufficient for connector, CLI, MCP, and privacy parity.
PSYCOPG76 selects Option A: PSYCOPG77 should adapt only
`query_terraform_summary(...)` through `execute_json_readback(...)` with
`expected_shape="object"`, using new focused unit and integration files rather
than enlarging current warning-band tests. No source, test, fixture,
dependency, environment, helper, runner, or control-plane change is included.

PSYCOPG77 implementation note: PSYCOPG77 adapts only
`query_terraform_summary(...)` through `execute_json_readback(...)` with the
unchanged SQL builder, `terraform summary` label, object shape, and typed
converter. Complete parity preserves all 12 fields, six fixed count maps and
40 required slots, the ordered mixed `tfvars` map, the nine-Boolean safety
map, scalar and nested coercion, unknown-root and Terraform-empty behavior,
CLI JSON/table/errors, direct and generic MCP routing, public/private root
handling, keyed MCP redaction, and the operational-routing boundary. Focused
unit and integration files cover both selector surfaces, invalid-psql Psycopg
proof, HCL/TFJSON payloads, complete CLI and public/private MCP parity,
malformed and extra-key behavior, and aggregate-only privacy assertions.
PSYCOPG78 should be a docs-only Terraform summary parity evaluation that
confirms completion and selects exactly one next summary direction or pause.

PSYCOPG78 evaluation note: PSYCOPG78 confirms that PSYCOPG77 satisfies the
PSYCOPG76 design and declares the Terraform summary connector migration
complete. Default Psycopg and explicit psql/Psycopg match through both
selectors for complete HCL and TFJSON records, preserving all 12 fields, six
fixed maps and 40 slots, mixed `tfvars`, nine safety Booleans, defaults,
malformed behavior, CLI, direct/generic MCP routing, sanitization, operational
routing, and aggregate-only privacy. The 646-line focused integration file is
localized warning-band debt rather than a blocker, and the ignored
`node_modules` sentinels remain a separate fixture-policy concern. PSYCOPG78
selects Option A: PSYCOPG79 should be a docs-only design for only
`query_python_summary(...)`; it must not migrate another summary.

PSYCOPG79 design note: PSYCOPG79 confirms that `query_python_summary(...)` is
a pure unconditional object-shaped database readback with an exact 14-field
record, one scalar count, nine fixed maps and 49 required slots, a fixed
three-Boolean dogfooding map, and a fixed nine-Boolean safety map. The design
inventories unknown-root and Python-empty behavior, permissive count coercion,
malformed and extra-key handling, CLI JSON/table/errors, direct and generic MCP
routing, configured operational routing, private-root handling, keyed
redaction of `credentialed_urls` and `secret_like_config`, mature Python
fixtures, aggregate-only privacy, and warning-band test pressure. PSYCOPG79
selects Option A: PSYCOPG80 should adapt only `query_python_summary(...)`
through `execute_json_readback(...)` using new focused unit and integration
files; no implementation, fixture, source, test, dependency, runner, or
control-plane change is included here.

PSYCOPG80 implementation note: PSYCOPG80 adapts only
`query_python_summary(...)` through `execute_json_readback(...)` with the
unchanged SQL builder, `python summary` label, object shape, and typed
converter. Complete parity preserves all 14 fields, the scalar coercion
contract, nine fixed count maps and 49 required slots, the ordered three-
Boolean dogfooding map, the nine-Boolean safety map, unknown-root and Python-
empty behavior, CLI JSON/table/errors, direct and generic MCP routing,
public/private root handling, keyed MCP redaction, aggregate-only privacy,
and the operational-routing boundary. Focused unit and integration files
cover both selector surfaces, invalid-psql Psycopg proof, complete CLI and
public/private MCP parity, malformed and extra-key behavior, mature Python
fixture anchors, and privacy exclusions. PSYCOPG81 should be a docs-only
Python summary parity evaluation that confirms completion and selects exactly
one next pure-summary, hybrid-summary, or pause direction.

PSYCOPG81 evaluation note: PSYCOPG81 confirms that PSYCOPG80 satisfies the
PSYCOPG79 design and declares the Python summary connector migration complete.
Default Psycopg and explicit psql/Psycopg match through both selectors for the
complete 14-field payload, preserving one scalar count, nine fixed maps and 49
slots, three dogfooding Booleans, nine safety Booleans, defaults, malformed and
extra-key behavior, CLI, direct/generic MCP routing, keyed redaction,
operational-routing separation, and aggregate-only privacy. The 754-line
focused integration file is cohesive localized warning-band debt, not a
blocker, and does not require an immediate split. Email is the final pure typed
summary: its unconditional 31-field object, 25 scalar counts, four strict
Booleans, CLI, mature EML/mbox fixtures, and privacy boundary are explicit,
while Bulk/API remain database-plus-manifest hybrids. PSYCOPG81 selects Option
A: PSYCOPG82 should be a docs-only design for only
`query_email_summary(...)`; it must not migrate email or begin hybrid work.

PSYCOPG82 design note: PSYCOPG82 inventories the final pure typed summary's
exact direct-psql implementation, unconditional object shape, ordered
31-field record, 25 permissive scalar counts, four strict scalar Booleans,
identity, unknown-root and email-empty defaults, malformed and extra-field
behavior, CLI surface, complete MCP non-exposure, aggregate-only privacy
boundary, mature email fixtures, and focused test placement. It selects Option
A: PSYCOPG83 should adapt only `query_email_summary(...)` through
`execute_json_readback(...)`, add focused connector and CLI parity coverage,
and preserve all existing SQL, record, projection, CLI, MCP-absence, and
privacy contracts. PSYCOPG82 is docs-only and does not begin Bulk or API
hybrid work.

PSYCOPG83 implementation note: PSYCOPG83 adapts only
`query_email_summary(...)` through `execute_json_readback(...)` with the exact
object shape, SQL builder, label, converter, ordered 31-field projection, 25
permissive counts, four strict Booleans, identity, defaults, CLI, MCP absence,
and aggregate-only privacy boundary preserved. Focused unit and disposable-
PostgreSQL tests prove default Psycopg and explicit psql/Psycopg parity through
both selectors, invalid-psql isolation for Psycopg modes, complete CLI JSON
parity, meaningful EML/mbox evidence, and a nonzero mailbox-limit count.
PSYCOPG84 should perform a docs-only email parity evaluation and choose one
next pure-to-hybrid direction without beginning hybrid implementation.

PSYCOPG84 evaluation note: PSYCOPG84 declares the email migration complete and
closes the 27-member pure typed-summary/readback family: every current pure
database readback now uses `execute_json_readback(...)`, with no missed pure
direct-psql owner. Remaining direct psql belongs to Bulk/API hybrids,
write/load/migration, operational status and refresh, MCP search, or the psql
connector implementation itself. Bulk and API share sorted contained manifest
discovery and database-over-manifest assembly but diverge in redaction merge,
nested request/response aggregation, safety folding, privacy, and fixtures.
PSYCOPG84 selects Option A: PSYCOPG85 should assess the pure-to-hybrid
transition, define the complete parity unit, and choose one first hybrid design
target without changing source, tests, fixtures, helpers, Bulk, or API.

PSYCOPG85 transition note: PSYCOPG85 selects full-function parity as the
authoritative hybrid model: the production edit may change only database
transport, but connector comparisons must cover unchanged manifest discovery,
diagnostics, aggregation, merge precedence, the complete typed record, CLI,
and privacy. It preserves the current order in which database execution,
decoding, and object shape precede filesystem access while database field
conversion follows manifest aggregation. Exact manifest-reader duplication is
deferred until both hybrid migrations have parity baselines; no shared
framework is justified. Bulk is selected as the first target because its flat
manifest model, fixed safety values, narrower privacy surface, and mature
fixtures make it lower risk than API despite its maximum-based redaction merge.
PSYCOPG86 should be a docs-only complete Bulk hybrid readback design.

PSYCOPG86 design note: PSYCOPG86 selects Option A and defines
`query_bulk_summary(...)` as the complete parity unit even though PSYCOPG87's
production edit should replace only its three-field database transport with an
object-shaped `execute_json_readback(...)` call. The design preserves database-
before-filesystem execution and post-manifest database-field conversion,
resolved `.repomap/bulk-runs` discovery, containment diagnostics, tolerant
normalization, the exact 28-field record, maximum-based `raw_observations`
redaction reconciliation, CLI behavior, MCP absence, and the explicit privacy
boundary. Existing fixtures plus temporary public-safe manifests are
sufficient; no helper extraction or fixture/privacy phase is required first.
PSYCOPG87 should implement only the Bulk adapter and prove complete default-
Psycopg and explicit psql/Psycopg full-function parity through both selectors,
without altering API or beginning shared-reader work.

PSYCOPG87 implementation note: PSYCOPG87 adapts only the database transport
inside `query_bulk_summary(...)` through object-shaped
`execute_json_readback(...)` while preserving database-before-filesystem
execution, post-manifest database-field conversion, tolerant manifest
diagnostics, maximum-based `raw_observations` reconciliation, the exact
28-field record, CLI behavior, MCP non-exposure, and privacy. Focused unit and
disposable-PostgreSQL coverage proves complete final-record and CLI parity for
default Psycopg and explicit psql/Psycopg through both selectors, including
invalid-psql proof for Psycopg modes. API and shared readers remain unchanged.
PSYCOPG88 should perform a docs-only Bulk full-function parity evaluation and
select one next direction without beginning API implementation.

PSYCOPG88 evaluation note: PSYCOPG88 declares the Bulk hybrid migration
complete and validates full-function parity as the reusable hybrid pattern:
production remained transport-only while focused pass-band tests proved the
unchanged database/filesystem ordering, manifest diagnostics, 28-field record,
maximum redaction reconciliation, connector/CLI equality, MCP absence, and
privacy boundary. The Bulk/API readers remain textually parallel, but the first
baseline exposed no extraction need; extraction stays deferred until API also
has parity and only proceeds later for a concrete maintenance benefit.
PSYCOPG88 selects Option A. PSYCOPG89 should be a docs-only complete API hybrid
summary readback design, without implementation or shared-reader extraction.

PSYCOPG89 design note: PSYCOPG89 selects Option A and defines
`query_api_summary(...)` as the complete parity unit even though PSYCOPG90's
production edit should replace only its three-field database transport with an
object-shaped `execute_json_readback(...)` call. The design preserves
database-before-filesystem execution, post-manifest database-field conversion,
resolved `.repomap/api-runs` containment and diagnostics, tolerant nested
request/response aggregation, literal-false safety folding, direct placeholder
merge, the exact 28-field record, CLI behavior, MCP non-exposure, and the
broader projected-string privacy boundary. Existing fixtures plus temporary
public-safe manifests are sufficient. PSYCOPG90 should implement only the API
adapter with complete five-mode full-function parity, without changing Bulk or
extracting shared readers.

PSYCOPG90 implementation note: PSYCOPG90 adapts only the database transport
inside `query_api_summary(...)` through object-shaped
`execute_json_readback(...)` while preserving database-before-filesystem
execution, post-manifest database-field conversion, `.repomap/api-runs`
containment and diagnostics, tolerant nested request/response aggregation,
literal-false safety folding, direct placeholder replacement, the exact
28-field record, CLI behavior, MCP non-exposure, and privacy. Focused unit and
disposable-PostgreSQL coverage proves complete final-record and raw/decoded CLI
parity for default Psycopg and explicit psql/Psycopg through both selectors.
Bulk and shared readers remain unchanged. PSYCOPG91 should perform a docs-only
API full-function parity evaluation, declare whether both hybrid summaries are
complete, reassess shared-reader extraction with two baselines, and select one
next direction without beginning another implementation.

PSYCOPG91 evaluation note: PSYCOPG91 declares the API migration and the full
current Bulk/API hybrid-summary family complete. The transport-only,
complete-function parity pattern succeeded for both hybrids without changing
manifest behavior. Their 26-line manifest readers are textually identical,
but extraction remains deferred because there is no third consumer, defect,
drift, or material pressure benefit to offset containment and diagnostic risk.
PSYCOPG91 selects Option B. PSYCOPG92 should perform a docs-only
operational/status PostgreSQL readback assessment that separates connector
selection from configured host/container fallback and lifecycle semantics,
classifies safe facade candidates, and does not migrate operational paths or
MCP search.

PSYCOPG92 assessment note: PSYCOPG92 selects an operational-specific adapter
design before any operational query migration. The four current operational
readbacks are object-shaped, but they do not form mechanical central-facade
targets: refresh status and graph summary depend on `_run_ops_psql(...)` for
one bounded host-to-owned-container topology retry, while config and graph
storage checks use distinct typed-failure behavior and no topology retry.
Container `exec ... psql` command prefixes cannot be represented as Psycopg
connection arguments, and operational retry is not connector fallback.
PSYCOPG93 should be docs-only and define a topology-preserving JSON readback
adapter, explicit-command and error-mapping contracts, psql-only container
execution, connector-selection boundaries, shape validation, and a first
bounded readback target without changing routing, status functions, lifecycle
paths, or MCP search.

PSYCOPG93 design note: PSYCOPG93 selects a topology-preserving operational
JSON adapter that composes the existing connector registry with one forced-
psql container attempt. Unset commands honor the two existing connector
selectors and default Psycopg; any non-`None` `psql_command` remains an exact
psql process override, bypasses selector resolution, and suppresses container
retry. Required `host_only` and `host_then_container` modes make topology
eligibility explicit. Connector selection, authentication, SQL, decoding,
shape, and caller field-conversion failures never trigger topology retry;
eligible default-host psql connection failures and classified Psycopg
connection failures may trigger exactly one owned-container psql attempt.
PSYCOPG93 selects complete `query_refresh_status(...)` as the first target
because it already distinguishes unset from explicit commands and already owns
the topology contract. PSYCOPG94 should implement only the adapter and both
read-only refresh-status stages with complete typed, CLI, MCP, privacy, and
partial-database parity; PostgreSQL readiness remains deferred until its
default-command and `OSError` compatibility boundary is designed separately.

PSYCOPG94 implementation note: PSYCOPG94 adds package-internal named-driver
storage seams and a topology-preserving operational JSON coordinator with
required host-only and host-then-container modes. Unset commands honor the
existing selectors and default Psycopg; every explicit command forces one psql
attempt and bypasses selector resolution and container inspection. Eligible
default-host topology failures may receive one owned-container psql attempt,
with no connector fallback. Both read-only database stages in
`query_refresh_status(...)` now use the coordinator while graph grouping,
typed failure folding, CLI/MCP projections, privacy, and mutation/lifecycle
ownership remain unchanged. PSYCOPG95 should perform a docs-only adapter and
refresh-status parity evaluation before selecting another operational target.

PSYCOPG95 evaluation note: PSYCOPG95 declares the storage support seams and
complete `query_refresh_status(...)` migration complete, including typed,
connector, CLI, MCP, partial-database, ordering, privacy, and lifecycle parity.
The topology-enabled adapter path is reusable, but the adapter as a whole is
not complete: terminal explicit-command and `host_only` failures can still
resolve a runtime plan while constructing the shared container hint; ineligible
topology-mode failures can do the same, and eligible failures can resolve a
second plan during augmentation. PSYCOPG95 selects Option E. PSYCOPG96 should
narrowly enforce no planning for ineligible paths and one plan for eligible
paths, add focused regression coverage, preserve topology-enabled and legacy
process behavior, and migrate no additional operational owner. PostgreSQL
readiness compatibility design remains the preferred next new readback phase
after that fix.

PSYCOPG96 implementation note: PSYCOPG96 closes the operational adapter's
failure-path topology-isolation defect. Explicit-command, `host_only`, selector,
and other non-retryable failures now perform zero runtime or container
planning. An eligible `host_then_container` failure resolves one private
execution-or-hint plan and reuses it for the single optional container psql
attempt and terminal error, including unavailable and failed-container cases.
Legacy `_run_ops_psql(...)`, refresh-status typed/CLI/MCP parity, connector
selection, privacy, and lifecycle ownership remain unchanged. PSYCOPG97 should
be a docs-only PostgreSQL readiness compatibility design covering `host_only`,
omitted versus explicit command intent, default Psycopg authorization, exact
psql compatibility, `OSError` folding, and the graph-storage prerequisite.

PSYCOPG97 design note: PSYCOPG97 selects a nullable command default for
`check_ops_postgres_status(...)` and `ops config-check --check-db`. Omission
authorizes the existing selectors and default Psycopg in `host_only` mode;
every supplied command still forces one exact psql attempt and bypasses
selectors. Adapter errors, including executable `OSError` and wrong top-level
shape, should intentionally fold into the existing typed readiness failure and
CLI status `0`, while permissive field conversion remains unchanged. The
`ops graphs --check-db` literal psql default and graph-storage SQL remain
unchanged until their complete function is designed. PSYCOPG98 should implement
only this readiness/config-check boundary with focused connector, CLI,
graph-short-circuit, and privacy parity.

PSYCOPG98 implementation note: PSYCOPG98 migrates only PostgreSQL operational
readiness through the completed operational JSON adapter in `host_only` mode.
Omitted config-check commands now honor the existing selectors and default to
Psycopg; every supplied command still forces one exact psql attempt. All
adapter failures fold into the existing typed readiness record, object-shape
validation and executable-error folding are the approved bounded compatibility
improvements, and permissive field conversion remains unchanged. The graphs
command retains its literal psql default and graph-storage SQL remains direct
psql-owned. PSYCOPG99 should perform a docs-only readiness parity evaluation
and choose whether graph-storage status is the next operational design target.

PSYCOPG99 evaluation note: PSYCOPG99 declares PostgreSQL operational readiness
complete. The nullable command/default-Psycopg convention, typed executable-
error folding, and explicit object-shape validation are approved bounded
compatibility improvements; permissive fields, typed/CLI projections,
`host_only` isolation, connector parity, and privacy remain intact. The graphs
parser still supplies literal psql and graph-storage SQL remains direct
psql-owned without partial selector behavior. PSYCOPG100 should be a docs-only
complete graph-storage status readback design covering both stages, nullable
command intent, multi-database failure folding, typed/CLI parity, and privacy.

PSYCOPG100 design note: PSYCOPG100 defines one nullable command contract for
the complete graph-storage status boundary. Omission should use the existing
selectors and default Psycopg independently for readiness and graph-storage
`host_only` object reads; every supplied command should force exact psql for
both stages. The design preserves database grouping, readiness short-circuit,
graphs-list normalization, last-row overwrite, permissive scalar conversion,
missing-row defaults, caller-owned malformed-count failure, typed per-database
transport failures, later-database continuation, CLI ordering, and privacy.
PSYCOPG101 should implement only this migration and focused parity coverage.

PSYCOPG101 implementation note: PSYCOPG101 completes the operational
graph-storage status migration. The readiness precheck and graph-storage query
now share one nullable command intent and use independent `host_only` object
readbacks: omission honors the existing selectors and default Psycopg, while a
supplied command forces exact psql for both stages. Multi-database grouping,
readiness short-circuit, tolerant graphs-list normalization, last-row overwrite,
permissive row conversion, caller-owned malformed-count failures, typed
per-database transport failures, CLI ordering, and privacy remain unchanged.
PSYCOPG102 should be a docs-only parity evaluation that formally confirms this
boundary and selects exactly one next direction among graph summary, MCP search,
a discovered correction, or pause.

PSYCOPG102 evaluation note: PSYCOPG102 declares the complete graph-storage
status boundary connector-facade-backed and complete. Both read-only stages now
share the nullable operational command convention, the config-check/graphs
parser asymmetry is closed, the approved executable-error and object-shape
folding remains bounded, and normalization, permissive conversion,
multi-database continuation, typed/CLI ordering, and privacy retain full parity.
No material correction or cleanup phase is required. Graph summary is the sole
remaining pure operational status/summary direct owner and has mature topology,
CLI, baseline, drift, and private-graph evidence; PSYCOPG103 should therefore be
a docs-only complete graph-summary readback design. MCP search remains deferred
as a separate configured-wrapper, pagination, raw-payload, and sanitization
boundary.

PSYCOPG103 design note: PSYCOPG103 selects direct implementation of the complete
graph-summary boundary. Both readiness and summary stages should use independent
`host_then_container` object readbacks with the existing nullable command
contract, one eligible owned-container psql attempt per stage, and no connector
fallback. Graph validation, privacy warnings, typed failures, repository-missing
success, caller conversion, CLI and baseline projection, baseline-save gating,
persisted payloads, drift behavior, and no-root-read/mutation boundaries form the
parity unit. PSYCOPG104 should implement only those two transport replacements
with focused connector and downstream parity tests; MCP search and configured
storage remain deferred.

PSYCOPG104 implementation note: PSYCOPG104 completes the graph-summary
transport migration. Readiness and summary now use independent
`host_then_container` object readbacks with the existing nullable command
contract, default Psycopg and selector behavior, exact-command psql precedence,
one eligible owned-container psql attempt per stage, and no connector fallback.
Typed records, repository-missing success, conversion, CLI and graph-baseline
projection, baseline-save gating and persisted content, drift, runtime fallback,
privacy, no-root-read, and mutation isolation retain complete parity. PSYCOPG105
should be a docs-only parity evaluation that confirms the pure operational
status/summary family and selects exactly one remaining direction among MCP
search design, configured-storage assessment, a discovered correction, or
pause.

PSYCOPG105 evaluation note: PSYCOPG105 declares graph-summary migration and the
four-member pure operational status/summary family connector-adapter-backed and
complete. Exact two-stage topology routing, typed conversion and failures, CLI,
graph-baseline, baseline persistence, drift, runtime fallback, privacy, no-root-
read, and mutation isolation retain complete parity; no correction phase is
required. Remaining configured readback ownership is heterogeneous: the generic
psql topology wrapper surrounds already selector-aware storage callbacks as well
as direct MCP search. PSYCOPG106 should therefore be a docs-only configured-
storage wrapper assessment that inventories every consumer and decides whether
MCP search can migrate independently or requires an adapter-aware configured
topology coordinator.

PSYCOPG106 assessment note: PSYCOPG106 inventories 17 configured-storage
callbacks. Sixteen already own psql/Psycopg selection, declared object/array
shape, and conversion through the central storage adapter; only MCP search still
owns direct psql and array parsing. Search has one production operations-context
call site and does not serve the legacy `StorageConnection` callback family, so
it can bypass the generic psql topology wrapper without changing the other
callbacks or compatibility routing. PSYCOPG107 should be a docs-only independent
MCP-search readback design covering array transport, pagination, raw policy,
topology, public MCP parity, and privacy. Generic wrapper redesign, retirement,
and other callback changes remain deferred.

PSYCOPG107 design note: PSYCOPG107 defines an operations-specific private MCP-
search boundary that accepts configuration and effective database explicitly,
uses `execute_ops_json_readback(...)` with array shape and
`host_then_container`, and bypasses the generic configured callback wrapper only
for search. Target SQL, `limit + 1` pagination, filters, raw-observation policy,
public tools and schemas, sanitization, and privacy remain unchanged. Omitted
commands authorize existing selectors and default Psycopg; a validated supplied
psql path forces exact psql and suppresses topology retry. PSYCOPG108 should
implement only this migration with focused public MCP parity coverage. Generic
wrapper semantics, other callbacks, and legacy MCP routing remain deferred.

PSYCOPG108 implementation note: PSYCOPG108 migrates only MCP search to the
topology-preserving operational array adapter and bypasses the generic
configured callback wrapper only for search. Nodes, observations, files,
`limit + 1` pagination, raw-payload policy, public MCP schemas, sanitization,
privacy, exact-command psql, selector/default Psycopg, and one eligible
container psql topology attempt retain complete parity. PSYCOPG109 should be a
docs-only parity evaluation that decides search completion and selects one
bounded final direction. Generic wrapper redesign, other callbacks, legacy
routing, and all mutation/lifecycle work remain deferred.

PSYCOPG109 evaluation note: PSYCOPG109 declares MCP-search migration complete.
The operations-specific array adapter preserves connector selection, exact-
command psql, bounded topology, target SQL, pagination, raw-observation policy,
public MCP schemas, sanitization, privacy, and read-only behavior. All pure
operational and configured JSON callbacks are now connector-adapter-backed;
remaining direct psql owners are intentional load, mutation, process, named-
connector, and compatibility infrastructure. PSYCOPG110 should close and pause
the connector/readback series. Generic wrapper redesign and lifecycle work
remain explicit deferrals.

PSYCOPG110 closure note: PSYCOPG110 closes and pauses the PSYCOPG connector and
readback series. The operational adapter foundation, four-member pure status/
summary family, MCP search, and 16 central-adapter configured callbacks are
complete. Remaining direct psql owners are intentional named-connector,
process, load, mutation, and compatibility infrastructure; no known parity,
privacy, ordering, or connector-fallback gap remains in the completed scope.
No PSYCOPG111 phase is selected. Generic wrapper redesign, legacy routing,
lifecycle, runner/control-plane, publication, and private live operations
remain outside this series.

DOC-SHA0 inventory note: DOC-SHA0 inventories and classifies Git commit
references and SHA-like hexadecimal values across tracked public-facing
documentation. The assessment distinguishes gratuitous phase/predecessor
references from content digests, fixtures, domain identifiers, false positives,
and four then-retained Apache-2.0 licensing-baseline references. It keeps
`git-show-report` private-only and finds no need for a public `docs/git-show/`
archive. DOC-SHA1 should replace confirmed private-history references with
phase IDs and status-document paths. DOC-SHA2 should define publication-safe
documentation-reference policy, the narrow exception mechanism, and a future
scanner contract. Neither follow-on phase is implemented by DOC-SHA0.

DOC-SHA1 completion note: DOC-SHA1 replaces the 59 private-history
STORAGE-SQL and PSYCOPG phase references with phase IDs and status-document
paths, and replaces the four Apache-2.0 baseline commit references with the
dedicated `lair001/repo-map_apache-2.0-final` repository planned for public
historical preservation. Legitimate content hashes, fixtures, and domain
identifiers remain unchanged. The raw DOC-SHA0 inventory and private report
are deferred until DOC-SHA2 defines the publication and control-plane policy;
DOC-SHA3 should then normalize the inventory and perform final cleanup.

DOC-SHA2 completion note: DOC-SHA2 adopts
`docs/contrib/documentation-reference-policy.md` as the publication-safe
history-reference policy. Semantic phase, status, ADR, roadmap, and repository
references are the public default; private-development SHAs and public
git-show archives are prohibited. The policy defines the dedicated Apache-2.0
historical repository, legitimate-hash boundary, future scanner contract,
no-ordinary-exception decision, and private `git-show-report` control-plane
role without implementing a scanner or changing report tooling. DOC-SHA3
should normalize the deferred DOC-SHA0 inventory and run the final tracked-doc
scan; private report migration remains separate `repo-map_ctrl` work.

DOC-SHA3 closeout note: DOC-SHA3 normalizes the DOC-SHA0 inventory by removing
copied raw private commit values while preserving the original counts,
STORAGE-SQL and PSYCOPG semantic mappings, and legitimate non-Git
classifications. Final tracked-document scans apply the DOC-SHA2 policy and
close the public documentation SHA cleanup. Private reports remain unchanged;
CI-DOCSAFE0, CTRL0, GIT-SHOW0, and CI0 remain independent future work.

PHASE-ID0 collision-inventory note: PHASE-ID0 inventories the two completed
phase families that both use `STORAGE-ROWS0` through `STORAGE-ROWS7`. No phase
identifier is renamed in PHASE-ID0. The assessment recommends retaining
`STORAGE-ROWS` for the earlier broad `storage/rows.py` decomposition and using
`STORAGE-SUMMARY-ROWS` for the later `storage/summary_rows.py` decomposition.
PHASE-ID1 should perform the explicit semantic rename with a scoped historical
alias map; PHASE-ID2 should close the remediation and define phase-ID
uniqueness and future scanner policy.

PHASE-ID1 completion note: PHASE-ID1 renames the later summary-row family to
`STORAGE-SUMMARY-ROWS0` through `STORAGE-SUMMARY-ROWS7`, preserves the earlier
canonical `STORAGE-ROWS0` through `STORAGE-ROWS10` family, and publishes the
scoped historical mapping in `docs/contrib/phase-id-aliases.md`. The eight
summary-row status sequences remain unchanged, their filenames and active
references use the canonical prefix, and immutable commit subjects and private
reports remain unchanged. PHASE-ID2 should verify closure and establish the
permanent phase-ID uniqueness and scanner policy.

PHASE-ID2 closeout note: PHASE-ID2 adopts
`docs/contrib/phase-identity-policy.md` as the permanent canonical-ID,
namespace-reservation, status/roadmap consistency, historical-alias, immutable
Git, private-report, and future scanner policy. The duplicate-heading audit
resolves two M1 smoke/documentation records as supporting evidence for one
primary M1 status record and finds no duplicate canonical ID. The
`STORAGE-ROWS` collision remediation is closed; scanner implementation and
control-repository work remain independent later phases.

GO0 assessment note: GO0 begins the Go language extraction and
large-repository dogfooding epic after PSYCOPG110 closure. Current discovery
does not classify .go, go.mod, go.sum, go.work, _test.go, or standard
generated-code headers; it emits only generic file observations and has no Go
extractor or canonical family. Read-only inventory of Kubernetes, Terraform,
Argo CD, and Docker Language Server found 20,635 tracked Go files and more than
6.3 million physical Go lines across 54 modules and seven workspaces, with
material generated, vendor, build-tag, platform, test, cgo, and assembly
boundaries. GO1 should remain docs-only and define the exact Go taxonomy,
standard-library AST helper protocol, safety and packaging boundary, fixtures,
tests, and dogfood acceptance criteria. Python-only lexical scanning is
retained for classification and module metadata but rejected as the long-term
syntax parser; Tree-sitter is deferred. GO1 must decide whether the preferred
Go helper constitutes a new parser runtime requiring a user stop before
implementation.

GO1 design note: GO1 accepts docs/extraction/go-extraction-design.md as the
taxonomy, evidence, safety, parser, protocol, fixture, test, dogfood,
performance-bound, packaging, rollback, and phase contract. GO2 may implement
only Python-owned .go/test/generated/platform/vendor classification and
go.mod/go.work metadata extraction with no dependency, Go module, executable,
type checking, canonicalization, or schema change. A standard-library Go AST
helper remains the preferred high-fidelity parser, but it is classified as a
new parser runtime. The epic should complete GO2 and then stop before GO3 for
explicit authorization of that helper and its platform packaging boundary.

GO2 implementation note: GO2 classifies Go source, tests, generated files,
platform filename constraints, go.mod, go.sum, go.work, and vendor manifests;
adds bounded Python-only module/workspace metadata observations; and proves the
boundary with synthetic unit and CLI integration coverage. An untracked local
overlay defines the four authorized dogfood graphs. Docker Language Server
preflight and two complete refreshes produced stable latest-run counts, stored
and preflight baselines, and a no-drift result without modifying its source
tree. GO2 adds no dependency, Go module, executable, canonical Go model,
schema change, or target execution. The epic is stopped before GO3 for the
mandatory decision on the recommended RepoMap-owned standard-library Go parser
helper and platform packaging boundary.

GO3 implementation note: GO3 adds the authorized standard-library-only Go
module and source-built parser helper, strict versioned JSONL protocol,
repository-relative path boundary, package/import/const/var/type/alias and
bounded parse-error observations, deterministic package-adjacent helper
publication, Python validation and adaptation, and repository-runner Go gates.
Docker Language Server produced stable declaration counts across two unchanged
refreshes with no Go diagnostics, no source mutation, and no stored or
preflight drift. Canonical Go modeling remains deferred to GO9. GO4 should add
syntax-only function, method, receiver, parameter, and result observations
through the existing protocol without changing the accepted packaging or
static-extraction boundary.

GO4 implementation note: GO4 adds syntax-only function, method, receiver,
parameter, and result observations through the existing Go helper protocol.
Callable metadata is structured and bounded; receiver and type source text is
not stored, unnamed fields retain stable position identity, and no type
resolution or canonical Go model is introduced. Docker Language Server
produced identical callable counts across two unchanged refreshes with no Go
diagnostics, source mutation, or stored/preflight drift. GO5 should add
composite type and generic detail for structs, interfaces, fields, embedded
fields, type parameters, constraints, and union terms without changing the
accepted runtime, protocol, packaging, or static-extraction boundary.

GO5 implementation note: GO5 adds syntax-only struct, interface, field,
embedded-field, type-parameter, constraint, and union-term observations. It
stores bounded AST-shape metadata rather than raw type, tag, or constraint
text and makes no type-resolution or interface-satisfaction claim. Docker
Language Server produced stable composite counts across two unchanged
refreshes with no Go diagnostics, source mutation, or stored/preflight drift.
GO6 should add reference and expression syntax without changing the accepted
runtime, protocol, packaging, or static-extraction boundary.

GO6 implementation note: GO6 adds syntax-only references, selectors, calls,
method expressions, constructions, conversions, assertions, type switches,
indexing, slicing, proven map access, and multi-index instantiation. Ambiguous
forms remain unresolved or unknown, and no literal or expression text is
stored. Docker Language Server produced 102,199 stable observations across two
unchanged refreshes with zero Go diagnostics and no drift; the measured memory
and refresh-time increase remains explicit scale evidence. GO7 should add
control-flow and concurrency syntax without changing the accepted runtime,
protocol, packaging, or static-extraction boundary.

GO7 implementation note: GO7 adds syntax-only closure, goroutine, defer,
channel send and receive, select, panic, recover, return, branch, and dynamic
call-target observations. Unresolved built-in names and dynamic call targets
remain explicit, and no literal, function body, expression text, or runtime
claim is stored. Docker Language Server produced 104,538 stable observations
across two unchanged refreshes with zero Go diagnostics, no source mutation,
and no drift. GO8 should add build, generated, cgo, assembly-companion, test,
and vendor context without changing the accepted runtime, protocol, packaging,
or static-extraction boundary.

GO8 implementation note: GO8 completes the accepted raw Go taxonomy with
bounded build-constraint, generated-marker, cgo, assembly-companion, test,
benchmark, fuzz, example, TestMain, and vendor-package evidence. Build and test
meaning remains syntactic; cgo and assembly are not executed or parsed, and
raw directive text is not stored. Docker Language Server produced 104,670
stable observations across two unchanged refreshes with 132 syntactic test
functions, zero Go diagnostics, no source mutation, and no drift. The epic is
stopped before GO9 for the mandatory decision on the proposed public canonical
Go identities and conservative edge rules.

GO9 implementation note: GO9 adopts deterministic version-1 Go module,
package, type, alias, function, method, constant, and variable identities with
raw-evidence linkage, expected-duplicate accounting, bounded collision errors,
and evidence-only unresolved syntax. Exact ownership, bounded local imports,
module requirements/replacements, workspace use, and defined receiver
ownership become canonical edges. Docker Language Server plus the RepoMap
runner and controller dogfood graphs produced stable collision-free canonical
outputs across unchanged repeats, saved stored/preflight baselines, and no
drift. GO10 should be a dedicated docs-only inventory and phase-map assessment
for the five newly authorized dogfood repositories before any formal parity
claim or broader extraction correction.

GO10 assessment note: GO10 inventories the five added protected dogfood
repositories without running extraction or changing source. Caddy has 322 Go
files and 20 build-tagged files; gorush has 63 Go files; recipes has 385 Go
files across 91 module roots; the RepoMap controller has 82 Go files across
two module roots; and the RepoMap runner has 77 Go files across two module
roots. All five worktrees remained clean. GO11 should harden module, workspace,
package, and bounded local-import resolution before formal evaluation phases,
with recipes as the primary nested-module structure fixture.

GO11 design-correction note: the first recipes canonicalization finds two
module paths repeated across 6 and 19 independent module roots, with 14 and 2
overlapping derived package identities. Canonical key version 1 cannot preserve
exact source ownership for these cases. The current resolver correctly fails
closed. GO11 recommends preserving the semantic module coordinate while adding
explicit repository-scoped source-module and source-package instances, but the
new node, edge, scope, and versioned identity contract requires user approval
before GO12 implementation.

GO12 implementation note: Model A preserves `go.module` as the shared semantic
coordinate and adds explicit `go-source-v2` source-module, source-package, and
source-declaration identities beneath the configured repository name. Source
ownership no longer emits GO9 package or declaration keys. Repeated module
paths are expected independent instances linked to one semantic coordinate;
bounded local imports cannot cross those instances. Existing Go graphs require
a rebuild because the migration is additive and does not rewrite stored keys.
GO13 remains the performance and incremental-refresh phase.

GO13 assessment note: a bounded uncommitted JSONL cache reused all unchanged
Go helper observations and preserved byte-identical raw and canonical output,
but it demonstrated no material improvement on Docker Language Server, RepoMap
runner, RepoMap controller, or recipes. The trial was removed and no
source, test, CLI, schema, identity, or graph contract changed. Full refresh
remains authoritative. Material incremental refresh would require a language-
neutral transactional storage design for content-addressed extraction
generations, run membership, invalidation closure, partial canonical
reconciliation, and full-refresh recovery. The epic stops for a user decision:
defer that storage architecture and proceed to GO14 full-refresh evaluation,
or authorize a separate incremental-storage architecture phase first.

GO14 evaluation note: GO13 Deferral A is accepted, and deterministic full
refresh remains the only supported refresh mode. RepoMap runner passes formal
evaluation with 77 Go files across two source modules, 42,324 Go observations,
811 canonical Go nodes, 1,036 canonical Go edges, 2,649 evidence links, 61
expected duplicate evidence records, zero identity collisions, and stable
repeated full refreshes. Fresh stored/preflight baselines report no drift. No
runner-specific correction phase is required; GO15 should formally evaluate
RepoMap controller under the same full-refresh contract.

GO15 evaluation note: RepoMap controller passes formal evaluation with 82 Go
files across two source modules, 38,874 Go observations, 777 canonical Go
nodes, 1,021 canonical Go edges, 2,432 evidence links, 72 expected duplicate
evidence records, zero identity collisions, and byte-stable direct plus stable
repeated full-refresh output. The controller adds build-constraint, limited
generic-constraint, embedded-field, and panic coverage. Fresh stored/preflight
baselines report no drift. No correction phase is required; GO16 should
formally evaluate recipes under the full-refresh-only contract.

GO16 evaluation note: recipes passes formal evaluation with 385 Go files, 91
source modules, 68 distinct declared semantic coordinates, two repeated-
coordinate groups with multiplicities 19 and 6, 65,604 Go observations, 2,719
canonical Go nodes, 5,446 canonical Go edges, 13,994 evidence links, 160
expected duplicate evidence records, and zero identity collisions. Direct raw
and canonical output is byte-stable, repeated full refresh is stable, and fresh
stored/preflight baselines report no drift. Full refresh reaches roughly 96
seconds and 5.6 GiB peak memory but remains feasible. No correction phase is
required; GO17 should formally evaluate gorush.

GO17 evaluation note: gorush passes formal evaluation with 63 Go files, one
source module, 20 source packages, 25,158 Go observations, 828 canonical Go
nodes, 1,107 canonical Go edges, 2,731 evidence links, 46 expected duplicate
evidence records, and zero identity collisions. Direct raw and canonical output
is byte-stable, repeated full refresh is stable, and fresh stored/preflight
baselines report no drift. Gorush adds bounded benchmark, test-main, goto,
module-replacement, send, receive, generated-file, and build-constraint
coverage. No correction phase is required; GO18 should formally evaluate Caddy.

GO18 evaluation note: Caddy passes formal evaluation with 322 Go files, one
source module, 48 source packages, 182,764 Go observations, 3,721 canonical Go
nodes, 5,699 canonical Go edges, 14,245 evidence links, 712 expected duplicate
evidence records, and zero identity collisions. Direct raw and canonical output
is byte-stable, repeated full refresh is stable, and fresh stored/preflight
baselines report no drift. Full refresh peaks near 6.5 GiB and the unchanged
second run is materially slower, but remains feasible. No correction phase is
required. Caddy also exercises filename-constraint metadata on eight Go files;
GO19 should formally evaluate Argo CD.

GO19 correction note: Argo CD exposed a tracked dangling file symlink that
passed lexical root containment and raised `FileNotFoundError` during
extensionless language detection. Repository discovery now verifies that each
walked filename resolves to a regular file before classification. A red/green
synthetic regression, a regular in-root symlink preservation test, the existing
escaping-symlink test, bounded Argo CD inventory, and the full source gate pass.
The separate path checks do not eliminate a concurrent retarget/removal race;
atomic-open hardening remains deferred. GO20 should resume formal Argo CD
evaluation; deterministic full refresh remains the only supported mode.

GO20 correction note: the resumed Argo CD audit exposed one duplicate Go source
ID because an in-root symlink and its target both normalized to the same resolved
`FileInfo.path`. Discovery now deduplicates classified records by that resolved
repository-relative identity before stable sorting. A red/green synthetic test,
the complete million-observation Argo CD canonical recheck, and the full source
gate pass with zero collisions. GO21 should perform the formal Argo CD
full-refresh evaluation.

GO21 feasibility note: Argo CD direct extraction and canonicalization complete
successfully with 1,982,148 observations, 22,516 canonical Go nodes, 36,004 Go
edges, 81,036 evidence links, and zero collisions. The first monitored
storage-backed full refresh terminated abnormally after roughly 12.7 minutes,
approximately 26 GiB maximum resident memory, and an approximately 92 GiB peak
memory footprint. Transactional rollback left an empty initialized graph.
The graph was disabled, no retry or baseline was attempted, and the epic stops
for a full-refresh bounded-memory decision. GO22 Option A is recommended; it is
language-neutral full-refresh work, not incremental storage or caching.

GO22 correction note: full refresh now lazily adapts raw and canonical storage
rows and streams deterministic SQL through bounded psql stdin transfer while
retaining one `BEGIN`/`COMMIT` transaction. Byte-equivalence, one-shot iterator,
bounded output, cancellation, mixed-language, large generated population, and
failure-injection rollback tests pass. RepoMap runner maximum RSS fell to
approximately 229 MiB and recipes to approximately 446 MiB, with stable repeat
counts and no baseline drift. Argo CD remained PostgreSQL CPU-bound for more
than two hours without completing; rollback remained empty, its dedicated
database was removed backup-first, and its graph registration was retired.
This establishes a storage-throughput architecture limit distinct from the
corrected client-memory problem. Argo CD, Terraform, and Kubernetes formal
full-refresh parity and any set-based storage redesign are deferred outside the
Go epic. GO23 should close the epic with that support boundary.

GO23 closure note: the Go extraction epic is complete. The accepted contract is
the RepoMap-owned standard-library helper, versioned bounded JSONL protocol,
syntax-honest raw extraction, Model A repository-scoped source identities,
deterministic evidence-linked canonicalization, and forced-full transactional
refresh. Formal dogfood parity covers Docker Language Server, RepoMap runner,
RepoMap controller, recipes, gorush, and Caddy. Argo CD direct extraction is
stable but storage-backed dogfood is retired; Terraform and Kubernetes formal
parity are not claimed. High-scale/incremental storage, vendored identity,
dependency-backed type analysis, and release-platform binary packaging require
separate future mandates.

LOCAL0 assessment note: a new local-operations epic begins with six dedicated,
manual, initially MCP-hidden graph identities and an untracked late-sorting
operations overlay. The current CLI, lifecycle, baseline/drift, MCP, privacy,
source-protection, and test surfaces are inventoried in
`docs/status/2026/07/12/00470-local0-local-operations-assessment.md`. The exact
remaining legacy-default storage commands are `storage files`,
`storage entrypoints`, and `storage file-nodes`; each receives a separate
assessment, implementation, and parity sequence after two clean lifecycle/API
cycles. LOCAL0 also confirms that private operations config/graph output leaks
machine-local fields, so LOCAL2 is reserved for a bounded redaction correction
before the first destructive cycle. LOCAL1 should establish the six-graph
overlay, privacy/exclusion design, exact private target ledger, MCP visibility
isolation, and source-cleanliness protocol without initializing or refreshing
graphs.

High-scale set-based or COPY-based ingestion and language-neutral transactional
incremental storage remain deferred backlog work. The LOCAL epic targets the
supported local repository envelope and does not claim Argo CD, Terraform, or
Kubernetes scale.

LOCAL1 configuration note: an untracked late-sorting overlay now defines the
six dedicated `local-*` graph registrations with exact private target mapping,
accepted privacy/profile values, manual refresh, and initial MCP-hidden state.
It also suppresses pre-existing graph visibility during the one-at-a-time MCP
matrix. All six read-only preflights pass, the local operations/credential,
runtime, backup, status, and server-memory exclusions are enforced, and every
protected source worktree remains clean. No runtime, database, refresh,
baseline, drift, MCP, or destructive operation occurred. LOCAL2 should correct
the confirmed private-field leak in operations config and graph CLI output
before the first lifecycle cycle.

LOCAL2 privacy correction note: operations config and graph-registry JSON and
table output now hide local config locations, server-memory paths, and private
graph roots, database names, and exclusion paths behind stable markers. Public
graph metadata, graph selectors, readiness, diagnostics, and counts remain
available. Red-green projection tests, CLI unit and integration coverage, a
bounded live six-graph absence check, the 2,441-test full gate, coverage,
container smoke, compileall, and file-length policy passed. No lifecycle,
database, refresh, baseline, drift, MCP, schema, migration, extractor,
canonicalization, or dependency change occurred. LOCAL3 should perform the
first exact-allowlisted clean database initialization and refresh cycle for all
six graphs with backup-first destructive handling and source-cleanliness
verification.

LOCAL3 lifecycle note: the first exact-allowlisted six-graph destructive cycle
passed. Each initially absent dedicated database was bootstrapped, exercised
through a verified backup-first drop, reinitialized from current source
migrations, preflighted, refreshed, summarized, baselined, and checked for
immediate stored and preflight drift. All six latest runs completed with zero
diagnostics, every actual drop had a verified backup, and no RepoMap action
mutated a source root. Concurrent controller and flakes development was
preserved and classified separately through operation-scoped snapshots and
preflight drift. Backup metadata inspection passed, but live backup content
inspection exposed an invalid `pg_restore` stdin filename. LOCAL4 should make
that bounded red-green correction before the complete read-only CLI matrix.

LOCAL4 backup inspection note: the invalid `pg_restore` archive filename is
removed from the list command, so verified custom archives streamed on standard
input now produce the existing bounded TOC summary. A focused command-contract
test failed before the correction and passed afterward; 17 related tests and
one live verified backup inspection for each authorized graph also passed. All
six live inspections verified manifests and checksums, read 130 bounded TOC
entries with zero diagnostics, exposed no raw dump content, and performed no
destructive action. Backup format, creation, checksum, restore, drop, database,
schema, graph, and dependency contracts are unchanged. LOCAL5 should execute
the complete CLI read-only and status operation matrix.

LOCAL5 nested status correction note: the first six-only CLI readiness probe
found that `ops graphs --check-db` redacted the parent graph but embedded raw
private database values and internal numeric repository IDs in successful
storage-status JSON. The graph-registry projection now applies the parent
database privacy rule to nested status and removes `repository_id` while
preserving public-development metadata, readiness, repository name, and
aggregate counts. Red-green JSON/table coverage, 11 focused test executions,
and corrected live output for all six authorized graph databases passed. No graph source,
database, backup, baseline, runtime, MCP, schema, or dependency state changed.
LOCAL6 should restart and complete the read-only/status CLI matrix against the
corrected boundary.

LOCAL6 CLI read-only matrix note: exact six-only operations, runtime, backup,
preflight, refresh-status, summary, stored-baseline, drift, policy, and 20
non-keyed storage readback commands passed in JSON and table modes. Keyed
readback then found a canonical contract mismatch: stored edge listing returned
`calls`, while CLI canonical edge validation rejected it. Source inspection
found 14 CLI-accepted kinds against 65 migration-supported kinds, with 51
schema-supported kinds absent from CLI validation. LOCAL6 stopped before later
graphs or failure/connector cases, retained no raw output, and performed no
graph or source mutation. One private source had one-file preflight drift, and
concurrent external development advanced two protected roots after their
time-bounded checks. LOCAL7 should correct canonical edge-kind validation with
red-green parity coverage; LOCAL8 should resume the remaining CLI matrix.

LOCAL7 canonical edge-kind correction note: a focused production vocabulary now
contains all 65 kinds supported by current migrations, and CLI canonical edge
filters, neighborhoods, and explanations import that contract instead of a
historical 14-kind subset. The migration unit test now compares SQL directly to
the production vocabulary rather than a duplicate test-only set. Red-green
`calls` explanation evidence, 34 focused tests, live filtered listing and
JSON/table explanation, bounded unsupported-kind failure, and the 2,443-test
complete gate passed. No SQL, migration, schema, canonicalization, graph,
source, database, baseline, backup, or dependency state changed. LOCAL8 should
resume the remaining CLI read-only/status matrix from the LOCAL6 stop boundary.

LOCAL8 CLI read-only continuation note: all four keyed commands and seven
legacy-mode surfaces passed in JSON and table modes for all six graphs.
Representative filters, empty results, repeated-ordering checks, invalid mode
and graph-key cases, graph selection failures, malformed configuration,
missing database, and explicit psql/current-source Psycopg parity also passed.
An unavailable explicit psql executable then escaped as an uncaught traceback
containing private runtime paths. LOCAL8 stopped without source or graph
mutation. LOCAL9 should correct subprocess-launch error translation with
red-green coverage before the final CLI matrix cases resume. Unpaginated legacy
projections and null-path semantics remain assigned to the command-by-command
canonical migration track.

LOCAL9 psql launch correction note: both the ordinary JSON readback runner and
the streaming loader now translate launch-time `OSError` failures into one
fixed, path-free `StorageSchemaError`. Two focused tests failed with raw
`FileNotFoundError` before the correction and passed afterward; 76 related
tests, corrected live unavailable-executable behavior, a successful live
summary, and the 2,445-test complete gate passed. No CLI argument, successful
output, SQL, schema, migration, graph, database, source, baseline, backup,
registration, or dependency state changed. LOCAL10 should resume the remaining
CLI failure and interruption matrix.

LOCAL10 CLI failure-matrix note: existing public sanitization replaced every
source-shaped private path from a synthetic nonzero psql failure and emitted no
traceback, but it retained all 512 stderr lines and 19,475 bytes. Complete psql
stderr currently flows into the storage error before path redaction, and the
presentation boundary applies no size or line bound. LOCAL10 stopped without
graph, database, source, lifecycle, or dependency mutation. LOCAL11 should add
a deterministic bounded psql failure diagnostic with red-green stderr/stdout
coverage before malformed-output and interruption testing resumes.

LOCAL11 psql diagnostic-bound note: nonzero psql stderr and stdout fallback now
retain only the first nonempty diagnostic line, cap detail at 512 characters,
and append one deterministic marker whenever content is omitted. Two oversized
cases failed before the correction while short and empty compatibility cases
passed; all four passed afterward. The 114-test focused gate, corrected
512-line live failure, 2,449-test complete gate, and privacy checks passed. No
successful output, connection-category prefix, CLI schema, SQL, graph,
database, source, lifecycle, or dependency state changed. LOCAL12 should resume
malformed-output and interruption evaluation.

LOCAL12 malformed-output note: malformed nonempty psql output returned a
bounded command-specific canonical-storage-summary diagnostic in JSON and table
modes. Empty successful output remained bounded and sanitized but incorrectly
reported the hard-coded load-summary label in both modes. Source inspection
located the mismatch between labeled JSON parsing and unlabeled empty-output
selection. LOCAL12 stopped without PostgreSQL, graph, source, lifecycle, or
dependency access. LOCAL13 should propagate the requested result label through
empty-output handling before interruption evaluation resumes.

LOCAL13 empty-output label correction note: labeled JSON readback now carries
its requested result family into empty psql output selection, while direct use
of the exported line-selection helper retains its historical load-summary
default. One strengthened assertion failed before the correction and passed
afterward; the direct-helper compatibility assertion, 40 focused tests, live
JSON/table empty-output probes, and the 2,449-test complete gate passed. No SQL,
schema, graph, database, source, lifecycle, or dependency state changed.
LOCAL14 should evaluate interruption behavior before closing the read-only CLI
matrix or selecting a separate correction phase.

LOCAL14 interruption assessment note: an isolated synthetic psql process group
terminated promptly after interruption and left no survivor, but ordinary
readback emitted a 65-line traceback containing interrupt text and a private
runtime value. Ordinary `run_psql` lacks the bounded interrupt translation
already present in streaming ingestion, and the storage-summary handler catches
only the resulting storage error family. LOCAL14 changed no source, test,
graph, database, lifecycle, or dependency state. LOCAL15 should add red-green
ordinary-runner interruption translation before the read-only CLI matrix can
close.

LOCAL15 psql interruption correction note: ordinary `run_psql` now translates
`KeyboardInterrupt` into one fixed path-free storage error with suppressed
exception context. One regression test failed on the raw interrupt before the
correction and passed afterward; 40 focused tests, a corrected isolated live
probe, and the 2,450-test complete gate passed. The live CLI returned exit code
1 and one 32-byte line with no traceback, private value, timeout, survivor, or
forced cleanup. No SQL, graph, database, source, lifecycle, or dependency state
changed. The six-graph CLI read-only/status matrix is complete. LOCAL16 should
begin the backup-first lifecycle and destructive CLI matrix.

LOCAL16 lifecycle matrix note: all six authorized databases passed sequential
dry-run, verified backup-first drop, source-migration initialization, refresh,
summary, baseline, drift, prune, recovery, and source-protection checks. Seven
new verified backups cover the six targets; two superseded controller
baselines were pruned with latest pointers preserved. Runtime down/up preserved
the volume, database fingerprint, graph readiness, and final health. Actual
`local up --json`, however, mixed container build output into stdout before the
JSON result. Source inspection traced the defect to inherited subprocess
streams in `up_local_runtime`. LOCAL17 should isolate runtime child output with
red-green coverage before lifecycle matrix completion resumes.

LOCAL17 runtime stream correction note: runtime up and down now discard child
stdout and stderr before emitting RepoMap-owned JSON or table results, and
nonzero child exits become one fixed exit-code diagnostic with suppressed
context. Three focused cases failed before the correction; 22 runtime tests, 24
broader focused tests, two actual JSON/table restart cycles, unchanged database
fingerprints, and the 2,451-test complete gate passed afterward. The JSON up
and down commands each emitted one document and zero stderr bytes. LOCAL18
should finish the remaining restore-from-backup lifecycle surface before the MCP
read-only matrix begins.

LOCAL18 CLI lifecycle closure note: one public-safe canary passed verified
backup inspection, backup-first drop, bounded missing and mismatched restore
failures, JSON/table restore dry runs, verified dump restore, pre-refresh stored
readback, current-source refresh, summary, both baselines, immediate drift, and
two-kind prune. The complete 18-database fingerprint was restored, the five
unrelated databases and canary source Git state were unchanged, all six
authorized databases remained present, and the runtime stayed healthy. The
latest run contains 38,881 observations with zero diagnostics; two retained
runs account for 77,762 historical raw observations without changing canonical
counts. The supported CLI read-only and lifecycle matrices are complete.
LOCAL19 should begin one-at-a-time MCP read-only/search dogfooding with only the
runner canary temporarily visible.

LOCAL19 MCP privacy assessment note: the stdio server registered 27 unique
closed read-only tool schemas, kept all configured graphs hidden, and returned
bounded handshake, method, tool, argument, selection, and parse errors. The
all-hidden `repomap_list_graphs` call nevertheless exposed two absolute
operations-configuration locations in both structured and text content. Source
inspection also found public graph and legacy project/status root values that
conflict with the epic-wide path-free MCP requirement. The phase stopped before
making the runner visible, queried no storage, and removed its raw payloads.
LOCAL20 should add red-green coverage and establish one path-free MCP metadata
contract before LOCAL21 resumes the runner canary matrix.

LOCAL20 MCP metadata correction note: graph listing no longer serializes
operations configuration locations; public, private, legacy-project, and
explicit-development connection roots use stable markers; graph database and
legacy project database values are markerized; and legacy project listing no
longer exposes host/socket, port, or user values. Search and configured
neighborhood results now replace configured path markers for public and private
graphs while internal query routing retains exact configured values. Six
red-green metadata tests, 104 MCP unit tests, five focused PostgreSQL
integrations, the corrected all-hidden 27-tool JSON-RPC probe, and the
2,457-test complete gate passed. All six epic graphs remain hidden and no graph,
database, source, lifecycle, or dependency state changed. LOCAL21 should run
the complete read-only/search matrix with only the runner canary temporarily
visible.

LOCAL21 MCP runner canary note: the runner alone was temporarily MCP-visible
and all 25 graph-applicable tools passed bounded JSON-RPC dogfood, including
pagination, filters, empty results, raw-observation opt-in, canonical
node/edge/explanation/neighborhood readback, project/language summaries,
source/feed absent-state behavior, hidden/missing selection, and isolated
connector and absent-database failures. All 27 schemas remain closed and
read-only; two server-memory bridge tools were inventory-only because they are
outside the six-graph source scope. Privacy scans passed, all six graphs are
hidden again, and runner graph/source fingerprints are unchanged. The legacy
`repomap_status` response exposes legacy-table node/edge counts under generic
names that differ from canonical graph-status counts. LOCAL22 should make that
count model explicit with red-green coverage before the next graph canary.

LOCAL22 legacy MCP count contract note: `repomap_status` and
`repomap_project_summary` now declare `storage_model="legacy"` and expose
`legacy_nodes`, `legacy_edges`, and `legacy_evidence` instead of ambiguous
generic count keys. Their registered descriptions direct canonical-count
clients to `repomap_graph_status`. Two red-green slices, 106 MCP unit tests,
two focused PostgreSQL integrations, the 2,459-test complete gate, and a
current-source runner parity probe passed. The live probe preserved exact
underlying values, routing, redaction, graph/source fingerprints, and hidden
cleanup state. LOCAL23 should continue the complete MCP canary matrix with only
the development-repository graph temporarily visible.

LOCAL23 development-graph MCP canary note: the development graph alone was
temporarily visible and all 25 graph-applicable tools passed current-source
JSON-RPC dogfood across 27 registered schemas. Pagination, filters, empty
results, raw opt-in, canonical explanation and neighborhoods, summaries,
source/feed absent states, hidden and missing selection, malformed requests,
an absent database, response bounds, graph/source fingerprint stability, and
mandatory cleanup passed. The isolated unsupported-connector error still
includes configured runtime topology and a generated local container
identifier. LOCAL24 should correct this MCP-only privacy boundary with
red-green coverage while preserving operational CLI diagnostics before the
next graph canary.

LOCAL24 MCP storage-error redaction note: MCP storage failures now remove the
known operational topology suffix before presentation while retaining the
preceding bounded failure reason. Both direct tool and ops-wrapper conversion
paths share the projection; local operations CLI/runtime diagnostics are
unchanged. One red-green privacy test, 107 MCP unit tests, two focused
PostgreSQL integrations, the 1,908-test unit suite, the 2,460-test complete
gate, and a current-source live unsupported-connector probe passed. The live
probe restored all six graphs to hidden state and preserved development graph
and source fingerprints. LOCAL25 should continue the MCP canary matrix with
only the controller graph temporarily visible.

LOCAL25 controller-graph MCP canary note: the sensitive controller graph alone
was temporarily visible and all 25 graph-applicable tools passed current-source
JSON-RPC dogfood across 27 schemas. Pagination, filters, empty results, raw
opt-in, canonical explanation and neighborhoods, summaries, source/feed absent
states, hidden/missing selection, malformed requests, sanitized connector and
absent-database failures, response bounds, graph/source fingerprint stability,
and mandatory cleanup passed. Its single warning is the expected private-graph
readback marker. LOCAL26 should continue the one-at-a-time matrix with the
private flakes graph.

LOCAL26 flakes-graph MCP canary note: the private flakes graph alone was
temporarily visible and all 25 graph-applicable tools passed current-source
JSON-RPC dogfood across 27 schemas. Pagination, filters, empty/raw policy,
canonical explanation and neighborhoods, summaries, source/feed absent states,
bounded failures, strict private-config redaction, graph/source fingerprint
stability, no-Nix-execution protection, and mandatory cleanup passed. Its one
warning is the expected private readback marker. LOCAL27 should continue with
the private Codex configuration graph.

LOCAL27 Codex configuration MCP canary note: the private-operations graph alone
was temporarily visible and the functional matrix completed across 27 schemas,
all 25 graph-applicable tools, pagination, filters, empty/raw policy, canonical
readback and neighborhoods, summaries, source/feed state, and 12 bounded
failure routes. Graph, protected-source, overlay, and hidden-state cleanup
checks passed unchanged. The strict privacy scan found that canonical-edge
list metadata exposes an absolute source-derived value through
`metadata.values`; edge explanation repeats it through edge metadata and
evidence `metadata.raw` and `metadata.value`. LOCAL28 must correct those MCP
presentation field families with red-green coverage before another private
graph is exposed.

LOCAL28 private canonical metadata correction note: private graph-registry
canonical node, edge, explanation, and neighborhood payloads now reuse the
configured-marker sanitizer at the MCP presentation boundary while preserving
canonical and evidence identities. Public and explicit storage payloads remain
unchanged. Two focused red-green cases, 109 MCP unit tests, focused PostgreSQL
integration, the 2,462-test complete gate, coverage gates, Go gates, container
smoke, compileall, file lengths, and current-source live privacy validation
passed. LOCAL29 should exercise the final sensitive graph through the complete
isolated MCP canary matrix.

LOCAL29 Codex memories MCP canary note: the final sensitive graph alone was
temporarily visible and all 25 graph-applicable tools passed across 27 closed
schemas with bounded filters, pagination, offsets, empty results, default and
explicit raw policy, source/feed absent states, summaries, canonical
explanation/neighborhoods, and 12 failure routes. Protected-source, graph,
overlay, privacy-artifact, and cleanup checks passed. The canonical node and
edge list tools expose no `limit` or `offset`; unfiltered responses exceeded
the 400,000-byte canary ceiling even on this modest graph. LOCAL30 must add
deterministic pagination and default bounds without changing canonical
identity or the LOCAL28 privacy contract.

LOCAL30 canonical MCP pagination note: canonical node and edge list tools now
apply deterministic `limit` and `offset` pagination with a 50-record default
and 200-record maximum. Filters and ordering precede pagination, the JSON list
shape and canonical identities remain unchanged, private presentation retains
LOCAL28 redaction, and non-MCP storage callers retain their unbounded default.
Eight focused red-green tests, 113 MCP unit tests, 40 canonical readback unit
tests, focused PostgreSQL integration, and the 2,470-test complete gate passed.
Current-source validation produced non-overlapping pages and kept default and
maximum responses below the 400,000-byte ceiling. All six graphs are hidden
and graph state is unchanged. LOCAL31 should assess and design canonical
migration or intentional removal of `storage files`, the first exact
legacy-default command.

LOCAL31 storage-files canonical assessment note: the exact legacy command is
`repomap-kg storage files`, registered in the storage parser and dispatched
through legacy `files`/`repositories` readback. Six-graph evidence found 2,847
legacy rows, all with complete canonical file counterparts, plus 508
evidence-backed referenced-only canonical file nodes. The current command is
unbounded, root/connection-scoped, filters after full readback, and silently
returns empty success for an unknown root. LOCAL31 accepts a backwards-
incompatible replacement: remove `storage files` and add canonical, configured,
graph-scoped `ops graph-files` with explicit observed/referenced state,
deterministic candidate arrays, evidence counts, stable JSON/table contracts,
and 50-default/200-maximum pagination. No legacy fallback or alias is retained.
LOCAL32 should implement this contract with red-green tests and migration docs;
LOCAL33 should perform six-graph parity evaluation.

LOCAL32 canonical graph-files implementation note: public `storage files` is
removed without an alias or fallback and replaced by `ops graph-files` with
required graph selection, canonical/evidence-only readback, deterministic
filters and ordering, 50-default/200-maximum pagination, decoded canonical
file paths, bounded candidate/evidence fields, and stable JSON/table output.
Twelve focused unit tests, five focused PostgreSQL tests, and six-graph live
readback passed. The live matrix read 3,355 canonical file nodes as 2,847
observed and 508 referenced, with every 200-record page below 121,000 bytes;
graph summaries, baselines, and protected-source fingerprints were unchanged.
LOCAL33 should evaluate legacy-to-canonical parity and the completed migration
contract across all six graphs.

LOCAL33 graph-files parity note: all 2,847 legacy file rows matched observed
canonical rows across 14,235 language, role, generated, executable, and
confidence comparisons with zero differences. The replacement additionally
returns 508 disjoint evidence-linked referenced-only files, for 3,355 bounded
canonical rows with no ambiguity. Complete pagination, 102 grouped CLI
filter/table/JSON operations, bounded negative paths, privacy checks, and
before/after source, graph-summary, graph-baseline, and stored-baseline
fingerprints passed across all six enabled, MCP-hidden graphs. The first legacy
migration sequence is complete. LOCAL34 should assess and design migration of
the exact second command, `repomap-kg storage entrypoints`.

LOCAL34 storage-entrypoints assessment note: the command is only the legacy
`files.role == "entrypoint"` subset, not a cross-language framework-entrypoint
model. All 58 legacy rows matched observed canonical graph files across 290
field comparisons with zero differences; candidate pagination and bounds
passed, and one framework-specific entrypoint observation remained raw-only
with no canonical node or edge link. Remove `storage entrypoints`, its orphaned
legacy file query/SQL compatibility surface, and its connector-comparison case
without an alias. Migrate stored callers to `ops graph-files --graph
<graph-id> --role entrypoint --observation-state observed`; retain the distinct
top-level raw-JSONL `entrypoints` command unchanged. LOCAL35 should implement
this contract, and LOCAL36 should evaluate parity and removal.

LOCAL35 storage-entrypoints removal note: `storage entrypoints` is removed
without an alias or fallback together with its orphaned file-row query, SQL
builder, payload parser, compatibility exports, and connector-comparison case.
Stored callers use `ops graph-files --graph <graph-id> --role entrypoint
--observation-state observed`; the distinct top-level raw-JSONL `entrypoints`
command remains intact. Focused red-green tests, connector parity, the 2,473-
test full gate, and six-graph live validation passed. The canonical replacement
returned the accepted 58-row population in bounded pages, emitted no private
root or database values, kept all graphs hidden, and left every protected
source fingerprint unchanged. LOCAL36 should evaluate published parity and
complete the second legacy migration sequence.

LOCAL36 storage-entrypoints parity note: published help and parser behavior
reject the removed command with exit 2, all orphaned file-row query/SQL/parser
and connector-comparison names are absent, and the raw-JSONL `entrypoints`
command remains distinct. Stable-scope direct legacy counts and complete
canonical graph-file role/state readback both returned 58 rows with exact
per-graph populations. Default/maximum pagination, byte-identical repeats,
JSON/table privacy, negative paths, hidden-state checks, and before/after
source, graph-summary, and graph-baseline fingerprints passed. The second
legacy migration sequence is complete. LOCAL37 should assess and design
migration or intentional removal of the exact third command, `storage
file-nodes`.

LOCAL37 storage-file-nodes assessment note: the command joins every legacy
evidence row co-located in a file to the file's legacy node without a node-
evidence relation. Across the six graphs it would emit 72,555 unbounded rows,
approximately 53.9 MB of JSON; 11,725 rows do not correspond to an exact
canonical evidence link on the canonical file node, and one exact-path result
can reach 4,682 rows. Remove `storage file-nodes`, its record/query/SQL/
presentation compatibility surface, and its `legacy_file_node_records`
connector-comparison case without an alias or fallback. Use bounded configured
`ops graph-files` for canonical file identity and aggregate evidence,
canonical neighborhood and edge-explanation surfaces for graph context, and
explicitly named bounded observation search for raw evidence. LOCAL38 should
implement the removal and migration guidance; LOCAL39 should evaluate the
published result.

LOCAL38 storage-file-nodes removal note: `storage file-nodes` is removed
without an alias, fallback, or replacement evidence command together with its
orphaned record, decoder, query, SQL, JSON/table, facade, CLI, and connector-
comparison compatibility surface. Canonical file-list callers use bounded,
configured `ops graph-files`; canonical neighborhood and edge explanation
retain graph context and linked evidence; explicitly named MCP observation
search retains bounded raw access. The 2,463-test complete gate passed at 94.1
percent line and 87.0 percent branch coverage with Go gates and container
smoke. The six-graph live matrix returned 3,355 bounded canonical files as
2,847 observed and 508 referenced, with maximum pages below 121 KB, stable
graph and source fingerprints, and no private topology in output. LOCAL39
should evaluate the published removal and complete the third legacy migration
sequence.

LOCAL39 storage-file-nodes parity note: published help and parser behavior
reject the removed command with exit two; all six obsolete Python names and the
connector-comparison operation are absent; and remaining legacy modes,
canonical CLI surfaces, and exact canonical/raw MCP registrations remain
available. Complete six-graph pagination reproduced 3,355 canonical files as
2,847 observed and 508 referenced, with deterministic non-overlapping pages,
default and maximum bounds, exact and empty paths, JSON/table output, selected
connectors, bounded failures, private-root redaction, and stable graph,
baseline, and source fingerprints. The third legacy migration and all epic
runtime/API acceptance work are complete. LOCAL40 should perform the final
docs-only epic closure and record the authorized scale/storage deferrals.

LOCAL40 local-operations closure note: the contiguous LOCAL0–LOCAL39 ledger has
40 complete status records, gates, and approved reviews. Both clean six-graph
backup-first destructive cycles, CLI read-only/lifecycle/failure matrices,
isolated MCP matrices, bounded privacy/output corrections, source protection,
and all three legacy removals and parity evaluations pass. The final 2,463-test
gate passed at 94.1 percent line and 87.0 percent branch coverage with Go gates
and container smoke. Stored drift is false on all six graphs; current flakes
and controller preflight inventory drift is attributable to authorized
concurrent source development, has no safety drift, and is deferred to routine
post-development refresh. The epic is closed. Language-neutral high-scale set-
based or COPY ingestion and language-neutral transactional incremental storage
remain deferred outside the first release.

LOCAL41 retrospective architecture note: ADR 0038 in
`docs/adr/2026/07/0038-local-operations-and-canonical-readback-architecture.md`
accepts the architecture established and tested by LOCAL0–LOCAL40 with explicit
review triggers. ADR-first planning remains the default; retrospective ADRs are
reserved for explicitly declared experimental or discovery-led epics with a
mandatory closing ADR. No present revision is required, LOCAL remains closed,
and no LOCAL42 phase is selected.

ASYNC0 execution-architecture note: ADR 0039 in
`docs/adr/2026/07/0039-synchronous-and-asynchronous-architecture.md` retains
synchronous forced-full execution for the first release and selects a hybrid
Python asynchronous coordinator with durable PostgreSQL-backed jobs and bounded
synchronous workers as the long-term target. The synchronous CLI remains a
facade over one semantic implementation; MCP remains read-only. Synchronous
Psycopg stays the current adapted-readback default and `psql` stays the mutation,
lifecycle, and fallback transport. A bounded Psycopg async pool is the first
future control; asyncpg, Go, Rust, high-scale storage, and transactional
incremental storage remain evidence-gated. ASYNC1 will define the durable job
contract and coordinator boundary before implementation.

ASYNC1 durable-contract note: the accepted design in
`docs/specs/durable-job-and-coordinator-contract.md` fixes the versioned job
envelope, state machine, claims, durable graph leases, singleton fencing,
idempotency, coalescing, source/configuration generations, bounded JSONL worker
protocol, publication reconciliation, cancellation, progress, retry,
retention, local transport, authorization, backpressure, watcher hints, and
formal invariants selected by ADR 0039. Lifecycle remains CLI-owned, MCP remains
read-only, and no production, schema, migration, dependency, graph, or runtime
change occurs in ASYNC1. ASYNC2 should prove the contract with a disposable
synthetic control database and synthetic workers before any real graph refresh
integration.

ASYNC2 synthetic-pilot note: the internal coordinator package and isolated
control-schema migration prove durable submission, idempotency, ordered claims,
graph leases, singleton fencing, state compare-and-set, publication markers,
reconciliation, cancellation, retry, coalescing semantics, bounded progress,
retention, strict JSONL subprocess ownership, and authenticated test-owned local
transport with public-safe synthetic evidence. No configured graph, graph schema,
public CLI, MCP, lifecycle authority, production service default, or dependency
changed. ASYNC3 may package the synthetic coordinator service and client boundary;
real refresh integration remains deferred to ASYNC4.

ASYNC3 service-seam note: the bounded synthetic coordinator is packaged behind a
structured, non-self-daemonizing service and an explicit synchronous local client.
Startup recovery precedes readiness; claim and singleton-heartbeat tasks have
separate ownership; restart rotates private endpoint credentials; shutdown drains
and joins owned tasks before releasing fencing authority; and connection failure
never triggers direct fallback. The phase adds no public CLI, MCP mutation, service
manager, configured graph access, dependency, or real refresh adapter. ASYNC4 should
prove one real forced-full worker/publication adapter behind an explicit non-default
pilot.

ASYNC4 forced-full-adapter note: one explicit production worker now delegates exactly
once to the existing `ops.refresh_graph` implementation through the ASYNC2 JSONL and
process-supervision boundary. A private single-attempt capability carries only
coordinator-resolved authority and is deleted after cleanup. Disposable direct,
worker, and durable-coordinator paths demonstrate result parity without changing CLI,
MCP, defaults, schemas, dependencies, or configured graphs. The existing graph run
identity is committed evidence, but graph storage does not yet atomically persist all
four ASYNC1 generation tokens. ASYNC5 should close that publication fence before
watcher work or coordinator adoption.

ASYNC5 publication-generation-fence note: the existing graph `runs` transaction now
optionally commits source, configuration, extractor, and canonicalizer generations as
one all-or-none receipt. The streamed load reads the committed receipt back before a
worker may report success, while direct refreshes retain the legacy all-null shape.
Resolver generations must match the claimed job before capability creation. This
closes generation authenticity but not crash attribution: `runs` does not yet retain
coordinator job and attempt identity. ASYNC6 should add that identity and bounded
graph-to-control reconciliation before configured coordinator adoption.

## Verification Strategy For Refactor Phases

Docs-only refactor checkpoints use:

```sh
git diff --check
git diff --cached --check
```

Source/test refactor phases use proportional local verification justified by
the slice: affected unit tests, affected integration tests when integration or
storage behavior changes, the affected smoke path when runtime behavior
changes, and relevant compile/static checks. Every phase also uses:

```sh
git diff --check
git diff --cached --check
```

Integration selections must use the containerized Postgres harness. The hosted
`repomap-staging-gate` owns routine complete verification across unit, integration,
coverage, container smoke, and Docker accounting. The local `heavy` all-suite
gate remains available for explicit operator diagnostics, explicit local
qualification campaigns, and rare whole-population reproductions under
`testing-standards.md`.

For an explicit operator diagnostic, explicit local qualification campaign, or
rare whole-population reproduction, use the supported local complete-gate
example:

```sh
python3 tools/run_tests.py \
  --suite staging \
  --hygiene-profile heavy \
  --declared-complete-gates 1 \
  --pg-container-port 55433
```

## Dependency Stance

REF2 adds no dependencies and recommends no immediate dependency adoption.

Later phases may evaluate dependencies only when the local refactor work shows
a concrete problem:

- clear performance bottleneck;
- clearer expression of a difficult domain;
- meaningful reduction in code size or maintenance burden;
- stronger correctness for parsing or graph work.

Any dependency proposal must answer:

- What problem does it solve better than small local code?
- Does it improve performance, readability, or maintenance?
- Is it stable and maintained?
- Is it compatible with RepoMap packaging, smoke, CLI, MCP, storage, and test
  environments?
- What transitive and operational risk does it add?

## Private-Data Boundary

Refactor phases must not commit private graph data, database dumps, backup
receipts, raw private observations, source snippets, local machine config, or
secrets. Inventory should report module structure and counts, not private
payloads.

### ASYNC6 publication-attempt reconciliation

ASYNC6 adds an all-or-none coordinator job and attempt identity to the authoritative
graph run receipt and a bounded completed-run readback. A disposable integration test
proves that a lost committed worker terminal resolves through the existing control
marker classifier only after exact graph receipt readback. Direct refreshes retain
null receipt fields. The full repository gate passed with 2,813 tests, 93.6 percent
line coverage, 86.2 percent branch coverage, Go validation, and container smoke.
Configured graph adoption and public coordinator mode remain deferred to ASYNC7.

### ASYNC7 configured service composition

ASYNC7 composes one owner-configured graph with the existing local coordinator service,
production refresh worker, generation fence, and publication reconciliation readback.
Public requests are validated before static source discovery; all four generations are
owner-resolved; execution generations are revalidated in the worker; and the source
generation is derived from the exact observation set before transaction start. Direct
mode remains the public default. The full repository gate passed with 2,822 tests,
93.5 percent line coverage, 86.1 percent branch coverage, Go validation, and container
smoke. Startup recovery and public mode selection remain deferred to ASYNC8.

### ASYNC8 configured startup recovery

ASYNC8 adds a stable bounded startup scan for current reconciliation-required attempts
and runs exact graph-receipt reconciliation under the newly acquired singleton fence
before the local service accepts clients. A disposable restart proves that a committed
configured attempt with a lost control terminal reaches succeeded. Changed storage
routes and unavailable graph evidence remain paused and appear only as bounded count
categories. The full repository gate passed with 2,827 tests, 93.5 percent line
coverage, 86.1 percent branch coverage, Go validation, and container smoke. Public mode
selection remains deferred to ASYNC9.

### ASYNC9 explicit local coordinator mode

ASYNC9 adds a foreground-only local coordinator launch command and an explicit
coordinator-backed `refresh-graph` mode. Direct execution remains the default.
Coordinator clients supply only a configured graph ID and durable idempotency identity;
the service derives its authenticated endpoint, executable authority, and dedicated
control-database identity from an owner-private RepoMap home. Launch checks an existing
compatible control schema and never initializes or migrates it. Disposable integration
proves configured refresh, terminal replay, single publication, bounded startup refusal,
and endpoint cleanup. Explicit control-database lifecycle remains deferred to ASYNC10.

### ASYNC10 control database lifecycle

ASYNC10 adds read-only control status and explicit control initialization commands for
the derived local coordinator database. One shared private authority now supplies both
lifecycle and foreground launch. Initialization creates only the absent derived database,
installs or validates only the isolated version-1 schema, replays idempotently, and fails
closed for incompatible existing state. Launch remains check-only and never initializes
implicitly. Disposable integration proves creation, replay, incompatibility refusal, and
launch-after-init. Resumable local job status, wait, and cancellation remain for ASYNC11.

### ASYNC11 resumable local job control

ASYNC11 adds authenticated local status, bounded wait, and cancellation commands for one
explicit existing durable job. The adapter reuses the version-1 local transport, validates
job identity and state, and never resubmits or queries the control database directly.
Disposable integration proves status and terminal wait can resume from a prior refresh
job ID. Bounded recent-job listing remains for ASYNC12.

### ASYNC12 bounded recent-job listing

ASYNC12 adds one authenticated read-only recent-job page with a strict 1-to-32 row bound,
optional exact graph filtering, and canonical newest-first keyset continuation. Results
contain only public job identity, state, and UTC submission time. The service owns the
parameterized store query; clients cannot select SQL, sort, state, requester, or payload.
No schema or retention policy changes. Native user-service packaging remains for ASYNC13.

### ASYNC13 portable user-service packaging

ASYNC13 defines one normalized platform-neutral coordinator service specification and
translates it through macOS launchd and Linux systemd per-user adapters. Both adapters
invoke the same foreground coordinator module with a pre-resolved validated `psql`
dependency, use exact argument vectors without a shell, retain only a fixed locale/time-zone
environment allowlist, and keep installation, status, start, stop, restart, upgrade,
validation, rendering, and removal behind one neutral operator CLI. Launchd installation
is disabled by default until an explicit start. Owner-safe generated files, final
pre-mutation identity checks, atomic publication, unrecognized-file refusal, and
native-state rollback are tested. Foreground operation remains independent on currently
supported coordinator platforms; MCP, direct mode, schemas, storage, dependencies, and
automatic client repair are unchanged. Windows remains an architectural target; ASYNC14
should prove its local transport, foreground runtime, and Job Object process supervision
before selecting the native Windows startup adapter.

### ASYNC14 Windows coordinator runtime boundary

ASYNC14 defines and provisions proof of the platform seams required for the common
service contract on a real Windows runner without forking coordinator semantics.
Windows uses authenticated loopback TCP on `127.0.0.1` with an ephemeral port, a random
startup token, and an owner-ACL descriptor containing only endpoint and fencing metadata.
Workers launch suspended, join a kill-on-close Job Object before resume, and expose
graceful versus forceful cleanup through the same process-supervision interface used by
POSIX process groups. Windows path/reparse validation, owner-private refresh
capabilities, exact `psql.exe` resolution, `os.devnull`, an explicit `SystemRoot`
runtime prerequisite, and a standard-library cooperating mutation lock are explicit
adapters. The foreground coordinator remains the canonical module and direct mode
remains independent; the disposable Windows workflow now proves the runtime boundary.
Native startup authority remains deferred to ASYNC15.

Named pipes remain a review trigger because they would add ACL, asyncio, cancellation,
packaging, and testing complexity without a demonstrated advantage over authenticated
loopback. Task Scheduler and Windows Service packaging are not selected in ASYNC14:
the former needs current-user logon/lifetime evidence and the latter introduces a
service-account authority boundary. ASYNC15 is reserved for a focused Windows startup
adapter decision or a bounded correction if the native proof identifies a defect.

### ASYNC15 Windows startup adapter decision

ASYNC15 runs a disposable native Task Scheduler probe for both `InteractiveToken` and
passwordless `S4U` principals. Registration, structured query, exact foreground argv,
current-user identity, least-privilege intent, manual run, bounded end, deletion,
repeat-delete refusal, and private temporary-directory cleanup pass on the Windows
Server 2025 runner. The runner is an elevated administrator in a non-interactive
session, so these facts do not prove ordinary-user installation or removal. `psql.exe`
is unavailable, so no RepoMap control-database or credential-file canary is claimed.

No native Windows background adapter is selected. Task Scheduler remains a bounded
future candidate only after standard-user and real RepoMap/PostgreSQL evidence proves
the current-user contract. Windows Service remains deferred because it requires an
explicit service-account, profile, credential, session-zero, ACL, and elevated
machine-authority design. Windows foreground coordinator operation remains supported
and the neutral CLI fails explicitly without cross-platform fallback. The next phase is
desired-state polling/watch work; Windows packaging may be revisited as a bounded
authority correction or dedicated service-account design.

### ASYNC16 desired-state polling and repository reconciliation

ASYNC16 adds the polling-first desired-state reconciler selected by ADR 0039. A
bounded standard-library source inventory hashes sorted repository-relative file
records with content digests, detects source instability, honors configured
exclusions, rejects symlink/reparse paths, and enforces file, byte, path, retry,
timeout, and cancellation limits. The same `sg1` inventory helper is used by
polling and the forced-full refresh fence, so dirty Git and non-Git roots do not
depend on commit or modification time alone.

Enabled `polling` and `continuous` graph policies participate in one
coordinator-owned scheduler; `manual` remains operator-only and `startup_check`
and `watch` remain deferred. Desired source, configuration, extractor, and
canonicalizer generations are compared with the latest complete publication
receipt. Mismatches use the existing automatic `refresh_graph` coalescing path;
unchanged receipts record current state; unavailable or unstable sources retain
the last good graph and schedule a bounded retry. Duplicate polls, queued
replacement, one running follow-up, manual intent, fencing, and publication
reconciliation remain durable contracts.

Polling schedule state is reconstructable in memory and uses monotonic waits with
bounded deterministic jitter; existing `coalescing_state.next_reconcile_at` is
updated without a migration. Health exposes only bounded counts/categories. The
service owns scheduler lifecycle, cancellation, restart rescan, and shutdown.
The later watcher seam is a path-free hint protocol only; no watcher dependency,
native watcher API, raw event persistence, MCP mutation, or Windows startup work
is introduced. Windows foreground polling/path tests are repeatable through the
repository-controlled ASYNC16 workflow; a native Windows run is not claimed until
that workflow executes.

### ASYNC17 watcher dependency evaluation

ASYNC17 evaluates native inotify, FSEvents, and ReadDirectoryChanges behavior,
the cross-platform `watchdog` package, the Rust-backed `watchfiles` package,
and direct native wrappers against the polling-first authority contract. Queue
or buffer overflow, event loss/reordering, sleep/wake, downtime, network
filesystems, and unsupported roots all require a complete polling rescan. The
evaluation selects no watcher dependency or implementation: `watchdog` would
add threaded native backends and documented per-platform caveats, while
`watchfiles` would add a compiled Rust/Notify dependency and wheel/source-build
obligations. Direct wrappers would duplicate cancellation and overflow logic.

The existing path-free `WatcherAdapter` hint seam remains the only accepted
boundary. ASYNC18 hardens polling operations and does not reopen watcher
implementation; any later watcher work still requires disposable native
canaries and an explicit dependency decision. Polling remains authoritative and
no watcher events are persisted.

### ASYNC18 multi-graph polling and coordinator operational hardening

ASYNC18 hardens polling for bounded multi-graph local operation. A
coordinator-owned standard-library worker pool admits a fixed number of polls,
prevents overlap for one graph, orders due work by eligibility, failure/backoff
class, last completion, and stable graph ID, and drains startup or wake backlog
in bounded batches. Graph-local source, configuration, publication, timeout,
and cancellation failures use capped exponential backoff and remain isolated
from the coordinator heartbeat, transport, active refresh workers, and manual
intent. Successful current, requested, and coalesced outcomes reset the graph
failure count; retry does not create a second queue or a job per interval.

Configuration reload adds eligible graphs and stops future scheduling for
disabled, manual, or removed entries without deleting product graph state.
Health is a bounded path-free scalar projection covering capacity, backlog,
outcome categories, backoff, oldest due age, and shutdown. Existing durable
coalescing, graph leases, fencing, publication receipts, and retention remain
authoritative. No schema migration, dependency, watcher implementation, raw
event persistence, MCP mutation, Windows startup packaging, or incremental
graph mutation is introduced. The next phase is coordinator operator adoption
and default-mode evaluation after end-to-end evidence.

### ASYNC19 coordinator operator adoption and default-mode evaluation

ASYNC19 makes the coordinator recommended for routine local operation while
keeping selection explicit and leaving the direct refresh default unchanged for
compatibility and recovery. The CLI now exposes one authenticated,
read-only `coordinator-health` inspection command and a versioned, bounded
health projection with stable service, ownership, queue, worker, publication,
polling, transport, and storage sections. Sections without an authoritative
provider report `not_reported` rather than inventing queue or freshness facts.

Foreground startup, control-state lifecycle, durable refresh submission,
recent-job inspection, cancellation, restart, and shutdown remain explicit
operator actions. macOS launchd and Linux systemd packages remain optional
wrappers around the same foreground entrypoint; WSL is documented as a
Linux-style foreground pattern; Windows remains foreground-only. No service
manager is automatically installed or started, and coordinator failure never
falls back to direct mode. MCP remains read-only and no new dependency, schema,
watcher, Windows background adapter, or private graph access is introduced.

The next bounded phase is ASYNC20 end-to-end dogfood and failure recovery before
the final ASYNC closure decision.

### ASYNC20 end-to-end dogfood and failure-recovery campaign

ASYNC20 repeats the accepted coordinator workflows against synthetic
public-safe repositories and disposable PostgreSQL fixtures. Eleven grouped
campaign runs produced 536 passed tests, 4 skipped platform/service-package
tests, and no failures. Normal startup, reconciliation, refresh, coalescing,
manual intent, cancellation, restart, shutdown, process supervision,
publication uncertainty, storage and source failure classification, transport
rotation, configuration reload, polling backoff, and cleanup all remained
bounded. No orphan process, endpoint, lease, or temporary service artifact was
observed by the disposable cleanup assertions.

Machine lifecycle behavior used deterministic restart, wake, missed-interval,
clock, descriptor, and token simulations. Native Windows, WSL, launchd, and
systemd canaries were not available in this environment; the accepted ASYNC14
Windows foreground evidence and optional ASYNC13 adapters remain unchanged.
No source, schema, dependency, MCP, watcher, Windows background, or default-mode
change was required. The final ASYNC20 decision is that the architecture is
ready for closure, with ASYNC-CLOSE limited to consistency review, full-gate
verification, and documentation cleanup.

### ASYNC-CLOSE durable coordinator architecture acceptance

ASYNC-CLOSE accepts and closes the bounded local ASYNC architecture. The final
contract is one semantic coordinator and durable job state machine with one
mutating graph lease, singleton fencing, complete publication receipts,
polling-first desired-state reconciliation, explicit direct/coordinator mode,
read-only MCP, and CLI-owned lifecycle. The coordinator remains usable in the
foreground on every supported Python platform.

macOS launchd LaunchAgents and Linux systemd user units remain optional
platform-neutral service-package adapters around the exact foreground
entrypoint. Windows foreground transport and Job Object containment remain
supported; native Windows background packaging remains deferred. WSL remains a
Linux-style foreground deployment pattern. No watcher dependency or native
watcher implementation was selected.

The ASYNC20 campaign recorded 536 passed tests, 4 skipped, and no failures in
eleven grouped disposable runs. The closure gate recorded 3,049 passed tests,
7 skipped, 92.8% aggregate line coverage, 85.2% aggregate branch coverage,
passing container smoke, compileall, file-length, and diff checks, with no
dependency metadata changes. The default PostgreSQL test listener was preserved
and no configured private graph was accessed.

Future watcher acceleration, Windows native background packaging, SQLite/Desktop
or cloud architecture, incremental graph updates, remote workers,
multi-coordinator scaling, and high-scale ingestion are separate future epics.
The ASYNC architecture is closed; no deferred feature is implemented by this
closure record.

### SCALE — High-Scale Full-Refresh Ingestion

The ASYNC epic and the Go epic through GO23 remain closed. SCALE is the
language-neutral architecture epic for the remaining forced-full storage
throughput boundary. Its objective is to make authoritative full refresh
practical at Argo CD scale while preserving deterministic graph output, one
publication authority, all-or-nothing final mutation, bounded cancellation,
and public-safe operation.

### SCALE0 high-scale full-refresh ingestion architecture decision

SCALE0 accepts durable regular attempt-scoped staging, the existing Psycopg 3
COPY protocol as the later bulk transport boundary, set-based validation and
merge, and one final transaction that revalidates ASYNC lease, fencing,
generations, staging ownership, and receipt authority before committing
publication. Staging completion, COPY completion, queue completion, and worker
exit are not publication proof. `psql` remains the explicit fallback and
comparison oracle. No production ingestion, final-schema, dependency, graph,
or private-source change is part of SCALE0.

The public-safe disposable probe measured row-wise, multi-row, pipelined, and
COPY/set-based controls and confirmed injected rollback and bounded
cancellation. The modeled current storage-family path remained proportional to
row count; the selected architecture makes the write protocol and merge work
family-shaped. The probe is not Argo CD performance proof.

The next bounded phases are expected to cover staging ownership and schema,
COPY encoding, legacy/raw merge, canonical merge, publication fencing and
reconciliation, failure injection, performance calibration, intermediate
dogfood, protected Argo CD dogfood, and final closure. The final closure must
issue exactly one GO24 recommendation. SCALE does not create GO24
automatically, and storage speed alone is not sufficient to reopen the Go
epic.

### SCALE1 staging ownership, schema, and legacy-family decision

SCALE1 confirms that `files`, legacy nodes, legacy evidence, and legacy edges
remain required to preserve the current forced-full write and read contracts.
`files` remains product storage; the other three families remain explicit
compatibility projections and are scheduled for separate bounded
decommissioning only after executable parity evidence. SCALE1 does not remove
any legacy family or change public CLI, MCP, connector, summary, baseline, or
drift semantics.

The phase adds one additive migration for durable regular attempt-scoped stage
ownership and ten stage row families. The header carries graph, operation,
job/attempt, direct/coordinator, fencing, generation, completeness,
validation, merge, reconciliation, expiry, and cleanup metadata. A minimal
graph-local monotonic publication-authority projection is added because ASYNC
control and graph state use separate databases; it is not a second coordinator
or publication proof. Cleanup reconciles receipts and ownership before
stage-owned deletion, and rollback refuses unresolved or quarantined stages.

The pure contract and disposable migration tests pass. No COPY transport, final
set-based merge, staging publication, cleanup daemon, dependency, private Argo
CD access, or GO24 work is part of SCALE1. The next bounded phase is SCALE2 for
strict row encoding and the existing Psycopg 3/psql COPY boundary.

### SCALE2 COPY encoding and transfer

SCALE2 establishes the existing Psycopg 3 `Cursor.copy()` / `write_row()`
transport for exactly the ten retained stage families. It uses a closed
repository-owned table catalog, fixed typed column order, explicit JSONB
adaptation, stage ownership checks, and caller-owned transaction boundaries.
COPY completion is transfer evidence only and cannot publish a graph or prove a
receipt. The phase adds no dependency, binary-loader path, connector fallback,
final merge, cleanup daemon, or private Argo CD access. The next bounded phase
is SCALE3 for set-based validation and retained legacy/raw merge design.

### SCALE3 retained legacy and raw set-based merge

SCALE3 establishes the caller-owned set-based mutation boundary for `files`,
legacy nodes, legacy evidence, legacy edges, and raw observations. It preserves
the existing final schemas, repository-scoped stable identities, file/evidence
joins, raw run/ordinal identity, current conflict-update columns, and all
legacy compatibility readback. A complete SCALE1 stage-owner tuple and
repository run are checked in the graph-local stage guard; ASYNC authority,
publication receipts, and final fencing remain SCALE5 responsibilities.

The merge consists of eight fixed SQL statements: owner/run validation,
duplicate and raw-hash guards, five retained-family set-based operations, and
edge-reference validation. Exact duplicate proposals use the lowest stable
ordinal; conflicting payloads or missing edge references fail before any
publication claim. The caller owns the transaction, and disposable PostgreSQL
tests prove upsert, repeat idempotency, duplicate refusal, missing-reference
refusal, and injected rollback. No canonical merge, publication, cleanup
daemon, legacy API removal, dependency, connector fallback, or protected Argo
CD access is part of SCALE3. The next bounded phase is SCALE4 for canonical
set-based merge.

### SCALE4 canonical set-based merge

SCALE4 adds a caller-owned set-based merge for canonical nodes, canonical
evidence, canonical edges, and both canonical evidence-link families. It keeps
the final schemas, canonical identities, graph-key versions, existing
conflict-update semantics, foreign keys, public readback, baseline/drift
meaning, and the SCALE1 legacy compatibility decision unchanged. Exact
duplicate stage proposals are reduced by stable family ordinal; conflicting
typed payloads and missing raw/graph references fail before dependent mutation.

The fixed eleven-statement builder reuses the SCALE3 stage-owner guard and
leaves transaction control with the caller. It does not publish, write receipts,
update ASYNC authority, delete old graph rows, clean staging, remove legacy
APIs, add dependencies, or access the protected Argo CD clone. Focused
synthetic PostgreSQL evidence proves idempotent canonical readback and caller
rollback. The next bounded phase is SCALE5 for publication fencing,
authoritative receipt handoff, and commit-unknown reconciliation.

### SCALE5 — publication fencing and reconciliation

SCALE5 accepts the graph-local final publication handoff for the staged
set-based ingestion path. Existing ASYNC control authority remains in the
control database. Before the final graph transaction, the authority adapter
must revalidate the job, attempt, singleton, graph-lease, and generation
claim. Inside the graph transaction, the exact stage owner and run receipt are
locked, the graph-local monotonic authority projection is locked and checked
for higher fences, and the final receipt, authority projection, and published
stage are committed together.

The known-commit path explicitly permits `merging` → `published`; staging,
COPY, validation, merge completion, queue completion, and worker exit are not
publication proof. Direct mode uses the same implementation with an explicit
local operation/attempt and no fabricated coordinator job. Commit-unknown
reconciliation is receipt-first: matching commits, proved absence permits
failed/cancelled disposition, conflict quarantines, and insufficient evidence
remains blocked.

SCALE5 adds no dependency, migration, final-table change, public-read change,
legacy API removal, connector fallback, cleanup daemon, or protected Argo CD
access. Focused disposable PostgreSQL evidence covers stale fencing, atomic
receipt handoff, rollback, idempotent replay, and commit-unknown outcomes.
The next bounded phase is `SCALE6` for cancellation, rollback, cleanup, and
failure injection.

### SCALE6 cancellation, rollback, cleanup, and failure injection

SCALE6 closes the failure and cleanup boundary for the ten retained staging
families. The caller-owned cleanup contract requires exact stage ownership,
expired reconciled publication state, an explicit no-live-attempt proof, and a
bounded batch size. It deletes only stage-owned rows, retries through
`cleanup_pending`, and reaches `cleaned` only after all owned rows are gone.
Commit-unknown and quarantined stages remain blocked; final graph rows are not
part of cleanup and no cleanup daemon is introduced.

Disposable PostgreSQL evidence proves that an injected failure after final
merge work and before the complete receipt rolls back final graph mutation,
receipt, authority, and publication state. Proved-absence reconciliation then
permits explicit cancellation and cleanup. A separate cleanup failure rolls
back all cleanup mutation and is retryable. Focused unit and disposable
PostgreSQL evidence passes `23` tests. No migration, dependency, final-schema
change, public-read change, legacy API removal, private repository access, or
GO24 work is part of SCALE6.

The next bounded phase is `SCALE7`, public-safe performance and resource-bound
calibration for COPY, set-based merge, cancellation, cleanup, and publication.

### SCALE7 performance and resource calibration

SCALE7 calibrates the accepted COPY and set-based merge shape with generated
public-safe workloads. The disposable helper compares current streamed
per-row SQL with ten Psycopg 3 COPY transfers followed by eight retained
legacy/raw and eleven canonical merge executions in one caller-owned
transaction. All ten family row vectors match at generated sizes 4, 16, and
64. Current wire statement counts are 85, 325, and 1,285; staged data-plane
wire count is 29. Two post-fix size-64 timings remain within
`0.174062–0.174979` seconds current and `0.073556–0.075520` seconds staged,
with process peak RSS in approximately the 58–59 MiB current and 59–59 MiB
staged bands and zero temporary files/bytes. Durable staging increases WAL in
the disposable probe and remains a protected-campaign resource to calibrate.

The staged timing and wire count cover COPY plus set-based merge after durable
stage-header, repository, and run setup; SCALE8 must measure complete
orchestration before protected dogfood acceptance.

The helper reports normalized observation bytes separately from encoded
transport/SQL bytes and emits only aggregate synthetic values. Existing
SCALE3/SCALE4 tests retain duplicate, existing-row, canonical-collision,
evidence-link, missing-reference, and rollback evidence; SCALE6 retains
cancellation, commit-unknown, receipt-first cleanup, and injected failure
evidence. SCALE7 is not publication proof or Argo CD performance proof.

Provisional synthetic bounds are 29 staged wire statements, less than 5
seconds and 128 MiB client peak RSS at generated size 64, and no uncontrolled
temporary-file growth. Protected dogfood must replace these with measured
PostgreSQL resource, WAL, cancellation, rollback, cleanup, publication,
parity, baseline, and drift thresholds. Independent review is `approved` with
that requirement. The next phase is `SCALE8`, production orchestration through
the existing direct/coordinator adapters followed by intermediate public-safe
repository dogfood; the protected Argo CD clone remains out of scope.

### SCALE8 production staged ingestion

SCALE8 routes direct CLI and coordinator forced-full refresh through one
durable attempt-scoped staging, existing Psycopg 3 COPY, set-based merge, and
complete receipt-bearing final transaction. The accepted ASYNC job, attempt,
instance, fencing, lease, and generation values remain authoritative; direct
mode uses an explicit local operation identity. Stage transitions, ownership,
matching commit-unknown reconciliation, and exact published-attempt replay are
implemented without changing final schemas, canonical identities, public
reads, dependencies, or legacy compatibility surfaces.

The focused staging unit and disposable PostgreSQL evidence passes `14` tests,
including exact row-wise/staged parity across all retained families. The
complete repository gate passes `3132` tests with `7` skipped, `92.8%`
aggregate line coverage, `85.0%` aggregate branch coverage, and the container
smoke suite. A public-safe intermediate direct fixture run publishes aggregate
evidence for `19` files and `189` observations. A same-database unchanged
repeat retains run-scoped history, so SCALE9 must use the authorized
backup-first isolated lifecycle for exact repeat parity. SCALE8 does not access
the protected Argo CD clone. The next selected phase is `SCALE9`, protected
Argo CD dogfood and lifecycle verification; GO24 remains closed.

### SCALE9 — protected Argo CD dogfood

SCALE9 opens the protected exit campaign for the accepted high-scale
forced-full ingestion path. It must safely identify the configured local Argo
CD clone and isolated graph, run preflight, verify backup-first lifecycle
readiness, publish through the staged Psycopg/COPY/set-based path with a
complete receipt, repeat unchanged input through an isolated lifecycle for
exact structural and count parity, store graph and preflight baselines, run
immediate drift checks, and prove cancellation, rollback, cleanup, fencing, and
commit-unknown behavior.

Target code execution, dependency installation, network operations, private
paths, source text, graph contents, credentials, and raw operational payloads
remain prohibited. Final schemas, public reads, canonical identities, ASYNC
authority, read-only MCP, and CLI-owned lifecycle remain unchanged. The graph
is retained by default; destructive cleanup requires explicit authorization and
a verified backup. GO24 remains closed until SCALE-CLOSE.

SCALE9 is being executed through bounded subphases. `SCALE9A` bounds protected
preparation with private re-iterable observation and row spools, streaming
typed checksums, explicit resource closure, and an explicit oversized-HTML
unsupported policy. `SCALE9B` is the selected validation-cost and retained
legacy-proposal compatibility phase. Neither subphase changes final schemas,
public reads, canonical identities, ASYNC authority, publication receipts, or
the closed GO epic.

`SCALE9B` replaces the measured JSONB-distinct proposal guard with exact typed
PostgreSQL composite-row distinctness and preserves the existing row-wise
last-write result for retained legacy projections. The protected retry is
selected as `SCALE9C`; publication, repeat parity, baselines, drift, cleanup,
and GO24 remain pending.

`SCALE9C` narrows the canonical edge-reference guard to indexed correlated
existence checks after a protected retry exposed approximately `11.7 GB` of
temporary-file growth in the prior wide hash plan. `SCALE9D` is the selected
protected authoritative retry; no publication or GO24 recommendation exists
yet.

`SCALE9D` narrows the canonical node-evidence reference guard to correlated
identity existence checks after the protected retry exposed a fixed
approximately `1.05 GB` temporary-file footprint in that guard. The same retry
also exposed that a foreground direct-mode interrupt did not quiesce the
database backend without an explicit bounded cancel and receipt-first failure
reconciliation. `SCALE9E` must verify cancellation quiescence before the next
protected publication attempt; publication, parity, drift, cleanup, and GO24
remain pending.

### SCALE9E — direct cancellation quiescence boundary

SCALE9E installs temporary main-thread signal handlers around the shared
Psycopg connection used by staged direct and coordinator refresh. `SIGINT` and
`SIGTERM` request bounded `cancel_safe()` cancellation and fall back to the
existing cancel API. Handler restoration is performed before connection close
and during final cleanup. The existing rollback, receipt-first failure,
commit-unknown, and cleanup contracts remain authoritative.

The focused tests and full repository gate pass; the exact aggregate result is
`3,141` tests passed with `7` skips, `92.7%` line coverage, and `85.0%` branch
coverage. The next selected phase is `SCALE9F` for actual backend-quiescence
proof and the next protected authoritative retry. Publication, parity,
baseline, drift, cleanup, and GO24 remain pending.

### SCALE9F — direct cancellation and stage cleanup

The protected direct CLI cancellation now has operational evidence: an
interrupt after database work began quiesced PostgreSQL without external
backend cancellation, reconciled as pre-publication rollback, and left no
final rows or complete publication receipt. An isolated exact-owner stage with
`4,550,368` rows was cleaned after receipt and no-live-attempt checks in `338`
bounded transactions over `319.812` seconds. The isolated expiry advance does
not alter retained-stage grace policy. `SCALE9G` is the next protected
authoritative publication attempt; no parity, baseline, drift, performance, or
GO24 result is claimed here.
### SCALE9H — canonical node-evidence guard query-plan bound

SCALE9H maps the SCALE9G diagnostic boundary to canonical merge-builder slot
`7`, direct final-transaction ordinal `19`: the canonical node-evidence
reference guard, not its proposal or merge. It replaces only the former
combined correlated node/evidence check with two narrow full-identity checks.
The node path uses a merge full join; the evidence path uses a spill-capable
hash full join. Both preserve repository, graph-key version, current-run,
missing-reference, transaction, receipt, rollback, cancellation, and privacy
contracts.

No index or `ANALYZE` change is selected. Generated public-safe fixture evidence
shows that the former constrained-memory fallback could issue repeated final
identity probes, while the selected shape avoids a nested-loop fallback. After
the external direct-debug listener was removed, the unchanged complete gate
passed `3,148` tests with `7` skips, `92.7%` line coverage, `85.0%` branch
coverage, and the container smoke suite. Independent review is `approved`.
SCALE9I may begin only after SCALE9H commit, push, and report.

### SCALE9J — direct PostgreSQL connection ownership attribution

SCALE9J replaces aggregate backend inference with exact local ownership
attribution for a direct staged refresh. The opt-in, query-blind telemetry seam
covers the source-controlled staged and receipt-reconciliation connections. It
uses bounded local lifecycle metadata only. A synchronous local ownership
callback may acknowledge readiness while the direct connection remains live.
For the direct CLI, paired private FIFOs hold the source at ready until the
one-connection autocommit observer has bound the reported PID to backend start
time, type, and parallel leader identity and returned the matching
acknowledgement. A one-way pipe frame remains lifecycle audit transport and
cannot admit identity alone. Each telemetry instance starts from a
cryptographically random positive local sequence, preventing a buffered
acknowledgement from an earlier instance matching a new ready event. The
classifier recognizes exact direct clients,
attributable parallel workers, the observer, internal PostgreSQL activity,
ambient clients, and unknown work.

Ambient and unknown classifications remain fail-closed. The public projection
is category counts only. Paired inherited FIFO adapters are hidden and
direct-only; coordinator mode rejects either side. Terminal channel failure
remains visible unless an active direct interruption must remain primary.
Disposable PostgreSQL evidence covers real parallel-worker attribution,
reconnect safety, acknowledged-pipe exact identity registration,
direct-signal rollback without final rows or receipt, and transparent
instrumented-versus-uninstrumented staged publication. No protected graph
operation, source access, schema, dependency, merge, receipt, or public-read
change is part of this phase.

The next bounded phase is SCALE9K, a newly isolated authoritative retry after
the direct-main commit, push, report, parity check, and fresh-cluster preflight.

### SCALE9K0 — local runtime image dependency packaging

Before SCALE9K static preflight, the generated RepoMap server image copied the
project source without installing its already-declared runtime dependencies.
SCALE9K0 packages the image through existing project metadata, retaining one
dependency authority and adding no dependency declaration, lockfile, schema,
migration, graph-model, public CLI, MCP write surface, or protected-source
behavior. The runtime source-root predicate now requires that metadata-bearing
build context. Current-checkout module invocation is required for lifecycle
evidence so a pre-existing installed executable cannot substitute for reviewed
source.

Focused regression coverage, the complete repository gate, container smoke,
and owned runtime health verification pass. No protected source was read, no
graph database was initialized or refreshed, and no publication, receipt,
parity, baseline, drift, performance, or GO24 claim is made. SCALE9K remains
the next protected phase after SCALE9K0 direct-main publication, reporting,
parity verification, and independent review.

### SCALE9K — fresh-cluster authoritative protected retry

SCALE9K completed the fresh-runtime, static-only preflight, zero-state, and
exact-ownership gates. The single direct staged attempt reached
canonical_node_evidence_merge at direct final-transaction ordinal 20 after
completing boundaries 1 through 19. It exceeded the 90-second statement
limit, received one direct signal, and quiesced without database termination,
manual rollback, container intervention, or retry.

No ambient or unknown client was observed. Bounded terminal aggregate
temporary-byte and WAL upper bounds exceeded their accepted caps; direct-client
RSS remained below its cap and PostgreSQL process-group RSS was unavailable.
Readback established a failed terminal run, no complete receipt, and zero
stored graph families. The result is not publication, parity, baseline, drift,
performance, or GO24 evidence.

The next selected phase is SCALE9L, a narrow test-first correction for the
canonical node-evidence merge boundary. The unchanged-repeat phase moves to a
later number after a successful authoritative retry.

### SCALE9L — canonical node-evidence merge bound

SCALE9L corrects the canonical-node-evidence merge boundary identified by
SCALE9K. It materializes staged logical link identities before canonical joins
and refreshes statistics for that staged family after COPY and before the
prepared-state transition. The staged owner boundary, canonical identity
predicates, final target uniqueness, conflict handling, and final-transaction
position remain unchanged. No schema, migration, COPY transport, retained
legacy/raw merge, canonical vocabulary, receipt, cancellation, public CLI, or
MCP write surface changes.

Public synthetic disposable PostgreSQL coverage reproduces the old ordered
deduplication shape and verifies the corrected staged grouping, retained final
links, and insertion of distinct valid links. Independent review required a
controlled orchestration regression that proves statistics refresh once after
COPY and before preparation and validation; it fails when the refresh is
absent. The follow-up complete repository gate passes with 3,240 tests and 7
skips, including smoke and coverage gates; compileall, file-length,
dependency-scope, and diff checks pass. Two dry-run mapping fixtures now
isolate only their availability probe from unrelated local listeners without
changing the real port-conflict preflight coverage.

A fresh independent review approved the published follow-up, including the
orchestration regression, scope, privacy boundary, and remote-parity closeout.

No protected operation occurred in this phase. SCALE9L is neither publication,
parity, baseline, drift, performance, SCALE-CLOSE, nor GO24 evidence. SCALE9M
is the next fresh bounded protected authoritative retry. If it succeeds, the
next phase must run the deferred unchanged-repeat parity boundary; if a new
bounded query category fails, the next numbered source-correction phase must
come first.

### SCALE9M — authoritative retry after node-evidence bound

SCALE9M passed fresh-runtime, static-only preflight, zero-state,
protected-source cleanliness, and exact ownership gates before its one direct
staged attempt. The attempt reached the accepted total elapsed limit and
received one direct signal. The ownership observer remained healthy and
quiesced after exit; no ambient or unknown client, resource threshold, or
final-statement category caused the stop. Aggregate temporary and WAL upper
bounds and direct-client RSS remained within their limits, while
PostgreSQL-process RSS was unavailable rather than inferred.

Bounded readback found a failed terminal run, no complete receipt, zero exposed
graph families, and final protected-source cleanliness. No publication, repeat
parity, baseline, drift, calibrated performance, SCALE-CLOSE, or GO24 claim is
made. SCALE9N is selected to isolate the total-attempt throughput boundary with
public-safe synthetic evidence before any later protected retry.

Independent review approved the published closeout with no actionable findings.

### SCALE9N — direct-attempt timing attribution

SCALE9N published a bounded private timing-attribution design, but did not
install it or launch a protected direct child. Its read-only exact-scope gate
found a clean protected source and owned services reported running, while
required bounded storage readbacks could not re-establish readable state. A
supported alternate readback path did not establish it either. Running services
are not accepted as a substitute for exact storage-readback evidence.

No attempt, signal, reset, cleanup, rebuild, publication, receipt, parity,
baseline, drift, performance, SCALE-CLOSE, or GO24 result is claimed. The next
selected phase is SCALE9O, a bounded lifecycle-readback availability diagnosis
using public-safe synthetic evidence and RepoMap-owned lifecycle commands. It
must not authorize a protected retry or state mutation until that boundary is
resolved. The unchanged-repeat phase remains deferred.

Independent review approved the published closeout with no actionable findings.

### SCALE9O — storage-readback availability

SCALE9O ran one private closed-category diagnostic after clean source and
owned-service gates. The primary readback classified as a connection failure,
the fallback classifier did not accept it, the owned-container plan classified
as unavailable, and a supported alternate readback failed. The result is a
lifecycle-readback topology boundary only; it is not graph, receipt, run,
rollback, or source evidence.

No protected child, signal, backup, reset, cleanup, rebuild, or retry occurred.
No publication, parity, baseline, drift, performance, SCALE-CLOSE, or GO24
claim is made. The next selected phase is SCALE9P, a bounded RepoMap-owned
lifecycle-readback topology correction with public-safe synthetic evidence
before any lifecycle mutation or protected retry. The unchanged-repeat phase
remains deferred.

Independent review approved the published closeout with no actionable findings.

### SCALE9P — lifecycle-readback topology classification

SCALE9P passed public synthetic unavailable-plan and disposable PostgreSQL
readback evidence, then ran one private fail-closed topology classifier after
clean source and worktree gates. It returned `non_container_topology` and did
not query graph state, execute SQL, execute target code, or create a protected
child.

The decision table forbids a configuration edit and does not authorize a
lifecycle start for that category. No lifecycle action, protected retry, reset,
rebuild, publication, parity, baseline, drift, performance, SCALE-CLOSE, or
GO24 result is claimed. SCALE9Q is selected for a bounded
configuration-contract readback-topology correction using public synthetic
evidence and static contract analysis. Independent review approved the
published closeout with no actionable findings.

### SCALE9Q — loopback container-readback contract

SCALE9Q applies a readback-only correction to the existing owned-container
JSON-readback fallback. When direct host-port mapping is disabled, public
loopback configurations retain their established fallback path for operational
JSON readback; the direct-host opt-out remains explicitly tested. The shared
refresh-ingestion fallback retains its existing loopback restriction. The
correction preserves the host attempt, fallback classifier, runtime and
ownership checks, execution arguments, diagnostics, and public interfaces.

The public regression failed before the correction and passed afterward.
Independent review caught and the published correction resolved a shared-helper
scope gap and incomplete loopback-matrix coverage. The complete repository gate
passed 3,246 tests with 7 skips, including smoke, at
92.8% line and 85.1% branch coverage. Compileall, file-length profile
validation with warnings only, and diff checks passed.

No private configuration, live runtime inspection, graph query, live SQL,
target-code execution, protected child, retry, signal, lifecycle action,
operational publication, unchanged-repeat parity, baseline, drift, or
performance operation occurred. This is not SCALE-CLOSE or GO24 evidence.
SCALE9R is selected for a bounded private no-query topology reclassification
before any later operational readback or protected retry. Fresh independent
review of this corrected closeout approved the published result with no
actionable findings.

### SCALE9R — JSON-readback topology reclassification

SCALE9R passed public loopback/readback matrix and disposable integration
evidence, then ran one fail-closed private no-query classifier with fixed
schema validation. It returned `non_container_topology`; the protected source
and main worktree were clean before and after the classification.

The category is not evidence of a configuration value, graph, receipt, run,
rollback, or source state. No configuration edit, graph query, SQL execution,
private database-client invocation, target-code execution, protected child,
retry, signal, lifecycle action, publication, parity, baseline, drift, or
performance operation occurred. This is not SCALE-CLOSE or GO24 evidence.

The next selected phase is SCALE9S, a bounded direct-host or topology-contract
phase. It must not treat the category as permission for a configuration edit,
operational readback, lifecycle action, or protected retry. Fresh independent
review approved the closed category, no-action boundary, privacy, verification
claims, and successor with no actionable findings.

### SCALE9S — direct-host topology contract boundary

SCALE9S records the public source-only AST proof and existing public synthetic
three-case matrix as passed. The closed category is
`non_container_topology_contract`, preserving the predecessor category's
ambiguity without disclosing a private condition.

No target execution and no private runtime, graph, configuration, or lifecycle
action occurred; permitted public Git publication and checking were separate.

SCALE9S is closed. The public topology-contract evidence is approved. The
result preserves ambiguity where private runtime state cannot be inferred from
public evidence.

No readiness determination is made from public evidence alone.

No private runtime, graph, configuration, storage, lifecycle, or protected
operation occurred as part of the public closeout.

No successor SCALE phase is opened. Further private-runtime diagnosis or
protected work requires explicit user direction and a new bounded plan.

Fresh independent review approved the public closeout with no actionable
findings and introduced no new operational evidence.

### SCALE10 — Argo CD staging throughput boundary

SCALE10 passed fresh-runtime, zero-state, static preflight,
protected-source-cleanliness, exact ownership, and public supervisor-
transparency gates before one direct staged attempt. The attempt reached the
90-minute bound during staging/COPY/validation, received one direct signal, and
quiesced. Readback proved a failed run, no complete receipt, no active or
commit-unknown stage, and zero retained-family rows.

Post-signal aggregate temporary and WAL counters exceeded their ceilings after
the private supervisor had selected elapsed time as the stop reason. Its
priority-ordered evaluator did not revise the resource result, so resource
acceptance is not claimed. No publication, repeat, parity, accepted baseline,
drift, SCALE closure, or final GO24 recommendation follows.

No SCALE11 source correction is selected because no reproducible product
defect was isolated. Future work requires a new bounded public-safe profiling
plan for COPY, staged checksums, validation, statistics, and counter evaluation
before source changes or another protected attempt.

### SCALE11 — normalized pipeline profiling and protected-retry readiness

SCALE11 profiles the accepted seven-family full-refresh path through its
existing opt-in observer and disposable PostgreSQL. The public-safe synthetic
matrix completed 72 receipt-bearing publications with resolved cleanup and no
resource crossing, but produced three `superlinear_suspect` and three
`measurement_unstable` profile classifications.

Targeted mixed-profile attribution later crossed the 300-second elapsed ceiling
at 485.4 seconds. The crossing was terminal-only because the profiling harness
did not sample and cancel during the operation. Ordered semantic-guard and
merge events shifted across unchanged repeats and did not isolate one stable
statement-level product boundary. Protected-retry readiness is denied.

SCALE12 is selected solely for live sampled threshold enforcement, bounded
cancellation, and stable operation-level attribution on public-safe disposable
workloads. It must not access a protected target or optimize production
ingestion without a separately isolated product boundary.

### SCALE12 — live operation attribution and measurement acceptance

SCALE12 adds a direct child supervisor, closed source-owned operation registry,
public-safe lifecycle events, validated active-operation state, 250-millisecond
polling, one-second resource sampling, incremental independent threshold
retention, and bounded single-signal cancellation. The opt-in production seam
preserves SQL, statement order, transactions, schema, dependencies,
publication results, and public APIs.

The bounded public-safe campaign completed 29 publications across event
coverage, deterministic cancellation, targeted mixed repetitions, and
instrumentation overhead. All three 8,192-item publications completed below
55 seconds, every logical operation completed below 22 seconds, no threshold
crossed, and overhead remained within the 20 percent limit. Self-host and
explicitly public full-repository repeat/parity also passed. No stable product
boundary or query-plan trigger was found.

SCALE12 accepts the measurement controls and selects SCALE13 as a separately
authorized fresh-cluster Argo CD authoritative retry. SCALE12 does not perform
that retry or authorize any product optimization.

### TEST-COV2 — SCALE13 opening-gate coverage correction

The first SCALE13 opening verification stopped before disposable state or
protected-source access because accepted `main` covered 12,396 of 14,584
branches, or 84.997 percent, below the 85.0 percent hard gate. The exact gap was
the three default-path arcs in uninstrumented bounded stage-cleanup execution.

TEST-COV2 adds one focused compatibility test and changes no production source,
SQL, schema, dependency, runtime behavior, or coverage policy. The complete
gate now covers 12,399 of 14,584 branches and passes container smoke. SCALE13
may restart from clean synchronized `main` under its unchanged Gate A and
protected-access restrictions.

### SCALE13 — actual-path publication attribution integration

SCALE13 closes the synthetic-to-configured-path measurement gap identified by
its Gate A opening inspection. The actual direct `ops refresh-graph` path now
carries 25 source-owned pre-final phase boundaries, the accepted SCALE12
final-publication operations and family measurements, and exact SCALE9J
ownership over one bounded acknowledged private channel. The opt-in seam
preserves ordinary uninstrumented behavior, SQL, transactions, schema,
canonical identity, dependencies, and public output.

Disposable actual-command proof passes complete lifecycle attribution, live
resource availability, seven-family instrumented/uninstrumented semantic
parity, and one-signal cancellation at both pre-final COPY and final guard
boundaries. The complete repository and platform gate passes.

The required production integration selects Outcome A. SCALE13 stops without
protected-source access or Gate B runtime creation. SCALE14 is selected as the
fresh-cluster protected retry; it must begin from the published SCALE13 result
and re-run the unchanged launch gates before any protected access.

### SCALE14 — protected-launch controls

SCALE14 removes product-reachable deterministic delay and provides closed
test-support acknowledgement control. It replaces the prior storage estimate
with exact complete-PGDATA allocated growth and backing-filesystem free space,
validated against the owned runtime labels and fixed read-write mount before
launch.

One reusable actual-refresh supervisor now composes phase and operation state,
the exact final-transaction clock, backend ownership, required live resources,
the accepted incremental threshold monitor, one-signal cancellation, terminal
sampling, quiescence, receipt-first readback, and eligible cleanup. Disposable
actual-path completion, ordinary-path parity, pre-final COPY cancellation,
final-guard cancellation, storage-growth, and crossing-retention campaigns all
pass. The complete repository and platform gate passes.

SCALE14 accesses no protected source or runtime and makes no protected-state or
publication claim. Its implementation is retained; SCALE15 owns the terminal-
authority correction identified by the successor review.

### SCALE15 — terminal reconciliation and receipt authority

SCALE15 closes the active-run exception escape, status-only receipt acceptance,
files-only terminal validation, and synthetic storage integration gaps. One
abort-and-reconcile state machine preserves the primary control failure, sends
at most one direct signal, settles child and backend state, samples terminal
resources, opens a fresh terminal observer when live telemetry fails, reads the
canonical receipt-bearing publication, reconciles stage and cleanup authority,
and reports only closed public-safe categories.

Publication success requires matching repository identity, execution mode,
publication attempt, four generations, latest-recorded and latest-publication
semantics, all seven final families, structural digest, reconciled stage state,
and eligible cleanup. Disposable success, threshold cancellation, prior-
publication preservation, five control-failure, nine adversarial database, and
sustained real-PGDATA campaigns pass without protected access.

SCALE15 accepts protected-launch terminal authority. SCALE16 is selected as the
separately authorized fresh-cluster Argo CD authoritative retry.

### SCALE16 — exact direct launch-attempt binding

SCALE15 implementation is retained. Its protected-launch readiness is deferred
because the supervisor did not bind terminal publication and failed-stage
acceptance to the exact direct attempt created inside its child.

SCALE16 carries the existing `IngestionAuthority.receipt().attempt` through one
private acknowledged event, validates it before acknowledgement, freezes it in
the supervisor, and requires exact equality across the bound attempt, exact
stage owner, latest recorded run, and canonical receipt-bearing publication.
The event precedes graph connection and mutation. Missing, malformed,
duplicate, changed, late, and foreign authority state fails closed without
exposing the private identity.

Disposable success, zero-state cancellation, prior-publication preservation,
same-generation foreign-publication rejection, transport and telemetry
control, adversarial database, and uninstrumented compatibility coverage pass
without protected access. SCALE17 is the selected separately authorized fresh-
cluster Argo CD authoritative retry.

### SCALE17 — fresh-cluster Argo CD authoritative retry

SCALE17 creates one fresh exact-scope private runtime, distinct control and
dedicated graph databases, and one private manual MCP-hidden registration.
Lifecycle, schema, ownership, zero-state, backend, event, binding, resource,
threshold, terminal, and protected-source gates pass before static analysis.

Current product discovery, extraction, generation, canonicalization, and
seven-family expectation construction complete within their time and storage
bounds. Prelaunch structural-digest construction then crosses the 6 GiB
client-RSS hard bound. The expectation is rejected and no refresh child,
stage, run, receipt, publication, or final-family row is created. Exact
zero-state and backend readback pass after the stop.

SCALE17 ends at
`protected_prelaunch.structural_digest` /
`client_peak_rss_bytes`. SCALE18 owns a memory-bounded prelaunch digest and
sampled maximum-retention control correction before another protected retry.
The historical field label is not an exact operating-system peak. No
publication, repeat, parity, baseline, drift, SCALE closure, or GO24 result is
accepted.

### TEST-COV3 — supervisor/event-ACK startup ordering correction

The first SCALE18 opening gate exposed a startup race in the accepted
configured direct-path supervisor. The child could execute product code and
begin its private two-second event acknowledgement deadline before parent-side
event, semantic, backend, telemetry, resource, and failure authorities were
ready. Later transport EOF could then mask the intended first control failure.
SCALE18 did not begin.

TEST-COV3 inserts a private inherited pipe gate before the unchanged product
argv, establishes a closed parent readiness state machine, uses one bounded
lifetime validate-before-ACK receiver, holds stable backend readiness through
the atomic child-release transition, and serializes first-failure and one-
signal settlement. Test-support failures activate at accepted source-owned
boundaries without blocking event acknowledgement.

Public-safe disposable campaigns, deterministic scheduling and process stress,
three consecutive actual-storage integration passes, and independent review
accept the correction. SQL, schema, publication, receipt, canonical identity,
graph key, digest, extraction, dependency, public CLI, MCP, and coordinator
contracts remain unchanged. SCALE18 resumes only after TEST-COV3 is committed,
pushed, reported, clean, synchronized, and revalidated through SCALE18's own
opening gate.

### SCALE18 — memory-bounded prelaunch structural digest

SCALE18 replaces simultaneous whole-graph, complete JSON-text, and complete
UTF-8-byte ownership with one shared incremental SHA-256 encoder. The prepared
adapter orders the unchanged seven-family projections through bounded private
runs and limited merge fan-in. Terminal readback feeds the same encoder through
one explicitly closed server cursor per unchanged ordered query.

The resource monitor retains first crossing, sampled maximum, pre-signal
maximum, post-signal maximum, and terminal authority through process exit or
reader loss. It signals at most once and continues parent sampling through exit.
A worker-owned continuous 50-millisecond digest sampler is combined with the
100-millisecond parent maximum for acceptance.

Seven public-safe family-skew profiles at six geometric bands remain below
192 MiB total sampled RSS, 138 MiB conservative digest increment, 203 MiB
combined temporary growth, and eight seconds of digest time at the 8,192-item
band. All seven 4,096-to-8,192 profile pairs pass the direct or fixed-baseline
25 percent doubling rule. Current-checkout and explicit-public repository
repeats preserve generations, family counts, digests, artifacts, and source
state. Disposable PostgreSQL repeats preserve prepared/readback digest, typed
count order, and receipt-bearing publication parity. The final complete gate
passes with 3,835 tests and 8 platform skips, and independent review approves
the corrected final tree with no remaining findings.

Digest bytes, SQL, schema, migrations, canonical identity, graph keys,
staging descriptors, publication, receipts, launch binding, lifecycle, public
interfaces, and dependencies remain unchanged. SCALE18 accesses no protected
source or retained runtime and performs no protected prelaunch. SCALE19 is the
separately authorized fresh-cluster Argo CD prelaunch and authoritative retry.

### SCALE19 — fresh-cluster Argo CD prelaunch and authoritative retry

SCALE19 establishes one fresh private lifecycle scope, byte-compatible graph
collation, one restrictive aggregate artifact root, active artifact/free-space
controls, current startup/event/backend/resource/terminal readiness, exact zero
state, and protected-source cleanliness before static content access.

One protected prelaunch completes current static discovery, Go extraction,
four-generation calculation, canonicalization, seven-family preparation, and
the accepted streaming prepared-stage digest within every hard bound. The
private result transport then sorts the nested family-count mapping, which does
not preserve the separate typed `FINAL_FAMILY_CODES` iteration contract.
Expected-authority validation rejects the handoff before refresh child creation.

No attempt, signal, stage, run, receipt, publication, or final row exists.
Read-only reconciliation proves exact zero state, backend quiescence, artifact
cleanup, and protected-source cleanliness. The empty SCALE19 runtime is retained
for bounded diagnosis, and the retained SCALE17 runtime is untouched.

SCALE19 does not establish publication, repeat parity, baseline, drift, SCALE
closure, or GO24 readiness. The accepted interruption sequence is SECURITY0,
SECURITY1, and then SCALE20.

### SECURITY0 — Dependabot and security policy

SECURITY0 configures one minimal weekly Dependabot policy for the root PEP 621
Python project, the Go module under `src/main/go`, and root GitHub Actions. It
also adds the public security-reporting policy and verifies the bounded GitHub
dependency-security settings without changing dependency or release pins.

### SECURITY1 — alert confirmation and coherent remediation

SECURITY1 confirms that authenticated repository alert enumeration returns no
current or historical Dependabot alerts, independently confirms the Setuptools
Unicode-normalization manifest-exclusion advisory against the exact 80.9.0
build pin, and coherently updates every live build, release-image, notice, and
test authority to fixed Setuptools 83.0.0. Scheduled Psycopg and GitHub Actions
version updates remain routine modernization outside SECURITY1. SCALE20 may
resume only after the coherent commit is pushed, post-push alert enumeration
confirms zero unresolved actionable findings, and the superseded one-file
Setuptools pull request is disposed without merging it.

### SCALE20 — order-preserving prelaunch handoff and protected retry

After SECURITY1, SCALE20 accepts the order-preserving private seven-family
expectation handoff correction. The private worker wire contract now uses a
closed ordered array derived from `FINAL_FAMILY_CODES`; strict bounded decoding
rejects the legacy object form and every missing, extra, duplicate, unknown, or
reordered sequence before constructing the unchanged launch authority.

Focused unit and real-process integration evidence passes 59 cases, including
two deterministic public-safe Go prelaunch worker repeats. The complete Stage A
gate passes 3,885 tests with 10 platform skips, 92.7 percent line coverage,
exactly 85.0 percent branch coverage, Go validation, and container smoke.

The protected retry is deferred. A read-only Stage A diagnostic search
traversed one retained SCALE19 report file, invalidating the explicit zero-
retained-runtime-access transition prerequisite. It did not mutate retained
runtime state or access protected source, and SCALE20 created no runtime or
protected process. SCALE20 therefore selects Outcome B; SCALE21 owns the fresh
protected retry. Neither SECURITY phase is part of SCALE, and SCALE20 does not
begin in SECURITY0.

### SCALE21 — fresh-cluster Argo CD authoritative retry

SCALE21 establishes one new exact-scope private runtime, distinct owned graph,
control, and maintenance targets, byte-compatible graph collation, one private
manual MCP-hidden registration, one restrictive accounted artifact root,
current control-plane readiness, exact zero state, and protected-source
cleanliness. Retained SCALE17 and SCALE19 runtime contents are neither reused
nor directly inspected.

One protected worker completes static discovery, Go extraction, four-generation
derivation, canonicalization, seven-family preparation, and the accepted
streaming digest within every hard bound. Its committed SCALE20 ordered-array
payload decodes successfully and temporary artifacts are cleaned. The private
parent then requests an RSS evidence field that is absent from the committed
worker result, so expectation finalization fails closed before an immutable
launch expectation is accepted.

No refresh child, attempt, signal, stage, run, receipt, publication, or final
row exists. Read-only reconciliation proves exact zero state, backend
quiescence, artifact cleanup, and source cleanliness. The no-retry rule prevents
a second protected worker. SCALE21 stops at
`protected_prelaunch.expectation_finalize` /
`phase_local_parent_rss_field_mismatch`; SCALE22 owns the phase-local parent-field
correction and one fresh protected retry. No publication, parity, baseline,
drift, SCALE closure, or GO24 result is accepted.

### SCALE22 — sampled-RSS authority and protected telemetry refusal

SCALE22 corrects the phase-local private prelaunch parent without changing
tracked source or tests. The parent consumes the committed aggregate sampled-
RSS authority, verifies both accepted equations, rejects the historical field,
and binds resource and semantic evidence to one settled worker. Public-safe
real-process repetitions and adversarial evidence pass before protected access.

One fresh private runtime passes lifecycle, topology, schema, registration,
collation, artifact, control-plane, zero-state, and protected-source gates.
Exactly one protected prelaunch produces a valid ordered immutable expectation
within every bound. One configured direct child then enters extraction, where
backend telemetry authority fails before launch-attempt binding. The supervisor
sends one signal and settles the child without retry.

Post-stop readback proves exact zero state, backend quiescence, artifact
cleanup, source cleanliness, and no commit uncertainty. SCALE22 selects Outcome
E at `refresh.extraction` / `backend_telemetry_failed`; SCALE23 owns the exact
control correction before another protected retry. Publication, repeat parity,
baseline, drift, SCALE closure, and GO24 readiness remain unproved.

### SCALE23 — direct child backend-telemetry lifetime correction

SCALE23 corrects the private parent monitor that previously treated the first
database connection frame as telemetry-session readiness. Reader readiness,
child process state, optional owned-connection frames, and terminal EOF are now
separate authorities. Database-free discovery and extraction require no
heartbeat or connection event. Remote EOF while the child is live remains an
exact fail-closed control; sender EOF after child terminal is accepted only by
terminal settlement.

The existing child sender and inherited endpoints already span startup,
bootstrap `exec`, the full direct operation, owned connection closure, and
process terminal. Existing maintenance, staging, and publication connections
continue to require exact announcement and matching acknowledgement before
caller use, with a new generation on reconnect.

Private terminal readback now distinguishes independently proved pre-binding
and bound pre-stage exact state from publication uncertainty. Exact zero and
unchanged prior receipt-bearing publication can reconcile when no new stage,
run, receipt, family row, stale owner, or commit uncertainty exists and fresh
backend authority is quiescent. Unknown or foreign state remains refused.

Repeated public-safe actual configured campaigns, real acknowledgement loss,
premature EOF, prior-publication preservation, connection-ordering evidence,
and deterministic scheduling stress pass without dependency, SQL, schema,
identity, digest, publication, lifecycle, public interface, MCP, or coordinator
change. SCALE23 performs no protected or retained-runtime access. SCALE24 owns
the separately authorized fresh-cluster Argo CD prelaunch and authoritative
retry.

### SCALE24 — public-safe parent-result refusal

SCALE24 passes the unchanged-source repository and platform gate and creates
one owner-private parent that composes the accepted SCALE18 sampled-RSS and
digest authorities with the SCALE20 ordered handoff and immutable expected
authority. The one public-safe Go worker completes every derivation and
validation phase, but parent reporting requests an optional key absent from
the committed worker payload and fails before publishing the private result.

The fail-closed boundary is
`public_safe_prelaunch.result_reporting_contract_mismatch`. No second
rehearsal, private runtime, protected or retained-runtime access, protected
prelaunch, or protected refresh occurs. SCALE25 owns the exact phase-local
reporting correction and a separately authorized fresh-cluster retry.

Delivery remains blocked: two final full-gate runs lost public-safe terminal
resource and backend-quiescence authority, and an isolated SCALE15 campaign
reproduced the terminal failure. No SCALE24 commit or protected operation is
accepted. The next bounded correction must restore a passing complete gate as
well as repair the phase-local result-reporting contract.

### SCALE25 — prelaunch reporting and terminal authority stabilization

SCALE25 preserves the historical SCALE24 plan and refusal exit, then replaces
the stale phase-local optional-field copy with one immutable repository-owned
public-safe projection. It is derived only from a validated internal prelaunch
result, uses closed and bounded deterministic serialization, proves exact
internal/public agreement, and excludes private authority values. The
transient operational-report envelope remains separate from this projection.

Terminal supervision now uses one shared immutable child-terminal latch and an
order-independent fact collector. Child, event, terminal resource,
asynchronous resource settlement, live backend monitor, fresh backend observer,
receipt/stage/family readback, and cleanup authorities are each attempted
before final result freeze. Active remote EOF still fails closed, terminal EOF
after child terminal remains valid, static silence remains healthy, and exact
connection acknowledgement remains required before use. Resource and backend
failures remain independent and cannot overwrite the first causal failure.

Two exact parent rehearsals, ten consecutive focused repetitions, six
consecutive real-storage terminal campaigns, one hundred deterministic
terminal-order permutations, broad cross-phase compatibility, and two
consecutive complete repository gates pass. No protected source or retained
runtime is accessed, no protected operation runs, and no timeout, dependency,
schema, SQL, digest, family, receipt, publication, lifecycle, public interface,
or coordinator authority changes. SCALE26 owns the separately authorized fresh-
cluster Argo CD prelaunch and authoritative retry.

### SCALE26 — public-safe terminal-authority refusal

SCALE26 passes the synchronized accepted-main opening gate, focused reporting,
terminal, telemetry, startup, RSS/digest, handoff, launch-binding, receipt, and
dependency checks, plus Go and container validation. One actual configured
public-safe disposable campaign then rejects its event-transport case because
backend ownership becomes the first causal failure before launch binding. The
expected injected event category is not retained as primary.

The exact boundary is
`public_safe_terminal_authority.event_transport_first_failure_mismatch`.
SCALE26 safely reconciles the public fixture and selects Outcome D before
private runtime inventory or creation, protected source access, protected
prelaunch, or protected refresh. Retained SCALE17, SCALE19, SCALE21, and
SCALE22 runtime contents remain untouched. The next bounded phase must
stabilize the public-safe startup ownership and first-failure precedence
contract before another protected retry.

The mandatory final full gate confirms the instability when the configured
threshold case selects a resource-reader failure before the expected threshold
category. SCALE26 is not approved for protected continuation. After explicit
operator authorization, its documentation-only bounded-stop record is
committed and pushed without accepting the control plane or authorizing
protected work.

TEST-COV4 — deterministic startup ownership and first-failure arbitration — is
the immediate successor. Protected SCALE operations are paused, and the SCALE
epic remains open. SCALE27 owns the next protected retry only after TEST-COV4
acceptance.

### TEST-COV4 — deterministic startup ownership and first-failure arbitration

TEST-COV4 assigns one unique total sequence at each source-owned failure
creation boundary. Callback observation, lock arrival, diagnostic time,
category priority, and test expectations do not select the primary. Immutable
private candidates retain lifecycle and ordering evidence, while public results
contain only closed categories and bounded order status.

Startup resource work is settled before child release, pre-release ownership
or reader failures block launch, test probes are closed, and injections remain
disarmed until their exact selected boundary. Later terminal limitations cannot
replace an earlier ambient, event, threshold, or resource failure. One bounded
confirmation handles only transient storage-unavailability samples and retains
the complete elapsed time under the unchanged threshold.

Twelve consecutive owning public-safe campaigns, ten consecutive focused
selections, one hundred deterministic causal permutations, three consecutive
complete repository gates, cross-phase compatibility, and all supporting Go,
container, compile, file-length, privacy, dependency, cleanup, and diff gates
pass. Independent review is approved. No protected or retained-runtime access
occurred and no dependency, timeout, heartbeat, SQL, schema, digest, family,
receipt, lifecycle, public interface, or coordinator contract changed.

TEST-COV4 is accepted. SCALE27 owns the separately bounded fresh-cluster Argo
CD prelaunch and authoritative retry. SCALE remains open; publication, repeat
parity, accepted baseline, drift, closure, and GO24 are not claimed.

### SCALE27 — opening-gate backend-observer refusal

SCALE27 begins from synchronized accepted TEST-COV4 and passes dependency,
status-path, Go coverage, vet, lint, race, and protocol checks. Its mandatory
complete opening gate then stops in the public-safe SCALE23 backend-telemetry
lifetime campaign with `backend_observer_failed` causally first, followed by
lifecycle incompleteness and event EOF.

The child settles after one signal, terminal resource evidence remains
available, fresh backend readback is quiescent, pre-binding state is reconciled,
and no publication occurs. The gate reports 3,970 tests passed, 10 platform
skips, and one failure and is not rerun for a favorable schedule.

SCALE27 selects Outcome B before its separate public-safe control campaign,
private runtime inventory or creation, protected source access, prelaunch, or
refresh. Exact disposable cleanup passes, retained runtime contents remain
untouched, and independent review is not approved for protected continuation.

SCALE28 must first correct and requalify the public-safe backend-observer
lifetime boundary before any fresh-cluster protected retry. SCALE remains open;
publication, repeat parity, accepted baseline, drift, closure, and GO24 are not
claimed.

### SCALE28 — live backend observer lifetime and failure-boundary correction

SCALE28 proves that live summary, telemetry-event, and fixed resource queries
were already serialized but local close was not part of the same lifetime
authority. After a bounded consumer join, cleanup could close the observer
connection while an operation remained in flight, and no closing state blocked
new work.

One private session now owns one observer and one exact autocommit connection
through constructed, connection-created, registered, startup-validated, active,
failed, closing, and closed states. It serializes operations, rejects work after
closing begins, waits for in-flight work, and closes once. Active connection
loss remains fail-closed without reconnect, heartbeat, or timeout increase; the
fresh terminal observer remains independent.

Exact private boundaries cover observer construction, connection creation,
registration, startup and active summary, event application, contract
validation, connection loss, identity change, resource read, local close, and
terminal wait. TEST-COV4 retains source order and the original sanitized error
while public categories remain bounded.

Twenty long campaigns, ten mixed campaigns, one hundred deterministic order
permutations, ten focused repetitions, and three consecutive complete gates
pass. No protected or retained-runtime access occurs, no protected operation
runs, and independent review is approved. SCALE29 owns the separately
authorized fresh-cluster Argo CD prelaunch and authoritative retry.

### SCALE28-FIX1 — backend summary category preservation and bounded observer settlement

Post-commit review retains SCALE28's one-session connection-lifetime correction
but supersedes its protected-retry readiness. The retained implementation could
wrap structured backend-summary failures as observer-mechanism failures, and
operation acquisition and close settlement used condition waits without
deadlines.

SCALE28-FIX1 preserves exact repository `ControlFailure` identity and code,
keeps valid forbidden-backend observations from poisoning the session, removes
test-owned ambient causal prepopulation, and routes active validation through
the serialized session. Monotonic caller-budgeted waits, observer-only statement
timeout, and exact-connection bounded cancellation establish operation and
settlement bounds without reconnect, heartbeat, or close-under-use.

Twenty category campaigns, twenty settlement campaigns, one hundred order
permutations, ten focused repetitions, and three complete gates pass.
Independent review is approved. Protected source and retained runtime contents
remain outside scope. SCALE29 owns the separately authorized fresh-cluster Argo
CD prelaunch and authoritative retry.

### SCALE28-FIX2 — observer bootstrap deadline and deterministic timeout classification

Post-commit review retains SCALE28-FIX1's category and coordinated-settlement
correction but supersedes protected-retry readiness. Connection establishment
was not explicitly bounded, the post-connect statement-timeout installation
was outside the operation timer, and equal server/client trigger timing could
change private mechanism attribution.

An isolated candidate installed the observer timeout through libpq startup
options before registration, limited each observer connection to one bounded
endpoint, and validated a strict deadline hierarchy. Disposable PostgreSQL
server, client-fallback, connection-bootstrap, registration, and cleanup
evidence passed, as did deterministic ordering tests.

The configured-runtime full gate did not pass. Under sustained suite load,
ambient-client or resource-reader authority preceded expected SCALE14,
SCALE23, and SCALE28 outcomes. Stable startup ownership settlement and another
strictly ordered observer operation did not reliably fit the unchanged
handoff ceiling. Independent review is not approved; the incomplete source and
test candidate is retained privately and reverted from Git.

SCALE28-FIX2 is a bounded Outcome B stop. No dependency, schema, SQL,
publication, lifecycle, public-interface, or protected-runtime change is
committed. TEST-COV5 and SCALE29 remain prohibited until a separately
authorized deadline or ownership-architecture decision resolves the handoff.

### TEST-COV5 — observer bootstrap and deadline-hierarchy qualification

Explicit operator authorization opens a test-only qualification of the
authoritative Outcome B tree without restoring or accepting the reverted
SCALE28-FIX2 candidate. The first connector-faithful local protocol probe uses
the production observer session and actual Psycopg connection factory against a
loopback endpoint that accepts TCP while withholding PostgreSQL startup.

The connection attempt does not return within the bounded contract and never
produces the required connection-timeout boundary. Exact test-owned process and
socket cleanup completes. The failing test patch is retained privately and
reverted, and later hierarchy, causality, configured-campaign, dress-rehearsal,
and complete-gate work does not run after the product defect.

TEST-COV5 selects Outcome B with a documentation-only tracked closeout. No
production, test, dependency, schema, publication, lifecycle, public-interface,
or protected-runtime behavior changes. SCALE29 remains prohibited;
SCALE28-FIX3 must establish bounded connection bootstrap and reconcile its
deadline with configured startup ownership and resource settlement.

### TEST-COV5A — observer bootstrap and deadline failure-surface characterization

TEST-COV5A retains the stalled-handshake defect through a strict expected-
failure regression and a reusable local PostgreSQL protocol harness rather than
stopping at the first finding. The accepted tree lacks bounded connection
bootstrap and deterministic timeout-mechanism classification. The exact private
SCALE28-FIX2 candidate fixes those isolated contracts but still fails configured
long and mixed campaigns through ambient-client and resource-reader authority.

The selected correction retains only the candidate's bounded one-endpoint
connection, startup options, and timeout classification. It also requires
complete-operation budget reservation and settled startup resource authority
before the final stable ownership proof under the unchanged handoff ceiling.
SCALE28-FIX3 is authorized to implement that bounded design. Protected work and
SCALE29 remain prohibited.

### SCALE28-FIX3 — bounded observer bootstrap and configured ownership reconciliation

SCALE28-FIX3 does not accept a production correction. Under actual configured
load, 350 ms does not contain resource SQL and 400 ms does not contain ownership
SQL. Raising the server budget to 450 ms within the unchanged 500 ms handoff
removes the reserve needed for transient ambient settlement and two stable
ownership samples. The incomplete candidate is private and the accepted
TEST-COV5A production and test tree is restored.

SCALE28-FIX3 selects Outcome C. TEST-COV5B may perform test-only
decision-support characterization for the timeout-ceiling or observer-
architecture choice. Protected SCALE remains paused and SCALE29 is not
authorized.

### TEST-COV5B — observer deadline independent decision support

TEST-COV5B retains an implementation-independent model for configured SQL
containment, strict deadline reserves, transient settlement, stable ownership,
and 500 source-causality orderings. Current/candidate comparison confirms that
bounded bootstrap alone is insufficient: the accepted tree retains strict
bootstrap and configured resource defects, while the private candidate has no
single frozen deadline contract and does not pass configured acceptance.

TEST-COV5B selects Outcome C. The next authorized correction requires an
operator choice between an evidence-sized handoff-ceiling increase and a
bounded process-isolated or revised startup authority. Both options must pass
the retained option-specific requirements and the shared bootstrap, timeout,
configured-campaign, fresh-rehearsal, prior-state, complete-gate, and cleanup
bars. Protected SCALE remains paused and SCALE29 is not authorized.

### SCALE28-ADR1 — evidence-sized startup ownership handoff decision

SCALE28-ADR1 measures Option 1 with a pre-registered public-safe campaign and
removes zero valid observations. The frozen model produces a 5,810 ms component
bound, a 4,624 ms measured handoff bound, and a 5,850 ms rounded in-process
candidate. The valid 4,144 ms loaded local-resource maximum is retained. Every
controlling result exceeds the separate 3,000 ms operator guard.

Option 1 is rejected. The production 500 ms path remains known-defective, but
5,850 ms is not authorized. Protected SCALE remains paused. SCALE28-ADR2 owns
bounded process-isolated, two-stage, and hybrid startup-authority decomposition.
SCALE29 remains prohibited.

### SCALE28-ADR2 — bounded startup authority decomposition

SCALE28-ADR2 selects hybrid isolated resource preparation with parent-owned
final observer, freshness, ownership, and atomic release authority. Static
analysis rejects full live-authority transfer and the uncancellable in-process
PGDATA path. The fixed revision 2 campaign removes zero valid observations and
proves the public-safe receipt, process cleanup, freshness, ordering, fault,
and disposable PostgreSQL prototype contracts.

The frozen private internal bounds are 5,000 ms per preparation attempt,
10,000 ms total, 650 ms final release, and a 1,000 ms freshness lease. FIX4 may
implement only this architecture. TEST-COV5C must independently qualify it;
SCALE29 remains prohibited.

### SCALE28-ADR2-FIX1 — parent-anchored preparation freshness

SCALE28-ADR2-FIX1 retains the hybrid architecture but supersedes receipt-
version-1 freshness and withdraws the 1,000 ms lease. The corrected test-only
contract uses one immutable baseline freeze, one bounded observation-complete
frame, one exact digest-bound ACK, terminal receipt version 2, and a
conservative parent-monotonic origin 100 ms before frame receipt. It never
compares absolute parent and worker clocks.

The pre-registered revision-3 private prototype campaign completes 522 valid
records with zero valid removals. Its accepted maxima are 88 ms preparation,
2 ms frame-to-receipt, 15 ms frame-to-release, and 2 ms final release. The
frozen formula selects a 1,450 ms freshness lease while retaining the 5,000 ms
attempt, 10,000 ms total-preparation, and 650 ms final-release bounds.

SCALE28-FIX4 may implement only the corrected acknowledged-frame, receipt-v2,
parent-age, reacquisition, and cleanup contract. TEST-COV5C adds the corrected
frame/ACK, age, stale-checkpoint, and reacquisition qualification matrices.
SCALE29 remains prohibited.

### SCALE28-ADR2-FIX2 — immutable preparation evidence and bounded IPC qualification

SCALE28-ADR2-FIX2 retains the hybrid isolated resource-preparation worker and
parent-anchored acknowledged observation-frame freshness design but supersedes
revision-3 selection authority. Accepted evidence is now deeply immutable typed
data backed by exact canonical bytes and verified digests. Receipt version 3
limits worker claims to pre-emission completion, subordinate cleanup, and
expected disposition; the parent owns actual terminal facts. Observation, ACK,
and receipt traffic is bounded at the process transport before decode.

The campaign serializes only typed observed results and compares them with
separate expectations. Revision-4 iteration 6 froze the exact 702-record design
and 32 source hashes, but its configured-owning-path prerequisite did not
complete. The final authorized launcher completed ten SCALE14 executions and
two SCALE23 executions before SCALE23 invocation 03 failed closed at the
backend-observer boundary during documented external test contention. It
published no partial report. The 702-record campaign and lease derivation did
not run.

SCALE28-ADR2-FIX2 therefore closes as Outcome B. SCALE28-ADR2-FIX3 must obtain
complete source-frozen configured-owning-path evidence, resolve or bound the
observer-lifecycle failure, run the complete campaign, and derive the lease
before implementation authority can be reconsidered. SCALE28-FIX4, TEST-COV5C,
and SCALE29 remain prohibited.

### SCALE28-ADR2-FIX3 — isolated-host configured owning-path qualification

SCALE28-ADR2-FIX3 retains the iteration-6 source freeze and independently
monitors current-user test-process and disposable-container transitions. Both
authorized configured attempts began after clean 90-second intervals.

The initial launcher completed ten SCALE14, ten SCALE23, and eight SCALE28
executions before SCALE28 invocation 09 refused publication with
`ambient_client_detected` first. External pytest and APG work began before and
remained active at the product failure, so the attempt is invalidated and does
not prove a source defect. The sole replacement was likewise invalidated when
external pytest and APG work began before configured completion. It produced no
product failure and no partial report.

FIX3 selects Outcome C. No complete configured report, 702-record campaign,
revision-4 lease, or architecture-bound revalidation exists. Production and
dependencies remain unchanged. SCALE28-FIX4, TEST-COV5C, and SCALE29 remain
prohibited pending a dedicated qualification environment decision.

### SCALE28-FIX4 — hybrid startup authority implementation

The operator supersedes FIX3's pre-implementation dedicated-environment
prerequisite and authorizes implementation followed by qualification of the
real implementation. FIX4 moves only the slow PGDATA and PostgreSQL resource
preparation into one spawn-context worker. The parent retains the continuous
observer, TEST-COV4 causality, parent-monotonic freshness, final ownership
proof, actual terminal facts, atomic child release, publication, and
reconciliation.

Production now uses deeply immutable canonical preparation evidence,
receipt-version-3 pre-emission facts, parent-owned terminal settlement, bounded
observation/ACK/receipt/failure IPC, exact process-group cleanup, and complete
two-generation reacquisition. The selected private policy is 1,800 ms per
attempt, 4,100 ms total preparation, 800 ms freshness, 600 ms final release,
100 ms transfer reserve, and two attempts, with 150/300/300 ms ACK, receipt,
and settlement deadlines.

All selected known defects and configured quarantines pass normally. Focused,
owning-area, mixed, ordering, mutation/IPC, fresh-runtime, and three complete
repository gates pass without product-contract drift or protected access.
FIX4 selects Outcome A. TEST-COV5C is the sole successor and may modify only
test, test-support, plan, and status surfaces; SCALE29 remains prohibited.

### TEST-COV5C — hybrid startup authority independent qualification

TEST-COV5C adds only public-safe tests, test support, and phase records.
Production-boundary qualification covers immutable canonical evidence,
mutation, parent freshness/reacquisition, actual bounded process IPC, actual
worker receipt-v3 settlement, Psycopg/PostgreSQL bootstrap and timeout
hierarchy, and fail-closed cross-platform containment.

The four repository-owned SCALE14/SCALE23/SCALE28/SCALE28-FIX1 areas each pass
ten executions, including quiet and bounded unrelated-contention conditions.
Fifteen consecutive mixed campaigns, three fresh rehearsals, one
prior-publication rehearsal, the source-observed 702-record revision, ten
focused selections, and four complete gates pass from frozen production
source. TEST-COV5C selects Outcome A and authorizes but does not begin SCALE29.

### SCALE28-FIX5 — observer cancellation settlement and evidence correction

Post-commit review retains FIX4's hybrid preparation architecture but
supersedes the cancellation-failure close behavior and TEST-COV5C's technical
Outcome A. A failed cancellation request did not establish that the
operation-owning thread had stopped, so the callback could close the observer
connection under active use.

FIX5 makes cancellation request and outcome, operation settlement, settlement
limitation, and close eligibility separate immutable facts. The callback never
closes. The operation owner alone clears in-flight state, and coordinated close
alone closes after settlement. Operation timeout remains primary and
cancellation limitation remains secondary.

The 702 TEST-COV5C records are reclassified as request-round-trip stability,
not semantic cohort authority. The repeated 100 reacquisition, 500
cross-authority, and 20 worker-terminal claims are replaced with 20 distinct
reacquisition combinations, 24 actual release-order permutations, and 12
terminal fact variants. Fifty distinct cancellation/close/settlement cases and
real PostgreSQL server-timeout and cancellation-limitation cases pass.

The frozen 40 ms exact-connection cancellation-request reserve is not reliable
on the disposable local PostgreSQL boundary. Bounded direct characterizations
observe 9 of 20 and 6 of 10 successes at 40 ms; no timeout is retuned. FIX5
selects Outcome B. TEST-COV5D proceeds in characterization mode and SCALE29
remains prohibited.

### TEST-COV5D — observer cancellation semantic characterization

TEST-COV5D retains FIX5 Outcome B and freezes production source, dependencies,
deadlines, policy, and diagnostics. Its test-only characterization adds a
typed per-group qualification manifest, 100 barrier-distinct close orders, 200
source-sequenced causality orders, 18 terminal claims, 36 reacquisition paths,
and real PostgreSQL server-timeout, decision-support fallback, default-reserve,
and cancellation-limitation operations.

The unchanged 40 ms default reserve again fails qualification: 20 additional
operations produce 12 successful cancellation requests and 8
`CancellationTimeout` results. The focused 555-test selection and complete
5,019-test repository gate pass without production drift.

TEST-COV5D selects Outcome B. The exact SCALE28-FIX6 boundary is an
evidence-sized product cancellation-request reserve plus 30 consecutive real
successful client fallbacks under the selected default, while retaining
server-timeout precedence, no-close-under-use, source causality, settlement,
and exact cleanup. SCALE29 remains prohibited.

### SCALE28-FIX6 — request settlement and coupled caller-budget result

FIX6 corrects the remaining three-party close race by tracking
cancellation-request-in-flight independently from operation-in-flight.
Coordinated close requires both operation and request settlement; the
cancellation callback remains unable to close.

C120-420 passes isolated real-PostgreSQL selection and provisional
product-default cohorts but fails the configured hybrid caller sequence. Later
final-release operations cannot contain its fixed 420 millisecond trigger and
120 millisecond request bound after preceding work consumes part of the
unchanged 600 millisecond authority. The candidate is rejected and rolled back
without retuning.

FIX6 selects Outcome B. The predecessor product default remains unchanged and
unqualified. TEST-COV5E proceeds in characterization mode and must freeze
production source, retain the request-settlement regressions, characterize the
complete caller sequence, and specify the next acceptance suite. SCALE29
remains prohibited.

### TEST-COV5E — product-default observer cancellation characterization

TEST-COV5E freezes the pushed FIX6 production source and adds public-safe
caller-budget, semantic-manifest, PostgreSQL, and three-party settlement
coverage. Fifty new request/operation/close/terminal/readback schedules pass
together with the retained 100 close schedules, 200 causality schedules, 18
terminal claims, 36 reacquisition paths, a 564-test focused selection, and a
complete 5,112-test repository gate.

The product default remains unqualified. Real quiet and bounded-contention
cohorts continue to produce request timeouts, and a 440 millisecond remaining
caller budget compresses the client trigger to the server floor. C120-420
requires 620 milliseconds including the mandatory sample gap and cannot fit
the unchanged 600 millisecond final-release cap.

TEST-COV5E selects Outcome B. SCALE28-FIX7 must model the complete
final-release caller sequence and select one reliable fitting default.
Protected SCALE remains paused, and SCALE29 remains prohibited.

### SCALE28-ADR3 — final-release deadline and observer authority reconciliation

SCALE28-ADR3 is an architecture and specification phase under accepted ADR 0045
and status record 00667. It changed documentation only.

Four consecutive Outcome B phases had treated the observer deadline tuple as a
selection problem. ADR3 modelled the complete final-release caller sequence from
source and found the tuple was not the defect. The path carried two unrelated
deadline authorities — `_OWNERSHIP_HANDOFF_SECONDS = 0.5`, used as both the
two-sample window and every per-operation caller budget, and
`final_release_timeout_ms = 600`, which only audits state transitions — so the
last in-window operation was structurally guaranteed to be compressed, and no
tuple could be correct.

ADR 0045 selects Decision Category B. ADR 0044's hybrid preparation-worker
architecture and every preserved authority are retained; six bounded amendments
reconcile the deadline model. The cancellation-request reserve moves out of the
caller budget to the settlement authority, making an evidence-sized 120
millisecond bound affordable; bounded pre-dispatch refusal replaces silent
compression; four closed observer operation classes separate SQL-bearing from
serialization-only work; the 500 millisecond handoff constant is demoted; and the
sample separation becomes an explicit 50 millisecond floor. The 600 millisecond
final-release window is retained and now derived, 650 milliseconds is confirmed
as the live architectural maximum, and the 400 millisecond server statement
timeout is unchanged.

The phase also recorded two latent source defects for SCALE28-FIX7: operations
that issue no SQL still arm a `cancel_safe()` deadline timer, and
`BackendObserverSession.run` can overrun its declared caller budget when
operation acquisition is contended.

SCALE28-ADR3 selects Outcome A. SCALE28-FIX7 is authorized, TEST-COV5F is
required, and SCALE29 remains prohibited.

### SCALE28-FIX7 — final-release observer authority implementation

SCALE28-FIX7 implemented the complete ADR 0045 candidate without changing the
accepted hybrid architecture or frozen timing values. The candidate replaced
duplicate deadline authority and silent trigger compression with four closed
operation classes, one acquisition-aware caller deadline, bounded
pre-dispatch refusal, serialization-only no-cancel ownership, one propagated
final-release clock, and a non-early-wakeable two-sample floor.

The first 30-operation product-default fallback cohort passed. The mandatory
unchanged-candidate repeat produced `CancellationTimeout` within the frozen
120 millisecond request bound. The explicit stop condition applied; no average,
retuning, restart, or 650 millisecond headroom was used. The incomplete
production candidate was preserved privately and reverted.

SCALE28-FIX7 selects Outcome B. TEST-COV5F proceeds in characterization mode,
and SCALE29 remains prohibited.

### TEST-COV5F — final-release observer authority characterization

TEST-COV5F is test-only and freezes the pushed accepted production source. Its
independent ADR model covers twelve pre-dispatch cases, eight operation-class
cases, nine caller contexts, and twenty final-window derivations without using
candidate constants as an expectation oracle.

A new 30-operation accepted-tree client-fallback cohort produced 19 successful
requests and 11 bounded request timeouts. Retained settlement, close,
causality, terminal, reacquisition, PostgreSQL, contention, mixed, and complete
repository evidence passed. Candidate-only and blocked groups remain explicit
rather than simulated.

TEST-COV5F selects Outcome C. Before another implementation, an ADR revision
must select a configured cancellation-request tail contract and matching
settlement deadline from platform measurement. It may not raise the final
window, lower the server timeout, accept request timeout as success, or restart
cohorts for favorable results. SCALE29 remains prohibited.

### TEST-COV5G — configured cancellation-request tail characterization

TEST-COV5G froze the accepted source and policy and pre-registered the required
two-cohort configured measurement. The mandatory unchanged-source opening
complete gate failed before measurement in the accepted FIX6
candidate-characterization integration test. Operation-failure construction
overtook cancellation-timeout publication; later state reported
`request_timed_out`, but the already-constructed failure lacked its
cancellation limitation.

The exact focused test passed on immediate rerun, confirming an intermittent
cross-owner publication race. TEST-COV5G selects Outcome B and routes to
TEST-COV5G-FIX1. No configured tail evidence, request-bound selection, ADR
revision, SCALE28-FIX8 authorization, or SCALE29 authorization resulted.

### TEST-COV5G-FIX1 — cancellation projection ordering correction

TEST-COV5G-FIX1 preserves TEST-COV5G's truthful red opening-gate stop and
corrects its unproved root-cause label. The accepted integration test compared
a later terminal session snapshot with an earlier operation error.

The test-only correction records session state atomically at error construction
and asserts the error from that boundary. Deterministic barriers prove
request-first, operation-first, transport-first, and
operation-before-transport projections without production synchronization.
Later request state changes later snapshots but does not retroactively change
the already-presented error.

Twelve projection semantics, 40 publication schedules, 30 consecutive
real-PostgreSQL repetitions, retained matrices, five focused selections, and
two complete gates passed. TEST-COV5G-FIX1 selects Outcome A and routes to
TEST-COV5G-R1 measurement mode without production or policy change. ADR 0046,
SCALE28-ADR4, SCALE28-FIX8, and SCALE29 remain unauthorized.

### TEST-COV5G-R1 — configured cancellation-request characterization rerun

TEST-COV5G-R1 completed the unchanged pre-registered two-cohort,
five-condition, 500-operation configured request-tail protocol. All 500
requests succeeded; no timeout, transport failure, censoring, sample removal,
or cleanup failure occurred. The combined p95 was 85.186 milliseconds, p99
was 111.923 milliseconds, maximum was 144.905 milliseconds, and 160
milliseconds was the smallest reporting threshold with zero exceedances.

Forty deterministic same-process schedules and 20 process-feasibility cases
passed with exact settlement and cleanup. Process isolation remains
feasibility only. R1 selects Outcome A as evidence for SCALE28-ADR4; it does
not select an option or authorize ADR 0046, SCALE28-FIX8, or SCALE29.

### SCALE28-ADR4 — bounded observer cancellation containment

SCALE28-ADR4 is an architecture and specification phase under accepted ADR
0046, Decision Category A. Successful `cancel_safe()` completion becomes a
required bounded-dispatch authority at a 250 millisecond settlement-charged
bound selected from R1's pre-registered threshold ladder with an explicit
margin policy; operation settlement, request settlement, coordinated close,
fresh terminal readback, and whole cleanup receive separate fixed
authorities (900, 750, 1,000, 500, and 5,000 milliseconds); and the ADR
0044/0045 structural contract is retained intact.

Best-effort same-process cancellation is rejected because no second
deterministic containment authority exists in-process; the triple-fault
residual — a thread blocked in a C-level libpq wait — is recorded honestly
with fail-closed decision containment and connection quarantine. Process
isolation is rejected on feasibility-only evidence and retained as the sole
qualified escalation fallback. The platform contract names the supported
stack, requires runtime-identity recording, and keeps capability fail-closed
refusal; the recorded loaded-libpq identity conflict is dispositioned.

SCALE28-ADR4 selects Outcome A. SCALE28-FIX8 is authorized under a frozen
implementation contract, TEST-COV5H is required before SCALE29, and SCALE29
remains prohibited.

### SCALE28-ADR4-FIX1 — deadline origin, containment scope, and platform qualification clarification

SCALE28-ADR4-FIX1 is a documentation-only correction of ADR 0046 before
implementation, retaining Decision Category A and the 250 millisecond
request bound. It replaces the unsafe operation-origin 750 millisecond
request-settlement deadline with `D_req = 300 ms` from actual
`cancel_safe()` dispatch, so a late deadline-timer wake can never consume
the request owner's authority; reclassifies `D_op`, `D_close`, and `D_clean`
as a settlement-classification threshold and close/cleanup attempt budgets
with the triple-fault thread-reclamation residual explicitly unbounded; and
restricts the initial timing-qualified baseline to the exact R1 measured
stack, separating `has_cancel_safe()` capability from timing qualification
with an expanded requalification-trigger list. The FIX8 and TEST-COV5H
contracts gain request-origin, containment-semantics, and runtime-identity
verification duties (FIX8 red tests 5–13).

SCALE28-ADR4-FIX1 selects Outcome A. ADR 0046 remains Accepted as amended;
SCALE28-FIX8 remains authorized, TEST-COV5H remains required, and SCALE29
remains prohibited.

### ARCH — Architectural Baseline And Normalization

ARCH is closed under accepted ADR 0041 and status records 00568, 00569, and
00625 after the normalized ARCH1 through ARCH8 implementation. SCALE remains
open; no SCALE successor or protected attempt is part of ARCH-CLOSE.

The proposed sequence is:

1. **ARCH0:** as-built architecture, data authority, legacy inventory,
   algorithmic/amplification analysis, target decision, and remediation map;
2. **ARCH1:** authority/package normalization, latest-run/publication split,
   collision-free graph/control ownership, and the relocation-stable repository
   identity/migration contract without existing-row DDL;
3. **ARCH2:** typed staging-family and ordinal-contract normalization;
4. **ARCH3:** canonical parity and compatibility adapters;
5. **ARCH4:** receiptless final mutation plus legacy node/edge/evidence write
   shutdown after caller/reader parity;
6. **ARCH5:** version-tracked transactional graph/control upgrade and recovery,
   followed by stable-identity schema/data migration and then legacy staging,
   schema, and API decommissioning by forward migration;
7. **ARCH6:** proven algorithmic corrections and representation
   simplification;
8. **ARCH7:** lifecycle, readback, public-contract, HTTP privacy, platform, and
   end-user container deployment with exact ownership, streaming/private
   recovery, pinned database compatibility, collation, least-privilege roles,
   and storage/schema readiness;
9. **ARCH8:** normalized public-safe multi-repository dogfood; and
10. **ARCH-CLOSE:** accepted-debt review and SCALE-resumption gate.

The selected target is retained raw/source evidence, one canonical graph, one
explicit first-class file/source index, and temporary compatibility adapters at
public boundaries. Staging normalization retains the semantic distinction
between run-provenance `source_ordinal` and stage-proposal `family_ordinal` in
typed family descriptors.

ARCH7 implements the self-contained Linux end-user container cluster with
packaged migration resources, Psycopg and compatible PostgreSQL clients, the
matching Go helper, bounded HTTP status, read-only MCP integration, the
foreground coordinator, and one-shot administration. ARCH8 accepts its exact
ownership, stable identity, versioned upgrade, complete bounded recovery,
least privilege, privacy, and storage/schema readiness in the integrated
public-safe ladder.

ARCH1A implements the shared authority vocabulary and exact recorded/import/
publication freshness selection without schema or writer changes. Public
`latest_run_*` shapes remain compatibility projections. ARCH1B is the next
bounded phase and owns resolved database, ownership, and repository identity.

ARCH1D publishes the allowed package dependency matrix and static DAG guard,
then removes the storage telemetry SCC. ARCH1E removes the graph
discovery/extractor-routing SCC. ARCH1F removes the coordinator
protocol/launch/refresh SCC while preserving protocol, refresh, worker-launch,
patch-target, and subprocess compatibility. Three pinned SCCs remain, and
ARCH1G owns the CLI/server presentation component.

ARCH1G moves shared canonical filter validation below both CLI and MCP,
preserves the CLI main and package-facade identities, and removes the complete
five-module presentation SCC. Two pinned SCCs remain. ARCH1H owns the
operations/runtime component.

ARCH1H moves operations configuration loading below runtime adapters and
removes the operations/runtime SCC. ARCH1I places neutral structured-config
contracts below the generic registry and format implementations, preserves
facade identities and patch targets, and removes the final production SCC.
The static allowlist is empty and the committed production import graph is a
DAG. ARCH1J removes the synthetic-worker test-support subprocess exception;
the production-to-test-support allowlist is also empty.

ARCH4A through ARCH4D are complete. Complete-generation callers use receipt-bearing
staged publication. Feed, archive, WARC, bulk, generic API, and GitHub
acquisition are explicit non-publishing inputs with no mutation selectors. The
canonical-only public load and row-wise SCALE7 baseline are retired, and the
executable receiptless-binding census is zero. The two row-wise primitives and
all legacy node/edge/evidence writer machinery are removed; retained legacy
tables and migrated readers define the rollback window. Exact normalized
direct/coordinator parity, failure/recovery behavior, deterministic resource
shape, and code-only rollback without data reconstruction are accepted.
ARCH5A1 establishes ordered checksummed graph migration state for fresh managed
databases with transactional DDL/ledger updates and exact-current refusal.
ARCH5A2 establishes exact catalog recognition, verified backup-first adoption,
ledger-only bootstrap, and recovery evidence for supported pre-ledger graph
databases. ARCH5A3 establishes equivalent product-owned control-database
version and adoption authority. ARCH5A4A establishes coordinator admission,
whole-worker drain, failure release, and schema-upgrading readiness under one
control-database maintenance lock. ARCH5A4B completes the boundary with
graph-local staged-publication ownership, configured direct control ownership,
and deterministic control-then-graph exclusivity for both schema upgrade
owners. ARCH5A is complete. ARCH5B treats fresh graph/control targets as
provisional until exact schema readiness, cleans failed targets created by the
current invocation, proves retry, and refuses all pre-existing unrecognized
state. ARCH5C establishes stable repository identity, reconciliation,
relocation, and rollback acceptance. ARCH5D removes the legacy runtime schema
through one guarded forward migration. ARCH5E removes the expired compatibility
APIs, facades, aliases, flags, result schemas, connector operations, and
obsolete tests while retaining current canonical graph and file/source
readback. ARCH5 is complete; ARCH6 begins algorithmic and representation
simplification.

Implementation through ARCH-CLOSE is complete under ADR 0041 review triggers
and the per-phase verification and publication gates.

SCALE28-FIX8 selected Outcome B. Its private bounded-cancellation candidate
passed focused and disposable-PostgreSQL request evidence, then failed the
first complete gate in actual SCALE14, SCALE23, and SCALE28 owning paths:
active backend supervision failed closed and terminal backend quiescence
remained unproved. The exact exercised Psycopg/libpq stack also differs from
R1 and requires a complete 500-request requalification. Incomplete production
was removed and preserved in an owner-private binary patch. TEST-COV5H
proceeds in characterization mode; SCALE29 remains prohibited.

TEST-COV5H selected Outcome B. The exact Darwin/arm64, CPython 3.13.12,
Psycopg 3.2.12 `c`, libpq 180004, PostgreSQL 160014, loopback-TCP stack passed
the complete 500-request requalification with a 142.731 millisecond maximum
and no timeout, transport failure, censoring, sample removal, or cleanup
failure. Retained semantic and process-feasibility matrices plus a fresh
complete repository gate passed. The candidate's actual owning paths remain
the acceptance blocker. SCALE28-FIX9 owns the configured-path final-window and
active backend-supervision correction; SCALE29 remains prohibited.

ARCH8 is complete. A closed public-safe acceptance catalog passes the complete
cross-phase lifecycle, publication, recovery, compatibility, privacy,
packaging, and measurement evidence. Small synthetic, mixed fixture, RepoMap
self-host, and explicitly public full-repository rungs pass deterministic static
extraction; the public full-repository rung also passes repeated
receipt-bearing publication with equal bounded counts. No protected target was
accessed and no protected-scale result is claimed. ARCH-CLOSE completes the
epic.

ARCH8 operational recovery also closes the packaged lifecycle-admin execution
gap found by real dogfood: private artifacts resolve to the writable admin
volume, and the immutable application image invokes its fixed PostgreSQL
clients directly against the internal endpoint under an exact rendered runtime
identity. A real two-graph/control backup, empty-topology restore, control-last
readback, abrupt restart, and exact cleanup passed.
ARCH-CLOSE re-audits all 20 findings: 19 are resolved and
`ARCH0-PRIV-001` is accepted maintainability debt behind proved-safe public
adapters. The normalized target, package DAG, authority, lifecycle, recovery,
privacy, packaging, and public-safe acceptance gates are complete. No protected
operation ran and no SCALE phase began.

ARCH is closed. SCALE may resume only under a separately approved plan that
preserves ADR 0041 and begins with a new bounded public-safe evidence strategy.

SCALE28-FIX9 selected Outcome B after exact candidate reconstruction and
fourteen-case attribution. The terminal readback defect was corrected
privately without deadline movement, but repeated actual owning runs exhausted
both frozen preparation attempts before child release. The corrected candidate
remains owner-private and absent from production. TEST-COV5I proceeds in
characterization mode; SCALE29 remains prohibited.

TEST-COV5I selected Outcome B after a test-only source, protocol, failure
manifest, and category freeze. All 36 characterization cases pass, but the
candidate-dependent owning, mixed, rehearsal, and prior-state groups remain
blocked rather than inflated. SCALE28-FIX10 owns frozen preparation-worker
deadline exhaustion in actual configured observer owning paths; SCALE29
remains prohibited.

SCALE28-FIX10 selected Outcome B before reconstruction. The corrected private
patch's digest, mode, and changed-path count are known, but its owner-private
receipt does not establish the corrected patch's exact base and manifest.
Public-safe receipt and preparation-trace contracts are retained; production
and policy remain unchanged. TEST-COV5J proceeds in characterization mode and
SCALE29 remains prohibited.

TEST-COV5J selected Outcome B after an independent path-bound freeze and
37-event critical-path manifest review. Candidate-dependent preparation,
causality, owning, timing, mixed, and rehearsal groups remain blocked at zero
because exact corrected-candidate receipt provenance is absent. SCALE28-FIX11
owns receipt reconstruction and preparation attribution; SCALE29 remains
prohibited.

SCALE28-FIX11 selected Outcome C. A bounded Git patch parser proves the
corrected patch has 23 safe modified paths and fully resolvable object
identities, but five nonidentical exact base/result trees satisfy unchanged
apply, so provenance remains `nonunique_base`. The superseding trace contract
uses one global parent sequence, per-attempt worker sequences, exact failure
terminals, and ten closed variants.

Forty accepted-tree executions include 29 natural preparation timeouts.
Diagnostic calls through the existing required resource functions identify
container RSS as the dominant stage: its median already exceeds the selected
1,800 millisecond attempt policy, while its maximum remains inside ADR 0044's
5,000 millisecond ceiling. No implementation or policy value changed,
TEST-COV5K was not begun, and SCALE29 remains prohibited pending a narrowly
scoped preparation-policy decision.

SCALE28-ADR5 selected Outcome A and accepted ADR 0047 (Decision Category A).
The selected preparation implementation policy becomes 3,400 milliseconds
per attempt and 7,500 milliseconds total, derived from visible component
allowances and margins; resource-sampling ownership, subordinate deadlines,
freshness, final release, and the 5,000/10,000 millisecond architectural
maxima are unchanged. ADR 0047 also freezes the SCALE28-FIX12 fresh
test-first implementation contract and the TEST-COV5K independent
qualification contract, keeps the nonunique corrected patch excluded as
implementation authority, and defers all cleanup dispositions until after
TEST-COV5K. SCALE29 remains prohibited.

SCALE28-ADR5-FIX1 amended ADR 0047 additively before implementation. The
selected total moves from a 7,500 millisecond attempt-start gate to one
end-to-end preparation wall authority of 8,900 milliseconds (Model A,
containing both failed cleanups and explicit allowances), with a frozen
FIX12 validation rule making ADR 0044's 10,000 millisecond total maximum
mechanically enforceable and a frozen bounded-read deadline correction in
the preparation worker. Runtime qualification is corrected to status Q2
with a complete runtime-identity contract; the startup-handoff coupling is
retained and qualified; the 3,400 millisecond attempt timeout and all
architectural maxima are unchanged. SCALE28-FIX12's authorized scope now
also covers exactly the validation and bounded-read corrections; TEST-COV5K
must bind the first exact-stack qualification receipt. SCALE29 remains
prohibited.

SCALE28-FIX12 closed as a bounded stop without implementing any of that
scope. The opening gate failed for reasons unrelated to the old preparation
policy — no test in this repository is collectible in the executing
environment, and no container plane is reachable — so production mutation
stopped as the phase contract requires. The 1,800 / 4,100 millisecond policy,
the hardcoded SIGTERM join, the absent derived-wall validation, and the
additive bounded-read defect all remain in `tools/`. The phase also isolated
finding FIX12-F1: the engine-reported platform name does not discriminate the
container engine implementation, so the runtime identity contract cannot yet
support a trustworthy qualification receipt. TEST-COV5K is not authorized and
SCALE29 remains prohibited.

## SCALE28-FIX12-DIAG1 Runtime Process-Boundary Findings

`SCALE28-FIX12-DIAG1` (2026-07-28) characterized the runtime process boundary
without changing production. Its findings reshape two roadmap items.

The container-RSS reader is **not** production code. It lives in
`tools/scale12_resource_sampling.py`, `tools/` is not packaged, and no module
under `src/main/python` imports it. Roadmap entries that treat the docker-stats
sampler as a production runtime hot path should be re-scoped: replacing it
changes diagnostic scaffolding, not the shipped runtime, and would not add a
production dependency.

A new item is open ahead of the sampler work: a Psycopg-selected runtime read
can execute psql. `ops/readback.py` in `host_then_container` mode answers a
connection-class psycopg failure by re-dispatching through
`<container-runtime> exec -i <container> psql`, on MCP server readback and
configured public refresh paths. The behavior is deliberate and already covered
by existing `test_psycopg96_*` cases, but connector selection does not govern
it. A deterministic regression is retained at
`src/test/unit/python/repomap_kg/ops/scale28_diag1_psql_boundary.unit.test.py`,
marked strict-xfail against the contract it should satisfy. Production is not
repaired until `SCALE28-ADR5-FIX2` settles the connector boundary.

Measurement for the sampler decision is complete: 90 CLI and 90 Engine API
observations across quiet, CPU-contention, and container-workload conditions.
The CLI reader is bimodal with a ~2,000 ms median and one process spawn per
sample; the in-process one-shot call has a ~3 ms median and no spawn. Under
cgroup v2 the CLI value equals `usage - inactive_file` byte for byte, and does
not equal raw `usage`.

The 1,800 / 4,100 millisecond policy, the hardcoded SIGTERM join, the absent
derived-wall validation, and the additive bounded-read defect all remain
in `tools/` and are untouched. TEST-COV5K is not authorized and SCALE29 remains
prohibited.

## SCALE28-FIX12-DIAG1-FIX1 Test Scratch Ownership

`SCALE28-FIX12-DIAG1-FIX1` (2026-07-28) gave the repository one owner for every
temporary, cache, and build-state path a test run creates.

`repomap_test_support.test_scratch` selects a scratch root by explicit
environment variable, then a Darwin shared root when one already exists and is
safe, then a portable fallback beneath `tempfile.gettempdir()`. It never
creates the operator-managed shared root. It allocates a short run root by
exclusive directory creation rather than by time, writes a public-safe
manifest and a monitoring-index symlink, and exposes one complete child
environment covering `TMPDIR`, `TMP`, `TEMP`, `PYTHONPYCACHEPREFIX`,
`GOTMPDIR`, `GOCACHE`, `GOLANGCI_LINT_CACHE`, `PIP_CACHE_DIR`, and
`BUILDX_CONFIG`. `DOCKER_CONFIG` is deliberately never set and the active
Docker context is never changed.

Three properties are worth keeping in mind when extending it.

`apply()` resets `tempfile.tempdir`. An earlier `tempfile.gettempdir()` call
caches its answer, and without the reset that cached value silently outranks
the new `TMPDIR`.

The layout must be installed before Go validation, not before pytest.
`tools/run_tests.py` runs the Go toolchain first, so establishing the scratch
later would leave Go writing outside the run root.

Only the process that allocated a run root may mark it terminal. The runner's
own tests invoke `main()` repeatedly inside one outer run; a borrower that
finalized an inherited root would collide with the allocator on a state it does
not own.

For tests that create Unix-domain sockets, use `short_test_directory` and pass
the longest relative path the test actually creates. The helper measures
encoded bytes against a conservative 103-byte `sun_path` limit and refuses
before execution rather than failing at `bind()`. Do not root a second scratch
tree under pytest's `basetemp`: that now lives inside the run root, so the
nested path is far deeper than any real caller's.

## SCALE28-FIX12-DIAG1-FIX2 Scratch Ownership And Direct-Pytest Lifecycle

`SCALE28-FIX12-DIAG1-FIX2` (2026-07-29) narrowed the scratch authority above
and gave standalone pytest a terminal owner. Four things are worth knowing
before extending `test_scratch` or the common conftest again.

**A conftest cannot own initial configuration.** `pytest_load_initial_conftests`
defined in a `conftest.py` never fires. pytest loads conftests *during* that
hook, and the hook is not historic, so the implementation is registered too
late to be called. Import-time work in the conftest body still runs first and
is the only lever a conftest has over `TMPDIR`. Accept the two resulting
basetemp spellings — `<run>/pt` under the runner, pytest's own basename under
`<run>/tmp` standalone — rather than shipping the conftest as an installed
plugin to unify them.

**`pytest_sessionfinish` is the lifecycle owner, and there must be exactly one.**
It fires on pass, failure, and collection error. Ownership is decided by
`TestScratchLayout.allocated`, so a pytest launched under `tools/run_tests.py`
is a no-op and the runner keeps its own run. Do not add an `atexit` handler:
a process killed outright should leave `running` behind for an operator, not
be recorded as a clean finish.

**Beneath the scratch root is not proof of ownership.** `/Users/Shared/agent-scratch/r`
holds runs from other projects and other agents. Inheriting a run requires an
exact manifest — schema, `run_kind`, project, phase when supplied, `run_id`
matching the directory name, `physical_run_root` canonicalizing to it, and
state `running` — with the expected project and phase passed in explicitly
rather than read back out of the manifest being checked. Finalization
revalidates the same identity immediately before writing, and writes only that
one manifest. Never enumerate the shared run directory to find manifests to
close: doing exactly that damaged three other projects' records during the
DIAG1-FIX1 closeout.

**The monitoring index fails closed.** An existing entry is reused only when it
is a symlink whose canonical target is this exact run root, beneath the scratch
root. A regular file, a real directory, a dangling link, a link to another run,
or a link outside the root all raise. Nothing is overwritten, unlinked,
renamed, or silently reused, and the error is never swallowed into `None`.

Test fixtures that must not be collected by the ordinary suite belong in
`src/test/fixtures/`, outside `testpaths` and `TEST_ROOTS` but still beneath
`src/test/` so the common conftest loads. That is how the deliberately failing
and collection-error direct-pytest fixtures are kept out of the gate.

## SCALE28-FIX12-DIAG1-REVIEW1 Capable-Environment Gate

Independent review accepts the DIAG1-FIX1/FIX2 scratch, lifecycle, manifest,
monitoring-index, and process-boundary implementations. The exact nine former
`/bin/ps` nodes pass in a capable environment, and their prior failures remain
attributed to sandbox `EPERM` before useful product behaviour. This result does
not architecturally approve `/bin/ps`.

The four `load_sources` residuals were test assertion defects, not
canonicalization nondeterminism. Acquisition left the canonical graph empty as
required; the tests then explicitly published observations and incorrectly
asserted that the post-publication graph and provenance counts remained empty.
The corrected tests preserve the staged-publication boundary and assert exact
fixture-specific post-publication contents.

The complete repository gate is green with 5,585 passed, 10 skipped, 1 strict
xfail, 92.7% line coverage, 85.1% branch coverage, and passing container smoke
with exact image cleanup. No production source, dependency metadata, graph
vocabulary, hidden-psql behaviour, or frozen 90/90 dataset changed.

`SCALE28-ADR5-FIX2` is authorized for Claude Fable 5. It owns the no-CLI
runtime-data-plane decision; this review does not implement that decision.
`SCALE28-FIX12-R1`, `TEST-COV5K`, and `SCALE29` remain unauthorized.

## SCALE28-ADR5-FIX2 In-Process Runtime Data Plane

The runtime data-plane decision is closed in ADR 0047's SCALE28-ADR5-FIX2
amendment. For contributors, the durable rules are:

**Runtime data-plane code never shells out.** MCP/configured readback,
observer database work, refresh hot-path readback, and both preparation
RSS reads use in-process libraries only: Psycopg, psutil, and the Docker
Engine API through the Python Docker SDK. A Psycopg-selected read that
hits a connection failure returns a structured error with the topology
hint — it must never silently re-execute as `psql` or `docker exec`.

**CLI is for the explicit administrative plane.** Backup, restore,
migration, database lifecycle, bulk psql-native load, container
lifecycle, test-harness lifecycle, and operator diagnostics may keep
bounded fixed-argv subprocesses, but only under explicit selection, with
the host executable and nested command intent visible in evidence, and
never reachable as an automatic fallback from runtime reads.

**Names must not lie about transport.** `host_only` and
`host_then_container` become psql-plane parameters after
`SCALE28-FIX12-R1`; the Psycopg path has no topology-fallback axis.
`REPOMAP_STORAGE_READBACK_DRIVER` and `REPOMAP_PSQL_COMMAND` keep their
meanings.

**Operational dependencies live in `scale-tools`.** psutil and the Docker
SDK belong to the dedicated optional-dependencies group, exact-pinned;
they must not be added to the shipped `repomap_kg` dependencies. A missing
operational dependency fails at import time — it is never `None`, zero
RSS, or `resource_unavailable`.

**Failure is structured, never zero.** Reader failures map to `None` and
then to `resource_unavailable` at the exact reader boundary; raw
`memory_stats.usage` is never CLI-equivalent memory; peak RSS is never
current RSS; unsupported stacks refuse.

Implementation belongs to `SCALE28-FIX12-R1` under the amendment's frozen
contract; qualification belongs to `TEST-COV5K`. Until R1 lands, the
hidden fallback and both subprocess readers remain in the tree with their
strict-xfail and behavioral tests unchanged.

## SCALE28-FIX12-R1 In-Process Runtime Data Plane

R1 has landed the ADR 0047 data-plane boundary:

- Psycopg selection is closed: connection-shaped failure keeps the existing
  topology guidance but never changes transport to psql or `docker exec`;
- the explicit psql driver retains `host_only` and `host_then_container`;
- process and process-tree RSS use psutil current-RSS bytes without `/bin/ps`
  or host-wide enumeration;
- container RSS uses a short-lived Docker SDK low-level client, one exact
  one-shot stats call, and `usage - inactive_file`;
- Docker negotiation and stats share the retained 2.0-second reader budget;
- Docker environment/context resolution is honored, while an ambiguous Podman
  endpoint fails closed rather than querying the wrong engine;
- psutil 7.2.2 and Docker SDK 7.2.0 live only in the exact-pinned
  `scale-tools` extra; and
- runtime identity is complete and redacted but remains unqualified.

The administrative/lifecycle/diagnostic CLI plane remains explicitly
permitted and bounded. The runtime data-plane process target is zero; this is
not a whole-refresh zero-process claim. The hidden-psql xfail is now a passing
regression. Qualification still belongs to TEST-COV5K after the operator
shared-tip guard, and SCALE29 remains prohibited.

## TEST-COV5K-R1 Capable-Environment Disposition

The retry proved that the prior environment blockers are removable without
changing repository policy: the exact-pinned scale tooling, host diagnostics,
Docker endpoint, loopback, disposable PostgreSQL/Psycopg path, Engine API
one-shot read, complete runtime identity, and exact cleanup all passed.

The first Group A policy observation then stopped the phase. The accepted R1
tip still selects 1,800/4,100 milliseconds; TEST-COV5K requires the
ADR 0047 3,400/8,900 implementation and end-to-end validation owned by the
full SCALE28-FIX12 contract. Outcome B authorizes no repair in the
qualification phase. SCALE29 remains prohibited pending implementation,
acceptance, and a fresh exact-stack qualification retry.

## SCALE28-FIX12-R2 Opening-Gate Disposition

R2 recreated the exact capable environment and passed the complete repository
all-suite opening gate. The separately mandated
`python -m compileall -q src/main/python src/test tools` command then selected
two deliberately malformed extraction fixtures under `src/test` and failed.

The phase followed its opening-gate stop rule before source freeze or
candidate mutation. The 3,400/8,900 policy, mechanical wall validation,
bounded-read correction, and observer/terminal completion remain pending.
TEST-COV5K-R2 and SCALE29 remain unauthorized.

## SCALE28-FIX12-R2-FIX1 Preparation And Observer Completion

The bounded retry has landed the remaining accepted FIX12 behavior:

- preparation selects 3,400/8,900 milliseconds and validates the exact
  mechanically derived end-to-end wall;
- all nested preparation reads share one absolute attempt authority, cleanup
  precedes retry, and cleanup limitation prohibits attempt two;
- the four observer operation classes, actual-dispatch request clocks,
  settlement-only operation deadline, quarantine-safe close, one later close
  retry, terminal readback, and incomplete-cleanup semantics are implemented;
- a validated pre-release sample counts as sample one under the one 600
  millisecond final deadline, with one later sample after the 50 millisecond
  floor; and
- the R1 in-process data plane and unqualified complete runtime identity remain
  unchanged.

Implementation campaigns, the frozen timing protocol, complete gates, and
cleanup pass. TEST-COV5K-R2 owns fresh exact-stack qualification after operator
shared-tip acceptance. SCALE29 remains prohibited until that qualification
selects Outcome A.

## SCALE28-FIX12-R2-FIX2 Terminal And Evidence Correction

Independent review found that the accepted terminal readback used a
post-return elapsed check and that its 500-request evidence support imported
the product request bound. The correction keeps the established architecture:
one in-process low-level Psycopg/libpq connection performs one terminal query
under one absolute 500 millisecond authority, with no process, psql, retry, or
watcher owner.

Qualification evidence now has a test-owned ADR 0046 tuple and separate policy
and source digests. Historical cohort definitions remain evidence inputs, not
the successor expected-value oracle. This is a bounded correction, not a new
refactor phase. TEST-COV5K-R2 and SCALE29 remain outside the phase.
