# RepoMap Review Standards

Reviews should protect behavior, boundaries, and project readability.

## Review Focus

Check in this order:

1. Scope matches the accepted phase or user request.
2. Public behavior, CLI/MCP contracts, storage contracts, graph vocabulary,
   and extraction semantics are preserved unless intentionally changed.
3. Tests cover behavior changes and boundary changes.
4. Static extraction, redaction, private-data, and non-execution boundaries
   are preserved.
5. Dependency changes are justified and documented.
6. Docs, ADRs, release notes, and contributor skills are updated when
   public behavior or standards changed.
7. Formatting, naming, and local style are consistent.

Style nits should not distract from behavior, safety, privacy, deterministic
extraction, or phase-boundary issues. Verify docs and release notes are
durable enough that the audit trail does not live only in chat.

## Phase Hygiene

Phase commits should include the phase ID in the subject and durable scope plus
verification details in the body. Public releases and changes are documented
in [CHANGELOG.md](../../CHANGELOG.md) and `docs/releases/`.

Docs-only changes should state that source tests were not run because the
change is docs-only. Source and test changes should run proportional local
verification justified by scope; hosted CI owns routine exhaustive correctness
under `testing-standards.md`.

Reviewers first assess whether the exact selected unit owners and any
changed-boundary integration owners cover the changed contract. When evidence
is narrow, identify the missing exact paths or node IDs, or a justified wider
package or directory selection. Do not demand or execute a complete suite as
generic caution. If only complete-population evidence can resolve the risk,
state why and request a current prompt-owned complete-suite override; review
authority alone cannot grant one.

## Commit Hygiene

A phase normally produces one final commit. Additional commits are permitted
only for actual source, test, schema, operational-evidence, or independently
identified correctness corrections. Review approval, report generation,
remote-parity confirmation, checklist completion, and wording cleanup do not
receive standalone commits. A no-findings review does not mutate the
repository.

## Private-Data Check

Public commits must not include secrets, private graph data, DB dumps, backup
receipts, raw observations from private repositories, private source snippets,
or local operator paths unless a path is intentionally public-safe
documentation.
