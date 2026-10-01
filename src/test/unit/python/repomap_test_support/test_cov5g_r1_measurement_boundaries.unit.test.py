"""Pure doubles for connection arguments and missing backend evidence."""

from pathlib import Path
import sys
from unittest.mock import MagicMock

_TOOLS_DIR = Path(__file__).resolve().parents[5] / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from psycopg.conninfo import conninfo_to_dict
import pytest

from repomap_test_support import test_cov5g_r1_measurement as measurement
from repomap_test_support import test_cov5g_r1_process as process
from repomap_test_support.test_cov5g_r1_characterization import Condition


class _ConnectionIntercepted(Exception):
    pass


@pytest.mark.parametrize("configured", [False, True])
def test_optional_connection_values_keep_libpq_semantics(
    monkeypatch: pytest.MonkeyPatch, configured: bool,
) -> None:
    captured: list[str] = []

    def connect(conninfo: str, *, autocommit: bool) -> None:
        assert autocommit is True
        captured.append(conninfo)
        raise _ConnectionIntercepted

    monkeypatch.setattr(measurement.psycopg, "connect", connect)
    parameters: dict[str, object] = {"dbname": "public_fixture", "port": 5432, "password": None}
    with pytest.raises(_ConnectionIntercepted):
        if configured:
            measurement.run_configured_observation(
                parameters, MagicMock(), cohort="fixture", case_number=1,
            )
        else:
            measurement.run_direct_observation(
                parameters, MagicMock(), cohort="fixture", case_number=1,
                condition=next(iter(Condition)),
            )
    assert len(captured) == 1
    parsed = conninfo_to_dict(captured[0])
    assert parsed["dbname"] == "public_fixture"
    assert parsed["port"] == "5432"
    assert "password" not in parsed


@pytest.mark.parametrize("row", [None, (0,), (2,)])
def test_missing_backend_row_is_not_zero_evidence(row: tuple[int] | None) -> None:
    admin = MagicMock()
    admin.execute.return_value.fetchone.return_value = row
    if row is None:
        with pytest.raises(RuntimeError, match="backend count"):
            process.backend_count(admin, "public_fixture")
    else:
        assert process.backend_count(admin, "public_fixture") == row[0]
    admin.execute.assert_called_once()


def test_scoped_environment_isolates_and_restores_cleanly() -> None:
    import os

    os.environ["TEST_SCOPED_ORIGINAL"] = "original_val"
    os.environ.pop("TEST_SCOPED_NEW", None)
    os.environ.pop("TEST_SCOPED_INTERNAL", None)

    try:
        target = {"TEST_SCOPED_ORIGINAL": "modified_val", "TEST_SCOPED_NEW": "added_val"}
        with process._scoped_environment(target):
            assert os.environ.get("TEST_SCOPED_ORIGINAL") == "modified_val"
            assert os.environ.get("TEST_SCOPED_NEW") == "added_val"
            os.environ["TEST_SCOPED_INTERNAL"] = "leak_attempt"

        assert os.environ.get("TEST_SCOPED_ORIGINAL") == "original_val"
        assert "TEST_SCOPED_NEW" not in os.environ
        assert "TEST_SCOPED_INTERNAL" not in os.environ
    finally:
        os.environ.pop("TEST_SCOPED_ORIGINAL", None)
        os.environ.pop("TEST_SCOPED_NEW", None)
        os.environ.pop("TEST_SCOPED_INTERNAL", None)


def test_scoped_environment_restores_on_exception() -> None:
    import os

    os.environ["TEST_SCOPED_ERR"] = "before"
    try:
        with pytest.raises(ValueError, match="boom"):
            with process._scoped_environment({"TEST_SCOPED_ERR": "during"}):
                assert os.environ.get("TEST_SCOPED_ERR") == "during"
                raise ValueError("boom")
        assert os.environ.get("TEST_SCOPED_ERR") == "before"
    finally:
        os.environ.pop("TEST_SCOPED_ERR", None)


def test_cov5g_cooperative_construction_order_under_child_coverage_session_emits_no_unregistered_shard(
    tmp_path: Path,
) -> None:
    import multiprocessing
    import os
    import sys
    from pathlib import Path
    import coverage

    tools_dir = Path(__file__).resolve().parents[5] / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    from runner_coverage import ChildCoverageSession
    from runner_coverage_execution import prepare_child_coverage_environment

    session = ChildCoverageSession(
        coverage_module=coverage,
        scratch_dir=tmp_path / "measure",
        source_root=Path(__file__).resolve().parents[5],
        suite="staging",
    )
    with session:
        assert "COVERAGE_PROCESS_START" in os.environ
        target_env = prepare_child_coverage_environment(family="unmeasured")
        with process._scoped_environment(target_env):
            context = multiprocessing.get_context("spawn")
            parent_channel, child_channel = context.Pipe(duplex=True)
            stop = context.Event()
            p = context.Process(
                target=process._cooperative_worker_target,
                args=(child_channel, stop),
                name="cov5g-cooperative-test-worker",
            )
            p.start()
        child_channel.close()
        ready = parent_channel.recv() == "ready"
        assert ready is True
        p.join(timeout=3.0)
        parent_channel.close()
        shards = list(session.data_dir.glob(".coverage*"))
        assert shards == []

    assert session.combine() is None
