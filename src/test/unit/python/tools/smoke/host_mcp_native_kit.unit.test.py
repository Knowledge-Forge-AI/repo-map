"""PREPARE1/PREPARE2 evidence redaction and operator-kit contracts for the host MCP native runner."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from smoke import host_mcp_native as cli
from smoke.host_mcp_native_evidence import ATTESTS, EvidenceWriter, deterministic_zip
from smoke.host_mcp_native_kit import (
    FIXTURE_INPUTS, KIT_DIR, KIT_ZIP, MANIFEST, build_kit, compare_checkout, import_closure, operator_command,
    verify_kit,
)
from smoke.host_mcp_native_run import RunInterrupted

REPO = Path(__file__).resolve().parents[6]
SECRET, ENV_SECRET = "fixture-admin-secret-0123", "read-status-secret-4567"


@pytest.fixture(scope="module")
def kit(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    out = tmp_path_factory.mktemp("kit out")
    receipt = build_kit(REPO, out)
    return out, receipt


def _extract(zip_path: Path, destination: Path) -> Path:
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(destination)
        for info in archive.infolist():
            (destination / info.filename).chmod((info.external_attr >> 16) & 0o777)
    return destination / KIT_DIR


def test_redaction_records_both_hash_domains_and_the_receipt_attests_delivery_only(tmp_path: Path) -> None:
    writer = EvidenceWriter(tmp_path / "PHASE" / "run-1", run_id="run-1", phase="PHASE")
    env_file = tmp_path / ".env"
    env_file.write_text(f"# comment\nREPOMAP_READ_STATUS_PASSWORD={ENV_SECRET}\nSHORT=abc\n", encoding="utf-8")
    writer.add_secret(SECRET)
    assert writer.add_env_file_secrets(env_file) == 1
    original = f"dsn password={SECRET} and {SECRET}; read {ENV_SECRET}\n"
    writer.write_text("session.txt", original)
    writer.write_json("clean.json", {"ok": True})
    receipt = writer.finalize(outcome="completed_pending_manager_review", exit_code=0,
                              qualification_class="linux-harness-exercise", summary={"note": f"x {SECRET}"})
    data = (writer.run_dir / "evidence.zip").read_bytes()
    assert receipt["zip"]["sha256"] == hashlib.sha256(data).hexdigest() and receipt["attests"] == ATTESTS
    assert json.loads((writer.run_dir / "receipt.json").read_text()) == receipt
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    assert not any(secret.encode() in blob for blob in members.values() for secret in (SECRET, ENV_SECRET))
    manifest = json.loads(members["run-1/MANIFEST.json"])
    entry = manifest["members"]["session.txt"]
    assert entry["redactions"] == 3 and entry["original_sha256"] == hashlib.sha256(original.encode()).hexdigest()
    assert entry["recorded_sha256"] == hashlib.sha256(members["run-1/session.txt"]).hexdigest()
    assert "original_sha256" not in manifest["members"]["clean.json"]
    with pytest.raises(RuntimeError):
        writer.finalize(outcome="x", exit_code=0, qualification_class="x", summary={})


def test_zip_bytes_are_deterministic() -> None:
    files = {"b.txt": (b"b", 0o644), "a/run.sh": (b"#!/bin/sh\n", 0o755)}
    assert deterministic_zip(files) == deterministic_zip(dict(reversed(files.items())))
    with zipfile.ZipFile(io.BytesIO(deterministic_zip(files))) as archive:
        assert archive.namelist() == ["a/run.sh", "b.txt"]
        assert (archive.getinfo("a/run.sh").external_attr >> 16) & 0o777 == 0o755


def test_kit_closure_ships_runner_helpers_and_fixture_inputs(kit: tuple[Path, dict], tmp_path: Path) -> None:
    out, receipt = kit
    closure = import_closure(REPO)
    for required in ("tools/host_mcp_native_qualify.py", "tools/smoke/host_mcp_native_run.py",
                     "tools/smoke/host_mcp_native_scenario.py",
                     "src/test/support/python/repomap_test_support/cli_in_process.py",
                     "src/test/support/python/repomap_test_support/postgres_container.py"):
        assert required in closure, required
    assert not any(path.startswith("src/main/") for path in closure)
    root = _extract(out / KIT_ZIP, tmp_path / "extract here")
    assert receipt["sha256"] == hashlib.sha256((out / KIT_ZIP).read_bytes()).hexdigest()
    for relative in (*FIXTURE_INPUTS, "run.sh", "README.md", MANIFEST):
        assert (root / relative).is_file(), relative
    assert (root / "run.sh").stat().st_mode & 0o777 == 0o755
    ok, detail = verify_kit(root)
    assert ok and detail["mismatched"] == []
    manifest = json.loads((root / MANIFEST).read_text())
    assert manifest["product"] and all(path.startswith(("src/main/", "pyproject")) for path in manifest["product"])
    assert compare_checkout(root, REPO) == []
    (root / "tools" / "smoke" / "host_mcp_native.py").write_text("# tampered\n", encoding="utf-8")
    assert verify_kit(root)[1]["mismatched"] == ["tools/smoke/host_mcp_native.py"]
    assert compare_checkout(root, REPO) == ["checkout differs from kit: tools/smoke/host_mcp_native.py"]
    with pytest.raises(FileExistsError):
        build_kit(REPO, out)


def test_kit_parent_imports_resolve_inside_the_kit(kit: tuple[Path, dict], tmp_path: Path) -> None:
    root = _extract(kit[0] / KIT_ZIP, tmp_path)
    probe = ("import sys; sys.path[:0] = [sys.argv[1] + '/tools', sys.argv[1] + '/src/test/support/python']\n"
             "import smoke.host_mcp_native, smoke.host_mcp_native_scenario\n"
             "bad = [n for n, m in sys.modules.items() if n.startswith(('smoke', 'repomap_test_support', 'runner_'))"
             " and getattr(m, '__file__', None) and not m.__file__.startswith(sys.argv[1])]\n"
             "print(bad)")
    completed = subprocess.run([sys.executable, "-I", "-B", "-c", probe, str(root)], capture_output=True, text=True,
                               timeout=120, check=False)
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert completed.stdout.strip() == "[]"


def test_extracted_kit_check_from_a_spaced_folder_is_not_run_with_a_receipt(
        kit: tuple[Path, dict], tmp_path: Path) -> None:
    root = _extract(kit[0] / KIT_ZIP, tmp_path / "Downloads copy")
    checkout = tmp_path / "fake checkout"
    (checkout / ".venv" / "bin").mkdir(parents=True)
    (checkout / ".venv" / "bin" / "python").symlink_to(sys.executable)
    outbox = tmp_path / "out box"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("PG", "REPOMAP_"))}
    completed = subprocess.run(["sh", str(root / "run.sh"), "--check", "--checkout", str(checkout),
                                "--outbox-root", str(outbox)], capture_output=True, text=True, timeout=300,
                               check=False, env=env, cwd=tmp_path)
    assert completed.returncode == 2, completed.stderr[-2000:]
    receipts = list(outbox.rglob("receipt.json"))
    assert len(receipts) == 1 and json.loads(receipts[0].read_text())["outcome"] == "not_run"
    with zipfile.ZipFile(receipts[0].with_name("evidence.zip")) as archive:
        name = next(n for n in archive.namelist() if n.endswith("prerequisites.json"))
        items = {item["name"]: item for item in json.loads(archive.read(name))["items"]}
    assert items["kit"]["status"] == "ok" and items["console-present"]["status"] == "refused"
    assert items["docker"]["status"] == "skipped"


def test_missing_checkout_interpreter_is_a_shell_level_refusal_without_a_receipt(
        kit: tuple[Path, dict], tmp_path: Path) -> None:
    root = _extract(kit[0] / KIT_ZIP, tmp_path)
    outbox = tmp_path / "outbox"
    completed = subprocess.run(["sh", str(root / "run.sh"), "--check", "--checkout", str(tmp_path / "none"),
                                "--outbox-root", str(outbox)], capture_output=True, text=True, timeout=60,
                               check=False)
    assert completed.returncode == 2 and "NOT RUN: checkout interpreter is missing" in completed.stderr
    assert not outbox.exists()
    missing = subprocess.run(["sh", str(root / "run.sh"), "--check"], capture_output=True, text=True, timeout=60,
                             check=False)
    assert missing.returncode == 2 and "--checkout PATH is required" in missing.stderr


def test_operator_command_verifies_the_exact_delivered_kit_and_checks_before_executing() -> None:
    delivery = Path.home() / "Documents" / "agent" / "outbox" / "repo-map_dev" / "PHASE X"
    command = operator_command("f" * 64, delivery)
    assert f"kit_sha={'f' * 64}" in command and "shasum -a 256" in command and "ditto -x -k" in command
    assert f'zip="$HOME/Documents/agent/outbox/repo-map_dev/PHASE X"/{KIT_ZIP}' in command
    assert "inbox" not in command and "Downloads" not in command and "for candidate" not in command
    assert command.count('--checkout "$HOME/projs/repo-map_dev"') == 2
    assert command.index("--check ") < command.index("--execute") and "set -eu" in command
    assert "mktemp -d" in command and "--repo-map-home" not in command
    assert "zip='/opt/kit $dir'/" in operator_command("0" * 64, Path("/opt/kit $dir"))


def test_early_ownership_member_is_on_disk_private_exclusive_and_hash_labelled(tmp_path: Path) -> None:
    writer = EvidenceWriter(tmp_path / "PHASE" / "run-1", run_id="run-1", phase="PHASE")
    writer.add_secret(SECRET)
    with pytest.raises(ValueError, match="registered secret"):
        writer.write_early_json("LEAK.json", {"password": SECRET})
    assert not (writer.run_dir / "LEAK.json").exists()
    path = writer.write_early_json("OWNER.json", {"run_id": "run-1", "home": "/w/late-registered-value"})
    early = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600 and json.loads(early)["run_id"] == "run-1"
    with pytest.raises(FileExistsError):
        writer.write_early_json("OWNER.json", {"run_id": "again"})
    writer.add_secret("late-registered-value")  # a later secret redacts the member, never the early file
    writer.finalize(outcome="failed", exit_code=1, qualification_class="linux-harness-exercise", summary={})
    with zipfile.ZipFile(writer.run_dir / "evidence.zip") as archive:
        member = archive.read("run-1/OWNER.json")
        manifest = json.loads(archive.read("run-1/MANIFEST.json"))
    entry = manifest["members"]["OWNER.json"]
    assert member == early.replace(b"late-registered-value", b"[REDACTED]") and path.read_bytes() == early
    assert entry["early_file_sha256"] == entry["original_sha256"] == hashlib.sha256(early).hexdigest()
    assert entry["recorded_sha256"] == hashlib.sha256(member).hexdigest() != entry["early_file_sha256"]
    assert "early_file_sha256" in manifest["hash_domains"]
    with pytest.raises(RuntimeError):
        writer.write_early_json("LATE.json", {})


def test_a_finished_run_directory_is_never_reused(tmp_path: Path) -> None:
    EvidenceWriter(tmp_path / "run", run_id="r", phase="P")
    with pytest.raises(FileExistsError):
        EvidenceWriter(tmp_path / "run", run_id="r", phase="P")
    assert RunInterrupted.__mro__[1] is BaseException


def test_build_kit_refuses_inside_an_extracted_kit(tmp_path: Path) -> None:
    (tmp_path / "KIT-MANIFEST.json").write_text("{}", encoding="utf-8")
    assert cli.main(["--build-kit", str(tmp_path / "out")], kit_root=tmp_path) == 2
    assert not (tmp_path / "out").exists()
