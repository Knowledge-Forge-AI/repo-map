"""Scoped pgvector materialization inside the canonical disposable sandbox."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
from collections.abc import Callable, Sequence
import urllib.request
import uuid

from runner_pgvector_profile import (
    CORE_PROFILE, EXPECTED_ABI, EXPECTED_VERSION, PGVECTOR_PROFILE,
    validate_profile_choice, verify_pgvector_source_facts,
)
from runner_sandbox_assets import (
    IMAGE_OWNER_LABEL, IMAGE_RECIPE_LABEL, PGVECTOR_SANDBOX_TAG,
    compute_recipe_hash, generate_pgvector_recipe_definition,
    remove_pgvector_container, validate_pgvector_runtime,
)
from test_sandbox_contract import TEST_POSTGRES_IMAGE

_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


class _SetupCommands:
    """Emit bounded setup evidence without exposing argv or environment values."""

    def __init__(self, environment: dict[str, str], runner: Callable | None) -> None:
        self.environment, self.runner = environment, runner or subprocess.run
        self.stage = "source_facts"
        self.failed_stage: str | None = None

    def event(self, stage: str, status: str, **fields: object) -> None:
        self.stage = stage
        if status == "failed" and fields.get("terminal"):
            self.failed_stage = self.failed_stage or stage
        print(json.dumps({"event": "repomap-pgvector-setup-v1", "stage": stage,
                          "status": status, **fields}, sort_keys=True), flush=True)

    def safe_text(self, value: str | bytes | None) -> str:
        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
        for name, secret in self.environment.items():
            if secret and re.search(r"TOKEN|PASSWORD|SECRET|CREDENTIAL|API_KEY", name, re.I):
                text = text.replace(secret, "<redacted>")
        text = re.sub(r"(?:/Users/|/home/)[^\s\"']+", "<private-path>", text)
        text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1<redacted>@", text)
        text = re.sub(r"(?i)((?:token|password|secret|api_key)[=:]\s*)[^\s]+",
                      r"\1<redacted>", text)
        return text

    def execute(self, stage: str, cmd: list[str], *, check: bool = True,
                payload: bytes | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
        self.event(stage, "started")
        command_exception = None
        try:
            raw = self.runner(cmd, env=self.environment, capture_output=True,
                              text=payload is None, input=payload, timeout=timeout, check=False)
            def decoded(value: str | bytes | None) -> str:
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
            result = subprocess.CompletedProcess(
                cmd, raw.returncode, decoded(raw.stdout), decoded(raw.stderr))
        except (OSError, subprocess.TimeoutExpired) as error:
            command_exception = type(error).__name__
            result = subprocess.CompletedProcess(
                cmd, 124 if isinstance(error, subprocess.TimeoutExpired) else 127,
                self.safe_text(getattr(error, "stdout", None)),
                self.safe_text(getattr(error, "stderr", None)) or type(error).__name__)
        output: dict[str, object] = {
            name: self.safe_text(getattr(result, name))[:4096] for name in ("stdout", "stderr")}
        output.update({name + "_bytes": len(getattr(result, name).encode())
                       for name in ("stdout", "stderr")})
        output["output_truncated"] = any(len(getattr(result, name)) > 4096
                                         for name in ("stdout", "stderr"))
        self.event(stage, "completed" if result.returncode == 0 else "failed",
                   returncode=result.returncode, command_exception=command_exception, **output)
        if check and result.returncode != 0:
            self.failed_stage = self.failed_stage or stage
            raise RuntimeError(f"pgvector setup failed at {stage}: status={result.returncode}; "
                               f"stderr={output['stderr']}; stdout={output['stdout']}")
        return result


def extract_profile_from_argv(argv: list[str]) -> str:
    runner_argv = argv[:argv.index("--")] if "--" in argv else argv
    for i, arg in enumerate(runner_argv):
        if arg == "--pg-test-profile" and i + 1 < len(runner_argv):
            return validate_profile_choice(runner_argv[i + 1])
        if arg.startswith("--pg-test-profile="):
            return validate_profile_choice(arg.split("=", 1)[1])
    return CORE_PROFILE


def forward_profile_into_sandbox(argv: list[str], profile: str) -> list[str]:
    validated = validate_profile_choice(profile)
    index = argv.index("--") if "--" in argv else len(argv)
    if any(arg == "--pg-test-profile" or arg.startswith("--pg-test-profile=")
           for arg in argv[:index]):
        return list(argv)
    return [*argv[:index], "--pg-test-profile", validated, *argv[index:]]


def validate_sandbox_profile_options(
    args,
    forwarded_pytest_args: Sequence[str] | None = None,
) -> None:
    if getattr(args, "pg_test_profile", CORE_PROFILE) != PGVECTOR_PROFILE:
        return
    if args.suite != "int" or not getattr(args, "no_coverage", False):
        raise RuntimeError("--pg-test-profile pgvector requires scoped int --no-coverage")
    if getattr(args, "pg_container_runtime", "docker") != "docker":
        raise RuntimeError("--pg-test-profile pgvector requires --pg-container-runtime docker")
    if forwarded_pytest_args is not None and not list(forwarded_pytest_args):
        raise RuntimeError("canonical pgvector profile requires scoped test selector(s) after '--'")


def _verify_source_archive(payload: bytes, facts: dict[str, object]) -> None:
    if len(payload) != facts["archive_bytes"]:
        raise RuntimeError("pgvector archive byte count mismatch")
    if hashlib.sha256(payload).hexdigest() != facts["archive_sha256"]:
        raise RuntimeError("pgvector archive SHA-256 mismatch")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for name, expected in (
            ("vector.control", f"default_version = '{EXPECTED_VERSION}'"), ("LICENSE", "PostgreSQL"),
        ):
            member = archive.extractfile(f"pgvector-{EXPECTED_VERSION}/" + name)
            if member is None or expected not in member.read().decode("utf-8"):
                raise RuntimeError(f"pgvector archive {name} verification failed")


def _resolve_cached_source_archive(inner_env: dict[str, str], facts: dict[str, object]) -> Path:
    cache = Path(inner_env.get("XDG_CACHE_HOME", "/sandbox-scratch/cache"))
    for candidate in (inner_env.get("REPOMAP_PGVECTOR_ARCHIVE_PATH", ""),
                      str(cache / f"pgvector-{EXPECTED_VERSION}.tar.gz"),
                      f"/workspace/tools/pgvector-{EXPECTED_VERSION}.tar.gz"):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"pgvector-{EXPECTED_VERSION}.tar.gz"
    try:
        with urllib.request.urlopen(str(facts["archive_url"]), timeout=60) as response:
            payload = response.read(2_000_000)
        target.write_bytes(payload)
    except (OSError, ValueError) as error:
        raise RuntimeError("pgvector source archive unavailable; no materialization performed") from error
    return target


def _materialize_inner_pgvector_if_requested(
    test_argv: list[str], inner_env: dict[str, str], *,
    runner_fn: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    archive_verifier_fn: Callable[[bytes, dict[str, object]], None] | None = None,
) -> dict[str, object] | None:
    if extract_profile_from_argv(test_argv) == CORE_PROFILE:
        return None
    index = test_argv.index("--") if "--" in test_argv else len(test_argv)
    argv = test_argv[:index]
    suites = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "--suite"]
    suites += [arg.split("=", 1)[1] for arg in argv if arg.startswith("--suite=")]
    if suites != ["int"] or "--no-coverage" not in argv:
        raise RuntimeError("only canonical int scoped --no-coverage profile pgvector allowed")
    if not test_argv[index + 1:]:
        raise RuntimeError("canonical pgvector profile requires scoped test selector(s) after '--'")

    setup = _SetupCommands(inner_env, runner_fn)
    try:
        return _materialize_pgvector(setup, inner_env, archive_verifier_fn)
    except BaseException as error:
        setup.event(setup.failed_stage or setup.stage, "failed",
                    error=setup.safe_text(str(error))[:4096], terminal=True)
        raise


def _materialize_pgvector(
    setup: _SetupCommands, inner_env: dict[str, str],
    archive_verifier: Callable[[bytes, dict[str, object]], None] | None,
) -> dict[str, object]:
    execute = setup.execute
    facts = verify_pgvector_source_facts()
    base = json.loads(execute("base_verification", ["docker", "image", "inspect", TEST_POSTGRES_IMAGE]).stdout)[0]
    base_id, digests = base.get("Id", ""), base.get("RepoDigests", [])
    if (_IMAGE_ID.fullmatch(base_id) is None
        or not any(value.endswith("@" + TEST_POSTGRES_IMAGE.split("@", 1)[1]) for value in digests)
        or base.get("Os") != "linux" or not base.get("Architecture")):
        raise RuntimeError("pinned PostgreSQL base identity/platform verification failed")
    setup.event("source_acquisition", "started")
    archive = _resolve_cached_source_archive(inner_env, facts)
    with archive.open("rb") as source:
        payload = source.read(int(str(facts["archive_bytes"])) + 1)
    setup.event("source_acquisition", "completed", archive_bytes=len(payload))
    setup.event("source_verification", "started")
    (archive_verifier or _verify_source_archive)(payload, facts)
    setup.event("source_verification", "completed", archive_bytes=len(payload),
                archive_sha256=hashlib.sha256(payload).hexdigest())
    recipe_digest = compute_recipe_hash(generate_pgvector_recipe_definition())
    container = f"repomap-pgvector-build-{uuid.uuid4().hex}"
    created = False
    primary: BaseException | None = None
    result_id = server_version = config_version = build_packages = ""
    try:
        created = True  # A timed-out create may still have created the exact owned name.
        execute("builder_create", ["docker", "create", "--pull=never", "--name", container, "--label",
                 "org.repomap.test.profile=pgvector", "--tmpfs", "/tmp:rw,exec",
                 "--tmpfs", "/var/lib/postgresql/data:rw", TEST_POSTGRES_IMAGE, "sleep", "3600"])
        execute("builder_start", ["docker", "start", container])
        prefix = ["docker", "exec", "--user", "0", "--workdir", "/tmp", container]
        server_version = execute("abi_verification", [*prefix, "postgres", "--version"]).stdout.strip()
        config_version = execute("abi_verification", [*prefix, "/usr/local/bin/pg_config", "--version"]).stdout.strip()
        if (not server_version.endswith(config_version.removeprefix("PostgreSQL "))
            or re.fullmatch(r"PostgreSQL 16\.[0-9]+", config_version) is None):
            raise RuntimeError(f"PostgreSQL server/pg_config ABI {EXPECTED_ABI} mismatch")
        setup.event("abi_verification", "completed", postgres_abi=EXPECTED_ABI,
                    postgres_server=server_version, pg_config=config_version)
        # Docker cp cannot reliably address container tmpfs mounts. Exec writes
        # these exact verified bytes in the running builder's mount namespace.
        execute("archive_transfer", [*prefix[:-1], "-i", container, "dd",
                                     "of=/tmp/pgvector.tar.gz", "bs=65536"], payload=payload)
        checksum = execute("archive_destination_verification", [*prefix, "sha256sum", "/tmp/pgvector.tar.gz"])
        size = execute("archive_destination_verification", [*prefix, "wc", "-c", "/tmp/pgvector.tar.gz"])
        if (not checksum.stdout.split() or checksum.stdout.split()[0] != hashlib.sha256(payload).hexdigest()
                or not size.stdout.split() or size.stdout.split()[0] != str(len(payload))):
            raise RuntimeError("pgvector destination archive byte identity mismatch")
        setup.event("archive_destination_verification", "completed", verified=True,
                    archive_bytes=len(payload), archive_sha256=hashlib.sha256(payload).hexdigest())
        execute("archive_extraction", [*prefix, "tar", "-xzf", "/tmp/pgvector.tar.gz", "-C", "/tmp"])
        execute("build_dependencies", [*prefix, "apk", "add", "--no-cache", "--virtual", ".build-deps", "build-base"])
        build_packages = execute("build_dependencies", [*prefix, "apk", "info", "-v"]).stdout.strip()
        source_dir = f"/tmp/pgvector-{EXPECTED_VERSION}"
        make = [*prefix, "make", "-C", source_dir,
                "PG_CONFIG=/usr/local/bin/pg_config", "with_llvm=no", "OPTFLAGS="]
        execute("build_clean", [*make, "clean"])
        execute("build", make)
        execute("build_install", [*make, "install"])
        for path in ("/usr/local/lib/postgresql/vector.so",
                     "/usr/local/share/postgresql/extension/vector.control",
                     f"/usr/local/share/postgresql/extension/vector--{EXPECTED_VERSION}.sql"):
            execute("installed_files", [*prefix, "test", "-f", path])
        execute("build_artifact_cleanup", [*prefix, "rm", "-rf", "/tmp/pgvector.tar.gz", source_dir])
        execute("build_dependency_cleanup", [*prefix, "apk", "del", ".build-deps"])
        execute("builder_stop", ["docker", "stop", container])
        result_id = execute("commit", [
            "docker", "commit", "-c", 'CMD ["postgres"]',
            "-c", f"LABEL {IMAGE_OWNER_LABEL}=true",
            "-c", f"LABEL {IMAGE_RECIPE_LABEL}={recipe_digest}",
            "-c", "LABEL org.repomap.test.profile=pgvector", container, PGVECTOR_SANDBOX_TAG,
        ]).stdout.strip()
        if _IMAGE_ID.fullmatch(result_id) is None:
            raise RuntimeError("pgvector commit returned an invalid Engine image identity")
        setup.event("image_built", "completed", image_built=True, resulting_engine_id=result_id,
                    recipe_digest=recipe_digest)
    except BaseException as error:
        primary = error
        setup.failed_stage = setup.failed_stage or setup.stage
        raise
    finally:
        if created:
            try:
                remove_pgvector_container(execute, setup.event, container, "cleanup")
            except BaseException as cleanup_error:
                setup.event("cleanup", "failed", verified=False,
                            error=setup.safe_text(str(cleanup_error))[:4096])
                if primary is None:
                    raise
                primary.add_note("pgvector builder cleanup failed; see setup cleanup diagnostics")
    installed = json.loads(execute("runtime_image_verification", ["docker", "image", "inspect", result_id]).stdout)[0]
    config = installed.get("Config", {})
    if (installed.get("Id") != result_id or config.get("Cmd") != ["postgres"]
            or config.get("Entrypoint") != base.get("Config", {}).get("Entrypoint")
            or (installed.get("Os"), installed.get("Architecture")) != (base["Os"], base["Architecture"])
            or config.get("Labels", {}).get(IMAGE_OWNER_LABEL) != "true"
            or config.get("Labels", {}).get(IMAGE_RECIPE_LABEL) != recipe_digest
            or config.get("Labels", {}).get("org.repomap.test.profile") != PGVECTOR_PROFILE):
        setup.event("runtime_image_verification", "failed", terminal=True)
        raise RuntimeError("pgvector resulting image identity/platform/recipe/entrypoint verification failed")
    runtime = validate_pgvector_runtime(execute, setup.event, result_id)
    report = {
        "pgvector_setup": "materialized", "pgvector_version": EXPECTED_VERSION,
        "source_commit": facts["commit"], "archive_sha256": facts["archive_sha256"],
        "source_license": facts["license"], "postgres_server": server_version,
        "pg_config": config_version, "postgres_abi": EXPECTED_ABI,
        "observed_platform": f"{base['Os']}/{base['Architecture']}",
        "base_engine_id": base_id, "base_repo_digest": digests,
        "resulting_engine_id": result_id, "recipe_digest": recipe_digest,
        "image_built": True, "environment_materialized": True, **runtime,
        "build_package_versions": build_packages.splitlines(), "count": 1,
        "setup_cleanup": {"disposable_container": container, "removed": True, "verified": True},
    }
    print(json.dumps(report, sort_keys=True), flush=True)
    inner_env["REPOMAP_TEST_PG_IMAGE"] = result_id
    inner_env["REPOMAP_TEST_PG_PROFILE"] = PGVECTOR_PROFILE
    return report
