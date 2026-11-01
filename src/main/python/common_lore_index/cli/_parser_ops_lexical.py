"""Parser construction for PostgreSQL cloe_lexical ops subcommands."""

from __future__ import annotations

import argparse
from collections.abc import Callable

StorageArgumentHelper = Callable[[argparse.ArgumentParser], None]


def _lexical_limit(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 100:
        raise argparse.ArgumentTypeError("limit must be between 1 and 100")
    return parsed


def _lexical_offset(value: str) -> int:
    parsed = int(value)
    if parsed < 0 or parsed > 1000:
        raise argparse.ArgumentTypeError("offset must be between 0 and 1000")
    return parsed


def add_ops_lexical_commands(
    ops_subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
    add_ops_config_arguments: StorageArgumentHelper,
) -> None:
    """Register opt-in PostgreSQL lexical-build, lexical-query, and lexical-revoke commands."""
    lex_build = ops_subcommands.add_parser(
        "lexical-build",
        help="build and publish an opt-in PostgreSQL cloe_lexical generation for a public-dev graph",
    )
    add_ops_config_arguments(lex_build)
    lex_build.add_argument(
        "--graph",
        required=True,
        help="configured graph id to build a cloe_lexical generation for",
    )
    lex_build.add_argument(
        "--authorize-body",
        dest="authorize_body",
        action="store_true",
        default=False,
        help="explicitly authorize public-dev body indexing",
    )
    lex_build.add_argument(
        "--no-authorize-body",
        dest="authorize_body",
        action="store_false",
        help="refuse body indexing",
    )
    lex_build.add_argument(
        "--binding-id",
        "--binding",
        dest="binding_id",
        action="append",
        default=[],
        help="optional explicit binding_id selection (may be repeated)",
    )
    lex_build.add_argument(
        "--portable-store-root",
        default=None,
        help="optional portable store root path",
    )
    lex_build.add_argument(
        "--json",
        action="store_true",
        help="emit lexical build outcome as JSON",
    )

    lex_query = ops_subcommands.add_parser(
        "lexical-query",
        help="query an active PostgreSQL cloe_lexical generation with single-statement fencing",
    )
    add_ops_config_arguments(lex_query)
    lex_query.add_argument(
        "--graph",
        required=True,
        help="configured graph id to query",
    )
    lex_query.add_argument(
        "--query",
        required=True,
        help="lexical query text",
    )
    lex_query.add_argument(
        "--query-style",
        "--style",
        dest="query_style",
        choices=("ranked_terms", "normalized_phrase", "literal_captured_text"),
        default="ranked_terms",
        help="PostgreSQL lexical query style (default: ranked_terms)",
    )
    lex_query.add_argument(
        "--authorize-body",
        dest="authorize_body",
        action="store_true",
        default=False,
        help="explicitly authorize public-dev body query",
    )
    lex_query.add_argument(
        "--no-authorize-body",
        dest="authorize_body",
        action="store_false",
        help="refuse body query",
    )
    lex_query.add_argument(
        "--requested-mode",
        choices=(
            "exact_identity",
            "current_literal_enumeration",
            "literal_captured_text",
            "ranked_discovery",
            "graph_investigation",
            "semantic_discovery",
        ),
        help="optional caller-requested QueryMode",
    )
    lex_query.add_argument(
        "--binding-id",
        "--binding",
        dest="binding_id",
        action="append",
        default=[],
        help="restrict query scope to this binding_id (may be repeated)",
    )
    lex_query.add_argument(
        "--path-prefix",
        action="append",
        default=[],
        help="restrict query scope to this relative path prefix (may be repeated)",
    )
    lex_query.add_argument(
        "--limit",
        type=_lexical_limit,
        default=20,
        help="maximum hits to return (1..100, default: 20)",
    )
    lex_query.add_argument(
        "--offset",
        type=_lexical_offset,
        default=0,
        help="hit page offset (0..1000, default: 0)",
    )
    lex_query.add_argument(
        "--fallback-from-mode",
        choices=(
            "exact_identity",
            "current_literal_enumeration",
            "literal_captured_text",
            "ranked_discovery",
            "graph_investigation",
            "semantic_discovery",
        ),
        help="explicit caller-selected fallback source mode",
    )
    lex_query.add_argument(
        "--fallback-reason",
        help="explicit caller-selected fallback reason code",
    )
    lex_query.add_argument(
        "--json",
        action="store_true",
        help="emit lexical QueryEnvelope outcome as JSON",
    )

    lex_revoke = ops_subcommands.add_parser(
        "lexical-revoke",
        help="revoke active PostgreSQL cloe_lexical generations and purge derived body rows",
    )
    add_ops_config_arguments(lex_revoke)
    lex_revoke.add_argument(
        "--graph",
        required=True,
        help="configured graph id whose cloe_lexical generations should be revoked",
    )
    lex_revoke.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="report counts without mutating database state",
    )
    lex_revoke.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="confirm revocation",
    )
    lex_revoke.add_argument(
        "--reason",
        default="operator_revoked",
        help="revocation audit reason recorded on cloe_lexical.generations",
    )
    lex_revoke.add_argument(
        "--json",
        action="store_true",
        help="emit lexical revocation outcome as JSON",
    )


__all__ = ["add_ops_lexical_commands"]
