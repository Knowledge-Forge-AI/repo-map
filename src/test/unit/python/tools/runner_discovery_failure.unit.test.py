"""Discovery retains the observed primary when cleanup or optional evidence fails."""
import errno
from pathlib import Path
from types import SimpleNamespace

import pytest
import runner_staging_discovery as discovery
from runner_failure_evidence import DISCOVERY_SCHEMA, read_diagnostic

REPO = Path(__file__).resolve().parents[5]


@pytest.mark.parametrize("fault", ["cleanup", "bad-child-record", "popen"])
def test_discovery_primary_survives_secondary_failures(tmp_path, monkeypatch, fault):
    script = tmp_path / "child.py"
    script.write_text("from pathlib import Path\nimport sys\n"
                      "Path(sys.argv[2]).with_name('child_error.json').write_text('{}')\n"
                      "raise SystemExit(17)\n" if fault == "bad-child-record" else "raise SystemExit(17)\n")
    settled = discovery.terminate_and_reap

    def fail_cleanup(process):
        settled(process)
        raise OSError(errno.EIO, "opaque-fixture")

    def fail_popen(*_args, **_kwargs):
        raise PermissionError(errno.EACCES, "opaque-fixture")

    if fault == "cleanup":
        monkeypatch.setattr(discovery, "terminate_and_reap", fail_cleanup)
    elif fault == "popen":
        monkeypatch.setattr(discovery.subprocess, "Popen", fail_popen)
    args = SimpleNamespace(suite="int", report_dir=tmp_path / "reports")
    expected = PermissionError if fault == "popen" else discovery.PopulationDiscoveryError
    with pytest.raises(expected):
        discovery.discover_staging_population(
            args, [], repo_root=REPO, source_root=REPO / "src/main/python",
            test_support_root=REPO / "src/test/support/python", invocation_id="secondary-failure",
            candidate_identity={"commit": "a" * 40, "source_sha256": "b" * 64},
            scoped=True, child_script_path=script,
        )
    path = args.report_dir / "int/latest/staging_discovery_diagnostic.secondary-failure.json"
    value = read_diagnostic(path, DISCOVERY_SCHEMA)
    assert value["primary"]["type"] == expected.__name__
    assert value["process_exit"] == (None if fault == "popen" else 17)
    assert value["child_error"] is None
    if fault != "popen":
        assert value["secondary"][0]["stage"] == (
            "discovery_cleanup" if fault == "cleanup" else "discovery_receipt")
    assert "opaque-fixture" not in path.read_text()
