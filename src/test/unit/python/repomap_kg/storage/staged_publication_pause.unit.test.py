"""The system interruption checkpoint preserves a real final-transaction handoff."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from repomap_kg.coordinator import _refresh_execution
from repomap_kg.runtime import system_test_pause as pause_window
from repomap_kg.storage import _staged_publication_pause as pause
from src.test.unit.python.repomap_kg.storage.scale8_staged_helpers_fixtures import _handoff


def test_validated_checkpoint_carries_exact_stage_run_and_receipt(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    trigger = tmp_path / "pause"
    trigger.touch()
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_STAGED_PAUSE_PATH", str(trigger))
    observed = []

    def resume(_duration):
        ready = Path(f"{trigger}.ready")
        observed.append(ready.read_text())
        trigger.unlink()

    monkeypatch.setattr(pause.time, "sleep", resume)
    handoff = _handoff()
    pause._run_system_test_publication_pause(handoff)
    values = dict(line.split("=", 1) for line in observed[0].splitlines())
    assert values["job_id"] == handoff.receipt.attempt.job_id
    assert int(values["attempt"]) == handoff.merge.owner.attempt
    assert json.loads(values["handoff"]) == {
        "repository_id": handoff.merge.owner.repository_id,
        "stage_id": handoff.merge.stage_id,
        "run_id": handoff.merge.run_id,
        "receipt": handoff.receipt.to_mapping(),
    }
    assert not Path(f"{trigger}.ready").exists()


def test_checkpoint_hook_is_disabled_and_rejects_marker_symlink(tmp_path, monkeypatch):
    monkeypatch.delenv("_REPOMAP_SYSTEM_TEST_STAGED_PAUSE_PATH", raising=False)
    pause._run_system_test_publication_pause(_handoff())
    tmp_path.chmod(0o700)
    trigger = tmp_path / "pause"
    victim = tmp_path / "victim"
    victim.write_text("preserved")
    Path(f"{trigger}.ready").symlink_to(victim)
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_STAGED_PAUSE_PATH", str(trigger))
    pause._run_system_test_publication_pause(_handoff())
    assert victim.read_text() == "preserved"


@pytest.mark.parametrize("producer", ["staged", "coordinator"])
def test_producers_use_the_shared_configured_pause_window(
    producer: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    trigger = tmp_path / "pause"
    trigger.touch()
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_STAGED_PAUSE_PATH", str(trigger))
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_PAUSE_PATH", str(trigger))
    monkeypatch.setattr(pause_window, "SYSTEM_TEST_PRODUCER_PAUSE_SECONDS", 120.0)
    pause_window.validate_pause_window_contract()
    elapsed = 0.0

    def advance(_duration: float) -> None:
        nonlocal elapsed
        assert Path(f"{trigger}.ready").is_file()
        elapsed += 10.0

    monkeypatch.setattr(pause.time, "monotonic", lambda: elapsed)
    monkeypatch.setattr(pause.time, "sleep", advance)
    if producer == "staged":
        pause._run_system_test_publication_pause(_handoff())
    else:
        _refresh_execution._run_system_test_pause(SimpleNamespace(job_id="job-1", attempt=1))
    assert elapsed == pause_window.SYSTEM_TEST_PRODUCER_PAUSE_SECONDS
    assert not Path(f"{trigger}.ready").exists()


def test_staged_producer_refuses_incompatible_window_before_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    trigger = tmp_path / "pause"
    trigger.touch()
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_STAGED_PAUSE_PATH", str(trigger))
    monkeypatch.setattr(pause_window, "SYSTEM_TEST_PRODUCER_PAUSE_SECONDS", 1.0)
    with pytest.raises(ValueError, match="Total window budget"):
        pause._run_system_test_publication_pause(_handoff())
    assert not Path(f"{trigger}.ready").exists()
