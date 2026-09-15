# RepoMap Agent Hosted CI Stewardship Policy

## Purpose And Authority

GitHub-hosted Actions is a scarce qualification resource. Agents conserve it
even when capacity is available, stop creating trigger events when capacity is
exhausted, and preserve the distinction between admission evidence and
candidate execution evidence.

This document is the detailed procedural owner for agent use of hosted CI. It
implements [ADR 0054](../adr/2026/08/0054-staged-promotion-topology-and-logical-ci-gates.md)
and follows the qualification authority in
[ADR 0049](../adr/2026/08/0049-qualification-evidence-authority-verification-boundaries-and-reproducible-gates.md)
and the
[qualification evidence contract](qualification-evidence-contract.md). It does
not supersede those authorities, change a workflow, or grant a remote action.

The hosted-CI availability state is independent of Agent-Central execution or
model-routing modes. In particular, `EXHAUSTED` is not an Agent-Central mode,
and an Agent-Central mode says nothing about GitHub Actions capacity.

## Hosted-CI Availability State

The hosted-CI availability state is closed:

| State | Meaning |
| --- | --- |
| `AVAILABLE` | Hosted attempts may be requested under the normal trigger and approval policy. |
| `CONSERVE` | Capacity remains, but agents batch publication and spend a hosted attempt only when its result will change a decision. |
| `EXHAUSTED` | The operator or account authority says no further GitHub-hosted execution is available under the current quota or budget. |
| `UNKNOWN` | Observed runs did not execute, but the cause has not been authoritatively attributed. |

The human operator, account owner, or future JACA policy owner sets and clears
the state. An agent may report observations and recommend a state, but it must
not silently change or clear one. `UNKNOWN` uses conservative trigger behavior
until disposition and must not be relabeled `EXHAUSTED` without corroborating
operator or account evidence. `AVAILABLE` is not permission to waste runs.

The state applies only to GitHub-hosted Actions. It does not block proportional
local tests, local development, authorized local commits, or Agent-Central
provider routing.

## Authority Boundary

GitHub Actions payment, budget, spending, and quota authority belongs to the
operator or account owner and, when implemented, to the designated JACA policy
owner. An agent has standing authority only to:

- read this and adjacent repository policy;
- inspect repository and workflow status read-only within the task scope;
- perform proportional local verification; and
- create a local commit when the current task or manager authorizes it.

An agent has no standing authority to:

- change a payment method, budget, spending limit, quota, or billing setting;
- make a private repository public to obtain free hosted minutes;
- enable, add, or replace a self-hosted runner;
- disable or weaken workflows, gates, tests, thresholds, timeouts, or security
  checks;
- change triggers or paths to evade required evidence;
- push a branch or tag;
- open, close, reopen, update, or mark a pull request ready;
- dispatch, rerun, or cancel a workflow or job; or
- merge, promote, or otherwise move `staging` or `main`.

Every remote mutation above requires explicit current authorization even in
`AVAILABLE`. A capacity state describes admission posture; it never grants Git,
GitHub, billing, or promotion authority.

## Current Trigger And Cost Map

RepoMap has five hosted lanes across three cost tiers:

| Candidate event | Lane | Trigger and work |
| --- | --- | --- |
| Pull request to `staging` | `repomap-static-analysis` | Automatic for matching paths, including `docs/**` and `AGENTS.md`; runs the sequential PR Fast static aggregate. |
| Pull request to `staging` | `repomap-unit-tests` | Automatic for matching source, test, tool, package-policy, and workflow paths; docs-only changes do not trigger it; runs the canonical unit population at 85% statement and 85% branch coverage. |
| Logically approved feature/fix | `repomap-staging-gate` | Explicit `workflow_dispatch` for one exact approved base/head pair; runs smoke then integration at the independent 80/80 integration gate and does not rerun unit. |
| Pull request to `main` | `repomap-main-source-policy` | Cheap automatic source-topology check; accepts only same-repository `staging` as the source. |
| Logically approved `staging` to `main` candidate | `repomap-main-system-gate` | Explicit `workflow_dispatch` for one exact approved pair; runs assembled-product system qualification. |

A change confined to `.github/pull_request_template.md` matches neither PR
Fast lane's path filter and therefore receives no automatic hosted feedback.
This does not grant publication authority or change the evidence required for
other matching paths in the candidate.

The automatic pull-request event types are `opened`, `reopened`,
`ready_for_review`, and `synchronize`. `pull_request:synchronize` is the
push-to-open-PR feedback event. A push to a branch with no open matching pull
request does not currently invoke the two PR Fast workflows, but the push is
still a remote publication and still requires explicit authorization. A push
to `main` triggers no hosted workflow.

The static and unit workflows use per-workflow/ref concurrency with
`cancel-in-progress: true`. This contains superseded work; it does not make
time already executed free and is not permission to push repeatedly. The
staging and main-system gates do not cancel an authorization run in progress.

The workflow job timeouts are conservative hosted qualification envelopes:
static analysis retains 25 minutes, PR Fast unit has 60 minutes, Staging Gate
has 180 minutes, and Main System Gate has 90 minutes. They are not expected
runtimes. GitHub-hosted runners are materially slower and more variable than
the operator laptop. Main System Gate's inner `--system-timeout 3600` semantic
deadline leaves 30 minutes for checkout, tool installation, image/build setup,
cleanup, evidence generation, and hosted variance. Product-operation, worker,
heartbeat, deadlock, cancellation, subprocess, database, individual-test, and
ordinary local default deadlines remain independently owned and must not be
expanded to consume the outer envelope. Record actual hosted durations and
tighten outer envelopes only from evidence; do not add retries that conceal a
deterministic failure.

Workflow files currently expose manual dispatch on the automatic lanes for
operator use, but agents must never manually duplicate an automatically
triggered PR Fast run. Read-only inspection of a bounded set of runs does not
authorize a rerun, cancellation, dispatch, or other mutation.

## Scoped Local Testing And Pipeline Ownership

Ordinary agents use exact scoped unit selectors and changed-file static checks
for local phase verification. A local integration selector is an optional,
current-prompt-owned diagnostic, not an ordinary phase-closing requirement.
Every such selector is automatically dispatched into the host-disposable
RepoMap sandbox and retains the containerized Postgres harness. Scoped commands
use `--no-coverage`; they make no whole-population coverage claim and do not
weaken a threshold.

Complete local unit, integration, staging, or system execution requires an
explicit current prompt-owned override naming the suites, reason, exact
candidate boundary, and maximum executions. Agents and reviewers may identify
missing exact owners or request an override but cannot grant one. Generic
caution, a failed scoped run, or hosted exhaustion supplies no authority.

The pipeline owns routine complete-population qualification: the complete unit
population runs in the PR Fast `repomap-unit-tests` lane; an approved feature/fix runs smoke then
the complete integration population in `repomap-staging-gate`; and an approved
`staging`-to-`main` candidate runs the assembled-product scenario in
`repomap-main-system-gate`. Local scoped success leaves those hosted gates
pending and must not be presented as their substitute.

Hosted unavailability, including `EXHAUSTED`, does not transfer complete
integration qualification to a laptop. A product implementation may be
retained and subsequent local product development may continue with the
Staging Gate recorded as pending, unless an operator prompt identifies a
narrower mechanical blocker. This conservation rule preserves the promotion
topology and exact SHA/tree-bound gate evidence rather than turning Actions
into a Git broker or the laptop into a replacement gate.

## Standing Conservation Policy

The following rules apply in every state, including `AVAILABLE`:

- Use proportional local verification during development.
- Create useful authorized local checkpoint commits instead of withholding all
  progress until hosted CI is available.
- Batch reviewed local commits before remote publication.
- Do not open a pull request merely to use CI as the development loop.
- Do not push every intermediate checkpoint to an open pull request.
- Publish only when hosted feedback is decision-relevant and the candidate is
  ready for that tier.
- Never manually duplicate an automatically triggered PR Fast run.
- Dispatch the staging gate only after logical approval of one exact
  review-ready feature/fix candidate.
- Dispatch the main-system gate only after logical approval of one exact
  `staging`-to-`main` candidate.
- Do not rerun a failure until its category is understood and the rerun can add
  information.
- Do not rerun a superseded SHA.
- Treat read-only run inspection as bounded observation, never mutation
  authority.

Conservation changes when work runs, not what a named gate proves. Never reduce
tests, coverage thresholds, timeouts, safety checks, or security checks merely
to spend fewer hosted minutes.

### `AVAILABLE`

Under `AVAILABLE`, hosted work may be requested only through its normal trigger
and approval policy and only with current authority for the remote action. The
standing conservation rules still apply. Capacity availability does not make
an intermediate candidate review-ready or a gate decision-relevant.

### `CONSERVE`

Under `CONSERVE`, agents additionally:

- prefer one final branch publication after local review;
- accumulate accepted local commits when safe;
- delay non-decision-critical hosted feedback;
- use exactly one staging or main-system attempt for an unchanged approved
  candidate unless the operator separately authorizes a replacement; and
- never use a workflow as a quota probe.

### `EXHAUSTED`

Under `EXHAUSTED`, agents must not:

- push any branch, whether or not it has an open matching pull request;
- open, reopen, update, or mark a matching pull request ready;
- invoke `workflow_dispatch`;
- rerun a workflow or job;
- create an empty or no-op commit to provoke CI;
- toggle paths or workflow files to provoke CI;
- repeatedly poll or retry in the hope that quota returned;
- weaken or bypass a gate; or
- substitute local evidence for hosted qualification.

Agents may continue local development, run proportional local verification,
create manager-approved local checkpoint commits, prepare a complete
review-ready branch, record the exact pending hosted gates, and perform bounded
read-only status inspection.

Required promotion evidence remains pending:

- feature/fix to `staging` remains pending when required PR Fast or staging
  evidence is unavailable;
- `staging` to `main` remains pending when main-source or main-system evidence
  is unavailable;
- local success never silently becomes hosted success; and
- only an explicit candidate-bound operator exception outside this standing
  policy may override a pending hosted boundary.

### `UNKNOWN`

Under `UNKNOWN`, use the same conservative trigger behavior as `EXHAUSTED`
until the operator or account authority disposes the cause. Preserve the cause
as unknown: do not claim a quota, payment, runner, workflow, or candidate defect
without supporting evidence.

## Hosted Result Classification

Use this closed project vocabulary in phase closeouts, pull requests, and
handoffs:

| Classification | Meaning |
| --- | --- |
| `NOT_REQUESTED_CONSERVATION` | No hosted attempt was made by policy. |
| `NOT_EXECUTED_CAPACITY_EXHAUSTED` | An attempt exists, repository workload did not execute, and operator/account authority corroborates exhausted quota or budget. |
| `NOT_EXECUTED_CAUSE_UNKNOWN` | An attempt exists, repository workload did not execute, and no authoritative cause is available. |
| `EXECUTED_PASS` | The named workload executed and passed for the exact recorded candidate. |
| `EXECUTED_FAIL` | The named workload executed and failed; preserve the failing step and evidence category. |
| `CANCELED_SUPERSEDED` | A newer revision or explicit cancellation made the attempt non-current. |

The GitHub UI or API conclusion is an observation, not the RepoMap
classification. A workflow displayed as `failure` whose sole job reports all
of the following did not execute repository workload:

```text
steps: []
runner_id: 0
no runner name
only a few seconds of lifetime
```

With a corroborating operator-declared exhausted state, classify that attempt
`NOT_EXECUTED_CAPACITY_EXHAUSTED`. Without that corroboration, classify it
`NOT_EXECUTED_CAUSE_UNKNOWN`. Never say "tests failed" when no test step ran.

When available, retain:

- workflow name, run ID, and run attempt;
- event, head branch, and head SHA;
- created, started, and completed timestamps;
- job count;
- runner identity;
- step count and step names;
- GitHub conclusion;
- operator/account capacity observation and timestamp;
- whether repository code executed; and
- whether the run is current or superseded.

## Qualification And Promotion Evidence

Capacity admission is separate from candidate execution. A no-step attempt
supports neither pass nor fail of repository workload, and local evidence
cannot replace a required hosted claim. Preserve candidate and attempt identity
even when workload never starts. A later executed attempt does not erase the
earlier admission record.

Accept a positive hosted result only when the named workload executed and the
green evidence is bound to the current exact SHA or tree under the applicable
gate contract. A red executed result remains candidate evidence until
understood and dispositioned. A no-execution result is admission evidence, not
a candidate defect.

For staging requests adopting PR26-STAGING-CONTRACT1, the
[ADR0067 amendment](../adr/2026/09/0067-runner-owned-portable-child-measurement.md)
requires both ordinary measured M and predeclared abrupt behavior A, with exact
pre-execution population reconciliation. M alone provides verified same-run
80/80 coverage over the complete product denominator. A's abrupt measurement is
unavailable/incomplete; its behavior and cleanup must still pass. This changes
whole-population measurement completeness and cannot relabel an older attempt.
Follow the [same-attempt report acceptance procedure](staging-obligations-acceptance.md)
in addition to trusted candidate/parent verification. An old step-derived
gate-result success alone is insufficient; missing reports fail acceptance.
This policy grants no next attempt, trusted deployment, rerun or promotion.

## Recovery After Capacity Returns

Only the operator or future JACA policy owner clears `EXHAUSTED` or `UNKNOWN`.
After it is cleared:

1. Identify the latest exact review-ready local candidate.
2. Keep accumulated local commits; exhaustion alone is no reason to discard
   them.
3. If the branch advanced locally, publish the final accumulated head once.
4. Do not rerun no-execution attempts for superseded SHAs.
5. Let the automatic PR Fast event run instead of manually duplicating it.
6. For an old automatic PR Fast no-execution attempt, rerun only the latest
   unsuperseded attempt, only with explicit current authorization, and only
   when all exact candidate binders still hold:
   - it belongs to the same open pull request with the expected base/head
     branch shape;
   - the current `refs/pull/<N>/merge` SHA equals the original run's
     `GITHUB_SHA`;
   - that merge commit's parents prove the current base and head SHAs;
   - the original `GITHUB_REF` is the same PR merge ref; and
   - the workflow remains intended for the candidate and changed-path set.
   If any binder changed or is unavailable, do not rerun the old attempt. Use
   one authorized current-candidate trigger without an empty commit or
   pull-request-state churn.
7. Obtain a fresh logical staging or main-system request whenever the approved
   base or head identity changed.
8. Dispatch each expensive gate once for the exact approved pair.
9. Accept only green evidence bound to the current exact SHA or tree.
10. Retain older capacity failures as historical admission evidence, not
    candidate defects.

Do not replay every failed, canceled, or superseded attempt from the exhausted
interval. Capacity restoration requires a fresh trigger or an explicitly
authorized rerun of the declared current attempt; it does not retroactively
execute an old admission failure.

## Current Docs-Only Example

For a docs-only policy phase on `docs/ci-agent-policy` while the operator has
declared `EXHAUSTED`:

- develop and review locally;
- create one authorized local commit;
- do not push or open the pull request while `EXHAUSTED`;
- once the operator declares `AVAILABLE`, publish the final branch once and
  open one pull request to `staging`;
- allow the current path filters to trigger static analysis but not the unit
  lane; and
- do not dispatch staging until the exact docs candidate is logically approved
  and staging qualification is actually required.

This is an illustrative state application, not a permanent assertion that the
account or repository is exhausted.

## External GitHub Behavior

GitHub documentation is a changing external source, not RepoMap policy. As of
this policy's verification on 2026-08-29:

- for private repositories, GitHub-hosted minutes are charged to the repository
  owner's account, and included minutes reset at the start of each billing
  cycle;
- use can be blocked after included quota is exhausted when no valid payment
  method is available, and metered-product budgets can be configured to stop
  use at their threshold;
- concurrency can contain outdated work, but time already executed remains
  usage; and
- GitHub exposes billable execution time for jobs that actually ran on hosted
  runners in private repositories.

See GitHub's current documentation for
[Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions),
[budgets and alerts](https://docs.github.com/en/billing/concepts/budgets-and-alerts),
[concurrency](https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency),
and [job execution time](https://docs.github.com/en/actions/how-tos/monitor-workflows/view-job-execution-time).
Do not infer a plan-specific monthly allowance or a precise billing cause for a
no-step run without account-authoritative evidence.

## Operator-To-JACA Transition

The current human operator owns state changes, remote Git/GitHub authorization,
logical gate approval, and promotion decisions. Future JACA enforcement may
assume those duties only through a separately implemented, reviewed policy
owner that preserves the same state vocabulary, explicit remote authority,
candidate-bound gate requests, result classifications, and evidence boundaries.

Until that transition is implemented, documented, and authorized, references
to JACA are future ownership statements, not an agent capability or standing
permission.
