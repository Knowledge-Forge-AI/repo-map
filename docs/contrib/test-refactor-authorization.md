# Test Refactor Authorization

RepoMap's tests are among the largest and hardest-to-navigate files in the
repository, so test organization improvement is a standing cross-cutting
maintenance effort. This document owns the standing authorization and its
boundaries.

## Authorization Boundary

Opportunistic test refactoring is authorized only when an agent or
contributor is already editing the relevant test file or directly adjacent
production code. It is not permission to turn unrelated feature, bugfix,
docs, extraction, storage, or runtime work into a broad test-reorganization
pass.

Apply these rules conservatively:

- Preserve behavior and assertions unless the accepted task explicitly
  changes behavior.
- Prefer splitting by production module, command group, behavior boundary,
  or fixture family.
- Keep moved tests discoverable by the current pytest configuration (see
  `docs/contrib/testing-standards.md` for roots and filename patterns).
- Keep public fixtures and temporary state public-safe.
- Do not weaken coverage thresholds, delete assertions, skip tests, or mark
  failures acceptable to make a split easier.
- Do not mix unrelated production refactors into test-file cleanup.
- When unsure whether a move is safe, leave the test in place and add only
  the focused test changes needed for the task.
- Record test-file moves and verification in the commit/status notes for
  the current task.

## Unit Tests

Scope: unit test files under `src/test/unit/python`.

If you are already editing a unit test file and that file is oversized,
poorly scoped, or mixing unrelated production modules, you are authorized to
split, move, and rename the touched tests as needed to improve local order.

Preferred shape:

- Unit tests for `src/main/python/repomap_kg/<module_path>.py` should live
  under `src/test/unit/python/repomap_kg/<module_path>.unit.test.py`.
- If one production module has several large behavior areas, split into
  focused files under an appropriate subdirectory, for example
  `src/test/unit/python/repomap_kg/<module_name>/<behavior>.unit.test.py`,
  as long as pytest still discovers the files.
- Unit tests for support code under `tools/` or other non-package paths
  should live under
  `src/test/unit/python/<source-path-relative-to-repo-root>/<base-source-file-name>.unit.test.py`
  when that path is practical and discoverable.
- Tests for code under `src/test/support/python` may stay near existing
  support-test conventions; do not force them into production-module
  mapping.

Rules:

- A unit test file should primarily test one production source module or
  one coherent behavior boundary.
- If a test necessarily spans multiple modules, name it after the behavior
  contract rather than pretending it belongs to one source file.
- If a unit test exercises a file outside this repository or opaque local
  runtime state, do not move it as part of this refactor.
- Run the affected unit suite, then the proportional local verification
  required for the task.

## Integration Tests

Scope: integration test files under `src/test/int/python`.

If you are already editing an integration test file and that file is
oversized, poorly scoped, or mixing unrelated runtime/storage/CLI contracts,
you are authorized to split, move, and rename the touched tests as needed to
improve local order.

Preferred shape:

- Integration tests for a production module or command family should live
  under
  `src/test/int/python/repomap_kg/<module_or_command_boundary>.int.test.py`.
- If one integration area is too large, split into focused files under an
  appropriate subdirectory, for example
  `src/test/int/python/repomap_kg/storage/<behavior>.int.test.py` or
  `src/test/int/python/repomap_kg/cli/<command_group>.int.test.py`, as long
  as pytest still discovers the files.
- Integration tests for `tools/` or other non-package runtime behavior
  should live under
  `src/test/int/python/<source-path-relative-to-repo-root>/<base-source-file-name>.int.test.py`
  when that path is practical and discoverable.

Rules:

- Integration tests should prove runtime, storage, CLI, MCP, container, or
  cross-module contracts; they do not need to map one-to-one to a single
  production file when the real contract crosses modules.
- Prefer splitting giant integration files by durable public behavior, such
  as storage readback family, canonical contract family, CLI command group,
  local runtime lifecycle, or report behavior.
- Do not move tests that directly depend on external private resources,
  local machine state, or ambiguous runtime state as part of opportunistic
  cleanup.
- Preserve the containerized Postgres harness for integration and combined
  suites.
- Run the affected integration suite with `--pg-container-port 55433`, then
  the proportional local verification required for the task.
