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

        rc_pg_fallback, raw_pg_fallback, err_pg_fallback = _invoke_cli(
            [
                "ops", "context-pack", "--config", str(pg_dir / "repomap.rpl.toml"),
                "--graph", CTX_GRAPH_ID, "--mode", "graph_investigation",
                "--canonical-key", "py:pkg.billing.InvoiceService", "--query", "InvoiceService",
                "--fallback-to", "ranked_discovery", "--allow-partial",
            ],
            monkeypatch,
        )
        assert rc_pg_fallback == 0, err_pg_fallback
        pg_fallback = json.loads(raw_pg_fallback.decode("utf-8"))
        assert_valid_context_packet(pg_fallback)
        assert pg_fallback["requested_mode"] == "graph_investigation"
        assert pg_fallback["effective_mode"] == "ranked_discovery"
        assert pg_fallback["fallback"] == {
            "requested_mode": "graph_investigation",
            "effective_mode": "ranked_discovery",
            "reason": "backend_unsupported",
            "target_used": "query",
        }

        # Argparse errors exit 2; budget out of range exits 1
        rc_arg, _, _ = _invoke_cli(
            ["ops", "context-pack", "--graph", CTX_GRAPH_ID], monkeypatch
        )
        assert rc_arg == 2
        rc_bud, raw_bud, _ = _invoke_cli(
            [
                "ops", "context-pack", "--graph", CTX_GRAPH_ID,
                "--mode", "ranked_discovery", "--query", "InvoiceService",
                "--budget-bytes", "2048",
            ],
            monkeypatch,
        )
        assert rc_bud == 1
        assert_valid_budget_error(json.loads(raw_bud.decode("utf-8")))


@pytest.mark.parametrize(
    ("mode", "extra", "reason"),
    [
        ("literal_captured_text", ["--query", "InvoiceService"], "capability_not_admitted"),
        ("semantic_discovery", ["--query", "InvoiceService"], "capability_not_admitted"),
        ("ranked_discovery",
            ["--query", "InvoiceService", "--canonical-key", "py:pkg.billing.InvoiceService"],
            "invalid_target_flags"),
        ("graph_investigation",
            ["--canonical-key", "py:pkg.billing.InvoiceService", "--query", "InvoiceService"],
            "invalid_target_flags"),
        ("ranked_discovery",
            ["--query", "InvoiceService", "--intent", "not-an-intent"],
            "invalid_intent"),
        (
            "ranked_discovery",
            ["--query", "InvoiceService", "--fallback-to", "semantic_discovery"],
            "invalid_fallback",
        ),
        (
            "ranked_discovery",
            ["--query", "InvoiceService", "--freshness", "later"],
            "invalid_request",
        ),
    ],
)
def test_cli_context_pack_refuses_unsupported_modes_and_target_combinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    extra: list[str],
    reason: str,
) -> None:
    """Validate public CLI refusal envelopes before any database work for invalid requests."""
    home = tmp_path / "sqlite_home"
    home.mkdir()
    build_sqlite_context_fixture(home)
    rc, raw, _err = _invoke_cli(
        [
            "ops", "context-pack", "--repo-map-home", str(home),
            "--graph", CTX_GRAPH_ID, "--mode", mode,
            *extra,
        ],
        monkeypatch,
    )
    assert rc == 1
    packet = json.loads(raw.decode("utf-8"))
    assert packet["status"] in {"refused", "unavailable"}
    assert packet["reason"] == reason


def test_cli_context_select_deduplicates_bindings_and_rejects_invalid_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise source-selection scope limits and the O_EXCL output contract over a real SQLite home."""
    home = tmp_path / "sqlite_home"
    home.mkdir()
    build_sqlite_context_fixture(home)

    selected = tmp_path / "selected.json"
    rc, raw, err = _invoke_cli(
        [
            "ops", "context-select", "--repo-map-home", str(home),
            "--graph", CTX_GRAPH_ID, "--binding", BINDING_CORE,
            "--binding", BINDING_CORE, "--path-prefix", f"{BINDING_CORE}=src",
            "--path-prefix", f"{BINDING_CORE}=src", "--output", str(selected),
        ],
        monkeypatch,
    )
    assert rc == 0, err
    record = json.loads(raw.decode("utf-8"))
    assert record["bindings"][0]["binding_id"] == BINDING_CORE
    assert record["bindings"][0]["path_prefixes"] == ["src"]
    assert selected.stat().st_mode & 0o777 == 0o600

    rc_exists, _raw_exists, err_exists = _invoke_cli(
        [
            "ops", "context-select", "--repo-map-home", str(home),
            "--graph", CTX_GRAPH_ID, "--binding", BINDING_CORE,
            "--output", str(selected),
        ],
        monkeypatch,
    )
    assert rc_exists == 1
    assert "selection output already exists" in err_exists

    invalid_cases = [
        (["--binding", "unknown-binding"], "unknown binding_id"),
        (
            ["--binding", BINDING_CORE, "--path-prefix", f"{BINDING_DOCS}=adr"],
            "path_prefix for unselected binding",
        ),
        (
            ["--binding", BINDING_CORE, "--path-prefix", f"{BINDING_CORE}=../src"],
            "invalid path_prefix",
        ),
    ]
    for args, expected_fragment in invalid_cases:
        output = tmp_path / ("invalid-" + str(len(list(tmp_path.iterdir()))) + ".json")
        rc_bad, _raw_bad, err_bad = _invoke_cli(
            [
                "ops", "context-select", "--repo-map-home", str(home),
                "--graph", CTX_GRAPH_ID, *args, "--output",
                str(output),
            ],
            monkeypatch,
        )
        assert rc_bad == 1
        assert expected_fragment in err_bad
        assert not output.exists()


def test_cli_context_pack_freshness_scope_and_graph_fallback_are_real_boundary_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run opt-in freshness and graph fallback through the public CLI and inspect packet semantics."""
    home = tmp_path / "sqlite_home"
    home.mkdir()
    _db_path, config, _graph, _binding, _adapter = build_sqlite_context_fixture(home)
    source_root = Path(config.graphs[0].root_path)

    rc, raw, err = _invoke_cli(
        [
            "ops", "context-pack", "--repo-map-home", str(home),
            "--graph", CTX_GRAPH_ID, "--mode", "ranked_discovery",
            "--query", "InvoiceService", "--intent", "implementation",
            "--binding", BINDING_CORE, "--path-prefix", f"{BINDING_CORE}=src",
            "--freshness", "check", "--source-root", f"{BINDING_CORE}={source_root}",
        ],
        monkeypatch,
    )
    assert rc == 3, err
    packet = json.loads(raw.decode("utf-8"))
    assert_valid_context_packet(packet)
    assert packet["status"] == "partial"
    assert packet["freshness"]["files_checked"] > 0
    assert packet["scope"]["selected_binding_ids"] == [BINDING_CORE]

    rc_graph, raw_graph, err_graph = _invoke_cli(
        [
            "ops", "context-pack", "--repo-map-home", str(home),
            "--graph", CTX_GRAPH_ID, "--mode", "graph_investigation",
            "--canonical-key", "py:pkg.billing.InvoiceService", "--allow-partial",
        ],
        monkeypatch,
    )
    assert rc_graph == 0, err_graph
    graph_packet = json.loads(raw_graph.decode("utf-8"))
    assert_valid_context_packet(graph_packet)
    assert graph_packet["requested_mode"] == "graph_investigation"
    assert graph_packet["effective_mode"] == "graph_investigation"
