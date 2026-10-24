# ADR 0088: D12 bundled-libpq remediation preflight for exact Psycopg 3.3.6

## Status

**Accepted as a conditional preflight (2026-10-22); dependency change NOT
admitted.** At 2026-10-22T14:35:03Z the operator answered "Approve exact
Psycopg 3.3.6 remediation (Recommended)" to a parent decision proposal with
SHA-256 `b1d9c7bad8604ee5b5a44c52de1919cd301bfe34bc9e2d5c367b5d8e1c692319`.
`REPOMAP-PRODUCT6-NAVIGATION44-D12LIBPQ1` records that approval here before any
source change.

The approval is conditional. It allows the pin to move only after the exact
artifacts prove a fixed, supported and licensed library closure. The preflight
in this phase did **not** establish that closure. The pin stays at
`psycopg[binary]==3.2.12` with bundled libpq `170006` (17.6). No dependency,
lock, bootstrap, release-assertion or license asset changed. The
[ADR 0087 P3](0087-d12-image-evidence-and-core-security-prerequisite.md#p3--findings-are-versioned-severity-sourced-and-compared)
hold on the current pin continues.

## Date

2026-10-22

## Context

ADR 0087 accepted D12-A, which kept Psycopg and its bundled libpq unchanged. The
parent then found that bundled libpq 17.6 falls inside the affected range of
[CVE-2026-6477](https://www.postgresql.org/support/security/CVE-2026-6477/).
That advisory gives CVSS 3.0 8.8 and names the fixed releases 18.4, 17.10,
16.14, 15.18 and 14.23. The bundled 17.6 also precedes the 17.7 fix for
[CVE-2025-12818](https://www.postgresql.org/support/security/CVE-2025-12818/).
Under P3 the parent set the candidate build budget to zero. The human ceiling
stays two builds in total, one per platform, and zero have been used.

The approved proposal asked for exactly `psycopg[binary]==3.3.6` with matching
`psycopg-binary==3.3.6`. The upstream binary workflow at tag commit
`a67654d1e7afbf9b3a619557838f62de1c790e7c` declares libpq 18.6 and OpenSSL
3.5.8. The proposal stated that this source fact does not prove what the
published wheels contain.

## Decision

### What the approval covers

- Inspecting only the three approved, hash-bound wheels already in task scratch:
  - `psycopg-3.3.6-py3-none-any.whl`
    (`a1db9f7148b06a28606767efaca51fa6f9398c5c0a3810519be69d7000bdb631`)
  - `psycopg_binary-3.3.6-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`
    (`1679a1cb93fbe5a6d1fd58d82cbddcc6fcb8c61446ba7cae6eb2a7b19bc585de`)
  - `psycopg_binary-3.3.6-cp312-cp312-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl`
    (`37d40450659401600e6d043ff586c89a71a69f33cbb8bcdba6cdb2569beecdbe`)
- Inspecting their primary upstream sources and metadata.
- Only after a fixed, supported and licensed closure is proved for both
  architectures: moving the exact pair, its release assertions, and the
  dependent bootstrap and hash-locked metadata to 3.3.6. The existing pinned
  lock generator would run in preserve-existing mode, and every other pin,
  extra, index, hash-checking rule and platform coverage would stay unchanged.
- License-text assets only under
  `src/main/python/repomap_kg/third_party_licenses/` (`.txt` and `.json`), each
  bound to a proved component and to primary-byte provenance.
- One optional disposable library-load probe: no build, network none, no
  private mounts or data, no host installation, exact cleanup, and only under
  existing authenticated test-resource ownership.

### What the approval does not cover

- Any waiver of a new runtime finding, of a missing license or of missing
  provenance. The dependency approval is not a P3 disposition.
- A source-built wheel, `psycopg[c]`, pure-Python Psycopg with system libpq, or
  any substitute version.
- Acquiring any other wheel, source, RPM or OCI artifact. Installing scanners or
  tools. Contacting a vendor. Mutating the host.
- Application candidate builds, a ledger reset or release, the incumbent
  comparison gap, CI triggers, publication, live deployment, production pgvector
  or D15 admission.

### Preflight method and result

The three wheels matched their approved SHA-256 values before they were opened.
The producer read each one in memory. Separately, the parent wrote two
hash-verified libpq files into private scratch for static `objdump`
inspection. No package code was executed and nothing was installed. Every
`RECORD` hash matched, and there were no traversal, absolute or symlink entries.
Each binary wheel carries an auditwheel 6.7.0 CycloneDX SBOM at
`psycopg_binary-3.3.6.dist-info/sboms/auditwheel.cdx.json`. The ELF
`.gnu_debuglink` names, `KRB5_BRAND` strings and OpenSSL version strings
corroborate that SBOM. So does the pinned upstream
[`tools/ci/build_libpq.sh`](https://github.com/psycopg/psycopg/blob/a67654d1e7afbf9b3a619557838f62de1c790e7c/tools/ci/build_libpq.sh).
That script builds OpenSSL, OpenLDAP 2.6.14 and libpq from source. On CentOS
and AlmaLinux it takes Kerberos and Cyrus SASL from the distribution
(`yum install cyrus-sasl-devel krb5-devel`).

| Item | linux/amd64 wheel | linux/arm64 wheel |
| --- | --- | --- |
| libpq | static `PQlibVersion` 180006 (18.6) | static `PQlibVersion` 180006 (18.6) |
| OpenSSL used by libpq | 3.5.8, built from source | 3.5.8, built from source |
| Grafted distribution RPMs (SBOM) | CentOS 7: `krb5-libs-1.15.1-55.el7_9`, `cyrus-sasl-lib-2.1.26-24.el7_9`, `pcre-8.32-17.el7`, `libselinux-2.5-15.el7`, `keyutils-libs-1.5.8-3.el7`, `libcom_err-1.42.9-19.el7` | AlmaLinux 8: `openssl-libs-1.1.1k-17.el8_6`, `krb5-libs-1.18.2-34.el8_10`, `cyrus-sasl-lib-2.1.27-6.el8_5`, `pcre2-10.32-3.el8_6`, `libselinux-2.9-11.el8_10`, `keyutils-libs-1.5.10-9.el8`, `libcom_err-1.45.6-7.el8_10`, `libxcrypt-4.1.1-6.el8` |
| Not covered by the SBOM | `libcrypt-bc2db45e.so.1`: GCC 10.2.1 and clang 22.1.8 objects, upstream identity unproved | none observed |
| License files shipped | psycopg-binary `LICENSE.txt` (LGPL-3.0) only | psycopg-binary `LICENSE.txt` (LGPL-3.0) only |

The arm64 Kerberos libraries depend on `libcrypto-02bae65c.so.1.1.1k`
("OpenSSL 1.1.1k FIPS 25 Mar 2021"). libpq's `NEEDED` entry for
`libgssapi_krb5` loads that library eagerly, so the process would hold two
OpenSSL generations.

Closure classification:

- **Fixed:** by static version only, bundled libpq 18.6 is outside the
  CVE-2026-6477 range. No loaded library was observed. OpenSSL 3.5.8 and every
  grafted vendor package remain unclassified.
- **Supported:** *not established.* The producer's own requests were refused
  at the network boundary. The parent then read three primary lifecycle pages
  and recorded them in retained preflight source records. They were
  not re-fetched at revise_close.
  - [CentOS Linux](https://www.centos.org/centos-linux/) 7 ended life on
    2024-06-30. So the amd64 wheel's grafted packages come from a distribution
    outside public project support. Third-party extended support is not
    evidenced.
  - [OpenSSL 1.1.1](https://openssl-corporation.org/blog/2023-09-11-eol-111.html)
    public upstream support ended on 2023-09-11. The page warns that OS-vendor
    support periods may differ.
  - [AlmaLinux 8](https://wiki.almalinux.org/release-notes/) security support
    runs to 2029-05-31. Whether the unchanged `openssl-libs-1.1.1k-17.el8_6`
    build is still current in 8.10, and which vendor fixes it carries, remains
    unresolved.

  Nothing in the bytes or the SBOM shows that those exact releases carry every
  applicable vendor fix.
- **Licensed:** *not established.* The wheels ship only Psycopg's LGPL text.
  They ship no notice for OpenSSL, OpenLDAP, MIT Kerberos, Cyrus SASL,
  PCRE/PCRE2, libselinux, keyutils, libxcrypt or e2fsprogs `com_err`. The RPM
  license files are not in the wheels, and acquiring them is not authorized.
- **Loaded:** the optional probe was not run. It could not change any of the
  failures above. It would also need new Docker-capable test code outside the
  one-owner scope, and amd64 base variants that the sandbox does not hold.

The decision is therefore to keep 3.2.12/170006. No license asset was added,
because no component closure was proved.

### Recommended bounded next choice

The operator must choose. In recommended order:

1. **Retain the hold (recommended default).** Keep the checkpoint and
   evidence. No candidate build proceeds. This does not make 3.2.12 safe.
2. **Authorize a separate system-linked dependency class (recommended if D12-A
   must proceed).** Psycopg 3.3.6's C implementation would link to the runtime
   image's distribution libpq instead of grafted wheel libraries. Upstream
   [installation guidance](https://www.psycopg.org/psycopg3/docs/basic/install.html)
   prefers this implementation for production. It requires a compiler and matching
   Python/libpq headers while building; those tools need not ship in the runtime.
   Pure-Python Psycopg is an alternative that avoids compiling the extension,
   but upstream describes it as substantially slower. RepoMap has not measured
   either variant. Libpq ownership,
   advisories and licenses would then move into the Debian/PGDG package set that
   the D12 inventory already reconciles through `dpkg`. This changes packaging
   and ABI ownership. It needs its own ADR, artifact and advisory proof, the
   observed system libpq version, and functional tests. It is not authorized
   here.
3. **Continue the existing binary preflight if useful evidence becomes
   available.** Read-only primary errata, lifecycle and plaintext license facts
   are already authorized; a provider's network refusal does not create a new
   operator approval requirement. Any additional package archive, image or
   dependency class still requires authority. A load probe cannot repair an
   unsupported or unattributed component. Any eventual P3 risk acceptance
   could not be described as fixed or vendor-supported.

## Scope and non-scope

In scope: this ADR, the read-only wheel and source inspection, retained scratch
evidence, and truthful status and roadmap records. Out of scope: every pin,
lock, bootstrap, release-assertion or license-asset change, and everything in
"What the approval does not cover".

## What would prove this wrong

- Primary vendor evidence shows that every SBOM-named release is fully patched
  and vendor-supported for its loaded use, and that complete license texts are
  available under the project's distribution obligations. The blocked decision
  would then be overly conservative.
- An actual load probe shows that the 1.1.1k library is never mapped. That
  would narrow, but not remove, the support and license findings.
- A published 3.3.6 wheel differs from the inspected bytes. The approved hashes
  bind identity, so any difference is a stop, not a correction.

## Consequences

- The CVE-2026-6477 and CVE-2025-12818 findings against bundled libpq 17.6
  remain open under the P3 hold. The canonical ledger stays at
  `maximum_total: 0`.
- The D12-A source and test-policy corrections proceed independently. They are
  recorded in the D12 native qualification companion note, including the dispositions of the phase's one
  independent work review.
- linux/amd64 is **not executable** under the current authority. The fresh
  inner sandbox daemon acquires its prerequisites with a plain native
  `docker pull`, so amd64 base variants are never local. The owner refuses
  missing bases only after host admission has consumed the platform's single
  reservation. Reserving or consuming amd64 would therefore spend its only
  attempt without a build. Qualifying amd64 needs a separately authorized
  base-acquisition route or a pre-check that consumes nothing.
- A ledger that carries a non-null `parent_admission_state` refuses reservation and
  consumption, even at the approved bounds. Only the parent's written release
  removes the hold.
- The staging report schema identifier stays `repomap-staging-obligations-v1`,
  but `partition.optional` is now required. Older v1 reports, CI62 among them,
  validate only with the validator at their own commit. A version change needs
  a decision on `docs/contrib/staging-obligations-acceptance.md`, which is
  outside this phase's write scope.
- The wheel artifacts remain separate working inputs in task scratch and are
  never committed.

## Rejected alternatives

- **Moving the pin on the strength of the libpq version alone.** That ignores
  the grafted libraries and missing notices.
- **Inferring vendor backports, support or licenses from version strings, file
  names or the upstream workflow.** This is explicitly prohibited.
- **Substituting another version or packaging class within this approval.**
  This is outside the approved scope.
