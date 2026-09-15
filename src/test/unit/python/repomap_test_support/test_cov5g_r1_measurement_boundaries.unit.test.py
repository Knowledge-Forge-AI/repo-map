"""Pure doubles for connection arguments and missing backend evidence."""

from unittest.mock import MagicMock

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
