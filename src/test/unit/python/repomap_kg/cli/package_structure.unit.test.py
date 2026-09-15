from __future__ import annotations

import argparse

import repomap_kg.cli as cli
import repomap_kg.cli.parser as parser_module
import repomap_kg.cli.dispatch as dispatch_module
from repomap_kg.cli.main import (
    main as main_func,
    canonical_node_kind_from_args as main_canonical_node_kind_from_args,
    psql_args_from_args as main_psql_args_from_args,
    build_parser as main_build_parser,
)


def _subparser_choices(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("parser has no subparsers")


def test_pkg2_cli_package_exports_compatibility_surface() -> None:
    assert callable(cli.main)
    assert cli.main is main_func
    assert getattr(cli, "build_parser") is getattr(parser_module, "build_parser")
    assert getattr(cli, "dispatch_command") is getattr(dispatch_module, "dispatch_command")
    assert getattr(cli, "canonical_node_kind_from_args") is main_canonical_node_kind_from_args
    assert getattr(cli, "psql_args_from_args") is main_psql_args_from_args


def test_pkg2_cli_parser_keeps_representative_commands() -> None:
    parser = getattr(cli, "build_parser")()

    assert {
        "discover",
        "storage",
        "mcp",
        "local",
        "ops",
        "host-mutators-summary",
    } <= _subparser_choices(parser)


def test_pkg2_cli_package_path_main_builds_parser() -> None:
    assert main_build_parser is parser_module.build_parser
    assert main_build_parser().prog == "repomap-kg"
