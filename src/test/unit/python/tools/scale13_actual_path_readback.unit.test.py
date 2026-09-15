"""Missing readback rows must not become successful terminal evidence."""

from unittest.mock import MagicMock

import pytest

import scale13_actual_path_readback as readback


@pytest.mark.parametrize("missing", ["repository", "run", "backends", None])
def test_readback_requires_each_row_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch, missing: str | None,
) -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    rows: list[tuple[object, ...] | None] = [
        None if missing == "repository" else (7,),
        None if missing == "run" else (9, "complete", "s", "c", "e", "k"),
        None if missing == "backends" else (0,),
    ]
    connection.execute.return_value.fetchone.side_effect = rows
    connection.execute.return_value.fetchall.return_value = []
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(readback.psycopg, "connect", connect)
    counts = {family: 0 for family in readback.FINAL_FAMILY_CODES}
    digest = MagicMock(return_value=(counts, "a" * 64))
    monkeypatch.setattr(readback, "read_semantic_digest", digest)

    if missing is None:
        result = readback.read_actual_path_state(["-d", "public_fixture"])
        assert result["backend_quiescent"] is True
        assert result["receipt_complete"] is True
    else:
        with pytest.raises(readback.Scale13ReadbackError) as exc_info:
            readback.read_actual_path_state(["-d", "public_fixture"])
        evidence = exc_info.value.structural_evidence()
        assert evidence["role"] == "scale13_actual_path_readback"
        assert evidence["phase"] == f"readback_{missing if missing != 'backends' else 'backend'}"
        assert evidence["expected"] is not None
        assert evidence["observed"] is not None
    connect.assert_called_once_with(host=None, port=None, user=None, dbname="public_fixture")
    connection.__exit__.assert_called_once()
    if missing in ("repository", "run"):
        digest.assert_not_called()
    else:
        digest.assert_called_once_with(connection, 7, 9)


def test_scale13_readback_error_fields() -> None:
    err = readback.Scale13ReadbackError(
        "missing row",
        role="custom_role",
        phase="custom_phase",
        return_classification="exit_1",
        expected="row",
        observed="none",
    )
    assert err.structural_evidence() == {
        "role": "custom_role",
        "phase": "custom_phase",
        "return_classification": "exit_1",
        "expected": "row",
        "observed": "none",
    }
