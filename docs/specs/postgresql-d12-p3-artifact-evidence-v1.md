# D12 P3 artifact evidence checkpoint

Status: diagnostic evidence published for review. D12/P3, image, native-platform,
merge and deployment acceptance remain open under
[ADR 0087](../adr/2026/10/0087-d12-image-evidence-and-core-security-prerequisite.md).
[Proposed ADR 0099](../adr/2026/10/0099-d12-p3-artifact-evidence-and-remediation-hold.md)
records the remediation proposal; it grants no implementation or new build.

The dated [machine record](postgresql-d12-p3-artifact-evidence-v1.json) is
diagnostic data, with SHA-256 `fa0f95f6c826aed09c07d92702a979ebd309240d8c79bef584035f61a5134bd7`. It contains the immutable input
identities, observed populations, remaining candidates and explicit gaps.
It is not a runtime admission manifest or a public collector implementation.

## CI72 and the separate inspected input

[CI72 attempt 1](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/40457734398)
assembled the native AMD candidate, completed its 2,000-row archive round trip
and five diagnostic system phases, then deliberately failed the P3 hold.
Its unit population passed 13,836 items with 40 skips; measured integration M
passed 1,812 with 12 skips. Recorded coverage arithmetic is:

| Population | Statements | Branches |
|---|---:|---:|
| Unit | 53,607 / 60,931 = 87.9798% | 17,400 / 19,864 = 87.5957% |
| Integration M | 54,934 / 60,931 = 90.1577% | 16,356 / 19,864 = 82.3399% |

These figures exceed the unchanged hard 85/85 unit and 80/80 integration gates
by at least two percentage points. Raw joins and arithmetic were checked; the
complete project acceptance validator was not executed under the spent proof
allowance. The run is not an accepted image/P3 result. These measurements
belong to CI72's existing candidate, not the later Python base inspection.

The separate inspected input is the prospective Python 3.12.16 slim-Trixie
index `sha256:962f801b08c870ac2a51b72bf02dae38c9a4162319e5e882ec244e198188d54e`.
The application recipe still pins Python 3.12.15. No pin, dependency, lock,
workflow, release version or default changed in this publication.

## Inert acquisition and audit

Eight exact AMD/ARM gzip blobs were acquired once: 87,312,078 compressed bytes.
Index/child/config/blob SHA-256 and all eight uncompressed config diff_ids
matched. The audit covered 274,937,856 expanded bytes, 12,335 logical members
and 12,347 conservative header/extension units. Forty-five synthetic cases
passed before the first whole-set audit. Neither archive extraction nor image
code, module, binary, loader, Docker/container or emulation execution occurred.
No RepoMap test population, coverage run or application build was added.

| Observation | AMD64 | ARM64 v8 |
|---|---:|---:|
| Installed Debian package claims / source-version pairs | 87 / 61 | 87 / 61 |
| Matching package MD5 rows | 2,346 | 2,345 |
| Not-observed or unresolved MD5 rows | 2,048 | 2,049 |
| Those rows below `usr/share` | 2,046 | 2,047 |
| Matching directly observed conffiles | 70 | 70 |
| Copyright text observations | 85 | 85 |
| lib-dynload modules | 78 | 78 |
| Regular untainted ELF objects inspected | 745 | 744 |

The two remaining unresolved MD5 paths are the withheld Perl hardlink aliases.
ELF counts exclude those aliases and describe section-header metadata;
PT_DYNAMIC, loader resolution, imports and ABI were not executed or qualified.
Both `_tkinter` byte hashes/sizes/machines equal the existing 3.12.15 entries,
while their OCI index/child/config identities change. The old complete
allowlists do not admit the new index automatically.

Both inspected Python bases still contain `libc6 2.41-12+deb13u4`. These
Debian package, Perl, file-metadata and CA-store observations concern the
Python build stage and its ABI target. The final runtime is based on
PostgreSQL and takes the Python `/usr/local` payload from that stage; its glibc, CA store
and remaining Debian userland require separate PostgreSQL-base evidence.
A Python-base replacement alone cannot clear final-userland findings. Fifty-nine source/version
pairs match the prior catalogue exactly; its 72 unresolved source rows retain
their individual severity, feature and disposition requirements. The new
`ca-certificates 20250419+deb13u1` and `tzdata 2026e-0+deb13u1` claims were not
assigned old-version verdicts. Their primary tracker pages were captured.

The exact dpkg exclusion policy and full package control/file/md5 metadata
were observed. Each unresolved `usr/share` row has a lexical exclusion-policy
association, with architecture-specific document paths explaining the count
difference. These associations are not executed dpkg or license admission.
Shared copyright directories for libgcc-s1, libstdc++6 and libncursesw6 point
to observed gcc-14-base or libtinfo6 text; that is not a legal-admission verdict.
Generated/unowned paths and publisher/attestation provenance remain gaps.
The prior CI72 sample comparison is 36 equal files, one unresolved Perl
hardlink and zero demonstrated differences, not a whole-image comparison.

## Python distribution and vendor candidates

The bases contain pip 25.0.1 and 18 vendored-component version claims. Nineteen
exact version queries produced 43 overlapping OSV GHSA/PYSEC records, grouped
into 22 GHSA candidates: one CRITICAL, eight HIGH, ten MODERATE and three LOW
OSV labels. Eleven captured CNA/ADP records add numeric scores for selected
aliases; the largest fetched score is 8.9. Nine other CVE aliases and two
groups without a CVE alias retain unknown primary numeric severity. Labels
cannot lower an applicable numerical score; these are not 22 confirmed final
application vulnerabilities or a blanket risk disposition.

The machine record preserves each group, version, reported metrics and unknown.
Setuptools PackageIndex, msgpack C-extension and Windows/macOS conditions
need actual vendored-subset and platform classification. Eleven queries found
no record for the sent name/version; none is cleared. CacheControl and
typing_extensions name equivalence was not independently proved. Responses
had no pagination token or error marker and were below their byte caps.
All 32 supplementary request slots were spent; no retry was performed.

The ensurepip pip 25.0.1 wheel has the same captured vendor manifest as the
installed copy; it is a second copy of those claims. Only pip's own license
text was captured there. Packaging files beneath a `licenses` module are code
data, not license text. Vendored-license coverage remains incomplete.

The current [release recipe](../../src/main/python/repomap_kg/runtime/commands.py)
removes pip/setuptools/wheel/packaging and ensurepip before copying the final
payload, and its [final probe](../../src/main/python/repomap_kg/runtime/release.py)
checks build-only absence. Base findings therefore do not establish current
final-image vulnerabilities. Pip/vendor advisories still bear on builder-stage
download/install before removal; hash-bound requirements and offline install
controls are mitigations, not complete build-safety evidence. The inspected
Python build-stage CA package/generated trust store needs its own CA-distrust
disposition; the final PostgreSQL-stage CA store was not inspected here.

## Review and disposition

Independent review inspected inline collector code and compact evidence; it
could not read or rehash raw layers/reports or the public checkout. Parent
custody/source checks own those facts. The parent corrected a false Perl
"difference," labelled the actual public source revision and confirmed both
unchanged `_tkinter` byte identities. Those derived corrections were not
independently rereviewed; collector source and raw audit were unchanged.
No second collector check or audit was needed. Dedicated global-PAX fixture,
generic reserved-whiteout hardening and same-user import/hash timing remain
tool limitations. This is not general OCI-parser qualification.

The proposal retains the P3 hold. Future implementation/native public-CI proof
requires exact supported fixed base inputs, per-finding written dispositions,
publisher/byte/license and ownership evidence, updated frozen payload bindings,
and a fresh bounded execution decision. Preserve dynamic C Psycopg 3.3.6 and
distribution-owned shared libpq, strict release guards and the existing
incumbent-comparison owner. No fifth application start or grant rearm follows.
The evidence binds only to this index and cannot qualify a later rebuild.

## Public supplier references

- [Debian glibc finding](https://security-tracker.debian.org/tracker/CVE-2026-19499).
- [Python 3.12.16 release](https://www.python.org/downloads/release/python-31216/).
- [Debian CA source tracker](https://security-tracker.debian.org/tracker/source-package/ca-certificates).
- [Debian time-zone source tracker](https://security-tracker.debian.org/tracker/source-package/tzdata).

This publication changes evidence documentation only. The next automatic
public workflow must still enforce all existing holds and spent-grant checks.
Its result is pending; no new hosted pass is claimed here.
