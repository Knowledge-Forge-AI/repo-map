# ADR 0089: D12 dynamically linked C Psycopg 3.3.6 with system libpq

## Status

**Exact Trixie remediation A approved (2026-10-23); no candidate accepted.**
The human selected [ADR 0091 A](0091-d12-tls-p3-disposition-and-trixie-remediation.md)
with its reviewed parent bounds and the named unresolved incumbent comparison
gap. Native ARM read-only inspection of both exact approved bases observed
supplier-fixed libssl3t64 `3.5.7-1~deb13u3`; it is not final-image P3 evidence.
The new dependency/payload amendment in ADR 0091 requires independent review
and parent acceptance before source implementation. The old Bookworm .20
header and Tk identities below remain historical and must not match new bytes.
No E3, application build, SDK change, budget release or publication follows
from the observation. All other P3/refusal/native/image gates remain.

**Accepted dependency class and parent-accepted design (2026-10-22), after
one independent review and documented corrections. Implementation, correction,
prerequisite custody correction, final refusal correction, guard correction,
import correction, archived header correction, Perl prerequisite
correction, byte identity correction, installed-package hold correction,
SDK probe import-order correction and receipt framing/M2 checkpoints produced the same day,
and the producer-status erratum and guard-attribution correction of 2026-10-23,
NOT ACCEPTED: they await an independent review of the resulting
source, the observed per-platform package manifest, a positive inner-daemon
platform preflight, P3 and actual image evidence** (see
[Implementation checkpoint](#implementation-checkpoint-2026-10-22),
[Correction checkpoint](#correction-checkpoint-2026-10-22),
[Prerequisite custody correction](#prerequisite-custody-correction-2026-10-22),
[Final refusal correction](#final-refusal-correction-2026-10-22),
[Guard correction](#guard-correction-2026-10-22),
[Import correction](#import-correction-2026-10-22),
[Archived header correction](#archived-header-correction-2026-10-22),
[Perl prerequisite correction](#perl-prerequisite-correction-2026-10-22),
[Byte identity correction](#byte-identity-and-python-312-header-correction-2026-10-22),
[Installed-package hold correction](#installed-package-hold-correction-2026-10-22),
[SDK probe import-order correction](#sdk-probe-import-order-correction-2026-10-22),
[Producer-status erratum](#producer-status-erratum-2026-10-23) and
[Guard-attribution correction](#guard-attribution-correction-2026-10-23)).
On 2026-10-23 the parent's frozen C11/Go-wheel cohort passed and the one Go
component campaign ran (see
[Scoped cohort and component evidence](#scoped-cohort-and-component-evidence-2026-10-23)).
Neither is release-image, platform or P3 evidence. The E1 non-consuming
exploration source was then produced (see
[E1 exploration implementation checkpoint](#e1-exploration-implementation-checkpoint-2026-10-23)).
It had one independent review; the parent rejected its shared admission
slot, and a correction separates it (see
[E1 admission separation correction](#e1-admission-separation-correction-2026-10-23)).
The parent accepted that correction locally. The integration owner's eager
build-admission read was found before any E1 attempt and is corrected (see
[Named-owner E1 dataflow correction](#named-owner-e1-dataflow-correction-2026-10-23)).
NOT ACCEPTED; no E1 run has happened. (Superseded 2026-10-23: after one
independent review and a close stage, the parent ran the one admitted E1. It
refused at the Python-base closure, and D4 was then unchanged (now
[amended](#exact-payload-implementation-2026-10-23)); see
[E1 actual refusal](#e1-actual-refusal-2026-10-23).)
On 2026-10-22 the operator
answered the
[ADR 0088](0088-d12-psycopg-binary-remediation-preflight.md#recommended-bounded-next-choice)
follow-up decision with "Okay, dynamic linking approved. Static linking of
psycopg never approved." This selects choice A: exact C Psycopg 3.3.6,
dynamically linked to the distribution-owned shared libpq. The operator's
preceding clarification grounded the dynamic-only constraint in Psycopg's
license. `REPOMAP-PRODUCT6-NAVIGATION45-D12DYNAMIC1` records the approval here,
before any source change.

The approval does **not** authorize static incorporation of Psycopg or libpq;
the prebuilt `psycopg-binary` distribution, private libpq copy, pure Python or substitute version; Cython,
another build backend or any new Python dependency; host package installation,
new emulators or builders, or a tmpfs increase; a P3 disposition, hold release
or new budget; or publication, deployment, CI triggers, pgvector or D15. It is
not a license or security waiver. Implementation starts only after parent
acceptance of this design and a separately bounded implementation checkpoint,
within the same approved phase.

## Date

2026-10-22

## Context

[ADR 0087](0087-d12-image-evidence-and-core-security-prerequisite.md) accepted
D12-A and its P1 to P5 evidence rules. Under P3 the candidate build budget is
held at zero: the pinned `psycopg[binary]==3.2.12` bundles libpq 17.6, inside
the [CVE-2026-6477](https://www.postgresql.org/support/security/CVE-2026-6477/)
range. ADR 0088 found that the binary 3.3.6 wheels lack a proven supported and
licensed closure. The human ceiling remains two candidate builds in total, one
per platform, with no retries. None has been used.

Current owners (committed source unless noted):

- [`pyproject.toml`](../../../../pyproject.toml): the `postgres` extra pins
  `psycopg[binary]==3.2.12`; the base SQLite install has no driver.
- [`release.py`](../../../../src/main/python/repomap_kg/runtime/release.py)
  pins Psycopg 3.2.12, libpq `170006`, setuptools 83.0.0 and PostgreSQL
  16.14. The 16.15 Bookworm digest `d81f7b51…` exists only in unaccepted D12-A
  working-tree changes.
- [`commands.py`](../../../../src/main/python/repomap_kg/runtime/commands.py)
  `render_server_dockerfile` is the one server recipe, used by the local
  Compose runtime, the system candidate image and D12. Its `python-runtime`
  stage installs setuptools and `.[postgres]` from the index without hashes.
  The final stage, `FROM` the PostgreSQL base, copies that stage's
  `/usr/local` **and** `/usr/lib`, which can replace PostgreSQL-image
  libraries behind `dpkg` (ADR 0087).
- `repomap_kg.coordinator._control_schema` imports `psycopg` eagerly, so the
  `python-runtime` migration check loads libpq.
- `tools/ci/project_dependencies.{in,lock}` under
  `generated_lock_policy.json`, whose `exclude_newer` (2026-08-26) predates the
  2026-09-18 psycopg-c 3.3.6 upload; also `uv.lock`. The hosted unit lane
  installs the project lock with `--require-hashes --no-deps` on Python 3.13.
- The [test sandbox](../../../../tools/test_sandbox/Dockerfile) (Python
  3.13.12, Debian `postgresql-17`, `gcc`, `libc6-dev`) pip-installs unhashed
  pins including `setuptools==83.0.0`, `wheel==0.48.0` and `psycopg[binary]`.
  `tools/test_sandbox_images.py` derives its recipe identity from the
  Dockerfile bytes alone and builds from `tools/test_sandbox/`.
- `TestImageManager`'s dependency-only Python 3.12 image pip-installs
  unhashed `pyproject` specifiers and probes `psycopg-binary` metadata.
- `tools/ci/python_type_check.py` attests `psycopg` 3.2.12 and carries a
  missing-Psycopg-import debt ceiling.

Upstream facts, read from primary sources at tag commit
`a67654d1e7afbf9b3a619557838f62de1c790e7c`:

- The C `pyproject.toml` uses the in-tree `cython_backend`, requires
  `setuptools == 83.0.0` and `wheel >= 0.37`, and needs `tomli` only below
  Python 3.11.
- `cython_backend` requests Cython only when `psycopg_c/_psycopg.pyx` exists;
  otherwise it trusts packaged `.c` files. `psycopg_build_ext` links `-lpq`
  using `pg_config` include and lib dirs.
- `psycopg.pq` tries `c`, then `binary`, then `python` unless `PSYCOPG_IMPL`
  is set, so a failed C import can fall back silently. It exposes
  `__impl__`, `version()` (runtime libpq) and `__build_version__` (headers).

Sealed PyPI metadata for `psycopg_c-3.3.6.tar.gz`: 698,245 bytes, SHA-256
`29c568426ad61c1b702c7d73505c43ca2c9fc5d97a8431d8d9049e731e319ff8`, not
yanked, `LGPL-3.0-only`, no release attestation observed. The pure wheel
`psycopg-3.3.6-py3-none-any.whl` is hash-verified as
`a1db9f7148b06a28606767efaca51fa6f9398c5c0a3810519be69d7000bdb631`. The
parent inspected that exact archive without extracting or executing it:
34 tar members, three `.c` files, no `.pyx`, static archive or `setup.py`.
(Correction at implementation: `_psycopg.c` and `pq.c` are Cython 3.3.0
output; `types/numutils.c` is hand-written Psycopg code with
PostgreSQL-derived portions.) Its `pyproject.toml` matches the pinned tag byte-for-byte.
This is source inspection, not compiled, loaded-library or image evidence.
The docs dispatcher acquired, built and installed nothing.

## Decision

### D1. Package identity

The `postgres` extra becomes exactly `psycopg[c]==3.3.6`: `psycopg==3.3.6`
from the approved wheel plus `psycopg-c==3.3.6` built from the approved
sdist. No `psycopg-binary` or private libpq ships in any environment. Every
other Python pin, the base SQLite set (`typing-extensions==4.16.0` only),
private version 0.1.0, the index and the hash rules stay unchanged.
`PSYCOPG_RELEASE_VERSION` becomes `"3.3.6"`. `PSYCOPG_LIBPQ_VERSION` becomes
the observed numeric version of the release base's system libpq, a preflight
output that is never guessed. If the two platforms' libpq versions differ,
the preflight refuses rather than splitting the constant.

**Base precondition.** The prior D12-A approval permits the pinned 16.15 base
for investigation and preflight. The parent rechecked its OCI index and both
platform child/config digests against the registry. This authorizes neither
final-image admission nor a P3 hold release; those remain pending. Recheck the
same identities before executing a platform preflight.

### D2. Dynamic linkage and loaded-library proof

Bundling and linkage are separate axes; both a system-owned library and
dynamic linkage are required. Each condition is a refusal when unmet:

1. Every ELF in the installed `psycopg-c` `RECORD` is listed. Each one that
   references a libpq symbol (`PQ*`, `pg_*`, `lo_*`) has `DT_NEEDED`
   `libpq.so.5`, and at least one does. Those symbols are undefined dynamic
   imports, none defined locally; the full list is recorded. No static
   archive or `-static`/`-Bstatic` flag contributes to the link.
2. In the final image, with `PSYCOPG_IMPL` unset: `pq.__impl__ == "c"`;
   `pq.version() == pq.__build_version__ == PSYCOPG_LIBPQ_VERSION`; no
   `psycopg_binary` module or `psycopg-binary` distribution; no libpq shared
   or static library under `/usr/local` (Cython's `libpq.pxd` declaration is
   not a library). The product libpq is 17 or newer and
   `psycopg.capabilities.has_cancel_safe()` is true, preserving the incumbent's
   bounded `cancel_safe(timeout=...)` (see the correction checkpoint).
3. A probe process that has imported Psycopg finds exactly one `libpq.so.5`
   in `/proc/self/maps` and records its real path; its SHA-256, equal to the
   frozen per-platform value; its `dpkg -S` owner, which must be `libpq5`;
   that package's version, equal to the frozen value; and a clean
   `dpkg --verify` that exits 0 or 1 (problems reported) and nothing else.
   Every probe subprocess fails closed on an undocumented exit status.

These are qualification observations. They do not introduce an application
runtime checksum lock against replacing interface-compatible shared libraries.

### D3. libpq ownership and ABI

- **One runtime owner.** The release image's runtime libpq is the `libpq5`
  package installed in the pinned PostgreSQL base. The preflight verifies its
  origin from `apt-cache policy` and the base's source entries; an origin
  other than the base's configured PGDG repository is a refusal. The same
  library serves Psycopg and the packaged clients.
- **Matching headers.** The extension compiles against `libpq-dev` at exactly
  the same version and repository, and `pg_config --version` must match.
  Python headers come from the shipped interpreter tree.
- **Repository trust.** The PGDG source entry and keyring come byte-for-byte
  from the pinned base and are hash-asserted. No new signing key is trusted.
  If the preflight shows an exact version is held only by the vendor's
  official historical archive (PGDG's archive, or Debian's snapshot service
  for Debian packages), that archive URL is added as a declared source
  verified by the same key fingerprints. That is a new URL, not new key
  trust, and is recorded. The SDK recipe meets this by binding the base
  keyring file's SHA-256: a byte-identical file holds the same key set (see
  [Perl prerequisite correction](#perl-prerequisite-correction-2026-10-22)).
- **Frozen manifest, per platform.** Each base config digest; every builder
  and runtime package's name, version, architecture, repository and `.deb`
  SHA-256 from the signed index; the libpq file SHA-256; the key
  fingerprints. These values are rendered release constants in `release.py`,
  so ADR 0087 P1 recipe identity covers them.
- **Install-time enforcement.** The recipe downloads pinned `name=version`
  packages first, asserts each cached `.deb` SHA-256 equals the frozen value,
  then installs from that cache without further downloads.
- **Drift.** Immediately before any reservation, resolution is re-run against
  the frozen manifest. A mismatch is a non-consuming refusal that returns to
  preflight and P3 classification.
- **Refusal** also on an unresolved identity, any install that would change a
  preinstalled package, or a header/runtime version mismatch.

### D4. Release recipe (narrow correction)

`render_server_dockerfile` changes only as follows:

- **`python-runtime` stage.** Copy the PGDG source and keyring from the
  pinned base. Install the frozen `gcc`, binutils, `libc6-dev`, `libpq-dev`
  and `libpq5` closure per D3; a `dpkg` before/after diff must show additions
  only. Fetch the psycopg-c sdist as an **opaque file**: no pip resolution or
  backend execution, SHA-256 and size checked against release constants.
  Fetch the five wheels (psycopg 3.3.6, `typing-extensions==4.16.0`,
  `setuptools==83.0.0`, `wheel==0.48.0` and its requirement
  `packaging==26.3`) with `--require-hashes --only-binary :all:`. Then,
  under `RUN --network=none`, in order: the D5
  sdist inspection; install the hashed build tools offline; build with
  `--no-index --no-build-isolation --check-build-dependencies`; run the D2
  ELF checks; install `.[postgres]` offline. The existing migration check
  then loads the same libpq version. `pip check` passes with the build tools
  installed. Finally uninstall `pip`, `setuptools`, `wheel` and `packaging`
  and remove `ensurepip` and `/usr/local/include`. The inspected archive is
  kept for the final image's documentation (D7).
- **Exact Python payload amendment (2026-10-23), parent-accepted after
  independent review; source implemented, NOT ACCEPTED.** The parent selects
  [route A](../../../specs/postgresql-d12-python-payload-decision-v1.md#a-exact-unusable-_tkinter-exclusion).
  Record the complete unmodified baseline first. In the owned staged payload
  exclude only the frozen native arm64 `_tkinter` regular file (70,512 bytes,
  SHA-256 `e6856022061704f2b95ea01c9c12b6fa6fee36d2527a8ad7d0f18d4bacd9519f`),
  bound to the accepted Python index and config. Before deletion require
  exactly the observed Tcl/Tk missing pair, the sole nonimporting module,
  path/hash/size/base/native checks and no other unresolved ELF. Refuse
  unknown platforms or changed observations. Re-enumerate after deletion:
  every retained ELF must resolve and every baseline-successful module must
  still import. Preserve all other payload and notices except the already
  named build tools. The recipe and exploration use the same frozen contract;
  no glob or blanket exception. File/spec and import-error behavior can change;
  P2 must name the deletion. No new dependency or budget. Full contract,
  alternatives, source owners and negative proof are in the linked packet.
- **Final stage.** Remove the `/usr/lib` overlay and keep `COPY /usr/local`.
  The interpreter's other library needs come from a **derived** closure. The
  preflight inventories every Python-base `/usr/local` ELF before any trim,
  classifies only the exact exclusion above, then maps every retained ELF's
  `DT_NEEDED` to its owning Debian package and version. It preserves the
  complete baseline findings and the set of importing `lib-dynload` modules. Packages already in the PostgreSQL base
  stay at its version; only missing packages are installed, at the Python
  base's version, per D3, additions only. The linker cache is regenerated
  only if resolution needs it. The closure is observed, frozen and asserted,
  not a hand-written copy list.
- **Added final assertions:** every `DT_NEEDED` of every ELF under
  `/usr/local` resolves to a `dpkg`-owned file, the CPython tree or an
  installed `RECORD` file; `ldd` reports no missing object or symbol version
  for any of them; with `LD_BIND_NOW=1` every `psycopg-c` extension and the
  same `lib-dynload` set that imports in the Python base imports. The package
  set equals the base set plus the derived closure, with no compiler,
  binutils or `-dev` package. `pip`, `setuptools`, `wheel`, `packaging` and
  `/usr/local/include` are absent; the D2 probe passes; the D7 license
  assets are present. Label `io.repomap.release.psycopg.implementation="c"` is
  added, and `io.repomap.release.libpq` carries the system version.

`RUN --network=none` requires BuildKit. Preflight checks the existing builder's
capabilities without a probe build; the one admitted application attempt
asserts network isolation before backend execution. Unsupported builders
refuse, without fallback or installation. Compose's application services and
the system candidate use this recipe. Compose's separate `postgres` service
continues to use the official pinned image; no server topology changes.
`compose.py`, stage topology, bases, clients, Go helper and entrypoint stay.

### D5. Build inputs and lock owners

- **Sdist inspection, before any backend execution:** hash and size equal the
  sealed values; no traversal, absolute or link entries; `PKG-INFO` gives
  3.3.6 and `LGPL-3.0-only`; `LICENSE.txt`, `pyproject.toml` and
  `build_backend/*` match their resolved tag files (including tag symlinks);
  compare `setup.py` only if present; no `.pyx`; a generated `.c`
  exists for every extension source; no new requirement. It runs once in the
  preflight and again in the release recipe. Other environments are bound to
  the inspected bytes by hash.
- **Generated C** is attributed to the hash-bound release artifact. It cannot
  be regenerated without Cython, which is not authorized, so it is recorded as
  a known supply-chain residual, never as verified.
- **Build-tool pins.** A new hash-locked `psycopg_build.in`/`.lock` holding
  exactly the build closure `setuptools==83.0.0`, `wheel==0.48.0` and wheel's
  one requirement `packaging==26.3` (the version and hashes the tooling lock
  already selected) joins `PYTHON_LOCKS`. The project lock adds `psycopg-c` and
  drops `psycopg-binary`.
- **No isolated build, anywhere.** Every environment installs the hashed build
  tools first, and builds psycopg-c only with `--no-build-isolation
  --check-build-dependencies` and hash-required inputs, so pip never resolves
  an unhashed `wheel` or a substitute. Any install path that builds psycopg-c
  under isolation is a refusal.
- **Lock regeneration.** The pinned generator runs with `--preserve-existing`
  under the earliest `exclude_newer` that admits the approved 3.3.6 files,
  taken from their PyPI upload times. `uv.lock` is updated by the pinned uv
  without `--upgrade`. Only the Psycopg entries and the new build lock may
  change. The `psycopg` and `psycopg-c` hash sets must equal PyPI's published
  sets for 3.3.6 and include the approved hashes. Any other change is a stop.
- **Hash copies.** Release constants and the sandbox Dockerfile embed the same
  hashes as the locks; unit tests assert equality.

### D6. Environments and developer prerequisites

Every environment uses C from the one approved sdist, with no binary or pure
fallback and `PSYCOPG_IMPL` unset. In each, headers and runtime libpq come
from the same distribution source version, and `pq.__impl__ == "c"` is
asserted. The libpq owner differs by environment and is recorded. Only the
release image is product evidence.

| Environment | Python | libpq owner | Change |
| --- | --- | --- | --- |
| Release image | 3.12.13 | PGDG `libpq5` in the PostgreSQL base | D4 |
| Dependency-only test image (`TestImageManager`) | 3.12 slim | The base's configured Debian `libpq5` | In the disposable container: install the compiler, `libc6-dev`, `libpq-dev` and `libpq5` only through the fingerprinted prerequisite helper (resolved, hash-bound and frozen before installation); install the hashed build lock, then the hashed dependencies per D5; purge compiler and `-dev` packages and assert `libpq5` remains; probe `psycopg-c` |
| Test sandbox | 3.13.12 | Debian `libpq5` with `postgresql-17` | Add `libpq-dev`; install the whole native package set only through the hash-checked prerequisite helper; drop psycopg, setuptools and wheel from the unhashed line; a hashed `--no-deps` step installs the build tools and psycopg wheel; an opaque hash-checked sdist fetch and offline build per D5. Recipe identity binds the Dockerfile and helper bytes |
| Hosted unit and pre-review lanes | 3.13 runner | The runner image's packages; no repository added | Acquire or install no system package; verify and record the existing compiler, `libpq-dev` and `libpq5` identities and the PATH `pg_config` binding; install the build lock, then the project lock per D5 |
| Developer hosts | ≥3.12 | The operator's existing libpq and `pg_config` | Document the hash-locked pip route (build lock, then the project lock without isolation, then RepoMap with `--no-deps`) and the uv route (`no-build-isolation-package` plus static `dependency-metadata`); RepoMap installs nothing on hosts |

Sandbox and test-image rebuilds are existing-owner, non-ledger builds. They
are not D12 candidate builds and are not product evidence.

The parent confirms that necessary dependency-install and prerequisite steps
in the two existing hosted workflows are bootstrap owners under the approved
CI-environment acquisition. Triggers, lanes, gates and limits stay unchanged.
Existing `[postgres]` users are told that a
compiler, libpq and `pg_config` are now required. A host suite importing host
Psycopg 3.2.12 is never package compatibility evidence.

### D7. Licenses, notices and supply chain

Dynamic linking is the operator's chosen mechanism. This ADR does **not**
claim that it settles every legal obligation and makes no legal conclusion.

- **License texts.** Psycopg and psycopg-c are `LGPL-3.0-only`. Verbatim
  texts go in `src/main/python/repomap_kg/third_party_licenses/` (`.txt` and
  `.json`), each bound to primary bytes: Psycopg's tagged `LICENSE.txt` and
  the [LGPL-3.0](https://www.gnu.org/licenses/lgpl-3.0.html) and
  [GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html) texts, plus the
  PostgreSQL License notice of `numutils.c`. The wheel ships them as package
  data. The image installs them with the source identity (sdist URL and hash,
  tag commit), the inspected archive itself and its build instructions under
  `/usr/share/doc/repomap-kg/psycopg/`, as it does for Go.
- **[Third-party notices](../../../legal/third-party-notices.md)** record the
  C package form and its dynamic linkage; the system libpq owner and its
  [PostgreSQL License](https://www.postgresql.org/about/licence/); and every
  package the derived closure adds, with its in-image `copyright` file
  present or absent per ADR 0087 P2.
- **Open obligations.** LGPL-3.0 section 4 and GPL-3.0 section 6, including
  source availability for the compiled psycopg-c, are assessed before any
  image or wheel containing it is conveyed. Nothing is conveyed by this phase.
- **Supply-chain review** records the hash binding and sealed metadata, the
  tag comparison, the absence of release attestations (hashes bind identity,
  not publisher trust), the generated-C residual, and each package's
  repository and key.

### D8. Inventory and P3 classification

Each platform's final image is inventoried under ADR 0087 P2, including the
D2 probe and the derived closure. P3 classifies every runtime component: the
system libpq (including CVE-2026-6477 and
[CVE-2025-12818](https://www.postgresql.org/support/security/CVE-2025-12818/)),
Psycopg and psycopg-c 3.3.6, the closure packages, libc and TLS. Primary
sources are PostgreSQL for libpq, the
[Debian security tracker](https://security-tracker.debian.org/tracker/) for
Debian packages and upstream for Psycopg; named secondary CVE records are
also recorded. Libraries the PostgreSQL clients load that differ from the
incumbent image's are part of the P3 comparison.

The base libpq and closure versions are classified **before** any application
candidate build. A
critical, high or unknown-severity `affected` finding, or any `unknown`
runtime finding, stops before a reservation. Missing incumbent application
inventory stays a distinct P3 disposition item; no build is added to create
it. Distribution ownership, banners and inferred backports never imply safety.

### D9. Budget and platform preflight

The ledger, its ceiling (two total, one per platform, no retries, zero used)
and the P3 hold are unchanged; this ADR writes no ledger. Before any
reservation, each platform passes a non-build preflight in the disposable
sandbox:

1. **Executability**: `native` (daemon architecture), `emulated` (existing
   registration observed, never installed) or `non_executable`. amd64 under
   existing emulation is always `emulated`, never native. The candidate is
   built by the fresh inner sandbox daemon, so the host classification is
   only an observation and forecast: neither a native host architecture nor a
   host BuildKit builder proves execution or pinned base availability in the
   daemon that will build. Until a real inner-daemon preflight proves both,
   the host preflight refuses every platform, `native` included, before any
   reservation, consumption or admission.
2. **Base acquisition** by digest of the accepted bases for that platform.
   PostgreSQL config digests must equal the sealed values; Python and Go
   config digests are recorded and sealed.
3. **Inspection containers** (`--network none`) read the libpq version,
   origin, path and hash, the Python-base `DT_NEEDED` closure and its
   importing `lib-dynload` set.
4. **Package resolution and P3 classification** per D3 and D8, and the
   BuildKit check per D4.

A failed preflight refuses that platform without reserving or consuming
anything. Attempts run only after the parent's written P3 disposition
releases the ledger, after the D3 drift recheck, on frozen source and recipe
hashes, at most once per platform. A failed attempt is spent; no budget is
minted. No new emulator, builder, base-image version or tmpfs increase.

### D10. Harness obligations carried from NAVIGATION44

- **Report schema.** The staging report schema becomes
  `repomap-staging-obligations-v2`, which requires `partition.optional`. A v1
  report validates under v1 rules only through an explicit legacy mode and is
  never current qualification.
  `docs/contrib/staging-obligations-acceptance.md` is updated as owner.
- **Optional registry.** `validate_report` pins the registered optional
  reason and node IDs exactly, as discovery does.
- **Cleanup errors.** A deterministic non-build unit test proves that the D12
  node preserves and reports a cleanup-report failure.
- **Unchanged owners.** The twelve deferred build-profile owners, their
  refusals and every debt, coverage and Psycopg type-check ceiling stay
  unchanged; a changed type-check count is a stop, not a ceiling edit.

### D11. Verification plan

All runs are scoped with `--no-coverage`. No complete unit, integration,
smoke, staging, system or coverage suite runs.

- **Unit:** the 18 sealed scoped selectors, plus the owners of touched
  modules: `resource_test_images*`, `resource_test_image_materialization*`,
  `ci2a_generated_drift`, `ci2a_pre_review`, `ci2a_python_type_ownership`,
  `ci2a_unit_tests_contract`, `ci1_static_analysis_contract`,
  `pipe0_topology_contract`, `staging_report_presentation`,
  `test_report_runner`, `test_sandbox_builder`,
  `test_sandbox_image_lifecycle`, `local_runtime` and `package_structure`.
  The retention inventory owner runs only if a new file is enrolled.
- **Integration**, in the authenticated sandbox on the rebuilt 3.13 image so
  it executes C 3.3.6: the 4 sealed core selectors; the 6 sealed dependency
  selectors; and one new owner that materializes the 3.12 dependency-only
  image and probes the D2 points independent of the product libpq owner.
- **Candidate node** `test_d12_core_image_refresh_candidate_round_trip` runs
  only after P3 release, at most once per platform.
- Host Psycopg 3.2.12 results are never package evidence. Historical
  qualification fixtures keep their recorded 3.2.12 values.

### D12. Rollback

Exact pre-change bytes, lock hashes and frozen evidence are retained. If the
new class fails its proof, the checkpoint stays `NOT ACCEPTED` and the hold
stays. Restoring 3.2.12 is not a claim that its bundled libpq 17.6 is safe.
Private retention-history refusals and inherited mypy findings are preserved;
no history, projection or baseline is edited, and a new file is enrolled only
as a zero-debt entry.

## Scope and non-scope

In scope for the later implementation checkpoint in this phase: the D1 to
D11 owners (extra, locks and policy, `uv.lock`, release constants, recipe and
assertions, bootstrap, sandbox and test-image owners, license assets and
notices, D10 corrections, scoped tests, prerequisite docs, status).

Out of scope: static linkage, substitute packaging, Cython, host installs,
`compose.py` or base-image changes, D12-B/P6, pgvector, D15, ledger release,
CI triggers, publication and deployment. The design checkpoint changed only
this ADR and its status record; the implementation checkpoint changed the D1
to D10 owners recorded below.

## What would prove this wrong

- The approved sdist contains `.pyx` sources, lacks generated C, or declares
  an unlisted requirement.
- No exact `libpq-dev` matching the base `libpq5` exists in PGDG's primary
  repository or its official archive, or the base `libpq5` is not from PGDG.
- The extension shows a static libpq, no `libpq.so.5` `DT_NEEDED`, or the
  process maps more than one libpq.
- After the overlay is removed, the clients or the interpreter need bytes
  only the overlay supplied, a symbol version is missing, or `dpkg` ownership
  disagrees with the loaded bytes. A narrow correction would then not exist.
- The base libpq is itself `affected` under P3.
- Hosted runners cannot obtain a matching header/runtime pair without adding
  a repository.

## Consequences

- **Benefits.** libpq advisories, licenses and identity move into the
  `dpkg`-reconciled PGDG and Debian set that D12 inventories. The grafted
  CentOS and AlmaLinux closures leave the product.
- **Costs.** Builds need a compiler and headers; Python headers no longer
  ship. Developers and hosted lanes gain native prerequisites.
- **Product evidence.** Product library loads are observable only in a
  candidate build after the P3 release; earlier results are diagnostic.
- **Performance.** Unmeasured; no performance claim is made.

## Implementation checkpoint (2026-10-22)

`REPOMAP-PRODUCT6-NAVIGATION45-D12DYNAMIC1` implemented D1 to D7, D9 and D10
in one solo producer stage ([the D12 native qualification companion note](../../../../tools/ci/nav46-d12-native-qualification.md)).
It is not an independent review and accepts nothing.

**Implemented.** `psycopg[c]==3.3.6` in the extra, the project lock and
`uv.lock` (only Psycopg entries changed); a new hash-locked
`psycopg_build.lock` then holding only setuptools 83.0.0 and wheel 0.48.0
(the correction checkpoint added wheel's requirement, packaging 26.3);
release constants for the archive, wheel hashes and inspected tag files; the
D4 recipe with an opaque fetch, `RUN --network=none` inspection, offline
no-isolation build, build-time linkage check, no `/usr/lib` overlay, a
hash-verified additions-only package closure and final D2/D4 probe; C
bootstraps for the hosted unit and pre-review lanes, the 3.13 test sandbox and
the 3.12 dependency-only test image; license assets; report and receipt
schema v2 with a pinned optional registry; a cleanup-custody helper; and the
non-consuming platform preflight.

**Unobserved, so the release recipe refuses.** `DYNAMIC_PACKAGE_MANIFEST` is
empty and `PSYCOPG_LIBPQ_VERSION` is `None`. Freezing them requires acquiring
the 16.15 base per platform and resolving its PGDG and Debian packages from
the signed indices. That is sandbox-only preflight work for which this
checkpoint had no executable route. The rendered recipe therefore refuses
before any package fetch or build-backend execution on every platform, and the
host preflight refuses both platforms without consuming a reservation. No
version or hash was guessed.

**Corrections found by execution.** These refine the design and need the
independent review:

1. *D2.1 symbol rule.* psycopg-c defines its own `pg_lltoa` and `pg_ulltoa_n`
   (PostgreSQL-derived `numutils.c`). The literal `PQ*`/`pg_*`/`lo_*` prefix
   rule would refuse every correct build. The implemented rule counts a symbol
   as libpq's only if the actual system `libpq.so.5` exports it; prefix-only
   matches are reported, not refused.
2. *D2.3 `dpkg --verify`.* bookworm-slim bases install with dpkg
   `path-exclude` filters, so `dpkg --verify libpq5` always lists filtered
   docs and locales as missing. The implemented rule ignores only missing
   paths that the image's own dpkg filters exclude. Any other line, or any line
   naming the loaded library, refuses.
3. *D5 lock resolution.* uv's `--no-build` refuses sdist-only packages. Wheel-only
   locks keep `--no-build`. The project lock instead resolves under a
   build-constraint file that no setuptools or wheel release satisfies, so any
   build environment fails before sdist code could run. The successful
   resolution therefore read static metadata only.
4. *Build lock closure (resolved by the correction checkpoint).* wheel 0.48.0
   declares `packaging>=24.0`; the two-pin lock left it unsatisfied, so the
   release recipe's `pip check` would have failed. The parent selected the
   already-locked `packaging==26.3`.
5. *Lock header (resolved by the correction checkpoint).* Moving the shared
   cutoff to `2026-09-18T13:22:58Z` rewrites only the header comment of
   `pre_review_python.lock`; the parent authorized that change.
6. *Harness defect exposed.* The retained runtime-identity evidence file name
   (91 bytes) exceeded the 64-byte scratch category bound once that file was a
   run root's largest entry, failing run close. The name now uses a 16-hex
   fingerprint prefix; the payload keeps the full fingerprint.
7. *Attribution.* `numutils.c` carries PostgreSQL Global Development Group and
   University of California copyright portions; see the notices.
8. *Cancellation capability.* Psycopg 3.3.6 bounds `cancel_safe(timeout=...)`
   only when libpq is 17 or newer, and otherwise calls `cancel()` without the
   timeout. `_staged_ingestion_stages.py` relies on `cancel_safe(timeout=1.0)`.
   The superseded binary pin bundled libpq 17.6. The 3.12 test image's libpq
   15.19 reports `has_cancel_safe()` false. The release base's libpq is
   unobserved. The parent's disposition: the product release probe requires
   it (correction checkpoint); diagnostic environments only record it.

**Observed evidence (diagnostic, not product).** The 3.12 dependency-only test
image built psycopg-c 3.3.6 from the hash-bound sdist against Debian
`libpq-dev 15.19-0+deb12u1` (arm64, native). With `PSYCOPG_IMPL` unset it
loaded C; header and runtime were both 150019. Both extensions have
`DT_NEEDED libpq.so.5` and import 17 and 101 libpq exports, none defined
locally. Exactly one `libpq5 15.19-0+deb12u1` file was mapped, and its filtered
verify was clean. `has_cancel_safe()` was false. This is not the release
base's PGDG libpq.

**Not executed.** The 3.13 sandbox could not be rebuilt from the changed recipe:
BuildKit's client-side token request to `auth.docker.io` was denied by the
producing environment's network policy. So no sealed D9 or dependency selector
ran on C 3.3.6. Hosted lanes, the release recipe, the candidate node, P3
classification, the D3 drift recheck and the per-platform manifest are also
unexecuted. Psycopg 3.3.6 type stubs in the static lane are unverified, and a
changed type-check count is a stop.

## Correction checkpoint (2026-10-22)

The same phase corrected the implementation checkpoint against an advisory
review whose formal transport was refused (one digest-only input lacked its
acknowledgment), so its findings were used as correction input, not as an
accepted review. One solo producer stage made the corrections; it is not an
independent review and accepts nothing.

- **Build closure (H1).** `psycopg_build.{in,lock}` add `packaging==26.3` with
  the hashes the tooling lock already held; the pinned generator reproduces all
  three Python locks byte-for-byte, and the generated policy authority digest
  and the `pre_review_python.lock` header now match. The release recipe,
  sandbox, bootstrap and 3.12 test image install it hash-bound, run
  `pip check` where the recipe or image owns its build closure, and remove all
  build-only tools from the release image and test image.
- **Deterministic package comparison (H2).** The release recipe's
  additions-only check runs `sort` and `comm` under `LC_ALL=C`, the byte order
  of the Python-sorted expectation; the PostgreSQL base sets
  `LANG=en_US.utf8`, where `libpq-dev`/`libpq5` collate differently.
- **Library matching (H3).** The release probe and the candidate owner's
  packaging probe match only shared or static libraries, so psycopg-c's
  installed `psycopg_c/pq/libpq.pxd` is not a private libpq.
- **Fail-closed probes (M1, L4).** Final-probe subprocesses accept only
  documented exit statuses; `dpkg --verify` must exit 0 or 1; `dpkg-query` and
  `ldd` must succeed; static ELFs are recognised from program headers and not
  passed to `ldd`. The D2 dependency probe records the verify exit status, and
  assessment refuses an incomplete verify. The Debian bootstrap requires the
  `ii` state and that `pg_config` and `libpq-fe.h` belong to `libpq-dev` and
  `libpq.so.5` to `libpq5` of one version; an empty or malformed attestation
  refuses with a bounded error. Without `dpkg` the bootstrap refuses
  explicitly, so a darwin-arm64 pre-review bootstrap now stops at that step;
  the hosted lane runs on Ubuntu. The `pg_config` binding is superseded by the
  [prerequisite custody correction](#prerequisite-custody-correction-2026-10-22).
- **Test runtime packages (M2).** The 3.12 dependency-only image records
  added packages (`name=version`) at build and final state and refuses any
  changed or removed pre-existing package. It is a diagnostic cache, not
  release reproducibility. Comparing only after an unversioned install did not
  meet approved item 3; the
  [prerequisite custody correction](#prerequisite-custody-correction-2026-10-22)
  replaces it.
- **Cache identity (M3, L5).** The runtime fingerprint now includes the
  SHA-256 of both locks, of the install/probe program and the native package
  set, replacing the always-null `lock_resolution_input`; evidence schema v2.
  A truncated evidence-name collision or a conflicting observation of the same
  identity refuses; a consistent repeat (built, then reused) is retained beside
  the first rather than dropped.
- **Platform preflight (M4).** See D9: only `native` is admissible before
  consumption. This is an explicit, truthful refusal for amd64, not a
  capability claim; no emulator or builder was added and no attempt spent.
  (Superseded by the [guard correction](#guard-correction-2026-10-22), which
  refuses `native` too.)
- **Install routes (M5).** The README and SQLite Local reference use the
  hash-locked route. `pyproject.toml` sets uv's `no-build-isolation-package`
  for psycopg-c and declares its static metadata. `uv lock` was proved
  backend-free by re-locking under build constraints that no setuptools or
  wheel release satisfies; the result changed only `uv.lock`'s `[manifest]`.
- **Cancellation (M6).** The product release probe requires libpq 17 or newer
  and `has_cancel_safe()`, and the manifest validator refuses an older frozen
  libpq. Diagnostic and developer environments with older libpq only record
  the capability; that is not product compatibility. Storage code is
  unchanged.
- **Manifest validation (L1).** The frozen manifest must name builder
  `libpq-dev` and `libpq5` at the runtime `libpq5` version, and must carry
  well-formed digests, fingerprints, trust paths, package fields, library path
  and module names.
- **Legacy reports (L2).** See D10. `--legacy-v1` reports `"rules": "v1"` and
  `"current_qualification": false`.
- **Licensing (L3).** A new asset reproduces the `numutils.c` notice verbatim
  with the PostgreSQL License text from the PostgreSQL 13.0 tag (matching
  years); the tag copy of `numutils.c` equals the archive's. License URLs use
  the tag commit. The wheel ships the assets as package data; the release image
  also keeps the inspected source archive and build instructions. The approved
  gnu.org fetch was refused by the producing environment's network policy, so
  the GPL text remains Debian's. No legal conclusion is made, and no generic
  approval gate is added.

The release recipe still refuses before any package or backend work, because
the manifest remains unobserved. See
[the D12 native qualification companion note](../../../../tools/ci/nav46-d12-native-qualification.md)
for the exact verification.

## Prerequisite custody correction (2026-10-22)

Approved bounded-phase item 3 admits the compiler, header and libpq closure
only with exact package versions, repository provenance and hashes resolved
**before** installation, refusing unrelated upgrades or unresolved ABI or
provenance. The correction checkpoint's test image still installed unversioned
and compared afterwards, and the sandbox installed unversioned; a diagnostic
label does not waive the condition. A third solo `claude_only` stage, not an
independent review, corrected this. NOT ACCEPTED.

- **One stdlib helper.** `tools/test_sandbox/apt_prerequisites.py` is the only
  native acquisition path of the disposable sandbox and the 3.12 dependency-only
  test image. It uses only the repositories and keys apt already trusts. After
  `apt-get update` acquires signed metadata, it:
  1. snapshots the dpkg database (any half-installed state refuses) and pins a
     requested package that is already installed to its installed version;
  2. simulates the transaction and refuses any upgrade, downgrade, reinstall,
     removal, foreign architecture, unrecognised line or `Inst`/`Conf`
     mismatch;
  3. binds each selected name, version and architecture to exactly one size and
     SHA-256 identity in the `Packages` indexes that `apt-get indextargets`
     reports as `Trusted: yes`, recording origin, label, suite, codename,
     component, repository and `Signed-By`. No record, two identities, an
     untrusted or unreadable target, or a missing SHA-256 refuses; MD5 is never
     a substitute;
  4. downloads only those archives into a private, initially empty cache and
     matches every cached file to one manifest entry by size, SHA-256 and
     `dpkg-deb` control fields; a missing or extra archive refuses;
  5. freezes the manifest (canonical JSON digest, read-only archives),
     re-verifies the archives and the unchanged dpkg state, installs exactly
     those `name=version` archives with `--no-download` from that cache, marks
     unrequested packages automatic, and rechecks that every pre-existing
     package is unchanged and the additions equal the manifest.

  Its evidence records current repository resolution and exact additions. It
  is not release reproducibility, the application package manifest or P3
  admission, and it adds no key, repository, parser dependency or fallback.
- **Sandbox identity.** The Dockerfile copies the helper, checks it against
  the `REPOMAP_SANDBOX_APT_HELPER_SHA256` build argument, installs its whole
  existing package set only through it, and keeps
  `/usr/local/share/repomap/apt-prerequisites.json`. A Dockerfile-only recipe
  keeps its file digest. A recipe that names the helper is identified by a
  `repomap-sandbox-recipe-v2` digest over both files' SHA-256 values, carried by
  the recipe label (inspection reuses only an exact match) and an `apt-helper`
  label. The checked-in `.dockerignore` admits only the Dockerfile, so builds
  stage exactly the hashed bytes in a fresh private context.
- **Test-image identity.** `materialization_inputs` adds
  `apt_prerequisites_sha256`. The manager reads the locks and helper once; the
  materializer executes that snapshot's helper text in-process after checking
  its digest, and refuses before creating a container if the snapshot differs
  from the fingerprint. Later checkout edits cannot reach a fingerprinted run.
- **Hosted lanes.** `psycopg_bootstrap.py` acquires and installs no system
  package. It records the runner image's `gcc`, `libc6-dev`, `libpq-dev` and
  `libpq5` dpkg identities and uses the helper's attestation. Custody of those
  packages is the runner image's. Only workflow comments changed; steps,
  triggers, lanes and limits are unchanged.
- **`pg_config` attestation.** `--bindir` reports a configured directory, not
  necessarily the invoked executable. Every owner now binds the PATH-resolved
  `pg_config`, after `realpath`, to its single installed package, which must
  come from the same source package and version as the one installed
  `libpq-dev`/`libpq5` pair. It separately binds the selected `--includedir`
  header to `libpq-dev` and the `--libdir` runtime library to `libpq5`.
  Diversions or several owners refuse. No Darwin packaging authority is added;
  the Debian-only pre-review limitation stays unqualified pending parent review.

Observed offline, without running a container, from the dpkg database layers of
the local NAVIGATION44-era sandbox image `sha256:f03e67257c19…`:

- The pinned Python 3.13.12 slim base layers hold `libc6` `2.41-12+deb13u2`; the
  image's final state holds `2.41-12+deb13u3`, with `libc6-dev` at the same
  version. The old unversioned install upgraded a pre-existing package. The
  helper is therefore expected to refuse this sandbox transaction before
  installation whenever current metadata cannot pair `libc6-dev` with the
  base's `libc6`. Approved official historic repositories under existing keys
  could remedy that; this checkpoint adds no archive values or fallback.
- `/usr/bin/pg_config` belongs to `postgresql-common` 278 there, and
  `/usr/lib/postgresql/17/bin/pg_config`, first on the sandbox `PATH`, to
  `postgresql-client-17` (source `postgresql-17`, the `libpq5` source). A host
  whose `PATH` resolves the `postgresql-common` wrapper therefore refuses;
  whether hosted runners do is unobserved.

This would be wrong if live apt emitted simulation, `indextargets` or index
fields other than the forms the unit doubles exercise. That has not been run
against a real Debian apt here; the expected effect of such a difference is a
refusal before installation, not an unverified install.

Coverage and incumbent evidence: the old hosted candidate `a00e3c60` measured
81.849939% integration branches, 30 branches short of the 82% aim. Coverage
of this changed source is unmeasured, and scoped `--no-coverage` runs support
no whole-population percentage. Incumbent evidence comprises a partial arm64
static inventory and the hash-bound component versions executed by the old
hosted amd64 run 39772826111; neither is a complete native closure, and the
absence of a local amd64 image is not an absence of all amd64 evidence. P3
remains unreleased, the build hold stays at `maximum_total` 0 with the original
two-total, one-per-platform, no-retry ceiling and zero attempts used.

## Final refusal correction (2026-10-22)

The parent's review of the helper found five gaps in the preinstallation
contract and asked that dependency selection preserve existing versions. A
fourth solo `claude_only` stage, not an independent review, corrected the
helper. NOT ACCEPTED.

- **Error-flagged state.** A dpkg row must have exactly the three-character
  `${db:Status-Abbrev}` `ii ` or `rc `. A set error flag, such as `iiR`,
  refuses.
- **Missing request.** Every requested package that is not already installed
  must appear in the simulated additions. An empty or partial simulation
  refuses and is no longer a no-op success.
- **Repository provenance.** `Trusted: yes` is not enough. Each `Packages`
  target also needs a non-empty `Repo-URI` and `Origin`, and a `Suite` or
  `Codename`. These are the fields the helper already records from
  `apt-get indextargets`. `Signed-By` is recorded when present and is not
  required, because a source can be trusted without it.
- **Archive identity.** Distinct selections must have distinct SHA-256 values
  and pool file names. If they do not, the helper refuses before download.
  Archive verification also refuses a manifest whose entries share a SHA-256.
- **Final removal.** The `--download-only` and final `--no-download` installs
  pass `--no-remove`, so APT aborts any removal it would plan at install time.
  The dpkg snapshot and post-install recheck remain.
- **Baseline-preserving selection.** The simulation now holds every installed
  package (`ii` rows only) at its installed version as `name=version`. Native
  and `Architecture: all` rows are unqualified; a foreign-architecture row is
  `name:arch=version`. Any closure APT selects from its existing trusted
  metadata must therefore leave that state unchanged; otherwise the simulation
  fails and the helper refuses before download. The final install pins only
  the frozen additions, so pre-existing packages are neither reinstalled nor
  remarked. (Superseded: the install now also names the holds, which APT marks
  manual; see the [manual-flag correction](#adjacent-double-and-manual-flag-correction-2026-10-22).)
  The pre-existing-change and removal refusals, the private verified
  cache, the exact pins and `--no-download` all remain. There is no upgrade
  permission, new repository, key, guessed version or archive fallback.

The unit double resolves exact dependencies over real archive bytes. Under the
baseline holds it selects an older `libc6-dev` matching the base's `libc6`.
Without the holds it upgrades `libc6`, and it refuses an unsatisfiable set.
That shows the helper's contract, **not** live APT behaviour. Whether apt's
resolver chooses an older non-candidate addition when held packages conflict
with the newest candidate is unobserved. If it does not, the observed
`2.41-12+deb13u2` base refuses before installation, as before.

**M4 not corrected.** A host native classification proves neither execution
nor pinned Python and Go base availability in the fresh inner daemon that
builds the candidate. The host preflight should therefore refuse every
platform, native included, until a same-inner-daemon preflight exists. This
stage did not make that change, because the existing out-of-scope owner
`test_runner_safety3_build_policy.unit.test.py` asserts that native
preflight succeeds. The native path remains a known gap. Today the held
ledger (`maximum_total` 0) refuses any reservation. The positive inner-daemon
preflight is unimplemented and unqualified. (Superseded by the
[guard correction](#guard-correction-2026-10-22).)

## Guard correction (2026-10-22)

The parent widened the write scope to the M4 owners and asked for exact
dynamic-loader governance and safe APT failure diagnostics. A fifth solo
`claude_only` stage, not an independent review, made these changes. NOT
ACCEPTED.

- **M4 platform guard.** The host preflight now refuses every platform,
  `native` included, with a reason that names the fresh inner build daemon.
  Its record keeps the host classification only as `host_forecast` and marks
  `inner_daemon_execution` and `inner_base_availability` as `unproved`, with
  `consumed: false`. The runner facade calls it before `admit_profile`, so on
  the host no platform reaches admission or consumption. A canonical-facade
  regression uses a populated synthetic manifest, a native daemon
  (`aarch64` and `x86_64`) and a BuildKit builder, and proves that
  `admit_profile` is never called and the ledger bytes are unchanged. The
  positive inner-daemon preflight remains unimplemented and unqualified. This
  is a truthful stop. It is not D12 readiness, admission or platform
  qualification.
- **Dynamic loaders.** The `d12_apt_prerequisites` unit owner now reuses
  `ci.psycopg_bootstrap.apt` and has no dynamic operation of its own. The
  remaining `spec_from_file_location` chain in `tools/ci/psycopg_bootstrap.py`
  is intentional: `tools/test_sandbox.py` shadows the helper's directory, so
  the helper is not importable. The existing closed `file_loader_spec` recipe
  cannot credit it. The real `validate_boundary` refuses every probe with
  "closed recipe has no maintained owner contract", because the recipe's
  cases and owner contracts are closed policy code. So no dynamic-boundary
  record was added, and the inventory is unchanged. The loader stays
  explicit, undeclared and blocking; it is not accepted debt. The same audit
  found an out-of-scope builtin `compile(...)` in
  `d12_dynamic_linkage.unit.test.py` that also blocks acceptance.
- **APT failure diagnostics.** A failed helper command now reports a bounded
  tail of its stdout and stderr: the last 40 non-empty lines, cut to 4000
  characters. The whole output is redacted first. Redaction covers
  secret-bearing lines, URLs, `user@host` credentials, absolute paths,
  hostnames, IP addresses, values of sensitive or long environment variables
  and control characters. The command prefix and the CLI's printed refusal are
  redacted too. Package names, versions and dependency constraints survive.
  There is no retry, relaxed hold, install-on-error, guessed version or archive
  fallback. The five custody fixes, archive byte and control checks, and the
  unchanged-before/after rechecks are unchanged.

The `apt-get install --simulate` exit 100 the parent observed is still
unexplained. A solver or metadata conflict with the `2.41-12+deb13u2` base
is a hypothesis. The new diagnostics only make the next attempt's cause
observable.

## Import correction (2026-10-22)

The parent asked for an ordinary helper import, end-to-end safe and useful
APT diagnostics, and truthful testing guidance. A sixth solo `claude_only`
stage, not an independent review, recorded this private-tool organization
before implementing it. It stays within the approved shared-helper design.
NOT ACCEPTED.

- **Private tool organization.** The stdlib-only implementation moves to
  `tools/native_apt_prerequisites.py`, an ordinary module under the tool root.
  It stays self-contained: it imports only the standard library and nothing
  from the repository. `tools/test_sandbox/apt_prerequisites.py` remains a
  small static compatibility CLI wrapper. It sets up the tool root the same
  way other `tools/` scripts do and calls the canonical `main`, so its path,
  inventory record and command line are unchanged.
  `tools/ci/psycopg_bootstrap.py` imports the canonical module with an
  ordinary static import, and the tests reuse that module. No
  `spec_from_file_location`, `exec`, `compile` or other host-side loader
  remains. This is private tooling. The public CLI, test-runner policy and
  retention policy code are unchanged.
- **Executed bytes.** Containers never receive the wrapper. The sandbox
  builder reads the canonical module's bytes and stages them under the
  existing context basename `apt_prerequisites.py`. Their digest still joins
  the `repomap-sandbox-recipe-v2` manifest under that name. It is also passed
  as `REPOMAP_SANDBOX_APT_HELPER_SHA256`, which the Dockerfile rechecks, so
  the identity binds the bytes that run. The dependency-image materializer
  reads, fingerprints (`apt_prerequisites_sha256`) and executes the same
  canonical text in-process after its digest check. The v2 schema, labels,
  absent-file refusal and snapshot refusal are unchanged. Changed bytes select
  a new recipe and a new cache fingerprint. No old image is relabelled or
  reused.
- **Diagnostic rendering.** Redaction must be idempotent. The
  greedy secret-line rule erases the rest of a line, and the old markers
  `<secret>` and `<credential>` matched that rule. The CLI then redacted the
  already joined tail a second time, so the first marker erased every later
  line, including any dependency constraint. The new markers (`<redacted>`,
  `<userinfo>`) match no rule, and each redaction repeats its rules until the
  text is stable. A second pass therefore changes nothing. The CLI still
  redacts every refusal it prints, including raw messages that no command
  produced. A tail longer than the bound is cut at a line boundary, so the cut
  cannot form a new word. Redaction also covers bare IPv6 addresses (validated
  with the standard `ipaddress` module), APT's `[IP: address port]` form, and
  single-label host names after APT's resolve and connect phrases or in
  `name:port` form. A redaction run still happens before bounding.

Outcome, as implemented. NOT ACCEPTED.

- The canonical module is 400 lines and the wrapper 21. The bootstrap's
  loader is gone. The real `dynamic_operations` and `build_dependency_graph`
  functions report no dynamic operation, dynamic uncertainty, unresolved
  import or graph error in the 57 Python paths of the D12 candidate. The
  bootstrap and the wrapper both resolve statically to the canonical module.
  The retention inventory gained only two clean cohorts and two file records
  for the new module and its test owner. Every earlier record is unchanged.
- The static import made the helper's real signatures visible to type
  checking. Evidence results are now typed as JSON-shaped
  `dict[str, Any]`, and test doubles return real `CompletedProcess` objects.
  There is no suppression.
- A URL is now redacted as its whole whitespace-delimited token. Without that,
  an environment value replaced first, such as a sensitive variable holding
  `http`, could stop the URL rule from matching.
- The `compile(...)` call in `d12_dynamic_linkage.unit.test.py` is replaced by
  `ast.parse` inspection of the probe's top-level imports and its
  `__main__`/`probe` entry point. The probe module itself is still covered by
  compile and static checks. Running the generated probe is still an
  integration gate.
- The [guard correction](#guard-correction-2026-10-22) claimed redaction of
  "IP addresses". In fact it covered only IPv4 and bracketed IPv6.
- The testing standard and its skill now say that every platform, native
  included, refuses before consumption, and that the positive same-inner-daemon
  preflight is unimplemented and unqualified.
- **Process limitation (guard-correction review).** The guard-correction
  producer did not print its full handoff. Its reviewer read the actual
  changed repository files instead, and the parent supplied full hash and body
  custody. That checkpoint makes no claim to a fully sealed post-result
  transport.

The cause of the `apt-get install --simulate` exit 100 is still unobserved.
No package, archive, solver or pin was changed, and the libc
`2.41-12+deb13u2`/`deb13u4` hypothesis was not acted on. The build hold, the
budget and all acceptance flags are unchanged.

## Archived header correction (2026-10-22)

A seventh solo `claude_only` stage, not an independent review, recorded this
plan here before changing any code. It applies the approved decision's item 3
and [D3](#d3-libpq-ownership-and-abi): an exact version that only the
vendor's official historical archive still holds may come from that archive
under the same keys. NOT ACCEPTED.

**Observation (parent, before this stage).** The SDK's
`apt-get install --simulate` exited 100. The current repositories offer
`libc6-dev` `2.41-12+deb13u4`, which needs `libc6` `deb13u4`, and
`libssl-dev` `3.5.7-1~deb13u3`, which needs `libssl3t64` `3.5.7-1~deb13u3`.
The pinned Python 3.13.12 base has `libc6` `2.41-12+deb13u2` and `libssl3t64`
`3.5.5-1~deb13u1`, and the helper holds them. Both platform bases' `debian.sources`
comments name the snapshot `20260406T000000Z`. Debian's snapshot service has
the matching `libc6-dev` and `libc-dev-bin` `2.41-12+deb13u2`, and
`libssl-dev` `3.5.5-1~deb13u1`, for arm64 and amd64. Their index hashes match
the snapshot `InRelease`. The host did not verify the signature, so APT must
do that inside the SDK.

**Plan.** The only source change is in `tools/test_sandbox/Dockerfile`, in
the RUN that installs native prerequisites. It uses POSIX `/bin/sh` syntax,
and each step is joined with `&&`, so any failure stops the build before the
helper or any installation:

1. Check the staged helper's digest (unchanged).
2. Check that `/usr/share/keyrings/debian-archive-keyring.pgp` has SHA-256
   `506b815cbb32d9b6066b4a2aa524071e071761e7e7f68c3ac74f3061ba852017`. Both
   platform bases have this keyring. A mismatch stops before APT runs.
3. Set `noclobber`, then write two new files. A file of the same name makes
   the build stop, so no existing file is replaced:
   - `/etc/apt/sources.list.d/repomap-snapshot-20260406.sources`, a deb822
     source for `https://snapshot.debian.org/archive/debian/20260406T000000Z/`,
     suite `trixie`, component `main`. It is `Signed-By` the same keyring
     file. `Check-Valid-Until: no` applies only to this dated source, because
     an archived `Release` file is past its validity date. Signature and hash
     checks stay on. No `Trusted`, `allow-insecure` or global option is set.
   - `/etc/apt/preferences.d/repomap-snapshot-headers.pref`. It pins exactly
     `libc6-dev` and `libc-dev-bin` `2.41-12+deb13u2` and `libssl-dev`
     `3.5.5-1~deb13u1` at priority 999, and gives everything else from the
     host `snapshot.debian.org` priority 100. APT uses the first matching
     package-specific record, so the specific records come first. Priority
     999 is below the downgrade threshold of 1000. Current repositories keep
     their default 500, so every other package still comes from them.
4. Run the helper exactly as before. Its arguments are still plain package
   names. It still refreshes indexes and holds every installed version. It
   simulates before installing and binds each archive to one trusted index
   identity. If APT cannot verify the snapshot index, the index refresh
   fails or the index is untrusted, and the helper refuses. It verifies each archive's size, hash and control
   fields, then checks that no installed version changed.

The base's `debian.sources`, its keyrings and its trust model are unchanged.
No other package, version, key, image, Python or lock pin changes. Old libpq
and PostgreSQL versions are not pinned, and no downgrade, held-package or
unauthenticated flag is added. The configuration is fixed text inside the
hash-bound Dockerfile, so it adds no new context file. The build frontend,
stages and staged context names are unchanged. The Dockerfile's bytes change,
so the existing recipe-v2 manifest selects a new recipe and cache key.

**Tests.** `staging_report_contract.unit.test.py:341` passes the three
identities by keyword instead of `**dict[str, str]`, which mypy cannot match
to `legacy_v1: bool`. All three negative cases remain. The builder test owner
runs the real RUN text under `sh` in temporary paths, with a hashing double
and a helper double. It shows that a wrong keyring stops before the helper and
writes nothing; that a correct keyring writes the exact source and pins
before the helper runs; that the helper's error code reaches the shell and
skips cleanup; and that an existing file of the same name stops the build.
These tests check the order of the shell steps. They do not prove a
signature, APT's pin behavior or an install.

**Limits.** Taking these headers from the archive solves only this
prerequisite. It does not accept the runtime, its security fixes or P3. The
older headers match the base's older runtime libraries, which this stage does
not change. The parent will run at most one exact diagnostic SDK attempt after
it closes the writer.

Outcome, as implemented. NOT ACCEPTED.

- The Dockerfile follows the plan. It grew from 106 to 128 lines, and the
  helper and its arguments are unchanged. The recipe-v2 identity changes from
  `36cf4dd1…` to `dce07683…` because the Dockerfile's bytes changed. Nothing
  was relabelled, and no image was built.
- The mypy finding at `staging_report_contract.unit.test.py:341` is gone. The
  file is still 400 lines, and its three negative cases are unchanged.
- The builder test owner has two new tests. They found a real fault in a
  mutation run: when the keyring check was joined with `;` instead of `&&`,
  a wrong keyring no longer stopped the build. Execution under `sh` covers
  only step order and exit codes. No real APT, signature, pin, network or
  install ran.
- Whether APT verifies the snapshot `InRelease` with this keyring, and whether
  the pins resolve the whole transaction, is still unobserved. Other packages
  in the transaction may still conflict with the base's runtime versions.
  This is the parent's single diagnostic attempt to observe. The build hold,
  the budget and every acceptance flag are unchanged.

## Perl prerequisite correction (2026-10-22)

An eighth solo `claude_only` stage, not an independent review, recorded this
plan here before changing any code. It acts on the archived header review's
advisories A2, A3 and A5, under the same approved native prerequisite class
and [D3](#d3-libpq-ownership-and-abi). No new class, key, base, image, Go,
Python, lock, metadata or policy change. NOT ACCEPTED.

**Observation (parent, before this stage; arm64 only).** A host-metadata
check compared exact (`=`) dependencies of selected index records with the
installed base versions. It is an equality comparison, not an APT solver, and
the host did not verify any `InRelease` signature. The index tables were bound
to the `InRelease` SHA-256 lines it read. In the current `trixie` index,
`perl` `5.40.1-6+deb13u1` needs `perl-base (= 5.40.1-6+deb13u1)` and
`libperl5.40 (= 5.40.1-6+deb13u1)`. The pinned base has `perl-base`
`5.40.1-6`, which the helper holds, and does not have `perl`, `libperl5.40`
or `perl-modules-5.40`. `git` and `postgresql-common` need `perl`. The base's
dated snapshot (`20260406T000000Z`) holds these records:

| Package | Version | Arch | Relevant Depends | `.deb` size | SHA-256 |
|---|---|---|---|---|---|
| `perl` | `5.40.1-6` | arm64 | `perl-base (= 5.40.1-6)`, `perl-modules-5.40 (>= 5.40.1-6)`, `libperl5.40 (= 5.40.1-6)` | 267336 | `68e82fa4deba7c9dc6b58c73f79b514f77521435b379e5680b8b8adfcd1d2b33` |
| `libperl5.40` | `5.40.1-6` | arm64 | `perl-modules-5.40 (>= 5.40.1-6)` | 4142100 | `3ae323c6210a7844fb96aedec078b11a9d52405d77ef3adc4e5d4b55bce235e2` |
| `perl-modules-5.40` | `5.40.1-6` | all | `perl-base (>= 5.40.1-1)` | 3019100 | `dfd42c1bf0c45858488ad666b90de17f81b55e6f9c0d8ca530c27b4a66c08b0b` |

Only `perl` has an exact (`=`) dependency on `perl-base`, and it matches the
base's `5.40.1-6`. `perl-modules-5.40` needs `perl-base (>= 5.40.1-1)`, which
the base satisfies, and `libperl5.40` has no `perl-base` dependency. (Wording
clarified by the [byte identity correction](#byte-identity-and-python-312-header-correction-2026-10-22)
for review advisory P3; the pin selection is unchanged.) amd64 records were
not observed.

**Plan.** As before, the only recipe change is in the native-prerequisite RUN
of `tools/test_sandbox/Dockerfile`. It stays POSIX `/bin/sh`, with every step
joined by `&&`.

1. **Three more exact pins (A2).** The pin file gains `perl`, `libperl5.40`
   and `perl-modules-5.40` at version `5.40.1-6`, priority 999. They follow the
   three header records and come before the `Package: *` origin record. These
   packages are not installed in the base, so 999 cannot downgrade anything.
   `perl-base` and every other installed package stay held exactly by the
   helper; nothing installed is pinned, upgraded or downgraded. The three
   header pins, the source, the keyring digest check, the hold, the
   simulation, the trusted-index binding, the archive size, hash and control
   checks and the final checks are unchanged.
2. **Transaction-only archive configuration (A3).** The dated source and the
   pin file are needed only while the helper resolves and installs. After the
   helper succeeds, the same RUN removes exactly those two files with plain
   `rm` (no `-f`, no glob), then runs the existing list cleanup. If the helper
   fails, `&&` skips both removals and the list cleanup, the RUN exits with the
   helper's status, and no layer is committed. A diagnostic build keeps the
   files and lists in its failed build context only. There is no broader
   cleanup, no new source or context file and no helper or parser change.
3. **Accurate custody text (A5).** The recipe comment says the helper
   resolves against the base's configured repositories plus the one declared
   dated historical source, under the base's keyring. The recipe binds the
   keyring file's SHA-256. A byte-identical keyring file holds the same key set
   the base already trusts, so the source adds a URL, not trust. This stage
   did not recompute key fingerprints and claims none.

The priority-100 origin record is not a resolver fallback: classic APT
considers one candidate version per package. These pins cover only the exact
conflicts that the equality check found. They do not prove the whole
transaction resolves.

**Tests.** The builder test owner checks all six specific pins and the origin
record exactly, and checks the cleanup step's text and position. Running the
real RUN text under `sh` with doubles in temporary paths, it shows that the
helper sees the exact source and pins before it runs; that success removes
both files and the lists but keeps other APT files; that a helper error keeps
both files and the lists; and that a wrong digest still stops before any
write or helper call. These checks cover shell order and exit codes only.

Outcome, as implemented. NOT ACCEPTED.

- The Dockerfile follows the plan. It grew from 128 to 136 lines: three pin
  records, the two-file removal and the corrected comment. The helper, its
  arguments and every guard are unchanged. The recipe-v2 identity changes from
  `dce07683…` to `088a3718…` because the Dockerfile's bytes changed. No image
  was built.
- The builder test owner grew from 209 to 219 lines. Its two archived-header
  tests now check the six pins, the origin record and the exact cleanup tail.
  Against the entry Dockerfile, 3 of its 10 tests failed. A mutation that
  joined the cleanup with `;` instead of `&&` also failed 3, including the
  helper-error case and the existing-file case, where the cleanup would have
  removed an operator's file.
- Still unobserved: whether APT verifies the snapshot `InRelease` with this
  keyring, whether the whole transaction resolves, and the amd64 Perl
  records. Other transaction packages may still need newer base versions. The
  build hold, the budget and every acceptance flag are unchanged.

## Byte identity and Python 3.12 header correction (2026-10-22)

A ninth solo `claude_only` stage, not an independent review, recorded this
plan here before changing any code. It acts on the Perl correction review's
finding P1 and on the parent's Python 3.12 follow-up, under the same approved
native prerequisite class and [D3](#d3-libpq-ownership-and-abi). No new class,
key, source, base, image, Go, Python, lock, metadata or policy change, and no
new file. NOT ACCEPTED.

**Observation P1 (review, from supplied arm64 metadata).** The current
`trixie` main and security indexes both list `postgresql-17` and
`postgresql-client-17` `17.11-0+deb13u1` with the same size and SHA-256
(`16181424` `7565afa5…82fe`; `2018616` `68186414…43b7`) but different
repository-relative `Filename` values: `pool/main/p/…` and
`pool/updates/main/p/…`. The helper keyed identity on SHA-256, size **and**
`Filename`, so it would refuse these two selections with "2 trusted index
identities" before any download. Step 3 of the
[prerequisite custody correction](#prerequisite-custody-correction-2026-10-22)
says "exactly one size and SHA-256 identity"; the code also required one
`Filename`. The source and this ADR disagreed. This correction makes the code
follow the ADR.

**Plan A, trusted byte identity.** In `tools/native_apt_prerequisites.py`,
`bind_to_trusted_index` only:

1. A selection's identity is its SHA-256 and size. A `Filename` is a location
   of those bytes in one trusted index, not part of their identity.
2. Every matching record in every `Trusted: yes` target with resolved
   provenance contributes one location: its `Filename` together with that
   target's recorded origin fields (origin, label, suite, codename,
   component, repository and `Signed-By`). Each manifest package keeps all its
   distinct locations, sorted, in a new `locations` list, so each path stays
   paired with the index that advertised it. Nothing is chosen or dropped.
3. The existing `filename` field stays for compatibility. It is the least
   `Filename` among the locations, and the manifest and evidence gain a
   `filename_role` text that says so: a canonical diagnostic value, not the
   path or mirror APT fetched. APT chooses the mirror; the helper binds bytes.
   The existing per-package `origins` list is unchanged.
4. Refusals are kept or tightened. Two different SHA-256 values or sizes for
   one name, version and architecture still refuse as ambiguous. No record
   still refuses. An untrusted target, or a target without `Repo-URI`,
   `Origin` and `Suite` or `Codename`, still refuses before any index is read.
   A missing or malformed SHA-256 or size still refuses, and MD5 is never a
   substitute. New: a matching record without a `Filename` refuses, because
   its location is unknown. Distinct selections still may not share a
   SHA-256, and now may not share any location path.
5. Unchanged: name, version and architecture matching, simulation, holds,
   download into the private cache, archive size, SHA-256 and control checks,
   the manifest freeze and read-only archives, the before and after state
   checks and `--no-download` installation. Archive verification already keys
   on SHA-256 and size. The schema name stays
   `repomap-apt-prerequisites-v1`; the change only adds fields. Consumers were
   inspected: the materializer and the D12 linkage integration owner read
   `manifest_sha256`, `added` and attestation fields, and nothing reads
   `filename`.

**Observation (parent, Python 3.12 base, read-only, before this stage).** Both
approved Python 3.12 base architectures hold `libssl3` and `openssl`
`3.0.20-1~deb12u2`, `libc6` `2.36-9+deb12u14` and `perl-base`
`5.36.0-7+deb12u3`. The configured current Bookworm main index still lists
`libssl-dev` `3.0.20-1~deb12u2` (arm64: `2312256` bytes,
`c6941a83bebd83d2a1cd2db56418062d8f48b3200786aacafa194b75a93a3702`), which
needs `libssl3 (= 3.0.20-1~deb12u2)`. The security index's newer candidate
`3.0.22-1~deb12u1` needs `libssl3 (= 3.0.22-1~deb12u1)`, an installed-library
change that the helper refuses. That is an equality comparison of index
metadata, not an APT solver or an install. The host did not verify signatures.
Main's `libc6-dev` matches the base; security's older `deb12u7` is not the
candidate. This materializer requests only `gcc`, `libc6-dev`, `libpq-dev` and
`libpq5`, so no Perl pin is planned here.

**Plan B, exact header preference.** In the existing fingerprinted
`_INSTALL_AND_PROBE` program of `resource_test_image_commands.py` only:

1. A small self-contained function reads the actual dpkg state that the
   program already captures. Only when the installed `libssl3` versions are
   exactly `{3.0.20-1~deb12u2}` does it create
   `/etc/apt/preferences.d/repomap-libssl-dev-header.pref` with exclusive
   create (no clobber). The file holds exactly one record: `Package:
   libssl-dev`, `Pin: version 3.0.20-1~deb12u2`, `Pin-Priority: 999`. Any
   other state, including another version or no `libssl3`, writes nothing.
   Another runtime base therefore gets no pin.
2. An existing file of that name raises before the helper runs, so nothing is
   overwritten and nothing is installed.
3. The helper then runs unchanged, with the same plain package names. APT
   selects `libssl-dev` from the configured main repository and authenticates
   its index as usual. The helper still holds every installed package, binds
   the archive to its trusted size and SHA-256, verifies it and refuses any
   change to installed packages. Priority 999 is below the downgrade threshold
   of 1000, and `libssl-dev` is not installed in the base.
4. After the helper returns successfully, the program removes exactly the
   file it created and nothing else. If the helper refuses, the file stays for
   diagnosis, the program fails and no image is committed.
5. No archive URL, key or source is added. No `libc6`, Perl or other package
   is pinned. The helper's names-only command line is unchanged. There is no
   fallback, retry or upgrade. The program's digest is already part of the
   cache fingerprint (`install_and_probe_sha256`), so the change selects a new
   cache image and stale reuse refuses.

**Tests.** The helper owner `d12_apt_prerequisites.unit.test.py` runs the full
install over real archive bytes with an extra trusted security target that
lists `libpq5` at a second path with the same bytes. The positive case must
bind once, keep both locations with their own suites, and freeze them in the
manifest. Negative cases change the alias's SHA-256 or size, mark its target
untrusted, drop its target's `Origin`, or drop its record's `Filename`; each
must refuse before download. The materializer owner's existing generated-prefix
test runs the real header function through the same subprocess call, with
temporary destinations: the exact state writes the exact pin; another state
writes nothing; an existing file refuses and keeps its contents. A structural
check fixes the order: create, then the helper, then removal, then the
attestation. Neither proves APT pin behavior, signature checks, resolution or
an install; the parent's later exact integration owner observes those.

Outcome, as implemented. NOT ACCEPTED.

- The helper follows plan A and stays at 400 lines. One joined `raise`
  line and a list comprehension for the existing per-target origin records
  made room; neither changes behavior. Its SHA-256 changes from
  `d6b8b396…` to `5341768c…`. The sandbox Dockerfile is unchanged, but the
  recipe-v2 identity, which hashes the helper too, changes from `088a3718…`
  to `d75b377f…`. No image was built or relabelled.
- The materializer follows plan B. The install program's digest changes from
  `0bf56761…` to `11af7627…`, so the runtime cache fingerprint changes.
- Against the entry helper and materializer, the new tests failed in 3 cases:
  the alias positive case, the missing `Filename` refusal and the header
  test. The size, untrusted-target and missing-`Origin` alias cases passed
  there too: those refusals already existed and are kept. Mutations each
  failed their tests: pairing every path with the first index's origin; not
  refusing an empty `Filename`; opening the pin file with overwrite; pinning
  when any installed `libssl3` matches; and removing the pin before the
  helper runs.
- Unchanged and still unobserved: real APT selection under the pin and with
  aliased indexes, signature checks, whole-transaction resolution, amd64
  records and every image. A pre-existing preferences file in the base that
  names `libssl-dev` could change APT's choice; the helper's holds and
  checks would still refuse any change to installed packages. The build hold,
  the budget and every acceptance flag are unchanged.

## Installed-package hold correction (2026-10-22)

A tenth solo `claude_only` stage, not an independent review, recorded this
plan here before changing any code. Same approved native prerequisite class;
no new package, base pin, trust source, allowed upgrade or downgrade,
fallback, retry or relaxed check. NOT ACCEPTED.

**Observation (parent).** The parent's frozen scoped D2 integration run
stopped during archive verification after download, before installation and
before any test. Its verified SDK build log (21,511 bytes, SHA-256
`52da7426…`) reports the cached archive `libc-bin_2.41-12+deb13u4_arm64.deb`
outside the frozen manifest. There was no image or container delta and the
ledger is unchanged. `install_prerequisites` gives the simulation every
baseline hold, but gives `--download-only` and `--no-download` only the
additions' pins. Each of those is a new APT resolution that may upgrade an
installed package the simulated plan held. The refusal worked; the downloaded
resolution was not the simulated one, contrary to D6's "resolved, hash-bound
and frozen before installation". Which resolver step chose `libc-bin` is not
observed.

**Plan, in `install_prerequisites` only.**

1. One hold list: the existing baseline holds (every other installed `ii` row
   at its installed version, native and arch-all unqualified, foreign
   qualified) followed by `name=version` for each requested package that is
   already installed. The request then names only packages to add. The
   simulation receives the same tokens as before.
2. `--download-only` and `--no-download` receive exactly that hold list,
   then the frozen additions' pins. All three operations resolve from one
   held baseline.
3. Unchanged: name checks, simulation parsing, trusted SHA-256 and size
   binding with correlated locations, control fields, the frozen manifest and
   read-only archives, before and after state checks, `--no-remove`, the
   no-download install, `apt-mark auto` and the 400-line ceiling.
4. Architecture: additions are native or arch-all (foreign ones refuse) and
   pinned unqualified, as in the simulation; holds qualify only foreign rows.
   All three commands carry identical tokens. Residual, unchanged: a requested
   name installed only for a foreign architecture is pinned unqualified as
   before; no approved set has one.
5. Unobserved effect: APT may record a held auto-installed package as manual.
   Versions and the state checks are unaffected; the later
   `purge --auto-remove` could only remove fewer packages. (Superseded: the
   effect is expected; see the [manual-flag correction](#adjacent-double-and-manual-flag-correction-2026-10-22).)

**Tests.** The helper owner's `World` models resolution: an installed package
is held only by an explicit `name[:arch]=installed-version`, otherwise its
newer candidate is selected. Installed `libc-bin` and `libc6` have newer
candidates; an unheld simulation plans the upgrade, an unheld download caches
its archive and an unheld `--no-download` install fails as APT would. A
foreign row needs a qualified hold. The positive case checks the exact tails
of both commands and unchanged installed versions. The entry helper must fail;
mutations drop holds from the download, the install, the simulation or the
already-installed request, or unqualify the foreign hold.

**Scope conflict.** `d12_preinstall_refusals.unit.test.py`, outside this
stage's write scope, has a second double whose download and install treat
every pin as a new package, and its positive test asserts that the install
names no baseline package ("baseline is not reinstalled"). That assertion
encodes the defect, so its positive-path tests will fail. This stage does not
edit it; an unapplied patch is offered for parent disposition.

Outcome, as implemented. NOT ACCEPTED.

- The helper follows the plan in three edited lines and stays at 400 lines
  (`5341768c…` → `df616a15…`). The recipe-v2 identity changes from
  `d75b377f…` to `df8dee1f…`; the install program digest stays `11af7627…`.
  No image was built.
- Against the entry helper the updated owner failed 7 of 36 tests, each with
  `libc-bin.deb` refused as outside the frozen manifest, the parent's
  observed failure. Mutations failed: holds dropped from the download (7),
  the install (2), the simulation (18) or the already-installed request (1),
  and an unqualified foreign hold (7).
- As predicted, the out-of-scope owner fails 3 of 17 (`KeyError:
  'python3-minimal'`). With the proposed patch, in a scratch copy only, it
  passes and fails against the entry helper. The candidate is incomplete
  until the parent disposes of that path.
- Unobserved: real APT resolution with the holds, the manual-mark effect and
  amd64. The build hold, budget and acceptance flags are unchanged.

## Adjacent-double and manual-flag correction (2026-10-22)

An eleventh solo `claude_only` stage, not an independent review, changed one
test and documents only, in the same approved native prerequisite class.
NOT ACCEPTED.

- **H1.** `d12_preinstall_refusals.unit.test.py` received the parent-sealed
  patch: in its double an installed-version pin on the download or install is
  a hold, not a new archive or a reinstallation. The positive test asserts the
  exact download and install tails (three holds, then four additions) and
  unchanged held rows. No case, source guard or helper line changed.
- **M1, superseding the two marked sentences above.** APT marks every package
  named on an install command as manual (fixture `d12_native_apt_import`), so
  held auto-installed packages become manual. That is an APT flag, not a
  package change: no version, architecture or dpkg state may change, and the
  state checks still refuse one. A later `purge --auto-remove` removes no more
  than before. No flag is restored.
- **L1/L2.** `World` models the observed worst case, not APT's install
  semantics: upgrades only for native `libc-bin` and `libc6`. A dropped
  foreign hold is caught only by exact tails, an unqualified one by a lookup
  error inside the double. The refusals owner's docstring records this;
  `World` was outside this stage's scope.

## Application APT correction design (2026-10-22)

Design only, recorded before implementation (review M2), in the same class.
The manifest stays unfrozen and no budget is spent. The complete plan is the
stage's `APPLICATION-APT-CORRECTION-PLAN.md`, pending an independent
implementation-plan review. NOT ACCEPTED.

- **Defect.** `_apt_steps` downloads and installs the pins without baseline
  holds, simulation or `--no-remove`. It hashes only listed archives, so an
  unlisted upgrade reaches `--no-download`, and it refuses only after install
  inside the consuming build. `dpkg-query | sort` masks a query failure. It is
  unreachable while the manifest is empty.
- **Design.** The renderer moves to `release.py`. Each platform branch uses a
  private work directory, checks the architecture and exact `ii`/`rc` rows,
  and refuses an addition already installed. Every `ii` row is held (foreign
  rows qualified), passed as separate arguments to the simulation, download
  and install, all with `--no-remove`. A simulated removal or change of an
  installed version refuses before download. Before `--no-download`, the
  private cache must equal the frozen archives exactly, by SHA-256 and control
  fields. Postchecks require unchanged rows and exactly the additions. No
  producer is piped; the validator refuses duplicates.
- **Tests and gaps.** A new unit owner runs the rendered program under `sh -c`
  with stub Debian commands; its retention addition is one appended clean
  record pair. The budget-held D12 core owner is the only integration executor
  and stays an unexecuted gap. Manual flags change as in M1. P3 stays separate.
- **Review outcome.** The independent implementation-plan review answered
  NOT READY with three blocking corrections (B1–B3) and advisories.
- **Revision 2 (design only, pending a fresh plan review).** The stage's
  revised plan:
  - **B1.** Refuses before any network access an addition that has any dpkg
    row, `ii` or `rc`; there is no implicit `rc`→`ii` transition.
  - **B2.** The future arch7f fixture gives each package a distinct
    deterministic SHA-256. The duplicate refusals run after every existing
    check, so each negative keeps its own error, with an ordering case.
  - **B3.** Names the stubbed Debian commands and the real host tools: nix
    bash as `sh` with a BSD userland locally, dash with GNU tools when hosted.
    The owner proves step order, argv and exit propagation, not dash, GNU,
    Debian or APT behaviour. Its `sh -c` is declared as a new shell boundary;
    it is not Python dynamic-operation debt and needs no waiver.
  - **Exit status.** Producers write files compared with `cmp`; no
    `test "$(producer)" = value` and no counts; grep's no-match exit 1 passes
    and its error exit 2 refuses. Matching output with a nonzero exit is a
    tested refusal.
  - **Advisories.** `release.py` is `retained_ratchet` under
    `retained_python_ratchets`, estimated at 388–398 lines; more than 400 is a
    stop, with no packed statements or new module. An extra simulated package
    is caught only by the exact cache membership. The 0700 work directory's
    APT notice is expected. The D12 identities are recomputed after M2 and
    again over the tree with both M2 and Go, before any P3, reservation or
    qualification.

  No application APT production code changed.

## SDK probe import-order correction (2026-10-22)

A twelfth solo `claude_only` stage, not an independent review, recorded this
design here before changing the SDK recipe. Same approved class; no new
package, pin, hash, trust source, fallback or retry. NOT ACCEPTED.

- **Observation (parent).** The parent's scoped C compatibility attempt
  stopped inside the SDK build, before pytest. Native prerequisites were
  installed, psycopg-c 3.3.6 was built, and the first probe loaded the default
  C implementation with matching build and runtime libpq `170011`. The second
  probe's fresh `python3 -I` process imports `psycopg_c._psycopg` without
  first importing `psycopg`, and refuses (raw log 183,771 bytes, SHA-256
  `5b5032ca…`, scratch only). No image, container, volume or network delta;
  no application build; ledger unchanged.
- **Design, in `tools/test_sandbox/Dockerfile` only.** The second probe
  imports `psycopg` first, as the application recipe's loaded-library program
  already does in its main process. (Correction: its fresh `LD_BIND_NOW`
  child did not; see
  [Receipt framing, application APT custody and probe child](#receipt-framing-application-apt-custody-and-probe-child-2026-10-22).)
  Unchanged: the separate fresh isolated process; the first
  probe's default-backend, version, `psycopg_binary`-absent and build/runtime
  libpq assertions; the per-extension `readelf -d` check for `libpq.so.5`;
  the sdist bytes and hashes, the libpq attestation, and the helper and
  recipe binding. The recipe identity changes only because its bytes do.
- **Test.** The builder owner reads the recipe text and asserts the two
  probes, their isolated flags, the import order and the `DT_NEEDED` loop.
  It executes no Python taken from the recipe; it adds no exec, compile,
  loader or import boundary. The real C package proof is the canonical
  integration's SDK build.
- **Sequence.** Scoped units, then exactly one frozen C compatibility attempt
  with the parent's eleven selectors. If setup or pytest fails, no Go source
  changes in this stage.

Outcome, as implemented. NOT ACCEPTED.

- The recipe change is one token: `import psycopg, ` before the C extension
  modules in the second probe. The builder owner gained one structural test.
  It failed on the entry recipe and passed on the candidate. Two mutations
  each failed it: `psycopg` imported after `psycopg_c._psycopg`, and the
  `readelf` loop without `|| exit 1`.
- **The C compatibility attempt was not executed.** The changed recipe needs
  a fresh SDK build. None of the three digest-pinned bases is a registered
  local image, so `docker build --pull=false` must resolve them from the
  registry. With the inherited Docker configuration the token fetch runs in
  the producing session's CLI, and that session's network policy denies
  `auth.docker.io`. The attempt would have stopped in setup before testing
  the correction, so the parent's single attempt was left unspent rather
  than consumed by a known environment refusal. No Docker state changed.
- Consequently no Go source changed in this stage (see
  [ADR 0090](0090-d12-application-go-supported-toolchain.md#plan-readiness-and-sequencing-2026-10-22)).
  The real C package, `DT_NEEDED`, libpq and ABI results remain unobserved for
  the corrected recipe. (Superseded: the parent's later cohorts ran inside an
  SDK image built from this corrected recipe, so its in-build C, `DT_NEEDED`
  and matching-libpq assertions passed. That is SDK diagnostic evidence only;
  see [Scoped cohort and component evidence](#scoped-cohort-and-component-evidence-2026-10-23).)

## Receipt framing, application APT custody and probe child (2026-10-22)

A thirteenth solo `claude_only` stage recorded this before changing source.
Same approved class; no new package, pin, trust source, parser, fallback,
retry or budget. NOT ACCEPTED.

- **Framing.** The parent's C cohort passed 20 of 21 items; the last passed
  its real ABI, ELF and ownership checks, then its strict record read failed
  (`Extra data`): the unflushed JSON's newline stayed buffered while the
  `pip check` child wrote `No broken requirements found.` to the same pipe.
  Both materializer records now print with `flush=True`. Format, custody,
  locks and guards are unchanged; the install program digest and cache
  fingerprint change. Strict whole-line `json.loads` stays (no decoder
  fallback, truncation or suppressed output); the failed item stays failed
  until rerun. The linkage owner runs both actual record statements, then a
  child writing to the same stdout, via the existing `-I -c` boundary.
- **M2.** Ready plan `5da17f87…` implemented as
  [designed](#application-apt-correction-design-2026-10-22), within 400
  `release.py` lines, with its advisories (every architecture's names,
  distinct fixture hashes, a count-printing exit-2 `grep` stub); the new
  owner's `sh -c` is the declared shell boundary.
- **Probe child (R-F1).** The fresh `LD_BIND_NOW=1` child now imports
  `psycopg` before `psycopg_c` (the parity claim held only for the main
  process); every ELF, owner, ABI and eager-binding guard is unchanged.
- **Then Go** ([ADR 0090](0090-d12-application-go-supported-toolchain.md#implementation-2026-10-22));
  identities recomputed after M2 and at the end.

## Producer-status erratum (2026-10-23)

A fourteenth solo `claude_only` stage recorded this before changing source.
Same approved class; no new package, pin, trust source, parser, fallback,
retry or budget. NOT ACCEPTED.

- **Erratum to plan `5da17f87…`.** I7 requires every producer's status in
  the `&&` chain and no producer read only through `$(…)`. Its step 7, as
  implemented (`release.py` `3faea7da…`, line 196), runs `set -f`;
  `set -- $(cat W/holds)`; `set +f`. `set --` returns its own status, so a
  `cat` that prints every correct byte and exits nonzero is hidden; the
  `argv` `cmp` passes and the chain reaches `apt-get update`. The plan's
  "a failed `cat` … cannot pass" holds only for differing bytes, and the
  truncated-`cat` negative tests only that. The parent's host-shell
  diagnostic (no APT): `set -f && set -- $(printf 'heldpkg=1\n'; exit 7)`
  exits 0. `set +f` is present and stays. I7 is not weakened; step 7 is
  corrected to meet it.
- **Correction.** Step 7 becomes `holds=$(cat W/holds)`; `set -f`;
  `set -- $holds`; `set +f`; `printf '%s\n' "$@" > W/argv`;
  `cmp W/holds W/argv`. An assignment-only command takes its substitution's
  exit status, so `cat`'s status joins the chain before any positional
  argument exists. Unquoted splitting stays between `set -f` and `set +f`;
  every other step, guard and refusal, including the empty-manifest and
  all-platform preflight refusals, is unchanged.
- **Test.** A `cat` stub prints the whole hold file and exits 1; it must
  refuse at the `holds=` assignment, before `apt-get update`, red on the
  entry renderer and green after. The rows query is only the last stubbed
  call logged, not the refusal location (wording corrected by the
  [guard-attribution correction](#guard-attribution-correction-2026-10-23)).
  The truncated-`cat` negative stays; that correction makes it exit 0.

Outcome, as implemented. NOT ACCEPTED.

- **Source.** One element became four, plus a comment: `release.py` is 399
  lines including `__all__` (`6cc2fba7…`). No helper, module, parser, trust
  or dependency change; nothing packed.
- **Red, green, mutation.** On the entry renderer only the new negative
  failed (1 of 37): the chain ran through update and install. Corrected, it
  refuses at the assignment (last logged call: the rows query); the render
  test, which pinned the old text,
  now pins `holds=$(cat W/holds) && set -f && set -- $holds && set +f`, and
  37 pass. Mutation `$(cat W/holds; true)` failed both; the source was
  restored and hash-checked. Host `sh`, `dash`, `bash` and `zsh` refuse the
  corrected form (status 7) and pass the entry form (not Debian `dash`; no
  APT).
- **Identities.** D12 source `4924753b…` → `c6218750…`; recipes unchanged
  (arm64 `d6c1dfd3…`, amd64 `43556aa4…`), as the empty manifest renders no
  APT. Not image, platform or P3 evidence.

## Guard-attribution correction (2026-10-23)

A fifteenth solo `claude_only` stage, test and wording only, under the
parent's disposition of the erratum's review. `release.py` ends
byte-identical (`6cc2fba7…`); no package, pin, trust source, parser,
fallback, retry or budget. NOT ACCEPTED.

- **Finding.** The erratum kept the truncated-`cat` stub exiting 1, so the
  new `holds=` assignment refused it before `cmp W/holds W/argv` ran. The
  `cmp` had no discriminating negative, the test comment "the argv `cmp`
  refuses" was false, and the render pin ended at `printf`; the review
  found that a renderer without the `cmp` would pass (not rerun on the
  erratum's tests). "Refuse at the rows query" named
  only the last stubbed call; the refusal is at the assignment. Both are
  recorded, not erased; the erratum's wording is corrected above.
- **Test.** The truncated stub now prints one hold row and exits 0, so
  only the `argv` `cmp` can refuse. The whole-output, exit-1 stub stays and
  refuses at `holds=`. A two-case test reads `W/argv`: one short row for the
  truncated case (written, then refused by the `cmp`, the only step before
  update) and absent for the failing assignment; neither reaches
  `apt-get update`. The render pin now runs through
  `cmp W/holds W/argv && apt-get update`. Every other negative is unchanged.
- **Red, green.** Current renderer: the owner passes, 39 tests. Two
  transient `release.py` mutants, each restored to `6cc2fba7…` and
  hash-checked after its run: dropping only the `argv` `cmp` failed the
  truncated case in both negatives (update and install ran with only
  `libc6` held) and the pin; restoring `set -- $(cat W/holds)` failed the
  whole-output case in both negatives (update ran) and the pin. Each
  mutant left the other case green.
- **Identities.** Recomputed, equal to the erratum's: D12 source
  `c6218750…`, recipes arm64 `d6c1dfd3…`, amd64 `43556aa4…`. Not image,
  platform or P3 evidence.

## Scoped cohort and component evidence (2026-10-23)

A sixteenth solo `claude_only` stage recorded the parent's executions, in
documents only; it ran nothing. Same approved class; no package, pin, trust
source, budget or retry. NOT ACCEPTED.

- **Cohort.** The receipt-framing failure of the parent's first C11 attempt
  (20 passed, 1 failed) is closed for scoped purposes. The parent's final run
  of the same eleven selectors with the Go wheel node, under `--no-coverage`,
  gave 21 passed, exit 0 (log SHA-256 `f2e7efac…`). Docker deltas were 0, and
  no application was built. This is compatibility evidence for C 3.3.6 in
  the SDK and in the dependency-only test image, on their Debian libpq
  (earlier parent observations: SDK `170011`, dependency-only image
  `150019`). It is not evidence of the release base's PGDG libpq, the derived
  closure, a frozen D3 manifest or the final image. The D2 product probe
  remains unobserved.
- **Go.** The one native linux/arm64 component campaign ran. Its control
  status is failed on cleanup bookkeeping, while every component check passed
  ([ADR 0090](0090-d12-application-go-supported-toolchain.md#component-campaign-result-2026-10-23)).
- **Unchanged.** The D3 manifest is empty and `PSYCOPG_LIBPQ_VERSION` is
  `None`. The host preflight refuses every platform. The P3 hold and the
  ledger are unchanged (`maximum_total` 0; original 2, 1 per platform, no
  retries, 0 used). A non-consuming inner-daemon preflight under D9 is
  designed in private scratch for the parent's acceptance; nothing is
  implemented.

## E1 exploration design note (2026-10-23)

Written before any E1 source change (wording tightened later in the same
stage), after the parent accepted the design with corrections. E1 only: one native linux/arm64 exploration in the
disposable inner daemon. NOT ACCEPTED.

- **Same owner and profile.** `--d12-core-image-preflight` is a mode of
  `--d12-core-image-profile` and its one optional node: no new registry,
  profile, reason or owner. The twelve deferred nodes are unchanged.
- **No build, no ledger.** A ledger option refuses before any access. The
  host never calls the D9 preflight, `admit_profile` or `record_budget`. The
  owner reports and returns before `build_candidate`; custody requires zero
  build and pull counts.
- **Placement (parent-approved).** Logic in the D9 support module
  `tools/d12_dependency_preflight.py`, lazily imported by the owner from the
  runner's `tools` path; pure owner `d12_inner_preflight.unit.test.py` with a
  zero-debt cohort. The byte-identical root conftest gates the node on the
  one admission slot, so exploration fills it; each admission refuses an
  occupied slot. (Superseded 2026-10-23: the parent rejected the shared slot;
  see [E1 admission separation correction](#e1-admission-separation-correction-2026-10-23).)
- **No cryptographic parser.** Fingerprints only from a key-listing tool
  already in the base; otherwise the keyring SHA-256 is recorded and the fact
  refuses.
- **Unchanged.** Build-mode refusal, admission and consumption; E1 never
  lifts them. The cross-daemon host gate and residual R1 were rejected (D1).
  Same-daemon readiness before consumption needs its own design. The manifest
  and `PSYCOPG_LIBPQ_VERSION` stay empty; O3 is out of scope. The written
  operator P3 disposition is still required before any ledger release; no
  waiver.

## E1 exploration implementation checkpoint (2026-10-23)

**Amended by ADR 0091 (2026-10-23).** The
[numeric libpq runtime proof](0091-d12-tls-p3-disposition-and-trixie-remediation.md#proposed-numeric-libpq-runtime-proof-design-amendment-2026-10-23),
accepted as a design ([C1–C3](0091-d12-tls-p3-disposition-and-trixie-remediation.md#numeric-design-acceptance-and-conditions-c1c3-2026-10-23)),
extends this contract from index acquisition and simulation to one bounded
runtime-subset installation in the owned Python builder. The record below is
unchanged.

A seventeenth solo `claude_only` stage produced the source. It ran no
integration node, Docker, APT, network, ledger or Go command. Unreviewed; no
E1 run has happened. NOT ACCEPTED.

- **Routing.** Ledger option, then missing profile, then
  `validate_selection`, `frozen_identity` and (host) an absent report
  directory. The host returns before any build-mode call.
- **Owner.** Lazy import; `explore`, then `return`, immediately before
  `build_candidate` inside the `try`, so custody still cleans up.
- **Facts.** E-b/E-c: buildx exit status, BuildKit, native, emulated or
  non-executable labels, sealed PostgreSQL, Python ID, Go `347d64c4…`. E-e:
  exact source and keyring bytes; `gpg` fingerprints. E-f: `ldd` of every
  ELF under `/usr/local`, owners via the resolved file, `lib-dynload`
  imports. Only then E-g/E-h: bridge for update and simulation, exact PGDG
  bytes read back, the existing APT helpers through an argv-only exec
  adapter, every row held. E-i: `validate_package_manifest`, never written;
  libpq number derived (R3). E-j: free-space forecast. Refusals are named and
  saved in a partial report first.
- **Deviation.** Design section 5 item 2 kept `d12._ADMISSION` `None`; a
  plain `D12Admission` fills it instead (not a new type), identified by
  `current_exploration()`.
- **Evidence.** Entry 39 failed; nine selectors 270 passed; four restored
  mutants caught; no own retention finding.
- **Unchanged.** Build-mode refusal and consumption, twelve deferred nodes,
  ceilings, the empty manifest, the ledger (`maximum_total` 0).
- **Disposition.** One independent work review rated the shared slot low
  (F4) and the scoped 270 passed was reproduced, but the parent rejected the
  deviation (B1/DI-1): see the correction below. The source was never
  accepted.

## E1 admission separation correction (2026-10-23)

Design, written before this correction's source change. NOT ACCEPTED; no E1
run has happened. With the build slot filled by exploration, a lost or
aliased exploration state while build admission remained would let the owner
fall through to `build_candidate`, and the zero-count custody would see the
build only afterwards. That breaks the no-build boundary, so:

- **Separate slots.** E1 sets only `_EXPLORATION` in
  `tools/d12_dependency_preflight.py`. `d12._ADMISSION` stays `None`, so
  `d12.current_admission()` refuses throughout E1. No subclass, environment
  selection or patched accessor.
- **Setup gate.** For the D12 marker, the root conftest's
  `pytest_runtest_setup` keeps build mode unchanged when no exploration is
  admitted (`d12.current_admission()`). Otherwise it accepts only an
  exploration admitted for exactly the named node with no build admission; a
  mismatched node and both modes refuse, and a lost exploration falls to the
  refusing build accessor. It imports the E1 module lazily, for that marker
  only, from the canonical runner's `tools` path as the owner does; product
  and test support still never import `tools`.
- **Both directions.** `admit_exploration` refuses an existing build or
  exploration admission. The runner refuses build admission after E1 before
  `admit_profile` can fill its slot. Host preflight and refusal are unchanged.
- **Tests.** A new pure owner, `d12_exploration_admission.unit.test.py`,
  calls the actual root conftest plugin hook and the real routing under
  ledger, build and filesystem traps. Restored mutants that bring back the
  shared slot or drop the setup node check must each fail.
- **Consequence outside this scope.** The integration owner is not in this
  correction's write scope. Its first statement still calls
  `d12.current_admission()` unconditionally, so an E1 run would refuse there
  before any Docker work: it fails closed and builds nothing, but it observes
  nothing either. E1 is not ready until that statement takes the exploration
  admission first and keeps the refusing build accessor otherwise. That
  needs its own scoped change and review. (Produced 2026-10-23 and not yet
  reviewed: see the
  [Named-owner E1 dataflow correction](#named-owner-e1-dataflow-correction-2026-10-23).)
- **Unchanged.** Everything in the checkpoint's Unchanged bullet, the
  observation functions and constants, the host preflight, and the spent
  native arm64 Go component campaign (components passed, control failed).
  The cross-daemon host
  gate stays rejected. There is no P3 disposition and no ledger release.

## Named-owner E1 dataflow correction (2026-10-23)

Design, written before this correction's source change. NOT ACCEPTED; no E1
run has happened. The parent accepted the admission separation and setup
correction above locally. The integration owner's eager build-admission read
was found before any E1 attempt. In E1 the owner's first statement would
refuse before any Docker work, so the separation leaves E1 unobservable.
This correction changes only that owner, its unit owners and their
documentation:

1. **Exploration first.** The owner reads `inner.current_exploration()`
   first. It reads `d12.current_admission()` only when no exploration is
   admitted. During E1 the local build-admission variable stays `None`, and
   the exploration object is never assigned to it. If an exploration is
   present while the build slot is also filled, the owner refuses as mixed
   before any Docker interface. A separate `frozen` binding (the exploration
   in E1, the build admission otherwise) carries the platform, frozen source
   and recipe identity, staged context, labels and freeze report. It is never
   passed as build authority.
2. **Guard before the build helper.** E1 still observes, reports and returns
   inside the `try`, before `build_candidate`, so custody still runs. The
   build call's admission argument is now the return value of a small helper,
   `_build_authority(admission)`. It refuses `None` itself. Any other object
   must be identical to `d12.current_admission()`, which refuses throughout
   E1, so an exploration binding or a foreign admission refuses too (identity,
   not field equality). Python evaluates the argument before entering
   `build_candidate`, so if the E1 return were missing, the build would be
   refused before the helper is entered. This does not depend on post-hoc
   count assertions. In ordinary build mode the helper returns the actual
   current admission unchanged.
3. **Actual owner tests.** The old AST check
   `test_the_named_owner_cannot_obtain_build_admission_from_exploration` only
   proved the accessor and a source substring that also accepts unsafe forms.
   It is narrowed to the accessor plus the guard's call site. A new pure owner,
   `d12_owner_exploration.unit.test.py`, gets the real owner function through
   pytest's normal fixed-path collector API:
   `pytest.Module.from_parent(request.session, path=ROOT / d12.NODE_FILE).obj`.
   That imports only this known RepoMap test module with the session's
   configured import mode. It does not collect or run the int suite, load its
   conftest, use a custom loader or start a second pytest. The test then calls
   the function with every external interface faked: resource run, boundary,
   client, owned containers, server, inventory, hashes, stage context, buildx
   query, base check, labels, scratch, the explore and report writers, and a
   trapping `build_candidate`. Cases cover E1 success, an E1 refusal with
   cleanup, none, lost and mixed admission before any resource call, a valid
   build that reaches the build trap, and direct guard refusal of `None`, an
   exploration object and a foreign admission. The orchestration cases assert
   the build helper's call count and the ordered fake calls. Those that reach
   resources also assert the binding passed to context staging versus the
   build admission argument, owned-server cleanup, the baseline check and the
   cleanup report.
   This is unit orchestration evidence only. It is not an integration run, a
   qualification or an E1 attempt.

Negative controls restore the eager read, remove only the E1 return (the guard
must refuse with a build-helper count of zero), and remove the return and
bypass the guard together (the build trap must be reached and the case must
fail). F1–F3, the observation code, the admission separation, the setup gate,
the routing guards, M1–M4 and the R15 controls are unchanged. There is still
no P3 disposition, no ledger release and no application build attempt.

Produced evidence (scoped unit only; NOT ACCEPTED). Against the entry owner,
the new file had 6 failed and 3 passed: E1 refused at the eager read, mixed
was only an `assert`, and the guard was absent. The final six-file selection
passed 136. Restored, hash-checked controls on the real owner gave these
results:

- Eager read restored: both E1 cases fail at that read, with zero
  build-helper calls.
- Return removed: the guard refuses in `_build_authority`, with zero calls.
- Return removed and guard bypassed: the trap is reached (one call), and the
  case fails.
- Guard body weakened: the 3 direct guard cases fail.
- Guard call bypassed with the return kept: only the narrowed call-site check
  fails.

The targeted static checks found nothing in the changed Python files, and
there are no new direct dynamic-operation sites. The remaining limits are in
the Exit.

## E1 actual refusal (2026-10-23)

A twentieth solo `claude_only` stage recorded this in documents only; it
ran nothing. The named-owner correction had one independent review and a
close stage (136 scoped units reproduced). The parent then admitted that
source for exactly one E1. NOT ACCEPTED; all acceptance is false.

- **Run.** One canonical native linux/arm64 run of the D12 node under
  `--d12-core-image-preflight`, `--no-coverage` and no ledger option, on
  source `c6218750…` and recipe `d6c1dfd3…`. It exited 1, an executed
  refusal at E-f, not a qualification or admission. The attempt is spent;
  there is no automatic retry.
- **Observed (E-b/E-c/E-e/E-f).** Engine 29.4.0, API 1.54, `docker` driver,
  `overlay2`, BuildKit v0.29.0; arm64 native, amd64 offered by the builder
  and classified emulated. The base's existing `gpg` listed PGDG primary
  `B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8`. The PostgreSQL base's `libpq5`
  is `18.6-1.pgdg12+2`. In the Python base: 83 ELF files under `/usr/local`,
  27 dependency paths owned by 22 Debian packages, and 79 `lib-dynload` names,
  78 of which import in a fresh `LD_BIND_NOW=1` process.
- **Refusal.** `/usr/local/lib/python3.12/lib-dynload/_tkinter.cpython-312-aarch64-linux-gnu.so`
  needs `libtcl8.6.so` and `libtk8.6.so`, which are not found. It is the only
  unresolved entry and the only non-importing module. The exception text,
  the module's SHA-256 and size were not recorded.
- **Not observed.** E-g, E-h and E-i did not run. The F1 `libssl-dev`
  matching-header issue remains a forecast, not this refusal (superseded:
  [E2](#e2-actual-header-refusal-and-exact-builder-selector-2026-10-23)
  observed it). There was no
  serialized libpq file-hash inventory, no Go 1.26 execution and no amd64
  execution. Builder metadata does not show `RUN --network=none` support or
  same-building-daemon readiness.
- **Custody.** Candidate, product or build-profile, unmanaged build and pull
  counts were 0, and the candidate ID is null. One existing managed
  test-runtime materialization was recorded; it is non-ledger and not an
  application candidate. The server was removed and containers are at
  baseline. All four resource and reference inventories are identical. The
  hold (`8cb19a8c…`) and the spent Go record (`c3b26714…`) are unchanged, and
  source custody was re-proved after the run.
- **Authority correction after independent review.** D4 could not pass as
  originally written, but its recipe/assertion design is parent-accepted,
  within approved dynamic-route item 4. The prior mandatory operator-choice
  framing was unsupported. The parent selects exact exclusion through the
  reviewed D4 amendment above; only a new Tcl/Tk dependency class needs a
  separate operator decision. The
  [Python payload decision packet](../../../specs/postgresql-d12-python-payload-decision-v1.md)
  records static module identity recovered after E1, peer alternative
  tradeoffs, strict live checks and the independent review gate. This is
  no source, image, platform, phase or P3 acceptance.
- **Unchanged.** The build-mode preflight refuses every platform. The D3
  manifest and `PSYCOPG_LIBPQ_VERSION` are empty. The ledger stays held at
  `maximum_total` 0 (original 2, 1 per platform, no retries, 0 used), and a
  written operator P3 disposition is still required before any release.

## Exact payload implementation (2026-10-23)

A twenty-second solo stage implemented the accepted amendment, NOT ACCEPTED:
see the [contract](../../../specs/postgresql-d12-python-payload-decision-v1.md#implemented-contract-2026-10-23)
and the Exit. No E2, build, ledger or Go action ran; P3 still needs a
written operator disposition.

## E2 actual header refusal and exact builder selector (2026-10-23)

Written before the source change by a twenty-fifth solo `claude_only` stage.
NOT ACCEPTED; source, image, platform, phase, P3 and coverage acceptance false.

- **E2.** The parent's one non-consuming native linux/arm64 exploration
  (source `b335ae10…`, recipe `30474516…`, 694 context files, `--no-coverage`,
  no ledger) exited 1. E-f passed on Python config `a0938838…` with payload
  program `f3d92f4f…` (result `trimmed`, exit 0): 83 ELF files and 1,721
  entries before, only `_tkinter` failed; the exact `e6856022…` (70,512
  bytes) was removed; 82 ELF files and 1,720 entries remain, 78 imports
  succeed, nothing is unresolved, and the retained digest equals the
  expected `6d3af915…`. The original ELF observations are serialized; the
  raw post-trim inventory is not. The preservation of every other entry
  rests on a count, a digest and the same in-container checker, not a
  host-independent replay. This is component evidence only, not final
  image, amd64, P3 or coverage proof.
- **Refusal.** E-g's simulation exited 100: with every installed row held,
  `libpq-dev` pulled the security candidate `libssl-dev` `3.0.22-1~deb12u1`,
  which needs `libssl3 (= 3.0.22-1~deb12u1)`, while the base holds
  `3.0.20-1~deb12u2`. The earlier F1 forecast is now an actual refusal.
  E-h and E-i did not run. Candidate, product, unmanaged build and pull counts
  were 0; one non-ledger test-runtime materialization, no new cache image;
  cleanup and the four inventories matched; hold `8cb19a8c…` and Go record
  `c3b26714…` unchanged. Reports: exploration `b073b90c…`, cleanup
  `5311e1b9…`, freeze `43a13bd2…`. E2 is spent; there is no automatic retry.
- **Decision.** Plan B's approved matching header, applied as a direct
  solver constraint in E-g instead of a preferences file. In `resolve` only,
  after the native architecture and the installed rows are known,
  `builder_request` appends exactly `libssl-dev=3.0.20-1~deb12u2` when the
  request names `libpq-dev` and `missing_only` is false. It first requires
  exactly one `libssl3` row: `ii`, the native architecture and
  `3.0.20-1~deb12u2`. It also requires no `libssl-dev` row of any status or
  architecture, and no `libssl-dev` in the request. Anything else, or a
  malformed row, refuses before `apt-get install --simulate`. The input is
  not mutated. E-h keeps `missing_only=True` and never gains a header.
- **Unchanged.** Every baseline hold (`exclude=()`), additions-only
  planning, the existing-row clash check, request matching, trusted-index
  binding (size, SHA-256, provenance), native and status checks. There is no
  installed-library change, upgrade, downgrade, fallback, broader pin,
  source, preferences file, key or download. The materializer's Plan B
  preference, the SDK and the helper are unchanged. The selector picks only
  from the authenticated configured indexes; if `3.0.20-1~deb12u2` is gone
  or conflicts, the simulation or the request match refuses. A later frozen
  manifest would list the header among the builder packages, which the recipe
  already installs at exact versions, so the recipe is unchanged.
- **Proof limit.** The parent's earlier static main-index metadata is
  background, not current resolution proof. Unit doubles prove the argv and
  the refusal order, not APT behavior. Only one later parent E3 could observe
  it, and this record does not admit it. The same-daemon protocol, D3
  manifest, runtime numeric libpq, P2, P3, incumbent inventory and coverage
  remain separate. The ledger stays at `maximum_total` 0; a written operator
  P3 disposition is still required.

**Superseded by ADR 0091 (2026-10-23).** The `.20` header constraint, the
materializer's Plan B `libssl3` preference and the Bookworm D4 entry above are
historical. Under [ADR 0091](0091-d12-tls-p3-disposition-and-trixie-remediation.md#package-and-payload-design)
both selectors bind exactly one installed native `libssl3t64` row at
`3.5.7-1~deb13u3` with no `libssl-dev` row. The materializer's selector now
refuses every other state before any preference or install instead of writing
nothing. The D4 entry is re-bound to the exact Trixie case with 77 imports. No
Bookworm value generalizes to the new bytes. NOT ACCEPTED.

## Rejected alternatives

- **Static libpq or Psycopg.** Not approved.
- **Binary 3.3.6 wheels.** ADR 0088 found their closure not established.
- **Pure-Python Psycopg (choice B).** Not selected; its slowdown is
  unmeasured.
- **Retaining the hold (choice C).** Superseded; it is the rollback state.
- **Keeping the `/usr/lib` overlay.** It hides ownership from `dpkg` and
  could replace the PGDG libpq this design depends on.
- **Copying selected library files without packages.** Unowned files are a
  P3 refusal.
- **Debian's own libpq headers for the release image.** They would differ
  from the shipped runtime ABI.
- **`pip download` of the sdist.** It runs the backend before inspection.
- **A per-environment fallback to binary or pure Psycopg.** An unreviewed
  mixed packaging default.
