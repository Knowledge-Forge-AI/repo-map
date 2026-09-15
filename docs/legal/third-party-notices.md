# Third-Party Notices

This document records third-party dependency notices for RepoMap. It is not legal advice.

## Psycopg

- Package name: `psycopg`
- Selected package form: `psycopg[binary]==3.2.12`
- License expression: `LGPL-3.0-only`
- Upstream URL: <https://github.com/psycopg/psycopg>
- License URL: <https://github.com/psycopg/psycopg/blob/master/LICENSE.txt>

RepoMap uses Psycopg as an unmodified third-party dependency. RepoMap does not modify Psycopg.

The binary package bundles libpq 17.6. libpq is distributed under the
PostgreSQL License. The release image also uses the official PostgreSQL 16.14
Bookworm image for matching `psql`, `pg_dump`, and `pg_restore` clients.

## typing-extensions

- Package name: `typing-extensions`
- Selected version: `4.16.0`
- License expression: `PSF-2.0`
- Upstream URL: <https://github.com/python/typing_extensions>
- License URL: <https://github.com/python/typing_extensions/blob/main/LICENSE>

RepoMap pins this unmodified Psycopg runtime requirement so the release image
has a reproducible dependency closure.

## setuptools

- Package name: `setuptools`
- Selected version: `83.0.0`
- License expression: `MIT`
- Upstream URL: <https://github.com/pypa/setuptools>
- License URL: <https://github.com/pypa/setuptools/blob/main/LICENSE>

Setuptools is used only as RepoMap's pinned Python distribution build backend.

## Go runtime and standard library

- Packaged version: `1.25.12`
- License expression: `BSD-3-Clause`
- Upstream URL: <https://go.dev/>
- License URL: <https://go.dev/LICENSE>
- Image license path: `/usr/share/doc/repomap-kg/go/LICENSE`

The Linux release helper statically includes the unmodified Go runtime and
standard library. The release image retains the Go distribution license text
without retaining the Go compiler or source tree.

## Python runtime and standard library

- Packaged version: `3.12.13`
- License expression: `PSF-2.0`
- Upstream URL: <https://www.python.org/>
- License URL: <https://docs.python.org/3/license.html>
- Image license path: `/usr/local/lib/python3.12/LICENSE.txt`

The release image retains the Python runtime and standard-library license text.
Pip, setuptools, and the bundled `ensurepip` wheels are removed after the
RepoMap distribution is installed.
