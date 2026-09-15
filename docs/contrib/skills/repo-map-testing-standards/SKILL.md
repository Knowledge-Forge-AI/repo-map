---
name: repo-map-testing-standards
description: Use when selecting, running, documenting, or reviewing RepoMap scoped unit and integration tests, complete-suite requests, breadth disputes, smoke, compileall, docs-only, diff, or qualification verification.
---

# RepoMap Testing Standards

## Suite Selection

Use `tools/run_tests.py`. A no-selector unit or integration invocation is a
complete-population command for the hosted pipeline or a current prompt-owned
override. Ordinary phases forward exact scoped selectors after `--` with
`--no-coverage`:

- `--suite unit` for pure source-level behavior, directly without Docker.
- `--suite int --pg-container-port 55433` for integration-only storage/runtime
  behavior. This is an explicit local diagnostic: the runner automatically
  dispatches it into the authenticated host-disposable sandbox, and direct host
  execution is unavailable.
- `--suite smoke` for manager-backed pass/fail containerized runtime sanity.
- `--suite staging --hygiene-profile heavy --declared-complete-gates 1
  --pg-container-port 55433` for an explicitly requested local complete gate.
- `--suite system --system-timeout 1500 --hygiene-profile heavy
  --declared-complete-gates 0 --sandbox` for the candidate assembled-product promotion gate.

`--suite staging` runs substantial smoke first; smoke failure refuses integration.
Integration then requires both measured M and predeclared abrupt behavior A under
the ADR0067 PR26-STAGING-CONTRACT1 amendment. Unit is not recomputed, and no combined unit-plus-integration
coverage owner remains. Unit independently owns hard 85/85 statement/branch
coverage (settled in REPOMAP-CI2A-R4D); integration independently owns hard 80/80. Integration and staging
suites use the containerized Postgres
harness with `--pg-container-port 55433`; do not fall back to host IPC or a
developer's live database.

The mandatory monolithic privileged DinD backend contains pytest and its owned
inner daemon. It mounts host source read-only at `/workspace-ro`, projects a
run-owned tmpfs-backed overlay at `/workspace`, keeps nested bind paths
identical, and never mounts the host Docker socket or writable host state.
Inner `/var/lib/docker` is a 4 GiB tmpfs. Exact outer removal and before/after
host identity readback apply on success, failure, interruption, and setup
exceptions; never prune unattributed host resources. Privileged DinD is a
pollution boundary, not a hostile-code security boundary. A future disposable
Tart VM may substitute its VM-owned daemon without changing the `int` suite.
The runner selects this backend automatically; hosted `--sandbox` remains a
redundant assertion. It pulls Postgres and
Alpine prerequisites into the inner daemon before the inner canonical Docker
baseline and exports a fixed, bounded, path-safe report tree from the stopped
container before exact outer removal. Direct integration pytest collection
outside the authenticated marker/token, inner-Docker, and absent-host-socket
boundary fails before fixtures execute.

Forward exact scoped integration selectors after `--`; file, class, test, and
quoted parameterized node IDs remain unchanged. Selections outside the
integration root fail closed. Canonical unit items activate the bounded live
Postgres purity guard while preserving injected doubles and harmless subprocess
tests.

Direct-SIGINT test control must wait for the child-originated post-ACK blocker
readiness byte before sending exactly one signal. Preserve strict lifecycle
validation, rollback assertions, and the no-skip/no-xfail boundary. Hosted
adoption additionally recovers sandbox test diagnostics upon completion and
preserves staging smoke-then-integration behavior.

Smoke asks the repository-owned `TestImageManager` to ensure a dependency-only
`repomap-test-runtime:*` cache and consumes the exact Engine image ID returned.
The configured base is an exact immutable repository digest. The manager reuses
it locally or pulls only that digest once on a miss under its checkout-scoped
single-flight lock, then verifies RepoDigest, Engine ID, and Docker-server
architecture. Mutable tags, registry resolution, alternative bases, and
fallback digests are prohibited. The cache fingerprint excludes candidate
source, phase, and run identity. The
runner mounts the current checkout read-only at `/workspace`, selects
`/workspace/src/main/python` through `PYTHONPATH`, and uses one exact run-owned
network for the runtime/Postgres probe. Smoke refreshes two bounded fixtures,
performs product readback, proves backup-first destruction and dump structure,
and cleans every run-owned resource within one 540-second monotonic budget.

An explicit exact-ID override remains diagnostic-only and grants no cleanup or
deployment ownership. Obtain such an ID with:

```sh
docker image inspect --format '{{.Id}}' <locally-prepared-image>
```

The accepted value is the image configuration ID, not a repository or
multi-architecture manifest digest. Docker is the only qualified smoke runtime;
Podman compatibility is deferred.

Ordinary canonical `unit`, `int`, and `staging` do not execute real builds. The
runner validates and deselects the exact `requires_build_profile` debt registry
in `repomap_test_support.build_profile_debt`, reports its count, and refuses a
forwarded marker override. Direct execution of a deferred node requires
separately implemented build-profile authority; ambient environment cannot
authorize it, and skip or xfail is never a substitute.

For container-capable canonical work, preserve the run-wide entry snapshot of
Docker image and volume IDs. Postgres routes use `--pull=never`, tmpfs for the
image-declared data path, current-run labels, exact returned-ID ledgering, and
exact cleanup without `--rm` or volume deletion. Any new unattributed or
current-run residual image/volume fails closed without deletion.

Container-capable canonical runs report closed build/pull classes:
product or build-profile builds, managed test-runtime builds, managed external
base pulls, unmanaged builds, and unmanaged pulls. Product/build-profile and
unmanaged counts must be zero; each managed count may be zero or one. A newly
pulled exact Python base is reported separately from RepoMap runtime caches and
never consumes one of the two runtime-cache retention slots.

Those zero-unmanaged requirements are canonical-run requirements. In an
isolated refusal proof, `unmanaged_build_count=1` and `unmanaged_pull_count=1`
are the intended refusal evidence and must never be suppressed or reported as
failures. See `docs/testing/managed-docker-mediation-boundary.md`.

Managed runtime materialization uses one ledgered temporary container and one
final commit, not the Docker image builder. Require zero runtime-build
intermediate residue and zero new unattributed images; temporary-container
cleanup failure is terminal and never authorizes prune or force image removal.

## Scoped Phase Decision Sequence

For source, test, schema, package metadata, runner, or behavior-affecting
fixture changes, apply this sequence:

1. Classify the changed production, test, tool, schema, fixture, process,
   runtime, database, or container boundary and name its test owners.
2. Select the narrowest exact unit paths or node IDs that cover the changed
   behavior.
3. Select exact integration paths or node IDs only when the current prompt
   owns that optional diagnostic. A crossed integration, storage, process,
   runtime, database, or container boundary identifies pending hosted evidence;
   it does not make local integration an ordinary closeout requirement.
4. Add adjacent owners or a justified subdirectory only when a shared contract
   makes them affected. Do not invent automatic Git-diff-to-test mapping.
5. Check the current prompt for a complete-suite override naming suites,
   reason, candidate boundary, and maximum executions. No such block means no
   complete-suite authority.
6. Run exact scoped commands with `--no-coverage`, then applicable changed-file
   Ruff, compileall, mypy, docs/link, and diff checks.
7. Record exact selectors, results, and each unselected suite with its scope
   reason.
8. If only complete-population evidence can resolve the risk, request a prompt
   or manager override instead of self-escalating.

Canonical scoped forms are:

```sh
python3 tools/run_tests.py --suite unit --no-coverage -- \
  src/test/unit/python/<owner>.unit.test.py::test_exact_contract
python3 tools/run_tests.py --suite int --no-coverage \
  --pg-container-port 55433 -- \
  src/test/int/python/<owner>.int.test.py::test_exact_boundary
```

Multiple exact selectors remain ordered after `--`. A pathless `-k` may be
used for exploration but is not preferred final evidence; pair any retained
`-k` with an exact path and `--no-coverage`. Scoped runs make no
whole-population coverage claim, and `--threshold` must not be used to make a
partial population pass.

Do not routinely run complete unit, complete integration, smoke, staging,
system, or the retired combined suite. A generic request to be thorough, a
failed scoped run, or reviewer caution is not an override. Reviewers challenge
owner adequacy first and may recommend, but cannot grant, complete-suite
authority. Hosted exhaustion does not broaden local authority.

When a prompt grants a complete-suite override, record its authority, suites,
candidate boundary, maximum executions, and actual count. Do not exceed that
count. A local complete integration or staging execution remains diagnostic
and cannot replace the logically approved hosted Staging Gate. The hosted
pipeline retains routine ownership of the complete unit
population, approved smoke-then-complete-integration gate, and approved
assembled-product system gate.

Before any hosted trigger or remote write, follow the detailed
[hosted-CI stewardship policy](../../ci-agent-policy.md):

- obtain the current `AVAILABLE`, `CONSERVE`, `EXHAUSTED`, or `UNKNOWN` state
  from the operator or future JACA policy owner; do not infer or clear it;
- inspect the trigger map, batch review-ready local work, and publish only when
  hosted feedback is decision-relevant;
- never duplicate an automatic PR Fast run or perform an unapproved dispatch,
  rerun, cancellation, push, or pull-request mutation;
- under `EXHAUSTED` or `UNKNOWN`, keep work and proportional verification local
  and record every pending hosted gate;
- classify hosted attempts with the policy's closed vocabulary, distinguishing
  no-execution admission evidence from executed workload; and
- after capacity returns, recover only the latest exact review-ready candidate,
  without replaying superseded attempts.

RepoMap operates five hosted CI lanes across three cost tiers:
- `repomap-static-analysis` (PR Fast): one sequential aggregate that runs Ruff,
  Pyflakes, mypy, retained-Python ratchets, file-length, compileall, actionlint, zizmor, pip-audit,
  govulncheck, Semgrep, Betterleaks, MalSkanner, Prompt Defense Audit,
  suppression visibility, offline Liquibase validation, Hadolint, and
  generated-output drift before one final result. Its global Ruff
  `E9`/`F821`/`F822`/`F823` correctness seed, one cumulative full-`F` production
  ratchet over `src/main/python/repomap_kg/runtime`,
  `src/main/python/repomap_kg/graph`, and
  `src/main/python/repomap_kg/server`, and an ownership-manifest-derived mypy
  boundary over every T0 cross-language contract plus the declared T1
  retained-Python seed. The separate `retained-python-ratchets` aggregate
  check derives all T0, T1-seed, and T1-future retained modules from that same
  manifest. It ratchets full Ruff `F`, T1-future mypy findings and direct
  T2/T3 import edges, and retained warning-band file lengths without promoting
  T2/T3 implementation into the blocking set. It audits the unique trusted
  baseline genesis and every reachable Git transition, treats incomplete
  history as a tool failure, forbids baseline reinitialization and debt growth,
  and requires exact append-only authority for retained-scope removal or
  reclassification. Clean additions remain permitted; maintained Python
  quality protection does not await hypothetical replacement, while
  architectural placement is reserved for post-main. The global file-length
  profile remains separate. The lane retains current-checkout `MYPYPATH`, seals exact runtime
  dependencies into the tool Python, and invokes Semgrep through that Python's
  exact console script. It also runs the stdlib-only `tools/ci/ci_topology.py`
  contract check; it triggers only for pull requests targeting `staging`;
- `repomap-unit-tests` (PR Fast): the complete canonical unit population through
  `python3 tools/run_tests.py --suite unit`, with Python 3.13 and hard 85% statement
  and 85% branch coverage (settled in REPOMAP-CI2A-R4D),
  `.[test,scale-tools,static-analysis]`, and the Go toolchain pinned from `src/main/go/go.mod`
  because the canonical runner validates/builds the existing helper; the lane
  bootstraps exact verified `golangci-lint` v2.6.2; TEST-ISO1 purity guards
  prohibit live Docker and Postgres use, and the lane has no integration,
  smoke, or sandbox access;
- `repomap-staging-gate`: the canonical post-review smoke-then-integration gate
  (80/80 integration coverage and Docker operation accounting), invoked only
  by an explicit `repomap-ci-gate-request-v1` logical
  gate request;
- `repomap-main-system-gate`: the canonical assembled-product main promotion gate
  (REPOMAP-SYS0-FIX1), invoked only by an explicit `main-system` gate request, testing the
  candidate release image with zero source mounts under durable coordinator lifecycle
  and MCP stdio readback;
- `repomap-main-source-policy`: a cheap advisory check that only same-repository
  `staging` may promote to `main`.

The two independent PR Fast checks provide static and unit feedback on every
code-affecting pull-request update. Exhaustive qualification runs only on a
logical approval of one exact base/head pair and
emits SHA-bound `repomap-ci-gate-result-v1` merge-authorization evidence. No
workflow merges, updates a ref, enables auto-merge, or closes a pull request; the
operator (later, JACA) is the git broker.

The complete laptop gate remains available, without weakening its admission or
safety policy, only under a current prompt-owned override for an operator
diagnostic, local qualification campaign, or rare reproduction that genuinely
requires the full local population:

```sh
python3 tools/run_tests.py \
  --suite staging \
  --hygiene-profile heavy \
  --declared-complete-gates 1 \
  --pg-container-port 55433
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

For docs-only patches:

```sh
git diff --check
git diff --cached --check
```

Add local docs link/path checks when the patch moves docs or updates links.
Do not run source tests or compileall for docs-only patches unless
executable behavior changed.

## Qualification Claims

Follow `docs/contrib/qualification-evidence-contract.md` for the complete
ADR 0049 procedure. A positive canonical-suite claim records the exact suite
command, candidate identity, environment and runner identity, suite result, and
whether coverage was enabled. Keep pytest status, runner composed status, line
coverage, branch coverage, threshold, threshold selector or policy, explicit
threshold decision, and measured roots distinct; a bare exit `1` does not prove
which boundary failed.

Canonical suite claims quantify over the suite's whole collected population.
An exact node manifest is not a general requirement; integration/staging now
require a pre-execution exact M/A partition under ADR0067. Fixed-cohort or exact-set claims do
require the ordered manifest and other claim-proportional reproducibility
fields. When a phase will make a qualification claim, declare its attempt
before execution. Development and scoped runs remain useful feedback but cannot
become qualification retroactively.

## Test Placement And Ownership

- Test roots are `src/test/unit/python` and `src/test/int/python`; shared
  helpers live under `src/test/support/python`.
- pytest collects the `*.test.py` filename pattern; project convention is
  more specific: `.unit.test.py` for unit tests and `.int.test.py` for
  integration tests.
- Do not move tests to paths pytest does not discover or rename them to
  patterns `pyproject.toml` does not collect unless the same accepted phase
  updates the test configuration and verifies discovery.
- Standing authorization and boundaries for opportunistic test
  reorganization live in `docs/contrib/test-refactor-authorization.md`.

## Test Hygiene

- Scoped tests are the normal proportional development feedback. They do not
  replace the hosted exhaustive gate and do not become qualification evidence.
- Use public fixtures and temporary state.
- Use mocks/fakes for external commands, container orchestration, and
  network boundaries.
- Keep redaction, non-execution, and private-data boundaries explicit in
  tests.

The human-readable authority, including runner details and platform-specific
evidence commands, remains `docs/contrib/testing-standards.md`.


## Retention enforcement evidence

For retention maintenance, keep candidate census, profile assignment, current
profile results, and suite coverage outcomes separate. Use the aggregate's
`python-retention-inventory --check` owner; census-only validation does not
establish enforcement. Follow the root-specific policy in
`docs/contrib/testing-standards.md`. Report exact eligible-minus-enforced sets
and never treat a failing non-product profile as clean admission.

The aggregate keeps a compact retention summary ahead of capped output and seals
a versioned compact machine projection as a separate hash-bound JSON payload (ADR 0064). The 200,000-byte
log and 5 MiB aggregate caps remain unchanged. Successful finalization reports
remaining byte capacity and warns below 20%. A finalization failure preserves the
individual check statuses in console output, reports evidence as unqualified, and
returns nonzero; retained files alone do not prove a valid evidence envelope.

With coverage and `--report`, the canonical runner retains coverage.py
`coverage.json` beside the suite's `latest/` HTML directory before owned cleanup.
It preserves per-file executed/missing lines and branches over the unchanged
product denominator. A scoped report remains scoped evidence, including any
full-denominator threshold failure; it is not whole-population qualification.

The ADR0067 amendment changes whole-population measurement completeness: both M
and A must execute and pass, but only M supplies verified same-run coverage at
80/80 over the complete product-source denominator. A retains authentic abrupt
launch/checkpoint/termination/cleanup observations with unavailable measurement;
its parent and sibling data are also excluded from M. Ordinary registered
measurement remains strict in either leg. Preserve exact population and role
accounting, skips/deselections as non-passes, teardown failures and failure-safe
report export. Missing/blocked legs and unsafe cleanup fail aggregation. Scoped
and `--no-coverage` runs remain diagnostic. Follow the
[shared report acceptance procedure](../../staging-obligations-acceptance.md).
