"""Unit tests for W4 CLI commands cloe ops context-pack and cloe ops context-select."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from common_lore_index.cli.main import main
from repomap_test_support.context_assertions import (
    assert_valid_budget_error,
    assert_valid_context_packet,
)
from repomap_test_support.context_fixture import BINDING_CORE, build_sqlite_context_fixture


def _run_cli(argv: list[str], capfd: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    try:
        code = main(argv)
    except SystemExit as exc:
        out, err = capfd.readouterr()
        return int(exc.code or 0), out, err
    out, err = capfd.readouterr()
    return code, out, err


def test_cli_argparse_errors_exit_2_and_budget_error_exits_1(
    capfd: pytest.CaptureFixture[str],
) -> None:
    # Missing --mode exits 2
    c_missing_mode, _, _ = _run_cli(["ops", "context-pack", "--graph", "g"], capfd)
    assert c_missing_mode == 2

    # Non-integer --budget-bytes exits 2 (argparse)
    c_str_budget, _, _ = _run_cli(
        ["ops", "context-pack", "--graph", "g", "--mode", "ranked_discovery", "--query", "x", "--budget-bytes", "abc"],
        capfd,
    )
    assert c_str_budget == 2

    # Out-of-range integer --budget-bytes 2048 emits budget_error <= 512 bytes and exits 1 before config load
    c_oor, out_oor, _ = _run_cli(
        [
            "ops", "context-pack", "--graph", "nonexistent-graph",
            "--mode", "ranked_discovery", "--query", "x", "--budget-bytes", "2048",
        ],
        capfd,
    )
    assert c_oor == 1
    env = json.loads(out_oor)
    assert_valid_budget_error(env)
    assert env["reason"] == "budget_out_of_range"
    assert env["budget_bytes"] == 2048


def test_cli_context_select_and_context_pack_exit_codes(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    _, _, graph, _, _ = build_sqlite_context_fixture(tmp_path)
    sel_path = tmp_path / "sel.json"

    # context-select succeeds with exit 0
    c_sel, out_sel, _ = _run_cli(
        [
            "ops", "context-select",
            "--repo-map-home", str(tmp_path),
            "--graph", graph.id,
            "--binding", BINDING_CORE,
            "--path-prefix", f"{BINDING_CORE}=src/billing",
            "--pin-publication",
            "--output", str(sel_path),
        ],
        capfd,
    )
    assert c_sel == 0
    sel_json = json.loads(out_sel)
    assert sel_json["schema"] == "cloe-source-selection-v1"

    # Second context-select to same --output refuses with exit 1 (O_EXCL)
    c_dup, _, _ = _run_cli(
        [
            "ops", "context-select",
            "--repo-map-home", str(tmp_path),
            "--graph", graph.id,
            "--binding", BINDING_CORE,
            "--output", str(sel_path),
        ],
        capfd,
    )
    assert c_dup == 1

    # Unscoped context-pack returns complete -> exit 0
    c_pack, out_pack, _ = _run_cli(
        [
            "ops", "context-pack",
            "--repo-map-home", str(tmp_path),
            "--graph", graph.id,
            "--mode", "ranked_discovery",
            "--query", "InvoiceService",
            "--intent", "definition",
        ],
        capfd,
    )
    assert c_pack == 0
    pkt = json.loads(out_pack)
    assert_valid_context_packet(pkt)
    assert pkt["status"] == "complete"

    # Scoped context-pack with --intent definition returns partial -> exit 3 by default, 0 with --allow-partial
    c_part, out_part, _ = _run_cli(
        [
            "ops", "context-pack",
            "--repo-map-home", str(tmp_path),
            "--graph", graph.id,
            "--mode", "ranked_discovery",
            "--query", "InvoiceService",
            "--intent", "definition",
            "--selection", str(sel_path),
        ],
        capfd,
    )
    assert c_part == 3
    pkt_part = json.loads(out_part)
    assert_valid_context_packet(pkt_part)
    assert pkt_part["status"] == "partial"

    c_allow, _, _ = _run_cli(
        [
            "ops", "context-pack",
            "--repo-map-home", str(tmp_path),
            "--graph", graph.id,
            "--mode", "ranked_discovery",
            "--query", "InvoiceService",
            "--intent", "definition",
            "--selection", str(sel_path),
            "--allow-partial",
        ],
        capfd,
    )
    assert c_allow == 0

    # Early refusal on a PostgreSQL config reports backend="postgresql" and consistency_mode="per_statement_identity_checked"
    pg_toml = tmp_path / "pg.rpl.toml"
    mem_dir = tmp_path / "mem"
    mem_dir.mkdir(exist_ok=True)
    pg_toml.write_text(
        'schema_version = 1\n\n[storage]\nbackend = "postgresql"\n\n'
        '[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n\n'
        '[postgres]\nhost = "127.0.0.1"\nport = 55433\ndatabase = "repomap"\nuser = "repomap"\n\n'
        '[runtime]\ncoordinator_mode = "native"\nbind_host = "127.0.0.1"\n\n'
        f'[server_memory]\nenabled = false\npath = "{mem_dir.resolve().as_posix()}"\nmode = "read_only"\n\n'
        f'[[graphs]]\nid = "{graph.id}"\nname = "{graph.id}"\ndatabase = "repomap"\n'
        'enabled = true\nmcp_visible = true\nrefresh_policy = "manual"\n',
        encoding="utf-8",
    )
    c_pg_ref, out_pg_ref, _ = _run_cli(
        [
            "ops", "context-pack",
            "--config", str(pg_toml),
            "--graph", graph.id,
            "--mode", "literal_captured_text",
            "--query", "InvoiceService",
        ],
        capfd,
    )
    assert c_pg_ref == 1
    pg_ref_pkt = json.loads(out_pg_ref)
    assert_valid_context_packet(pg_ref_pkt)
    assert pg_ref_pkt["scope"]["backend"] == "postgresql"
    assert pg_ref_pkt["consistency_mode"] == "per_statement_identity_checked"
