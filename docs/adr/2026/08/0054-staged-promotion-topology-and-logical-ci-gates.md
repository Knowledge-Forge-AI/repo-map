# ADR 0054: Staged Promotion Topology And Logical CI Gates

## Status

Accepted, amended by REPOMAP-CI2A-R1, REPOMAP-SYS0, REPOMAP-SYS0-FIX1,
and PR26-STAGING-CONTRACT1. This ADR restructures
when RepoMap's hosted CI work runs and who is allowed to move a branch. The
REPOMAP-CI2A-R1 amendment replaced the retired combined suite with independent
pre-review unit coverage and a post-review smoke-then-integration composition.
The REPOMAP-SYS0 and REPOMAP-SYS0-FIX1 amendments implement and qualify the approved
`staging -> main` promotion assembled-product system gate (`repomap-main-system-gate.yml`)
under the `main-system` gate contract, qualifying the packaged release container with
zero host source mounts against durable coordinator execution, crash recovery, idempotency
fencing, and public MCP readback.
ADR 0053's admission decision is preserved unchanged.

## Date

2026-08-22

## Context

REPOMAP-CI0B established a green hosted exhaustive gate, `repomap-dev-gate`,
triggered on every `pull_request` event and on `push` to `main`. It runs the
complete `tools/run_tests.py --suite all` qualification: Go validation, unit and
integration tests, line and branch coverage, container smoke, and Docker
operation and residue accounting.

That topology has one shape and one cost. Every development push to an open pull
request paid for the whole qualification, including pushes that only reworded a
comment. REPOMAP-CI1 is about to widen Ruff and mypy coverage, and TEST-ISO1 is
about to separate fast pure unit tests from slow infrastructure tests. Both of
those phases add checks. Adding checks to a pipeline whose only tier is "run
everything" makes the cost problem worse, and choosing tiers after the checks
exist means relitigating each one.

A second problem is authority. The gate's usefulness depends on it having
qualified the revision that actually lands. Triggered on `synchronize`, it
qualifies whatever head existed at trigger time; by the time a human merges, the
head or the base may have moved. Nothing binds the tested content to the merged
content.

A third problem is that RepoMap's private-operation policy is intended to be
owned by a future JACA git broker, not by GitHub. Reaching for GitHub branch
protection, rulesets, required reviews, a merge queue, or CODEOWNERS would put
the policy in the wrong place and would have to be unwound. The repository is
also on a private plan where server-side required-check enforcement is
unavailable, so those mechanisms would not even work today.

## Decision

### 1. Two long-lived logically protected branches

`staging` and `main`. Feature and fix work targets `staging`; `staging` promotes
to `main`.

"Logically protected" is exact: no GitHub branch protection, ruleset, required
GitHub review, merge queue, or CODEOWNERS policy is configured. "Approval" means
a logical approval of one exact pull-request revision and never GitHub's
review-approval feature. Outside-contributor repositories may adopt rulesets
later in a separate phase; that is a different problem with different
adversaries.

### 2. Three cost tiers, currently wired to four lanes

`repomap-static-analysis` becomes the PR Fast lane: Ruff, the production
full-`F` ratchet, the `service_package` mypy seed, and a new stdlib-only CI
topology contract check. It triggers on `opened`, `reopened`,
`ready_for_review`, and `synchronize` for pull requests targeting `staging`, and
on nothing else.

There is deliberately no additional branch `push` trigger.
`pull_request:synchronize` *is* the push-to-open-PR feedback signal; a second
lane would double the cost of every push and prove nothing extra.

After TEST-ISO1 proved unit purity, REPOMAP-CI2A added
`repomap-unit-tests` as a second, independent PR Fast lane. It runs the complete
canonical unit population through `tools/run_tests.py --suite unit` with hard
85% Python statement and 85% branch gates (settled in REPOMAP-CI2A-R4D); static analysis and behavioral feedback
remain separately visible and cancellable. The lane watches `src/main/go/**`,
because the canonical unit runner validates and builds the existing Go helper,
and bootstraps verified `golangci-lint` v2.6.2. It uses no Docker, Postgres,
integration, smoke, or sandbox resource.

REPOMAP-CI2A-R1 supersedes the earlier CI2A/CI2B roadmap split on this branch.
The stable `repomap-static-analysis` job runs the selected local deterministic
pre-review stack sequentially in one runner and reports one aggregate result
only after every check ran. The post-review `repomap-staging-gate` invokes
`tools/run_tests.py --suite staging --sandbox` exactly once. The project-owned
composition runs bounded lifecycle smoke first; a smoke failure refuses
integration. The current ADR0067 amendment requires ordinary measured M and
separately accounted intentional abrupt behavior A. Integration M independently
owns hard 80% statement and branch gates over the complete product denominator.
Unit is not rerun and no combined unit-plus-integration coverage owner remains.

`repomap-dev-gate` is renamed `repomap-staging-gate` and converted from event
triggering to explicit logical-gate invocation. The rename is not cosmetic: the
workflow's meaning changed from "runs on every pull request" to "runs only on an
approved logical gate request", and the old name would now misdescribe it.

`repomap-main-source-policy` is added for pull requests targeting `main`.

### 3. GitHub Actions is an evidence executor, never a git broker

No workflow merges, updates a ref, enables auto-merge, or closes a pull request.
The staging gate holds `contents: read` and `pull-requests: read`; no workflow
holds any write permission. The roles are:

```text
JACA                = intended git-operation/policy broker
GitHub Actions      = qualification/evidence executor
GitHub pull request = collaboration/change object
logical gate request = operator/JACA approval of an exact revision
```

Until JACA owns merging, the human operator is the temporary broker.

### 4. The `repomap-ci-gate-request-v1` contract

A project-owned versioned contract, implemented in `tools/ci/gate_contract.py`,
binding `gate_kind`, `pr_number`, `base_branch`, `base_sha`, `head_branch`,
`head_sha`, and `approval_id`. Its semantics: *qualify exactly this head against
exactly this base for exactly this gate.*

`approval_id` is an opaque correlation value. It deliberately models no GitHub
reviewer identity, because reviewer identity is GitHub's concept and this
contract must survive GitHub not being in the picture.

A head or base change invalidates the request. The newer revision is never
silently qualified under the older approval.

`workflow_dispatch` is transport, not semantics. Its inputs are `pr_number`,
`approved_base_sha`, `approved_head_sha`, and `approval_id`; the workflow name
fixes `gate_kind=staging`. JACA can construct and dispatch the identical logical
request later without the contract changing.

For the current GitHub transport, the trusted execution context supplies base
freshness authority. The broker/operator must select `refs/heads/staging` as the
dispatch ref, and the contract requires both that exact `github.ref` and that
`github.sha` equals `approved_base_sha`. GitHub already supplies the immutable
workflow revision that instantiated the run, so the gate performs no later
moving-ref lookup. Dispatching the workflow from another ref fails closed even
when every explicit input is otherwise valid.

The REST pull-request object supplies descriptive state only: number,
open/closed state, draft state, base and head branch names, and head-repository
identity. Its `base.sha`, `head.sha`, and `merge_commit_sha` fields are not
revision-freshness authority and cannot override the trusted executor or commit
parent evidence.

### 5. Merge-candidate binding, proved from commit parents

The gate qualifies `refs/pull/<N>/merge` — the pull request merged into its
current base — not the bare feature head, so the suite tests what would actually
land.

Before any expensive step it validates the trusted executor ref/SHA binding and
that the pull request is open and not a draft, the head is from this repository,
and the base branch is the gate's required base. The merge-ref checkout then
fails closed if no candidate exists. The gate records `tested_candidate_sha`
and `tested_candidate_tree` and proves the exact tested relation from the merge
commit's own parents (`HEAD^1` is the approved base, `HEAD^2` is the approved
head). A base or head move after dispatch therefore fails candidate verification
rather than silently qualifying a recomputed candidate.

Authorization semantics come from the trusted staging executor revision. The
workflow checks out `github.sha`, preserves its stdlib-only
`tools/ci/gate_contract.py` in runner-owned temporary storage, and uses that
same preserved copy for request resolution, candidate verification, and result
recording after the candidate checkout. Candidate tests still execute candidate
code; this preservation guarantees authorization integrity through candidate
verification, while result recording remains subject to the runner's shared
execution context and is not treated as a hardened sandbox for hostile code.

The result artifact `repomap-ci-gate-result-v1` records the approved base/head,
the tested candidate SHA and tree, the candidate parents, the conclusion, and
`merge_authorized`. `merge_authorized` is true only when that exact recorded
candidate passed. The schema is closed — unpublished fields are rejected — so no
secret, source payload, database content, or host-private path can ride along.

A future JACA broker may synthesize the final merge commit, but must be able to
prove it preserves the tested candidate tree and the approved base/head
relation.

### 6. Main-source policy as a cheap advisory check

Pull requests targeting `main` pass only when the base is `main`, the head
repository is this repository, and the head branch is `staging`. Any other
source fails immediately and performs no expensive work. It does not close or
mutate the pull request.

This check is explicitly **not** the security boundary and must not be described
as one. It is a cheap, early, honest signal. JACA will enforce the same policy
authoritatively by refusing to move `main`.

### 7. Structural contract checks, not grep

The topology contracts parse the repository's own workflow YAML. PyYAML is not a
declared dependency and the PR Fast lane installs only the `static-analysis`
extra, so `tools/ci/workflow_model.py` implements the exact restricted subset
the repository's workflows use and raises on every construct outside it. A
reader that silently mis-parses would be weaker than the grep it replaces;
failing closed is what makes it stronger.

### 8. The main milestone gate is an assembled-product system gate

The logical `staging -> main` approval gate is implemented in REPOMAP-SYS0 via
`.github/workflows/repomap-main-system-gate.yml` and the `main-system` gate contract.
It executes `tools/run_tests.py --suite system --system-timeout 1500 --hygiene-profile exhaustive --declared-complete-gates 1`
in the nested container sandbox, building the candidate release image and exercising
the full 5-phase packaged lifecycle with zero host source mounts. Later release/system/SBOM/expensive
milestone checks remain documented as future roadmap intent. No gate merely echoes success.

## Consequences

**Ordinary development pushes receive bounded pre-review feedback.** A
code-affecting push to an open `staging` pull request runs independent static
analysis and canonical unit checks. The unit lane provisions the pinned Python
and Go toolchains; static analysis bootstraps only its closed pinned tool
manifest. Neither PR Fast lane pulls integration images or starts Docker or
Postgres resources. Unit coverage is intentionally owned by the unit lane.

**Exhaustive qualification becomes deliberate.** It runs when someone approves an
exact revision. This is a real behavioral change: a pull request can now sit
green-on-fast-checks without ever having been exhaustively qualified. That is
intended — qualification is now an act, not a side effect — but it means merge
discipline must actually consult the gate result rather than the check list.

**A push to `main` now runs no hosted check.** REPOMAP-CI0B's handoff activation
was defined as a green push-to-`main` run of the old combined-trigger gate. This
ADR replaces that mechanism rather than satisfying it, and the `push` trigger is
gone everywhere. This is accepted, not overlooked. The compensating control is
structural: the only supported way to move `main` is a `staging -> main`
promotion, and the exact tree being promoted was already qualified by a green
staging gate against that same content. Re-running the identical suite on the
identical tree would produce evidence, not information. Until the main milestone
gate exists, `staging -> main` is governed by the main-source policy plus
operator merge discipline.

**Approval/dispatch races surface as red gates.** GitHub may recompute
`refs/pull/<N>/merge` between approval and dispatch. The parent proof detects
this as drift and fails. A race therefore costs a re-approval, not a silent
mis-qualification. That trade is deliberate.

**A hand-written YAML reader is now a maintained surface.** It is small,
fail-closed, and self-tested against every real workflow, but it is code that
did not exist before. The alternative was declaring PyYAML, which
`dependency-standards.md` forbids without explicit phase allowance.

**A docs-only pull request to `staging` still runs no checks.** The PR Fast lane
keeps its pre-existing `paths` filter. This ADR does not change that behavior; it
is recorded here so it is an owned decision rather than an accident.

**The runner is replaceable.** Workflow YAML stays thin and semantics stay in
project-owned commands, so `ubuntu-latest` can later become a JACA-provisioned
ephemeral Tart Linux ARM64 VM running an ephemeral Actions runner and the same
gate command. No self-hosted or Tart labels are configured yet.

## Non-goals

The original ADR did not expand Ruff or mypy or add scanners; the
REPOMAP-CI2A-R1 amendment explicitly supersedes that part of the original
non-goal. It still does not reclassify any unit test, build SYS0, configure
self-hosted or Tart runners, implement JACA, configure GitHub rulesets or
protection, or enable GitHub auto-merge. `src/main/python/repomap_kg/**` remains
untouched: this is CI
topology, not product behavior.

## Bootstrap

This phase bootstraps once. The operator creates `staging` at the current `main`;
the implementing branch targets `staging`; the legacy hosted gate may run one
final expensive pull-request check, which is accepted rather than bypassed. After
the change merges into `staging`, a `staging -> main` pull request is opened, the
new main-source policy accepts it, and the promotion is made once on that
evidence. Once the change is on the default `main`, future staging gates use the
logical approval workflow. A `workflow_dispatch` workflow is not required to
bootstrap itself before it exists on the default branch.

The executable one-time bootstrap exception procedure is:
1. An operator exception lands only the trusted executor bootstrap closure on
   `main`, so the workflow and stdlib-only verifier exist on the trusted base.
2. The exception record states explicitly that the bootstrap commit was not
   pre-qualified by `REPOMAP-SYS0` and authorizes no later candidate.
3. Open or refresh the ordinary `staging`-to-`main` promotion pull request.
4. Run the now-existing workflow against that exact open pull request, base,
   head, merge candidate, and tree.
5. Merge only the exact candidate whose trusted result says
   `merge_authorized=true`; there is no post-merge authorization substitute.

## PR26-STAGING-CONTRACT1 Amendment — staging evidence consumption

### Amendment Status

Accepted policy amendment following operator approval of the two staging
decisions, 2026-09-12. Implementation qualification and trusted consumer activation
remain separate boundaries. This amendment changes no workflow or deployment.

### Statements Superseded By This Amendment

The prior single integration measurement claim is replaced by the two required
obligations in [ADR0067](../09/0067-runner-owned-portable-child-measurement.md).
Whole-population behavior must pass, while M alone provides complete verified
measurement at 80/80; A records required abrupt behavior with unavailable child
measurement. Unit 85/85 and the promotion topology remain unchanged.

For a later request adopting this policy, a staging step success and the existing
gate result's `merge_authorized` field are necessary but insufficient acceptance
evidence. The manager also validates the same-attempt structured obligations
report, exact population reconciliation, both legs, M coverage and cleanup. The
trusted command already delegates execution to the candidate runner, but the
old gate-result schema does not bind the new policy/report. The separate
[consumer handoff](../../../contrib/staging-obligations-acceptance.md) identifies
the unactivated automatic-consumer proposal and artifact custody requirements.
