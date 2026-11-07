"""Explicit entrypoint branding and finite canonical object reexports."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import sys
from unittest.mock import patch

import pytest

import common_lore_index
from common_lore_index import cli, entrypoints
from common_lore_index.cli.main import main as canonical_main
from common_lore_index.cli.parser import build_parser
from common_lore_index.ops import config_migration as canonical_migration
from common_lore_index.runtime.project_identity import PROJECT_IDENTITY
import repomap_kg
from repomap_kg.ops import config_migration as legacy_migration
from repomap_kg.server.mcp import LEGACY_MCP_NOTICE

BRANDS = ((entrypoints.cloe_main, "cloe"), (entrypoints.long_main, "common-lore-index"),
          (entrypoints.legacy_main, "repomap-kg"))
LEGACY_LINE = entrypoints.LEGACY_COMMAND_NOTICE + "\n"


def capture(entry, *args: str):
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = entry(list(args))
        except SystemExit as exited:
            code = exited.code
    return code, stdout.getvalue(), stderr.getvalue()


def test_each_entrypoint_delegates_to_the_one_canonical_main():
    calls = []
    def canonical(argv=None, *, prog):
        calls.append((argv, prog))
        return 7
    for entry, prog in BRANDS:
        calls.clear()
        with patch.object(cli, "main", side_effect=canonical):
            code, stdout, stderr = capture(entry, "identity", "--json")
        assert (code, stdout) == (7, "")
        assert calls == [(["identity", "--json"], prog)]
        assert stderr == (LEGACY_LINE if prog == "repomap-kg" else "")
    assert cli.main is canonical_main


@pytest.mark.parametrize("argv0", ["repomap-kg", "cloe", "/opt/env/bin/common-lore-index", "-c"])
def test_brand_is_explicit_and_never_inferred_from_argv0(argv0):
    with patch.object(sys, "argv", [argv0, "--help"]):
        for entry, prog in BRANDS:
            code, stdout, stderr = capture(entry, "--help")
            assert code == 0 and stdout.startswith(f"usage: {prog} ")
            assert stderr == (LEGACY_LINE if prog == "repomap-kg" else "")
    assert build_parser().prog == "cloe"


def test_cli_keeps_no_argument_build_parser_seam(monkeypatch):
    seen = []
    def parser():
        seen.append(True)
        return build_parser(prog="seam")
    monkeypatch.setitem(canonical_main.__globals__, "build_parser", parser)
    code, stdout, _stderr = capture(canonical_main, "--help")
    assert code == 0 and stdout.startswith("usage: seam ") and seen == [True]


def test_version_brands_and_identity_stdout_preserve_exact_contracts():
    for entry, prog in BRANDS:
        assert capture(entry, "--version") == (
            0, f"{prog} {common_lore_index.__version__}\n", LEGACY_LINE if prog == "repomap-kg" else "")
        code, stdout, stderr = capture(entry, "identity", "--json")
        assert code == 0 and json.loads(stdout) == PROJECT_IDENTITY.as_dict()
        assert len(json.loads(stdout)) == 6
        assert stderr == (LEGACY_LINE if prog == "repomap-kg" else "")


@pytest.mark.parametrize("notice", [entrypoints.LEGACY_COMMAND_NOTICE, LEGACY_MCP_NOTICE])
def test_notices_are_bounded_public_lines(notice):
    assert notice.startswith("warning: legacy-") and "deprecated" in notice and "v0.1.x" in notice
    assert notice.isascii() and notice.isprintable() and len(notice) <= 160
    assert "/" not in notice and "\\" not in notice


def test_documented_migration_names_are_the_canonical_function_objects():
    assert legacy_migration.apply_cloe_config_migration is canonical_migration.apply_cloe_config_migration
    assert legacy_migration.rollback_cloe_config_migration is canonical_migration.rollback_cloe_config_migration
    assert legacy_migration.finalize_cloe_config_migration is canonical_migration.finalize_cloe_config_migration
    assert {name for name in vars(legacy_migration) if not name.startswith("_")} == {
        "apply_cloe_config_migration", "rollback_cloe_config_migration", "finalize_cloe_config_migration"}
    assert legacy_migration is not canonical_migration


def test_root_identity_reexports_do_not_duplicate_the_canonical_module():
    assert repomap_kg is not common_lore_index
    assert repomap_kg.DISTRIBUTION_NAME is common_lore_index.DISTRIBUTION_NAME
    assert repomap_kg.IMPORT_PACKAGE is common_lore_index.IMPORT_PACKAGE
    assert repomap_kg.PREFERRED_CLI is common_lore_index.PREFERRED_CLI
    assert repomap_kg.__version__ is common_lore_index.__version__
