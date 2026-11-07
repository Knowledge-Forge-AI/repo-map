"""Pure server recipe rendering, independent of runtime configuration or storage."""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable, Mapping
from common_lore_index.runtime.release import (
    DYNAMIC_PACKAGE_MANIFEST,
    GO_RELEASE_IMAGE,
    GO_RELEASE_VERSION,
    PACKAGED_PG_DUMP,
    PACKAGED_PG_RESTORE,
    PACKAGED_PSQL,
    POSTGRES_RELEASE_IMAGE,
    POSTGRES_RELEASE_VERSION,
    PSYCOPG_C_GENERATED_SOURCES,
    PSYCOPG_C_SDIST_MEMBERS,
    PSYCOPG_C_SDIST_SHA256,
    PSYCOPG_C_SDIST_SIZE,
    PSYCOPG_C_SDIST_URL,
    PSYCOPG_LIBPQ_VERSION,
    PSYCOPG_RELEASE_VERSION,
    PRODUCT_MINIMUM_LIBPQ_VERSION,
    PSYCOPG_TAG_COMMIT,
    PYTHON_RELEASE_IMAGE,
    PYTHON_RELEASE_VERSION,
    RELEASE_BUILD_LINKAGE_PY,
    RELEASE_BUILD_ONLY_MODULES,
    RELEASE_FINAL_PROBE_PY,
    RELEASE_SDIST_INSPECTION_PY,
    RELEASE_WHEEL_REQUIREMENTS,
    PlatformPackages,
    render_apt_steps,
    validate_package_manifest,
)

# ADR 0089 D4: copied and run before builder packages inventory the base payload.
PYTHON_PAYLOAD_SOURCE = "src/main/python/common_lore_index/runtime/python_payload.py"


def render_server_dockerfile(
    manifest: Mapping[str, PlatformPackages] = DYNAMIC_PACKAGE_MANIFEST,
    libpq_version: int | None = PSYCOPG_LIBPQ_VERSION,
) -> str:
    """Render the one server recipe (ADR 0089 D4): C Psycopg on the base's system libpq.

    A platform absent from the frozen manifest refuses before any package fetch
    or build-backend execution; no package identity is ever guessed. The exact
    payload contract then removes only its frozen native exclusion, or refuses.
    """
    validate_package_manifest(manifest, libpq_version)
    resolved = sorted(manifest)
    first = manifest[resolved[0]] if resolved else None
    trust = "".join(
        f"COPY --from={POSTGRES_RELEASE_IMAGE} {path} {path}\n"
        for path, _digest in ((first.pgdg_source, first.pgdg_keyring) if first else ())
    )
    builder = _platform_case(manifest, lambda arch, item: render_apt_steps(arch, item, item.builder, trust_files=True))
    closure = _platform_case(manifest, lambda arch, item: render_apt_steps(arch, item, item.closure, trust_files=False))
    expect = _platform_case(manifest, lambda _arch, item: _expected_identity(item, libpq_version))
    wheels = "".join(
        f"        \"{name} {' '.join('--hash=sha256:' + digest for digest in digests)}\" \\\n"
        for name, digests in sorted(RELEASE_WHEEL_REQUIREMENTS.items())
    )
    sdist_expectation = shlex.quote(json.dumps({
        "size": PSYCOPG_C_SDIST_SIZE, "sha256": PSYCOPG_C_SDIST_SHA256, "version": PSYCOPG_RELEASE_VERSION,
        "members": dict(PSYCOPG_C_SDIST_MEMBERS), "generated": list(PSYCOPG_C_GENERATED_SOURCES),
    }, sort_keys=True, separators=(",", ":")))
    sdist = f"/tmp/repomap-build/psycopg_c-{PSYCOPG_RELEASE_VERSION}.tar.gz"
    refusal = (
        'echo "ADR 0089 D3 package manifest unresolved for ${TARGETARCH}; '
        'refusing before package or backend execution" >&2; exit 1'
    )
    admission = (
        f'case "${{TARGETARCH}}" in {"|".join(resolved)}) ;; *) {refusal} ;; esac' if resolved else refusal
    )
    libpq_label = "unresolved" if libpq_version is None else str(libpq_version)
    build_only = " ".join(RELEASE_BUILD_ONLY_MODULES)
    return f"""\
FROM {GO_RELEASE_IMAGE} AS go-helper
ARG TARGETOS
ARG TARGETARCH
WORKDIR /src/main/go
COPY src/main/go/ ./
RUN test "${{TARGETOS}}" = "linux" \\
    && case "${{TARGETARCH}}" in amd64|arm64) ;; *) exit 1 ;; esac \\
    && mkdir -p /out \\
    && CGO_ENABLED=0 GOTOOLCHAIN=local GOOS="${{TARGETOS}}" GOARCH="${{TARGETARCH}}" \\
       go build -trimpath -o /out/repomap-go-extract ./cmd/repomap-go-extract

FROM {PYTHON_RELEASE_IMAGE} AS python-runtime
ARG TARGETARCH
WORKDIR /build
RUN {admission}
COPY {PYTHON_PAYLOAD_SOURCE} /tmp/repomap-payload/python_payload.py
RUN python -I -B /tmp/repomap-payload/python_payload.py "${{TARGETARCH}}" \\
    && rm -rf /tmp/repomap-payload
{trust}RUN {builder}
RUN mkdir -m 0700 /tmp/repomap-build /tmp/repomap-build/wheels \\
    && python -I -c "import hashlib, sys, urllib.request; data = urllib.request.urlopen(sy\
s.argv[1], timeout=120).read(); assert len(data) == int(sys.argv[2]) and hashlib.sha256(da\
ta).hexdigest() == sys.argv[3]; open(sys.argv[4], 'xb').write(data)" \\
        "{PSYCOPG_C_SDIST_URL}" "{PSYCOPG_C_SDIST_SIZE}" "{PSYCOPG_C_SDIST_SHA256}" "{sdist}" \\
    && printf '%s\\n' \\
{wheels}        > /tmp/repomap-build/wheels.txt \\
    && python -m pip download --no-cache-dir --require-hashes --no-deps --only-binary :all: \\
        --dest /tmp/repomap-build/wheels --requirement /tmp/repomap-build/wheels.txt
COPY <<'REPOMAP_PY' /tmp/repomap-build/inspect_sdist.py
{RELEASE_SDIST_INSPECTION_PY}REPOMAP_PY
COPY <<'REPOMAP_PY' /tmp/repomap-build/linkage.py
{RELEASE_BUILD_LINKAGE_PY}REPOMAP_PY
COPY pyproject.toml README.md ./
COPY src/main/python ./src/main/python
COPY src/main/resources ./src/main/resources
RUN --network=none test "$(ls /sys/class/net)" = "lo" \\
    && python -I /tmp/repomap-build/inspect_sdist.py "{sdist}" {sdist_expectation} \\
    && printf '%s\\n' "psycopg-c @ file://{sdist} --hash=sha256:{PSYCOPG_C_SDIST_SHA256}" \
> /tmp/repomap-build/psycopg-c.txt \\
    && python -m pip install --no-cache-dir --no-index --require-hashes --no-deps \\
        --find-links /tmp/repomap-build/wheels --requirement /tmp/repomap-build/wheels.txt \\
    && python -m pip install --no-cache-dir --no-index --require-hashes --no-deps \\
        --no-build-isolation --check-build-dependencies --requirement /tmp/repomap-build/psycopg-c.txt \\
    && python -I /tmp/repomap-build/linkage.py > /build/psycopg-c-linkage.json \\
    && install -D -m 0444 "{sdist}" "/build/psycopg-c-source/psycopg_c-{PSYCOPG_RELEASE_VERSION}.tar.gz" \\
    && python -m pip install --no-cache-dir --no-index --no-deps --no-build-isolation ".[postgres]" \\
    && python -m pip check
RUN python -c "from pathlib import Path; from common_lore_index.storage import discover_migrations; from common_lore_index.coordinator._control_schema import discover_control_migrations; encode=lambda items: tuple((item.relative_path,item.changeset_id,item.checksum) for item in items); installed_graph=encode(discover_migrations()); source_graph=encode(discover_migrations(Path('/build/src/main/resources/rdbms'))); installed_control=encode(discover_control_migrations()); source_control=encode(discover_control_migrations(Path('/build/src/main/resources/coordinator-rdbms'))); assert installed_graph == source_graph; assert installed_control == source_control"
RUN python -m pip uninstall -y {build_only} \\
    && rm -rf /usr/local/lib/python3.12/ensurepip /usr/local/include /tmp/repomap-build \\
    && python -c "from importlib.util import find_spec; assert [m for m in {list\
(RELEASE_BUILD_ONLY_MODULES)!r} if find_spec(m)] == []"

FROM {POSTGRES_RELEASE_IMAGE} AS runtime
ARG TARGETARCH
COPY --from=python-runtime /usr/local /usr/local
RUN {closure}
RUN ldconfig
RUN rmdir /usr/local/include
COPY --from=python-runtime /build/src/main/python/common_lore_index/third_party_licenses/GPL-3.0.txt /build/src/main/python/common_lore_index/third_party_licenses/psycopg-LICENSE.txt /build/src/main/python/common_lore_index/third_party_licenses/psycopg-c-numutils-PostgreSQL.txt /build/src/main/python/common_lore_index/third_party_licenses/psycopg-source.json /usr/share/doc/repomap-kg/psycopg/
COPY --from=python-runtime /build/psycopg-c-linkage.json /usr/share/doc/repomap-kg/psycopg/linkage.json
COPY --from=python-runtime /build/psycopg-c-source/ /usr/share/doc/repomap-kg/psycopg/source/
COPY --from=go-helper /out/repomap-go-extract /tmp/repomap-go-extract
COPY --from=go-helper /usr/local/go/LICENSE /usr/share/doc/repomap-kg/go/LICENSE
COPY --from=go-helper /usr/local/go/PATENTS /usr/share/doc/repomap-kg/go/PATENTS
RUN install -d -m 0700 /repo-map-home /repo-map-home/runtime /repo-map-home/coordinator \
/repo-map-admin /repo-map-home/state \\
    && install -m 0444 /dev/null /etc/repomap-release-container \\
    && chmod 1777 /tmp
RUN package_root="$(python -c 'import pathlib, common_lore_index; print(pathlib.Path(common_lore_index.__file__).parent)')" \\
    && install -D -m 0755 /tmp/repomap-go-extract \\
       "${{package_root}}/_bin/linux-${{TARGETARCH}}/repomap-go-extract" \\
    && rm /tmp/repomap-go-extract
ENV REPOMAP_PACKAGED_PSQL={PACKAGED_PSQL} \\
    REPOMAP_PACKAGED_PG_DUMP={PACKAGED_PG_DUMP} \\
    REPOMAP_PACKAGED_PG_RESTORE={PACKAGED_PG_RESTORE}
LABEL io.repomap.release.postgresql="{POSTGRES_RELEASE_VERSION}" \\
      io.repomap.release.python="{PYTHON_RELEASE_VERSION}" \\
      io.repomap.release.go="{GO_RELEASE_VERSION}" \\
      io.repomap.release.psycopg="{PSYCOPG_RELEASE_VERSION}" \\
      io.repomap.release.psycopg.implementation="c" \\
      io.repomap.release.psycopg.source="{PSYCOPG_C_SDIST_SHA256}" \\
      io.repomap.release.psycopg.tag="{PSYCOPG_TAG_COMMIT}" \\
      io.repomap.release.libpq="{libpq_label}"
COPY <<'REPOMAP_PY' /tmp/repomap-release-probe.py
{RELEASE_FINAL_PROBE_PY}REPOMAP_PY
RUN {expect} \\
    && python -I /tmp/repomap-release-probe.py && rm /tmp/repomap-release-probe.py
RUN python -c "import psycopg; from psycopg import pq; assert psycopg.__version__ == \
'{PSYCOPG_RELEASE_VERSION}'; assert pq.__impl__ == 'c'"
RUN python -c "from common_lore_index.storage import discover_migrations; from common_lore_index.coordinator._control_schema import discover_control_migrations; assert discover_migrations(); assert discover_control_migrations()"
RUN python -c "from importlib.util import find_spec; assert find_spec('pip') is None; assert find_spec('setuptools') is None" \\
    && test ! -e /usr/local/lib/python3.12/ensurepip \\
    && test -s /usr/share/doc/repomap-kg/go/LICENSE \\
    && test -s /usr/share/doc/repomap-kg/go/PATENTS \\
    && test -s /usr/local/lib/python3.12/LICENSE.txt \\
    && test -s /usr/share/doc/repomap-kg/psycopg/psycopg-LICENSE.txt \\
    && test -s /usr/share/doc/repomap-kg/psycopg/GPL-3.0.txt \\
    && test -s /usr/share/doc/repomap-kg/psycopg/psycopg-source.json \\
    && test -s /usr/share/doc/repomap-kg/psycopg/psycopg-c-numutils-PostgreSQL.txt \\
    && test -s /usr/share/doc/repomap-kg/psycopg/source/psycopg_c-{PSYCOPG_RELEASE_VERSION}.tar.gz
RUN case "$(psql --version)" in "psql (PostgreSQL) {POSTGRES_RELEASE_VERSION}"*) ;; *) exit 1 ;; esac \\
    && case "$(pg_dump --version)" in "pg_dump (PostgreSQL) {POSTGRES_RELEASE_VERSION}"*) ;; *) exit 1 ;; esac \\
    && case "$(pg_restore --version)" in "pg_restore (PostgreSQL) {POSTGRES_RELEASE_VERSION}"*) ;; *) exit 1 ;; esac
RUN ! command -v go
ENTRYPOINT [\"python\", \"-m\", \"common_lore_index\"]
CMD [\"server\", \"serve\", \"--repo-map-home\", \"/repo-map-home\"]
"""


def _platform_case(manifest: Mapping[str, PlatformPackages],
                   render: Callable[[str, PlatformPackages], str]) -> str:
    branches = "".join(f"    {arch}) {render(arch, manifest[arch])} ;; \\\n" for arch in sorted(manifest))
    return f'case "${{TARGETARCH}}" in \\\n{branches}    *) exit 1 ;; \\\n    esac'


def _expected_identity(item: PlatformPackages, libpq_version: int | None) -> str:
    values = {
        "REPOMAP_EXPECT_LIBPQ_VERSION": str(libpq_version),
        "REPOMAP_EXPECT_LIBPQ_PATH": item.libpq_path,
        "REPOMAP_EXPECT_LIBPQ_SHA256": item.libpq_sha256,
        "REPOMAP_EXPECT_LIBPQ5_VERSION": item.libpq5_version,
        "REPOMAP_EXPECT_LIB_DYNLOAD": json.dumps(list(item.lib_dynload)),
        "REPOMAP_EXPECT_MINIMUM_LIBPQ": str(PRODUCT_MINIMUM_LIBPQ_VERSION),
        "REPOMAP_EXPECT_BUILD_ONLY_MODULES": json.dumps(list(RELEASE_BUILD_ONLY_MODULES)),
    }
    return "export " + " ".join(f"{key}={shlex.quote(value)}" for key, value in values.items())
