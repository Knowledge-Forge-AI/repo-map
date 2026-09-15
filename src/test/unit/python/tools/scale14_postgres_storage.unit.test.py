from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scale14_postgres_storage import (
    PGDATA_CONTAINER_PATH,
    PostgresStorageAuthority,
    PostgresStorageError,
    read_allocated_tree_bytes,
    read_backing_free_bytes,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 100

    def __call__(self) -> int:
        value = self.value
        self.value += 25
        return value


class _Runner:
    def __init__(self, outputs: list[tuple[int, str, str]]) -> None:
        self.outputs = iter(outputs)
        self.calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def __call__(self, arguments, **kwargs):
        self.calls.append((tuple(arguments), dict(kwargs)))
        returncode, stdout, stderr = next(self.outputs)
        return subprocess.CompletedProcess(arguments, returncode, stdout, stderr)


def _plan(data_dir: Path = Path("/private/disposable/runtime/postgres-data")):
    labels = {
        "org.repomap.runtime": "true",
        "org.repomap.home_hash": "public-safe-hash",
        "org.repomap.component": "postgres",
    }
    identity = SimpleNamespace(
        postgres_container="repomap-public-safe-postgres",
        labels=lambda component: labels if component == "postgres" else {},
    )
    return SimpleNamespace(
        container_runtime="docker",
        identity=identity,
        postgres_data_dir=data_dir,
    )


def _inspect(
    *,
    source: str = "/private/disposable/runtime/postgres-data",
    destination: str = PGDATA_CONTAINER_PATH,
    mode: str = "rw",
    labels: dict[str, str] | None = None,
) -> str:
    return json.dumps(
        [
            {
                "Config": {
                    "Labels": labels
                    or {
                        "org.repomap.runtime": "true",
                        "org.repomap.home_hash": "public-safe-hash",
                        "org.repomap.component": "postgres",
                    }
                },
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": source,
                        "Destination": destination,
                        "Mode": mode,
                        "RW": mode == "rw",
                    }
                ],
            }
        ]
    )


class _Readings:
    def __init__(self, values) -> None:
        self.values = iter(values)

    def __call__(self, _root: Path):
        return next(self.values)


def test_storage_authority_uses_exact_argv_and_derives_delta() -> None:
    runner = _Runner([(0, _inspect(), ""), (0, _inspect(), "")])
    authority = PostgresStorageAuthority(
        _plan(),
        runner=runner,
        clock_ns=_Clock(),
        allocated_reader=_Readings((10 * 1024, 14 * 1024)),
        free_reader=_Readings((900 * 1024, 800 * 1024)),
    )

    baseline = authority.capture_baseline()
    sample = authority.capture()

    assert baseline.baseline_bytes == 10 * 1024
    assert baseline.current_bytes == 10 * 1024
    assert baseline.delta_bytes == 0
    assert sample.delta_bytes == 4 * 1024
    assert sample.free_bytes == 800 * 1024
    assert sample.availability == "available"
    assert sample.upper_bound is False
    assert sample.sampling_elapsed_ns == 25
    assert [call[0] for call in runner.calls] == [
        ("docker", "inspect", "repomap-public-safe-postgres"),
        ("docker", "inspect", "repomap-public-safe-postgres"),
    ]
    for _arguments, kwargs in runner.calls:
        assert kwargs == {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": 1.0,
            "shell": False,
        }


@pytest.mark.parametrize(
    ("inspect_output", "message"),
    (
        (_inspect(labels={"org.repomap.runtime": "false"}), "labels"),
        (_inspect(destination="/wrong"), "mount"),
        (_inspect(source="/wrong"), "mount"),
        (_inspect(mode="ro"), "mount"),
        ("not-json", "inspection"),
    ),
)
def test_storage_authority_rejects_unowned_or_changed_scope(
    inspect_output: str,
    message: str,
) -> None:
    runner = _Runner([(0, inspect_output, "")])

    with pytest.raises(PostgresStorageError, match=message):
        PostgresStorageAuthority(_plan(), runner=runner).capture_baseline()


@pytest.mark.parametrize(
    ("outputs", "allocated", "free", "availability"),
    (
        ([(1, "", "failed")], 10, 900, "runtime_inspection_unavailable"),
        ([(0, _inspect(), "")], None, 900, "pgdata_measurement_unavailable"),
        ([(0, _inspect(), "")], 10, None, "backing_free_measurement_unavailable"),
    ),
)
def test_storage_authority_reports_unavailability_without_false_zero(
    outputs: list[tuple[int, str, str]],
    allocated: int | None,
    free: int | None,
    availability: str,
) -> None:
    sample = PostgresStorageAuthority(
        _plan(),
        runner=_Runner(outputs),
        allocated_reader=lambda _root: allocated,
        free_reader=lambda _root: free,
    ).capture_baseline()

    assert sample.availability == availability
    assert sample.current_bytes is None
    assert sample.delta_bytes is None
    assert sample.free_bytes is None


def test_storage_authority_accepts_exact_scope_contraction_without_false_loss() -> None:
    runner = _Runner([(0, _inspect(), ""), (0, _inspect(), "")])
    authority = PostgresStorageAuthority(
        _plan(),
        runner=runner,
        allocated_reader=_Readings((10 * 1024, 9 * 1024)),
        free_reader=_Readings((900 * 1024, 800 * 1024)),
    )
    authority.capture_baseline()

    sample = authority.capture()

    assert sample.availability == "available"
    assert sample.current_bytes == 9 * 1024
    assert sample.delta_bytes == 0
    assert sample.free_bytes == 800 * 1024


def test_storage_sample_projection_is_path_free_and_bounded() -> None:
    runner = _Runner([(0, _inspect(), "")])
    sample = PostgresStorageAuthority(
        _plan(),
        runner=runner,
        allocated_reader=lambda _root: 10 * 1024,
        free_reader=lambda _root: 900 * 1024,
    ).capture_baseline()

    encoded = json.dumps(sample.to_payload(), sort_keys=True)

    assert len(encoded.encode("utf-8")) < 4096
    assert "/private/" not in encoded
    assert "public-safe-hash" not in encoded
    assert "repomap-public-safe-postgres" not in encoded
    assert sample.scope == "owned_postgresql_pgdata"


def test_local_bind_readers_are_exact_scope_and_symlink_safe(tmp_path: Path) -> None:
    root = tmp_path / "pgdata"
    root.mkdir()
    before = read_allocated_tree_bytes(root)
    root.joinpath("payload").write_bytes(b"x" * 1024 * 1024)
    root.joinpath("outside-link").symlink_to(tmp_path)
    after = read_allocated_tree_bytes(root)

    assert isinstance(before, int)
    assert isinstance(after, int)
    assert after >= before
    assert read_backing_free_bytes(root) is not None
    assert read_allocated_tree_bytes(root / "outside-link") is None
