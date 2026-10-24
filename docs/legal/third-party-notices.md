# Third-Party Notices

This document records third-party dependency notices for RepoMap. It is not legal advice.

## Psycopg

- Package names: `psycopg` and `psycopg-c`
- Selected package form: `psycopg[c]==3.3.6`, the pure Python wheel plus the
  C extension compiled from the source archive
  `psycopg_c-3.3.6.tar.gz` (SHA-256
  `29c568426ad61c1b702c7d73505c43ca2c9fc5d97a8431d8d9049e731e319ff8`),
  tag commit `a67654d1e7afbf9b3a619557838f62de1c790e7c`
  ([ADR 0089](../adr/2026/10/0089-d12-dynamic-psycopg-and-system-libpq.md))
- License expression: `LGPL-3.0-only` (both distributions)
- Upstream URL: <https://github.com/psycopg/psycopg>
- License URL (tag commit):
  <https://github.com/psycopg/psycopg/blob/a67654d1e7afbf9b3a619557838f62de1c790e7c/psycopg_c/LICENSE.txt>
- Package license assets: `src/main/python/repomap_kg/third_party_licenses/`
  (`psycopg-LICENSE.txt`, `GPL-3.0.txt`, `psycopg-c-numutils-PostgreSQL.txt`,
  `psycopg-source.json`). The wheel ships them as `repomap_kg` package data;
  the release recipe also installs them under `/usr/share/doc/repomap-kg/psycopg/`
  with the inspected source archive at
  `/usr/share/doc/repomap-kg/psycopg/source/psycopg_c-3.3.6.tar.gz`

RepoMap uses Psycopg as an unmodified third-party dependency. RepoMap does not modify Psycopg.
Psycopg is a supported optional dependency of the PostgreSQL Server Engine,
declared by the `postgres` extra (`repomap-kg[postgres]`). The base SQLite
Local distribution does not install it. The generated Server image always
installs the extra.

The C extension is dynamically linked to the system `libpq.so.5`; no libpq is
bundled or statically linked. libpq is distributed under the PostgreSQL
License; in the release image it is the PostgreSQL base's Debian `libpq5`
package, whose exact version, file hash and copyright file are frozen by the
ADR 0089 platform preflight and recorded per image by the D12 inventory.
`psycopg_c/types/numutils.c` is hand-written Psycopg code that carries
"Portions Copyright (c) 1996-2020, PostgreSQL Global Development Group" and
"Portions Copyright (c) 1994, Regents of the University of California"; the
compiled extension therefore includes PostgreSQL-derived code. That notice and
the PostgreSQL License text, verbatim from
<https://github.com/postgres/postgres/blob/REL_13_0/COPYRIGHT> (the matching
year range), are retained in `psycopg-c-numutils-PostgreSQL.txt`.
The LGPL text is Psycopg's tagged `LICENSE.txt`, byte-equal to Debian's
`/usr/share/common-licenses/LGPL-3`. The GPL-3.0 text is Debian's
`/usr/share/common-licenses/GPL-3` from `base-files 12.4+deb12u15`, read from
the earlier `golang:1.25-bookworm` source image recorded in
`psycopg-source.json`; the plaintext fetch from gnu.org was refused by the
producing environment's network policy, so no byte comparison with it exists.
For technical conveyance evidence, an image carries these license texts, the
exact source archive its extension was built from, the build instructions in
`psycopg-source.json`, and the extension as separately replaceable modules that
link `libpq.so.5` dynamically. Dynamic linking does not by itself settle any
obligation, and this document makes no legal conclusion about LGPL-3.0
section 4 or GPL-3.0 section 6.

The current release recipe pins the official PostgreSQL 16.15 Trixie image
for its `psql`, `pg_dump`, and `pg_restore` clients and system libpq, under
ADR 0091. The source image identity is
`postgres:16.15-trixie@sha256:9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97`.
This is a configured source identity; D12 image acceptance remains pending.
Earlier releases used PostgreSQL 16.14 and `psycopg[binary]==3.2.12`, which
bundled libpq 17.6. Notices and licenses present in a built image are recorded
per platform by that image's D12 inventory, not inferred from this document.

## Build tools: setuptools, wheel and packaging

`tools/ci/psycopg_build.lock` hash-locks the complete build-tool closure for
psycopg-c: `setuptools==83.0.0` (below), `wheel==0.48.0` (`MIT`,
<https://github.com/pypa/wheel>) and `packaging==26.3`
(`Apache-2.0 OR BSD-2-Clause`, <https://github.com/pypa/packaging>), the one
requirement wheel 0.48.0 declares (`packaging>=24.0`). packaging 26.3 is the
version and hash pair the repository's tooling lock already selected. All
three are build-time only: the release recipe runs `pip check` with them
installed, then removes them before the final image.

## typing-extensions

- Package name: `typing-extensions`
- Selected version: `4.16.0`
- License expression: `PSF-2.0`
- Upstream URL: <https://github.com/python/typing_extensions>
- License URL: <https://github.com/python/typing_extensions/blob/main/LICENSE>

RepoMap pins this unmodified package as its only base dependency. No packaged
RepoMap module imports it. It is also Psycopg's runtime requirement, so the pin
keeps the Server image's dependency closure reproducible.

## setuptools

- Package name: `setuptools`
- Selected version: `83.0.0`
- License expression: `MIT`
- Upstream URL: <https://github.com/pypa/setuptools>
- License URL: <https://github.com/pypa/setuptools/blob/main/LICENSE>

Setuptools is used only as RepoMap's pinned Python distribution build backend.

## Go runtime and standard library

- Packaged version: `1.26.10` (configured; no image built with it yet)
- License expression: `BSD-3-Clause`
- Upstream URL: <https://go.dev/>
- License URL: <https://go.dev/LICENSE>
- Image license path: `/usr/share/doc/repomap-kg/go/LICENSE`
- Image patent grant path: `/usr/share/doc/repomap-kg/go/PATENTS`

The Linux release helper statically includes the unmodified Go runtime and
standard library. The release image retains the Go distribution license text
and its additional patent grant without retaining the Go compiler or source
tree. Their presence in a built image is not yet observed.

## Python runtime and standard library

- Packaged version: `3.12.15` (configured; D12 image acceptance pending)
- License expression: `PSF-2.0`
- Upstream URL: <https://www.python.org/>
- License URL: <https://docs.python.org/3/license.html>
- Image license path: `/usr/local/lib/python3.12/LICENSE.txt`

The release image retains the Python runtime and standard-library license text.
Pip, setuptools, and the bundled `ensurepip` wheels are removed after the
RepoMap distribution is installed.
