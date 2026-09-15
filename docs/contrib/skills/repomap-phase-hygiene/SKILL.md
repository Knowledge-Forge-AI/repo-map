---
name: repomap-phase-hygiene
description: Use when planning, documenting, verifying, committing, amending, or reviewing RepoMap phases, ADRs, status exits, docs-only updates, source slices, test harness changes, test report work, smoke tests, or extended-phase exit audits.
---

# RepoMap Phase Hygiene

## Overview

RepoMap history is part of the project audit trail. Every phase commit should
name the phase, state scope and boundaries, and record verification in the
commit body.

This is a contributor/development skill. Operator/runtime RepoMap skills live
under `docs/ops/skills/`; contributor skills live under
`docs/contrib/skills/`. This skill is the sole owner of the commit-message
contract and template; other guidance points here rather than repeating it.

## Commit Message Contract

Use this shape for RepoMap phase commits:

```text
PHASE_ID: short imperative summary

Scope:
- what changed
- important boundaries and non-goals

Verification:
- unit: <exact scoped selectors, command, and result, or "not selected; <scope reason>">
- int: <exact scoped selectors, command, and result, or "not selected; <scope reason>">
- complete-suite override: <absent, or authority, suites, and executions consumed>
- staging: <command and result, or "not selected; <scope reason>">
- system: <command and result, or "not selected; <scope reason>">
- compileall: <command and result, or "not selected; <scope reason>">
- git diff --check: <result>
- git diff --cached --check: <result>

Hosted CI:
- state: <AVAILABLE | CONSERVE | EXHAUSTED | UNKNOWN>
- remote write/trigger: <what occurred, or not performed>
- automatic lanes expected: <names, or none>
- execution classification: <closed classification, or not applicable>
- pending gates: <names and candidate boundary, or none>
- local evidence sufficiency: <what it proves and what remains unsatisfied>
```

For docs-only phases, use `not run; docs-only` for unit, int, staging, system,
and compileall. For source/test phases, exact scoped unit and changed-boundary
integration verification is the ordinary default. Keep each unselected entry
truthful and specific, record pending pipeline gates, and never present scoped
evidence as whole-population qualification.

Do not use vague subjects such as "Add docs" or "Update skills". The subject
must preserve the current phase id. Follow
`docs/contrib/phase-identity-policy.md` for phase identity and family rules.

Use the closed state and result vocabulary from the
[hosted-CI stewardship policy](../../ci-agent-policy.md). Every phase closeout,
whether recorded in the commit, status exit, or both, states the hosted-CI
state, whether any remote write or trigger occurred, expected automatic lanes,
hosted execution classification, pending hosted gates, and why local evidence
is or is not sufficient. A GitHub conclusion alone is not the execution
classification.

Useful local checkpoint commits are explicitly acceptable during `CONSERVE` or
`EXHAUSTED` when the current task or manager authorizes local commits. They do
not authorize publication, satisfy pending hosted evidence, or relax the final
phase commit contract.

## Phase Families

Docs-only phase updates include ADRs, status audits, README examples, and
skill docs. Run docs-only verification, and record
unit/int/staging/system/compileall as not run because the change is docs-only.

Status docs remain in the complete historical archive under
`docs/status/YYYY/MM/DD/`, where placement uses the introducing commit's
local committer-date encoding and the five-digit sequence is global across
the archive. New primary phase records must be exit reports, end in
`-exit.md`, and have an H1 containing `Exit`; historical deviations are
grandfathered but do not authorize new deviations. ADRs use the independent
four-digit sequence under `docs/adr/YYYY/MM/`.

Source-code phases add or change executable behavior. Use TDD, keep the slice
bounded, add or update an exit status record, and run proportional local
verification under `repo-map-testing-standards`, including affected tests,
relevant compile/static checks, diff, and cached-diff checks. Hosted CI owns the
routine promotion gates; a local staging or system gate remains available when
the operator or accepted phase explicitly requires complete local evidence.
Integration selections use RepoMap's containerized Postgres harness; do not
fall back to host IPC or a developer's live database.

Test harness phases may change `tools/run_tests.py`, test support packages,
or temporary Postgres behavior. Keep operational cleanup conservative and
document what will not be touched, such as attached, other-user,
live-cluster, semaphore, message-queue, or ambiguous IPC resources.

Test report phases may use focused report-generator tests and targeted
compileall when the slice is isolated to report rendering. Promote to full
unit/int/staging/system verification when runner behavior or broader RepoMap
behavior changes.

Smoke-test phases document a reproducible manual or MCP check. If docs-only,
run docs-only verification and record source tests as not run. Include the
exact tool sequence, expected read-only boundary, and failure
classification.

Extended-phase exit sub-phases close a larger phase after earlier
implementation slices. Confirm what is already available, what remains
unchanged, and which later phase has not started. These are often
docs/status-only.

## Qualification Evidence Routing

For qualification claims and evidence handling, follow
`docs/contrib/qualification-evidence-contract.md`; ADR 0049 remains the
architectural authority. A positive qualification claim requires candidate
identity and a qualification attempt declared before execution. Ordinary
development or scoped runs cannot be promoted retroactively.

When the active orchestration environment supplies an artifact destination,
produce the managed-run response, report, and evidence bundle on every terminal
outcome. These private operational artifacts, including APG reports, are never
sole durable support for acceptance. A preserved checkpoint whose final
qualification is incomplete must say `NOT ACCEPTED` (or the equivalent
`candidate accepted: false`) rather than implying acceptance from maintenance
or diagnostic proof. Route test and coverage provenance fields to
`repo-map-testing-standards`; do not duplicate them here.

## ADR Template

RepoMap ADRs normally use:

- `# ADR NNNN: Title`
- `## Status`
- `## Date`
- `## Context`
- `## Decision`
- explicit `## Scope` or `## Scope and Non-Scope`
- policy/model sections for identity, storage, extraction, ingestion,
  security, privacy, readback, or CLI behavior as applicable
- raw observation, canonical namespace, and edge vocabulary sections when
  graph shape changes
- fixture and required-test sections for the next implementation phase
- rejected alternatives
- proposed phases or consequences

ADRs should define boundaries before code lands. Architecture-only ADR
commits must not imply implementation, migrations, MCP tools, provider
integrations, or public default changes unless the ADR explicitly accepts
them.

## Pre-Commit Checklist

- Changed files match the intended phase family.
- Subject starts with the phase id.
- Scope records both what changed and what stayed out of scope.
- Verification lists exact unit and integration selectors and results, or
  truthful scope reasons when not selected; staging, system, compileall,
  `git diff --check`, and `git diff --cached --check`; and the complete-suite
  override status, authority, suites, and execution count.
- The required `Hosted CI:` block records state, remote actions, expected lanes,
  execution classification, pending gates, and local-evidence sufficiency.
- Pending pipeline gates remain explicit, and scoped evidence is not described
  as whole-population qualification.
- Docs-only commits explicitly say source-code tests were not run because
  the change is docs-only.
- The durable record is in the commit message, status doc, or ADR, not only
  in chat.
