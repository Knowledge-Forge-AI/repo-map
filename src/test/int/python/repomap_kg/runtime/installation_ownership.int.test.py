"""Real metadata files and CLI transport, without installing or importing their packages."""
from importlib import metadata
import json
from pathlib import Path

import pytest

from repomap_test_support.sqlite_local_harness import LocalHarness


@pytest.mark.parametrize(("names", "state"), [
    ([], "unverified"), (["common_lore_index"], "single-owner"),
    (["repomap_kg"], "owner-mismatch"),
    (["common_lore_index", "common_lore_index"], "conflicting"),
    (["common_lore_index", "repomap.kg"], "conflicting"),
])
def test_real_dist_info_discovery_is_read_only_and_categorical(tmp_path: Path, names, state):
    from common_lore_index.runtime.installation_ownership import inspect_installation_ownership
    for index, name in enumerate(names):
        info = tmp_path / f"{name}-{index}.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 0.0.3\n")
        (info / "entry_points.txt").write_text("[console_scripts]\nprobe = forbidden_module:run\n")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = inspect_installation_ownership(finder=lambda name: metadata.distributions(name=name, path=[str(tmp_path)]))
    assert result.state == state
    assert {p: p.read_bytes() for p in before} == before
    assert str(tmp_path) not in json.dumps(result.as_dict()) and "forbidden_module" not in json.dumps(result.as_dict())


def test_real_cli_diagnostic_is_driver_free_and_does_not_inspect_homes(tmp_path: Path):
    harness = LocalHarness(tmp_path / "guarded", block_psycopg=True)
    foreign = harness.user_home / ".cloe"
    foreign.mkdir()
    sentinel = foreign / "foreign.txt"
    sentinel.write_text("opaque private sentinel")
    result = harness.run("identity", "--installation-check", "--json")
    assert result.returncode in (0, 1), result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == "cloe-installation-ownership-v1" and payload["metadata_only"]
    assert payload["state"] in ("single-owner", "conflicting", "owner-mismatch", "unverified")
    assert result.returncode == (0 if payload["state"] == "single-owner" else 1)
    assert not result.stderr and sentinel.read_text() == "opaque private sentinel"
    assert "opaque private sentinel" not in result.stdout and str(harness.user_home) not in result.stdout
    ordinary = harness.run("identity", "--json")
    assert ordinary.returncode == 0 and len(json.loads(ordinary.stdout)) == 6
    assert not harness.forbidden_events() and not harness.shim_invocations()
