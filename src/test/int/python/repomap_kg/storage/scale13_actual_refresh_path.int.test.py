from __future__ import annotations
from pathlib import Path
import psycopg
from psycopg.conninfo import make_conninfo
import pytest
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staging_family_contracts import (
    STAGING_FAMILY_DESCRIPTORS,
)
from repomap_kg.storage.staging_operation_contracts import (
    STAGING_OPERATION_DESCRIPTORS,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from scale13_actual_path_readback import read_actual_path_state
from scale13_gate_a_contracts import (
    validate_gate_a_backend_summary,
    validate_gate_a_resource_sample,
)

from src.test.int.python.repomap_kg.storage.scale13_actual_refresh_path_fixtures import (
    _assert_bounded_lifecycle_gaps,
    _fixture_digest,
    _required_row,
    _validate_lifecycle_frames,
    _write_config,
    _write_fixture,
)
from src.test.int.python.repomap_kg.storage.scale13_actual_refresh_path_runners import (
    _run_instrumented_refresh,
    _run_owned_resource_refresh,
    _run_uninstrumented_refresh,
)

def test_actual_configured_refresh_emits_all_pre_final_and_final_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        graph_postgres = postgres.create_database("scale13_public_fixture")
        apply_migrations(
            default_rdbms_root(),
            graph_postgres.psql_args,
            psql_command=graph_postgres.psql_command,
        )
        root = tmp_path / "repository"
        home = tmp_path / "home"
        _write_fixture(root)
        _write_config(home, root, graph_postgres)
        monkeypatch.setenv(
            "REPOMAP_SCALE13_UNUSED_PASSWORD",
            graph_postgres.password,
        )
        return_code, frames, signal_count = _run_instrumented_refresh(
            home,
            graph_postgres,
        )

        phase_codes = [
            frame.payload["phase_code"]
            for frame in frames
            if frame.category == "phase"
            and frame.payload["event_category"] == "started"
        ]
        operation_codes = [
            frame.payload["operation_code"]
            for frame in frames
            if frame.category == "operation"
            and frame.payload["event_category"] == "started"
        ]
        expected_operations = [
            code for code in STAGING_OPERATION_DESCRIPTORS if code != "cleanup.stage"
        ]

        assert return_code == 0
        assert signal_count == 0
        _validate_lifecycle_frames(frames)
        _assert_bounded_lifecycle_gaps(frames)
        expected_phases = [
            "refresh.total",
            *(f"staging.family_copy.{family}" for family in STAGING_FAMILY_DESCRIPTORS),
            "staging.pre_final_commit",
        ]
        assert phase_codes == expected_phases
        assert operation_codes == expected_operations
        assert all("legacy" not in code for code in phase_codes + operation_codes)


def test_actual_configured_refresh_instrumentation_is_semantically_transparent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        graph_postgres = postgres.create_database("scale13_parity")
        apply_migrations(
            default_rdbms_root(),
            graph_postgres.psql_args,
            psql_command=graph_postgres.psql_command,
        )
        root = tmp_path / "repository"
        home = tmp_path / "home"
        _write_fixture(root)
        _write_config(home, root, graph_postgres)
        monkeypatch.setenv(
            "REPOMAP_SCALE13_UNUSED_PASSWORD",
            graph_postgres.password,
        )

        instrumented_code, _frames, _signals = _run_instrumented_refresh(
            home,
            graph_postgres,
        )
        assert instrumented_code == 0
        instrumented = read_actual_path_state(graph_postgres.psql_args)
        uninstrumented_code = _run_uninstrumented_refresh(home, graph_postgres)
        assert uninstrumented_code == 0
        uninstrumented = read_actual_path_state(graph_postgres.psql_args)

    _validate_lifecycle_frames(_frames)
    assert instrumented["receipt_complete"] is True
    assert instrumented["cleanup_complete"] is True
    assert instrumented["backend_quiescent"] is True
    assert uninstrumented["receipt_complete"] is True
    assert uninstrumented["cleanup_complete"] is True
    assert uninstrumented["backend_quiescent"] is True
    assert instrumented["generations"] == uninstrumented["generations"]
    assert instrumented["family_counts"] == uninstrumented["family_counts"]
    assert instrumented["structural_digest"] == uninstrumented[
        "structural_digest"
    ]


def test_actual_configured_refresh_proves_backend_ownership_and_live_readers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    require_postgres_binaries()
    postgres_context = temporary_postgres()
    with postgres_context as postgres:
        graph_postgres = postgres.create_database("scale13_owned_resources")
        apply_migrations(
            default_rdbms_root(),
            graph_postgres.psql_args,
            psql_command=graph_postgres.psql_command,
        )
        root = tmp_path / "repository"
        home = tmp_path / "home"
        _write_fixture(root)
        _write_config(home, root, graph_postgres)
        monkeypatch.setenv(
            "REPOMAP_SCALE13_UNUSED_PASSWORD",
            graph_postgres.password,
        )
        session = postgres_context.session

        return_code, frames, samples, summaries, errors = (
            _run_owned_resource_refresh(
                home,
                graph_postgres,
                runtime=session.config.runtime,
                container_name=session.harness.container_name,
            )
        )
        assert return_code == 0, {"role": "scale13_actual_refresh_child", "phase": "owned_resource_refresh", "return_code": return_code}
        assert errors == []
        state = read_actual_path_state(graph_postgres.psql_args)

    owned_summaries = [
        summary for summary in summaries if summary.get("direct_owned_client") == 1
    ]
    validate_gate_a_backend_summary(summaries[0], require_owned=False)
    assert owned_summaries
    for summary in owned_summaries:
        validate_gate_a_backend_summary(summary, require_owned=True)
    assert samples
    for sample in samples:
        validate_gate_a_resource_sample(sample)
    assert any(frame.category == "phase" for frame in frames)
    assert any(frame.category == "operation" for frame in frames)
    _validate_lifecycle_frames(frames)
    assert state["receipt_complete"] is True
    assert state["backend_quiescent"] is True


@pytest.mark.parametrize(
    "cancel_code",
    (
        "staging.family_copy.files",
        "guard.source_index_stage",
    ),
)
def test_actual_configured_refresh_cancels_without_partial_publication(
    tmp_path: Path,
    monkeypatch,
    cancel_code: str,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        graph_postgres = postgres.create_database(
            "scale13_cancel_" + cancel_code.rsplit(".", 1)[-1]
        )
        apply_migrations(
            default_rdbms_root(),
            graph_postgres.psql_args,
            psql_command=graph_postgres.psql_command,
        )
        root = tmp_path / "repository"
        home = tmp_path / "home"
        _write_fixture(root)
        source_digest = _fixture_digest(root)
        _write_config(home, root, graph_postgres)
        monkeypatch.setenv(
            "REPOMAP_SCALE13_UNUSED_PASSWORD",
            graph_postgres.password,
        )

        return_code, frames, signal_count = _run_instrumented_refresh(
            home,
            graph_postgres,
            cancel_code=cancel_code,
        )
        started_codes = {
            frame.payload.get("phase_code") or frame.payload.get("operation_code")
            for frame in frames
            if frame.payload.get("event_category") == "started"
        }
        assert cancel_code in started_codes, {
            "role": "scale13_actual_refresh_child", "phase": "cancellation",
            "expected_started": cancel_code, "observed_started_count": len(started_codes),
            "return_code": return_code, "signal_count": signal_count,
        }
        assert return_code != 0
        assert signal_count == 1
        params = _psycopg_connection_params_from_psql_args(
            graph_postgres.psql_args
        )
        with psycopg.connect(make_conninfo(**params)) as connection:
            complete_receipts = _required_row(connection.execute(
                "SELECT count(*) FROM runs WHERE status = 'complete'"
            ))[0]
            final_rows = _required_row(connection.execute(
                "SELECT count(*) FROM files"
            ))[0]
            stage_state = connection.execute(
                "SELECT state, merge_status, publication_reconciliation_state "
                "FROM ingestion_stages"
            ).fetchone()
            other_backends = _required_row(connection.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            ))[0]
        final_source_digest = _fixture_digest(root)

    try:
        _validate_lifecycle_frames(frames)
    except Exception as error:
        tail = tuple(
            (
                frame.category,
                frame.payload.get("event_category"),
                frame.payload.get("phase_code")
                or frame.payload.get("operation_code"),
            )
            for frame in frames[-8:]
        )
        raise AssertionError(
            f"{error}; return_code={return_code}; frame_count={len(frames)}; "
            f"tail={tail!r}"
        ) from error
    assert any(
        frame.payload.get("event_category") == "cancelled"
        for frame in frames
    )
    assert complete_receipts == 0
    assert final_rows == 0
    assert stage_state == ("failed", "rolled_back", "reconciled")
    assert other_backends == 0
    assert final_source_digest == source_digest
