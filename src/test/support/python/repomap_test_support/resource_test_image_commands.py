"""Command, script, and output contracts for test image materialization."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from repomap_test_support.resource_test_image_base import TestImageError
from repomap_test_support.resource_test_image_types import MaterializationClaim

if TYPE_CHECKING:
    from docker import DockerClient
    from docker.models.containers import Container

_SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_LABEL_VALUE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_MATERIALIZATION_OWNER_PREFIX = "runtime-image-materializer:"
_DEFAULT_BRIDGE_OPTION = "com.docker.network.bridge.default_bridge"
MATERIALIZATION_NETWORK_MODE = "bridge"
MATERIALIZATION_NETWORK_POLICY = "dependency-acquisition-built-in-bridge-v1"
# ADR 0089 D5/D6: the checkout's hash locks are the only Python install inputs.
_CHECKOUT_ROOT = Path(__file__).resolve().parents[5]
BUILD_LOCK = "tools/ci/psycopg_build.lock"
PROJECT_LOCK = "tools/ci/project_dependencies.lock"
APT_PREREQUISITES = "tools/native_apt_prerequisites.py"  # the canonical module, never its CLI wrapper
NATIVE_BUILD_PACKAGES = ("gcc", "libc6-dev", "libpq-dev")
# Diagnostic test-runtime cache, never release reproducibility evidence. The
# exact fingerprinted helper text runs in-process: it resolves the native
# transaction, refuses any change to an installed package, binds and verifies
# every archive against trusted indexes and freezes them before installing.
# Only on the Python 3.12 Trixie base's exact libssl3t64 state does a
# transaction-only preference keep libssl-dev at that version from the
# configured live origins (ADR 0091); every other header state refuses before
# any preference or install, and a superseding upload is an expected refusal.
_INSTALL_AND_PROBE = """\
import hashlib, importlib, importlib.metadata as md, importlib.util, json, os, re, subprocess, sys
dependencies, locks, version, native, build_tools, helper_source, helper_sha256 = json.loads(sys.argv[1])
assert hashlib.sha256(helper_source.encode("utf-8")).hexdigest() == helper_sha256, "prerequisite helper differs"
apt_helper = {"__name__": "repomap_apt_prerequisites"}
exec(compile(helper_source, "apt_prerequisites.py", "exec"), apt_helper)
apt = dict(os.environ, **apt_helper["APT_ENVIRONMENT"])
def packages(rows=None):
    rows = apt_helper["installed_packages"](subprocess.run) if rows is None else rows
    return {key: row for key, row in rows.items() if row["status"] == "ii"}
def changes(before, after):
    changed = {key: [row["version"], after.get(key, {}).get("version")] for key, row in sorted(before.items())
               if after.get(key, {}).get("version") != row["version"]}
    assert not changed, f"existing packages changed {changed} or were removed"
    return [f"{key}={after[key]['version']}" for key in sorted(set(after) - set(before))]
def version_of(rows, name):
    return next(row["version"] for row in rows.values() if row["name"] == name)
LIBSSL, LIBSSL_DEV, LIBSSL_VERSION = "libssl3t64", "libssl-dev", "3.5.7-1~deb13u3"
HEADER_PIN = "/etc/apt/preferences.d/repomap-libssl-dev-header.pref"
def header_pin(rows, architecture, path):  # ADR 0091: every row of both names, before any preference or install
    state = {name: sorted((row["status"], row["architecture"], row["version"]) for row in rows.values()
                          if row["name"] == name) for name in (LIBSSL, LIBSSL_DEV)}
    if state != {LIBSSL: [("ii", architecture, LIBSSL_VERSION)], LIBSSL_DEV: []}:
        raise RuntimeError(f"header state refused before any preference or install: need one ii {architecture} "
                           f"{LIBSSL}={LIBSSL_VERSION} and no {LIBSSL_DEV} row; rows {state}")
    with open(path, "x", encoding="utf-8") as stream:  # an existing file refuses before any install
        stream.write(f"Package: {LIBSSL_DEV}\\nPin: version {LIBSSL_VERSION}\\nPin-Priority: 999\\n")
    return path
rows = apt_helper["installed_packages"](subprocess.run)
before = packages(rows)
architecture = apt_helper["command_output"](subprocess.run, ["dpkg", "--print-architecture"]).strip()
pinned = header_pin(rows, architecture, HEADER_PIN)
python_before = {d.metadata["Name"].lower() for d in md.distributions()}
custody = apt_helper["install_prerequisites"](subprocess.run, [*native, "libpq5"], "/tmp/repomap-apt-prerequisites")
os.remove(pinned)  # only after the helper's verified install succeeds; a refusal keeps it for diagnosis
# Records are flushed whole before any later child writes to the same stdout.
print("REPOMAP_APT_PREREQUISITES=" + json.dumps(custody, sort_keys=True, separators=(",", ":")), flush=True)
libpq = apt_helper["attest_libpq"](subprocess.run)
built = packages()
build_added = changes(before, built)
for name, text in sorted(locks.items()):
    with open(f"/tmp/{name}", "w", encoding="utf-8") as stream:
        stream.write(text)
pip = [sys.executable, "-m", "pip", "install", "--quiet", "--no-cache-dir", "--require-hashes", "--no-deps"]
subprocess.run([*pip, "--only-binary", ":all:", "--requirement", "/tmp/build.lock"], check=True)
subprocess.run([*pip, "--no-build-isolation", "--check-build-dependencies", "--requirement", "/tmp/project.lock"],
               check=True)
subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
removable = [name for name in build_tools if name not in python_before]
subprocess.run([sys.executable, "-m", "pip", "uninstall", "--quiet", "--yes", *removable], check=True)
subprocess.run(["apt-get", "-qq", "purge", "--yes", "--auto-remove", *native], check=True, env=apt)
subprocess.run(["rm", "-rf", "/var/lib/apt/lists"], check=True)
after = packages()
added = changes(before, after)
remaining = {row["name"] for row in after.values()}
assert "libpq5" in remaining and not set(native).intersection(remaining), "compiler or headers remain"
importlib.invalidate_caches()
assert not [name for name in removable if importlib.util.find_spec(name)], "build tools remain"
os.environ.pop("PSYCOPG_IMPL", None)
import psycopg, typing_extensions
from psycopg import pq
assert psycopg.__version__ == version and pq.__impl__ == "c" and pq.version() == pq.__build_version__
assert importlib.util.find_spec("psycopg_binary") is None
for spec in dependencies:
    name, pinned = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\\[[a-z,]+\\])?==(\\S+)", spec).groups()
    assert md.version(name) == pinned, spec
resolved = {name: md.version(name) for name in ("psycopg", "psycopg-c", "typing-extensions")}
resolved.update(implementation=pq.__impl__, libpq=pq.version(), libpq_build=pq.__build_version__,
                libpq5=version_of(after, "libpq5"), libpq_dev=libpq["libpq_dev"], gcc=version_of(built, "gcc"),
                pg_config=libpq["pg_config"]["version"], pg_config_executable=libpq["pg_config"],
                added_packages=added, build_added_packages=build_added, changed_packages={},
                owners=libpq["owners"], apt_manifest_sha256=custody["manifest_sha256"],
                has_cancel_safe=psycopg.capabilities.has_cancel_safe())
print("REPOMAP_DEPENDENCY_VERSIONS=" + json.dumps(resolved, sort_keys=True, separators=(",", ":")), flush=True)
"""


class MaterializationSources(NamedTuple):
    """Checkout inputs read once, so the fingerprinted text is the executed text."""

    build_lock: str
    project_lock: str
    apt_prerequisites: str


class _MaterializationValidationError(TestImageError):
    """Carry one closed authority or conformance predicate without daemon detail."""

    def __init__(self, message: str, predicate: str) -> None:
        self.validation_predicate = predicate
        super().__init__(message)


def exact_image_id(identity: str) -> str:
    identity = str(identity)
    if not _SHA256_ID.fullmatch(identity):
        raise TestImageError("Docker Engine image ID is not exact")
    return identity


def split_tag(tag: str) -> tuple[str, str]:
    repository, separator, tag_value = tag.rpartition(":")
    if not separator or not repository or not tag_value:
        raise TestImageError("runtime cache tag is invalid")
    return repository, tag_value


def commit_configuration(labels: Mapping[str, str]) -> dict[str, object]:
    committed_labels: dict[str, str] = {}
    for key, value in sorted(labels.items()):
        if not _LABEL_VALUE.fullmatch(key) or not _LABEL_VALUE.fullmatch(value):
            raise TestImageError("runtime image label is not commit-safe")
        committed_labels[key] = value
    return {
        "Cmd": ["python3"],
        "Entrypoint": None,
        "Labels": committed_labels,
    }


def read_materialization_sources() -> MaterializationSources:
    """Read each lock and the prerequisite helper exactly once, as UTF-8 bytes."""
    return MaterializationSources(*(
        (_CHECKOUT_ROOT / path).read_bytes().decode("utf-8")
        for path in (BUILD_LOCK, PROJECT_LOCK, APT_PREREQUISITES)
    ))


def build_lock_tools(lock_text: str) -> tuple[str, ...]:
    return tuple(sorted(re.findall(r"^([a-z0-9][a-z0-9._-]*)==", lock_text, re.MULTILINE)))


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def install_and_probe_command(
    dependencies: Sequence[str],
    psycopg_release_version: str,
    sources: MaterializationSources | None = None,
) -> list[str]:
    """Acquire native prerequisites under exact custody, then the hash-locked closure.

    psycopg-c is built from its hash-bound sdist without isolation, compiler and
    headers are purged while the system ``libpq5`` stays, and the C implementation
    is asserted before commit. ``sources`` must be the snapshot whose digests
    form the runtime fingerprint.
    """
    sources = sources or read_materialization_sources()
    payload = json.dumps(
        [tuple(dependencies),
         {"build.lock": sources.build_lock, "project.lock": sources.project_lock},
         psycopg_release_version, NATIVE_BUILD_PACKAGES, build_lock_tools(sources.build_lock),
         sources.apt_prerequisites, _digest(sources.apt_prerequisites)],
        separators=(",", ":"),
    )
    return ["-c", _INSTALL_AND_PROBE, payload]


def materialization_inputs(
    sources: MaterializationSources | None = None,
) -> dict[str, object]:
    """Every input that shapes a materialized runtime, for its cache fingerprint (ADR 0089 D6).

    A changed lock, prerequisite helper, install/probe program or native
    prerequisite set therefore selects a new cache image instead of reusing one
    built from older inputs.
    """
    sources = sources or read_materialization_sources()
    return {
        "apt_prerequisites_sha256": _digest(sources.apt_prerequisites),
        "build_lock_sha256": _digest(sources.build_lock),
        "install_and_probe_sha256": _digest(_INSTALL_AND_PROBE),
        "native_build_packages": list(NATIVE_BUILD_PACKAGES),
        "project_lock_sha256": _digest(sources.project_lock),
    }


def container_output(container: Container, *, stdout: bool) -> str:
    output: object = container.logs(stdout=stdout, stderr=not stdout)
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return str(output or "")


def exception_provenance(error: BaseException) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": type(error).__name__,
        "message": str(error),
    }
    nested = error.__cause__ or error.__context__
    if nested is not None and nested is not error:
        payload["cause"] = exception_provenance(nested)
    return payload


def require_builtin_bridge(client: DockerClient) -> str:
    try:
        network = client.networks.get("bridge")
        network.reload()
    except Exception as error:
        raise _MaterializationValidationError(
            "pre-existing built-in bridge is unavailable", "network_authority"
        ) from error
    attrs = network.attrs
    options = attrs.get("Options") or {}
    network_id = str(getattr(network, "id", "") or attrs.get("Id") or "")
    if not (
        str(attrs.get("Name") or "") == "bridge"
        and str(attrs.get("Driver") or "") == "bridge"
        and str(attrs.get("Scope") or "") == "local"
        and not bool(attrs.get("Internal", False))
        and str(options.get(_DEFAULT_BRIDGE_OPTION) or "").lower() == "true"
        and re.fullmatch(r"[0-9a-f]{64}", network_id)
    ):
        raise _MaterializationValidationError(
            "pre-existing built-in bridge identity differs", "network_authority"
        )
    return network_id


def validate_network_authority(
    client: DockerClient,
    attrs: Mapping[str, object],
    host_config: Mapping[str, object],
    claim: MaterializationClaim,
) -> None:
    raw_mode = str(host_config.get("NetworkMode") or "")
    network_settings = attrs.get("NetworkSettings")
    effective = (
        network_settings.get("Networks")
        if isinstance(network_settings, Mapping)
        else None
    )
    if not isinstance(effective, Mapping):
        raise _MaterializationValidationError(
            "materialization container network authority differs",
            "network_authority",
        )
    claimed_mode = str(claim["network_mode"])
    if claimed_mode == "none":
        if raw_mode != "none":
            raise _MaterializationValidationError(
                "materialization container network mode differs",
                "network_authority",
            )
        if set(effective).difference({"none"}):
            raise _MaterializationValidationError(
                "materialization container network authority differs",
                "network_authority",
            )
        return
    if claimed_mode != "bridge" or raw_mode not in {"bridge", "default"}:
        raise _MaterializationValidationError(
            "materialization container network mode differs",
            "network_authority",
        )
    if set(effective) != {"bridge"}:
        raise _MaterializationValidationError(
            "materialization container network authority differs",
            "network_authority",
        )
    bridge_attachment = effective.get("bridge")
    if not isinstance(bridge_attachment, Mapping):
        raise _MaterializationValidationError(
            "materialization container network authority differs",
            "network_authority",
        )
    claimed_id = str(claim.get("network_id") or "")
    if require_builtin_bridge(client) != claimed_id:
        raise _MaterializationValidationError(
            "materialization container network authority differs",
            "network_authority",
        )
    attached_id = str(bridge_attachment.get("NetworkID") or "")
    if attached_id and attached_id != claimed_id:
        raise _MaterializationValidationError(
            "materialization container network authority differs",
            "network_authority",
        )


__all__ = [
    "APT_PREREQUISITES",
    "BUILD_LOCK",
    "MATERIALIZATION_NETWORK_MODE",
    "MATERIALIZATION_NETWORK_POLICY",
    "MaterializationSources",
    "NATIVE_BUILD_PACKAGES",
    "PROJECT_LOCK",
    "_DEFAULT_BRIDGE_OPTION",
    "_LABEL_VALUE",
    "_MATERIALIZATION_OWNER_PREFIX",
    "_MaterializationValidationError",
    "_SHA256_ID",
    "commit_configuration",
    "container_output",
    "exact_image_id",
    "exception_provenance",
    "build_lock_tools",
    "install_and_probe_command",
    "materialization_inputs",
    "read_materialization_sources",
    "require_builtin_bridge",
    "split_tag",
    "validate_network_authority",
]
