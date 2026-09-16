# RepoMap Testing Standards

RepoMap uses behavior-focused tests with explicit coverage gates. Tests should
protect contracts and boundaries, not reward ceremony.

## Suites

Use `tools/run_tests.py` for project test runs. The no-selector unit and
integration forms below are complete-population commands for pipeline-owned
qualification or a current prompt-owned override; ordinary phases use the
scoped forms under [Scoped Phase Verification](#scoped-phase-verification).

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int --pg-container-port 55433
python3 tools/run_tests.py --suite smoke
python3 tools/run_tests.py \
  --suite staging \
  --hygiene-profile heavy \
  --declared-complete-gates 1 \
  --pg-container-port 55433
python3 tools/run_tests.py \
  --suite system \
  --system-timeout 1500 \
  --hygiene-profile heavy \
  --declared-complete-gates 0 \
  --sandbox
```

`--suite unit` covers source-level behavior, runs directly without Docker, and
owns hard 85% statement and 85% branch gates (settled in REPOMAP-CI2A-R4D). `--suite int` covers integration and
storage behavior only and owns hard 80% statement and branch gates. `--suite
smoke` is a pass/fail bounded lifecycle. `--suite staging` runs substantial
smoke first, refusing integration when smoke fails, then both required M/A
integration obligations under the ADR0067 amendment; it never runs unit and does not
combine unit and integration coverage. `--suite system` runs the assembled-product
promotion qualification gate (REPOMAP-SYS0-FIX1) against the candidate release image
with zero host source mounts. The retired `--suite all` is rejected.

Canonical `unit`, `int`, and `staging` never execute real Docker builds. The exact
visible build-required debt is the twelve-node
`DEFERRED_BUILD_PROFILE_NODE_IDS` registry in
`src/test/support/python/repomap_test_support/build_profile_debt.py`. Every
registered node carries `requires_build_profile`; whole-population collection
must agree with that registry in both directions. The runner reports the
deselected count, while direct execution fails closed until a separately
implemented future build-profile authority replaces that refusal. No ambient
environment variable can authorize it. Do not replace this contract with skip, xfail,
source-text grep, or a mutable local selection list.

Canonical smoke asks the repository-owned test-image manager to ensure a
dependency-only runtime cache image and consumes the exact lowercase Docker
Engine image configuration ID it returns. The cache is keyed by recipe, Docker
architecture, exact local base identity, normalized project runtime
dependencies, release inputs, and explicit smoke extras — never candidate
source, phase, or run identity. The manager does not copy or install RepoMap;
the mounted checkout remains source authority.

The configured base image is an exact immutable repository digest with an
optional human-selection tag before `@`. Engine equality strips only that tag,
preserves registry ports and repository paths, and compares canonical
repository plus exact digest. On a local miss, `TestImageManager` pulls only
the canonical repository digest under the same checkout-scoped single-flight lock,
then requires canonical Engine RepoDigest, exact image ID, and closed
`arm64`/`aarch64` or `amd64`/`x86_64` architecture equivalence. Mutable tags,
registry search, alternative bases, and fallback digests cannot authorize acquisition. An
explicit `--smoke-image-reference sha256:<64 lowercase hex>`
override remains available for diagnosis. It grants no cleanup authority and
is not deployment-image ownership. Mutable tags and repository or manifest
digests are not accepted as overrides. Derive an exact diagnostic ID with:

```sh
docker image inspect --format '{{.Id}}' <locally-prepared-image>
```

Smoke mounts the current checkout read-only at `/workspace`, sets
`PYTHONPATH=/workspace/src/main/python`, and uses one exact run-owned network
only for the runtime-to-Postgres probe. It initializes and refreshes two tiny
graphs, verifies product readback, performs backup-first destruction of one
graph database, inspects the run-owned dump, proves the other graph coherent,
and cleans every exact run-owned resource. One monotonic budget covers all work
and bounded cleanup; the configured ceiling is 540 seconds. Docker is the only
qualified smoke runtime; Podman compatibility is deferred.

Container-capable canonical runs snapshot exact Docker image and volume IDs at
the accepted run boundary. At post-pytest and terminal close, any new ID must
already be absent after exact ledger-owned cleanup; a new unattributed ID or a
current-run residual ID fails closed and is never deleted. All entry IDs are
protected baseline. Postgres image-declared data volumes must be prevented with
tmpfs, not created and reclaimed afterward.

Managed runtime-cache images use `repomap-test-runtime:*` plus the full
`org.repomap.test.image.*` label contract. The manager retains at most two
eligible RepoMap cache images, protects the requested image and every
container-referenced image, and removes only positively owned stale IDs with
`noprune` semantics and exact absence readback. A new manager-created cache is
persistent accepted state, reported separately from unattributed images and
current-run ephemeral residue. Deployment `repomap-runtime:*` and legacy
`repomap-runtime-<hash>:latest` images are never test-GC targets.

Runtime cache materialization uses one label-free, exactly ledgered temporary
container, a collision-resistant run-bound name, a checkout-stable private
recovery manifest, and one final `container.commit`. The persistent image must contain
exactly the five durable cache labels; current-run resource-label keys are
forbidden even when empty. Materialization must not invoke the Docker image builder or
leave runtime-build intermediate Engine images or builder state. The runner
reports intermediate created, removed, and residue counts separately. Canonical
success requires zero intermediate residue and zero new unattributed images.

The run-wide boundary reports closed operation classes:
`product_or_build_profile_build_count`,
`managed_test_runtime_image_build_count`,
`managed_runtime_build_intermediate_created_count`,
`managed_runtime_build_intermediate_removed_count`,
`managed_runtime_build_intermediate_residue_count`,
`managed_external_base_pull_count`, `unmanaged_build_count`, and
`unmanaged_pull_count`. Canonical success requires zero product/build-profile
and unmanaged operations, while each managed count is zero or one. A base
pulled through the exact manager path is
`managed_external_test_base_cache`, reported separately from managed RepoMap
runtime caches, and is never removed by test GC or charged to the two-cache
runtime retention bound.

Those zero-unmanaged requirements describe a **canonical run**. An isolated
refusal proof is the opposite context: there, `unmanaged_build_count=1` and
`unmanaged_pull_count=1` are the intended evidence that mediation observed and
refused an unmanaged operation. Never suppress, refilter, or reinterpret those
isolated counts as failures. The enforced mediation surface, its honest scope
limits, and the preserved evidence semantics are recorded in
`docs/testing/managed-docker-mediation-boundary.md`.

Integration and staging suites must use the MCP-RUNTIME3 containerized
Postgres harness with `--pg-container-port 55433` inside the authenticated
RepoMap DinD sandbox. The runner automatically dispatches every `int` and
`staging` invocation across that boundary; `--sandbox` is a redundant
compatibility assertion, not a stronger mode. Direct pytest collection under
`src/test/int/python` refuses outside the authenticated sandbox before fixture
or workload setup. No environment variable, alternate container runtime, or
Postgres option restores host execution.

The outer sandbox mounts only the checkout, read-only. Scratch, OverlayFS
upper/work state, the writable workspace, HOME, Git configuration, temporary
files, pytest state, language/build caches, the owner marker, and inner-Docker
state are invocation-scoped and container-private. The only permitted host
effects are the read-only checkout mount, exact outer-container lifecycle,
bounded dependency-only sandbox-image retention, stdout/stderr, and an
explicit report export. Reports are generated at a fixed container path,
validated as a bounded regular-file/directory archive, exported before exact
outer removal, and refused on path escape, symlink/special-file content, or an
existing destination. With no `--report`, no report destination is touched.
Privileged DinD remains a host-pollution boundary for ephemeral or VM-backed
Docker hosts, not a hostile-code or multi-tenant security sandbox.

ASYNC14 native Windows evidence uses the repository-controlled command below on
a disposable Windows runner. It intentionally does not install or mutate a
native service-manager task:

```powershell
python tools/run_windows_async14_tests.py
```

The command records sanitized runner facts and runs the loopback transport,
descriptor ACL, foreground service, and Job Object containment tests with
pytest's repository conftests disabled. This keeps the transport/process proof
from attempting the Linux-only disposable Postgres container on a Windows
Docker engine. It fails explicitly on non-Windows hosts. The historical workflow
file was `.github/workflows/async14-windows-runtime.yml` (retired in REPOMAP-CI1).
Historical evidence remains valid, and the underlying test script and tests
remain available for explicit Windows qualification or reproduction, though
GitHub Actions no longer runs the workflow automatically and no replacement
Windows CI lane is introduced in CI1. Native service-manager authority remains a
later phase until the transport and process-boundary proof is accepted.

ASYNC15 Windows startup-authority evidence uses the repository-controlled commands
below on a Windows host:

```powershell
python tools/run_windows_async15_tests.py
python -m pytest --noconftest -q src/test/int/python/repomap_kg/service_package/windows_startup.int.test.py
```

The probe exercises unique, temporary Task Scheduler definitions for both
`InteractiveToken` and passwordless `S4U` principals, validates structured XML,
checks exact foreground arguments and least-privilege intent, and removes each task
with repeat-delete and private-directory cleanup assertions. It records the runner's
account and session classification so an administrator-run canary cannot be presented
as ordinary-user authority. `sc.exe` availability is inspected without creating or
mutating a Windows Service. The historical workflow file was
`.github/workflows/async15-windows-startup.yml` (retired in REPOMAP-CI1;
historical ASYNC16 desired-state workflow `.github/workflows/async16-desired-state.yml`
was retired alongside it). Historical evidence remains valid, and test scripts
remain available for manual reproduction, but GitHub no longer runs these
phase-specific Windows workflows automatically. It does not claim PostgreSQL or
credential-file coverage when `psql.exe` is unavailable.

## Scoped Phase Verification

Scoped local verification is mandatory by default for ordinary development
phases. The ordinary local default is the narrowest exact unit paths or node
IDs beneath `src/test/unit/python` plus applicable changed-file static checks.
A local integration selector is optional, prompt-owned diagnostic evidence;
when requested, it remains automatically sandboxed and host-disposable. A
justified directory beneath a suite root is still scoped; selecting the whole
suite root is a complete run.

Unless the current prompt grants a complete-suite override, agents must:

1. Map changed production, test, tool, schema, and fixture paths to their test
   owners without inventing automatic Git-diff-to-test heuristics.
2. Run the narrowest exact unit paths or node IDs that cover the changed
   behavior.
3. Run exact integration paths or node IDs only when the current prompt
   explicitly requests that diagnostic; crossing a storage, process, runtime,
   database, or container boundary identifies the eventual hosted owner but
   does not make laptop integration an ordinary phase-closing requirement.
4. Add adjacent owners only when a shared contract makes them affected.
5. Run applicable changed-file static or compile checks.
6. Run `git diff --check` and `git diff --cached --check`.
7. Record the exact selectors, results, and scope reasons.
8. Record every unselected suite as intentionally not selected by scoped
   policy.

The normal final phase-verification forms are:

```sh
python3 tools/run_tests.py \
  --suite unit \
  --no-coverage \
  -- \
  src/test/unit/python/<owner>.unit.test.py::test_exact_contract
```

```sh
python3 tools/run_tests.py \
  --suite int \
  --no-coverage \
  --pg-container-port 55433 \
  -- \
  src/test/int/python/<owner>.int.test.py::test_exact_boundary
```

Multiple exact selectors may follow `--`. A pathless `-k` expression may help
exploration, but final evidence should use exact paths or node IDs. If `-k` is
retained, pair it with an exact path and `--no-coverage`. Scoped runs use
`--no-coverage` because they make no whole-population coverage claim; this
does not weaken or lower any threshold. Do not use `--threshold` to make a
partial population pass.

Agents must not routinely run complete unit, complete integration, staging,
system, or the retired `--suite all`. Hosted qualification is unified in
`.github/workflows/repomap-release-qualification.yml`: the `unit-tests` job
owns the routine complete unit population, `staging-integration-gate` owns the
logically approved smoke-then-complete-integration population, and
`main-system-gate` owns the logically approved assembled-product scenario. A
scope-complete local checkpoint does not become whole-population qualification,
and pending hosted gates remain pending. Hosted `EXHAUSTED` or `UNKNOWN` state
does not authorize a complete laptop substitute.

A locally verified product candidate may be retained and subsequent local
product development may proceed while hosted integration qualification remains
explicitly pending, unless the current operator prompt names a narrower
mechanical blocker. Local sandbox unavailability likewise records diagnostic
unavailability; it does not transfer the hosted qualification claim to the
laptop or force unrelated local work to stop.

## Complete-Suite Override

A complete local run is authorized only by a block or clear equivalent in the
current prompt that names:

```text
Complete-suite override:
- suite(s): <unit | int | staging | system>
- reason: <why scoped evidence is insufficient>
- candidate boundary: <exact state the run covers>
- maximum executions: <positive integer>
```

No block means no complete-suite authority. Phrases such as "run all relevant
tests", "be thorough", or "final gate" do not grant it. A failed scoped run
does not grant it. An agent or reviewer may recommend an override but cannot
self-authorize one, and executions must not exceed the stated maximum. The
status and commit message record whether an override existed and, when present,
its authority, suites, candidate boundary, and execution count.

Runner, discovery, coverage ownership, shared-fixture, suite-classification,
test-conftest, deferred-build, unit-purity, or integration-dispatch changes are
typical reasons a prompter may grant an override. They are examples, not
standing authority.

The complete staging composition remains executable only for an explicit
operator diagnostic or rare reproduction override. Even when such a local run
is authorized, it is diagnostic evidence and does not replace the logically
approved hosted Staging Gate:

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

Do not weaken the `heavy` profile's admission or safety policy. The profile is
the local development-laptop form, where the harness shares a disk with a full
developer environment. Hosted CI runs the same `--suite staging` work under the ADR
0053 `exhaustive` profile instead:

```sh
python3 tools/run_tests.py \
  --suite staging \
  --sandbox \
  --hygiene-profile exhaustive \
  --declared-complete-gates 1 \
  --operator-attest-exclusive \
  --operator-attest-pressure-degradation \
  --pg-container-port 55433
```

Both attestations are honest only on an ephemeral single-tenant runner. Do not
use the `exhaustive` form on the laptop to escape the `heavy` reserve.

Docs-only changes require:

```sh
git diff --check
git diff --cached --check
```

Add local docs link or path checks when a docs-only phase moves files or updates
links. An archive-layout migration must also verify complete document coverage,
stable numbers and basenames, introduction-date placement, unique targets,
resolved active references and fragments, and deliberate classification of any
retained obsolete paths. Do not run source test suites or compileall for a
docs-only patch unless the patch also changes executable behavior.

## Hosted CI Stewardship

Before any push, pull-request state change, workflow dispatch, rerun,
cancellation, or promotion, consult the
[agent hosted-CI stewardship policy](ci-agent-policy.md). Hosted-CI availability
(`AVAILABLE`, `CONSERVE`, `EXHAUSTED`, or `UNKNOWN`) is separate from
Agent-Central execution mode and never grants a remote action. Develop and
verify proportionally locally, batch publication, never duplicate automatic PR
Fast work, and preserve the policy's exact execution classification and pending
hosted gates in the phase closeout. No-step admission evidence supports neither
a hosted pass nor a hosted failure, and local evidence does not replace a
required hosted qualification claim.

## Hosted CI Current State

RepoMap promotes through two long-lived logically protected branches. "Logical"
is exact: private-operation policy is owned by the future JACA git broker, not by
GitHub branch protection, rulesets, required GitHub reviews, a merge queue, or
CODEOWNERS. None of those are configured, and "approval" throughout this section
means a logical approval of one exact pull-request revision, never GitHub's
review-approval feature.

```text
staging PR -> main
        |
        +--> repomap-release-qualification (.github/workflows/repomap-release-qualification.yml)
             |-- source-and-export-policy    staging source policy & public export boundary
             |-- pre-review-static           complete pre-review static analysis stack
             |-- unit-tests                  complete unit population (85/85 coverage)
             |-- staging-integration-gate    smoke and integration tests (exhaustive hygiene)
             |-- main-system-gate            assembled-product system qualification
             |-- codeql                      CodeQL security analysis (Python, Go)
             +-- sbom-security               Syft SPDX SBOM generation & Grype scanning
```

GitHub Actions is an evidence executor, never a git broker. No workflow merges,
updates a ref, enables auto-merge, or closes a pull request, and no workflow
holds a write permission. Until JACA owns merging, the human operator is the
temporary broker and decides what to merge from the gate's evidence.

RepoMap operates a unified release qualification workflow (`.github/workflows/repomap-release-qualification.yml`) spanning seven jobs across the qualification tiers:

1. `source-and-export-policy`:
   The promotion and export policy check. It verifies that pull requests targeting `main` originate from this repository's `staging` branch, and runs `tools/ci/public_export_policy.py` to enforce that public export boundaries and candidate commit identities hold. Any invalid source or policy mismatch fails immediately and runs no downstream jobs.

2. `pre-review-static` (formerly `repomap-static-analysis`):
   The pre-review static analysis lane.
   One sequential pre-review aggregate: Ruff, Pyflakes, mypy,
   retained-Python ratchets, file-length,
   compileall, actionlint, zizmor, pip-audit, govulncheck, Semgrep,
   Betterleaks, MalSkanner, Prompt Defense Audit, suppression visibility,
   offline Liquibase validation, Hadolint, and generated-output drift. It runs
   read-only permissions, unpersisted credentials, and explicit Python 3.13 setup,
   targeting Python 3.12 language semantics. It has zero dependencies on Docker,
   Postgres, or exhaustive test execution. Every check runs before one aggregate
   result; bootstrap/configuration/internal failures block. Its global Ruff correctness seed
   checks all executable repository Python in the configured production,
   test-support, test-suite, top-level test-conftest, and tools surfaces with
   rules `E9`, `F821`, `F822`, and `F823`; parser fixture trees are intentionally
   excluded. A separate cumulative production ratchet enforces the complete
   Pyflakes `F` family over `src/main/python/repomap_kg/runtime`,
   `src/main/python/repomap_kg/graph`, and
   `src/main/python/repomap_kg/server`. Mypy derives one explicit blocking
   target list from `tools/ci/python_type_ownership.json`: every T0
   cross-language contract and the declared T1 retained-Python seed. It uses
   current-checkout `MYPYPATH`, a mechanically tested silent-import boundary,
   and a sealed interpreter containing the exact project runtime dependencies.
   T2 transitional and T3 planned-replacement findings remain visible in a
   bounded informational inventory without broadening the blocking lane.
   `retained-python-ratchets` derives the complete T0/T1 retained production
   set from the same ownership manifest. It preserves hard-zero T0/T1-seed
   mypy and migration-direction gates, while monotonically ratcheting
   T1-future mypy findings and direct T2/T3 imports, full Ruff `F` findings
   across the retained set, and warning-band retained file lengths.
   Its candidate baseline must exactly match current actual state and must also
   descend monotonically from the unique trusted genesis through every
   reachable Git transition. Dirty worktrees use committed `HEAD` as their
   predecessor; clean checkouts audit the committed transition chain. Missing
   or shallow history is a tool failure, so this workflow checks out complete
   history. Baseline initialization is closed, debt increases are never
   authorizable, and removal or reclassification of retained scope requires an
   exact append-only scope-transition record bound to manifest and selected-set
   digests plus phase/status authority. New retained modules enter only clean.
   Semgrep runs through the exact console script owned by that sealed Python.
   Maintained Python code quality is protected under ratchets immediately
   rather than awaiting hypothetical replacement, with architecture placement
   reserved for the post-main phase. Planned-Go, planned-Go/Rust, and
   transitional Python implementation outside explicit retained maintenance
   enrollment remain outside the product baseline; a retention assessment of
   at least 80% still requires clean admission and is not waived by that label.
   `python-retention-inventory --check` in the same aggregate reconciles exact
   existing index plus nonignored untracked Python membership and executes its
   root-specific quality owners. Census-only output is `not_checked`, never
   an enforcement pass. Missing assignments, baselines, checker failures, or
   source changes during checking fail enforcement. Non-product executable
   paths use full Ruff F, checked function bodies in mypy, and zero-debt
   400-line admission through `python_quality_profiles`; they do not enter
   product coverage denominators. The inventory attributes mypy findings by
   canonical path, preserving raw findings, counts, and checker statuses.
   Dependency findings at product paths may be governed separately only when
   the current candidate's validated product selection and ratchet/type checks
   pass. Direct selected-root findings always remain debt, including findings
   encountered through imports. Unowned dependencies, path aliases, missing
   attestation, and tool failures remain fail-closed. Under ADR 0063, tools,
   support, and test owners gain credit only through stable admitted cohorts
   recorded in the inventory itself. Every member must pass direct checks and
   every outgoing repository dependency must be currently governed. Effective
   paths are the union of passing cohorts; partial credit leaves the root open
   and residual keeps the inventory failed. An admitted-cohort regression is
   separately classified as a hard ratchet regression. Immutable inventory
   lineage forbids removal, weakening, or silent reassignment. Root-batched
   cold checks preserve attestation without per-cohort subprocess costs.
   Inert extraction fixtures require explicit
   counterevidence and the fixture root; a non-executable label cannot exclude
   product, tooling, support, conftest, or test-owner paths. Executable
   child-pytest fixtures retain quality ownership. Required cleanup remains a
   failing residual until performed. The repository-wide file-length profile is
   still a separate no-waiver contract. It also runs the stdlib-only
   project-owned CI topology check `tools/ci/ci_topology.py`, which structurally
   parses the repository's own workflow YAML and asserts the contracts described
    here. The workflow triggers for pull requests targeting `main`, on
    `opened`, `reopened`, `ready_for_review`, and `synchronize`. There is
    deliberately no second arbitrary branch `push` trigger: `synchronize` *is* the
    push-to-open-PR feedback signal, and a duplicate lane would double cost while
    proving nothing extra. Static feedback remains independently visible and
    cancellable from the unit population.

3. `unit-tests` (formerly `repomap-unit-tests`) —
   the behavioral unit qualification lane. TEST-ISO1 proved that `--suite unit` is unit-only
   direct-host execution without Docker-backed integration resources, so this
   lane runs the complete canonical population exactly once through
   `python3 tools/run_tests.py --suite unit`. It installs
   `.[test,scale-tools,static-analysis]`. The `scale-tools` extra supplies `docker`
   and `psutil` for injected clients, parsers, and failure mapping. The pinned
   static-analysis extra supplies the real mypy and Ruff subprocesses exercised by
   `src/test/unit/python/tools/ci/python_quality_identity.unit.test.py`, including
   checker configuration, diagnostic and source-attestation controls. Its capture
   wrappers delegate to the original `subprocess.run`; they are not tool doubles.
   Unit installation consumes the project extra without the hash-locked PR Fast
   bootstrap; it does not change runtime dependencies or the static lane lock. Package
   availability grants no live-resource authority: unit purity guards still
   fail closed on Docker or Postgres contact. The canonical runner validates and
   builds the existing Go helper, so the workflow pins the Go toolchain `src/main/go/go.mod` and bootstraps verified `golangci-lint` v2.6.2. Python
   statement coverage fails below 85% and branch coverage fails below 85% (settled
   in REPOMAP-CI2A-R4D); Go retains its separate 85% statement gate. It has no
   integration, smoke, sandbox, Docker, or Postgres access. Its 60-minute job
   timeout is a conservative hosted qualification envelope, not an expected runtime.

4. `staging-integration-gate` (formerly `repomap-staging-gate`):
   The staging smoke and integration gate. It runs with `--suite staging`,
   `--hygiene-profile exhaustive`, selecting the owned DinD backend explicitly with
   `--sandbox`. `--suite staging` owns smoke-then-integration ordering, so the workflow
   does not run either stage separately and reproduces no test ordering, coverage
   arithmetic, or operation accounting of its own. Third-party Actions are pinned to
   immutable full commit SHAs. The host retains Python 3.13 for the repository-local
   launcher, while the owned sandbox recipe supplies the Python test environment.
   The composed gate owns integration tests with hard 80/80 coverage, container smoke,
   and Docker operation and residue accounting. It emits a machine-readable
   `repomap-ci-gate-result-v1` artifact binding that candidate. Its 180-minute outer
   job timeout reserves hosted-runner variance around the semantic smoke-then-integration
   gate.

5. `main-system-gate` (formerly `repomap-main-system-gate`):
   The canonical assembled-product main promotion qualification gate (REPOMAP-SYS0-FIX1).
   It tests the packaged candidate release container image
   (`repomap-system-candidate:<tree_prefix>`) built under managed boundary authority.
   It strictly rejects host repository source mounts, verifies container cluster readiness,
   durable coordinator refresh, controlled coordinator crash/interruption recovery, idempotency
   replayed coalescing and fencing, and line-delimited JSON-RPC MCP stdio readback with deterministic
   canonical semantic projection hashing. It emits `repomap-ci-gate-result-v1` companion with
   `repomap-system-gate-binding-v1` referencing the exact system report SHA-256.
   The 90-minute outer job envelope contains an inner
   `--system-timeout 3600` runner-owned semantic deadline, reserving 30 minutes
   for checkout, installation, image/build setup, cleanup, evidence, and hosted
   variance. The ordinary local system default remains 1,500 seconds.

6. `codeql` (`codeql-analysis`):
   Matrix security analysis for Python and Go with GitHub CodeQL action. Runs with
   `security-events: write` permissions and 30-minute timeout.

7. `sbom-security` (`sbom-and-vulnerability-scan`):
   Generates a full SPDX-JSON Software Bill of Materials (SBOM) using Anchore Syft
   and performs vulnerability scanning using Anchore Grype (`severity-cutoff: high`,
   `fail-build: true`). Runs with 20-minute timeout and publishes `repomap-sbom` artifact.

All hosted envelopes are ceilings rather than expected runtimes: `source-and-export-policy`
has 10 minutes, `pre-review-static` has 40 minutes, `unit-tests` has 60 minutes,
`staging-integration-gate` has 180 minutes, `main-system-gate` has 90 minutes,
`codeql` has 30 minutes, and `sbom-security` has 20 minutes. Hosted runners are materially
slower and more variable than the operator laptop. Record actual durations so
the outer envelopes can be tightened from evidence. Do not expand product,
worker, heartbeat, deadlock, cancellation, subprocess, database, or
individual-test deadlines, and do not add automatic retries to conceal
deterministic failures.

The gate supplies two ADR 0053 admission arguments that only an ephemeral
single-tenant host may honestly make: the exclusive attestation and the
pressure-degradation attestation. Linux memory readings come from
`/proc/meminfo` and are classified degraded, so every hosted run carries
`memory_pressure_degraded` in its admission decision. It supplies no free-disk
reserve override: the `exhaustive` profile's 10 GiB reserve is already within a
hosted runner's capacity, so the gate deletes no preinstalled toolchains and
instead records two exact `df -B1` readings as evidence.

**Hosted exhaustive correctness is ACCEPTED.** REPOMAP-CI0B live run
`32516257994` completed the whole composed gate successfully, and earlier live
failures demonstrated that a project-test failure or a managed-smoke cleanup
failure makes the workflow red. `staging-integration-gate` therefore owns routine
exhaustive correctness verification for private development, while development
agents own the proportional local verification defined above.

Server-side required-check enforcement is unavailable under the current private
repository GitHub plan. That limitation is not a correctness failure of the
hosted gate and is not a claim that GitHub blocks merges after a red check.
During private single-operator development, the operator procedurally owns merge
discipline; external-contributor enforcement remains deferred until repository
exposure or the GitHub plan makes that protection appropriate and available.
Outside-contributor repositories may adopt GitHub rulesets later in a separate
phase.

REPOMAP-CI0B's handoff activation was defined as a green push-to-`main` run of
the then-`pull_request`/`push`-triggered gate. REPOMAP-CI-PIPE0 replaces that
mechanism rather than satisfying it. There is now no `push` trigger anywhere, so
**a push to `main` runs no hosted check at all.** That is an accepted
consequence, not an oversight. The compensating control is structural: the only
supported way to move `main` is a `staging -> main` promotion, and the exact
tree being promoted has already been qualified by a green staging gate against
that same content. Re-running the identical suite on the identical tree would
have produced evidence, not information. `staging -> main` promotion is
governed by the `main-system-gate` assembled-product gate and the source and export policy.

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

### Logical gate request and result

The staging gate is invoked by the project-owned contract
`repomap-ci-gate-request-v1`, implemented in `tools/ci/gate_contract.py`. It
binds:

```text
gate_kind  pr_number  base_branch  base_sha  head_branch  head_sha  approval_id
```

Its meaning is exact: *qualify this head against this base for this gate*.
`approval_id` is an opaque correlation value and deliberately models no GitHub
reviewer identity. A change to either the base or the head invalidates the
request; the newer revision is never silently qualified under an older approval,
and a stale request fails before any expensive setup runs.

`workflow_dispatch` is only the current bootstrap transport. Its inputs are
`pr_number`, `approved_base_sha`, `approved_head_sha`, and `approval_id`; the
workflow name fixes `gate_kind=staging`. A future JACA broker constructs and
dispatches the same logical request, which is why all binding logic lives in the
project-owned command rather than in workflow YAML.

Before any expensive work the gate validates that the pull request is open and
not a draft, that the head comes from this repository, that the base branch is
`staging`, that the current base and head SHAs equal the approved ones, and that
a merge candidate still exists. It then resolves the candidate and proves the
relationship from the merge commit's own parents rather than trusting API
fields:

```text
git rev-parse HEAD          -> tested_candidate_sha
git rev-parse HEAD^{tree}   -> tested_candidate_tree
git rev-parse HEAD^1        -> must equal approved base SHA
git rev-parse HEAD^2        -> must equal approved head SHA
```

The emitted `repomap-ci-gate-result-v1` artifact records `gate_kind`,
`approval_id`, `pr_number`, the approved base/head, the tested candidate SHA and
tree, the candidate's parents, `conclusion`, and `merge_authorized`.
`merge_authorized` is true only when that exact recorded candidate passed; a
failed gate or a changed base/head never authorizes merging. The schema is
closed — unpublished fields are rejected — so no secret, source payload,
database content, or host-private path can ride along. A future JACA broker may
synthesize the final merge commit, but must be able to prove it preserves the
tested candidate tree and the approved base/head relation.

Drift between approval and dispatch therefore manifests as a red gate rather
than a retry. That is the intended failure mode.

### Main milestone gate

Promotion of `staging` to `main` requires logical milestone approval followed
by the implemented `main-system-gate` job in `repomap-release-qualification.yml`. The gate runs the bounded SYS0
assembled-product system suite for the exact approved base/head pair and emits
SHA/tree-bound authorization evidence. Later release, packaging, SBOM, and
image/release security checks remain roadmap work; they are not implied by the
implemented system gate.

### Planned check placement

Cost tiers, for deciding where a future check belongs:

```text
PR Fast
  Ruff, current mypy, CI/policy contracts
  proven-pure canonical unit qualification at 85/85 coverage
  cheap source/policy checks

Staging Gate
  substantial smoke, then unified isolated integration
  independent integration qualification at 80/80 coverage
  medium-cost dependency/security checks

Main Milestone
  assembled-product SYS0/system qualification
  packaging/release install
  SBOM/image/release security

Periodic/explicit
  performance/scale
  drift qualification
  very expensive compatibility/security campaigns
```

A new check that does not fit its tier's cost profile belongs in a different
tier, not in a faster one with a timeout raise.

### Isolated unified integration sandbox

TEST-ISO1 retained one canonical integration population and made `int`
integration-only. REPOMAP-TEST-ISO1-FIX1 qualified the sandbox as an explicit
backend, and REPOMAP-CI0B-FIX31 adopted it for the hosted Staging Gate after
closing the report, prerequisite, diagnostic, and combined-suite evidence
conditions. Direct host execution remains the developer default. The suite
taxonomy is:

```text
unit
  pure/hermetic unit behavior
  no live Docker
  no live Postgres
  no persistent host IPC
  no external host mutation

int
  all integration tests by default
  executes inside an owned integration sandbox
  supports full-suite and exact file/class/node selections
  sandbox owns an inner Docker daemon
  tests may create nested containers/images/volumes against that daemon
  no host Docker socket is mounted into the sandbox

smoke
  existing container smoke contract

system
  externally observed assembled-product tests

staging
  canonical staging qualification composition
```

The tested persistent-host prototype shape is:

```text
persistent host / GitHub runner
        |
        +-- one RepoMap-owned privileged integration sandbox container
              |
              +-- pytest / integration process
              +-- scratch and sandbox-local process namespace
              +-- inner dockerd
                    |
                    +-- Postgres test containers
                    +-- Docker/resource test containers
                    +-- test images/volumes/builds
```

The persistent daemon owns the collision-resistant outer container and a
dependency-only `repomap-test-sandbox:*` image cache; candidate source is never
baked into that cache. The image recipe uses immutable base digests, carries
positive ownership and recipe labels, retains at most two images, protects the
current and container-referenced identities, and removes only exact owned stale
IDs with no-prune semantics and absence readback. Inner `/var/lib/docker` is a
4 GiB tmpfs, so no image-declared anonymous data volume exists. Exact outer
`docker rm -f -v` and absence readback run on success, test/setup failure,
SIGINT/SIGTERM, and launcher exceptions. A before/after host identity snapshot
fails closed on unattributed container, image, volume, or network residue and
never authorizes host-wide pruning.

Once the exact outer ID is validated, the launcher starts one
`docker logs --follow <outer-id>` child with inherited stdout and stderr. This
streams setup and test output to the host without buffering the whole run or
discarding its beginning. Normal outer exit is followed by a bounded follower
drain so the final tail is delivered once; no post-hoc whole-log replay occurs.
On SIGINT, SIGTERM, or launcher exception, exact outer cleanup remains primary,
then the follower is drained or terminated and joined. A follower start,
readback, timeout, or nonzero-exit failure is reported, fails an otherwise
successful sandbox run, and does not replace an earlier test or interruption
status. Report export occurs after outer stop and before exact outer removal. An
uncatchable runner kill can still prevent the last buffered tail and report
export because no launcher cleanup time exists.

This is Docker-in-Docker, not Docker-outside-of-Docker. The sandbox never mounts
`/var/run/docker.sock`; the closed internal marker additionally rejects a
present host socket. Host source is mounted read-only at `/workspace-ro`, a
run-owned overlay is projected at `/workspace`, and pytest cache and bytecode
go to scratch. The test process and inner daemon see `/workspace` and
`/sandbox-scratch` at
identical paths, which is mechanically probed with a nested bind mount.

The PR26-STAGING-FIX2 candidate separates host/backing reserve from sandbox
capacity. Its current-owner binding proves the outer root's classic Docker
`overlay2` mapping before the runner measures that exact backing filesystem;
the 10 GiB exhaustive host floor never consumes scratch-tmpfs evidence. The
mapping is inspected on the target and is never inferred from an Engine version
or expanded into a claim about the whole Docker data root or host disk. Unknown
or unprovable mappings refuse. The 8 GiB scratch tmpfs, 4 GiB exhaustive quota,
and 4 GiB inner-Docker tmpfs remain independent. `validate_scratch_capacity()`
takes no quota or allocated-byte arguments and requires current whole-scratch
free space of at least a 1 GiB policy margin, exact 8 GiB scratch capacity,
exact 4 GiB inner-Docker capacity, and nonzero inner-Docker free space. The
margin covers actual pressure from non-ledger overlay state, metadata, caches,
temporary files, and HOME; it is not measured workload demand or free RAM.
The `QuotaTracker` remains the sole effective logical limit, including validated
overrides, so the existing 8 GiB integration maximum remains supported rather
than becoming a physical reservation. A separately labelled physical-capacity
refusal can precede that logical limit; no quota is silently lowered.
Capacity calculations that need a run limit read the validated effective value
from that existing `QuotaTracker`, including a supported override, rather than
copying `profile.quota[0]` or creating a second authority.

The binding is checked for invocation identity and mount continuity on every
read; its issuance value must be an integer that is nonnegative and not in the
future. Binding age alone does not expire the invocation, so late nested readers
may revalidate the same token and mount after more than 120 seconds while taking
fresh measurements. A different attempt cannot replay the binding because its
owner token differs, and no timestamp refresh or heartbeat loop is used.
Expected mount, filesystem, and decoding failures become bounded
capacity-domain refusals with private causes; public messages contain no raw
paths or exception text. Cleanup continues after a refusal and preserves
primary workload or interruption precedence. Bounded outer and inner setup can
occur before a pre-smoke/pre-pytest refusal because the real mapping and tmpfs
measurements must be established. For a requested report, the outer container
is stopped and export is attempted before exact outer removal at
`/sandbox-report/report`, outside scratch.
See [ADR 0055](../adr/2026/08/0055-isolated-unified-integration-sandbox.md)
for the candidate's binding, freshness, and qualification limitations.

Privileged DinD is an isolation and pollution-control mechanism, not a security
boundary for hostile code: it shares the runner kernel. `--cgroupns=host` is
required so resource-observation tests receive real Docker memory statistics;
the process and IPC namespaces remain container-local. The strongest intended
future JACA boundary is the disposable Tart VM itself.

Integration suite semantics remain independent from the sandbox backend:

```text
persistent host -> DinD integration sandbox
ephemeral Tart VM -> VM-owned daemon directly, or DinD if useful
GitHub hosted -> DinD initially if stable, or an equivalent disposable owned sandbox
```

Destroying a Tart VM already destroys its Docker, IPC, and process state, so
TEST-ISO1 must not require nested Docker there merely for architectural purity.
The unified integration suite may use the VM-owned daemon directly when that is
simpler and faster. Pytest must not encode JACA, Tart, or backend-specific
policy.

The entry inventory and exact per-module evidence are retained in
[`../testing/test-iso1-entry-capability-inventory.json`](../testing/test-iso1-entry-capability-inventory.json).
The sandbox passed representatives for Postgres, Docker SDK/CLI and resource
mediation, ordinary process/cancellation, support-mediated IPC, nested bind
mounts, and the Go 1.25 toolchain. The remaining two SCALE13 cancellation nodes
failed because the parent could send SIGINT after transmitting the STARTED ACK
but before the child-side transport had settled it and entered the test blocker.
The Linux sandbox separately proves that `threading.Event().wait()` executes
normal Python `KeyboardInterrupt` and `finally` unwind. The test-only control
path now sends one child-originated readiness byte after the real send/ack call
returns and immediately before blocking; only then may the parent send its sole
SIGINT.

Both exact nodes pass with strict lifecycle validation and publication rollback.
One fresh full population collected 884 tests, deselected the 12 registered
build-profile nodes, selected 872, and passed at 72.9% line and 58.5% branch
coverage with zero outer or unexpected host Docker residue. No `infra-int`,
skip, xfail, validator weakening, product lifecycle change, or parent-synthetic
terminal was introduced. REPOMAP-CI0B-FIX31 later proved report export after
outer removal, inner-daemon prerequisite pulls before the canonical inner
Docker baseline, untruncated diagnostic log readback, and unchanged
the then-combined behavior (now retired), then selected the sandbox explicitly for hosted staging
qualification. REPOMAP-CI0B-FIX32 then made that diagnostic stream live for the
owned outer container and added deterministic drain, failure reporting, and
interruption cleanup without changing direct-host execution.

The governing unit-purity invariant remains independent of DinD:

> A canonical unit test that requires live Docker, live Postgres, persistent IPC,
> mutates external host state, or depends on another external service is
> misclassified or violates concern separation.

The entry inventory found no actual live-resource unit violation and no test was
reclassified. During canonical unit items, the runner activates a closed purity
guard. Repository-owned Postgres constructors fail, rather than skip, before a
new or already-live container session can be consumed; injected test doubles
remain valid. The guard is deliberately bounded rather than a global subprocess
ban. Its current limitation is that an entirely new direct live-resource path
outside the owned constructors depends on the mechanical inventory and must add
its own guard hook.

Forwarded integration selections are validated against
`src/test/int/python` and cross the wrapper as unchanged argv. File, class,
test, and quoted parameterized node IDs remain exact; a selection outside the
integration root is refused inside the owned sandbox and still triggers exact
outer cleanup.

### JACA/Tart seam

Workflow YAML stays thin and test semantics stay in project-owned commands, so
the runner can be replaced without rewriting the contracts:

```text
today:  ubuntu-latest -> same project-owned gate command

future: JACA -> ephemeral Tart Linux ARM64 VM
             -> ephemeral GitHub Actions runner
             -> same project-owned gate command
             -> destroy VM
```

No self-hosted or Tart runner labels are configured yet.

## Qualification Evidence

The cross-cutting procedure for ADR 0049 qualification claims is
[`qualification-evidence-contract.md`](qualification-evidence-contract.md).
Ordinary development and scoped test runs remain useful feedback but do not
become qualification evidence retroactively. When a phase will make a
qualification claim, declare its attempt before execution and bind
repository-content, environment, and runner/profile identity.

For a canonical whole-population `unit`, `int`, `smoke`, `staging`, or `system`
claim, record the exact suite command, candidate identity, environment and
runner identity, suite result, and whether coverage was enabled. The suite
defines its collected population; an exact node manifest is not a general
requirement. Integration/staging additionally seal the exact M/A partition under
the ADR0067 PR26-STAGING-CONTRACT1 amendment before bodies execute. A
fixed-cohort or exact-set claim makes membership load-bearing and requires the
ordered manifest and the other reproducibility fields in the qualification
contract.

When coverage applies, preserve these as separate provenance facts: pytest
status, runner composed status, line coverage, branch coverage, threshold, the
policy or selector choosing that threshold, explicit threshold decision, and
measured root set. A bare exit `1` does not establish whether tests or coverage
failed. Smoke is not coverage-tracked and must not be given invented coverage
figures.

The [ADR0067 amendment](../adr/2026/09/0067-runner-owned-portable-child-measurement.md#pr26-staging-contract1-amendment--two-required-evidence-obligations)
requires ordinary measured integration M plus exact predeclared abrupt behavior A.
Both are required behavioral obligations, not optional coverage alternatives.
M retains the full product-source denominator, same-invocation validated data
and independent 80/80 floors. A reports unavailable/incomplete abrupt-child
measurement and contributes no data to M; ordinary measured children in A remain
strict. Authentic start/checkpoint, exact termination and bounded cleanup are
required, without fabricated terminal receipts or post-outcome reclassification.
Explicit platform/opt-in skips and build deselections remain separate non-passes.
Scoped selectors remain diagnostic and `--no-coverage` cannot qualify coverage.
Ordinary failures retain the other leg's evidence where supervisor safety permits;
interruption or unproved cleanup blocks unsafe continuation and fails aggregation.
Report validation and manager acceptance follow
[staging-obligations-acceptance.md](staging-obligations-acceptance.md).

## Test Layout

The three exact abrupt-leg tests declared in `runner_integration_obligations.py`
must run through `tools/run_tests.py`, including scoped diagnostics. Bare pytest
does not supply their sealed launch context and fails instead of executing the
declared abrupt child without runner-owned evidence accounting.

Current pytest discovery uses:

- test roots: `src/test/unit/python` and `src/test/int/python`;
- filename pattern: `*.test.py`.

Current project convention is more specific than pytest discovery: unit test
files should normally end in `.unit.test.py` and integration test files in
`.int.test.py`. Shared test helpers live under `src/test/support/python/`.

Do not move tests to paths that pytest does not discover, and do not rename
tests to a pattern that `pyproject.toml` does not collect unless the same
accepted phase updates the test configuration and verifies discovery.

When splitting or moving tests is authorized (see
`docs/contrib/test-refactor-authorization.md` for the standing
authorization):

- keep unit tests under `src/test/unit/python/` and integration tests under
  `src/test/int/python/`;
- preserve behavior-focused assertions and avoid helper frameworks that make
  assertions harder to read;
- ensure each moved test still runs under the intended suite;
- prefer names that identify the production module or behavior boundary
  being tested;
- run the narrowest exact affected selectors during development; complete local
  gates require a current prompt-owned override.

## Test Design

- Use exact scoped tests as the ordinary final local evidence. Run a complete
  local gate only under a current prompt-owned override; hosted qualification
  remains pipeline-owned.
- Prefer public fixtures and temporary state.
- Use mocks or fakes for external commands, container orchestration, network
  calls, and runtime processes when the behavior under test is orchestration.
- Integration tests should prove real storage/runtime boundaries only when that
  is the contract being changed.
- Keep redaction and non-execution boundaries under test for extractors and
  readback helpers.
- Do not weaken thresholds or mark failing coverage as acceptable inside a
  feature phase.

### Atomic retention cycles (ADR 0065)

Multi-cohort dependency SCCs may pass atomically only within one root/profile,
with complete passing member evidence and independently governed external
obligations. All constituents must be admitted before any group governance is
effective. Clean all-pending groups are diagnostic only; mixed admission and
cross-root groups remain blocked. A failed admitted constituent remains a
regression. Stable cohort membership and immutable history are unchanged.
