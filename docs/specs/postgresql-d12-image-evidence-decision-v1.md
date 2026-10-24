# PostgreSQL D12 Image Evidence Decision Packet v1

Date: 2026-10-22. Phase: `REPOMAP-PRODUCT6-NAVIGATION42-CI62-D12DESIGN1`
([the D12 native qualification companion note](../../tools/ci/nav46-d12-native-qualification.md)).
Status: **D12-A selected by the operator on 2026-10-22; see the
[approval record](#operator-approval-record).** Architecture:
[ADR 0087](../adr/2026/10/0087-d12-image-evidence-and-core-security-prerequisite.md),
accepted for D12-A only. Apart from that record, the text below is the packet
as approved, at SHA-256
`53785f4568b0a64dc908eed62b59548ac8ec6d77fcccf7673dca2ee49ecfcc84`. As
originally written it approved nothing; its "proposed" and "not granted"
wording describes the state before the decision. No dependency, image,
platform or extension is admitted by the selection itself. No part of D12 is
complete.

## Operator approval record

On 2026-10-22 the operator replied "Approve D12-A + bounded build-test
authority (Recommended)", selecting the
[recommended combined selection](#recommended-combined-selection).
`REPOMAP-PRODUCT6-NAVIGATION43-D12CORE1` records it before any source change.

| Item | Decision |
| --- | --- |
| D12-A core 16.15 refresh | **Approved**, pinned only by index `sha256:d81f7b51697014367236d07ec58b54153fc28f828b72bf247fe5c7487520bcb0` |
| Application-client path | **Approved:** one-owner build-test authority, the first execution route under required executed evidence |
| Candidate builds | At most one per platform (linux/amd64, linux/arm64), two in total, no automatic retry. Existing approved sandbox caches are a separate class |
| Test policy | Only the named new integration owner, its support module and the runner admission and population plumbing it needs. The twelve deferred build-profile nodes, their refusals and every debt or coverage ceiling stay unchanged. TEST-HYGIENE3C stays deferred |
| Complete local suites | **Not authorized** |
| D12-AB, D12-B and the P6 server-image choice | **Not selected**; still open |
| D15, pgvector production admission, live deployment | **Not authorized** |
| Image, platform and CVE qualification | **Not granted.** Requires executed evidence, P3 classification and written dispositions |
| Inherited findings and missing incumbent inventory | **Pending** written operator disposition under ADR 0087 P3 |
| Hosted triggers and public ref changes | **None** in this phase |

The selection approves producing D12-A evidence. It does not approve its
results.

**Post-approval P3 hold (2026-10-22T14:04Z).** After the approval, the parent
recorded a new version-based finding against the unchanged bundled libpq.
[CVE-2026-6477](https://www.postgresql.org/support/security/CVE-2026-6477/) is
fixed in libpq 17.10 and 16.14, with a supplier CVSS 3 score of 8.8. The pinned
`psycopg[binary]` 3.2.12 bundles libpq 170006 (17.6). The system libpq is a
separate copy and is unobserved, as are actual loading and reachability. Under
P3 this is a runtime-component `affected` finding of high severity, and
changing the psycopg pin is outside D12-A. The parent therefore set the
candidate build budget to zero, `STOP_PENDING_OPERATOR_DISPOSITION`.
Implementation, unit and review work may finish. No candidate build may start
until the operator writes a disposition: accept with the finding unresolved and
its owner named, authorize a separate remediation, or refuse.
At 14:35Z the operator chose a separate remediation: exact Psycopg 3.3.6
(parent evidence). That remediation is outside D12-A and this phase and is not
implemented here. The candidate budget stays at zero for this source, whose
bundled libpq is still 17.6.

**Remediation preflight (NAVIGATION44).**
[ADR 0088](../adr/2026/10/0088-d12-psycopg-binary-remediation-preflight.md)
records that approval and its conditional boundary. The three approved 3.3.6
wheels bundle libpq 18.6, outside the CVE-2026-6477 range by static version.
They also graft distribution libraries: CentOS 7 packages on amd64, and
AlmaLinux 8 packages on arm64, including OpenSSL 1.1.1k. They ship no notices
for those components. CentOS Linux 7 ended life on 2024-06-30, and public
OpenSSL 1.1.1 support ended on 2023-09-11. The required fixed, supported and licensed closure is
not established, so the pin stays at 3.2.12/17.6 and the hold continues. The
operator's next choice is listed in ADR 0088.

**Dynamically linked C Psycopg (NAVIGATION45).** The operator then approved
choice A: exact `psycopg[c]==3.3.6`, dynamically linked to the
distribution-owned shared libpq, and never static linkage
([ADR 0089](../adr/2026/10/0089-d12-dynamic-psycopg-and-system-libpq.md)). The source now pins it, and the release recipe builds it
against the PostgreSQL base's own `libpq5` with no `/usr/lib` overlay. The
per-platform package manifest and the base's libpq version are not yet
observed, so the rendered recipe refuses before any package or build-backend
step, and the non-consuming platform preflight refuses both platforms
([the D12 native qualification companion note](../../tools/ci/nav46-d12-native-qualification.md)). No candidate was built; the budget stays held at zero
and P3 and the missing incumbent inventory remain open.

**Application Go 1.26.10, Trixie TLS remediation, native ARM E4 observation,
and public-CI route selection (NAVIGATION45 / NAVIGATION46, 2026-10-22 to
2026-10-23).** On 2026-10-22 the operator approved exact application builder
`golang:1.26.10-bookworm@sha256:632dff7351799a5a9954a48dc06670ade72ee44e8c351cdc0e5a57af2fea21af`
and one bounded native `linux/arm64` component proof
([ADR 0090](../adr/2026/10/0090-d12-application-go-supported-toolchain.md); the
campaign ran once and is spent). After native `linux/arm64` E2 observed Bookworm
`libssl3` `3.0.20-1~deb12u2` affected by High / CISA CVSS 3.1 8.2
`CVE-2026-84782`, the operator approved Choice A on 2026-10-23
([ADR 0091](../adr/2026/10/0091-d12-tls-p3-disposition-and-trixie-remediation.md)):
bounded remediation to
`postgres:16.15-trixie@sha256:9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97`
and
`python:3.12-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704`
(supplier-fixed `libssl3t64` `3.5.7-1~deb13u3` in both bases), with the
unresolved incumbent comparison inventory gap recorded under **Samuel Leighton
Lair**. Following the parent-accepted numeric `PQlibVersion` probe amendment and
pre-E4 guard review, one parent-admitted non-consuming native `linux/arm64` E4
exploration node (`--d12-core-image-preflight`) passed on the frozen D12
build-context `source_sha256` (with source-domain separation documented in
[ADR 0092](../adr/2026/10/0092-public-native-d12-qualification.md#1-current-d12-remediation-state-and-distinct-source-identity-domains)),
observing runtime `PQlibVersion = 180006` from distribution-owned
shared `libpq5` `18.6-1.pgdg13+2`
(`/usr/lib/aarch64-linux-gnu/libpq.so.5.18`, SHA-256
`094cbe08c8c6134b91b1946e42012318728003cf2dd2fcc0ab1ee9821ba38f58`), resolving
47 signed builder package rows by index acquisition and simulation, selecting
and installing 10 runtime package rows in the gated install, with 0
final-closure additions and 81 retained ELFs / 77 `lib-dynload` imports
preserved ([the D12 native qualification companion note](../../tools/ci/nav46-d12-native-qualification.md)).
On 2026-10-23 direct human steering selected **public CI** to qualify/build
platforms in their native environments referencing Theme Forge Nebular Fusion
([ADR 0092](../adr/2026/10/0092-public-native-d12-qualification.md),
[the D12 native qualification companion note](../../tools/ci/nav46-d12-native-qualification.md)),
answering and superseding the prior local-native-environment operator question.
The human authorized the hosted route; after independent review of the initial
draft (`INDEPENDENT-DESIGN-REVIEW` SHA-256
`f53dc43e84c89a7b93c9386afadb59b5f9214fc0d19a70972f1fb0bb59e955e2`), the
parent accepted the narrowed bounded first-checkpoint hosted architecture
(retained design review records) in ADR
0092 before private-readiness implementation, and after independent review of
the initial `D12HOSTED2` candidate (`INDEPENDENT-IMPLEMENTATION-REVIEW` SHA-256
`63c0403dfe0b7470f8e4404823b7f222d575e7c29aaadb94e10fc45f0b558ead`), admitted
one bounded source correction in `D12HOSTED3` (retained remediation admission records).
`PSYCOPG_LIBPQ_VERSION = None`,
`DYNAMIC_PACKAGE_MANIFEST = {}`,
the held `maximum_total: 0` (`0` used) application ledger, the
two-total/one-per-platform/no-retries ceiling, final-image P3 classification and
live/D15 exclusions remain unchanged.

## Current boundary

- Production code pins PostgreSQL **16.14** on
  `postgres:16-bookworm@sha256:92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55`
  ([`release.py`](../../src/main/python/repomap_kg/runtime/release.py)) at the
  time this packet was written. That
  is the current as-built incumbent. While the unaccepted candidate source in
  `release.py` now pins the ADR 0090 / ADR 0091 Choice A digests pending
  qualification, the 16.14 Bookworm image stays the accepted incumbent baseline
  until a reviewed replacement is accepted.
- [CI62](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/39772826111)
  qualified the public core candidate on that incumbent (`EXECUTED_PASS`).
  The hosted SBOM job scans the source tree, not an image. CI62 is therefore not
  D12 image evidence.
- Optional pgvector testing uses a disposable Alpine-based local image under
  [ADR 0077](../adr/2026/10/0077-publication-bound-pgvector-candidates.md). That
  is test authority only. ADR 0051 D15 production admission remains refused.

## Exact current evidence

### Registry metadata (observed 2026-10-22T13:10:07Z)

Metadata only: zero layers downloaded, zero Docker operations, no signature or
attestation checked and no package inventory inferred. Repository
`docker.io/library/postgres`.

| Label | Reference | OCI index digest |
| --- | --- | --- |
| Incumbent | pinned digest | `sha256:92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55` |
| Proposed | tag `16.15-bookworm` | `sha256:d81f7b51697014367236d07ec58b54153fc28f828b72bf247fe5c7487520bcb0` |

| Label | Platform | Child manifest digest | Config digest | Reported PostgreSQL package |
| --- | --- | --- | --- | --- |
| Incumbent | linux/amd64 | `sha256:c95fd5346040eba2de3c435e14874af18f5d681fb5848d4f081dbead0878af28` | `sha256:67d1da22f4037b29cdd93e03d870a4a1c4d079358367d0cbc56459e52cde205e` | `16.14-1.pgdg12+1` |
| Incumbent | linux/arm64/v8 | `sha256:e7930dfbd285106b85cb3fd1d335744f53552d60ee09cb7f64dbe7b672ea12b4` | `sha256:c41393fce887eaa1a5d57b38f42f9bb1e79a2c7a80bb7c27a57ba1c0e16796c5` | `16.14-1.pgdg12+1` |
| Proposed | linux/amd64 | `sha256:e92e17ca202da4bb205f6f4a6c8cb30539edfbaa04987b506630f5d5851ff3c8` | `sha256:392c708576858a9a583a1b937503a99df57ca5dae63890748f4d0f2fc848abc6` | `16.15-1.pgdg12+2` |
| Proposed | linux/arm64/v8 | `sha256:2b429c90204d3dc581371d2ce267ffb0aeeddf4968e176de5003037b4d0de8a9` | `sha256:7a453af3765f0df89f869030d70b1aa5d79f68e33ba80ea3a8671d68cb259be0` | `16.15-1.pgdg12+2` |

Each platform reported 14 layers, none downloaded. The proposed digests are
**observed proposals**. They are not admitted dependencies, a platform
qualification or a package inventory. The tag is only how they were found.

### Primary-source findings (observed 2026-10-22)

| Source | Finding | Limit |
| --- | --- | --- |
| [CVE-2026-16239](https://www.postgresql.org/support/security/CVE-2026-16239/) | Core-server cursor/portal type confusion. Versions before 16.15 affected, fixed 2026-08-13 | Version-based; incumbent reports 16.14 |
| [CVE-2026-19385](https://www.postgresql.org/support/security/CVE-2026-19385/) | `pg_dump` heap buffer overflow. Versions before 16.15 affected, fixed 2026-08-13 | Packaged `pg_dump` is in the release contract |
| [16.15 release notes](https://www.postgresql.org/docs/release/16.15/) | Security fixes; possible configuration/data adjustments | Minor compatibility is not qualification |
| [Versioning policy](https://www.postgresql.org/support/versioning/) | 16.15 is the current 16 minor; major 16 supported to 2028-11-09 | Upstream recommendation, not RepoMap evidence |
| [Debian bookworm](https://www.debian.org/releases/bookworm/) | LTS, limited architectures, to 2028-06-30 | Not per-package coverage |
| [pgvector issue 1036](https://github.com/pgvector/pgvector/issues/1036) | CVE-2026-103484 affects 0.8.6 and below, fixed 0.8.7 | One advisory; not whole-image safety |
| [pgvector advisories page](https://github.com/pgvector/pgvector/security/advisories) | No published advisory listed | Absence is not evidence; see issue 1036 |
| [pgvector 0.8.7 control file](https://raw.githubusercontent.com/pgvector/pgvector/f37c13f68b57d2c3472b2214fbcff699d6d34876/vector.control) | Backend module `$libdir/vector`; no declared extension dependency | Native class comes from ADR 0077, not the control file alone |
| [pgvector 0.8.7 license](https://raw.githubusercontent.com/pgvector/pgvector/f37c13f68b57d2c3472b2214fbcff699d6d34876/LICENSE) | PostgreSQL license; notices and disclaimer must be retained | No whole-image license conclusion |
| [pgvector 0.8.7 changelog](https://raw.githubusercontent.com/pgvector/pgvector/f37c13f68b57d2c3472b2214fbcff699d6d34876/CHANGELOG.md) | 0.8.7 released 2026-10-01; fixes an IVFFlat build overflow | Earlier fixes have their own version contexts |

The statement "the incumbent predates the fix" is a version-based risk. It is
not a tested exploit, a reachability claim, or a complete package-CVE
determination for either image.

### Source bindings (SHA-256 of file bytes, read 2026-10-22)

| Path | SHA-256 | Fact used |
| --- | --- | --- |
| `src/main/python/repomap_kg/runtime/release.py` | `5898d257d381383885920f5cfb340b0db50e2d1752848d564c2bae674f72338f` | Version, image and client-path pins |
| `src/main/python/repomap_kg/runtime/commands.py` | `963ef941b0f78f54ac34239ae4b4fdfb5be4083879b3ec20c8add1b1ecc5e201` | `render_server_dockerfile`, `/usr/local` and `/usr/lib` overlay, version assertions |
| `src/main/python/repomap_kg/runtime/compose.py` | `7349d8554ed966a627d5a107826adfb55879cc68a420c47c2dfef838e52254ea` | Server service runs the pinned official image; container-internal application services; `--locale=C`; bind-mounted data; `pg_isready` healthcheck |
| `src/main/python/repomap_kg/runtime/backup_commands.py` | `b38a1cc5c60d401c7aa7df2a09acc8b7db6c0e3357a070f06428ee5749d50859` | Packaged `psql`/`pg_restore` run in the application image or through `docker exec` in the server container |
| `src/main/python/repomap_kg/runtime/backup_records.py` | `ce6253c689a0a6bb2760f2f8f15bf43b4e3663014361211f4df6260d50fd7519` | Packaged `pg_dump` in the same two modes |
| `pyproject.toml` | `b5a1aab4b79a1e0b4a6c014ff81c2d52a6edd453fe825610a1abaee9d45b2c22` | `psycopg[binary]==3.2.12` |
| `docs/legal/third-party-notices.md` | `d07c1be52a11869f6f01a07a7c8aa2fcaa1f0554f20468d5ec03b4adb1537cd7` | Bundled libpq 17.6 and 16.14 client notices |
| `tools/pgvector_test_source.json` | `0edce752f9a6256993916c12738c88f775faddb6feb080e0fe37a4472430c59f` | pgvector 0.8.7 source, archive digest, test and production base facts |
| `tools/runner_pgvector_profile.py` | `813817ac5fe93812377a0bb067d0203c225cea46d658d24da8d25bee6ac70ec0` | Archive digest verification |
| `tools/runner_sandbox_assets.py` | `637024428cb2f7e61570dd9ea5476eeaed6134ecf44a7eafcb28e4b844aca64d` | Mutable local pgvector test tag and recipe |
| `tools/system/candidate_image.py` | `f512b5394bc7db60d63949154545cd72644a76f48fe765eb5fd60a7a4abb1437` | System candidate: host architecture only, `--pull=false`, config ID check |
| `tools/test_sandbox_images.py` | `7a49952eeea8b03cd8cfcdc34b51f275e741cbfeabe571f93fe874549a6de851` | Sandbox image cache keyed by recipe digest |
| `tools/test_sandbox_contract.py` | `c1f760afec52bf0b6ec78889bc3bbf47fcbb4d6151a270fabfd493019bde0017` | Alpine test pin; production pin used by the sandbox |
| `src/test/support/python/repomap_test_support/postgres_container_config.py` | `ac96a6c87cd0245ee5646ad825d7349353720de4bee2c45d7a86bc85df1b8c89` | Harness default is the Alpine test pin |
| `src/test/support/python/repomap_test_support/postgres_container.py` | `6e49e42d34cbebcc7890fdeacf4c8761a2fcb347d519b851703aa28882064916` | Harness image resolution; explicit image override; `--pull=never` |
| `src/test/support/python/repomap_test_support/resource_test_images.py` | `8f81a75e0fb8164390de910e49ccc024fcd68eceac987a4a6918603ea00c8a25` | Context-free, single exact-base ephemeral build API with exact cleanup |
| `src/test/support/python/repomap_test_support/build_profile_debt.py` | `673f848528bf7f39eb14d0309e3a19d4591e406cb9bfcb5611213ae584db43be` | Real-build tests fail closed pending TEST-HYGIENE3C; deferred node registry |
| `src/test/unit/python/tools/test_runner_safety3_build_policy.unit.test.py` | `93a1dd88eb984ec8ed7b0e9ed039dced3f62b1699863dd065ee0c142dc6a49eb` | Deferred build-profile registry size pinned at 12 |
| `src/test/unit/python/repomap_kg/runtime/arch7f_release_resources.unit.test.py` | `e3570a02674fef3a13f0a586377b43a88f31e9b9c47e2f0adee30109832b4c00` | Incumbent index digest hard-coded twice |
| `docs/specs/as-built-architecture.md` | `11ac3718942b6834267ff9f49b1da53b7a2c48a4cda7ebfe6aa3a22e5f6b2e95` | As-built runtime image states PostgreSQL 16.14 and bundled libpq 17.6 |
| `src/test/int/python/repomap_kg/runtime/d9_extension_restore_requalification.int.test.py` | `fcf4570f55e157e0ff26df7adb927114554c87447655452d2ce41dd876e00b94` | States both its images run 16.14 |
| `tools/smoke/lifecycle.py` | `05e00bece138a61e1270a530b3b644657a1cbbd409ad9f2de3edb57317af6409` | Smoke uses the production pin |
| `tools/system/compose_topology.py` | `d173d3ef30c14f1d52a57ad15f13d84c4e79c4144ec1b8e1781fbe07e071074f` | System topology uses the production pin |
| Public `.github/workflows/repomap-release-qualification.yml` at public staging | `e63e544c1268ac3639c684894cd614f54537c2ba2a5f440fd81af1d0ff56de70` | SBOM job scans `path: "."` with a `high` severity cutoff |

The first three files and `tools/system/candidate_image.py` have identical bytes
in public staging. A later implementation must re-bind every changed file.

## Alternatives

| Option | What it does | Security | Change size and risk | Disposition |
| --- | --- | --- | --- | --- |
| **D12-0** retain incumbent | Keep 16.14. Record the two version-based findings as unresolved | Both findings remain | None now. Every later extension image or D15 record inherits an unsafe baseline | Viable as a temporary operator choice only. Not an acceptable D12 baseline |
| **D12-A** core 16.15 refresh and qualification | Move only the core base to the exact proposed index, then inventory and qualify | Addresses the two advisories if the actual binaries prove 16.15 | One base change; attributable | **Recommended first** |
| **D12-AB** combined core and pgvector candidate | Refresh the base and build an extension-enabled production-base image at once | Same core result plus a native extension | Two unproven deltas in one result. Larger review surface | Explicitly deferred |
| **D12-B** extension-enabled final image evidence | After D12-A, build and inventory the extension-enabled production-base image | Adds pgvector to the inventory | Separate decision on a qualified core. First needs the explicit server-image choice in ADR 0087 P6, because the Compose server runs the unmodified official image | Later; not proposed for approval now |

## Proposed D12-A authority (for operator approval, not granted)

D12-A is independently selectable. Approving it changes the core base pin, but
it does not approve D12-B, D15, any extension or product-capability default, or
any hosted trigger.

### Permitted change

- Change the core PostgreSQL runtime version and base to 16.15, pinned **only**
  by index `sha256:d81f7b51697014367236d07ec58b54153fc28f828b72bf247fe5c7487520bcb0`.
  The reference text should name the tag that was actually resolved
  (`16.15-bookworm`). The digest is the identity.
- Related source-fact consistency: `POSTGRES_RELEASE_VERSION`, the production
  pin in `tools/test_sandbox_contract.py`, and the
  `production_postgres_base_image` field of `tools/pgvector_test_source.json`.
  The pgvector version, tag, commit, archive digest and test base fields stay
  unchanged.
- Documentation, including the PostgreSQL client and libpq statements in
  [`docs/legal/third-party-notices.md`](../legal/third-party-notices.md) and
  the runtime-image statement in
  [`as-built-architecture.md`](as-built-architecture.md).
- Test expectations that the version change directly affects. Candidates to
  inspect are the `16.14` literals in `system_candidate_image.unit.test.py`,
  `gate_contract_main_system.unit.test.py` and `d9_final_boundaries.unit.test.py`,
  and the incumbent index digest hard-coded twice in
  `arch7f_release_resources.unit.test.py`. Each must be checked for production
  versus test-image meaning before it changes. The implementation assignment
  names each change.
- The Alpine test pin and the pgvector test image keep their existing ADR 0077
  authority. Refreshing them is not part of D12-A. Their `16.14` facts stay
  unchanged, including the literals in `pgvector_profile.unit.test.py` and
  `pgvector_materializer.unit.test.py` and the D9 requalification owner's
  docstring. The resulting test/production minor-version skew must be disclosed.
- One new integration owner,
  `src/test/int/python/repomap_kg/runtime/d12_core_image_refresh.int.test.py`,
  and one support module,
  `src/test/support/python/repomap_test_support/d12_core_image.py`. Together
  they exercise the candidate server **and** the actual application-image client
  paths, using only existing harness APIs and dependencies and exact owned
  resources. They add no other owner, test-policy change, dependency or
  production behavior beyond the accepted pin and version change. Feasibility
  limits are listed under required executed evidence.

Not permitted: live deployment, extension installation, a vector-enabled
default, any new capability or feature, schema change, Python, Go, psycopg,
setuptools, typing-extensions or package-manager pin changes, lock changes,
unrelated libraries, toolchains or scanners, and workflow changes.

### Materialization and network

- Build at most one core application-image candidate per platform:
  linux/amd64 and linux/arm64, **two candidate builds in total**. The current
  system candidate builder targets the host architecture only, so a second
  platform needs an available executor. An unavailable platform is **blocked**
  for that platform, not inferred to pass.
- Candidate-owned resources are named explicitly and cleaned exactly. There is
  no automatic retry of a failed build and no cleanup of foreign resources.
  Ordinary test-sandbox caches keep their existing authority.
- Network access is limited to the exact approved immutable base, by index and
  child digest, and to the build inputs already selected by current pins. A
  digest that changes, fails to resolve or fails verification stops for
  disposition.
- For each platform, record the source content digest, the recipe text digest
  and build arguments, the base index and child digests, and the output image
  config ID.

### Inventory and classification

For each platform, inventory both the pinned PostgreSQL service image and the
built application image as they actually are:

- actual binary paths and versions of `postgres`, `psql`, `pg_dump`,
  `pg_restore` and `pg_isready`, at both the absolute paths that runtime code
  invokes and the `PATH`-resolved names that the recipe checks;
- each invoked path resolved to its final executable: symlink chain, any
  interpreter and modules, and every shared library loaded, attributed to its
  source stage. The Debian `pg_wrapper` and Perl chain is a hypothesis to test,
  not a known fact;
- each libpq copy separately: the system libpq used by the packaged clients in
  each image, and the libpq bundled in `psycopg[binary]` (currently 170006)
  used by RepoMap's Python processes. Record each one's path, version, package
  or wheel provenance and consumers, and make no claim about runtime loading
  beyond what is observed;
- package-database claims reconciled against file bytes, given the
  `/usr/local` and `/usr/lib` overlay;
- present notices and licenses;
- versioned advisory applicability, severity source and incumbent comparison,
  using ADR 0087 P3;
- unsupported and unknown packages listed explicitly.

The incumbent is inventoried the same way from existing exact artifacts: the
digest-pinned official image, and any existing incumbent application image
whose config ID is recorded. No extra build creates an incumbent. Missing
incumbent inventory is an explicit gap carried to the disposition.

### Required executed evidence

- Exact scoped unit selectors and disposable-container integration selectors,
  all with `--no-coverage`. The implementation assignment names and freezes
  them before execution. Required owners cover runtime image rendering,
  packaging and lifecycle, plus D9 provenance and restore requalification.
- Nearby actual owners for the assignment to inspect, not a frozen list:
  - unit: `arch7f_release_resources`, `coordinator_migration_packaging`,
    `local_runtime`, `security1_dependency_authority`, `package_structure`,
    `system_candidate_image`, `gate_contract_main_system` and
    `d9_final_boundaries`;
  - integration: `arch7f_release_wheel`, `security1_packaging_security`,
    `d9_manifest_provenance`, `d9_extension_restore`,
    `d9_extension_restore_requalification`, `d9_final_catalog_boundaries` and
    `slice9_coordinated_backup_restore`.

  Test counts are not stated here.
- **Known gap.** The D9 integration owners run on the Alpine 16.14 test pin, not
  on the production base. Among scoped paths, this phase found the production
  pin only in the sandbox's image pre-pull and in the Group K image-build
  support route. It found no scoped integration selector that runs the built
  application image's clients. Smoke and system use the pin, but they are
  complete suites that need a separate override. Alpine results are never
  production proof.
- **Proposed owner and its remaining obstacle.** The new owner closes the
  server half of the gap with existing APIs. `PostgresContainerConfig.image`
  already accepts an exact image other than the test pin, and the harness starts
  it with `--pull=never`. The sandbox pre-pulls the production pin, so the
  candidate pin is available once it changes. The server container's packaged
  clients can run there too. The application-image half has no path within
  existing authority:
  - `TestImageManager.build_ephemeral_image` builds from Dockerfile text with no
    build context, and requires the first line to be `FROM` one exact local
    base. The release recipe is multi-stage, starts from the Go image and copies
    the source tree.
  - Real-build tests fail closed through `enforce_build_profile_authority()`
    until the deferred TEST-HYGIENE3C build profile exists. They are marked
    `requires_build_profile` and listed in `DEFERRED_BUILD_PROFILE_NODE_IDS`,
    whose size the runner policy unit test pins at exactly 12. A real-build
    owner would change that registry and the deferred partition, which is a
    test-policy change that the bounds above exclude.

  The D12-A approval must therefore choose one of the following: a named,
  bounded build authority for this one owner within the two-build budget,
  including the registry and partition change it requires;
  exercising the application clients only through the system candidate builder
  under a separately bounded system override; or recording the application
  path as an unmet, blocking gap. The implementation assignment freezes the
  exact selectors, ownership, image bindings and execution counts before any
  work starts.
- Build success is not evidence. Require real PostgreSQL lifecycle and the
  packaged `psql`, dump, restore, load and backup-then-restore behavior on the
  candidate. Require 16.15 at the actual binary paths, every existing packaging
  invariant (pip, setuptools and `ensurepip` absent, Go absent, licenses
  present, migrations discoverable), and core D9 behavior: extension absence and
  replay of an unchanged archive.
- No complete local suite is authorized. Hosted gates stay separately bound to
  the candidate, and approving D12-A creates no trigger authority.

### 16.15 release-note assessment and operator handoff

The sealed evidence records only that the 16.15 notes include security fixes
and possible configuration or data adjustments. Their individual entries were
not itemized, and this phase did no new research. Before execution, the
implementation assignment itemizes every 16.15 entry that calls for a
post-update action, such as a reindex, configuration change or data check. It
classifies each entry against RepoMap's actual surface, observed on 2026-10-22:

- 43 indexes across graph and coordinator migrations, all default B-tree. No
  migration names another access method, creates an extension or sets a
  column collation.
- Clusters are initialized with `--encoding=UTF8 --locale=C`, and RepoMap
  creates databases with `LC_COLLATE 'C'` and `LC_CTYPE 'C'`. Restore can
  recreate a source database's recorded locale provider.
- The Compose server sets no custom server configuration, and its data
  directory is a bind mount.
- Optional pgvector objects exist only under the experimental test profile.

An entry that applies, or cannot be classified, stops for disposition. The
phase performs no production or live database action.

A future installed pin can affect later operator-controlled starts on existing
data, so no zero-effect claim is made. The D12-A exit must include an operator
handoff that covers:

- a verified backup through the existing backup-first lifecycle before the first
  start on 16.15;
- any applicable release-note actions;
- reversal: restore that backup on the incumbent pin, because reverting the pin
  alone does not undo actions already applied to a data directory.

### Outcomes

ADR 0087 P3 governs outcomes, with no silent waiver:

- **Stop pending disposition:** any `unknown` runtime-component finding, an
  `affected` runtime-component finding with critical, high or unknown severity,
  an applicable or unclassifiable release-note entry, or missing incumbent
  inventory. Nothing
  is accepted automatically, and a strictly worse incumbent is not retained
  automatically. The operator's written disposition accepts with named
  unresolved findings, authorizes a separate remediation (for example, of the
  unchanged bundled libpq), or refuses. That disposition is not D15 admission.
- **Disposition before acceptance:** lower-severity runtime-component
  `affected` findings, and `affected` or `unknown` findings in other
  components.
- **Refusal:** missing license or provenance, unbound identities, ABI or
  platform mismatch, unsafe lifecycle or removal behavior, package drift
  unrelated to the base change, or inability to prove owned cleanup.

A refusal condition overrides any disposition, as ADR 0087 P3 states.

### Acceptance, refusal and rollback

- **Accept** when, per platform, identities are bound, candidate inventory is
  complete, every finding is classified and compared, every stop has a written
  disposition, both advisories are outside the affected range at the
  candidate's actual binary paths, and all frozen selectors pass. Each advisory
  is `fixed` against the incumbent where incumbent inventory exists. Where it
  does not, the gap is named in the written disposition. A platform without
  that evidence stays unqualified and limits the claim.
- **Refuse** when a refusal condition holds or the operator refuses by
  disposition. Missing candidate evidence that no disposition supplies leaves
  the candidate unqualified, never accepted.
- **Incumbent after refusal.** Refusal does not decide the incumbent. The 16.14
  pin stays as the as-built state only. The refusal record needs a written
  operator decision in D12-0 form that names its unresolved findings, or a
  decision to pursue another remediation. It is never retained silently.
- **Rollback** affects code and candidate artifacts only. Revert the pin change
  and remove owned candidate images. Never attach to, restart or migrate a live
  database. Moving an existing data directory between minor versions is an
  operator action outside this scope, covered by the handoff above.

## What remains open after any D12-A outcome

D12-B extension-enabled final image evidence, and its separation from D15
production admission and from actual database enablement. D12-B first needs
the server-image choice in ADR 0087 P6. ADR 0051 is not amended here. Also
open: any separate remediation of the bundled libpq, and complete
D9 optional mechanics, D10 and configuration-data replay, D13 workload and
benchmark, human utility (`utility_not_measured`), and corpus and model rights.

## What would make this packet wrong

- The proposed index does not carry `16.15-1.pgdg12+2` binaries on a platform,
  or a primary source withdraws either fix.
- An existing scoped owner already executes D9 behavior on the production base,
  which would make the gap above smaller than stated.
- The final application image's clients do not use overlaid libraries, which
  would make the overlay concern moot. Inventory would still be required.
- An existing harness path already builds the release recipe within current
  authority, which would remove the stated application-client obstacle.
- RepoMap creates core indexes, collations or server settings outside the
  migrations and Compose recipe surveyed above, so the release-note
  classification would rest on an incomplete surface.

## Operator decision requested

Choose one: **D12-A as bounded above (recommended)**, D12-0 (retain the
incumbent with findings unresolved), or D12-AB (combined; not recommended). A
D12-A approval must also choose how the application-client path is exercised
(see required executed evidence). Any choice is recorded in a later phase. This
packet does not record a selection.

### Recommended combined selection

Select **D12-A plus a bounded build-test authority for its one named new
integration owner**. This is the first execution route above, not a complete
local system-suite override. It requests an explicit, narrow test-policy
exception in addition to the image change: implement only the new owner's
build admission and population classification, using existing resource-accounting
APIs. Keep at most two candidate builds, one per platform, and exact scoped
`--no-coverage` selectors.

Preserve every existing deferred owner, its refusal behavior and every debt
ceiling. This choice does not activate TEST-HYGIENE3C generally, authorize an
unmarked-test bypass, or move any incumbent deferred case into an accepted
population. The later implementation assignment must freeze the new owner's
profile, selectors, classification and build accounting before execution. If it
cannot do so without weakening existing contracts, stop with the exact obstacle
for operator disposition. No implementation authority is granted by recording
this recommendation.
