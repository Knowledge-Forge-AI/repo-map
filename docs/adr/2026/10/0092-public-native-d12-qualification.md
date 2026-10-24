# ADR 0092: Public-CI Native Platform Qualification for D12 Core Candidate Images

- **Date:** 2026-10-23 (updated 2026-10-24 through `REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED11`)
- **Factual errata:** 2026-10-24, `D12HOSTED10`–`D12HOSTED11`; source names,
  recorded runtime observation, workflow facts, current README context identity,
  and guard-contract compliance (`A1`–`A4`) updated without changing the
  accepted bounded design or any hold.
- **Status:** Accepted bounded first-checkpoint design for public-CI native
  platform qualification, updated through
  `REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED11` to address state-I/O review
  findings `B1`–`B3` and advisories `A1`, `A3`–`A5` in
  [`tools/ci/d12_hosted_state.py`](../../../../tools/ci/d12_hosted_state.py),
  enforce the explicit merge-parent binding, single counted SDK adapter, and
  mandatory-step gating contracts (`A1`–`A3`), and project the bounded D12
  public-qualification tree onto public staging
  ([NAVIGATION46 D12 native qualification checkpoint](../../../../tools/ci/nav46-d12-native-qualification.md)).
  The initial `D12HOSTED1` draft was **not** accepted unchanged
  (`draft_as_written_accepted: false`), and earlier implementation checkpoints
  remained **not accepted** (`source_candidate_accepted: false`,
  `source_accepted: false`). Direct human steering (`2026-10-23T19:45:44-04:00`)
  selected the public-CI native qualification route referencing Theme Forge
  Nebular Fusion; this first checkpoint is narrowed to **AMD-first
  (`linux/amd64`) non-consuming exploration and early system-gate hold**.
  Candidate image qualification (`image_accepted: false`), ADR 0087 P3 closure
  (`P3_accepted: false`), positive application build admission
  (`application_builds_authorized_now: 0`), hosted build-ledger custody,
  same-platform system-image reuse, and two-platform same-source image
  qualification remain **not accepted** and explicitly deferred.
- **Phase:** `REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED1`; narrowed in
  `REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED2`; remediated through
  `REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED11`
  ([NAVIGATION46 D12 native qualification checkpoint](../../../../tools/ci/nav46-d12-native-qualification.md))
- **Related:**
  [ADR 0051](../08/0051-postgresql-extension-and-database-capability-architecture.md),
  [ADR 0054](../08/0054-staged-promotion-topology-and-logical-ci-gates.md),
  [ADR 0074](../09/0074-submit-admission-and-local-readback-authority.md),
  [ADR 0077](./0077-publication-bound-pgvector-candidates.md),
  [ADR 0084](./0084-extension-aware-backup-and-restore.md),
  [ADR 0087](./0087-d12-image-evidence-and-core-security-prerequisite.md),
  [ADR 0088](./0088-d12-psycopg-binary-remediation-preflight.md),
  [ADR 0089](./0089-d12-dynamic-psycopg-and-system-libpq.md),
  [ADR 0090](./0090-d12-application-go-supported-toolchain.md),
  [ADR 0091](./0091-d12-tls-p3-disposition-and-trixie-remediation.md),
  [PostgreSQL D12 Image Evidence Decision Packet v1](../../../specs/postgresql-d12-image-evidence-decision-v1.md),
  [Hosted-CI Agent Policy](../../../contrib/ci-agent-policy.md),
  [NAVIGATION46 D12 native qualification checkpoint](../../../../tools/ci/nav46-d12-native-qualification.md)

## Context

### 1. Current D12 Remediation State and Distinct Source-Identity Domains

Under [ADR 0087](./0087-d12-image-evidence-and-core-security-prerequisite.md),
[ADR 0089](./0089-d12-dynamic-psycopg-and-system-libpq.md),
[ADR 0090](./0090-d12-application-go-supported-toolchain.md), and
[ADR 0091](./0091-d12-tls-p3-disposition-and-trixie-remediation.md), RepoMap's
unaccepted candidate source in
[`release.py`](../../../../src/main/python/repomap_kg/runtime/release.py) pins:

- `POSTGRES_RELEASE_IMAGE`:
  `postgres:16.15-trixie@sha256:9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97`
- `PYTHON_RELEASE_IMAGE`:
  `python:3.12-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704`
- `GO_RELEASE_IMAGE`:
  `golang:1.26.10-bookworm@sha256:632dff7351799a5a9954a48dc06670ade72ee44e8c351cdc0e5a57af2fea21af`
- `postgres` extra in `pyproject.toml`: `psycopg[c]==3.3.6` (dynamically linked against the
  distribution-owned shared `libpq5`, never static linkage)
- `PSYCOPG_LIBPQ_VERSION = None` (numeric minimum `170000` via
  `PRODUCT_MINIMUM_LIBPQ_VERSION` in `release.py`; security/P3 disposition is
  governed separately)
- `DYNAMIC_PACKAGE_MANIFEST = MappingProxyType({})`

On 2026-10-23, following the numeric `PQlibVersion` probe repair and pre-E4
guard review, one non-consuming native `linux/arm64` E4 exploration node
(`--d12-core-image-preflight`) passed on a native `aarch64` Docker daemon:

- **Distinct source-identity domains:** The executed native `linux/arm64` E4
  command bound the 694-file D12 build-context `source_sha256` (together with
  its `recipe_sha256` and `dockerfile_sha256`), which is structurally distinct
  from a phase result-manifest digest. Neither pre-projection digest is copied
  into the public tree; public hosted execution binds the recomputed public
  D12 build-context identity recorded in
  [`tools/ci/d12_hosted_candidate.json`](../../../../tools/ci/d12_hosted_candidate.json).
- **Native `linux/arm64` E4 runtime observation:** `PQlibVersion = 180006` from
  distribution-owned shared `libpq5` `18.6-1.pgdg13+2` at
  `/usr/lib/aarch64-linux-gnu/libpq.so.5.18` (SHA-256
  `094cbe08c8c6134b91b1946e42012318728003cf2dd2fcc0ab1ee9821ba38f58`).
- **Two-stage APT custody (`A2`):** As recorded in ADR 0091's native ARM
  builder runtime observation, the disposable `python:3.12-slim-trixie`
  builder resolved 47 signed builder package rows. The subsequent gated
  runtime-subset installation occurred in that Python builder, not the
  PostgreSQL server container. Its exact 10-package subset comprised
  `libcom-err2`, `libgssapi-krb5-2`, `libk5crypto3`, `libkeyutils1`, `libkrb5-3`,
  `libkrb5support0`, `libldap2`, `libpq5`, `libsasl2-2` and
  `libsasl2-modules-db`. The shared APT prerequisite and runtime-probe owners
  verified it as an exact subset of the 47 rows before `apt-get install
  --no-download`; ADR 0091 retains the exact observed versions and custody.
- **Closure:** 0 final-closure additions on `linux/arm64` (`81` retained ELFs,
  `77` `lib-dynload` imports, `1` documented non-runtime `_tkinter` exclusion).
- **Cleanup:** Outer and inner Docker inventories restored to baseline;
  application candidate build ledger remained at `maximum_total: 0` (`0` used).

### 2. Why `linux/amd64` Was Blocked Locally and Human Route Selection

On an `aarch64` host, `linux/amd64` could not run natively because
[`d12_dependency_preflight.py`](../../../../tools/d12_dependency_preflight.py)
enforces `host_arch == expected_arch` (`x86_64` for `linux/amd64`) and rejects
emulation (`QEMU` / `rosetta` / `binfmt_misc`) under
[ADR 0089](./0089-d12-dynamic-psycopg-and-system-libpq.md).

The operator selected public CI to qualify/build platforms in their native
environments, with smoke or system testing chosen for the bounded scope, and
requested Theme Forge (`Nebular Fusion`) as a reference.

Following initial design review, the architecture was narrowed to a bounded
first checkpoint before any code edit.

### 3. Reference Facts: Theme Forge (`Nebular Fusion`) and Public RepoMap CI

1. **Theme Forge (`Nebular Fusion`) reference sizes (`A2`):**
   - `.github/workflows/native-rc.yml` (`690` lines)
   - `tools/native-rc-plan.mjs` (`100` lines)
   - `tools/native-rc-index.mjs` (`123` lines)
   Theme Forge runs native GitHub-hosted runners (`ubuntu-24.04` for `x64`,
   `ubuntu-24.04-arm` for `arm64`, `macos-15` for `darwin-arm64`,
   `windows-2025` for `win32-x64`) with explicit source-SHA binding, native
   runner architecture checks, and sealed artifact uploads.
2. **Public RepoMap unified workflow (`A1`, `A10`):**
   - `.github/workflows/repomap-release-qualification.yml` is triggered only by
     `pull_request` targeting `main` (`types: [opened, reopened, ready_for_review, synchronize]`),
     with top-level `permissions: contents: read` and workflow-level
     `concurrency` (`group: repomap-release-qualification-${{ github.ref }}`,
     `cancel-in-progress: true`).
   - Its existing gates include `source-and-export-policy`, `unit-tests`,
     `pre-review-static`, `codeql`, `sbom-security`,
     `staging-integration-gate` (`timeout-minutes: 180`), and `main-system-gate`
     (`timeout-minutes: 90`).
   - Note (`A10`): [`docs/contrib/ci-agent-policy.md`](../../../contrib/ci-agent-policy.md)
     notes that while standalone staging and main-system workflows in a
     five-workflow split do not cancel in-progress runs, the unified
     `repomap-release-qualification.yml` workflow sets
     `cancel-in-progress: true` at workflow level.

## Decision

We adopt the **bounded first-checkpoint design** (`B1`–`B8`) for public-CI
native D12 qualification, remediated and projected in
`REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED2` through
`REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED6`.

### D1 (`B1`). Concurrency Policy, Same-Repository PR Admission, and One-Execution Custody

1. **Preserve `cancel-in-progress: true`:** The public workflow's
   `concurrency.cancel-in-progress: true` is preserved unchanged in this slice.
2. **One execution spent on start:** A native D12 lane's single authorized
   execution is spent the moment the job starts, including if the run is
   cancelled by a concurrent push, times out, or fails partway through.
3. **Strict runtime admission (`prepare`):** Hosted `prepare` in
   [`tools/ci/d12_hosted_qualification.py`](../../../../tools/ci/d12_hosted_qualification.py)
   admits only:
   - `GITHUB_EVENT_NAME == "pull_request"`
   - `GITHUB_RUN_ATTEMPT == "1"` (`run_attempt == 1`; manual re-runs with
     `run_attempt > 1` are refused immediately before any Docker or SDK action)
   - Same-repository `staging -> main` pull request:
     `event.pull_request.base.ref == "main"`,
     `event.pull_request.head.ref == "staging"`, and
     `event.pull_request.base.repo.full_name == event.pull_request.head.repo.full_name == GITHUB_REPOSITORY`
   - Exact checked-out merge commit and parents:
     `CANDIDATE_SHA == GITHUB_SHA == git rev-parse HEAD`,
     `CANDIDATE_TREE == git rev-parse HEAD^{tree}`,
     `CANDIDATE_BASE_PARENT == git rev-parse HEAD^1 == event.pull_request.base.sha`,
     and
     `CANDIDATE_HEAD_PARENT == git rev-parse HEAD^2 == event.pull_request.head.sha`.
4. **No retries or superseded artifacts:** No automatic rerun, retry loop,
   `workflow_dispatch`, duplicate push campaign, or acceptance of cancelled or
   superseded-source artifacts is permitted. Live PR `head`/`base` SHAs are
   rechecked before publication and before accepting any downloaded artifact by
   exact GitHub Actions artifact ID (`A4`).

### D2 (`B2`). Fourth Literal Canonical Runner Invocation and Connected Topology Contract

1. **Fourth literal `python3 tools/run_tests.py` in the public workflow:**
   Instead of hiding `tools/run_tests.py` inside a Python wrapper, the public
   workflow adds a fourth literal canonical runner invocation in the single
   `d12-native-amd64` job ([`tools/ci/d12_native_amd64_job.yml`](../../../../tools/ci/d12_native_amd64_job.yml)).
   The public-case global runner count is amended openly from **three** to
   **four** (`unit-tests`, `staging-integration-gate`, `main-system-gate`, and
   `d12-native-amd64`), while the five-workflow split retains **three** literal
   runner invocations.
2. **Single native AMD job (`d12-native-amd64`):**
   - `runs-on: ubuntu-24.04`, `timeout-minutes: 90` (`A3`, aligned with the
     90-minute hosted `main-system-gate` envelope),
     `needs: [source-and-export-policy]` (matching the existing qualification
     workflow fan-out where downstream gates depend directly on
     `source-and-export-policy`).
   - Uses only existing pinned public actions (exact 40-hex `uses:` strings in
     `d12-native-amd64`; upstream release tags noted for reference):
     - `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (upstream `v7.0.1`)
     - `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97` (upstream `v7.0.0`)
     - `actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` (upstream `v7.0.1`)
   - Ordered steps:
     1. Checkout merge candidate (`fetch-depth: 2` so `HEAD^1` and `HEAD^2` are
        present locally, `persist-credentials: false`).
     2. Bind candidate merge identity (`id: bind`): stdlib/Git-only step that
        resolves `CANDIDATE_SHA="$(git rev-parse HEAD)"`,
        `CANDIDATE_TREE="$(git rev-parse 'HEAD^{tree}')"`,
        `CANDIDATE_BASE_PARENT="$(git rev-parse 'HEAD^1')"`, and
        `CANDIDATE_HEAD_PARENT="$(git rev-parse 'HEAD^2')"` and appends all four
        to `GITHUB_ENV`.
     3. Setup Python `3.13`.
     4. `python3 tools/ci/d12_hosted_qualification.py prepare ...` (requires
        explicit valid `GITHUB_SHA`, `CANDIDATE_SHA`, `CANDIDATE_TREE`,
        `CANDIDATE_BASE_PARENT`, and `CANDIDATE_HEAD_PARENT` without defaulting
        missing values to `HEAD`, validates PR merge/event/attempt=1, expected
        content record, native `Linux`/`x86_64` host and Docker daemon,
        recomputed `sdk_dockerfile_sha256`, `sdk_helper_sha256`, and
        `sdk_recipe_sha256`, captures `entry_baseline`, performs at most one
        counted SDK setup through a single `_counted_sdk_runner` path shared by
        both the default `test_sandbox.ensure_sandbox_image` facade and any
        injected `ensure_sdk_fn` control adapter—forwarding all subprocess
        kwargs including `timeout=1800` and recording `sdk-build-intent.json`
        only immediately before an actual `docker build` so warm hits record
        `sdk_build_attempts == 0` with `intent_recorded_before_build == False`
        and `intent_receipt_sha256 is None` while cold builds record `1`,
        `True`, and the 64-hex receipt digest—verifies the resulting
        `sdk_image_id`, owned `sdk_recipe_sha256` label, and actual inspected
        `sdk_architecture == "amd64"` without defaulting missing `Architecture`
        to `"amd64"`, captures `post_sdk_baseline` along with both
        `added_sdk_images` and `removed_sdk_images`, exports
        `D12_EXPECTED_SOURCE_SHA256` to `GITHUB_ENV`, and on any refusal or
        error persists `prepare-refusal.json` via
        [`tools/ci/d12_hosted_state.py`](../../../../tools/ci/d12_hosted_state.py)
        with the stage, redacted refusal reason, and only reached stage facts
        without executing new Docker/APT/build commands from error handling).
     5. Literal canonical runner invocation with exit-status capture:
        ```bash
        set -euo pipefail
        status=0
        python3 tools/run_tests.py \
          --sandbox \
          --suite int \
          --no-coverage \
          --jobs 1 \
          --pg-container-port 55433 \
          --d12-core-image-profile linux/amd64 \
          --d12-core-image-preflight \
          --d12-core-image-source-sha256 "${D12_EXPECTED_SOURCE_SHA256}" \
          --report-dir "${RUNNER_TEMP}/d12-native-amd64-report" \
          -- src/test/int/python/repomap_kg/runtime/d12_core_image_refresh.int.test.py::test_d12_core_image_refresh_candidate_round_trip || status=$?
        printf '%s\n' "${status}" > "${RUNNER_TEMP}/d12-native-amd64-evidence/runner-exit-code.txt"
        exit "${status}"
        ```
     6. `if: always()` `python3 tools/ci/d12_hosted_qualification.py seal ...`
        (fail-safely creates the output directory even if `prepare` refused
        before creating `state_dir`, loads `prepare-state.json` or falls back to
        `prepare-refusal.json` via `load_prepare_or_refusal_state` retaining the
        actual prepare refusal stage and reason in `seal_errors` while keeping
        unreached facts unknown, compares both added and removed outer Docker
        resources against `post_sdk_baseline` while reporting
        `entry_baseline -> post_sdk_baseline` SDK cache deltas separately,
        reads and retains every available safe partial canonical report
        `freeze.json`/`exploration.json`/`cleanup.json` via
        [`tools/ci/d12_hosted_state.py`](../../../../tools/ci/d12_hosted_state.py)
        and [`tools/ci/d12_hosted_reports.py`](../../../../tools/ci/d12_hosted_reports.py),
        projects actual canonical application boundary counts without hardcoding
        `0` or collapsing incomplete zero histories into `0`, writes
        `validation_violations` and any `seal_errors` into the redacted sealed
        evidence JSON, and exits non-zero if `prepare`, the canonical runner,
        cleanup, or partial/refused exploration failed).
     7. `if: always()` `actions/upload-artifact` with `retention-days: 14`,
        `if-no-files-found: error`, and lane/run/attempt/source-bound artifact
        name
        `repomap-d12-native-amd64-${{ github.run_id }}-a${{ github.run_attempt }}-${{ github.sha }}`.
3. **Structured connected contract validation (`A1`):**
   [`tools/ci/qualification_native_contracts.py`](../../../../tools/ci/qualification_native_contracts.py)
   and the connected CI contract owners
   ([`qualification_command_contracts.py`](../../../../tools/ci/qualification_command_contracts.py),
   [`ci_topology_contracts.py`](../../../../tools/ci/ci_topology_contracts.py),
   [`ci_topology_pr.py`](../../../../tools/ci/ci_topology_pr.py), and
   [`ci_topology.py`](../../../../tools/ci/ci_topology.py)) validate the fourth
   literal public runner invocation, its exact flags, sole node selector,
   `ubuntu-24.04` runner, `needs: [source-and-export-policy]`, 90-minute timeout
   cap, absence of `--d12-core-image-budget-ledger`, and step ordering, while
   catching shell parse `ValueError` and structurally rejecting retry/loop
   constructs (`for`, `while`, `until`, `do`, `done` only when unquoted literal
   tokens in command-leading position over `parse_shell_script(command)` and any
   nested `cmd_substitution` script, permitting quoted strings and non-command
   argument tokens), omitted/wrong/duplicate/hidden runner calls, ARM
   matrix/extras in this checkpoint, `setup-qemu-action`, and
   `setup-buildx-action` / `buildx create`.

### D3 (`B3`, `F4`). True Early System Hold Before SDK or Application Build

1. **Single reusable prerequisite guard in `tools/system/candidate_image.py`:**
   `require_release_prerequisites_resolved(arch)` runs **before**
   [`candidate_image.py`](../../../../tools/system/candidate_image.py) renders a
   Dockerfile, enters `boundary.managed_system_candidate_build()`, creates a
   `NamedTemporaryFile`, or invokes `docker build`. It enforces
   `PRODUCT_MINIMUM_LIBPQ_VERSION = 170000` (from
   [`release.py`](../../../../src/main/python/repomap_kg/runtime/release.py)),
   requires `DYNAMIC_PACKAGE_MANIFEST` to be a non-empty `Mapping` containing a
   `PlatformPackages` instance for `target_arch` (`amd64` or `arm64`) with no
   invented dict-row fallback, and delegates directly to
   `validate_package_manifest({target_arch: entry}, psycopg_libpq_version)`. Any
   unresolved or invalid prerequisite raises `SystemTestError` with `0`
   application builds started and `managed_system_candidate_image_build_count == 0`.
   Passing this guard establishes only that recipe prerequisites are populated
   and structurally valid; it is not candidate image, P3, or build-ledger
   admission.
2. **Hosted early hold step (`tools/ci/d12_system_hold_step.yml`):**
   In `main-system-gate`, `python3 tools/ci/d12_hosted_qualification.py system-hold`
   is placed **after** the existing SHA-pinned `actions/setup-python` step
   (which selects Python `3.13`) and **before** the canonical
   `python3 tools/run_tests.py --suite system` step can materialize an SDK or
   start an application build. `run_system_hold` delegates to the **same**
   reusable guard (`require_release_prerequisites_resolved`), writes a
   source-bound status report (`repomap-system-hold-refusal-v1.json`), returns `1` with the
   truthful guard refusal reason while release constants are unresolved or
   invalid, and returns `0` (`result: "prerequisites_resolved"`) when
   prerequisites resolve. While held, the normal canonical `main-system-gate`
   runner step remains present and required in the workflow; the held job exits
   non-zero/unqualified, never skip-as-pass or a budget exemption, and spends
   `0` SDK builds and `0` application builds.

### D4 (`B4`, `B8`, `D12HOSTED3-B1`). First-Failure Preservation, Canonical Refusal Labels, Verified AMD Metadata Custody, and Partial Refusal Sealing

1. **Preserve every `if not refusals:` gate and enforce canonical refusal prefixes (`B4`, `D12HOSTED3-B1`):**
   [`tools/d12_dependency_preflight.py`](../../../../tools/d12_dependency_preflight.py)
   does **not** continue into builder APT resolution or runtime probe steps after
   an earlier prerequisite or closure refusal. Every existing `if not refusals:`
   gate in `explore()` and its negative tests in
   [`d12_inner_preflight.unit.test.py`](../../../../src/test/unit/python/tools/d12_inner_preflight.unit.test.py)
   are preserved unchanged. Canonical `explore()` writes stage-prefixed refusals
   only for `KNOWN_EXPLORATION_REFUSAL_PREFIXES = ("libpq:", "trust:", "closure:", "builder:", "final:")`,
   whereas outer `except Exception as error:` blocks write `f"{type(error).__name__}: {error}"`
   (for example `PreflightRefusal: ...` from either `engine_facts` or `candidate()`).
   `validate_canonical_exploration_report` in
   [`tools/ci/d12_hosted_reports.py`](../../../../tools/ci/d12_hosted_reports.py)
   does not invent an `engine:` prefix or guess the stage of an ambiguous
   exception:
   - Any refusal not starting with `KNOWN_EXPLORATION_REFUSAL_PREFIXES` is
     preserved in the report as unqualified and appends an explicit
     validation-limitation violation
     (`ambiguous or unknown refusal stage cannot prove first-failure boundary`).
   - Refusals starting with `("libpq:", "trust:", "closure:")` forbid non-null
     `steps["builder"]`, `steps["libpq_runtime"]`, `steps["final_closure"]`, and
     `steps["candidate"]`.
   - Refusals starting with `"builder:"` allow earlier facts and forbid non-null
     `steps["libpq_runtime"]`, `steps["final_closure"]`, and
     `steps["candidate"]`.
   - Refusals starting with `"final:"` allow earlier facts (`libpq5_version`,
     `trust`, `closure`, `builder`, `libpq_runtime`) and `steps["final_closure"] is None`,
     while forbidding non-null `steps["final_closure"]` or `steps["candidate"]`.
2. **Mechanically verified AMD metadata custody (`B8`):**
   The retained OCI index, `linux/amd64` child manifest, and `linux/amd64`
   config JSON bytes and descriptor sizes were mechanically verified for all
   three pinned bases:

   | Base image | OCI index digest | `linux/amd64` manifest digest | `linux/amd64` config digest |
   | --- | --- | --- | --- |
   | `golang:1.26.10-bookworm` | `sha256:632dff7351799a5a9954a48dc06670ade72ee44e8c351cdc0e5a57af2fea21af` | `sha256:88750ccdd0f2a77fcc00a14b1a48d6409bd8ddb5d7c2dd6ec0b4a2e916daf9d9` | `sha256:0d494ea9b5863337de0dfb4f938062bf0261a919016eb162d2be26381dbadafe` |
   | `python:3.12-slim-trixie` | `sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704` | `sha256:e8a38829209aea82774882e5157e1f7c3e8c8393ff53a697b3580896e57f345c` | `sha256:a33c10a97f11005523814c6eee013986119fe41f3122f444518117536675c8e1` |
   | `postgres:16.15-trixie` | `sha256:9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97` | `sha256:f9d1e581cde3e4c8bc696b07e6f7b7aea1d41014b33a52b27990762daae61beb` | `sha256:066167ff39c2a612402ce99b734ea1cff92a9d1f2ac52f697a5f0384f0d88d6b` |

   This custody authorizes adding only
   `"linux/amd64": "sha256:0d494ea9b5863337de0dfb4f938062bf0261a919016eb162d2be26381dbadafe"`
   to `GO_CONFIGS` in `tools/d12_dependency_preflight.py` and binding observed
   runtime base config IDs and `linux/amd64` platforms under immutable
   image-index keys in [`tools/ci/d12_hosted_reports.py`](../../../../tools/ci/d12_hosted_reports.py)
   and [`tools/ci/d12_hosted_evidence.py`](../../../../tools/ci/d12_hosted_evidence.py)
   to this verified index -> child manifest -> config chain without requiring a
   Docker `RepoDigests` list to expose both the multi-arch index and child
   manifest digest simultaneously. It does not claim a native `linux/amd64` Go
   execution or any AMD package/payload observation.
3. **First native AMD campaign outcome (`B4`):**
   Because `PYTHON_PAYLOAD_EXCLUSIONS` in `python_payload.py` intentionally
   contains only `"arm64"`, the first native `linux/amd64` campaign may stop at
   the unconfigured `amd64` Python payload closure baseline (`E-f`) before
   builder APT resolution (`E-g`), runtime probe installation (`E-g`), or final
   closure (`E-h`). `seal` records that actual partial report with
   `result: "refused"` (`qualified: false`) and fails the lane non-zero. Any
   subsequent AMD payload exclusion entry and next native execution require a
   separate evidence-backed admission after reviewing the sealed E-f diagnostic
   artifact.

### D5 (`B5`, `B6`, `D12HOSTED3-B4`, `A3`, `A4`). Unknown AMD Facts and AMD-First Campaign Selection with Honest SDK Accounting

1. **Unknown AMD facts remain unknown (`B5`):**
   Native `linux/amd64` payload size and SHA-256, missing shared libraries in
   `python:3.12-slim-trixie`, resolved builder package count, installed runtime
   package set, runtime `libpq` path and `PQlibVersion`, and license/notice
   outcomes are **unobserved** prior to native hosted execution. No `arm64`
   observation is extrapolated to `amd64`.
2. **AMD-first campaign selection and single-runner SDK build accounting (`B6`, item 11, `D12HOSTED3-B4`, `A3`, `A4`):**
   - Only `d12-native-amd64` is added in this first checkpoint; `linux/arm64`
     hosted execution and positive candidate builds are not part of this slice.
   - `d12-native-amd64` permits at most `1` cold materialization of the
     unchanged outer SDK image (`repomap-test-sandbox:py313-go125-docker294-v1`),
     `1` ordinary managed test-runtime image, and `1` canonical E1/E4 node
     execution, with `0` retries.
   - `prepare` uses a single `_counted_sdk_runner` path for both the default
     `test_sandbox.ensure_sandbox_image` facade and any injected `ensure_sdk_fn`
     control adapter: it records `sdk-build-intent.json` only immediately before
     an actual `docker build` (`sdk_build_attempts == 0` with
     `intent_recorded_before_build == False`, `intent_receipt_sha256 is None`,
     and `sdk_cache_cold_built == False` on a warm hit; `sdk_build_attempts == 1`
     with `intent_recorded_before_build == True`, 64-hex `intent_receipt_sha256`,
     and `sdk_cache_cold_built == True` on a cold build, where a failed build
     still spends the `1` attempt), inspects the SDK image without defaulting
     missing `Architecture` to `"amd64"`, records `sdk_image_id`,
     `sdk_architecture`, `sdk_recipe_sha256`, `added_sdk_images`, and
     `removed_sdk_images` between `entry_baseline` and `post_sdk_baseline`, and
     never claims whole-job image parity after cold SDK setup. `seal` requires
     zero run-owned Docker residue (both `*_added` and `*_removed` empty) against
     `post_sdk_baseline` while reporting the SDK cache deltas
     (`added_sdk_images` and `removed_sdk_images`) truthfully.
   - Across a fresh public PR campaign, `d12-native-amd64` performs `<= 1` cold
     SDK setup, existing `staging-integration-gate` performs `<= 1` separate
     cold SDK setup under its existing pipeline authority, and early-held
     `main-system-gate` performs `0` SDK setups before refusing (`<= 2` campaign
     SDK setups total, `0` application builds). Actual recorded counts and
     failures take precedence over this forecast.

### D6 (`B7`). Expected Content Record (`tools/ci/d12_hosted_candidate.json`) and Two-Stage Export

1. **Frozen expected content record outside D12 build context:**
   `tools/ci/d12_hosted_candidate.json` (which resides under `tools/ci/`,
   outside D12's build-context paths) is frozen from the **final public file
   bytes** after export-specific version and documentation reconciliation and
   before committing.
2. **Independent runtime verification (`prepare`) and domain separation (`F5`):**
   Hosted `prepare` reads `tools/ci/d12_hosted_candidate.json` (failing closed
   if the file or any required digest is absent or malformed) and independently
   recomputes from the checkout:
   - D12 build-context identity via `d12.frozen_identity(repo_root, "linux/amd64")`
     (`source_sha256`, `recipe_sha256`, `dockerfile_sha256`, `context_file_count`)
   - Outer SDK Dockerfile and helper SHA-256 digests (`sdk_dockerfile_sha256`
     from `tools/test_sandbox/Dockerfile`, `sdk_helper_sha256` from
     `tools/native_apt_prerequisites.py`) and composite `sdk_recipe_sha256`
     (`sandbox_recipe_inputs` / `sandbox_recipe` for `sdk_image_tag`).
   Domain separation between a D12 694-file build-context `source_sha256` and a
   phase result-manifest digest is enforced structurally by typed role fields and
   independent recomputation against `expected_candidate_record`, with **zero**
   hardcoded pre-export hash literals in public-bound code or test fixtures.
3. **Bounded public projection:**
   Only reviewed D12 source/test prerequisites and the new CI owners/fragments
   are projected into the public staging checkout in
   `REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED6`, preserving public-only
   export/author-correction policy, public `v0.0.3` metadata, and all
   authority/debt ceilings.

### D7 (Item 12, `NB4`, `F1`, `F3`, `D12HOSTED3-B2`, `D12HOSTED3-B3`, Outer-Failure-Envelope & Partial-Report Lenses). Canonical Producer Report Schemas, Bounded State Persistence, and Fail-Safe Evidence Sealing

[`tools/ci/d12_hosted_state.py`](../../../../tools/ci/d12_hosted_state.py),
[`tools/ci/d12_hosted_reports.py`](../../../../tools/ci/d12_hosted_reports.py),
and [`tools/ci/d12_hosted_evidence.py`](../../../../tools/ci/d12_hosted_evidence.py)
validate the **exact canonical producer schemas** emitted by the maintained D12
runner owners rather than invented wrapper schemas:

1. **Canonical report contracts (`F1`, `D12HOSTED3-B2`):**
   - `freeze.json` (written in `d12_core_image_refresh.int.test.py`): top-level
     keys `{"admission", "availability", "bases", "budget", "labels", "tag"}`,
     where `admission` carries `context_file_count`, `dockerfile_sha256`,
     `node_id`, `platform`, `recipe_sha256`, `source_sha256`; `availability`
     carries `platform`, `execution`, `builder_platforms`; `bases` is keyed by
     the three pinned release image references (`POSTGRES_RELEASE_IMAGE`,
     `PYTHON_RELEASE_IMAGE`, `GO_RELEASE_IMAGE`), each mapping to
     `{"id", "platform", "config_digest_verified"}`; and `budget` carries the
     16-key `boundary.projection()` dictionary.
   - `exploration.json` (written by `explore()` in
     `tools/d12_dependency_preflight.py`): top-level keys
     `{"mode", "daemon", "build_readiness", "p3", "host_forecast_substituted",
     "admission", "bindings", "availability", "bases", "steps", "refusals",
     "result"}` with `"mode": "exploration"`, `"build_readiness": "NOT
     ESTABLISHED"`, `"p3": "inputs only"`, `"host_forecast_substituted": False`,
     and `"result"` in `{"refused", "observed"}`. `steps` contains reached keys
     from `engine`, `identity`, `libpq5_version`, `trust`, `closure`, `builder`,
     `libpq_runtime`, `final_closure`, `candidate`, and `capacity`.
   - `libpq_runtime` step record (written by `record()` and validated by calling
     the **real** `consume()` in `tools/d12_libpq_runtime_probe.py`): exact
     `RECORD_KEYS` (`schema == "repomap-d12-libpq-record-v1"`,
     `verified == "host-rechecked builder result"`, `run_id`, `api`, `native`,
     `library`, `selected`, `manifest_sha256`, `input_sha256`, `probe_sha256`,
     `helper_sha256`) validated via the real canonical `consume(lr, steps, srv, "linux/amd64")`
     where `srv` is reconstructed independently from
     `steps["candidate"]["manifest"]` (`libpq_path`, `libpq_sha256`, and
     `libpq5_version == steps["libpq5_version"]`), never copied from
     `steps["libpq_runtime"]["library"]`. In addition,
     `validate_canonical_exploration_report` verifies that both
     `d12_libpq_runtime_probe.apt.__file__` and
     `test_sandbox_images.SANDBOX_CONTEXT_SOURCES["apt_prerequisites.py"]`
     resolve to the single canonical owner `tools/native_apt_prerequisites.py`
     and match `expected_helper_sha256` and `lr["helper_sha256"]`, with
     `api >= PRODUCT_MINIMUM_LIBPQ_VERSION` (`170000`) and
     `steps["candidate"]["libpq_version"] == api == package_forecast`
     (`written_to_source == False`, `valid == True`). Per `NB4`, raw filtered
     `dpkg --verify` lines are not in `RECORD_KEYS` and are never required or
     claimed.
   - `cleanup.json` (written by `run_candidate_cleanup()` in
     `d12_core_image_cleanup.py` and `custody()` in
     `d12_core_image_refresh.int.test.py`): top-level keys
     `{"budget", "candidate_image_id", "containers", "primary", "server",
     "zero_build"}` (plus optional `"error"` only on cleanup failure), where
     `candidate_image_id is None`, `containers == "baseline_verified"`,
     `server == "removed"`, and `zero_build` maps all four `COUNTS` keys
     (`managed_system_candidate_image_build_count`,
     `product_or_build_profile_build_count`, `unmanaged_build_count`,
     `unmanaged_pull_count`) to `0`.
2. **Bounded report I/O, prepare-refusal persistence, honest counters, and outer-failure-envelope validation (`F3`, `D12HOSTED3-B3`, Outer-Failure-Envelope & Partial-Report Lenses):**
   - [`tools/ci/d12_hosted_state.py`](../../../../tools/ci/d12_hosted_state.py)
     (re-exported by `d12_hosted_reports.py`) enforces
     `MAX_SAFE_JSON_REPORT_BYTES = 8 * 1024 * 1024` (`8 MiB`) before reading
     report bytes (`status == "oversize"`, recording actual `st_size` and
     `sha256: None` without loading the file) and computes `len(raw_bytes)` and
     `sha256(raw_bytes)` before `raw_bytes.decode("utf-8")` so non-UTF-8 files
     return `status == "decode_error"` with actual `byte_length > 0` and
     `sha256` without raw content.
   - In `REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED5` and
     `REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED6` (`B1`–`B3`, `A1`, `A3`–`A5`),
     `d12_hosted_state.py` closes fail-safe state-I/O gaps without changing public APIs:
     1. **Ordinary parse and sanitization failures return or persist safe,
        unqualified error envelopes rather than escaping the failure recorder
        (`B1`, `A1`):**
        `load_safe_json_report` catches `(ValueError, RecursionError)` during
        standard `json.loads` (including deeply nested JSON within the `8 MiB`
        byte cap where Python raises `RecursionError`) and returns
        `(None, _prov("malformed_json", nbytes, digest, False), ...)` retaining
        the real `byte_length` and `sha256` provenance when read without
        claiming empty input or validity. Note (`B1`, `A1`): standard `json.loads`
        resolves duplicate raw JSON object keys by last-key wins rather than
        raising on duplicates, and recursion-limit refusal is enforced via
        Python's `RecursionError` during `json.loads`, `_validate_parsed_tree`,
        or `_apply_redact` rather than an explicit schema depth limit.
        Sanitization and JSON-serialization checks catch `_SanitizationError`
        and `Exception` (including `RecursionError` and callback exceptions) and
        return `(None, _prov("redaction_corrupted_json", nbytes, digest, True), ...)`
        without leaking unsanitized key/value content into diagnostics, while
        deliberate `BaseException` cancellation and process-exit exceptions
        (`KeyboardInterrupt`, `SystemExit`, `GeneratorExit`) are never caught.
     2. **Recursive mapping-key, list, and tuple sanitization with fail-closed
        input constraints (`B2`, `A3`):** `_apply_redact` recursively sanitizes
        mapping keys as well as values across nested mappings, lists, and tuples
        (`isinstance(value, (list, tuple))` and `isinstance(direct, (list, tuple))`,
        returning `tuple(items)` when `isinstance(value, tuple)`) so
        private-looking synthetic key or sequence data cannot survive in
        sanitized report payloads or reached-state persistence. The fail-closed
        sanitized-input constraints (`A3`) require non-empty stripped `str`
        mapping keys before and after `redact_fn`, no post-redaction key
        collisions (`new_k in out`), no non-null scalars redacted to `None`, any
        mapping or sequence remaining a mapping or sequence after `redact_fn`,
        and finite JSON values passing `json.dumps(..., allow_nan=False)`. Any
        violation raises `_SanitizationError` and yields an unqualified refusal
        (`status == "redaction_corrupted_json"`, `data is None`, `err is not
        None`) rather than silently losing evidence and qualifying. Valid
        unchanged reports remain `status == "valid"` with `redacted == False`
        and `err is None`.
     3. **Fixed public-safe refusal reason and stage fallbacks and partial
        reached-state isolation (`B3`, `A4`):** When `write_prepare_refusal_state`
        sanitizes `reason` and `redact_fn` returns `None`, empty/whitespace, a
        non-`str`, or raises an `Exception`, it never falls back to the original
        unsafe `str(reason)`; instead it persists `REDACTED_REFUSAL_REASON`
        (`"<redacted-prepare-refusal-reason>"`). Likewise (`B3`), when
        `_sanitize_stage` sanitizes `stage` and `_apply_redact` returns `None`,
        empty/whitespace, a non-`str`, or raises an ordinary `Exception`,
        `_sanitize_stage` never falls back to the raw `stage` string even when
        `raw_stage.isidentifier()` is true; instead it returns fixed `"unknown"`,
        while ordinary unchanged literal stage names return `redacted`. Each
        `REACHED_PREPARE_KEYS` entry is sanitized independently inside its own
        `try ... except Exception:` block so callback failures, key collisions,
        unusable keys, or deep recursion in one entry omit only that unsafe
        entry while retaining the safe refusal record and all safely reached
        facts, with zero Docker, APT, build, SDK, API, or runtime actions in
        error handling. As an explicit diagnostic limitation of an already
        non-qualifying refusal (`result == "refused"`), a dropped
        `REACHED_PREPARE_KEYS` section in `prepare-refusal.json` is
        indistinguishable in that file from an unreached section.
   - When `prepare_hosted_d12` refuses at any stage, it persists
     `prepare-refusal.json` (`PREPARE_REFUSAL_SCHEMA = "repomap-d12-prepare-refusal-v1"`)
     recording the stage, redacted refusal reason, and only reached stage facts
     without running new Docker/APT/build commands from error handling.
     `seal_hosted_d12` loads `prepare-state.json` or falls back to
     `prepare-refusal.json`, appending the actual prepare refusal stage and
     reason to `seal_errors` and keeping unreached facts unknown.
   - `project_canonical_boundary_counts` requires every key in
     `APPLICATION_BUILD_COUNT_KEYS` to exist in each present canonical mapping
     (`freeze.budget`, `cleanup.budget`, `cleanup.zero_build`), preserves the
     maximum positive count and records a violation when any observation is
     `> 0`, projects `0` only when all three canonical sources are present and
     strictly `0`, and projects `None` (unknown) when observations are
     incomplete and non-positive.
   - `validate_sealed_d12_evidence` in
     [`tools/ci/d12_hosted_evidence.py`](../../../../tools/ci/d12_hosted_evidence.py)
     requires `seal_errors == []` and `validation_violations == []` (both
     `list[str]` of non-empty strings), requires `application_builds` to contain
     exact keys `("application_builds", "application_candidate_builds", *APPLICATION_BUILD_COUNT_KEYS)`
     where all six values are strict integers equal to `0` and equal to
     `project_canonical_boundary_counts(freeze, cleanup)` (rejecting `None`,
     booleans, or nonzero values), and validates `sdk_materialization`
     (`sdk_image_id`, `sdk_architecture == "amd64"`, `sdk_recipe_sha256`,
     `added_sdk_images`, `removed_sdk_images`, and warm `0` vs cold `1` build
     attempt invariants).
3. **Stage 2 open design points (`A5`):**
   Positive hosted candidate image builds (`--d12-core-image-profile` without
   `--d12-core-image-preflight`), hosted build-ledger custody
   (`--d12-core-image-budget-ledger`), and same-platform system-image reuse
   between D12 qualification and `main-system-gate` remain open and require a
   later reviewed design before any positive build is authorized.
4. **Public-projection candidate identity and scoped verification (factual refresh in D12HOSTED10):**
   - Current expected public candidate record
     [`tools/ci/d12_hosted_candidate.json`](../../../../tools/ci/d12_hosted_candidate.json)
     has SHA-256 `b16312fedb3cc84ce7be6a7c4a31bde5cdc8486f54e7bea059e336185c9a757d`, with the 694-file public D12 context
     `source_sha256: 6e470c5b287e4218f8ce78f458dbc17f5d033bf87acd012a97bb99e048d3abca`,
     `recipe_sha256: 0dedb63d3a48c45df553dbe790c95363a248a7c99c368c436419f0ca1edeb392` and
     `dockerfile_sha256: 4f1654900a5598840f0a9caac6a62068f051ecad21493fed91c80ff05aa61878`.
     The expected record is outside the context and contains no commit
     self-reference. D12HOSTED10 corrects a stale README test-runtime sentence
     and recomputes only this metadata identity; it performs no image build.
   - Historical D12HOSTED6 public RED failed 8 cases with 109 passed and
     4 skipped before the connected workflow/topology projection. Its second
     public static attempt still failed with 194 raw mypy findings: 159
     existing product-dependency findings and 35 missing Docker/Psutil stub
     findings. Other scoped checks passed; this was not an overall static pass.
   - D12HOSTED8 supplied the exact existing read-only stub overlay and passed
     all seven canonical product-owner/scoped-profile/census/lineage/topology
     checks. Its first public scoped run failed three new fixture cases on
     selection ordering (969 passed, 5 skipped); after the bounded correction,
     the second run passed 972 cases with 5 skipped. D12HOSTED9's docs-only
     scoped confirmation also passed 972 cases with 5 skipped.
   - These are scoped source diagnostics. Complete independent publication
     review and final source checks remain required, and hosted/image/P3/
     two-platform/coverage acceptance remains pending. No failed attempt or
     refusal is relabeled as passing and no build ceiling is reset.

### D8. File Ownership (`REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED2`–`D12HOSTED11`)

| File path | Class | Role in `D12HOSTED2`–`D12HOSTED11` |
| --- | --- | --- |
| `tools/ci/d12_hosted_state.py` | New Python tool (`<= 400` lines, `D12HOSTED4`–`D12HOSTED6`) | Cohesive stdlib-only bounded JSON report reader (`8 MiB` pre-read cap, pre-decode byte/hash provenance, `RecursionError`/sanitizer-failure refusal, recursive key+value+tuple redaction with collision/unusable-key refusal) and fail-safe prepare-refusal state persistence (`prepare-refusal.json`, `REDACTED_REFUSAL_REASON`, `"unknown"` stage fallback) |
| `tools/ci/d12_hosted_reports.py` | New Python tool (`<= 400` lines, `D12HOSTED3`/`D12HOSTED4`) | Canonical-report validator and counter projector re-exporting `load_safe_json_report`, enforcing canonical refusal prefixes vs unknown/ambiguous refusal limitations, independent `candidate.manifest` server `libpq` reconstruction with real `consume()`, and shared `native_apt_prerequisites.py` owner verification |
| `tools/ci/d12_hosted_evidence.py` | New Python tool (`<= 400` lines, `D12HOSTED2`–`D12HOSTED4`) | Pure validator for sealed partial-refusal and positive D12 hosted evidence enforcing empty `seal_errors`/`validation_violations`, strict zero 6-key `application_builds` matching canonical observations, and warm/cold `sdk_materialization` contracts |
| `tools/ci/d12_hosted_qualification.py` | New Python tool (`<= 400` lines, `D12HOSTED2`–`D12HOSTED11`) | Stdlib `prepare` (explicit nonempty merge-parent SHA bindings, single `_counted_sdk_runner` path without `TypeError` retry fallback, `prepare-refusal.json` persistence, inspected `sdk_architecture`, `added_sdk_images`/`removed_sdk_images`), fail-safe `seal`, and reusable-guard `system-hold` CLI |
| `tools/ci/qualification_native_contracts.py` | New Python tool (`<= 400` lines, `D12HOSTED2`–`D12HOSTED11`) | Structured contract for `d12-native-amd64` job (`bind` step, `source-and-export-policy`, rejection of `if` and `continue-on-error` on mandatory `prepare`, `runner`, and `d12-system-hold` steps), quote-aware command-position loop rejection, runner invocation, and post-`setup-python` `system-hold` |
| `tools/ci/d12_native_amd64_job.yml` | New YAML fragment | Maintained `d12-native-amd64` job fragment with `bind` step and literal `python3 tools/run_tests.py` |
| `tools/ci/d12_system_hold_step.yml` | New YAML fragment | Maintained early `system-hold` step fragment placed after `setup-python` and before `run_tests.py --suite system` |
| `tools/system/candidate_image.py` | Existing Python tool (`<= 400` lines) | Reusable `require_release_prerequisites_resolved` guard (`PRODUCT_MINIMUM_LIBPQ_VERSION = 170000`, `PlatformPackages`/`validate_package_manifest`, pre-R42 formatting preserved) |
| `tools/d12_dependency_preflight.py` | Existing Python tool (`<= 400` lines) | Verified `linux/amd64` `GO_CONFIGS` digest; all `if not refusals` gates preserved |
| `tools/ci/qualification_command_contracts.py` | Existing Python tool (`<= 400` lines, `D12HOSTED2`–`D12HOSTED6`) | Connected native D12 runner invocation contract, `ValueError` handling, and quote-aware command-position loop rejection |
| `tools/ci/ci_topology_contracts.py` | Existing Python tool (`<= 400` lines) | Connected native D12 job/marker constants |
| `tools/ci/ci_topology_pr.py` | Existing Python tool (`<= 400` lines) | Openly support 4 literal runner uses in public workflow with native job validation; keep 3 in five-workflow split |
| `tools/ci/ci_topology.py` | Existing Python tool (`<= 400` lines) | Re-export and connect native D12 topology checks |
| `src/test/unit/python/tools/ci/d12_hosted_workflow_fixture.py` | New Python test helper (`<= 400` lines, `D12HOSTED3`) | Tracked public-safe baseline workflow fixture and builder |
| `src/test/unit/python/tools/ci/d12_hosted_fixtures.py` | New Python test helper (`<= 400` lines, `D12HOSTED2`–`D12HOSTED4`) | Schema-faithful canonical synthetic fixtures (`SYNTHETIC_SDK_IMAGE_ID` 64-hex digest, `sdk_image_id`, `sdk_architecture`, `sdk_recipe_sha256`, `added_sdk_images`, `removed_sdk_images`) and real producer-to-consumer seam helpers |
| `src/test/unit/python/tools/ci/d12_hosted_state.unit.test.py` | New unit test owner (`<= 400` lines, `D12HOSTED4`–`D12HOSTED6`) | Pure unit tests for `load_safe_json_report` (`8 MiB` oversize pre-read refusal, non-UTF-8 `decode_error` byte/hash provenance, deep parse/sanitizer `RecursionError`, recursive key+value+tuple redaction, key collision/unusable-key refusal, `BaseException` propagation, `valid` report compatibility) and fail-safe `write_prepare_refusal_state` / `load_prepare_or_refusal_state` (`REDACTED_REFUSAL_REASON` reason fallback, `"unknown"` stage fallback, tuple reached-state redaction, callback failure isolation) |
| `src/test/unit/python/tools/ci/d12_hosted_reports.unit.test.py` | New unit test owner (`<= 400` lines, `D12HOSTED3`/`D12HOSTED4`) | Pure unit tests for canonical `freeze`/`exploration`/`cleanup` validation using real `d12_libpq_runtime_probe.consume` (zero monkeypatch stubs), independent `candidate.manifest` server `libpq` verification, shared `native_apt_prerequisites.py` owner proof, `final:`/`builder:`/unknown refusal rules, and partial counter projection |
| `src/test/unit/python/tools/ci/d12_hosted_qualification.unit.test.py` | New unit test owner (`<= 400` lines, `D12HOSTED2`–`D12HOSTED4`) | Unit tests for `prepare` (single counted-runner warm/cold SDK path, `prepare-refusal.json` persistence, inspected `Architecture`, `added_sdk_images`/`removed_sdk_images`), fail-safe `seal`, `system-hold`, and real child-interpreter `-I -S -B` CLI execution |
| `src/test/unit/python/tools/ci/d12_hosted_admission.unit.test.py` | New unit test owner (`<= 400` lines, `D12HOSTED11`) | Unit tests for explicit nonempty merge-parent SHA bindings (`CANDIDATE_BASE_PARENT`, `CANDIDATE_HEAD_PARENT`, `GITHUB_SHA`, `CANDIDATE_SHA`, `CANDIDATE_TREE`) refusing before Docker/SDK work and single-call counted `ensure_sdk_fn` adapter without `TypeError` retry fallback |
| `src/test/unit/python/tools/ci/d12_hosted_evidence.unit.test.py` | New unit test owner (`<= 400` lines, `D12HOSTED2`–`D12HOSTED4`) | Unit tests for partial-refusal and positive hosted evidence validation including outer-envelope `seal_errors`/`validation_violations`/`application_builds` and warm/cold `sdk_materialization` negative controls |
| `src/test/unit/python/tools/ci/qualification_native_contracts.unit.test.py` | New unit test owner (`<= 400` lines, `D12HOSTED2`–`D12HOSTED11`) | Unit tests for `d12-native-amd64` (`bind` step), quote-aware command-position loop checks, mandatory-step `if` and `continue-on-error` rejection across `d12-system-hold`, `prepare`, and `runner`, and post-`setup-python` `d12_system_hold_step` contracts |
| `src/test/unit/python/tools/system/system_candidate_image.unit.test.py` | Existing unit test owner (`<= 400` lines) | Early prerequisite guard positive (`PlatformPackages`/`DebPackage`) and negative refusal tests proving zero Docker builds |
| `src/test/unit/python/tools/d12_inner_preflight.unit.test.py` | Existing unit test owner (`<= 400` lines) | Preserve first-failure stop tests and verify `linux/amd64` `GO_CONFIGS` binding |
| `src/test/unit/python/tools/ci/qualification_command_contracts.unit.test.py` | Existing unit test owner (`<= 400` lines, `D12HOSTED2`–`D12HOSTED6`) | Connected command contract tests using tracked workflow fixture, shell parse error, and quote-aware command-position loop rejection |
| `src/test/unit/python/tools/ci/ci_topology.unit.test.py` | Existing unit test owner (`<= 400` lines) | Connected topology tests using tracked workflow fixture for 3-runner and 4-runner native lane contracts |
| `tools/ci/python_retention_inventory.json` | Existing metadata inventory | Append-only clean `tools` and `test_owners` entries and cohorts for the new Python files |
| `tools/ci/nav46-d12-native-qualification.md` | Public qualification checkpoint | Public checkpoint exit record for `REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED8` |

## Carried Holds and Invariants

1. **Carried holds (`NB3`–`NB8`):**
   - `NB3` (`tools/test_sandbox/Dockerfile` `apt-get update && apt-get install`
     pattern) remains open outside this scope.
   - `NB4` (`verify_installed_packages` stores only `RECORD_KEYS` and omits raw
     filtered `dpkg --verify` lines) remains a carried limitation; no raw
     filtered-line retention claim is made.
   - `NB5` (incumbent comparison inventory gap) remains open under explicit
     owner **Samuel Leighton Lair**.
   - `NB6` (`PSYCOPG_LIBPQ_VERSION = None`, `DYNAMIC_PACKAGE_MANIFEST = MappingProxyType({})`),
     `NB7` (native `linux/amd64` unobserved), and `NB8` (final candidate builds
     and P3 classification unexecuted) remain in effect.
2. **Release and budget invariants:**
   - Dynamic-only `psycopg[c]==3.3.6` (`libpq.so.5`, never `libpq.a`).
   - Application candidate build ledger remains at `maximum_total: 0` (`0` used)
     under the two-total (`1` `linux/amd64` + `1` `linux/arm64`), no-retry
     ceiling.
   - Coverage aims (`87/87` unit, `82/82` integration) and hard gates (`85/85`
     unit, `80/80` integration) and ADR 0051 D15 / live deployment exclusions
     remain unchanged.

## What Would Prove This Wrong

1. **GitHub-hosted `ubuntu-24.04` runner or daemon incompatibility:** If the
   hosted `ubuntu-24.04` runner does not provide a native `x86_64` Linux kernel
   and `x86_64` Docker daemon capable of running `--sandbox` and inner
   containerized preflight without emulation, `prepare` or inner `engine_facts`
   will fail closed.
2. **90-minute lane timeout insufficiency (`A3`):** If cold outer SDK
   materialization (`repomap-test-sandbox:py313-go125-docker294-v1`), inner base
   image pulls, test-runtime build, and inner exploration exceed 90 minutes on
   `ubuntu-24.04`, the single execution will time out and spend the lane
   without producing a complete inner report.
3. **Public export build-context divergence (`B7`):** If any public export step
   modifies one of the five declared D12 build-context roots (`pyproject.toml`,
   `README.md`, `src/main/python`, `src/main/resources`, `src/main/go`) after
   `tools/ci/d12_hosted_candidate.json` is frozen, `prepare` and
   `d12.frozen_identity` will refuse on `source_sha256` mismatch before the
   test node runs.
4. **Unexpected AMD base or APT metadata drift:** If the official registry
   manifests or configs resolved on the hosted runner do not match the
   verified `linux/amd64` manifest/config digests, inner `engine_facts` or
   hosted evidence validation will refuse.
5. **Hidden application build path:** If any caller in `main-system-gate` or
   `candidate_image.py` could reach `boundary.managed_system_candidate_build()`
   or `docker build` before `require_release_prerequisites_resolved()` runs, the
   zero-application-build invariant would be violated; unit tests pin this order
   directly.
