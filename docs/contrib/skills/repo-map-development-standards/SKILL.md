---
name: repo-map-development-standards
description: Use when modifying RepoMap source, tests, docs, ADRs, status docs, or contributor guidance and needing the project's coding, dependency, scope, safety, and review standards.
---

# RepoMap Development Standards

## Start Here

Use the human-facing standards under `docs/contrib/` as the source of truth:

- `docs/contrib/coding-standards.md` — general engineering defaults, Python
  style, extraction and graph semantics, PostgreSQL and storage boundaries.
- `docs/contrib/go-standards.md` — Go toolchain, layout, testing, and
  library standards for approved Go components.
- `docs/contrib/dependency-standards.md` — dependency evaluation and review.
- `docs/contrib/testing-standards.md` — suites, gates, and test layout.
- `docs/contrib/review-standards.md` — review priorities and commit hygiene.
- `docs/contrib/file-length-profile.md` — the authoritative tracked-Python
  file-length policy and its executable contract.
- `docs/contrib/test-refactor-authorization.md` — standing authorization and
  boundaries for opportunistic test reorganization.
- `docs/contrib/documentation-reference-policy.md` — how to cite phases,
  commits, and historical records.
- `docs/contrib/phase-identity-policy.md` — phase identity and family rules.
- `docs/contrib/refactor-roadmap.md` — the living readability/refactor
  roadmap.

## Working Rules

- Keep work scoped to the active phase or user request.
- Follow existing RepoMap module patterns before inventing new abstractions.
- Write idiomatic Python. Avoid Java-style layering and ceremony.
- Separate IO, parsing/scanning, domain logic, storage/query logic, and
  formatting when that makes behavior clearer or easier to test.
- For readability/refactor phases, follow the incremental roadmap and keep
  behavior-preserving source moves separate from behavior changes.
- Prefer coherent abstractions and loose coupling, but allow small
  duplication when a shared abstraction would be worse.
- Keep extraction static-only unless an accepted phase explicitly says
  otherwise.
- Do not commit private graph data, DB dumps, receipts, raw private source,
  or secrets.
- Evaluate dependencies with `docs/contrib/dependency-standards.md` before
  proposing them.
- Protect maintained Python code quality under ratchets immediately without
  awaiting hypothetical replacement (architectural placement is reserved for
  post-main; see `testing-standards.md`).

## Before Finishing

- Update relevant docs, ADRs, status docs, and contributor skills when
  public standards or behavior changed.
- Use the commit contract in `repomap-phase-hygiene` when the task is a
  named phase.
- Run the verification required by `docs/contrib/testing-standards.md`
  (routed by `repo-map-testing-standards`).
