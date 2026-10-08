"""Managed image and host-resource inventory for the test sandbox."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Callable

from test_sandbox_report import write_sandbox_diagnostic

from test_sandbox_contract import Captured, HostSnapshot, Runner


def _image_diagnostic(stage: str, result, category: str) -> None:
    """Emit a closed stderr projection; never emit image config or command argv."""
    stderr = result.stderr or ""
    phrases = (
        "no such image", "permission denied", "cannot connect to the docker daemon",
        "error during connect", "no space left on device", "failed to solve",
        "connection refused", "tls handshake timeout",
    )
    safe = [phrase for phrase in phrases if phrase in stderr.lower()]
    write_sandbox_diagnostic(json.dumps({
        "event": "repomap-sandbox-image-diagnostic-v1", "stage": stage,
        "category": category, "returncode": result.returncode,
        "stderr": "; ".join(safe) if safe else ("<redacted>" if stderr else ""),
        "stderr_bytes": len(stderr.encode("utf-8", errors="replace")),
        "stderr_sha256": hashlib.sha256(stderr.encode("utf-8", errors="replace")).hexdigest(),
    }, sort_keys=True))


def inspect_managed_image(
    runner: Runner,
    recipe: str,
    *,
    captured: Captured,
    image_tag: str,
    owner_label: str,
    recipe_label: str,
    exact_id: re.Pattern[str],
) -> tuple[int, str | None]:
    result = captured(
        runner,
        ["docker", "image", "inspect", image_tag, "--format", "{{json .}}"],
        timeout=30,
    )
    if result.returncode != 0:
        # Permit surrounding warnings, but require an exact missing-image line
        # for this tag. Endpoint failures always take precedence over cache state.
        missing_lines = {
            f"error response from daemon: no such image: {image_tag}".lower(),
            f"error: no such image: {image_tag}".lower(),
        }
        missing = any(line.strip().lower() in missing_lines for line in (result.stderr or "").splitlines())
        category = "cache_absent" if missing else "inspection_failed"
        if any(text in (result.stderr or "").lower() for text in (
            "cannot connect to the docker daemon", "error during connect",
            "connection refused", "permission denied", "tls handshake timeout",
        )):
            category = "endpoint_unavailable"
            missing = False
        _image_diagnostic("inspect", result, category)
        if not missing:
            raise RuntimeError(f"managed sandbox image inspection failed: {category}; exit={result.returncode}")
        return result.returncode, None
    try:
        payload = json.loads(result.stdout)
        image_id = payload["Id"]
        labels = payload["Config"]["Labels"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("managed sandbox image inspection is malformed") from error
    if not isinstance(image_id, str) or exact_id.fullmatch(image_id) is None:
        raise RuntimeError("managed sandbox image has no exact image ID")
    if not isinstance(labels, dict):
        raise RuntimeError("managed sandbox image inspection is malformed")
    if labels.get(owner_label) != "true":
        raise RuntimeError("sandbox image tag exists without exact RepoMap ownership")
    if labels.get(recipe_label) != recipe:
        _image_diagnostic("inspect", result, "cache_stale")
        return 1, None
    _image_diagnostic("inspect", result, "cache_hit")
    return 0, image_id


def ensure_sandbox_image(
    *,
    dockerfile: Path,
    runner: Runner,
    captured: Captured,
    inspect: Callable[[Runner, str], tuple[int, str | None]],
    prune: Callable[..., None],
    image_tag: str,
) -> str:
    recipe = hashlib.sha256(dockerfile.read_bytes()).hexdigest()
    status, image_id = inspect(runner, recipe)
    if status == 0 and image_id is not None:
        prune(runner, keep_image_id=image_id)
        return image_id
    build = captured(
        runner,
        [
            "docker",
            "build",
            "--tag",
            image_tag,
            "--build-arg",
            f"REPOMAP_SANDBOX_RECIPE={recipe}",
            "--pull=false",
            str(dockerfile.parent),
        ],
        timeout=1800,
    )
    _image_diagnostic("build", build, "build_failed" if build.returncode else "built")
    if build.returncode != 0:
        raise RuntimeError(f"managed integration sandbox image build failed: exit={build.returncode}")
    status, image_id = inspect(runner, recipe)
    if status != 0 or image_id is None:
        raise RuntimeError("managed integration sandbox image is absent after build")
    prune(runner, keep_image_id=image_id)
    return image_id


def prune_managed_sandbox_images(
    runner: Runner,
    *,
    keep_image_id: str,
    captured: Captured,
    ids: Callable[[Runner, list[str]], frozenset[str]],
    exact_id: re.Pattern[str],
    owner_label: str,
    retention_limit: int = 2,
) -> None:
    if exact_id.fullmatch(keep_image_id) is None or retention_limit < 1:
        raise RuntimeError("invalid managed sandbox image retention request")
    listed = captured(
        runner,
        [
            "docker",
            "image",
            "ls",
            "--filter",
            f"label={owner_label}=true",
            "--format",
            "{{.ID}}",
            "--no-trunc",
        ],
        timeout=30,
    )
    if listed.returncode != 0:
        raise RuntimeError("managed sandbox image retention inventory failed")
    images = list(dict.fromkeys(line for line in listed.stdout.splitlines() if line))
    if keep_image_id not in images:
        raise RuntimeError("current sandbox image is absent from the owned retention inventory")
    container_ids = ids(runner, ["docker", "container", "ls", "-aq"])
    referenced: frozenset[str] = frozenset()
    if container_ids:
        references = captured(
            runner,
            ["docker", "container", "inspect", *sorted(container_ids), "--format", "{{.Image}}"],
            timeout=30,
        )
        if references.returncode != 0:
            raise RuntimeError("managed sandbox image reference inventory failed")
        referenced = frozenset(references.stdout.splitlines())
    protected = {keep_image_id, *referenced}
    for candidate in reversed(images):
        if len(images) <= retention_limit:
            break
        if candidate in protected:
            continue
        labels = captured(
            runner,
            ["docker", "image", "inspect", candidate, "--format", "{{json .Config.Labels}}"],
            timeout=30,
        )
        try:
            ownership = json.loads(labels.stdout) if labels.returncode == 0 else None
        except json.JSONDecodeError as error:
            raise RuntimeError("managed sandbox retention ownership is malformed") from error
        if not isinstance(ownership, dict) or ownership.get(owner_label) != "true":
            raise RuntimeError("managed sandbox retention candidate lacks exact ownership")
        removed = captured(
            runner,
            ["docker", "image", "rm", "--no-prune", candidate],
            timeout=120,
        )
        if removed.returncode != 0:
            raise RuntimeError("owned sandbox image retention removal failed")
        absent = captured(runner, ["docker", "image", "inspect", candidate], timeout=30)
        if absent.returncode == 0:
            raise RuntimeError("owned sandbox image remains after retention removal")
        images.remove(candidate)
    if len(images) > retention_limit:
        raise RuntimeError("managed sandbox image retention is blocked by active references")


def ids(runner: Runner, command: list[str], *, captured: Captured) -> frozenset[str]:
    result = captured(runner, command, timeout=30)
    if result.returncode != 0:
        raise RuntimeError("host Docker identity snapshot failed")
    return frozenset(line for line in result.stdout.splitlines() if line)


def snapshot_host_resources(
    runner: Runner,
    *,
    ids: Callable[[Runner, list[str]], frozenset[str]],
) -> HostSnapshot:
    return HostSnapshot(
        containers=ids(runner, ["docker", "container", "ls", "-aq"]),
        images=ids(runner, ["docker", "image", "ls", "-q", "--no-trunc"]),
        volumes=ids(runner, ["docker", "volume", "ls", "-q"]),
        networks=ids(runner, ["docker", "network", "ls", "-q", "--no-trunc"]),
    )


def _resource_diagnostic(kind: str, identity: str, inspect_resource) -> dict[str, object]:
    """Identify residue without exposing private names, labels or Docker config."""
    record: dict[str, object] = {
        "kind": kind, "identity_sha256": hashlib.sha256(identity.encode()).hexdigest(),
        "engine_id": identity if re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", identity) else None,
        "inspection": "unavailable", "ownership": "unknown", "owner_label_sha256": {},
    }
    if inspect_resource is None:
        return record
    try:
        result = inspect_resource(kind, identity)
        record["returncode"] = result.returncode
        if result.returncode != 0:
            return record
        if len(result.stdout) > 16384:
            record["inspection"] = "oversized"
            return record
        labels = json.loads(result.stdout)
        if labels is None:
            labels = {}
        if not isinstance(labels, dict):
            record["inspection"] = "malformed"
            return record
        # These commitments permit exact local attribution/readback while no
        # arbitrary label keys, paths, credentials or project names escape.
        owner_keys = (
            "org.repomap.test.sandbox.image", "org.repomap.test.run-id",
            "org.repomap.test.resource.run_id", "org.repomap.test.resource.owner",
            "com.docker.compose.project",
            "com.docker.compose.volume", "com.docker.compose.service",
        )
        record["owner_label_sha256"] = {
            key: hashlib.sha256(str(labels[key]).encode()).hexdigest()
            for key in owner_keys if key in labels
        }
        record["inspection"] = "inspected"
        record["ownership"] = (
            "repomap_metadata" if any(key.startswith("org.repomap.") for key in labels)
            else "unattributed"
        )
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        record["inspection"] = type(error).__name__
    return record


def verify_host_snapshot(
    before: HostSnapshot, after: HostSnapshot, *, inspect_resource=None,
) -> None:
    residue = {
        "containers": after.containers - before.containers,
        "images": after.images - before.images,
        "volumes": after.volumes - before.volumes,
        "networks": after.networks - before.networks,
    }
    counts = {kind: len(identities) for kind, identities in residue.items() if identities}
    if counts:
        remaining = 16
        for kind, identities in sorted(residue.items()):
            for identity in sorted(identities)[:remaining]:
                write_sandbox_diagnostic(json.dumps({
                    "event": "repomap-sandbox-residue-resource-v1",
                    **_resource_diagnostic(kind, identity, inspect_resource),
                }, sort_keys=True))
                remaining -= 1
        write_sandbox_diagnostic(json.dumps({
            "event": "repomap-sandbox-residue-summary-v1", "counts": counts,
            "omitted": sum(counts.values()) - (16 - remaining), "decision": "failed",
        }, sort_keys=True))
        detail = ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))
        raise RuntimeError(f"unexpected host Docker residue after sandbox cleanup: {detail}")
