"""TEST-RUNNER-SAFETY1 build-free smoke orchestration contracts."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_kg.runtime.release import PSYCOPG_RELEASE_VERSION
import smoke
from smoke.container_smoke import SmokeConfig, run_container_smoke


ROOT = Path(__file__).resolve().parents[6]
EXACT_IMAGE = "sha256:" + "a" * 64


class NotFound(Exception):
    pass


class FakeImage:
    def __init__(self, identity: str = EXACT_IMAGE):
        self.id = identity
        self.tags: list[str] = []
        self.attrs = {"Config": {"Labels": {"io.repomap.release.psycopg": "3.2.12"}}}


class FakeImages:
    def __init__(self, image: FakeImage):
        self.image = image
        self.get_calls: list[str] = []
        self.forbidden_calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def get(self, reference):
        self.get_calls.append(reference)
        return self.image

    def _forbidden(self, name: str, *args: object, **kwargs: object) -> None:
        self.forbidden_calls.append((name, args, kwargs))
        raise AssertionError(f"smoke must not {name} images")

    def list(self, *args, **kwargs): self._forbidden("list", *args, **kwargs)
    def pull(self, *args, **kwargs): self._forbidden("pull", *args, **kwargs)
    def build(self, *args, **kwargs): self._forbidden("build", *args, **kwargs)
    def remove(self, *args, **kwargs): self._forbidden("remove", *args, **kwargs)


class FakeContainer:
    def __init__(self, identity: str, labels: dict[str, str], collection):
        self.id = identity
        self._collection = collection
        self.attrs = {
            "Config": {"Labels": dict(labels)},
            "Image": EXACT_IMAGE,
            "Mounts": [],
        }

    def start(self): return None
    def logs(self, **kwargs): return b"public smoke output\n"
    def remove(self, **kwargs): self._collection.objects.pop(self.id, None)

    def wait(self, timeout):
        del timeout
        if self._collection.wait_error is not None:
            raise self._collection.wait_error
        return {"StatusCode": self._collection.status_code}


class FakeContainers:
    def __init__(self):
        self.objects = {}
        self.create_calls = []
        self.run_calls = []
        self.status_code = 0
        self.wait_error = None

    def list(self, all=False): return list(self.objects.values())

    def get(self, identity):
        try:
            return self.objects[identity]
        except KeyError as error:
            raise NotFound(identity) from error

    def create(self, image, command, **kwargs):
        self.create_calls.append((image, command, kwargs))
        identity = f"container-{len(self.create_calls)}"
        container = FakeContainer(identity, kwargs["labels"], self)
        self.objects[identity] = container
        return container

    def run(self, *args, **kwargs):
        self.run_calls.append((args, kwargs))
        raise AssertionError("smoke must use containers.create, never containers.run")


class FakeClient:
    def __init__(self, image: FakeImage | None = None):
        self.images = FakeImages(image or FakeImage())
        self.containers = FakeContainers()
        self.closed = False

    def ping(self): return True
    def close(self): self.closed = True


def _resource_run(tmp_path: Path):
    identity = RunIdentity("repo-map_dev", "TEST-RUNNER-SAFETY1", "run-1")
    ledger = ResourceLedger.create(tmp_path / "ledger.json", identity)
    run_root = tmp_path / "run-root"
    run_root.mkdir()
    retained = []
    return SimpleNamespace(
        ledger=ledger,
        layout=SimpleNamespace(run_root=run_root),
        retain_evidence=lambda path, reason: retained.append((path, reason)),
        retained=retained,
    )


def _config(tmp_path: Path, reference: str | None = EXACT_IMAGE):
    source_root = tmp_path / "repo" / "src" / "main" / "python"
    source_root.mkdir(parents=True, exist_ok=True)
    return SmokeConfig(
        repo_root=tmp_path / "repo",
        image_reference=reference,
        psycopg_release_version=PSYCOPG_RELEASE_VERSION,
        timeout_seconds=5,
    )


@pytest.mark.parametrize("reference", [None, "python:3.13-slim", "SHA256:" + "a" * 64])
def test_smoke_refuses_missing_or_mutable_image_reference_before_create(
    tmp_path, reference, capsys
):
    client = FakeClient()

    result = run_container_smoke(
        _config(tmp_path, reference),
        resource_run=_resource_run(tmp_path),
        docker_client_factory=lambda: client,
    )

    assert result == 2
    assert client.containers.create_calls == []
    assert "exact local image ID" in capsys.readouterr().err


def test_exact_image_readback_drift_refuses_before_container_creation(tmp_path):
    client = FakeClient(FakeImage("sha256:" + "b" * 64))

    result = run_container_smoke(
        _config(tmp_path),
        resource_run=_resource_run(tmp_path),
        docker_client_factory=lambda: client,
    )

    assert result == 2
    assert client.containers.create_calls == []


def test_build_free_smoke_uses_exact_image_and_retains_lifecycle_evidence(tmp_path):
    client = FakeClient()
    resource_run = _resource_run(tmp_path)

    def lifecycle(config, run, owner, admitted_client, budget):
        assert config.repo_root == tmp_path / "repo"
        assert run is resource_run
        assert admitted_client is client
        assert owner is not None
        assert budget.limit_seconds == 5
        return {
            "result": "passed",
            "elapsed_seconds": 4.5,
            "step_timings": {"lifecycle": 4.0, "cleanup": 0.5},
            "assertions": {"exact_cleanup": True},
        }

    result = run_container_smoke(
        _config(tmp_path),
        resource_run=resource_run,
        docker_client_factory=lambda: client,
        lifecycle_runner=lifecycle,
    )

    assert result == 0
    assert client.images.get_calls == [EXACT_IMAGE]
    assert client.images.forbidden_calls == []
    assert client.containers.run_calls == []
    assert client.containers.create_calls == []
    assert client.containers.objects == {}
    projection = resource_run.ledger.public_projection()
    assert projection["phase_containers_remaining"] == 0
    assert projection["pre_existing_objects_mutated"] is False
    report_path = resource_run.layout.run_root / "evidence/smoke-lifecycle.json"
    assert '"exact_cleanup": true' in report_path.read_text(encoding="utf-8")
    assert resource_run.retained == [
        (report_path.parent, "report_source")
    ]
    assert client.closed is True


def test_smoke_refuses_without_the_allocating_resource_run(tmp_path, capsys):
    client = FakeClient()

    result = run_container_smoke(
        _config(tmp_path),
        resource_run=None,
        docker_client_factory=lambda: client,
    )

    assert result == 2
    assert client.containers.create_calls == []
    assert "managed resource run" in capsys.readouterr().err


def test_missing_local_image_is_distinguished_as_admission_refusal(tmp_path, capsys):
    client = FakeClient()

    def missing(_reference):
        raise NotFound("missing")

    setattr(client.images, "get", missing)
    result = run_container_smoke(
        _config(tmp_path),
        resource_run=_resource_run(tmp_path),
        docker_client_factory=lambda: client,
    )

    assert result == 2
    assert client.containers.create_calls == []
    assert "host_admission_refused" in capsys.readouterr().err


def test_lifecycle_failure_verifies_baseline_and_closes_client(tmp_path, capsys):
    client = FakeClient()
    resource_run = _resource_run(tmp_path)

    def failing_lifecycle(*_args):
        raise RuntimeError("bounded lifecycle failed")

    result = run_container_smoke(
        _config(tmp_path),
        resource_run=resource_run,
        docker_client_factory=lambda: client,
        lifecycle_runner=failing_lifecycle,
    )

    assert result == 2
    assert client.containers.objects == {}
    projection = resource_run.ledger.public_projection()
    assert projection["phase_containers_remaining"] == 0
    assert projection["pre_existing_objects_mutated"] is False
    assert client.closed is True
    assert "container smoke execution failed" in capsys.readouterr().err


def test_timeout_budget_validation_is_fail_closed(tmp_path, capsys):
    client = FakeClient()
    config = _config(tmp_path)
    config = SmokeConfig(
        repo_root=config.repo_root,
        image_reference=config.image_reference,
        psycopg_release_version=config.psycopg_release_version,
        timeout_seconds=0,
    )

    result = run_container_smoke(
        config,
        resource_run=_resource_run(tmp_path),
        docker_client_factory=lambda: client,
    )

    assert result == 2
    assert client.images.get_calls == []
    assert "at least 1 second" in capsys.readouterr().err


def test_smoke_advisory_target_warning_when_elapsed_exceeds_600(tmp_path, capsys):
    client = FakeClient()
    resource_run = _resource_run(tmp_path)

    def slow_lifecycle(config, run, owner, admitted_client, budget):
        return {
            "result": "passed",
            "elapsed_seconds": 605.0,
            "step_timings": {"lifecycle": 604.0, "cleanup": 1.0},
        }

    config = SmokeConfig(
        repo_root=_config(tmp_path).repo_root,
        image_reference=_config(tmp_path).image_reference,
        psycopg_release_version=_config(tmp_path).psycopg_release_version,
        timeout_seconds=900,
    )
    result = run_container_smoke(
        config,
        resource_run=resource_run,
        docker_client_factory=lambda: client,
        lifecycle_runner=slow_lifecycle,
    )
    assert result == 0
    report_path = resource_run.layout.run_root / "evidence/smoke-lifecycle.json"
    content = report_path.read_text(encoding="utf-8")
    assert "exceeded advisory target of 600.0s" in content
    assert "timing_telemetry" in content
    assert "exceeded advisory target of 600.0s" in capsys.readouterr().err


def test_smoke_package_import_is_dependency_free_under_isolated_interpreter() -> None:
    script = (
        "import sys\n"
        "sys.path.insert(0, 'tools')\n"
        "import smoke\n"
        "forbidden = [\n"
        "    'smoke.container_smoke',\n"
        "    'smoke.lifecycle',\n"
        "    'repomap_kg',\n"
        "    'docker',\n"
        "    'psycopg',\n"
        "    'pytest',\n"
        "    'coverage',\n"
        "    'psutil',\n"
        "]\n"
        "imported = [m for m in sys.modules if any(m == f or m.startswith(f + '.') for f in forbidden)]\n"
        "if imported:\n"
        "    print(f'ERROR: forbidden modules imported: {imported}', file=sys.stderr)\n"
        "    sys.exit(1)\n"
        "sys.exit(0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}, stderr: {result.stderr}"


@pytest.mark.parametrize("valid_reference", [
    "sha256:" + "0" * 64, "sha256:" + "f" * 64, "sha256:" + "0123456789abcdef" * 4,
    "sha256:44c2b4be8e0ceae353a64c8929a7635a302ab01389283748293847281928374a",
])
def test_is_exact_image_reference_accepts_valid_lowercase_sha256(valid_reference: str) -> None:
    assert smoke.is_exact_image_reference(valid_reference) is True


@pytest.mark.parametrize("invalid_reference", [
    None, "", "   ", "sha256:" + "a" * 63, "sha256:" + "a" * 65, "sha256:" + "A" * 64,
    "sha256:" + "g" * 64, "SHA256:" + "a" * 64, "python:3.13-slim", "ubuntu:latest",
    "repomap-smoke", f"sha256:{'a' * 64}\n", f" sha256:{'a' * 64}", f"sha256:{'a' * 64} ",
    12345, ["sha256:" + "a" * 64], {"ref": "sha256:" + "a" * 64}, object(),
])
def test_is_exact_image_reference_rejects_invalid_references(invalid_reference: object) -> None:
    assert smoke.is_exact_image_reference(invalid_reference) is False


def test_container_smoke_reexports_package_helper_identity() -> None:
    from smoke.container_smoke import is_exact_image_reference as reexported
    assert reexported is smoke.is_exact_image_reference


def test_wait_postgres_verifies_tcp_readiness() -> None:
    from smoke.lifecycle import _wait_postgres, SmokeBudget
    fake_container = SimpleNamespace(exec_run=MagicMock(return_value=SimpleNamespace(exit_code=0)))
    _wait_postgres(fake_container, SmokeBudget(100.0))
    fake_container.exec_run.assert_called_once_with(
        ["pg_isready", "-h", "127.0.0.1", "-p", "5432", "-U", "repomap", "-d", "postgres"]
    )


def test_run_runtime_probe_preserves_redacted_failure_output(tmp_path: Path) -> None:
    from smoke.lifecycle import _run_runtime_probe, SmokeBudget
    probe = SimpleNamespace(start=MagicMock(), wait=MagicMock(return_value={"StatusCode": 1}),
                            logs=MagicMock(return_value=b"secret_pw /workspace failed"))
    fake_client = SimpleNamespace(containers=SimpleNamespace(get=MagicMock(return_value=probe)))
    cleaned = []
    fake_containers = SimpleNamespace(create=MagicMock(return_value="probe-id"),
                                      cleanup=lambda i: cleaned.append(i))
    config = SimpleNamespace(image_reference="sha256:" + "a" * 64, repo_root=tmp_path)
    with pytest.raises(RuntimeError) as exc_info:
        _run_runtime_probe(config, fake_containers, fake_client, "net", "postgres",
                           "secret_pw", SmokeBudget(100.0))
    assert "exit=1" in str(exc_info.value) and "[REDACTED]" in str(exc_info.value)
    assert "secret_pw" not in str(exc_info.value) and cleaned == ["probe-id"]
