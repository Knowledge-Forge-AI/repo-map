# RepoMap Test Runner Policy

## Status

Accepted and implemented through the TEST-RUNNER-SAFETY3-FIX1 development
candidate. Qualification and promotion of that candidate remain separate.

TEST-INFRA0 documented the target policy. TEST-INFRA1 added pytest
compatibility. TEST-INFRA2 migrated `tools/run_tests.py` to pytest while
preserving the public suite interface. TEST-INFRA3 added opt-in pytest-xdist
unit development runs. TEST-INFRA4 made coverage.py line and branch coverage
authoritative for serial runs. REPOMAP-CI2A-R1 retires the combined suite in
favor of independent unit and integration coverage ownership.

TEST-SMOKE1 added the containerized smoke suite. REPOMAP-SYS0 added the
assembled-product system gate. The public runner supports `--suite unit`,
`--suite int`, `--suite smoke`, `--suite staging`, and `--suite system`;
`staging` runs substantial smoke first and integration second, fail-fast;
`system` runs the 5-phase packaged container release lifecycle with zero
source mounts. The retired `all` selector is rejected. The smoke design lives in
`docs/testing/containerized-smoke-test-design.md` and the system design lives in
`docs/testing/containerized-system-test-design.md`.

TEST-RUNNER-SAFETY1 first replaced the ordinary smoke build with an exact
pre-provisioned image. ADR 0052 and TEST-IMAGE-LIFECYCLE1 replace manual image
preparation with one managed dependency-runtime cache while preserving exact
current-run container ownership.

TEST-RUNNER-SAFETY3-FIX1 extends the ordinary build prohibition across the
complete canonical unit/integration population. Twelve exact real-build test
nodes remain visible under the `requires_build_profile` marker and the closed
registry in
`src/test/support/python/repomap_test_support/build_profile_debt.py`. The
canonical runner validates marker/registry agreement, deselects those nodes,
and prints the exact deferred count. A direct attempt to run one fails closed;
only a future separately implemented and authorized build profile may replace
that refusal, and no ambient environment variable supplies authority. The tests
are not skipped, xfailed, deleted, or represented as passing. The build profile
and those twelve nodes remain deferred debt.

TEST-ISO2 removes the direct-host integration backend. Every `int` and
`staging` invocation now enters the authenticated RepoMap sandbox
automatically; `--sandbox` is a compatibility assertion only. Direct pytest
collection under the integration root refuses before fixtures or workload
setup when the marker/token, inner-Docker authority, and absent-host-socket
proof is unavailable.

The MCP-LIVE series remains paused after MCP-LIVE17. New testing
infrastructure work should use the TEST-INFRA or TEST-COV series.

## Current Verification Standard

Source, test, runner, package metadata, schema, or behavior-affecting fixture
changes require exact scoped unit verification and applicable changed-file
static checks (see `docs/contrib/testing-standards.md`). This is the mandatory
ordinary local default. Local integration is optional, prompt-owned diagnostic
evidence and is always auto-sandboxed. Complete unit, integration, staging, or
system runs require an explicit current prompt-owned complete-suite override;
a local complete integration or staging run does not replace hosted
qualification.

PR Fast owns complete unit feedback. Hosted CI (`repomap-staging-gate`) owns
the complete smoke-then-integration correctness gate for changes promoted into
`staging`, and runs only on an explicit logical gate request. The complete
laptop command remains supported only for explicit operator diagnostics and
rare reproduction work; it is not promotion evidence:

Hosted workflow timeouts are conservative outer qualification envelopes, not
expected runtimes: static analysis retains 25 minutes, PR Fast unit has 60
minutes, Staging Gate has 180 minutes, and Main System Gate has 90 minutes.
GitHub-hosted runners are materially slower and more variable than the operator
laptop. The hosted Main System Gate therefore uses an inner semantic deadline
of `--system-timeout 3600`, leaving 30 minutes in its outer envelope for
checkout, installation, image/build setup, cleanup, evidence, and runner
variance. The ordinary local system default remains 1,500 seconds. Record
actual hosted durations so outer envelopes can be tightened from evidence;
never change product, worker, database, subprocess, or individual-test
deadlines merely to consume an outer CI budget.

```sh
python3 tools/run_tests.py --suite staging --hygiene-profile heavy \
  --declared-complete-gates 1 --pg-container-port 55433
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

Integration and staging suites must keep using the MCP-RUNTIME3 containerized
Postgres harness inside the automatic RepoMap sandbox. Do not fall back to host
IPC, host Docker/Postgres sockets, a developer database, or an alternate
runtime.

Docs-only commits require:

```sh
git diff --check
git diff --cached --check
```

Do not run source-code test suites or compileall for docs-only patches unless
the patch also changes executable code, tests, migrations, build logic, package
metadata that affects behavior, or checked-in runtime data.

## Current Runner Shape

The current `tools/run_tests.py` runner:

- uses pytest execution under the public `tools/run_tests.py` interface;
- discovers `*.test.py` files through pytest configuration;
- runs unit tests under `src/test/unit/python`;
- runs integration tests under `src/test/int/python`;
- auto-dispatches `int` and `staging` before host scratch allocation, pytest
  import/collection, Go preparation, Postgres setup, or Docker-boundary setup;
- measures line and branch coverage with coverage.py for serial runs;
- measures an explicit source-tree denominator under `src/main/python`;
- supports `--suite unit`, `--suite int`, `--suite smoke`, `--suite staging`, and `--suite system`;
- starts the containerized Postgres integration harness for suites that include
  `int`;
- runs substantial containerized smoke without coverage for `--suite smoke` and
  before integration for `--suite staging`;
- runs the 5-phase packaged assembled-product lifecycle for `--suite system`;
- forwards scoped pytest arguments after `--`;
- supports `--jobs auto|N` for explicit parallel unit development runs;
- supports `--no-coverage` for parallel runs where pytest-xdist coverage
  aggregation is not enabled;
- rejects integration and staging parallel runs until the integration harness
  is isolated for xdist workers;
- mounts the checkout read-only as the sole host bind, keeps scratch, overlay
  upper/work state, HOME, caches, marker, writable workspace, and inner-Docker
  state container-private, and publishes no host port;
- exports reports only when requested from one fixed stopped-container path,
  with bounded archive membership, regular-file/directory-only extraction,
  path and symlink checks, and refusal to replace an existing destination;
- removes the exact outer container and accounts for host container, image,
  volume, and network residue on every terminal path.
- validates that every collected real-build marker is present in the exact
  deferred registry and that a whole canonical integration population contains
  all and only the twelve registered build-required nodes;
- snapshots exact Docker image and volume IDs before container-capable work,
  verifies the boundary after pytest and at terminal close, protects every
  pre-existing ID, and fails without deletion on a new unattributed or
  current-run-residual ID.

Every image build and image acquisition inside a runner process is mediated by
one canonical authority. `docs/testing/managed-docker-mediation-boundary.md` is
the single durable reference for which surfaces are enforced, what the closure
claim does and does not cover, and how the fail-closed run-wide boundary
behaves. Do not restate that surface set here.

Install the test and SCALE operational-tooling extras before running the
pytest-backed runner in a fresh environment:

```sh
python3 -m pip install -e '.[test,scale-tools,static-analysis]'
```

The `scale-tools` group owns the exact-pinned psutil and Docker SDK
dependencies used by repository operational sampling; neither is a shipped
`repomap_kg` dependency.

The public complete-population commands remain available for pipeline-owned
qualification and explicitly authorized local diagnostics. With no selector
after `--`, unit and integration retain their complete-population coverage
policy, but only the hosted Staging Gate owns complete integration promotion
evidence:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int --pg-container-port 55433
python3 tools/run_tests.py --suite smoke
python3 tools/run_tests.py --suite staging --hygiene-profile heavy \
  --declared-complete-gates 1 --pg-container-port 55433
```

The normal scoped phase-verification commands are:

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

The runner preserves exact file and node-ID selectors, including parameterized
node IDs, and accepts multiple ordered selectors. It resolves the path portion
before `::` and refuses a unit selection outside `src/test/unit/python`, an
integration selection outside `src/test/int/python`, or a selection outside
both roots. Selected integration tests remain serial and receive the
repository-owned containerized Postgres runtime and port environment.

Scoped runs use `--no-coverage` because a partial population cannot support the
complete source-tree coverage gate. No coverage claim is made and no threshold
is weakened. A no-selector canonical unit or integration command continues to
measure the explicit `src/main/python` denominator at its existing policy.

## Coverage Policy

Unit runner:

- fails if aggregate statement coverage is below 85%;
- fails if aggregate branch coverage is below 85% (settled in REPOMAP-CI2A-R4D).

Integration runner:

- fails if aggregate line coverage is below 80%;
- fails if aggregate branch coverage is below 80%;
- warns, but does not fail, if aggregate line coverage is below 85%;
- warns, but does not fail, if aggregate branch coverage is below 85%.

Staging runner:

- runs smoke first and stops when smoke is red;
- runs the integration population second at its independent 80/80 gate;
- never runs unit or computes combined unit-plus-integration coverage.

The coverage denominator is the explicit Python source universe under
`src/main/python`, not only files accidentally imported by the test run.
Coverage.py emits line and branch data for that source tree.

Smoke runner:

- is pass/fail only;
- is not coverage-tracked;
- qualifies Docker only; Podman compatibility is deferred;
- asks `TestImageManager` to ensure a dependency-only runtime cache and
  consumes its exact Engine ID; an exact-ID override remains diagnostic-only;
- permits builds only inside that manager; reuses the configured exact
  repository digest locally or pulls only that digest once under single-flight
  authority, with RepoDigest, Engine-ID, and architecture readback;
- rejects mutable-tag, registry-resolution, alternative, fallback, unmanaged,
  and broad-prune acquisition paths;
- reports product/build-profile builds, managed runtime builds, managed
  external-base pulls, unmanaged builds, and unmanaged pulls as closed classes;
- materializes a missing managed runtime through one label-free, exactly
  ledgered temporary container, a private persisted recovery claim, and one
  final commit whose labels are exactly the five durable cache labels, with
  zero runtime-build intermediate image residue and exact failure cleanup;
- retains at most two eligible managed cache images while protecting the
  requested and container-referenced images; deployment and legacy images are
  never GC targets;
- mounts the current checkout read-only at `/workspace`, selects its source
  with `PYTHONPATH=/workspace/src/main/python`, and disables networking;
- creates centrally labelled containers except for the positively claimed
  label-free runtime materializer, registers their exact returned IDs
  in the active resource ledger, and proves exact cleanup and baseline
  restoration;
- runs bounded dependency/import plus `python -m repomap_kg --help` sanity
  commands;
- fails clearly when the container runtime is missing, a smoke command fails,
  or a timeout expires.

All ordinary Postgres container producers use local-only image semantics and
override `/var/lib/postgresql/data` with tmpfs before creation. Managed
containers carry centralized current-run labels, register the exact Engine ID
returned by creation before cleanup, omit `--rm`, remove only that exact ID
with volume deletion disabled, and prove final absence. Group-K and
container-pair routes use the same ownership contract.

The shared short-directory helper owns Unix-socket budgets in encoded bytes.
It allocates under the registered `run_root/s` group, validates the actual
created path plus caller-declared suffix, and refuses before workload entry
when even a one-byte owned component cannot fit. Preparation workers similarly
inherit explicit `PYTHONDONTWRITEBYTECODE=1` policy from the test scratch
environment while the accepted attempt clock begins immediately before worker
process start.

The test-only local-runtime creation/teardown contract remains visible deferred
support for the same twelve build-required nodes. It is unit/fake-tested but is
not an executed or qualified build-profile path; TEST-HYGIENE3C still owns any
future activation.

Smoke must not use private graph config, host home, private repositories,
operator databases, live graph refreshes, or persistent generated artifacts by
default.

The existing `--threshold` option remains available for explicitly authorized
coverage diagnostics. It overrides the hard line and branch threshold for that
run. Do not use it to make a scoped population pass; routine scoped runs use
`--no-coverage`, and final complete-suite qualification uses the default policy
unless an accepted phase explicitly says otherwise.

## Development Runs

RepoMap has more than 1100 tests, so agents must use scoped test runs during
ordinary development and bug fixing unless the current prompt grants a
complete-suite override.

The target developer workflow is:

- run the narrowest unit tests for the module or behavior being edited;
- run local integration only when the current prompt explicitly owns that
  optional diagnostic; it is always sandboxed and host-disposable;
- add adjacent exact owners or a justified subdirectory only when shared
  contracts make them affected;
- record complete unit, integration, staging, and system as intentionally not
  selected when the prompt supplies no override; and
- request an override instead of self-escalating when only complete-population
  evidence can resolve the risk.

Hosted `EXHAUSTED` or local sandbox unavailability leaves the Staging Gate
pending; neither transfers that claim to the laptop. A locally verified product
candidate may be retained and subsequent local product work may continue unless
an operator prompt names a narrower mechanical blocker.

Pytest arguments may be forwarded after `--` when the scoped run honestly
covers the changed behavior:

```sh
python3 tools/run_tests.py --suite unit --no-coverage -- \
  src/test/unit/python/repomap_kg/test_cli.unit.test.py::test_exact_contract
python3 tools/run_tests.py --suite int --no-coverage \
  --pg-container-port 55433 -- \
  src/test/int/python/<owner>.int.test.py::test_exact_boundary
python3 tools/run_tests.py --suite unit --no-coverage -- \
  src/test/unit/python/repomap_kg/test_cli.unit.test.py -k graph_baseline
```

Exact paths and node IDs are preferred for final evidence. A pathless `-k`
selection is name-dependent and is exploratory only; if retained, pair it with
an exact path and `--no-coverage`. Do not present scoped development runs as
complete qualification evidence.

## Parallel Execution

Unit-only development runs may use pytest-xdist through the public runner:

```sh
python3 tools/run_tests.py --suite unit --jobs auto --no-coverage
```

Parallel execution requires `--no-coverage` in the current runner. Serial
coverage.py runs remain authoritative. Parallel coverage must not be reported
unless aggregation is implemented and verified honestly in a future phase.

Integration and staging parallel execution remain disabled. The integration
suite uses the MCP-RUNTIME3 containerized Postgres harness and shared
integration database state, so parallel integration execution needs a separate
isolation phase before it can be enabled honestly.

## Coverage Enhancement Work

Coverage warning cleanup belongs to explicit coverage enhancement phases, not
random feature phases.

Ordinary feature, bug-fix, and documentation phases should not chase advisory
coverage warnings unless the warning is directly related to the touched code or
the user explicitly scopes coverage cleanup into the phase.

TEST-COV0 made a coherent partial improvement but left individual unit and
integration branch coverage below the 85% advisory line. TEST-COV1 cleared the
individual branch advisory warnings with focused storage/readback and ops helper
coverage.

The long-term planned coverage target remains 90% line and branch coverage for
unit and integration runners individually. Coverage enhancement phases may treat
advisory warnings as normal work items.

## Roadmap

Completed:

1. TEST-INFRA0: documented policy and migration plan.
2. TEST-INFRA1: introduced pytest compatibility without changing thresholds.
3. TEST-INFRA2: migrated `tools/run_tests.py` to pytest while preserving the
   suite interface.
4. TEST-INFRA3: added opt-in unit parallel execution.
5. TEST-INFRA4: implemented line/branch coverage policy and changed the final
   source/test gate to the then-combined suite (now retired by REPOMAP-CI2A-R1).
6. TEST-COV0: made partial coverage improvements but did not clear individual
   branch advisory warnings.
7. TEST-COV1: cleared individual unit and integration branch advisory warnings
   through focused storage/readback and ops helper coverage.

Planned:

1. A later TEST-COV phase should reach 90% line and branch coverage for unit
   and integration individually.
2. A later integration-isolation phase may enable integration/all xdist runs if
   Postgres database, port, and filesystem state can be isolated per worker.

## Commit Message Standard

TEST-INFRA phase commits must preserve the phase id in the subject:

```text
TEST-INFRA<N>: <short summary>
```

Commit bodies should include:

- `Scope:` with what changed and important boundaries;
- `Verification:` with commands actually run;
- explicit docs-only notes when no source-code tests were run.

Do not rely on chat-only summaries for durable testing-policy audit records.

With coverage and `--report`, the canonical runner retains coverage.py
`coverage.json` beside the suite's `latest/` HTML directory before owned cleanup.
It preserves per-file executed/missing lines and branches over the unchanged
product denominator. A scoped report remains scoped evidence, including any
full-denominator threshold failure; it is not whole-population qualification.
## Retained-Python enforcement evidence

The pre-review evidence envelope retains the ADR 0064 versioned compact
`python-retention-inventory.result.json`, bound by its manifest size and SHA-256.
The console log remains capped at 200,000 bytes and begins with the enforcement
status, counts, root failure categories, and bounded examples. Live inventory
root results retain complete per-tool findings for policy evaluation. Retained
evidence includes qualification summaries and canonical counts/SHA-256 commitments
for omitted collections, plus explicit admitted regressions. Incomplete results
use a separate failure variant and cannot establish success. Unknown paths and
dependency findings remain failures. The existing 5 MiB aggregate evidence cap
still applies and fails closed when exceeded.
