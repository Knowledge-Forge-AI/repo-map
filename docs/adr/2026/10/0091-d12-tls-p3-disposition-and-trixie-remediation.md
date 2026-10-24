# ADR 0091: D12 TLS P3 disposition and bounded Trixie remediation

## Status

**Choice A approved by the human operator, 2026-10-23. The parent accepted
the dependency amendment (F1–F7) and, separately, the numeric design (N1–N9,
C1–C3). Source and runtime qualification remain open. No candidate is
accepted.**
Phase: `REPOMAP-PRODUCT6-NAVIGATION45-D12DYNAMIC1`.
The approved exact-base route records the incumbent comparison inventory gap
unresolved under Samuel Leighton Lair for this D12 candidate/staging evidence
scope. Current affected TLS risk was not accepted. The original application
ceiling and all non-dispositionable refusals remain unchanged.

Initial native ARM read-only inspection found supplier-fixed libssl3t64
`3.5.7-1~deb13u3` in both approved bases. Later exact-payload observation and
review preceded the implemented exclusion, server-version representation and
test-only ABI additions. The first successful D9 Trixie probe completed the
C-locale round trip and two collation refusals. Native ARM E3 then verified
the trimmed payload, 77 imports, PGDG trust and 47 builder package identities,
with no final closure additions. E3 acquired indexes and simulated resolution;
it did not install builder packages or observe the numeric libpq API.

The numeric amendment below adds a bounded step to that E1 exploration
contract. After a complete independent review, the parent accepted it as a
design before implementation, with
[N1–N9 and C1–C3](#numeric-design-acceptance-and-conditions-c1c3-2026-10-23).
Ordinary canonical test-runtime preparation is a separate owner. After
independent code review closed the three pre-E4 guard blockers
(`PARENT-C2-BASELINE`, `REVIEW-B1-DPKG-VERIFY-FILTER`,
`PARENT-LOADER-CONTAINMENT`), the `revise_close` finalizer reproduced 206
scoped unit passes on identical GREEN hashes and the parent verified all 123
file hashes, four patches, reviewer evidence delivery, frozen source and
private/public Git preservation, the parent admitted and ran one canonical
native `linux/arm64` E4 exploration node (`--d12-core-image-preflight`). It
passed in 17.36s and observed runtime `PQlibVersion = 180006` from the
hash-bound distribution-owned shared `libpq5` `18.6-1.pgdg13+2`
(`package_forecast = 180006` equality check only;
[implementation checkpoint](#numeric-implementation-checkpoint-2026-10-23),
[native ARM E4 observation](#native-arm-e4-numeric-observation-and-operator-handoff-2026-10-23)).
`build_readiness` remains `NOT ESTABLISHED` (`p3`: inputs only, `mode`:
exploration). Signed APT acquisition/install ran inside the owned disposable
builder and one ordinary managed test-runtime materialization ran; no
application/candidate build, SDK rebuild, new dedicated Go campaign, complete
local suite or publication occurred. `PSYCOPG_LIBPQ_VERSION = None`,
`DYNAMIC_PACKAGE_MANIFEST = {}`, source, final-image P3, native AMD, platform,
positive build admission and coverage qualification remain open; the SDK is
unchanged. Subsequent direct human steering on 2026-10-23 selected public CI
for native platform qualification/builds referencing Theme Forge Nebular Fusion
([ADR 0092](0092-public-native-d12-qualification.md),
[the D12 native qualification companion note](../../../../tools/ci/nav46-d12-native-qualification.md),
[the D12 native qualification companion note](../../../../tools/ci/nav46-d12-native-qualification.md),
[the D12 native qualification companion note](../../../../tools/ci/nav46-d12-native-qualification.md)),
answering and superseding the local-native-environment operator question in
current status; after independent design review, the parent accepted the
narrowed bounded first-checkpoint hosted architecture in ADR 0092 before
private-readiness implementation and subsequently admitted one bounded source
correction in `D12HOSTED3` while source, image, platform, P3 and hosted
execution remain open.

The parent accepted the dependency amendment below before any source edit, with
[conditions F1–F7](#parent-acceptance-conditions-f1f7); the source is unaccepted.
That acceptance is separate from the numeric design acceptance.

## Why the operator must decide

[ADR 0087 P3](0087-d12-image-evidence-and-core-security-prerequisite.md#p3--findings-are-versioned-severity-sourced-and-compared)
stops on affected high-severity runtime findings and missing incumbent
inventory. It says: "Work stops and nothing is accepted." Only the operator
chooses remediation, recorded unresolved acceptance with an owner, or refusal.
This is not a parent-reserved design adjustment like the exact Tk exclusion.
The affected observation is a Python-base precursor component, not a final-
inventory classification. The missing incumbent inventory independently
triggers the stop; no assembled candidate classification is being asserted.
The current D12 bounds exclude these new base versions and runtime classes.

The actual native ARM E2 observed the pinned Python base's TLS dependency:

| Field | Observation |
| --- | --- |
| Package | `libssl3`, arm64, `3.0.20-1~deb12u2` |
| Resolved file | `/usr/lib/aarch64-linux-gnu/libssl.so.3` |
| SHA-256 | `9e171264a6651d714938e83d81277d16524c150a36eaa59ce56e79b9cdbea7ce` |
| Scope | Dependency of the observed Python-base closure; no assembled candidate image exists |

[Debian's supplier tracker](https://security-tracker.debian.org/tracker/CVE-2026-84782)
marks this package and Bookworm security `3.0.22-1~deb12u1` vulnerable to
**CVE-2026-84782**. The [OpenSSL advisory](https://openssl-library.org/news/secadv/20260929.txt)
rates the DTLS issue **High**. The [official CVE record](https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/2026/84xxx/CVE-2026-84782.json)
has an OpenSSL CNA High label, no CNA numerical score, and CISA ADP CVSS 3.1
**8.2**, `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:H`.
The Debian page supplies no numerical severity. A Red Hat search snapshot
reported 7.4; the full page/vector were not retrieved. It cannot lower the
higher recorded assessment. NVD's fetched page supplied no usable content.

[OpenSSL 3.0 public support ended on 2026-09-07](https://openssl-library.org/post/2026-09-16-eol30/).
That is not proof Debian supplies no backports: its tracker marks
[CVE-2026-45447 fixed in the same .20 package](https://security-tracker.debian.org/tracker/CVE-2026-45447).
Use the distribution's per-CVE result, not the upstream banner alone.
Trixie security `3.5.7-1~deb13u3` is fixed for 84782 in the supplier tracker;
this does not prove a proposed image contains it. The CNA's upstream range
`3.5.0 <= version < 3.5.9` includes 3.5.7, while Debian excludes the patched
`3.5.7-1~deb13u3` package. Record both applicability inputs: the future
dependency ADR must link the supplier's exact backport/advisory and actual
installed bytes before treating that distribution build as fixed. No image
gets an automatic exemption from a version label. [OpenSSL 3.5 LTS](https://www.openssl-library.org/policies/releasestrat/)
has public support through 2030-04-08.

P3 applicability is version based. There is no reachability exemption in its
classes. RepoMap exploitability and transitive DTLS use have not been proved
or disproved; no claim that a final candidate was exploited is made. The
final image and incumbent inventories are absent, so comparison is a gap,
not a fabricated inherited, introduced or fixed classification.

## Completed evidence and its limits

- Historical Bookworm 3.12.13 evidence: E2 verified the then-exact Tk
  exclusion in the native ARM disposable Python container: 83 to 82 ELFs,
  1,721 to 1,720 entries, all 78 Bookworm baseline imports,
  no retained unresolved ELF, target absent and preservation digest matched.
  The reviewed in-container checker supplies the preservation proof; this is
  not independent host replay or final-image qualification.
- E2 then refused at E-g: available `libssl-dev` required libssl3 .22 while
  the base held .20. E-h and E-i did not run. The matching-header selector
  correction passed 158 scoped units on final bytes; actual resolution has
  not been retried. No E3 is admitted because of this P3 stop.
- Application builds and unmanaged pulls were zero; one non-ledger managed
  test-runtime materialization produced no new cache image. Cleanup and all
  four host resource/reference inventories matched. The held application
  ledger and spent Go record are unchanged. No complete local or coverage
  suite, new CI campaign or publication ran. The 82% integration aim remains.
- Earlier private ownership mismatches, including this phase's unbound new
  helper rule, remain explicit. A future isolated public candidate needs its
  own reviewed binding; this packet does not accept global governance.

## Choices: select one combined disposition

### A — separate exact Trixie remediation (recommended)

Authorize a bounded remediation class for **only these three exact official
image indexes** and their necessary distribution package/ABI closure:

| Role | Metadata reference and immutable index | Config-advertised version |
| --- | --- | --- |
| Server | `postgres:16.15-trixie@sha256:9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97` | `16.15-1.pgdg13+2` |
| Application Python | `python:3.12-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704` | `3.12.15` |
| Existing test SDK | `python:3.13-slim-trixie@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39` | `3.13.17` |

The parent verified public index, ARM/AMD child-manifest and config hashes
and sizes. These are metadata candidates, not accepted image artifacts,
native execution, package inventories, licenses or fixed-TLS proof. Floating
tag labels above never authorize a different digest.

The current SDK base in `tools/test_sandbox/Dockerfile` is
`docker.io/library/python:3.13.12-slim@sha256:f1927c75e81efd1e091dbd64b6c0ecaa5630b38635a3d1c04034ac636e1f94c8`.
No SDK vulnerability is asserted by this packet. The SDK row was proposed as
conditional additional scope: it would move the compilation/test environment
to the selected Python patch, invalidate cache identity and require a bounded
sandbox rebuild; it is not a no-op or an extra application candidate. The
original application-build ceiling is unchanged.

Correction (F6): that recipe is already Trixie-family (Trixie snapshot, `.pgp`
keyring, pinned `libssl-dev 3.5.5-1~deb13u1`). Its installed TLS revision is
unobserved and no SDK finding is asserted; it stays exactly as pinned.

Approval permits inspecting/acquiring these exact bases only in disposable
containers, reconciling release and SDK pins/bootstrap prerequisites and
their necessary distro closure, and producing a reviewed implementation with
scoped unit and container integration proof. It includes the Python patch
updates shown above and Bookworm-to-Trixie runtime ABI change. No other Python
package pin, Psycopg source/hash or Go source/image changes are authorized.

Before implementation, complete and independently review the dependency ADR
for observed versions, supplier provenance, vendor keyring/repository binding,
licenses/notices/source obligations, ABI/packaging, alternatives, rollback and
test owners. Use only vendor-supplied official Debian/PGDG origins/keyrings
from these bound bases; no arbitrary key import, repository or private library.
No host installation. If a candidate lacks fixed, supported and licensed
closure, refuse; no substitute digest or version is automatically permitted.

Preserve C Psycopg 3.3.6 dynamically linked to one distribution-owned shared
libpq. Static Psycopg/libpq, private bundled libpq and pure fallback remain
unapproved. Re-observe the new Python payload and review any exact exclusion;
the old hash-bound Tk entry and .20 header constraint must never be generalized
to new bytes. Keep additions-only installation and all ownership/ABI refusals.
Account for the distro/glibc/collation change in disposable PG/D9 compatibility
checks; deployment or reuse of a live data directory is separate authority.

Each scoped non-consuming probe is parent-bounded on frozen source, with a
written failure disposition before another. Complete local suites and local
coverage remain unapproved. No new native Go campaign, emulation, builder,
tmpfs/capacity increase, live runtime, pgvector/D15 or source-history change.
AMD remains unqualified without native evidence; ARM never substitutes for it.
The Go builder pin remains unchanged and may still be Bookworm. Its
CGO-disabled helper must run correctly in the Trixie final stage under
scoped integration/final-image proof; no repeat component campaign is granted.

Also record the **missing incumbent comparison inventory** as an unresolved
D12 gap, owned by **Samuel Leighton Lair**. Do not build an incumbent to fill
it, label it safe/worse, close its old bundled-libpq findings or claim a fixed
comparison. This disposition applies to this D12 candidate/staging evidence
scope only. It does not endorse continued incumbent use or deployment.

The original ceiling stays **two application candidates total, one per
platform, no retries, zero used**. The ledger stays held at zero until every
remaining P3/refusal, frozen manifest, runtime numeric libpq, same-building-
daemon admission and image evidence prerequisite permits release. This choice
does not itself release or mint budget, accept current TLS risk, qualify any
image/source/platform, lower any gate or authorize deployment/publication.

Rollback: preserve the current unaccepted checkpoint and hold; revert only
new remediation-owned edits. No reported history is rewritten and no runtime
is changed by rollback. The incumbent is not thereby declared safe.

### B — accept this finding and comparison gap unresolved

Give a written P3 disposition accepting the **High / CISA CVSS 3.1 8.2**
finding **CVE-2026-84782** unresolved for only this exact observed instance:
arm64 `libssl3` `3.0.20-1~deb12u2`,
`/usr/lib/aarch64-linux-gnu/libssl.so.3`, SHA-256
`9e171264a6651d714938e83d81277d16524c150a36eaa59ce56e79b9cdbea7ce`,
in the E2 Python-base closure (index `d50fb761…`, config `a0938838…`).
The PostgreSQL Bookworm server-image instance, amd64, a different package,
hash/version, and any final assembled-image instance are separate findings;
this choice does not accept them. It makes no final-inventory classification.

Also accept the missing incumbent comparison inventory as an unresolved D12
gap. Both this finding and the gap are owned by **Samuel Leighton Lair**.
Retain the advisory, severity and unproved reachability; risk acceptance
does not turn an affected package into outside_affected_range. No new base
or version is authorized.

Every other unknown or finding requires separate evidence and, where P3
requires it, its own operator disposition. A non-waivable refusal must be
fixed or disproved by evidence; **no disposition can waive it**. The hold is
not automatically released. Source, ABI, identity, licenses/provenance,
cleanup, native platform, same-daemon admission and final-image evidence
remain mandatory. No incumbent endorsement, live/D15 or publication authority
is added.

### C — refuse this route and keep D12 held

No further runtime/dependency work or build. Preserve the checkpoint and
open findings. This does not endorse the incumbent or alter live state.

## Dependency amendment: exact Trixie route (technical design)

Status: proposed for independent technical review and parent acceptance
before implementation. The human's A approval supplies the dependency class;
it supplies no source, image, platform, P3 or coverage acceptance.

### Observations and supplier applicability

The parent ran sequential, read-only, network-disabled native ARM containers
for the exact approved application Python and PostgreSQL bases. The first
attempt had refused before execution at an identity guard; its correction
received independent review. The successful inspection bound the exact child
manifest descriptor, registry config chain, local rootfs diff IDs and normalized
runtime config fields. The Engine image ID was the index digest; it was not
misreported as a config ID. Containers and exact acquired references were
removed without force or prune; all four reference inventories matched on
every probe. Physical containerd content/snapshot byte parity is not claimed.

| Observation | Application Python base | PostgreSQL base |
| --- | --- | --- |
| Distribution | Debian 13 (Trixie) | Debian 13 (Trixie) |
| Main runtime | Python 3.12.15 | PostgreSQL 16.15-1.pgdg13+2 |
| libc6 | 2.41-12+deb13u4 | 2.41-12+deb13u4 |
| libssl3t64, openssl, openssl-provider-legacy | 3.5.7-1~deb13u3 | 3.5.7-1~deb13u3 |
| libpq5 | Not installed in the unmodified base | 18.6-1.pgdg13+2 |

Both bases supplied the same observed regular files:

- `/usr/lib/aarch64-linux-gnu/libssl.so.3`: 1,195,960 bytes,
  SHA-256 `b3b9a479537bded757b818bb787413d8f8f636135e6546c84e90688eca1dc842`.
- `/usr/lib/aarch64-linux-gnu/libcrypto.so.3`: 6,302,952 bytes,
  SHA-256 `809909371a1db7d2b9cac4c2fa2eff63eb6169d5979416d94155955a7ad32516`.

Each file resolves to its `libssl3t64` dpkg owner. The PostgreSQL base's
`/usr/lib/aarch64-linux-gnu/libpq.so.5.18` is 395,720 bytes, SHA-256
`094cbe08c8c6134b91b1946e42012318728003cf2dd2fcc0ab1ee9821ba38f58`,
owned by `libpq5`. Its numeric `PQlibVersion()` has not been observed and
must not be inferred from its package name. `PSYCOPG_LIBPQ_VERSION` stays
unresolved until actual loaded-library evidence supplies it under D1/D2.

[Debian's CVE record](https://security-tracker.debian.org/tracker/CVE-2026-84782)
and [DSA-6531-1](https://security-tracker.debian.org/tracker/DSA-6531-1)
identify Trixie `3.5.7-1~deb13u3` as fixed for CVE-2026-84782, whereas
`3.5.7-1~deb13u2` is affected. This is the exact supplier backport/advisory
binding, corroborated by the installed package version and file bytes above.
The upstream affected 3.5 range still includes the `3.5.7` banner; retain that
input and the High / CISA CVSS 3.1 8.2 severity. The supplier's distribution
package classification excludes this exact revision; the version banner alone
does not. This is applicability evidence for these two observed ARM precursor
instances, not final-image P3 classification or a completed incumbent comparison.
Final bytes must be inventoried after the merge. No other finding is closed.

### Source, repository and key binding

The exact approved indexes and both platform child/config identities in A
remain the only candidate set. Only ARM was executed; AMD metadata is not
native proof. No mutable tag resolution or substitute digest is permitted.
PostgreSQL 16.15 and the observed libpq 18.6 belong to currently supported
[PostgreSQL release lines](https://www.postgresql.org/support/versioning/).
This does not settle all component advisories or the loaded libpq version.

The PG base supplies exactly one PGDG source:
`http://apt.postgresql.org/pub/repos/apt trixie-pgdg main 16`, signed by
`/usr/local/share/keyrings/postgres.gpg.asc`. Source-file SHA-256 is
`c070ae8f9f72df1c4f03a4a4a04629b0546a9fa92be2620ebd92285722999805`.
The key file SHA-256 is
`ab3ea5fa18220d88318cd9e41d1e4e709c9003c71494f9022cbd76353ba7c5e1`.
It is byte-identical to E2's independently retained, native-gpg-listed key:
primary `B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8`, no subkeys. This
fingerprint attribution is by exact key-byte lineage, not a fresh Trixie gpg
execution. No host gpg was available; none was installed and no parser or key
import substituted. The canonical preflight must re-list with the existing
base tool and refuse missing or different evidence.

Both bases use Debian's configured Trixie, Trixie updates and security origins.
`/usr/share/keyrings/debian-archive-keyring.pgp` is SHA-256
`506b815cbb32d9b6066b4a2aa524071e071761e7e7f68c3ac74f3061ba852017`,
equal to the previously bound keyring bytes despite the `.pgp` path suffix.
Copy the PGDG source and key exactly from the approved PG base for the Python
builder, and verify their hashes before resolution. Preserve the base's Debian
sources/keyring; no new trust, arbitrary origin, host install or unsigned
acquisition is authorized. Signed index origin, version, architecture, size
and `.deb` SHA-256 must still bind every package before installation under D3.
No new source or alternate key follows from a resolver failure (F4): the next
release checkpoint uses only the bound bases' configured live origins, with no
snapshot or older-version fallback, so superseded exact requests
(`libssl-dev=3.5.7-1~deb13u3`, `libpq-dev=18.6-1.pgdg13+2`) are an expected
refusal. The historical D3 conditional official-archive authority is not
silently revoked; any later use needs its own reviewed bounds. The SDK
snapshot recipe is untouched.

Full identities used by source (F7; ARM executed, AMD metadata only):

| Item | `sha256:` digest |
| --- | --- |
| Python index | `a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704` |
| Python ARM child | `6c6ae3622772575c3ac02ecb2b02a06d05f19e1713a0cbff476ef37bca79e90f` |
| Python ARM config | `7efd45553a98be3d940b73600550669831c0be34f30c521159e7030a91fcdee6` |
| PG index | `9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97` |
| PG ARM child | `d735d89e0f050dd5efa611ad633e44e06b526da77b04a7501cece311cd032375` |
| PG ARM config | `94a8e6634f916ffafee47d9be81c53d964e6ed2f5175224fab66b2abacae7279` |
| PG AMD config (metadata) | `066167ff39c2a612402ce99b734ea1cff92a9d1f2ac52f697a5f0384f0d88d6b` |

The PGDG source file SHA-256 changed from E2's Bookworm
`bb4db09b9c75a5cede3fa89644fb5fbe277c614ef57547509e3472860e63eedb` to the
Trixie value above; the key bytes did not.

### Package and payload design

Keep C Psycopg exactly 3.3.6 and all already approved wheel/sdist hashes and
offline build rules. No `psycopg-binary`, private libpq, pure fallback, Cython,
new Python package, build backend, Go image or compiler class is added.
The final libpq remains the one PGDG `libpq5` in the PG base, shared by Psycopg
and the packaged clients. Match `libpq-dev` exactly to `18.6-1.pgdg13+2` and
that origin; verify headers, actual runtime numeric ABI, loaded file identity
and bounded cancel capability before any acceptance. Per-platform manifests
must be derived, signed-index-bound and re-resolved without source guessing.
Differing platform numeric versions refuse; no split global constant is added.

Retain additions-only installation. For the frozen Trixie Python base, E-g's
header policy becomes exactly one installed native `libssl3t64` row at
`3.5.7-1~deb13u3` and no `libssl-dev` row, adding only the matching
`libssl-dev=3.5.7-1~deb13u3` request. Preserve the pre-simulation guards for
missing, duplicate, foreign, residual-config and mismatched rows, all baseline
holds, signed-index checks, and refusal of changes to any preinstalled package.
The final missing-only closure remains separate and gets no builder header.
The old Bookworm .20 constraint must not generalize to new packages or bytes.

The unmodified native ARM Python payload was observed separately with the
already reviewed payload program and `arm64 --no-exclusion`, under `-I -B`:
1,722 entries, 82 ELF files, 78 lib-dynload names, 77 fresh-process successful
imports, and only `_tkinter` failing. That intentional refusal is raw baseline
evidence; no file was removed. Compared with the old base, `nis` is absent
from the vendor payload. No production RepoMap direct `import nis` or
`from nis` was found. This is an observed consequence of the approved base
change, not a new product-side deletion; compatibility still needs scoped
product proof. Record the optional-module change in P2 rather than inventing
an unchanged CPython module set.

The parent proposes the same narrow D4 mechanism, re-bound only to the new
ARM index `a0f57064...`, child `6c6ae362...`, config `7efd4555...`:
regular `/usr/local/lib/python3.12/lib-dynload/_tkinter.cpython-312-aarch64-linux-gnu.so`,
70,584 bytes, SHA-256
`9fe4f2c93a746b000a15ebb6fbb71ea33b3b7888efb70e3c1296fac8b30c2c96`,
ELF64 little-endian AArch64 (183). Only `libtcl8.6.so` and `libtk8.6.so` are
missing; this is the sole failed module. Freeze all 77 observed successful
module names from the actual baseline, not the old set. Before one exact
unlink, require every current path, regular-file, byte, architecture, native,
missing-pair and import-set guard. Then prove every other entry, mode, link
and byte unchanged, 81 retained ELFs resolving, and all 77 imports still
succeeding. No glob, extra trim, dependency installation or AMD entry is
authorized by this amendment. Old Bookworm evidence remains historical, not
a matching exclusion for a new base. Refuse unknown or changed observations.

### License, notices, compatibility and rollback

Preserve ADR 0089 D7, including the exact LGPL-3.0-only Psycopg texts, approved
source archive, attribution and reproducible build instructions; the PostgreSQL
license; and all required distribution notices/source obligations. Dynamic
linking is the chosen mechanism, not a legal conclusion or compliance waiver.
The observed OS copyright assets include OpenSSL's Apache-2.0-led package
notice, glibc's complete mixed copyright/license record and libpq's complete
PostgreSQL-led record. They are not reduced to one blanket image license.
Their full package copyright texts and hashes were retained for review.
The libssl3t64 copyright hash is
`6a7da622fe0637a334d2a8fc470852d2ffb77d9a2b2f930f854e32a41ad6ef35`;
libpq5 copyright is
`afcc052a946b4117667527211b4ca303f07044f5585222f4c8f577e0764b2123`;
libc6 (glibc) copyright is
`f5788886720a2605a946e81d571e6c8162b09f58d2e2ceb8d36e5768fccd850d`.
The final image must retain those assets, CPython's license and any added
closure package's notices and applicable source material, with actual P2
presence and provenance proof. Missing license/provenance is a refusal.

The Python patch, Trixie/glibc/ABI and possible collation changes require
disposable PostgreSQL/D9 backup/restore and runtime compatibility proof. No
live data directory, migration, deployment or incumbent safety endorsement
is authorized.

`POSTGRES_RELEASE_IMAGE` has more consumers than the recipe (F3):
`runtime/compose.py` runs the local server on it with the persistent
`./postgres-data` bind (`--locale=C` initdb), so merging moves an existing
install's data directory from Bookworm to Trixie glibc 2.41 and ICU;
`tools/system/compose_topology.py` and `tools/smoke/lifecycle.py` use it; the
outer sandbox preloads it (`PRODUCTION_POSTGRES_IMAGE`) and the one pgvector
`production_postgres_base_image` field mirrors it (not a pgvector/D15 change).
C-collated creation limits the risk; ICU-provider restores are not covered.
The required D9 proof is the ordinary node
`d9_extension_restore.int.test.py::test_d12_trixie_backup_restore_and_collation_refusals`:
on the exact Trixie server in owned disposable clusters, a C-locale round trip
with an unchanged archive, recorded provider/`datcollversion`/ICU facts, and
refusal of a real ICU source and a deliberately tampered collation version
before any `CREATE DATABASE`. It never refreshes a collation version, reuses a
live directory or qualifies an ICU or cross-distribution migration. Live
reuse, startup and deployment remain separate authority.

The existing SDK stays exactly as pinned: no observed
necessity justifies its conditional replacement, and no SDK rebuild is admitted
by this design. Preserve Go 1.26.10's Bookworm builder and the separate test
SDK Go 1.25.10 stage. The existing CGO-disabled helper still needs scoped proof
in the Trixie final environment; its spent component campaign is not repeated.

Alternatives: retaining affected Bookworm requires a separate risk disposition
and was not selected; adding Tcl/Tk expands an unnecessary runtime closure;
upgrading existing TLS packages violates additions-only and is unnecessary
given the observed fixed bases; accepting unbound new digests or an SDK refresh
without necessity exceeds A. The exact-base route fits the observed TLS fix
and preserves system shared ownership, with the documented optional-module
and platform limitations. No performance improvement is claimed.

Rollback only new amendment-owned source edits to the preserved unaccepted
checkpoint. Do not reset unrelated work or reported history, replace the spent
Go record or release/change the held application ledger. Do not change live
state or characterize the incumbent as safe by rolling back.

### Parent acceptance conditions (F1–F7)

F1: sandbox and one pgvector mirror, constant-dependent unit fixtures and the
test-runtime base consumer. F2: the test-runtime header selector binds the
same state and refuses all others before any preference or install. F3/F4:
consumers, D9 proof and live origins above. F5: retained dependency ownership
unproved until the new trim. F6/F7: corrections above. SDK, Go, locks unchanged.

### Implementation and evidence gates

After independent design review and parent acceptance, a separate bounded
implementation may update the two release pins/Python version, exact ARM Tk
entry and 77-import set, exact header selectors, D12 base-config identities and
their affected unit/integration owners. It may update directly affected docs.
No source change was admitted by the docs-only design checkpoint; the later
source checkpoint and its pending gates are recorded in
[the D12 native qualification companion note](../../../../tools/ci/nav46-d12-native-qualification.md). Keep tests finite
through `tools/run_tests.py`, exact selectors and `--no-coverage`; no complete
unit, integration, smoke, staging, system, combined or coverage run is granted.
Exercise negative guards for old/new/wrong pins, sizes, hashes, native identity,
extra missing libraries, retained-byte changes, import-set drift and header
row states. Review the entire resulting patch and final bytes independently.

Required integration remains the exact D12 canonical owner under a separate
fresh parent admission after scoped units and source review, on frozen source,
with no budget-ledger option. The spent E1/E2 are not retried automatically.
Retain its intentional pre-build refusal versus executed checks distinctly.
Record later D9/runtime selectors explicitly when that boundary is changed;
an unexecuted required integration gap blocks completion. No alternative host
pytest, privileged host access or complete suite is authorized.

Package manifests, loaded numeric libpq, same-building-daemon native admission,
final-image identity/provenance/notices/P3, unchanged cleanup and native AMD
evidence remain unsatisfied. ARM observations never qualify AMD. The global
private ownership/retention mismatches remain unaccepted; export needs its own
exact public candidate binding. Hosted CI 62 qualifies only the predecessor;
new coverage is unmeasured and the 82% integration aim remains pending.
The application ceiling stays two total / one per platform / no retries /
zero used, held at zero until every existing release prerequisite permits
release. No budget reserve/consume, application build, new Go campaign,
emulation/builder, live/D15 action or publication is admitted here.

## Decision record

The human operator selected A on 2026-10-23, including the reviewed parent
bounds stated in Status. B and C were not selected. The choices above retain
the reviewed decision context; neither a reviewer nor the parent selected
on behalf of the human. The comparison gap remains unresolved with the named
owner, and affected TLS risk was not accepted. [the D12 native qualification companion note](../../../../tools/ci/nav46-d12-native-qualification.md)
keeps the publication and remaining roadmap gates open.

## Wiring and review-delivery correction (2026-10-23)

The source checkpoint passed 326 scoped Python units, reproduced once on its
final bytes, but remained unaccepted. The producer first identified the family mismatch; independent live-source
review confirmed it and caught the D9 database-forwarding defect before
integration. The managed-image callers paired the new pin with a Bookworm
family, and the D9 helper targeted the old fixture database. This correction changes only
those family values and forwards the configured test database explicitly,
preserving the helper's old default. Group K remains deferred and gated; its
family mirror change authorizes no build or rehearsal.

The earlier result delivered a summary rather than its full saved patch, and
the review sandbox could not read the outside-repository handoff. The entire
actual saved handoff, complete patch, manifest and custody proof are therefore
frozen inputs for this independent correction review. Prior mechanics were
verified, but full prior artifact delivery was not claimed.

Correct the execution record: canonical units run the existing Go coverage,
vet, lint and race gate and build a temporary host test helper. Those five earlier
invocations and both subsequent 36-case correction invocations total seven
canonical unit preparations at the source-wiring checkpoint. No dedicated Linux ARM Go 1.26.10 image
qualification campaign was repeated; its consumed record and script are
unchanged. The application budget remains held with zero candidates used.
Python coverage was disabled; the incidental Go measurement is not product
coverage or a new qualification claim. The parent resolves its conflicting
zero-Go wording by permitting only the canonical ancillary steps, not new
standalone Go work, runner policy changes or another campaign. Two direct
pytest exploratory runs are supplemental only; the canonical cohort covers
their cases. New checks follow the canonical route.

The ordinary D9 Trixie and canonical D12 non-consuming integration nodes are
still unexecuted and require separate fresh parent admission. No runtime,
image, platform, P3, coverage, phase or global-governance acceptance follows.
Historical as-built and earlier decision references remain historical; the
current unaccepted candidate is the exact Trixie route described here. No SDK,
Go source/image, dependency lock, debt, budget or public ref changes occur.

## D9 complete Debian server-version representation (design checkpoint, 2026-10-23)

The first bounded ordinary D9 Trixie probe failed in qualification construction,
before backup/restore or either negative. The actual observed server value was
`16.15 (Debian 16.15-1.pgdg13+2)`. The test helper retained that complete
`current_setting('server_version')` value. The constructor's shared safe-token
grammar rejects its spaces and parentheses, although stored and live server
qualification already compare complete strings by exact membership. The four
host resource/reference inventories matched after cleanup; source, raw index,
staging, HEAD, the protected public checkout and the held application ledger
were preserved. D12 preflight was not started. No application or SDK build was
admitted. The canonical ordinary test-runtime preparation is separate from both.

This amendment is a representation correction within the approved Trixie
PG/D9 compatibility class. Its design must be independently reviewed and
accepted by the parent before implementation. It grants no risk disposition,
new platform, build budget, migration, live-directory reuse or image acceptance.

### Exact contract proposed before implementation

- Only `TrustedArtifactQualification.allowed_server_versions` gains a bounded
  additional form: a numeric PostgreSQL release (two or three decimal parts),
  one literal ASCII space, `(Debian `, a Debian package version of 1 to 64 ASCII
  characters beginning with a digit and continuing only with digits, letters,
  `.`, `+`, `:`, `~`, `_` or `-`, and one closing `)`. The entire value must
  match. Existing safe-token server identities remain valid. (Superseded by
  the accepted review bounds in the implementation section below.)
- Keep the complete observed value unchanged in qualification, provenance,
  manifests and comparison. No strip, split, first-token normalization, regex
  prefix comparison, inferred suffix, wildcard, generic vendor description,
  lowercasing or synthesized replacement. Different Debian package revisions,
  bare numeric versus suffixed values, and absent/non-string values still fail
  exact source/target membership unless explicitly and independently qualified.
- Keep client and extension version token grammars, allowed majors, Engine
  identity, ABI, template baseline, declaration binding, quiescence, collation,
  cleanup and all refusal gates unchanged. The separate server grammar must
  never be substituted for the shared extension/client token validator.
- Full-match validation for the new server form rejects tabs, newlines,
  leading/trailing spaces, nested or missing parentheses, control/non-ASCII
  bytes, oversized package strings, arbitrary vendor labels and statement
  punctuation. It does not normalize malformed values into accepted ones.
- No stored archive, historical manifest, schema, CLI or MCP contract changes;
  old exact identities and existing refusal semantics remain intact. Current
  independently supplied qualification can name the complete Debian identity.

Alternatives: stripping to `16.15` would discard the observed package identity
and break the existing raw-string comparison; widening the shared token grammar
would affect extension/client contracts; bypassing validation in test support
would hide the production failure. These alternatives are rejected. No runtime
or test dependency, package metadata, lock or runner policy change is needed.
This introduces no package, license or supply-chain component. Rollback restores
only this amendment's owned hunks and retains the unsuccessful probe and hold.

### Bounded proof required after design review

Update the existing product qualification owner, existing requalification unit
owner and existing D9 Trixie integration owner. Meaningful units must prove the
observed full Debian identity and old safe identities construct; malformed and
non-string server values refuse; actual source/target assessment accepts only
the complete supplied identity and refuses another package revision, a numeric
prefix, wrong Engine/ABI and missing provenance. Keep client and extension
validators unchanged. The real integration node must retain the complete
observed server value through qualification and product backup/restore, then
prove unchanged-archive C round trip and the existing real-provider and tampered-
version refusals before database creation. No ICU migration is qualified.

Only finite exact canonical unit selectors with Python coverage disabled may
run in the later implementation checkpoint; its standard ancillary Go steps
must be disclosed. After review and final-byte reproduction, a fresh parent may
admit the one D9 node and then the non-consuming D12 preflight node once each,
stopping on first failure and recording disposition before another attempt.
The SDK recipe remains unchanged and must be an exact cache hit; no SDK rebuild
or application-candidate build is admitted here. Neither integration node nor
any unit runs in this docs-only design checkpoint. All acceptance and the held
application ledger remain unchanged pending actual evidence.

## D9 exact Debian server-version implementation (2026-10-23)

The parent accepted the design above before any source edit. Its review
bounds supersede the proposed grammar, which allowed `_` and unbounded
release digits:

- Only server qualification entries gain the new form. It is checked with
  `fullmatch` against a module-private pattern: a PostgreSQL release of two or
  three ASCII `[0-9]` parts, each 1 to 4 digits; the literal ` (Debian `; a
  package version of 1 to 64 ASCII characters, beginning with a digit and
  continuing only with digits, letters, `.`, `+`, `:`, `~` or `-` (no `_`);
  and a literal `)`. A whole value is therefore at most 88 characters.
- A server entry passes the unchanged `SAFE_VERSION_RE.match` or the new
  fullmatch. Client entries keep only `SAFE_VERSION_RE.match`, and
  `TrustedExtensionRule.exact_versions` keeps its own unchanged validator.
  The definition of `SAFE_VERSION_RE` and its `.match` use stay
  byte-identical. That includes its existing quirk: `$` admits one trailing
  newline for old tokens. The quirk is disclosed and not tightened here. The
  new form never admits a trailing newline.
- `parse_client_version`, `client_identities_qualified`,
  `qualify_server_provenance` and every other function stay byte-identical.
  Source and target membership remain exact raw-string checks with no strip,
  split, lowercasing, prefix match, normalization, fallback or inferred
  version. Differing source and target strings refuse unless each is
  independently qualified. No new rule requires source and target strings to
  be equal; the existing later-target admission depends on that.
- "No strip" applies to the product version value. The D9 test helper strips
  both its `psql -tA` output and each split value (`ver.strip()`,
  `abi.strip()`), so it is not merely output framing. On the observed GUC it
  is a no-op. The integration node asserts that the manifest's recorded source
  value equals the complete qualified value, which detects any divergence.
- The "tampered-version refusals" above mean the existing deliberately
  tampered `datcollversion` refusal, not a server-version tamper.
- No manifest, archive, schema, CLI or MCP migration occurs.

## D9 runtime observations and ABI refusal evidence (2026-10-23)

The parent closed the server-version source checkpoint after a complete
patch and source review. Its single finalizer reproduction failed before any
Go step or test: bare `python3` resolved to a system interpreter without
`psutil`, and the test-scratch claim refused. That attempt is retained. A
freshly admitted parent reproduction then used the explicit project virtualenv
interpreter and passed 12 tests on identical bytes, with Python coverage off.

The parent then admitted each integration node once. The D9 Trixie node
passed. It restored the unchanged C-locale archive and its content, kept the
complete Debian identity in provenance, and refused both collation cases
before `CREATE DATABASE`. The non-consuming D12 node passed native ARM E3
exploration. It confirmed the exact base, config, trust, trim and import facts
and the fresh PGDG primary fingerprint
`B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8`. It resolved 47 signed
additions-only builder packages and no final-closure additions. Resource
references matched and the existing SDK was a cache hit. No application or SDK
build ran, and the held ledger and spent Go record are unchanged. E3's libpq
number `180006` is derived from the `18.6-1.pgdg13+2` package label.
`PQlibVersion()` was not observed, and nothing was written to source.

Corrections to the server-version records:

- The earlier claim that existing tests covered wrong-ABI refusal was false.
  No unit exercised OS/arch membership or the source/target ABI comparison.
  The product code was correct and is unchanged; the evidence is added below.
- Those tests proved only that *differing and unqualified* source/target
  strings refuse. A later target that is independently qualified still admits
  an unchanged backup. No equality rule exists or is added.
- The canonical unit logs show Go coverage, golangci-lint (0 issues) and the
  race test. `go vet` prints nothing on success, and the temporary helper
  build is not logged. Both are inferred from the unchanged mandatory runner
  path (`tools/build_go_helper.py`), not traced. No Go-module network audit is
  claimed. The source-wiring count of seven preparations stays historical.
  The server-version checkpoint had three preparations (producer RED and
  GREEN, and the parent reproduction). A fourth invocation failed before any Go
  step or pytest.

This evidence is test-only; the product is unchanged:

- Requalification units cover the source side through
  `evaluate_backup_restore_support`. A source with an unknown or `unavailable`
  OS/arch ABI, or a non-mapping compile ABI, refuses. The same unknown value
  is admitted when a qualification lists it, so membership is the only cause.
  On the live target (fake-runner preflight), an unknown ABI fails membership.
  The units then use a target ABI that differs from the source but is
  separately admitted; the product's `qualify_server_provenance` accepts each
  side alone. That target still fails the cross-comparison in both
  directions, and a different `compile_abi` mapping also refuses. Restoring
  the facts re-admits the target. Every refusal returns the exact
  `restore-target-incompatible` code, and the diagnostic text shows which
  guard fired. The manifest is unchanged and no `CREATE DATABASE` runs.
- The D9 Trixie node adds one **deliberately tampered ABI metadata** negative
  between the C dump/drop and the genuine restore. A test-only qualification
  copy admits a synthetic second ABI, with the declaration binding unchanged.
  The source manifest claims that ABI, so the existing cross-ABI guard must
  refuse before creation. The original manifest bytes are restored in
  `finally`, and the archive hash is asserted unchanged. This proves refusal
  only. It qualifies no real cross-architecture, native AMD or ABI-migration
  compatibility. It is unrun and needs one fresh parent admission after review.

## Proposed numeric libpq runtime proof (design amendment, 2026-10-23)

Status: **design accepted by the parent before implementation**
([acceptance and C1–C3](#numeric-design-acceptance-and-conditions-c1c3-2026-10-23)).
The text below is the reviewed proposal, with the C1/C2 clarifications marked
in place. It was proposed before implementation; independent design review and
parent acceptance had to come before any source, metadata or cohort change.
No budget or gate changes here.

Problem: ADR 0089 D1/D2 and choice A keep `PSYCOPG_LIBPQ_VERSION` unresolved
and the ledger held until actual loaded-library evidence exists. E3 supplied
only a package-derived number. Inputs come from the E3 signed projection,
bound to its raw report (171,684 bytes, SHA-256
`324ec20171f8f3c794dceebc01082acdcd1960339a769393dd5ee4dd852cc299`):

- `libpq5` `18.6-1.pgdg13+2` arm64, `.deb` SHA-256
  `26d0c9de6c3939432d94d4ad74db1bd2899c87698e1f96f3ee9396054f44d5dc`, from
  `apt.postgresql.org` `trixie-pgdg`. Its runtime closure is expected to be a
  subset of the 47 builder rows; the pre-install gate must prove that
  expectation for every selected row before installation.
- The PG base's `/usr/lib/aarch64-linux-gnu/libpq.so.5.18`, SHA-256
  `094cbe08c8c6134b91b1946e42012318728003cf2dd2fcc0ab1ee9821ba38f58`, is owned
  by `libpq5`.

Proposed mechanism:

1. **Placement.** The probe runs inside the existing E3 builder action, after
   `resolve()` and its header check, in the same owned native Python-base
   container. The unchanged 400-line `tools/native_apt_prerequisites.py` uses
   its *local* filesystem (cache, `manifest.json`, `rmtree`). The host
   `exec_runner` therefore cannot drive it. Instead, a stdlib probe and the
   helper's exact bytes are staged into the container and hash-verified. The
   base's own `python3 -I` runs the probe, which loads the helper by its
   verified path.
2. **Request.** The probe calls
   `install_prerequisites(run, ["libpq5"], <fresh empty cache>)`. The request
   is a bare name because `_NAME` rejects `=`. The helper holds every baseline
   row, binds signed indexes, downloads only, verifies archives and writes
   `manifest.json`. It then re-verifies and runs one
   `apt-get install --no-download`, then (C1) `apt-mark auto` for the exact
   dependency names, and finally checks the exact added set.
3. **Pre-install gate.** The probe's runner intercepts the one
   `--no-download` install before executing it and reads the just-frozen
   manifest. It requires the schema, native architecture,
   `requested == ["libpq5"]` and the exact `libpq5` version supplied from
   `steps["libpq5_version"]` in the same native server inventory. Every
   (name, version, architecture, SHA-256) row must appear exactly once in the
   just-resolved builder table. The runner refuses absent, duplicate, changed
   or foreign rows and archive drift. It also refuses any selected package
   with an existing `ii` or `rc` row; the helper alone admits a request that
   has only an `rc` row. Zero or repeated interceptions refuse, including the
   already-installed case, in which the helper runs no transaction. The
   captured bytes must hash to the returned `manifest_sha256`. The probe
   reports the manifest before the helper deletes the cache. The probe binds
   the helper's hash because the helper's call order is an implicit contract
   of exactly those bytes; unknown command shapes refuse.
4. **Identity.** Before and after installation, the probe requires the native
   architecture, unchanged pre-existing rows, the fixed `libssl3t64`/`libc6`
   versions and no prior, private or unowned libpq. Afterwards there must be
   exactly one `libpq5`. The `libpq.so.5` realpath must be the PG-base path
   above, with that SHA-256, and dpkg must report `libpq5` at that version as
   its single owner.
5. **Call.** The probe loads that absolute path with `ctypes.CDLL`. It sets
   `PQlibVersion` to `argtypes = []` and `restype = c_int`, calls it, and
   requires a positive integer. `/proc/self/maps` must show exactly one mapped
   libpq, at the verified path. The probe records the integer, file hash,
   owner, version and architecture, the native result, the manifest hash and
   the probe and helper hashes. Any ambiguity refuses.
6. **Consumption.** `candidate()` records `observed` and `package_forecast`
   numbers separately. A missing or failed observation refuses, as does a
   mismatch with the forecast. No dpkg-derived fallback is allowed. Nothing is
   written to source, and the release constants and an empty
   `DYNAMIC_PACKAGE_MANIFEST` stay unchanged.

Authority and network use choice A's actual clauses: "Approval permits
inspecting/acquiring these exact bases only in disposable containers",
"reconciling release and SDK pins/bootstrap prerequisites and their necessary
distro closure", and "scoped unit and container integration proof". A also
requires "Use only vendor-supplied official Debian/PGDG origins/keyrings from
these bound bases" and "No host installation."

After independent review and parent acceptance, this explicitly amends the
earlier [ADR 0089 E1 exploration contract](0089-d12-dynamic-psycopg-and-system-libpq.md#e1-exploration-implementation-checkpoint-2026-10-23)
from index acquisition and simulation to one bounded runtime-subset download
and installation inside the already owned Python builder. It does not amend
build-mode admission, ledger access or any refusal gate. The helper uses only
the configured live Debian/PGDG origins and the existing bridge network. No
host installation, new origin/key/snapshot/fallback, package outside the proved
subset, application/SDK build or risk acceptance is added. A supplies the
necessary distro-closure class; parent admission of the exact frozen probe is
still required. A genuine additional authority gap must be identified and
resolved before execution, never hidden by a report label.

Rejected alternatives:

- A label-derived number.
- A C probe, which needs the compiler and headers.
- Copying the PG-base file into the Python base, which leaves an unowned
  private copy without its dependencies.
- Moving a Python runtime into the PG container.
- New base digests or host packages.
- Binary or static libpq.
- Ad-hoc Docker runs.
- Complete suites.

Other properties:

- Licensing: no new component class is added. Retain each selected package's
  signed source and hash and the `libpq5` copyright recorded above.
- Platform: native ARM only. AMD needs its own native evidence. Byte identity
  binds the number to the server's library, but loading by Psycopg in the
  final image is still separately required.
- Rollback: revert only the new probe, wiring, test and clean-row hunks. Keep
  the evidence and the held budget.

Later bounded owners:

- A new stdlib `tools/d12_libpq_runtime_probe.py` (at most 400 lines).
- Minimal wiring in `tools/d12_dependency_preflight.py`, which is 384 lines and
  must stay at or under 400. If 16 lines are not enough, stop for parent
  scope; do not raise a ceiling.
- The existing D12 integration and preflight unit owners.
- A new clean `src/test/unit/python/tools/d12_libpq_runtime_probe.unit.test.py`.
- Only the new clean metadata and cohort rows.

The helper, SDK recipe, locks, dependencies and runner policy stay unchanged.

The units must prove each refusal before the install is dispatched. They must
show that exactly one offline install is allowed. They must also cover a
wrong, multiple, private or extra mapped library, an invalid API value, a
hash or native drift, and the candidate's no-fallback rule. After review and
exact scoped reproduction, the parent may admit one canonical non-consuming
D12 node on frozen bytes. It requires an exact SDK cache hit and one managed
test runtime, with zero application, SDK or Go-campaign builds; any failure
stops for a written disposition. Loader/C backend, final-image, same-daemon
admission, P3, license, AMD and cleanup gates and the held ledger remain open.

Review must challenge four points: the in-container execution, the helper's
implicit call-order contract, whether a libpq5-only resolution stays a subset
of the builder resolution (a mismatch refuses), and the line budget and
authority above.

### Numeric design review conditions N1-N9 (before implementation)

The prior technical review rated the ABI tests and numeric design ready with
these conditions, but its review-input acknowledgement gate did not close.
This checkpoint adopts the refinements as proposed acceptance conditions and
binds the complete actual prior patch for a completed independent review. No
numeric source or metadata is implemented or admitted by this text alone.

- **Input/output and staging.** The host driver derives the platform, expected
  package version and single server-library path/hash from the current native
  E3 observations, not literals. It stages a bounded input JSON (at most
  256 KiB), the new probe and the unchanged canonical helper in a fresh private
  directory of that owned Python builder. Host read-back must verify the
  exact code and input bytes/hashes before execution. The result is one JSON
  object of at most 128 KiB with a fixed schema, no extra output, actual API
  value, manifest rows/hash, native and library identity. The host independently
  compares returned manifest rows with its resolved builder table and checks
  all expected library/helper/probe identities; a reported boolean is not
  sufficient authority.
- **No host execution.** Host import/driver mode never calls the installer
  locally. The internal container CLI requires an explicit run-bound staged
  marker and input/hash/role binding, and refuses before APT if absent or
  inconsistent. The host verifies the existing canonical run's container
  ownership, exact Python image and native platform before staging/exec. An
  ordinary direct host invocation must fail before any package mutation.
- **Install interception.** The gate is a non-`OSError` refusal such as
  `PrerequisiteRefused`; the helper rewrites `OSError` as command unavailable.
  Only the C1 sequence is permitted: download-only APT preparation, one
  correctly gated `--no-download` install and the exact `apt-mark auto`.
  Unknown mutating command shapes, zero/repeated interception, an existing
  `ii` or `rc` row for any selected package (C2), or any selected identity
  absent from the resolved table refuse before install. Capture and hash the
  manifest before the helper removes its private cache. The runtime-only
  closure being a subset is an expectation enforced by this gate, not an
  already observed fact.
- **Bounded library custody.** Define prior/private/unowned-library searches
  over the canonical loader roots `/lib`, `/usr/lib`, `/usr/local/lib` and
  `/opt`, including nested Python library directories and the process maps.
  Resolve and deduplicate normal usr-merge aliases, refuse unowned/private or
  multiple real copies and any unexpected loaded mapping. This is a bounded
  search, not a claim about every path on an arbitrary filesystem. The
  installed library and its aliases must be owned by the one exact native
  `libpq5`, regular resolved bytes must match the observed server library,
  and `dpkg --verify libpq5` must succeed without mismatch output. Preserve
  baseline rows and fixed TLS/glibc bytes/versions, and retain libpq5 copyright
  existence/hash. No Psycopg installation, product compilation or DB service
  is part of this probe.
- **Observed consumption.** `validate_package_manifest` consumes the verified
  runtime API integer. The package-derived forecast is only an equality
  check and a separately labeled field; it can never supply a missing,
  invalid or failed observation. Constants remain unresolved and manifests
  stay report-only until their separate acceptance gates.
- **Line and evidence bounds.** Put staging, execution and strict parse/readback
  logic in the proposed self-contained module. Preflight wiring stays within
  its remaining 16 physical lines and every owner stays at most 400 lines;
  stop rather than raise a ceiling. Only the already proposed new clean module,
  unit owner and cohort metadata may be added in the later implementation.
  Existing SDK/helper/lock/runner, old inventory and debt fields stay unchanged.
- **ABI evidence precision.** The updated real negative proves a deliberately
  tampered but individually admitted source ABI refuses against the actual
  target, by elimination of the membership branch. It is not native AMD or
  migration evidence. Its runtime execution remains separately parent-bounded.

All original P3, identity, native, ABI, license, cleanup, loader/final-image and
same-building-daemon build-admission gates remain open. The application ledger
is held at zero; no application or SDK build, standalone Go campaign, complete
suite, local coverage or publication follows from this design.

### Numeric design acceptance and conditions C1–C3 (2026-10-23)

The parent accepted this numeric design before any numeric source, metadata or
cohort change. Acceptance followed the complete independent R36 review, which
received all 29 inputs. This is **not** the
[dependency amendment](#dependency-amendment-exact-trixie-route-technical-design)
acceptance with [F1–F7](#parent-acceptance-conditions-f1f7). F1–F7 do not
cover the numeric probe, and N1–N9 and C1–C3 do not change the dependency
route. With this acceptance, the
[numeric amendment to the ADR 0089 E1 contract](#proposed-numeric-libpq-runtime-proof-design-amendment-2026-10-23)
in this ADR, above, is accepted as a design. It admits no numeric runtime execution, and no
source, image, platform, P3 or phase acceptance.

- **C1: exact helper sequence.** The probe's runner permits only the command
  shapes of the hash-bound `tools/native_apt_prerequisites.py`. Read-only:
  `dpkg --print-architecture`, `dpkg-query` (`-W` inventory, `-S` ownership and
  `-L` fixed-state checks for `libc6` and `libssl3t64`), `apt-get indextargets`,
  `apt-helper cat-file` and `dpkg-deb --field`. The probe adds only its own
  read-only post-install `dpkg --verify libpq5` under the established
  [ADR 0089 D2.3](0089-d12-dynamic-psycopg-and-system-libpq.md#implementation-checkpoint-2026-10-22)
  (lines 548–552) rule;
  that is not a helper command.
  Mutating, in this order: `apt-get update`, the `--simulate` and
  `--download-only` installs, and one gated `--no-download` install. After
  that install succeeds, one `apt-mark auto` follows, with exactly the sorted
  manifest package names other than `libpq5`, and only if that list is
  nonempty. Any other mutating command, repeat or retry refuses, and the gate
  runs before the install.
- **C2: every selected package.** A pre-existing `ii` or `rc` row refuses for
  every selected package, not only for `libpq5`. At the actual pre-install
  boundary immediately before dispatching `--no-download`, the gate re-queries
  `installed_packages` and requires both that the entire current installed
  baseline equals the initial pre-update baseline and that no selected package
  has an `ii` or `rc` row (`PARENT-C2-BASELINE`).
- **C3: separate records.** This subsection and a forward link at the
  [ADR 0089 E1 checkpoint](0089-d12-dynamic-psycopg-and-system-libpq.md#e1-exploration-implementation-checkpoint-2026-10-23)
  name the two acceptances separately. Earlier records are unchanged.
- **Loader (optional strengthening, adopted).** Refuse a nonempty `LD_*`
  variable, a nonempty `/etc/ld.so.preload`, or a configured loader path
  outside `/lib`, `/usr/lib`, `/usr/local/lib` and `/opt`. Directory
  containment is normalized and resolved against the canonical roots (preserving
  usr-merge and benign Trixie paths while rejecting `..` traversal and symlink
  escapes), and `ld.so.conf` include traversal refuses cycles and `>64`-file
  overflow before any APT command (`PARENT-LOADER-CONTAINMENT`). This grants no
  new search authority; the bounded-root and process-maps proof stays.

No numeric substitution or global policy change is made. Source status stays
unaccepted, and written code is not runtime proof.

**Implementation scope stop (2026-10-23).** The producer stopped before writing
any numeric code. The read-only cohort selector
`src/test/unit/python/tools/d12_builder_headers.unit.test.py`
(`test_the_bound_header_survives_into_the_validated_candidate_manifest`)
calls `candidate()` directly, with no runtime observation, and asserts that
the manifest is `valid`. Under N1–N9, `candidate()` must refuse a missing
observation and has no package-derived fallback. Both cannot hold in the
admitted ten-path scope. One of these parent decisions is needed: add that
owner to the write scope, so that its one direct call supplies a verified
observation fixture and keeps its header assertions; or record another
explicit disposition. No numeric module, wiring, metadata, cohort or unit
stage was produced.

### Numeric implementation checkpoint (2026-10-23)

The parent added that header owner to the write scope as a test-fixture
correction only. Its one direct `candidate()` call now supplies a synthetic
record bound to its inputs, and every header assertion is kept. This is not
operator input and allows no fallback.

- **Module.** The new stdlib `tools/d12_libpq_runtime_probe.py` (400 lines)
  holds the host driver, the strict host recheck and the container entry.
  `observe` runs only inside `explore`'s E3 builder action, after `resolve`.
  It requires that container's run, role and retention labels, the Python base
  image and the native classification. It stages the input (at most 256 KiB),
  a run-bound marker, its own bytes and the unchanged helper's bytes in a
  fresh `mktemp` directory. It reads every byte back before the single
  `python3 -I -B` run. It then accepts one JSON object of at most 128 KiB, with
  no stderr. The container entry refuses before any command unless the
  marker, the four hashes, the private directory, native Linux and the `-I -B`
  flags all match and the loader check passes. `Guard` dispatches only the C1
  shapes, in order, and gates the one `--no-download` install (C2 included).
  The host rebuilds the record from its own inputs, and `candidate()` consumes
  only that record. The dpkg-derived number is a separate `package_forecast`
  equality check, never a fallback.
- **Wiring.** `tools/d12_dependency_preflight.py` grew from 384 to 393 lines.
  The release constants, helper, SDK, locks, runner and dependencies are
  unchanged. The D12 int owner's E1 branch now asserts an oracle. The observed
  library path and SHA-256 must equal the server inventory's `libpq5` file.
  The API must equal the candidate number and match the server package's
  major and minor version. The owner remains 400 lines.
- **Metadata.** Two clean file rows and two cohorts were added:
  `product6.navigation45.d12numeric1.tools` and `.test_owners`. Every old
  record is byte-preserved.
- **Units.** The six sealed selectors ran once each. RED, on the interface
  scaffold, had 76 failures and 114 passes and no collection error. GREEN, on
  the final code and metadata, had 190 passes. Changed-file compile, Ruff F,
  mypy and file-length checks pass.

Fakes prove refusal order, the C1 sequence and the host recheck only. They do
not prove numeric runtime, native ARM or AMD, image, P3 or source acceptance.
Independent review and parent static review of the initial implementation
identified three pre-E4 blockers requiring bounded correction within the
accepted design before any container node is admitted:

- **`PARENT-C2-BASELINE`.** `Guard.before` precedes `apt-get update` and the
  helper's own baseline. Because the helper's `baseline_pins`, `plan` and
  `_changes` count `ii` rows, a selected package acquiring an `rc` row between
  the initial snapshot and the helper's baseline could pass the initial C2
  check. `Guard._gate` now re-queries `installed_packages` at the actual
  pre-install boundary before dispatching `--no-download`, requiring that the
  entire current database equal `Guard.before` and that no selected package
  hold an `ii` or `rc` row.
- **`REVIEW-B1-DPKG-VERIFY-FILTER`.** Under
  [ADR 0089 D2.3](0089-d12-dynamic-psycopg-and-system-libpq.md#implementation-checkpoint-2026-10-22)
  (lines 548–552), slim
  bases with `dpkg` `path-exclude` filters always list excluded documentation
  and locale files as missing (`dpkg --verify libpq5` exit 1). The probe now
  inlines the stdlib D2.3 ordered `path-exclude`/`path-include` filter from
  `/etc/dpkg/dpkg.cfg.d`, accepts exit 0 or 1 only when every reported line is
  a `missing` path excluded by the image's active rules (with `path-include`
  overriding earlier `path-exclude`), and refuses empty exit 1, any other exit
  code, any non-missing/checksum line, and any line naming the library, its
  runtime aliases or its copyright file even if a rule would exclude it. The
  active rules and filtered lines are bound in the probe result and rechecked
  by the host.
- **`PARENT-LOADER-CONTAINMENT`.** Lexical prefix checks on `ld.so.conf` entries
  admitted `..` traversal (`/usr/lib/../../home/app/lib`) and in-root directory
  symlinks resolving outside `/lib`, `/usr/lib`, `/usr/local/lib` and `/opt`,
  and `include` expansion silently truncated at 64 files. The probe now checks
  both lexical normalization and `realpath` containment against the canonical
  roots under `Native.root` (preserving usr-merge and benign missing-but-contained
  Trixie directories) and refuses `include` cycles or `>64`-file overflow
  before any APT command.
- **N4 stdout newline bound.** Separately from loader containment, the
  container entry enforces the 128 KiB stdout bound including the trailing
  newline (`len + 1 > RESULT_LIMIT`).
- **Guard-correction units.** Both Python owners (`tools/d12_libpq_runtime_probe.py`,
  reduced from 400 to 399 lines, and
  `src/test/unit/python/tools/d12_libpq_runtime_probe.unit.test.py`, 399 lines)
  are now at 399 lines (`<= 400`). The six sealed unit selectors ran once in RED (`d39r`:
  13 failed, 193 passed, 0 collection errors) against the unmodified probe and
  once in GREEN (`d39g`: 206 passed: 88 probe, 40 inner, 11 owner, 18 native
  APT import, 34 builder headers, 15 exploration admission) with `--no-coverage`
  and `--jobs 1`. The `finalizer` reproduction (`d39f`) is deferred to
  `revise_close`. Canonical Go coverage, lint and race ran inside the unit
  runner (vet and temp helper builds inferred from the unchanged runner path;
  no command trace, network audit or standalone Go campaign ran). Complete
  suites (`unit`, `int`, `smoke`, `staging`, `system`, `combined`) and Python
  coverage were intentionally unselected. Carried gaps (four prior unrelated
  omissions, 23 selection rows, old unbound ownership and long Exit line 1927)
  were not adopted in this four-file scope.

All original holds remain open: the incumbent comparison gap under Samuel
Leighton Lair, final-image and P3 qualification, native AMD evidence, positive
build admission, ABI/loader/license/cleanup gates, `PSYCOPG_LIBPQ_VERSION = None`,
`DYNAMIC_PACKAGE_MANIFEST = {}`, the held application ledger (`maximum_total` 0)
and the spent Linux ARM Go campaign.

### Native ARM E4 numeric observation and operator handoff (2026-10-23)

Independent code review of the four-file pre-E4 guard correction completed
(`NUMERIC_IMPLEMENTATION_REVIEW_COMPLETE: yes`, `E4_READY_FOR_PARENT: yes` at
the code level), closing all three named blockers (`PARENT-C2-BASELINE`,
`REVIEW-B1-DPKG-VERIFY-FILTER`, `PARENT-LOADER-CONTAINMENT`). Both the producer
GREEN stage and the `revise_close` finalizer ran the same six
exact unit selectors once with `--no-coverage` and `--jobs 1` (selector
ownership preserved by reference to
[the implementation checkpoint above](#numeric-implementation-checkpoint-2026-10-23)
and [the D12 native qualification companion note](../../../../tools/ci/nav46-d12-native-qualification.md),
with `--jobs 1` bound to the parent-retained `UNIT-finalizer-RESULT.json`
`--report-dir .../unit-report-finalizer` invocation, exit `0`, log `2,371`
bytes, SHA-256
`9eb8f4cbc47f5e5036ff1dd057985ea5ad75452c069b903c7e1365fd9301f559`, on
`tools/d12_libpq_runtime_probe.py` SHA-256
`c3d63cf7aa34252420fb2749d0d46febce26d5c3e376211a4f314f97e0ca50de` and
`src/test/unit/python/tools/d12_libpq_runtime_probe.unit.test.py` SHA-256
`2e9fdca9b36c072ce34fb24fcdc6e177238fb2187bbbea7d2c4a6dd3dc87b6a5`); the
finalizer reproduced **206 scoped passes** (`88 + 40 + 11 + 18 + 34 + 15`) on
identical GREEN hashes. The parent mechanically verified all 123 entry file
hashes, all four actual patches, full reviewer evidence delivery, frozen source
bytes, raw Git index/staged content/`HEAD` and protected public-checkout
preservation. No unit or integration tests are rerun in this docs-only closeout.

- **Canonical ARM E4 execution.** The parent admitted and executed one canonical
  ARM E4 integration node:
  `src/test/int/python/repomap_kg/runtime/d12_core_image_refresh.int.test.py::test_d12_core_image_refresh_candidate_round_trip`
  via `tools/run_tests.py --suite int --no-coverage --jobs 1
  --pg-container-port 55433 --d12-core-image-profile linux/arm64
  --d12-core-image-preflight --d12-core-image-source-sha256 <frozen-source-sha256> --` that
  exact node, with no `--d12-core-image-budget-ledger` option (source-domain separation
  documented in [ADR 0092](0092-public-native-d12-qualification.md#1-current-d12-remediation-state-and-distinct-source-identity-domains)). It
  **passed in 17.36s** (`mode: "exploration"`, `result: "observed"`,
  `refusals: []`).
- **Native ARM builder runtime observation.** Inside the native `linux/arm64`
  (`dpkg: "arm64"`, `machine: "aarch64"`) disposable Python builder, signed APT
  index acquisition and additions-only builder simulation (`E-g`) resolved
  **47** builder package rows (PGDG fingerprint
  `B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8`, keyring
  `/usr/local/share/keyrings/postgres.gpg.asc` SHA-256
  `ab3ea5fa18220d88318cd9e41d1e4e709c9003c71494f9022cbd76353ba7c5e1`, source
  `/etc/apt/sources.list.d/pgdg.list` SHA-256
  `c070ae8f9f72df1c4f03a4a4a04629b0546a9fa92be2620ebd92285722999805`, server
  config digest
  `sha256:94a8e6634f916ffafee47d9be81c53d964e6ed2f5175224fab66b2abacae7279`),
  and the subsequent gated runtime-subset installation (`apt-get install
  --no-download`) selected and installed **10** runtime package rows
  (`libcom-err2` `1.47.2-3+b12`, `libgssapi-krb5-2` `1.21.3-5+deb13u1`,
  `libk5crypto3` `1.21.3-5+deb13u1`, `libkeyutils1` `1.6.3-6`, `libkrb5-3`
  `1.21.3-5+deb13u1`, `libkrb5support0` `1.21.3-5+deb13u1`, `libldap2`
  `2.6.10+dfsg-1`, `libpq5` `18.6-1.pgdg13+2`, `libsasl2-2` `2.1.28+dfsg1-9`,
  `libsasl2-modules-db` `2.1.28+dfsg1-9`; `manifest_sha256`
  `2af0a3561466c1aa4b395658416a55832738e71b1f7a17e077078829a8b5c142`) verified
  before installation as an exact subset of those 47 builder rows, with
  `final_closure_additions: []` (`0`). Runtime `PQlibVersion`
  returned **`180006`** from the hash-bound distribution-owned shared library
  `/usr/lib/aarch64-linux-gnu/libpq.so.5.18` (SHA-256
  `094cbe08c8c6134b91b1946e42012318728003cf2dd2fcc0ab1ee9821ba38f58`, `libpq5`
  `18.6-1.pgdg13+2` `.deb` SHA-256
  `26d0c9de6c3939432d94d4ad74db1bd2899c87698e1f96f3ee9396054f44d5dc`,
  `copyright_sha256`
  `afcc052a946b4117667527211b4ca303f07044f5585222f4c8f577e0764b2123`).
  `package_forecast: 180006` was checked for equality only
  (`host_forecast_substituted: false`, `libpq_label: "runtime PQlibVersion;
  forecast is equality only"`), never used as the measurement. Staged custody
  bound `probe_sha256`
  `c3d63cf7aa34252420fb2749d0d46febce26d5c3e376211a4f314f97e0ca50de`,
  `helper_sha256`
  `df616a151d062b4ade001bbd029007b2f414aa22422de63c520895663b850c5f`,
  `input_sha256`
  `d1333ae6675c079aaa674bd45c46f438cac6ea4c47fea6fb1566c14a2adc51d6` and
  verified `repomap-d12-libpq-record-v1` record SHA-256
  `ca08803328bfc51cd6470d86d41fb6edbbb5bab546fe6359268a9da79a006a4c`. Retained
  Python payload kept **81 ELFs** and **77 `lib-dynload` imports**
  (`retained_preserved: true`) with **0** unresolved trimmed dependencies. The
  raw exploration report is `174,484` bytes (SHA-256
  `119a7707e08168de43ff8c5bbdeeca1a2c3c7aa264722330d915ec543fc663d0`, delivered
  to this closeout as a sanitized projection; the raw report is retained by the
  parent and not claimed reviewed).
- **Cleanup, resource parity and preservation.** Execution used one ordinary
  managed test-runtime materialization (`managed_test_runtime_image_build_count:
  1`; `new_managed_test_runtime_cache_images: 1` at the inner sandbox residue
  boundary and `0` in outer host cleanup; raw cleanup report SHA-256
  `99e06ecf8353f12c909ba6be2dc0e84f1800e25ec877250514fe08a0dca17169`), an
  existing exact SDK cache hit (`SDK_rebuilds: 0`), `application_builds: 0`,
  `managed_system_candidate_image_build_count: 0`,
  `product_or_build_profile_build_count: 0`,
  `managed_external_base_pull_count: 0`, `unmanaged_build_count: 0`,
  `unmanaged_pull_count: 0` and `new_dedicated_Go_campaigns: 0` (the spent prior
  campaign was not replayed). Parent host image, container, volume and network
  reference inventories matched before and after, the owned server was removed,
  owned containers matched baseline, `candidate_image_id` was `null` and
  ephemeral/image/volume/intermediate residue was `0`. Frozen source, Git
  indexes, staged content and `HEAD`, the protected public checkout, the held
  `maximum_total: 0` application ledger (`0` used), the spent Go record,
  `PSYCOPG_LIBPQ_VERSION = None` and `DYNAMIC_PACKAGE_MANIFEST = {}`
  (`written_to_source: false`) are preserved.
- **Review nonblockers and carried limitations.** `NB1` and `NB2` are resolved
  in these two documents. `NB3`–`NB8` and inherited gaps are carried explicitly
  without source edits as code-level nonblockers for this sealed-base numeric
  observation: `NB3` (exit 0 with only filtered missing lines accepted, matching
  `release.py`), `NB4` (raw filtered `dpkg --verify` lines and active rules are
  transient in `observe` and host-rechecked in `verify_result`, but omitted from
  `RECORD_KEYS` in the consumed `repomap-d12-libpq-record-v1` record, so no raw
  `dpkg` filter-line claim is established by the retained E4 record), `NB5`
  (D2.3 `/etc/dpkg/dpkg.cfg.d` non-dot file filtering without `/etc/dpkg/dpkg.cfg`,
  failing closed on missing main-file rules while protecting library and
  copyright paths), `NB6` (trusted symlinked canonical roots matching
  `libpq_files` traversal, `/` in production), `NB7` (no exact 64-file positive
  or relative-include unit test; shared `"drifted before installation"`
  substring where only `Guard._gate` refuses `late-drift`) and `NB8`
  (semantically neutral `140`–`170`-character compaction clean under Ruff `F`,
  `file_length` and strict `mypy`), plus prior `N1`, `N2`, `N3`, `N7`, `N8`, the
  four unrelated omissions, 23 selection rows, old unbound ownership and long
  Exit line 1927.
- **Qualification boundaries and open holds.** The report establishes
  `build_readiness: "NOT ESTABLISHED"`, `p3: "inputs only"` and `mode:
  "exploration"`. The current daemon observed `linux/arm64` as `native` and
  `linux/amd64` as `emulated`; native AMD requires an operator-provided already
  available native environment, and no alternate builder, emulation, capacity or
  remote runtime is authorized here. (Subsequent direct human steering on
  2026-10-23 answered the native environment question by selecting public CI for
  native platform qualification/builds referencing Theme Forge Nebular Fusion;
  see [ADR 0092](0092-public-native-d12-qualification.md),
  [the D12 native qualification companion note](../../../../tools/ci/nav46-d12-native-qualification.md),
  [the D12 native qualification companion note](../../../../tools/ci/nav46-d12-native-qualification.md),
  and [the D12 native qualification companion note](../../../../tools/ci/nav46-d12-native-qualification.md),
  which supersede the local-native-environment operator request in current
  status and record the parent's accepted bounded first-checkpoint hosted
  architecture and private-readiness implementation.) No image, source phase,
  same-daemon positive build admission, final-image loader/C
  Psycopg/security/license/provenance/P3 qualification, incumbent comparison or
  hosted coverage/publication acceptance follows. The incumbent comparison
  remains an unresolved gap owned by Samuel Leighton Lair under approved Choice
  A, not a fresh operator acceptance requirement or incumbent endorsement. The
  two-total / one-per-platform / no-retries application ceiling stays held at
  `maximum_total: 0` (`0` used). All original refusal gates and live/D15
  exclusions hold; the 82% coverage aim remains hosted-only and unmeasured
  (`Python_coverage: false`). For this docs-only closeout, `unit`, `int`,
  `smoke`, `staging`, `system`, `combined`, `compileall` and Python coverage
  were not run (`docs-only`); verification is `git diff --check`, `git diff
  --cached --check` and local link/anchor checks. Neither the roadmap nor this
  phase is complete or accepted.
