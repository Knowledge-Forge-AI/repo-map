"""Rules for the one optional D12 core-image owner (ADR 0087, D12-A), separate from build-profile debt.

Host admission consumes one write-ahead budget reservation; the sandbox's in-process admission, bound
to the run-wide Docker boundary that permits one managed candidate build per run, is build authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence
import uuid

PROFILE_OPTION = "--d12-core-image-profile"
PLATFORMS = ("linux/arm64", "linux/amd64")
MARKER = "requires_d12_core_image_profile"
NODE_FILE = "src/test/int/python/repomap_kg/runtime/d12_core_image_refresh.int.test.py"
NODE_ID = f"{NODE_FILE}::test_d12_core_image_refresh_candidate_round_trip"
OPTIONAL_NODE_IDS = (NODE_ID,)
ENV_PROFILE = "REPOMAP_TEST_D12_CORE_IMAGE_PROFILE"
ENV_REPORT_DIR = "REPOMAP_TEST_D12_CORE_IMAGE_REPORT_DIR"
DESELECTION_REASON = f"optional D12 core-image owner runs only under {PROFILE_OPTION}"
CONTEXT_PATHS = ("pyproject.toml", "README.md", "src/main/python", "src/main/resources", "src/main/go")
MAX_TOTAL_BUILDS, MAX_PLATFORM_BUILDS = 2, 1
REPORT_PART_LIMIT, REPORT_TOTAL_LIMIT, REPORT_CLEANUP_RESERVE = 1_500_000, 5_000_000, 100_000
LOG_EXCERPT_BYTES = 200_000
# Raw collection, exclusion and reason recorded for runner discovery; separate from build-profile debt.
POPULATION_ATTR = "_repomap_d12_optional_population"
CANDIDATE_LABEL = "org.repomap.d12.candidate"
# Registry metadata (ADR 0091, 2026-10-23): config digests of the pinned 16.15 Trixie index; AMD unqualified.
BASE_CONFIG_DIGESTS = {"sha256:9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97": {
    "linux/arm64": "sha256:94a8e6634f916ffafee47d9be81c53d964e6ed2f5175224fab66b2abacae7279",
    "linux/amd64": "sha256:066167ff39c2a612402ce99b734ea1cff92a9d1f2ac52f697a5f0384f0d88d6b"}}
_PROFILE_ATTR, _COMPANIONS = "d12_core_image_profile", ("d12_core_image_source_sha256", "d12_core_image_budget_ledger")
# Docker reports the daemon's kernel architecture; builders advertise OS/arch platform names.
_NATIVE_PLATFORMS = {"aarch64": "linux/arm64", "arm64": "linux/arm64", "x86_64": "linux/amd64", "amd64": "linux/amd64"}
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class D12ProfileError(RuntimeError):
    """The optional D12 profile refused before any candidate Docker work."""


@dataclass(frozen=True)
class D12Admission:
    platform: str
    node_id: str
    source_sha256: str
    recipe_sha256: str
    dockerfile_sha256: str
    context_file_count: int


_ADMISSION: D12Admission | None = None


def validate_options(args: Any) -> None:
    """Refuse every runner shape except canonical scoped serial int with a frozen source."""
    platform = getattr(args, _PROFILE_ATTR, None)
    if platform is None:
        return
    if platform not in PLATFORMS:
        raise D12ProfileError(f"{PROFILE_OPTION} must be one of {', '.join(PLATFORMS)}")
    refusals = (
        (args.suite != "int", "--suite int"),
        (not getattr(args, "no_coverage", False), "--no-coverage"),
        (str(getattr(args, "jobs", "1")) != "1", "--jobs 1"),
        (getattr(args, "pg_test_profile", "core") != "core", "--pg-test-profile core"),
        (getattr(args, "pg_container_runtime", "docker") != "docker", "Docker runtime"),
        (getattr(args, "threshold", None) is not None, "no --threshold"),
        (bool(getattr(args, "report", False)), "no --report"),
        (getattr(args, "declared_complete_gates", 0) != 0, "no declared complete gates"),
        (_DIGEST.fullmatch(str(getattr(args, _COMPANIONS[0], None))) is None,
         "a frozen --d12-core-image-source-sha256"),
    )
    missing = [requirement for refused, requirement in refusals if refused]
    if missing:
        raise D12ProfileError(f"{PROFILE_OPTION} requires " + ", ".join(missing))


def validate_selection(args: Any, forwarded: Sequence[str], *, repo_root: Path,
                       environ: Mapping[str, str] | None = None) -> None:
    """Validate the exact selection; ambient environment never selects the profile."""
    env = os.environ if environ is None else environ
    if ENV_PROFILE in env or ENV_REPORT_DIR in env:
        raise D12ProfileError("ambient environment cannot select the D12 core-image profile")
    if getattr(args, _PROFILE_ATTR, None) is None:
        if any(arg.split("::", 1)[0].lstrip("./") == NODE_FILE for arg in forwarded) or any(
                getattr(args, name, None) for name in _COMPANIONS):
            raise D12ProfileError(f"the D12 core-image owner requires {PROFILE_OPTION}")
        return
    validate_options(args)
    if list(forwarded) != [NODE_ID]:
        raise D12ProfileError(f"{PROFILE_OPTION} requires exactly the one named node and no pytest options")
    report_dir = getattr(args, "report_dir", None)
    if report_dir is None or Path(report_dir).resolve() == (repo_root / ".test-reports").resolve():
        raise D12ProfileError(f"{PROFILE_OPTION} requires an explicit unused --report-dir")


def admit_profile(args: Any, forwarded: Sequence[str], *, repo_root: Path,
                  sandbox_active: Callable[[], bool]) -> D12Admission | None:
    """Validate; the host consumes one ledger entry, the sandbox records admission."""
    global _ADMISSION
    validate_selection(args, forwarded, repo_root=repo_root)
    platform = getattr(args, _PROFILE_ATTR, None)
    if platform is None:
        return None
    identity = frozen_identity(repo_root, platform)
    if identity["source_sha256"] != getattr(args, _COMPANIONS[0]):
        raise D12ProfileError("stale source: checkout differs from --d12-core-image-source-sha256")
    if not sandbox_active():
        ledger = getattr(args, _COMPANIONS[1], None)
        if ledger is None:
            raise D12ProfileError(f"{PROFILE_OPTION} requires --d12-core-image-budget-ledger on the host")
        record_budget(Path(ledger), "consume", platform, identity["source_sha256"], identity["recipe_sha256"],
                      consumer=str(Path(args.report_dir).resolve()))
        return None
    if _ADMISSION is not None:
        raise D12ProfileError("the D12 core-image profile is already admitted in this process")
    _ADMISSION = D12Admission(platform=platform, node_id=NODE_ID, **identity)
    return _ADMISSION


def current_admission() -> D12Admission:
    if _ADMISSION is None:
        raise D12ProfileError("D12 core-image owner has no runner admission in this process; direct "
                              "pytest, ambient environment and marker selection cannot authorize a build")
    return _ADMISSION


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def frozen_identity(repo_root: Path, platform: str) -> dict[str, Any]:
    names = context_files(repo_root)
    return {"source_sha256": digest_files(repo_root, names), "recipe_sha256": recipe_digest(platform),
            "dockerfile_sha256": _sha256(recipe_text().encode()), "context_file_count": len(names)}


def context_files(repo_root: Path) -> tuple[str, ...]:
    """Exact non-ignored build-context files, as the recipe's COPY paths name them."""
    command = ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--"]
    listed = subprocess.run([*command, *CONTEXT_PATHS], cwd=repo_root, capture_output=True, check=True).stdout
    return tuple(sorted(os.fsdecode(name) for name in set(listed.split(b"\0")) - {b""}))


def digest_files(root: Path, names: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for name in names:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise D12ProfileError(f"build-context entry is not a regular file: {name}")
        executable = b"x" if path.stat().st_mode & 0o111 else b"-"
        digest.update(name.encode() + b"\0" + executable + bytes.fromhex(_sha256(path.read_bytes())))
    return digest.hexdigest()


def recipe_text() -> str:
    from repomap_kg.runtime.commands import render_server_dockerfile

    return render_server_dockerfile()


def build_args(platform: str) -> dict[str, str]:
    return {"TARGETOS": "linux", "TARGETARCH": platform.split("/", 1)[1]}


def recipe_digest(platform: str) -> str:
    payload = {"dockerfile": recipe_text(), "build_args": build_args(platform), "platform": platform}
    return _sha256(json.dumps(payload, sort_keys=True).encode())


def stage_context(repo_root: Path, destination: Path, admission: D12Admission) -> Path:
    """Copy exactly the bound context, then prove neither copy drifted from admission."""
    names = context_files(repo_root)
    if digest_files(repo_root, names) != admission.source_sha256:
        raise D12ProfileError("stale source: checkout changed after D12 admission")
    if recipe_digest(admission.platform) != admission.recipe_sha256:
        raise D12ProfileError("stale recipe: rendered recipe changed after D12 admission")
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in names:
        (destination / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo_root / name, destination / name)
    if digest_files(destination, names) != admission.source_sha256:
        raise D12ProfileError("staged build context differs from the admitted source")
    return destination


def offered_platforms(buildx_inspect: str) -> list[str]:
    """OS/arch strings from ``docker buildx inspect`` ``Platforms:`` lines (``*`` marks configured)."""
    return [value.strip().rstrip("*") for line in buildx_inspect.splitlines()
            if line.strip().startswith("Platforms:") for value in line.split(":", 1)[1].split(",") if value.strip()]


def platform_availability(platform: str, daemon_architecture: str,
                          builder_platforms: Sequence[str]) -> dict[str, object]:
    """Classify an OS/arch platform as native, already-offered emulation, or blocked."""
    execution = "native" if _NATIVE_PLATFORMS.get(daemon_architecture) == platform else "emulated"
    if execution == "emulated" and platform not in builder_platforms:
        raise D12ProfileError(f"platform blocked: the existing builder does not offer {platform}")
    return {"platform": platform, "execution": execution, "builder_platforms": list(builder_platforms)}


def verify_bases(client: Any, platform: str, references: Sequence[str]) -> dict[str, dict[str, object]]:
    """Freeze every pinned base for the admitted platform before a build; never pull a variant."""
    bases: dict[str, dict[str, object]] = {}
    for reference in references:
        digest = reference.split("@", 1)[1]
        if not image_present(client, reference):
            raise D12ProfileError(f"platform blocked: {reference} is not local; no extra pull")
        attrs = client.images.get(reference).attrs
        observed, expected = f"{attrs.get('Os')}/{attrs.get('Architecture')}", BASE_CONFIG_DIGESTS.get(digest, {})
        if not any(str(value).endswith("@" + digest) for value in attrs.get("RepoDigests") or ()):
            raise D12ProfileError(f"base identity mismatch: {reference} lacks its pinned digest")
        if observed != platform:
            raise D12ProfileError(f"platform blocked: local {reference} is {observed}, not {platform}; no extra pull")
        if expected and attrs.get("Id") not in (expected[platform], digest):
            raise D12ProfileError(f"base identity mismatch: {reference} is {attrs.get('Id')}")
        bases[reference] = {"id": attrs["Id"], "platform": observed,
                            "config_digest_verified": bool(expected) and attrs["Id"] == expected[platform]}
    return bases


def locate_run_boundary() -> Any:
    """Bind the one run-wide Docker boundary owned by this process's admitted run."""
    from repomap_test_support.resource_docker_boundary import RunWideDockerBoundary
    from repomap_test_support.resource_docker_mediation import installed_authorities
    from repomap_test_support.resource_run import active_resource_run

    authorities, run = installed_authorities(), active_resource_run()
    if len(authorities) != 1 or run is None:
        raise D12ProfileError("unbound identity: no single canonical Docker authority and run")
    found = [item for item in gc.get_objects() if isinstance(item, RunWideDockerBoundary)
             and item.authority is authorities[0] and item.ledger is run.ledger]
    if len(found) != 1 or not authorities[0].installed:
        raise D12ProfileError("unbound identity: run-wide Docker boundary is not uniquely bound")
    return found[0]


def build_candidate(*, boundary: Any, admission: D12Admission, context: Path, dockerfile: Path, tag: str,
                    labels: Mapping[str, str], runner: Callable[..., Any] = subprocess.run,
                    timeout: float = 2400.0) -> tuple[str, str]:
    """Spend this run's single build; the boundary counts it on entry, so a failure is never retried."""
    if boundary.projection()["managed_system_candidate_image_build_count"]:
        raise D12ProfileError("candidate build budget for this invocation is already spent")
    iidfile = dockerfile.with_name("candidate.iid")
    command = ["docker", "build", "--pull=false", "--platform", admission.platform,
               "--file", str(dockerfile), "--tag", tag, "--iidfile", str(iidfile), "--rm", "--force-rm"]
    for name, value in sorted(labels.items()):
        command += ["--label", f"{name}={value}"]
    for name, value in sorted(build_args(admission.platform).items()):
        command += ["--build-arg", f"{name}={value}"]
    command.append(str(context))
    request = f"d12-core-image:{admission.platform}:{admission.recipe_sha256[:16]}"
    with boundary.managed_system_candidate_build(request=request) as ticket:
        result = runner(command, capture_output=True, text=True, timeout=timeout, check=False)
        log = ((result.stdout or "") + (result.stderr or "")).encode()[-LOG_EXCERPT_BYTES:].decode("utf-8", "ignore")
        if result.returncode != 0:
            raise D12ProfileError(f"candidate build failed with status {result.returncode}: {log[-4000:]}")
        image_id = iidfile.read_text(encoding="utf-8").strip() if iidfile.is_file() else ""
        if _IMAGE_ID.fullmatch(image_id) is None:
            raise D12ProfileError("candidate build returned no exact image ID")
        boundary.complete_operation(ticket, image_ids=(image_id,))
    return image_id, log


def remove_candidate_image(client: Any, ledger: Any, image_id: str, tag: str) -> dict[str, object]:
    """Remove only the exact ledgered candidate image, then prove ID and tag absence."""
    from repomap_test_support.resource_ledger import CleanupResult, FinalPresence, ResourceKind

    record = ledger.get(ResourceKind.DOCKER_IMAGE, image_id)
    if record.created_before_run or not record.creation_observed:
        raise D12ProfileError("candidate image is not owned by this run")
    ledger.mark_cleanup_attempted(ResourceKind.DOCKER_IMAGE, image_id)
    try:
        client.images.remove(image_id, force=False, noprune=False)
        if any(image_present(client, ref) for ref in (image_id, tag)):
            raise D12ProfileError("candidate image cleanup is unproved")
    except Exception:
        ledger.mark_cleanup_result(ResourceKind.DOCKER_IMAGE, image_id, CleanupResult.FAILED)
        raise
    ledger.mark_cleanup_result(ResourceKind.DOCKER_IMAGE, image_id, CleanupResult.REMOVED)
    ledger.mark_final_presence(ResourceKind.DOCKER_IMAGE, image_id, FinalPresence.ABSENT)
    return {"image_id": image_id, "tag": tag, "removed": True, "id_absent": True, "tag_absent": True}


def image_present(client: Any, reference: str) -> bool:
    try:
        return bool(client.images.get(reference))
    except Exception as error:
        if type(error).__name__ != "ImageNotFound":
            raise
        return False


def record_budget(ledger: Path, action: str, platform: str, source_sha256: str, recipe_sha256: str, *,
                  consumer: str = "", now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
                  ) -> dict[str, object]:
    """``append`` reserves one write-ahead attempt; host admission may ``consume`` it exactly once. Racing
    invocations serialize on the ledger directory's lock; refusals leave the bytes unchanged."""
    if platform not in PLATFORMS or not (_DIGEST.fullmatch(source_sha256) and _DIGEST.fullmatch(recipe_sha256)):
        raise D12ProfileError("budget entry needs a supported platform and exact digests")
    import fcntl

    directory = os.open(ledger.parent, os.O_RDONLY)
    temporary = ledger.with_name(f".{ledger.name}.{uuid.uuid4().hex}.tmp")
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        try:
            data = json.loads(ledger.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise D12ProfileError(f"build budget ledger is missing or unreadable: {error}") from error
        data = data if isinstance(data, dict) else {}
        attempts, held = data.get("attempts"), data.get("parent_admission_state")
        if not isinstance(attempts, list) or held is not None or (data.get("maximum_total"), data.get(
                "maximum_per_platform")) != (MAX_TOTAL_BUILDS, MAX_PLATFORM_BUILDS):
            raise D12ProfileError(f"build budget ledger is held or not at the approved bounds; parent state: {held}")
        platforms = [entry.get("platform") if isinstance(entry, dict) else None for entry in attempts]
        if (len(attempts) > MAX_TOTAL_BUILDS or len(set(platforms)) != len(platforms) or not set(platforms) <= set(
                PLATFORMS) or [entry.get("attempt") for entry in attempts] != list(range(1, len(attempts) + 1))):
            raise D12ProfileError("build budget ledger has duplicate, foreign or misnumbered attempts")
        found = [entry for entry in attempts if entry["platform"] == platform]
        if action == "append":
            if found or len(attempts) >= MAX_TOTAL_BUILDS:
                raise D12ProfileError(f"build budget exhausted for {platform}")
            found = [{"attempt": len(attempts) + 1, "platform": platform, "source_sha256": source_sha256,
                      "recipe_sha256": recipe_sha256, "reservation_id": uuid.uuid4().hex,
                      "recorded_at": now().isoformat()}]
            attempts.append(found[0])
        elif action != "consume" or not found or "consumed_at" in found[0] or (
                found[0].get("source_sha256"), found[0].get("recipe_sha256")) != (source_sha256, recipe_sha256):
            raise D12ProfileError(f"no unused write-ahead budget entry matches {platform} and the frozen identity")
        else:
            found[0].update(consumed_at=now().isoformat(), consumed_by=consumer)
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, ledger.stat().st_mode & 0o777)
            stream.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, ledger)
        os.fsync(directory)
    finally:
        temporary.unlink(missing_ok=True)
        os.close(directory)
    return found[0]


def write_report(name: str, payload: Mapping[str, object]) -> Path:
    """Write one bounded JSON report part; all parts stay within the evidence ceiling, and only the
    cleanup part may use the final reserve, so exact cleanup evidence always fits."""
    root = os.environ.get(ENV_REPORT_DIR)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    path = Path(root or ".") / f"{name}.json"
    others = sum(p.stat().st_size for p in path.parent.glob("*.json") if p != path) if root else 0
    ceiling = REPORT_TOTAL_LIMIT - (0 if name == "cleanup" else REPORT_CLEANUP_RESERVE)
    if not root or len(text.encode()) > REPORT_PART_LIMIT or others + len(text.encode()) > ceiling:
        raise D12ProfileError(f"D12 report part {name} is unbound or exceeds the evidence ceiling")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    """Operator helper: print the frozen identity, or write ahead one budget attempt for it."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("identity", "budget-append"))
    parser.add_argument("--platform", choices=PLATFORMS, required=True)
    for option in ("--repo-root", "--ledger", "--expect-source", "--expect-recipe"):
        parser.add_argument(option)
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root or Path.cwd()).resolve()
    if str(repo_root / "src" / "main" / "python") not in sys.path:
        sys.path.insert(0, str(repo_root / "src" / "main" / "python"))
    identity = {"platform": args.platform, **frozen_identity(repo_root, args.platform)}
    if args.command == "budget-append":
        if not args.ledger or (args.expect_source, args.expect_recipe) != (
                identity["source_sha256"], identity["recipe_sha256"]):
            raise D12ProfileError("frozen source/recipe identity does not match the checkout")
        identity["budget_entry"] = record_budget(Path(args.ledger), "append", args.platform,
                                                 args.expect_source, args.expect_recipe)
    print(json.dumps(identity, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
