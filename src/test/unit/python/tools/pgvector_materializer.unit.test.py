"""Binary handoff and failure evidence; Docker/image operations are doubles."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from unittest.mock import MagicMock, patch

import pytest

import runner_sandbox as materializer
import test_sandbox_entrypoint as entrypoint
from runner_pgvector_profile import EXPECTED_VERSION, verify_pgvector_source_facts
from runner_sandbox_assets import IMAGE_OWNER_LABEL, IMAGE_RECIPE_LABEL, compute_recipe_hash, RUNTIME_SMOKE_SQL
from test_sandbox_contract import TEST_POSTGRES_IMAGE

ARGV = ["--suite", "int", "--no-coverage", "--pg-test-profile", "pgvector",
        "--", "src/test/int/python/example.int.test.py::test_example"]


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name, payload in {
            "vector.control": f"default_version = '{EXPECTED_VERSION}'".encode(),
            "LICENSE": b"PostgreSQL",
            "binary.dat": b"\x00\xff\xfe\x80\n\r\x00" * 40,
        }.items():
            info = tarfile.TarInfo(f"pgvector-{EXPECTED_VERSION}/{name}")
            info.size = len(payload)
            stream.addfile(info, io.BytesIO(payload))
    payload = archive.read_bytes()
    facts = dict(verify_pgvector_source_facts(), archive_bytes=len(payload),
                 archive_sha256=hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(materializer, "verify_pgvector_source_facts", lambda: facts)
    return archive, payload, facts


class BuilderDouble:
    """Fail on unknown operations; perform real stdin transfer and tar extraction."""

    def __init__(self, root: Path, failure: str = "") -> None:
        self.root, self.failure = root, failure
        self.commands: list[list[str]] = []
        self.archive = root / "pgvector.tar.gz"
        self.installed = False
        self.dependencies_removed = False
        self.environment: dict[str, str] = {}

    def run(self, cmd: list[str], **kwargs):
        self.commands.append(cmd)
        assert kwargs["check"] is False and kwargs["capture_output"] is True
        assert 0 < kwargs["timeout"] <= 300
        self.environment = kwargs["env"]

        def result(code=0, out="", err=""):
            return subprocess.CompletedProcess(cmd, code, out, err)

        if cmd[:3] == ["docker", "image", "inspect"]:
            if cmd[3] == TEST_POSTGRES_IMAGE:
                return result(out=json.dumps([{
                    "Id": "sha256:" + "a" * 64, "Os": "linux", "Architecture": "amd64",
                    "RepoDigests": [TEST_POSTGRES_IMAGE],
                    "Config": {"Entrypoint": ["docker-entrypoint.sh"]},
                }]))
            assert self.installed
            return result(out=json.dumps([{"Id": "sha256:" + "b" * 64,
                "Os": "linux", "Architecture": "arm64" if self.failure == "architecture" else "amd64",
                "Config": {"Cmd": ["postgres"], "Entrypoint": ["docker-entrypoint.sh"],
                           "Labels": {IMAGE_OWNER_LABEL: "true", IMAGE_RECIPE_LABEL: compute_recipe_hash(),
                                      "org.repomap.test.profile": "pgvector"}}}]))
        if cmd[1] == "create" and "--user" in cmd:
            assert self.dependencies_removed
            assert cmd[cmd.index("--user") + 1] == "postgres"
            assert cmd[cmd.index("--network") + 1] == "none"
            assert "--pull=never" in cmd and "sha256:" + "b" * 64 in cmd
            assert "-p" not in cmd and "-v" not in cmd and "--mount" not in cmd
            assert "initdb" in cmd[-1] and "exec postgres" in cmd[-1]
            return result()
        if cmd[1] in {"create", "start", "stop"}:
            return result()
        if cmd[1] == "commit":
            assert self.installed and self.dependencies_removed
            return result(out="sha256:" + "b" * 64)
        if cmd[1] == "logs":
            return result(err="postgres backend diagnostic: " + self.failure)
        if cmd[1] == "rm":
            fail = (self.failure == "extraction_cleanup" or
                    (self.failure in {"load_cleanup", "runtime_cleanup"} and "runtime-" in cmd[-1]))
            return result(17, err="remove failed") if fail else result()
        if cmd[1] == "ps":
            fail = (self.failure == "extraction_cleanup" or
                    (self.failure in {"load_cleanup", "runtime_cleanup"} and any("runtime-" in part for part in cmd)))
            return result(out="remaining-container" if fail else "")
        assert cmd[1] == "exec", f"unexpected Docker operation: {cmd[1]}"
        if cmd[3] == "postgres":
            assert cmd[4].startswith("repomap-pgvector-runtime-")
            operation = cmd[5:]
            if operation[0] == "/bin/sh":
                assert kwargs["timeout"] == 45 and "pg_isready" in operation[-1]
                if self.failure == "startup_timeout":
                    raise subprocess.TimeoutExpired(cmd, 45, stderr="readiness deadline exceeded")
                return result()
            assert operation[:3] == ["psql", "-X", "-qAt"]
            assert "ON_ERROR_STOP=1" in operation and operation[-1] == RUNTIME_SMOKE_SQL
            errors = {"load": "could not load library", "load_cleanup": "undefined symbol: pfree",
                      "missing_dependency": "libmissing.so: No such file or directory",
                      "symbol": "undefined symbol: unknown_backend_symbol",
                      "abi": "incompatible library: version mismatch", "sql": "syntax error"}
            if self.failure in errors:
                return result(1, err="ERROR: " + errors[self.failure])
            outputs = {"version": "16|0.8.6|0|1", "major": "17|0.8.7|0|1", "missing": "",
                       "self": "16|0.8.7|0.5|1", "orthogonal": "16|0.8.7|0|0.9"}
            return result(out=outputs.get(self.failure, "16|0.8.7|0|1") + "\n")
        assert cmd[2:6] == ["--user", "0", "--workdir", "/tmp"]
        interactive = cmd[6] == "-i"
        container_index = 7 if interactive else 6
        assert cmd[container_index].startswith("repomap-pgvector-build-")
        operation = cmd[container_index + 1:]
        if operation[0] == "dd":
            assert interactive and "-t" not in cmd
            assert operation[1:] == ["of=/tmp/pgvector.tar.gz", "bs=65536"]
            assert kwargs["text"] is False and isinstance(kwargs["input"], bytes)
            if self.failure == "transfer":
                return result(32, b"partial write", b"write failed")
            # A real child consumes compressed bytes through stdin until EOF.
            transferred = subprocess.run(
                [sys.executable, "-c", "import sys; from pathlib import Path; "
                 "Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read())", str(self.archive)],
                input=kwargs["input"], capture_output=True, check=False, timeout=5,
            )
            if self.failure == "corrupt_transfer":
                self.archive.write_bytes(self.archive.read_bytes()[:-1])
            return transferred
        assert not interactive and kwargs["input"] is None
        if operation == ["postgres", "--version"]:
            return result(out="postgres (PostgreSQL) 16.14\n")
        if operation == ["/usr/local/bin/pg_config", "--version"]:
            return result(out="PostgreSQL 16.14\n")
        if operation[0] == "sha256sum":
            return result(out=hashlib.sha256(self.archive.read_bytes()).hexdigest() + "  /tmp/pgvector.tar.gz\n")
        if operation[:2] == ["wc", "-c"]:
            size = self.archive.stat().st_size + (1 if self.failure == "wrong_size" else 0)
            return result(out=f"{size} /tmp/pgvector.tar.gz\n")
        if operation[0] == "tar":
            assert operation == ["tar", "-xzf", "/tmp/pgvector.tar.gz", "-C", "/tmp"]
            if self.failure.startswith("extraction"):
                self.archive.unlink()
            return subprocess.run(["tar", "-xzf", str(self.archive), "-C", str(self.root)],
                                  capture_output=True, text=True, check=False, timeout=5)
        if operation[0] == "apk":
            assert operation[1] in {"add", "info", "del"}
            if operation[1] == "del":
                self.dependencies_removed = True
            return result(out="build-base-1.0" if operation[1] == "info" else "")
        if operation[0] == "make":
            assert (self.root / f"pgvector-{EXPECTED_VERSION}" / "binary.dat").is_file()
            if self.failure == "build":
                return result(39, err="compiler failed")
            if operation[-1] == "install":
                self.installed = True
            return result()
        if operation[0] == "ldd":
            return result(127, out="/lib/ld-musl-aarch64.so.1", err="pfree: symbol not found")
        if operation[0] in {"test", "rm"}:
            assert self.installed
            return result()
        raise AssertionError(f"unexpected builder operation: {operation}")


def materialize(source, builder: BuilderDouble, **kwargs):
    archive, _, _ = source
    environment = {"REPOMAP_PGVECTOR_ARCHIVE_PATH": str(archive)}
    return materializer._materialize_inner_pgvector_if_requested(
        ARGV, environment, runner_fn=builder.run, **kwargs)


def events(output: str):
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def test_verified_binary_snapshot_reaches_extractor_even_if_source_path_changes(
    source, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    archive, payload, facts = source
    builder = BuilderDouble(tmp_path)

    def verify_then_change_path(data: bytes, expected: dict[str, object]) -> None:
        materializer._verify_source_archive(data, expected)
        archive.write_bytes(b"changed after verification")

    report = materialize(source, builder, archive_verifier_fn=verify_then_change_path)
    assert report is not None and report["setup_cleanup"]["verified"]
    assert builder.archive.read_bytes() == payload
    assert (tmp_path / f"pgvector-{EXPECTED_VERSION}" / "binary.dat").read_bytes() == b"\x00\xff\xfe\x80\n\r\x00" * 40
    verified = [e for e in events(capsys.readouterr().out)
                if e.get("stage") == "archive_destination_verification" and e.get("verified")]
    assert verified[0]["archive_sha256"] == facts["archive_sha256"]
    assert verified[0]["archive_bytes"] == len(payload)
    assert all(cmd[1] != "cp" for cmd in builder.commands)
    assert report["image_built"] and report["server_loaded"] and report["smoke_passed"]
    assert report["resulting_engine_id"] == builder.environment["REPOMAP_TEST_PG_IMAGE"]
    assert not any("ldd" in cmd for cmd in builder.commands)


@pytest.mark.parametrize("failure", ["load", "missing_dependency", "symbol", "abi", "sql",
                                   "version", "major", "missing", "self", "orthogonal", "startup_timeout",
                                   "architecture", "load_cleanup", "runtime_cleanup"])
def test_final_image_runtime_failure_blocks_publication_and_preserves_diagnostics(
    source, tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: str,
) -> None:
    builder = BuilderDouble(tmp_path, failure)
    with pytest.raises(RuntimeError) as error:
        materialize(source, builder)
    assert "REPOMAP_TEST_PG_IMAGE" not in builder.environment
    assert any(cmd[1] == "commit" for cmd in builder.commands)
    evidence = events(capsys.readouterr().out)
    assert any(e.get("image_built") for e in evidence)
    assert not any(e.get("pgvector_setup") == "materialized" for e in evidence)
    if failure == "architecture":
        assert not any(cmd[1] == "logs" for cmd in builder.commands)
        assert "platform" in str(error.value)
    else:
        assert any(e.get("stage") == "runtime_server_diagnostics"
                   and failure in e.get("stderr", "") for e in evidence)
        assert any(e.get("stage") == "runtime_cleanup" for e in evidence)
    if failure == "load_cleanup":
        assert "undefined symbol: pfree" in str(error.value)
        assert "runtime diagnostics/cleanup also failed" in error.value.__notes__[0]


@pytest.mark.parametrize("failure", ["transfer", "corrupt_transfer", "wrong_size", "extraction", "extraction_cleanup", "build"])
def test_setup_failure_preserves_diagnostics_and_prevents_commit(
    source, tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: str,
) -> None:
    builder = BuilderDouble(tmp_path, failure)
    with pytest.raises(RuntimeError) as error:
        materialize(source, builder)
    if failure.startswith("extraction"):
        assert "archive_extraction" in str(error.value)
        assert "status=" in str(error.value) and "stderr=" in str(error.value)
    evidence = events(capsys.readouterr().out)
    assert any(e.get("stage") == "source_verification" and e["status"] == "completed" for e in evidence)
    assert any(e.get("postgres_abi") == "16" for e in evidence)
    assert not any(cmd[1] == "commit" for cmd in builder.commands)
    assert any(cmd[1] == "rm" for cmd in builder.commands)
    assert any(cmd[1] == "ps" for cmd in builder.commands)
    if failure != "build":
        assert not any("make" in cmd or "apk" in cmd for cmd in builder.commands)
    if failure in {"transfer", "corrupt_transfer", "wrong_size"}:
        assert not (tmp_path / f"pgvector-{EXPECTED_VERSION}" / "binary.dat").exists()
    if failure == "extraction_cleanup":
        assert any(e.get("stage") == "cleanup" and e["status"] == "failed" for e in evidence)
        assert evidence[-1]["stage"] == "archive_extraction"
        assert "cleanup failed" in error.value.__notes__[0]
    else:
        assert any(e.get("stage") == "cleanup" and e.get("verified") for e in evidence)


@pytest.mark.parametrize("failure", ["length", "digest", "metadata"])
def test_invalid_source_never_creates_builder(source, tmp_path: Path, failure: str) -> None:
    archive, payload, facts = source
    if failure == "length":
        archive.write_bytes(payload[:-1])
    elif failure == "digest":
        archive.write_bytes(b"x" + payload[1:])
    else:
        invalid = b"not a gzip archive"
        archive.write_bytes(invalid)
        facts.update(archive_bytes=len(invalid), archive_sha256=hashlib.sha256(invalid).hexdigest())
    builder = BuilderDouble(tmp_path)
    with pytest.raises((RuntimeError, tarfile.ReadError)):
        materialize(source, builder)
    assert [cmd[1] for cmd in builder.commands] == ["image"]


def test_core_never_acquires_or_builds_pgvector() -> None:
    with patch.object(materializer, "verify_pgvector_source_facts") as facts, \
         patch.object(materializer, "_resolve_cached_source_archive") as acquire, \
         patch.object(materializer.subprocess, "run") as command:
        assert materializer._materialize_inner_pgvector_if_requested(
            ["--suite", "int", "--no-coverage", "--", "test.py"], {}) is None
    facts.assert_not_called()
    acquire.assert_not_called()
    command.assert_not_called()


def test_setup_diagnostics_bound_redact_and_preserve_timeout(capsys: pytest.CaptureFixture[str]) -> None:
    token = "test-private-token"
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 300, output=b"out\xff", stderr=(
            token + " /Users/example/private/archive " + "x" * 5000).encode())
    setup = materializer._SetupCommands({"AUTH_TOKEN": token}, timeout)
    with pytest.raises(RuntimeError, match="archive_transfer: status=124"):
        setup.execute("archive_transfer", ["docker", "exec"], payload=b"\x00\xff")
    output = capsys.readouterr().out
    assert token not in output and "/Users/example" not in output
    event = events(output)[-1]
    assert event["returncode"] == 124 and event["output_truncated"]
    assert len(event["stderr"]) == 4096 and event["stderr_bytes"] > 4096


@pytest.mark.parametrize("cleanup_failed", [False, True])
@pytest.mark.parametrize("setup_error", ["archive_extraction failed", "runtime_smoke LOAD failed"])
def test_entrypoint_never_launches_tests_after_materializer_failure(cleanup_failed: bool, setup_error: str) -> None:
    daemon = MagicMock()
    daemon.poll.return_value = None
    if cleanup_failed:
        daemon.terminate.side_effect = OSError("daemon cleanup denied")
    with patch.object(entrypoint.subprocess, "Popen", return_value=daemon) as launch, \
         patch("pathlib.Path.exists", return_value=True), \
         patch.object(entrypoint, "_test_environment", return_value={}), \
         patch.object(entrypoint, "_materialize_inner_pgvector_if_requested",
                      side_effect=RuntimeError(setup_error)), \
         pytest.raises(RuntimeError, match=setup_error) as error:
        entrypoint.main(["--docker-group", "0", "--", *ARGV])
    assert launch.call_count == 1
    assert launch.call_args.args[0][0] == "dockerd"
    daemon.terminate.assert_called_once()
    if cleanup_failed:
        assert "cleanup also failed" in error.value.__notes__[0]
    else:
        daemon.wait.assert_called_once_with(timeout=5)
