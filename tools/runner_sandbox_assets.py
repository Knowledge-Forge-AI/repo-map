"""Managed sandbox image, recipe, and volume accounting for pgvector test profiles."""

from __future__ import annotations

import hashlib
import subprocess
from typing import Callable, Mapping
import uuid

from test_sandbox_contract import (
    IMAGE_OWNER_LABEL,
    IMAGE_RECIPE_LABEL,
    TEST_POSTGRES_IMAGE,
)
from runner_pgvector_profile import (
    EXPECTED_ARCHIVE_SHA256,
    EXPECTED_COMMIT,
    EXPECTED_VERSION,
    PGVECTOR_PROFILE,
)

PGVECTOR_SANDBOX_TAG = f"repomap-test-postgres:16-pgvector{EXPECTED_VERSION.replace('.', '')}-v1"
PGVECTOR_PROFILE_LABEL = "org.repomap.test.profile"


def generate_pgvector_recipe_definition(*, base_image: str = TEST_POSTGRES_IMAGE) -> str:
    """Return the canonical materialization recipe for the disposable pgvector test image."""
    return f"""# RepoMap pgvector disposable test container recipe
# Pinned PostgreSQL base: {base_image}
# Upstream pgvector version: {EXPECTED_VERSION}
# Upstream verified commit: {EXPECTED_COMMIT}
# Upstream archive sha256: {EXPECTED_ARCHIVE_SHA256}
FROM {base_image}
# Compile container: tmpfs /tmp:rw,exec and /var/lib/postgresql/data:rw
# Verified binary archive streamed with exec -i dd into the mounted /tmp
# Destination SHA-256 and byte count checked before extraction
ARG PGVECTOR_VERSION={EXPECTED_VERSION}
ARG PGVECTOR_COMMIT={EXPECTED_COMMIT}
ARG PGVECTOR_ARCHIVE_SHA256={EXPECTED_ARCHIVE_SHA256}
LABEL {IMAGE_OWNER_LABEL}="true" \\
      {PGVECTOR_PROFILE_LABEL}="{PGVECTOR_PROFILE}"
RUN apk add --no-cache --virtual .build-deps build-base \\
    && /usr/local/bin/pg_config --version \\
    && postgres --version \\
    && cd /tmp \\
    && tar -xzf pgvector.tar.gz \\
    && make -C /tmp/pgvector-${{PGVECTOR_VERSION}} PG_CONFIG=/usr/local/bin/pg_config with_llvm=no OPTFLAGS= clean \\
    && make -C /tmp/pgvector-${{PGVECTOR_VERSION}} PG_CONFIG=/usr/local/bin/pg_config with_llvm=no OPTFLAGS= \\
    && make -C /tmp/pgvector-${{PGVECTOR_VERSION}} PG_CONFIG=/usr/local/bin/pg_config with_llvm=no OPTFLAGS= install \\
    && rm -rf /tmp/pgvector* \\
    && apk del .build-deps \\
    && rm -rf /var/cache/apk/*
# Verify exact installed control/SQL files; standalone ldd is not an acceptance gate
# Commit once, restore PostgreSQL command, remove exact setup container with volumes
# Final image: postgres OS user, network none, disposable tmpfs cluster and local socket
# Bounded readiness; psql -X -v ON_ERROR_STOP=1: LOAD '$libdir/vector', CREATE EXTENSION
# Require PostgreSQL major 16, extension 0.8.7, self/orthogonal cosine distances 0/1
# Capture server logs and verify exact runtime removal before image publication
# Runtime SQL SHA-256: {hashlib.sha256(RUNTIME_SMOKE_SQL.encode()).hexdigest()}
# Startup/readiness SHA-256: {hashlib.sha256((_RUNTIME_START + _RUNTIME_READY).encode()).hexdigest()}
CMD ["postgres"]
"""


def compute_recipe_hash(recipe_definition: str | None = None) -> str:
    """Compute deterministic SHA-256 hash of the recipe definition."""
    content = recipe_definition or generate_pgvector_recipe_definition()
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def pgvector_sandbox_labels(
    *,
    recipe_hash: str | None = None,
    run_id: str | None = None,
) -> dict[str, str]:
    """Produce labels for pgvector container, image, and volume materialization."""
    effective_recipe = recipe_hash or compute_recipe_hash()
    labels = {
        "org.repomap.test": "true",
        "org.repomap.component": "postgres",
        PGVECTOR_PROFILE_LABEL: PGVECTOR_PROFILE,
        IMAGE_OWNER_LABEL: "true",
        IMAGE_RECIPE_LABEL: effective_recipe,
    }
    if run_id:
        labels["org.repomap.test.run_id"] = run_id
    return labels


def verify_pgvector_asset_ownership(labels: object) -> bool:
    """Verify that a Docker asset possesses valid RepoMap pgvector ownership labels."""
    if not isinstance(labels, Mapping):
        return False
    if labels.get(IMAGE_OWNER_LABEL) != "true":
        return False
    if labels.get(PGVECTOR_PROFILE_LABEL) != PGVECTOR_PROFILE:
        return False
    recipe = labels.get(IMAGE_RECIPE_LABEL)
    if not recipe or len(recipe) != 64:
        return False
    return True


RUNTIME_SMOKE_SQL = """LOAD '$libdir/vector';
CREATE EXTENSION vector;
SELECT current_setting('server_version_num')::int / 10000, extversion,
       '[1,0]'::vector <=> '[1,0]'::vector,
       '[1,0]'::vector <=> '[0,1]'::vector
FROM pg_extension WHERE extname = 'vector';"""

_RUNTIME_START = """set -eu
initdb -D /var/lib/postgresql/data/pgdata -A trust -U postgres --no-instructions
exec postgres -D /var/lib/postgresql/data/pgdata -c listen_addresses= -c unix_socket_directories=/tmp
"""
_RUNTIME_READY = """set -eu
attempt=0
until pg_isready -q -h /tmp -U postgres -d postgres -t 1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo 'PostgreSQL readiness deadline exceeded' >&2
        exit 124
    fi
    sleep 1
done
"""


def remove_pgvector_container(
    execute: Callable[..., subprocess.CompletedProcess[str]], event: Callable[..., None],
    container: str, stage: str,
) -> None:
    removal = execute(stage, ["docker", "rm", "-f", "-v", container], check=False, timeout=20)
    inspection = execute(stage, ["docker", "ps", "-a", "--filter",
                                f"name=^{container}$", "--format", "{{.ID}}"], check=False, timeout=10)
    absent_on_create_failure = "no such container" in removal.stderr.lower()
    if (inspection.returncode or inspection.stdout.strip()
            or (removal.returncode and not absent_on_create_failure)):
        raise RuntimeError("pgvector setup container cleanup was not proven")
    event(stage, "completed", removed=True, verified=True)


def validate_pgvector_runtime(
    execute: Callable[..., subprocess.CompletedProcess[str]], event: Callable[..., None],
    image_id: str,
) -> dict[str, object]:
    """Prove backend loading in the final image, then reap its disposable cluster."""
    container = f"repomap-pgvector-runtime-{uuid.uuid4().hex}"
    primary: BaseException | None = None
    try:
        # Override the image entrypoint so initdb and the foreground server both
        # run as postgres. No host mounts, TCP listeners, credentials or layers.
        execute("runtime_create", [
            "docker", "create", "--pull=never", "--name", container, "--label",
            "org.repomap.test.profile=pgvector", "--network", "none", "--user", "postgres",
            "--entrypoint", "/bin/sh", "--tmpfs", "/tmp:rw,exec,mode=1777",
            "--tmpfs", "/var/lib/postgresql/data:rw,mode=1777", image_id,
            "-c", _RUNTIME_START,
        ], timeout=30)
        execute("runtime_start", ["docker", "start", container], timeout=30)
        execute("runtime_readiness", ["docker", "exec", "--user", "postgres", container,
                                      "/bin/sh", "-c", _RUNTIME_READY], timeout=45)
        output = execute("runtime_smoke", [
            "docker", "exec", "--user", "postgres", container, "psql", "-X", "-qAt",
            "-v", "ON_ERROR_STOP=1", "-h", "/tmp", "-U", "postgres", "-d", "postgres",
            "-c", RUNTIME_SMOKE_SQL,
        ], timeout=30).stdout.strip()
        if output != f"16|{EXPECTED_VERSION}|0|1":
            raise RuntimeError("pgvector runtime smoke output mismatch: " + output[:4096])
        event("runtime_smoke", "completed", server_loaded=True, smoke_passed=True,
              resulting_engine_id=image_id, postgres_abi="16", pgvector_version=EXPECTED_VERSION,
              self_cosine_distance=0, orthogonal_cosine_distance=1)
    except BaseException as error:
        primary = error
        event("runtime_smoke", "failed", error_type=type(error).__name__, terminal=True)
        raise
    finally:
        cleanup_errors: list[BaseException] = []
        for action in (
            lambda: execute("runtime_server_diagnostics", ["docker", "logs", container], timeout=10),
            lambda: remove_pgvector_container(execute, event, container, "runtime_cleanup"),
        ):
            try:
                action()
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
                event("runtime_cleanup", "failed", error_type=type(cleanup_error).__name__, verified=False)
        if cleanup_errors:
            if primary is None:
                raise cleanup_errors[0]
            primary.add_note("pgvector runtime diagnostics/cleanup also failed; see setup diagnostics")
    return {"server_loaded": True, "smoke_passed": True,
            "runtime_cleanup": {"removed": True, "verified": True}}


__all__ = (
    "PGVECTOR_PROFILE_LABEL",
    "PGVECTOR_SANDBOX_TAG",
    "compute_recipe_hash",
    "generate_pgvector_recipe_definition",
    "pgvector_sandbox_labels",
    "verify_pgvector_asset_ownership",
)
