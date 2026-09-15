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
6. Docs, ADRs, status records, and contributor skills are updated when
   public behavior or standards changed.
7. Formatting, naming, and local style are consistent.

Style nits should not distract from behavior, safety, privacy, deterministic
extraction, or phase-boundary issues. Verify docs and status records are
durable enough that the audit trail does not live only in chat.

## Phase Hygiene

Phase commits should include the phase ID in the subject and durable scope plus
verification details in the body. Status docs should record what changed, what
was intentionally left out, verification results, and report-command status.

Docs-only phases should say source tests were not run because the change is
docs-only. A new primary phase record under `docs/status/` must be an exit
report in the daily archive, use the next global five-digit number, end in
`-exit.md`, include `Exit` in its H1, and state a truthful terminal
disposition. Historical status records that do not follow this framing are
grandfathered but do not authorize new exceptions. Source/test phases should
run proportional local verification justified by phase scope; the hosted gate
owns routine exhaustive correctness under `testing-standards.md`.

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
