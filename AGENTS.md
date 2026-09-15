# RepoMap Agent Instructions

These instructions apply to AI coding-agent sessions launched from the root
of the RepoMap repository. This file is the shared, agent-neutral project
entrypoint; agent-specific adapters such as `CLAUDE.md` supplement it and
must not weaken it.

RepoMap is a deterministic knowledge graph system for polyglot software
repositories. The current implementation is local and PostgreSQL-backed; the
long-term product direction is cloud-first with additive multi-source graph
composition. The local system remains the as-built/reference implementation.
Its Python distribution is `repomap-kg`, its import package is `repomap_kg`,
and its CLI is `repomap-kg`.

## Instruction Precedence

When instructions conflict, apply them in this order:

1. The explicit user request or approved phase scope for the current task.
2. This `AGENTS.md`, then any agent-specific adapter file.
3. The skills routed below.
4. Human-facing standards under `docs/contrib/` and operations references
   under `docs/ops/`.
5. Existing local code style and tests.

Do not use these instructions as permission for broad rewrites. If the user
clearly expresses an intent and a detail here appears mistaken, preserve the
intent and correct the detail instead of ignoring the intent.

## Critical Safety Boundaries

These boundaries hold for every task:

- Static extraction does not execute target repository code by default.
- Redact first: fixtures, docs, tests, and outputs must be public-safe.
- Never put secrets, private identities, private paths, or raw private
  runtime data in public output or commits.
- The RepoMap MCP surface remains read-only.
- Runtime/database destructive work is backup-first and scoped to
  RepoMap-owned resources.
- The local runtime is containerized and localhost-bound by default; do not
  assume host Postgres, host IPC, or a developer's live database.
- Public behavior, schema, CLI/MCP contract, or graph vocabulary changes
  require explicit phase authority.

## Skill Routing

| Task | Skill or policy |
|---|---|
| Folder-backed graph maintenance, refresh and drift gates, canonical CLI readback, backup-first DB lifecycle, source ingestion | `docs/ops/skills/repomap-cli-workflow` |
| Read-only MCP server configuration, registries, resolution | `docs/ops/skills/repomap-mcp-configuration` |
| MCP query workflow over graph, search, and source tools | `docs/ops/skills/repomap-mcp-readback` |
| Post-configuration MCP verification | `docs/ops/skills/repomap-mcp-smoke-test` |
| Phase planning, status exits, ADRs, commit messages | `docs/contrib/skills/repomap-phase-hygiene` |
| Coding, dependency, safety, and review standards routing | `docs/contrib/skills/repo-map-development-standards` |
| Test selection, gates, docs-only verification | `docs/contrib/skills/repo-map-testing-standards` |
| Hosted-CI state, conservation, result classification, and remote trigger stewardship | `docs/contrib/ci-agent-policy.md` |

The `.agents/skills` and `.claude/skills` catalogs are active discovery
projections of the same seven skills. Their relative, repository-contained
symlinks point directly to the canonical skill bodies under `docs/`;
projection bodies are never canonical.

## Repository Shape

- `src/main/python/repomap_kg/` — main Python package.
- `src/main/go/` — approved Go components (`docs/contrib/go-standards.md`).
- `src/test/unit/python/`, `src/test/int/python/`,
  `src/test/support/python/` — test roots; `tools/run_tests.py` is the
  standard test runner.
- `docs/ops/` — operator skills and durable operations references.
- `docs/contrib/` — contribution standards and contributor skills.
- `docs/adr/YYYY/MM/` — ADRs (independent four-digit sequence).
- `docs/status/YYYY/MM/DD/` — complete historical status archive; new
  primary phase records use the next global five-digit number, end in
  `-exit.md`, and have an H1 title containing `Exit`.
- `.agents/skills` and `.claude/skills` — skill discovery projection
  catalogs for the canonical skill roots under `docs/`.

Do not relocate project roots, package names, CLI names, test roots, status
paths, or ADR paths unless an accepted phase explicitly authorizes it.

## Git, Phases, And Publication

1. Work on the explicitly authorized branch or worktree (normally `main`).
2. Run the verification required by `repo-map-testing-standards`.
3. Commit the completed phase using the `repomap-phase-hygiene` contract.
4. Generate the required local report for the exact commit.
5. Publication to a remote is performed only by an actor with authorized
   remote access.

Do not create a task branch, pull request, merge commit, or replacement
commit unless the user explicitly requests one. Never force-push or rewrite
an already reported phase commit.

Before any push, pull-request state change, workflow dispatch, rerun,
cancellation, merge, or promotion, consult `docs/contrib/ci-agent-policy.md`
and require explicit current authority for the remote action.

The `file-length` profile in `docs/contrib/file-length-profile.md` is
authoritative for included tracked Python files.

## Task-Open Obligations

Before editing:

- Identify the active phase ID, issue, PR, or user-approved task scope.
- Read the skills routed above that match the task, and any directly
  relevant standard under `docs/contrib/`.
- Inspect nearby code and tests before inventing new patterns.
- Determine whether the change is docs-only, test-only, source-affecting,
  schema-affecting, runtime-affecting, or behavior-affecting.
- Use scoped unit and changed-boundary integration selectors by default.
  Complete unit, integration, staging, or system runs require an explicit
  override in the current prompt.

## Task-Closeout Obligations

Before finishing:

- Run the verification required for the change class, and keep a short note
  of commands run and commands intentionally not run.
- Record exact unit and integration selectors and results, plus every complete
  suite intentionally unselected under the scoped-testing policy.
- Record scope, boundaries, and verification in the commit message, status
  doc, or ADR — durable history must not live only in chat.
- Update docs, ADRs, status records, and skills when public behavior or
  standards changed.
- Use ADRs before implementation when graph shape, storage semantics,
  extraction policy, ingestion policy, privacy/security policy, CLI/MCP
  behavior, or architecture boundaries materially change.

## Maintenance Rule

Keep this file within 160 physical lines and `CLAUDE.md` within 40. Detailed
procedure belongs in the routed skills and durable references, not here;
when this file grows, move content to its canonical owner instead of
expanding this document.
