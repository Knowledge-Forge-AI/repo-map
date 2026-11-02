"""End-to-end CLI integration tests for cloe ops context-select and cloe ops context-pack."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from common_lore_index.cli.main import main
from repomap_test_support.context_assertions import (
    assert_valid_budget_error,
    assert_valid_context_packet,
    build_postgres_context_fixture,
)
from repomap_test_support.context_fixture import (
    BINDING_CORE,
    BINDING_DOCS,
    CTX_GRAPH_ID,
    build_sqlite_context_fixture,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _invoke_cli(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> tuple[int, bytes, str]:
    out_buf = io.BytesIO()
    err_buf = io.StringIO()

    class _StdOutWrapper:
        def __init__(self, b: io.BytesIO) -> None:
            self.buffer = b

        def write(self, s: str) -> int:
            return self.buffer.write(s.encode("utf-8"))

        def flush(self) -> None:
            pass

    monkeypatch.setattr("sys.stdout", _StdOutWrapper(out_buf))
    monkeypatch.setattr("sys.stderr", err_buf)
    try:
        rc = main(argv)
    except SystemExit as exc:
        rc = int(exc.code) if isinstance(exc.code, int) else 1
    return rc, out_buf.getvalue(), err_buf.getvalue()


def test_cli_context_select_and_pack_over_sqlite_and_postgres_homes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify cloe ops context-select and context-pack across SQLite Local and PostgreSQL homes."""
    require_postgres_binaries()
    sq_dir = tmp_path / "sqlite_home"
    sq_dir.mkdir(parents=True, exist_ok=True)
    build_sqlite_context_fixture(sq_dir)

    sq_sel = tmp_path / "sq_sel.json"
    rc_sel, raw_sel, err_sel = _invoke_cli(
        [
            "ops",
            "context-select",
            "--repo-map-home",
            str(sq_dir),
            "--graph",
            CTX_GRAPH_ID,
            "--binding",
            BINDING_CORE,
            "--path-prefix",
            f"{BINDING_CORE}=src",
            "--pin-publication",
            "--output",
            str(sq_sel),
        ],
        monkeypatch,
    )
    assert rc_sel == 0, err_sel
    sel_doc = json.loads(raw_sel.decode("utf-8"))
    assert sel_doc["schema"] == "cloe-source-selection-v1"
    assert sel_doc["backend"] == "sqlite"

    # Scoped docs intent is complete -> exit 0
    rc_pack, raw_pack, err_pack = _invoke_cli(
        [
            "ops",
            "context-pack",
            "--repo-map-home",
            str(sq_dir),
            "--graph",
            CTX_GRAPH_ID,
            "--mode",
            "ranked_discovery",
            "--query",
            "Billing",
            "--intent",
            "docs",
            "--binding",
            BINDING_DOCS,
        ],
        monkeypatch,
    )
    assert rc_pack == 0, err_pack
    pkt = json.loads(raw_pack.decode("utf-8"))
    assert_valid_context_packet(pkt)
    assert pkt["status"] == "complete"

    # Scoped definition without --kind is partial by design -> exit 3 by default, 0 with --allow-partial
    rc_p3, raw_p3, _ = _invoke_cli(
        [
            "ops",
            "context-pack",
            "--repo-map-home",
            str(sq_dir),
            "--graph",
            CTX_GRAPH_ID,
            "--mode",
            "ranked_discovery",
            "--query",
            "InvoiceService",
            "--intent",
            "definition",
            "--selection",
            str(sq_sel),
        ],
        monkeypatch,
    )
    assert rc_p3 == 3
    assert json.loads(raw_p3.decode("utf-8"))["status"] == "partial"

    rc_p0, raw_p0, _ = _invoke_cli(
        [
            "ops",
            "context-pack",
            "--repo-map-home",
            str(sq_dir),
            "--graph",
            CTX_GRAPH_ID,
            "--mode",
            "ranked_discovery",
            "--query",
            "InvoiceService",
            "--intent",
            "definition",
            "--selection",
            str(sq_sel),
            "--allow-partial",
        ],
        monkeypatch,
    )
    assert rc_p0 == 0
    assert json.loads(raw_p0.decode("utf-8"))["status"] == "partial"

    # PostgreSQL home CLI execution
    with temporary_postgres() as postgres:
        monkeypatch.setenv("REPOMAP_PSQL_COMMAND", postgres.psql_command)
        pg_dir = tmp_path / "pg_home"
        pg_dir.mkdir(parents=True, exist_ok=True)
        build_postgres_context_fixture(pg_dir, postgres)

        pg_sel = tmp_path / "pg_sel.json"
        rc_pg_sel, raw_pg_sel, err_pg_sel = _invoke_cli(
            [
                "ops",
                "context-select",
                "--config",
                str(pg_dir / "repomap.rpl.toml"),
                "--graph",
                CTX_GRAPH_ID,
                "--binding",
                BINDING_DOCS,
                "--pin-publication",
                "--output",
                str(pg_sel),
            ],
            monkeypatch,
        )
        assert rc_pg_sel == 0, err_pg_sel
        pg_sel_doc = json.loads(raw_pg_sel.decode("utf-8"))
        assert pg_sel_doc["backend"] == "postgresql"

        rc_pg_pack, raw_pg_pack, err_pg_pack = _invoke_cli(
            [
                "ops",
                "context-pack",
                "--config",
                str(pg_dir / "repomap.rpl.toml"),
                "--graph",
                CTX_GRAPH_ID,
                "--mode",
                "ranked_discovery",
                "--query",
                "Billing",
                "--intent",
                "docs",
                "--selection",
                str(pg_sel),
            ],
            monkeypatch,
        )
        assert rc_pg_pack == 0, err_pg_pack
        pg_pkt = json.loads(raw_pg_pack.decode("utf-8"))
        assert_valid_context_packet(pg_pkt)
        assert pg_pkt["status"] == "complete"
        assert pg_pkt["scope"]["backend"] == "postgresql"

        # Argparse errors exit 2; budget out of range exits 1
        rc_arg, _, _ = _invoke_cli(
            ["ops", "context-pack", "--graph", CTX_GRAPH_ID], monkeypatch
        )
        assert rc_arg == 2
        rc_bud, raw_bud, _ = _invoke_cli(
            [
                "ops",
                "context-pack",
                "--graph",
                CTX_GRAPH_ID,
                "--mode",
                "ranked_discovery",
                "--query",
                "InvoiceService",
                "--budget-bytes",
                "2048",
            ],
            monkeypatch,
        )
        assert rc_bud == 1
        assert_valid_budget_error(json.loads(raw_bud.decode("utf-8")))
