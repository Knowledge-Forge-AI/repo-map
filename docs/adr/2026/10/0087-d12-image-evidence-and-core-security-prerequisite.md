# ADR 0087: D12 image evidence contract and core PostgreSQL security prerequisite

## Status

**Accepted for D12-A only (2026-10-22).** Prepared as proposed read-only design
by `REPOMAP-PRODUCT6-NAVIGATION42-CI62-D12DESIGN1`. On 2026-10-22 the operator
replied "Approve D12-A + bounded build-test authority (Recommended)" to the
[D12 decision packet](../../../specs/postgresql-d12-image-evidence-decision-v1.md)
at SHA-256 `53785f4568b0a64dc908eed62b59548ac8ec6d77fcccf7673dca2ee49ecfcc84`,
selecting its
[recommended combined selection](../../../specs/postgresql-d12-image-evidence-decision-v1.md#recommended-combined-selection).
`REPOMAP-PRODUCT6-NAVIGATION43-D12CORE1` records that approval here before any
source change.

What the approval accepts:

- P1 to P5 as the evidence contract and outcome rules for the D12-A candidate,
  and P4's order (core refresh before any extension image).
- D12-A: the core base moves to PostgreSQL 16.15 pinned only by index
  `sha256:d81f7b51697014367236d07ec58b54153fc28f828b72bf247fe5c7487520bcb0`.
- One-owner build-test authority: one named integration owner and its support
  module may build the release recipe at most once per platform (linux/arm64,
  linux/amd64), two builds in total, with no automatic retry. The twelve
  existing deferred build-profile nodes, their refusals and every debt or
  coverage ceiling stay unchanged. This is not TEST-HYGIENE3C and not a
  complete-suite override.

What stays unresolved:

- P6 and D12-B. No server-image choice is made, and ADR 0051 is not amended.
- D15 admission, pgvector production admission and any live deployment.
- Image, platform and CVE qualification of any candidate. Approval is
  authority to produce evidence, not evidence. No platform is qualified until
  P3 classification and its dispositions exist.
- Disposition of inherited findings, including any against the unchanged
  bundled libpq, and missing incumbent inventory. Each needs a written operator
  disposition under P3.

Follow-up: [ADR 0088](0088-d12-psycopg-binary-remediation-preflight.md)
records the operator's conditional approval of an exact Psycopg 3.3.6
remediation for the bundled-libpq finding. Its preflight did not establish the
required closure, so the bundled libpq 17.6 finding stays open under P3 and the
candidate build budget stays held.

## Date

2026-10-22

## Context

[ADR 0051](../08/0051-postgresql-extension-and-database-capability-architecture.md)
D12 requires a classified supply chain with no presumed property. Vulnerability
review is version-scoped and determined against the exact pinned server image.
License evidence comes from primary sources. D15 admits a capability only with a
complete record, and D12 item 2 is part of it.
[ADR 0077](0077-publication-bound-pgvector-candidates.md) authorizes only a
disposable extension-enabled **test** image, built from the existing pinned core
base. That authority is narrower than production. The approved D9-B scope
([ADR 0084](0084-extension-aware-backup-and-restore.md)) admits no new image,
dependency or default.

The roadmap allows read-only D12 design without installing dependencies. Current
primary-source research for this design, observed on 2026-10-22, found facts
that change the order of D12 work.

### What the current code builds

[`release.py`](../../../../src/main/python/repomap_kg/runtime/release.py) pins
`POSTGRES_RELEASE_VERSION = "16.14"` and
`postgres:16-bookworm@sha256:92620dad…dfc55`. It also pins the Python 3.12.13 and
Go 1.25.12 Bookworm images, psycopg 3.2.12 with libpq 170006, and setuptools
83.0.0. The packaged client paths are `/usr/lib/postgresql/16/bin/psql`,
`/usr/bin/pg_dump` and `/usr/bin/pg_restore`.

Two runtime images use the PostgreSQL pin:

- The Compose `postgres` service runs the pinned official image directly
  ([`compose.py`](../../../../src/main/python/repomap_kg/runtime/compose.py)).
  That container is the database server.
- The application image is built by `render_server_dockerfile`
  ([`commands.py`](../../../../src/main/python/repomap_kg/runtime/commands.py)).
  Its final stage is `FROM` the PostgreSQL pin. It then runs
  `COPY --from=python-runtime /usr/local /usr/local` **and**
  `COPY --from=python-runtime /usr/lib /usr/lib`, copies the Go helper and its
  license, and asserts the `psql`, `pg_dump` and `pg_restore` version strings.

The packaged clients run backup, restore and service SQL in two places. In
container-internal mode, which Compose sets for the application services, they
run in the application image
([`backup_commands.py`](../../../../src/main/python/repomap_kg/runtime/backup_commands.py),
[`backup_records.py`](../../../../src/main/python/repomap_kg/runtime/backup_records.py)).
In host-driven mode, the same absolute paths run through `docker exec` inside
the Compose server container. The server healthcheck runs `/usr/bin/pg_isready`
there too. A D12 record therefore covers clients in both images.

Two distinct libpq copies are in play:

| libpq | Where | Version and provenance | Consumers |
| --- | --- | --- | --- |
| System libpq | The PostgreSQL base image. In the application image, anything under `/usr/lib` is subject to the overlay | Not recorded in the checkout; it must be observed per image and platform | The packaged clients in both images |
| Bundled libpq | Inside the `psycopg[binary]` 3.2.12 wheel in the application image's `/usr/local` | `pq.version()` 170006 (17.6), asserted at build time; on-disk path not observed | RepoMap's Python processes |

Neither copy's path, file bytes or package source was observed in this phase.
No statement here says which library a running process actually loads. The
proposed D12-A does not change the psycopg pin. A finding against the bundled
copy can therefore need its own operator remediation choice.

The recipe checks client versions through `PATH` lookup (`psql --version`).
Runtime code invokes the absolute paths above, which can resolve differently.
One packaging hypothesis is that the `/usr/bin` client names are Debian
`postgresql-common` `pg_wrapper` symlinks to a Perl script. It is
**unverified** until the exact image is observed. If it holds, those clients
also depend on the Perl interpreter and its modules.

[Bookworm requires a merged `/usr`](https://www.debian.org/releases/bookworm/amd64/release-notes/ch-information.en.html#merged-usr),
so `/usr/lib` holds the system shared libraries.
The recipe therefore overlays files from the Python image's `/usr/lib` onto
the PostgreSQL image's `/usr/lib`. The dpkg database under `/var/lib/dpkg` is
not copied, so it keeps describing the PostgreSQL stage. This is an inference
from the recipe text. No image was inspected in this phase. If it holds, the
package database in the final image can disagree with the library bytes that
the PostgreSQL clients actually load. A base-image SBOM, or a scan that trusts
the package database, then cannot establish the final merged runtime contents.

The test harness pins `postgres:16-alpine@sha256:e013e867…28cb`
([`postgres_container_config.py`](../../../../src/test/support/python/repomap_test_support/postgres_container_config.py),
[`test_sandbox_contract.py`](../../../../tools/test_sandbox_contract.py)).
The D9 restore integration owners run on this Alpine test image, not on the
Bookworm production base. The optional pgvector test image is a mutable local
tag, `repomap-test-postgres:16-pgvector087-v1`, built from that Alpine base and a
recipe ([`runner_sandbox_assets.py`](../../../../tools/runner_sandbox_assets.py),
[`pgvector_test_source.json`](../../../../tools/pgvector_test_source.json)). The
hosted release-qualification workflow runs its SBOM and vulnerability job on the
checked-out source tree (`path: "."`), not on a built image. That job's
CI59 and CI62 passes are therefore not image inventory evidence.

### What primary sources say

Facts below were observed on 2026-10-22 and must be re-verified at
admission time:

- [CVE-2026-16239](https://www.postgresql.org/support/security/CVE-2026-16239/)
  is a core-server cursor/portal type confusion. Versions before 16.15 are
  affected, and 16.15 fixed it on 2026-08-13.
- [CVE-2026-19385](https://www.postgresql.org/support/security/CVE-2026-19385/)
  is a `pg_dump` heap buffer overflow. Versions before 16.15 are affected, and
  16.15 fixed it on 2026-08-13. RepoMap's release contract packages `pg_dump`.
- The [16.15 release notes](https://www.postgresql.org/docs/release/16.15/)
  include security fixes and possible configuration or data adjustments. Minor
  version compatibility alone is not qualification.
- The [versioning policy](https://www.postgresql.org/support/versioning/) lists
  16.15 as the current 16 minor release, with major 16 supported until
  2028-11-09. Upstream recommends the current minor release.
- [Debian bookworm](https://www.debian.org/releases/bookworm/) is in LTS for a
  limited set of architectures until 2028-06-30. That date is earlier than
  PostgreSQL's, and it is not a promise for every package in an image.

Registry metadata only, with zero layers downloaded and zero Docker operations,
reported `16.14-1.pgdg12+1` for both platforms of the incumbent index. This is
a **version-based** finding. The incumbent's server and its packaged `pg_dump`
predate the fixed release for both advisories. It is not a tested exploit,
not a reachability analysis and not a complete package-CVE determination.

For pgvector, the [0.8.7 control file](https://raw.githubusercontent.com/pgvector/pgvector/f37c13f68b57d2c3472b2214fbcff699d6d34876/vector.control)
names the backend module `$libdir/vector` and declares no extension dependency.
[Issue 1036](https://github.com/pgvector/pgvector/issues/1036) reports
CVE-2026-103484 in 0.8.6 and below, fixed in 0.8.7. The upstream
[security advisories page](https://github.com/pgvector/pgvector/security/advisories)
listed no published advisory at observation time. Issue 1036 shows that an
empty advisory page is not evidence of no vulnerabilities. pgvector is a
third-party native backend extension under ADR 0051 D12. Its "trusted" status,
if any, is an installation-privilege property and not a supply-chain judgment.

### Open D12-B design discrepancy

ADR 0051 D12 states that extension binaries originate only from RepoMap's built,
digest-pinned server image. Its supporting evidence is the release image built
`FROM` the PostgreSQL pin in `commands.py`, whose renderer is named
`render_server_dockerfile`. That image is what this ADR calls the application
image. It runs clients and the RepoMap services, not the database server. The
database server is the Compose `postgres` service, which runs the unmodified
official image. ADR 0051's Deferred Work already leaves open whether RepoMap
supports arbitrary conforming servers or only its own digest-pinned runtime
image.

The discrepancy does not depend on how "server image" is read. Under either
reading, no RepoMap-built image currently hosts the PostgreSQL server process,
so extension binaries added to the built image would not reach the server.
Renaming or reinterpreting the term does not resolve it. This ADR does not
amend ADR 0051 or change the topology. It records the discrepancy as an open
decision for D12-B (P6).

## Decision (accepted for D12-A only; see Status)

### P1 — Evidence identities are distinct

A D12 record names each of the following separately and never substitutes one
for another:

| Identity | Meaning | Not |
| --- | --- | --- |
| Source content digest | SHA-256 over the exact candidate source and recipe inputs | An image identity |
| Recipe identity | SHA-256 of the exact rendered Dockerfile text and build arguments | Proof of output contents |
| OCI index digest | The multi-platform registry index of a base image | A per-platform image |
| Child manifest digest | One platform's manifest within that index | The built candidate |
| Image config ID | The local `sha256:` config identity of a built candidate | A registry digest; nothing is pushed |
| Final inventory | Files, binaries, libraries, notices and package claims observed in that exact built image | Inferred from a base SBOM or a package database |

A tag such as `16.15-bookworm`, or a local tag such as a test cache name, is a
mutable lookup key. It is never evidence. A recipe label on a local image only
names the recipe it claims to come from.

### P2 — The final merged image is the unit of evidence

Each image that runs in production is inventoried as built, per platform:

- the PostgreSQL service image as pinned;
- the application image built from the release recipe.

The inventory records the actual paths and versions of `postgres`, `psql`,
`pg_dump`, `pg_restore`, `pg_isready` and each libpq copy, with each one's
consumers. Every invoked path is resolved to its final executable: symlink
chain, any interpreter and its modules, and every shared library loaded,
attributed to the build stage that supplied it. A wrapper chain is recorded as
observed, not assumed. The inventory reconciles package database claims against
file bytes. Disagreements are findings, never silently resolved. Notices and
licenses are recorded as present or absent from the image itself.

### P3 — Findings are versioned, severity-sourced and compared

Each finding names the component, its path and observed version in the final
inventory, the primary advisory and the affected and fixed ranges.

**Applicability**, per image, takes exactly one class:

| Class | Meaning |
| --- | --- |
| `not_present` | Component absent from the final inventory |
| `outside_affected_range` | Present at a version that the primary advisory excludes |
| `affected` | Present at an affected version |
| `unknown` | No determinable version, no primary data, or an unsupported package |

**Severity evidence** follows a fixed order:

1. The supplier's primary advisory: PostgreSQL for the server and clients, the
   Debian security tracker for Debian packages, otherwise the upstream project.
   Record its stated severity and any CVSS version, score and vector. A
   distribution urgency or triage label, such as Debian `unimportant` or
   `no-dsa`, is recorded as a label, following the
   [Debian tracker documentation](https://security-team.debian.org/security_tracker.html#severity-levels).
   It is not a numerical severity for this policy and never lowers one.
2. Always also record named secondary sources, such as the CVE record, labelled
   as secondary. They are consulted for every finding, not only when step 1 is
   silent.
3. When sources conflict, record all of them. The highest applicable severity
   governs until a written disposition.
4. No severity from any source is severity `unknown`. An absent score never
   lowers severity. In a runtime component it stops like critical or high.

**Comparison.** The incumbent and candidate are classified with the same sources
on the same date. Each `affected` or `unknown` finding is `inherited` (both
images), `introduced` (candidate only) or `fixed` (incumbent only). `fixed`
requires the candidate's actual binary version. Incumbent inventory comes from
inspecting existing exact incumbent artifacts. No build is added to create a
fresh incumbent. Unavailable incumbent inventory is an explicit gap carried to
the disposition, never read as clean or as worse.

**Outcomes:**

- **Stop pending disposition.** In a runtime component (the PostgreSQL server
  or clients, either libpq, libc, TLS, or the Python runtime): any `unknown`
  finding, or an `affected` finding with critical, high or unknown severity.
  Missing incumbent inventory also stops here. Work stops and nothing is
  accepted. The operator's written disposition chooses one of
  three outcomes: accept with the finding recorded as unresolved and its owner
  named, authorize a separate remediation, or refuse. An inherited finding that
  the candidate leaves unchanged, such as one against the bundled libpq, can
  need that separate remediation choice. A stop never retains a strictly worse
  incumbent automatically.
- **Disposition before acceptance.** Lower-severity `affected` findings in
  runtime components, and `affected` or `unknown` findings in other components.
- **Refusal.** Unbound identities, missing license or provenance, ABI or
  platform mismatch, unsafe lifecycle or removal, unrelated package drift, or
  unproven cleanup. No disposition turns these into acceptance. The operator may
  also refuse by disposition.

**Precedence.** A refusal condition overrides any disposition. Missing candidate
evidence that no disposition supplies leaves the candidate unqualified for that
scope, never accepted. Refusing or not qualifying a candidate does not decide
the incumbent. Its pin stays in place as the as-built state only. Keeping it
needs a written operator decision in D12-0 form that names its unresolved
findings, or a decision to pursue another remediation.

A written D12 disposition is not D15 admission. D15 stays refused while any D12
item is incomplete. This classification is proposed only for D12 image
candidates. The project-wide source-tree scan and its `high` cutoff are
unchanged. Nothing here permits a silent waiver.

### P4 — Core security precedes extension image work

The incumbent 16.14 base remains the current, historical, as-built pin until a
reviewed replacement is accepted. Under P3 it carries two version-based
`affected` core findings. It cannot be presented as an acceptable D12 security
baseline.
The recommended first image change is therefore a **core PostgreSQL 16.15
refresh and qualification** (D12-A). Its bounded authority is proposed in the
decision packet. Extension-enabled final image evidence (D12-B) follows as a
separate decision on the refreshed core. Bundling both changes into one
candidate is explicitly deferred. That would combine two unproven deltas into
one result that cannot be attributed.

### P5 — Image evidence is not admission or enablement

A complete D12 record for an image is one of ten ADR 0051 D15 items. It does not
admit pgvector, enable it in any database, select a default or settle D13
usefulness. Build success is not database evidence. Real PostgreSQL lifecycle,
packaged client, dump, restore, load and backup behavior need their own
executed, candidate-bound selectors. A platform that cannot be built or
executed is blocked for that platform. It is never inferred to pass.

### P6 — D12-B needs an explicit server-image choice

No extension-image work starts until the operator explicitly chooses how
extension binaries reach the server. For example, the Compose server could run
a RepoMap-built, digest-pinned server image, or ADR 0051 D12 could be amended
for the current topology. That choice also settles, or explicitly keeps open,
ADR 0051's deferred question of which servers RepoMap supports. It cannot be
met by reinterpreting "server image". Either choice needs its own decision
record. This ADR selects neither.

## Scope and non-scope

In scope: the D12 evidence identities, the final-image inventory obligation,
the proposed finding classes, severity evidence and outcomes, the recommended
order of core and extension image work, and the open D12-B server-image
discrepancy.

Out of scope: any source, pin, recipe, lock, test, fixture, workflow or
configuration change. Also out of scope are any image pull, build or inspection,
any live database action, extension installation, and changes to production
defaults. Changes to Python, Go, psycopg, setuptools or package-manager pins are
out of scope, as are any project-wide scanner or security gate, and D9, D10,
D13 or D15 dispositions.

## What would prove this wrong

- The final application image's library bytes and package database agree for
  every PostgreSQL client dependency on both platforms. The overlay concern
  would then be moot, though inventory would still be required.
- A primary source shows that 16.14 is not affected by either advisory, or that
  `16.15-1.pgdg12+2` does not carry the fix.
- The P3 classes cannot express a real finding, or they force an unsafe finding
  into an accepted class.
- The P3 outcomes let a disposition accept a candidate that is worse than the
  incumbent, or let refusal keep an incumbent that is strictly worse without a
  written operator decision.
- A distribution urgency label, or a silent primary advisory, lets a finding
  carry a lower severity than a recorded secondary source states.
- The Compose server already loads extension binaries from a RepoMap-built
  image, which would remove the P6 discrepancy.
- A core-only refresh changes behavior that only a combined extension candidate
  would have revealed, so that the split loses evidence instead of isolating it.

## Consequences

When accepted, a D12 image change costs per-platform inventory and
classification on top of build and test evidence. Hosted CI's current
source-tree SBOM job does not provide this evidence. Producing it needs a
separately authorized implementation phase.
Until then, the production base is unchanged and carries a version-based
remediation requirement that is recorded but not resolved.

An accepted pin change is not inert for existing installations. A later
operator-controlled start can run the new server binaries over an existing data
directory. The decision packet therefore requires a release-note assessment
against RepoMap's schema and configuration, plus an operator handoff with
backup and reversal steps.

## Rejected alternatives

- **Accept the base-image SBOM or registry metadata as the image record.** It
  ignores the `/usr/lib` overlay and the separate application image.
- **Infer safety from an empty advisory page.** Issue 1036 disproves this.
- **Retain 16.14 as the D12 baseline with findings noted.** This is not
  rejected as an operator choice. It is rejected as a basis for any extension
  image or D15 record.
- **Combined core and pgvector candidate first.** Deferred, not selected. It
  enlarges the change and confounds attribution.
