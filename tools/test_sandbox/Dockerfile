FROM docker.io/library/golang:1.25.10-bookworm@sha256:154bd7001b6eb339e88c964442c0ad6ed5e53f09844cc818a41ce4ecb3ce3b43 AS go-toolchain

RUN GOBIN=/opt/repomap/bin go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.6.2 \
    && go clean -cache -modcache

FROM docker.io/library/docker:29.4.0-dind@sha256:a6dd5322747a95cd8e3207bd8d415a8fd20ec34e9c00f06dc019cbd912013489 AS docker-runtime

FROM docker.io/library/python:3.13.12-slim@sha256:f1927c75e81efd1e091dbd64b6c0ecaa5630b38635a3d1c04034ac636e1f94c8

ARG REPOMAP_SANDBOX_RECIPE

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bash \
        ca-certificates \
        gcc \
        git \
        iproute2 \
        iptables \
        libc6-dev \
        postgresql-17 \
        postgresql-client-17 \
        procps \
        util-linux \
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
        "psycopg[binary]==3.2.12" \
        "pytest==9.1.1" \
        "pytest-xdist==3.8.0" \
        "ruff==0.16.2" \
        "setuptools==83.0.0" \
        "typing-extensions==4.16.0" \
        "wheel==0.48.0"

LABEL org.repomap.test.sandbox.image="true" \
      org.repomap.test.sandbox.recipe="${REPOMAP_SANDBOX_RECIPE}" \
      org.repomap.test.sandbox.backend="monolithic-dind-v1"
