FROM docker.io/library/golang:1.25.10-bookworm@sha256:154bd7001b6eb339e88c964442c0ad6ed5e53f09844cc818a41ce4ecb3ce3b43 AS go-toolchain

RUN GOBIN=/opt/repomap/bin go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.6.2 \
    && go clean -cache -modcache

FROM docker.io/library/docker:29.4.0-dind@sha256:a6dd5322747a95cd8e3207bd8d415a8fd20ec34e9c00f06dc019cbd912013489 AS docker-runtime

FROM docker.io/library/python:3.13.12-slim@sha256:f1927c75e81efd1e091dbd64b6c0ecaa5630b38635a3d1c04034ac636e1f94c8

ARG REPOMAP_SANDBOX_RECIPE
ARG REPOMAP_SANDBOX_APT_HELPER_SHA256

# ADR 0089 D5/D6 preinstallation custody: the helper's digest is part of the
# recipe identity and is rechecked here. It resolves this transaction against
# the base's configured repositories plus one declared dated historical source,
# under the base's hash-checked keyring, refuses any change to an installed
# package, binds and verifies every archive's SHA-256 against a trusted index,
# freezes the manifest and only then installs those archives.
# It records current repository resolution, not release reproducibility.
# ADR 0089 archived header and Perl prerequisite corrections: the base's libc6,
# libssl3t64 and perl-base are older than the current packages that need them.
# Six exact packages are pinned to the base's dated Debian snapshot; every
# other package still prefers the current repositories. The source and pins
# serve only this transaction: removed after the helper succeeds, kept if it
# fails.
COPY apt_prerequisites.py /usr/local/lib/repomap/apt_prerequisites.py
RUN printf '%s  %s\n' "${REPOMAP_SANDBOX_APT_HELPER_SHA256}" /usr/local/lib/repomap/apt_prerequisites.py \
        | sha256sum --check --strict - \
    && printf '%s  %s\n' 506b815cbb32d9b6066b4a2aa524071e071761e7e7f68c3ac74f3061ba852017 \
        /usr/share/keyrings/debian-archive-keyring.pgp \
        | sha256sum --check --strict - \
    && set -C \
    && printf '%s\n' \
        'Types: deb' \
        'URIs: https://snapshot.debian.org/archive/debian/20260406T000000Z/' \
        'Suites: trixie' \
        'Components: main' \
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp' \
        'Check-Valid-Until: no' \
        > /etc/apt/sources.list.d/repomap-snapshot-20260406.sources \
    && printf '%s\n' \
        'Package: libc6-dev' 'Pin: version 2.41-12+deb13u2' 'Pin-Priority: 999' '' \
        'Package: libc-dev-bin' 'Pin: version 2.41-12+deb13u2' 'Pin-Priority: 999' '' \
        'Package: libssl-dev' 'Pin: version 3.5.5-1~deb13u1' 'Pin-Priority: 999' '' \
        'Package: perl' 'Pin: version 5.40.1-6' 'Pin-Priority: 999' '' \
        'Package: libperl5.40' 'Pin: version 5.40.1-6' 'Pin-Priority: 999' '' \
        'Package: perl-modules-5.40' 'Pin: version 5.40.1-6' 'Pin-Priority: 999' '' \
        'Package: *' 'Pin: origin "snapshot.debian.org"' 'Pin-Priority: 100' \
        > /etc/apt/preferences.d/repomap-snapshot-headers.pref \
    && python3 -I /usr/local/lib/repomap/apt_prerequisites.py install \
        --cache /var/cache/repomap-apt-prerequisites \
        --evidence /usr/local/share/repomap/apt-prerequisites.json \
        bash \
        ca-certificates \
        gcc \
        git \
        iproute2 \
        iptables \
        libc6-dev \
        libpq-dev \
        postgresql-17 \
        postgresql-client-17 \
        procps \
        util-linux \
    && rm /etc/apt/sources.list.d/repomap-snapshot-20260406.sources \
        /etc/apt/preferences.d/repomap-snapshot-headers.pref \
    && rm -rf /var/lib/apt/lists/*

COPY --from=go-toolchain /usr/local/go /usr/local/go
COPY --from=go-toolchain /opt/repomap/bin/golangci-lint /usr/local/bin/golangci-lint
COPY --from=docker-runtime /usr/local/bin/containerd /usr/local/bin/containerd
COPY --from=docker-runtime /usr/local/bin/containerd-shim-runc-v2 /usr/local/bin/containerd-shim-runc-v2
COPY --from=docker-runtime /usr/local/bin/ctr /usr/local/bin/ctr
COPY --from=docker-runtime /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-runtime /usr/local/bin/docker-compose /usr/local/bin/docker-compose
COPY --from=docker-runtime /usr/local/bin/docker-init /usr/local/bin/docker-init
COPY --from=docker-runtime /usr/local/bin/docker-proxy /usr/local/bin/docker-proxy
COPY --from=docker-runtime /usr/local/bin/dockerd /usr/local/bin/dockerd
COPY --from=docker-runtime /usr/local/bin/runc /usr/local/bin/runc
COPY --from=docker-runtime /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins

ENV CGO_ENABLED="1" \
    PATH="/usr/lib/postgresql/17/bin:/usr/local/go/bin:${PATH}"

RUN python3 -m pip install --no-cache-dir \
        "coverage[toml]==7.15.4" \
        "docker==7.2.0" \
        "mypy==2.1.0" \
        "psutil==7.2.2" \
        "pytest==9.1.1" \
        "pytest-xdist==3.8.0" \
        "ruff==0.16.2" \
        "typing-extensions==4.16.0"

# ADR 0089 D5/D6: these hashes equal tools/ci/psycopg_build.lock and
# tools/ci/project_dependencies.lock. packaging closes wheel's Requires-Dist.
# psycopg-c is fetched as an opaque file, then built from those exact bytes
# offline, without build isolation.
RUN printf '%s\n' \
        "packaging==26.3 --hash=sha256:94edc256424af38762eb31306eed28beb9f0efc50a8837492c9d6fd6004aed79 --hash=sha256:d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c" \
        "setuptools==83.0.0 --hash=sha256:025bccbbf0fa05b6192bc64ae1e7b16e001fd6d6d4d5de03c97b1c1ade523bef --hash=sha256:29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3" \
        "wheel==0.48.0 --hash=sha256:3217dcc807155e45db462d7ef2431f5ddda0d7273b700d05a67b271ceb1287ab --hash=sha256:94800765601e9171bf5d58d066e640662842bcedcbab982b2c90787a2c987322" \
        "psycopg==3.3.6 --hash=sha256:a1db9f7148b06a28606767efaca51fa6f9398c5c0a3810519be69d7000bdb631 --hash=sha256:c081f2250df751a943036e42db6df4571c66cd0aabe8291a7a506512b12007d2" \
        > /tmp/psycopg-wheels.txt \
    && python3 -m pip install --no-cache-dir --require-hashes --no-deps --only-binary :all: \
        --requirement /tmp/psycopg-wheels.txt \
    && rm /tmp/psycopg-wheels.txt \
    && mkdir -m 0700 /tmp/psycopg-c \
    && python3 -I -c "import hashlib, sys, urllib.request; data = urllib.request.urlopen(sys.argv[1], timeout=120).read(); assert len(data) == 698245 and hashlib.sha256(data).hexdigest() == sys.argv[2]; open(sys.argv[3], 'xb').write(data)" \
        "https://files.pythonhosted.org/packages/58/53/bf15aa48cd6f0ad0039b9f48681d2e76e8564d413af47b13fab50dd03555/psycopg_c-3.3.6.tar.gz" \
        "29c568426ad61c1b702c7d73505c43ca2c9fc5d97a8431d8d9049e731e319ff8" \
        /tmp/psycopg-c/psycopg_c-3.3.6.tar.gz

# The PATH-resolved pg_config, header and runtime must share one libpq source version.
RUN --network=none python3 -I /usr/local/lib/repomap/apt_prerequisites.py attest-libpq \
        --evidence /usr/local/share/repomap/libpq-attestation.json \
    && printf '%s\n' \
        "psycopg-c @ file:///tmp/psycopg-c/psycopg_c-3.3.6.tar.gz --hash=sha256:29c568426ad61c1b702c7d73505c43ca2c9fc5d97a8431d8d9049e731e319ff8" \
        > /tmp/psycopg-c/requirement.txt \
    && python3 -m pip install --no-cache-dir --no-index --no-deps --require-hashes \
        --no-build-isolation --check-build-dependencies \
        --requirement /tmp/psycopg-c/requirement.txt \
    && rm -r /tmp/psycopg-c \
    && env -u PSYCOPG_IMPL python3 -I -c "import importlib.metadata as m, importlib.util as u, psycopg, psycopg_c; from psycopg import pq; assert psycopg.__version__ == m.version('psycopg-c') == '3.3.6'; assert pq.__impl__ == 'c'; assert pq.version() == pq.__build_version__; assert u.find_spec('psycopg_binary') is None; print(pq.__impl__, pq.version(), psycopg_c.__file__)" \
    && python3 -I -c "import psycopg, psycopg_c._psycopg as a, psycopg_c.pq as b; print(a.__file__); print(b.__file__)" \
        > /tmp/psycopg-c-extensions.txt \
    && while read -r extension; do \
        readelf -d "${extension}" > /tmp/psycopg-c-dynamic.txt \
        && grep -qF 'Shared library: [libpq.so.5]' /tmp/psycopg-c-dynamic.txt || exit 1; \
    done < /tmp/psycopg-c-extensions.txt \
    && rm /tmp/psycopg-c-extensions.txt /tmp/psycopg-c-dynamic.txt

LABEL org.repomap.test.sandbox.image="true" \
      org.repomap.test.sandbox.recipe="${REPOMAP_SANDBOX_RECIPE}" \
      org.repomap.test.sandbox.apt-helper="${REPOMAP_SANDBOX_APT_HELPER_SHA256}" \
      org.repomap.test.sandbox.backend="monolithic-dind-v1"
