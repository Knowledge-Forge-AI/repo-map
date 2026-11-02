"""CLI subparser definitions for cloe ops context-pack and cloe ops context-select (W4 §2.1-2.2)."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from common_lore_index.retrieval.context_contracts import DEFAULT_BUDGET_BYTES


def add_ops_context_commands(
    ops_subcommands: Any,
    add_ops_config_arguments: Callable[[argparse.ArgumentParser], None],
) -> None:
    """Register context-pack and context-select under cloe ops."""
    pack = ops_subcommands.add_parser(
        "context-pack",
        help="assemble a bounded, intent-aware compact context packet",
    )
    add_ops_config_arguments(pack)
    pack.add_argument("--graph", required=True, help="configured graph identifier")
    pack.add_argument("--mode", required=True, help="explicit query mode")
    pack.add_argument("--canonical-key", default=None, help="exact canonical node key")
    pack.add_argument("--query", default=None, help="navigation search query")
    pack.add_argument("--intent", default=None, help="explicit navigation intent")
    pack.add_argument("--selection", type=Path, default=None, help="reusable source selection JSON file")
    pack.add_argument(
        "--binding", dest="bindings", action="append", default=[],
        help="select configured source binding ID (repeatable)",
    )
    pack.add_argument(
        "--path-prefix", dest="path_prefixes", action="append", default=[],
        help="scoped prefix BINDING_ID=REL_PREFIX (repeatable)",
    )
    pack.add_argument(
        "--kind", dest="kinds", action="append", default=[],
        help="restrict canonical node kind (repeatable)",
    )
    pack.add_argument(
        "--budget-bytes", type=int, default=DEFAULT_BUDGET_BYTES,
        help="hard UTF-8 output byte budget (4096..65536)",
    )
    pack.add_argument("--max-items", type=int, default=12, help="max ranked seed items (1..50)")
    pack.add_argument(
        "--locations-per-item", type=int, default=2,
        help="max verified direct locations per item (1..5)",
    )
    pack.add_argument("--offset", type=int, default=0, help="rank offset (0..1000)")
    pack.add_argument("--expand-depth", type=int, default=None, help="expansion depth (0 or 1)")
    pack.add_argument("--expand-seeds", type=int, default=3, help="max seeds to expand (1..5)")
    pack.add_argument("--node-limit", type=int, default=8, help="max neighbor nodes per seed (1..32)")
    pack.add_argument("--edge-limit", type=int, default=16, help="max incident edges per seed (1..64)")
    pack.add_argument(
        "--edge-kind", dest="edge_kinds", action="append", default=[],
        help="restrict expansion edge kind (repeatable)",
    )
    pack.add_argument("--fallback-to", default=None, help="explicit fallback mode")
    pack.add_argument("--freshness", default="none", help="freshness mode (none or check)")
    pack.add_argument(
        "--source-root", dest="source_roots", action="append", default=[],
        help="caller source root BINDING_ID=ABS_PATH for --freshness check",
    )
    pack.add_argument(
        "--allow-partial", action="store_true", default=False,
        help="exit 0 instead of 3 when packet status is partial",
    )

    select = ops_subcommands.add_parser(
        "context-select",
        help="validate and persist a reusable cloe-source-selection-v1 file",
    )
    add_ops_config_arguments(select)
    select.add_argument("--graph", required=True, help="configured graph identifier")
    select.add_argument(
        "--binding", dest="bindings", action="append", required=True,
        help="select configured source binding ID (1..8)",
    )
    select.add_argument(
        "--path-prefix", dest="path_prefixes", action="append", default=[],
        help="scoped prefix BINDING_ID=REL_PREFIX (repeatable)",
    )
    select.add_argument(
        "--pin-publication", action="store_true", default=False,
        help="pin expected_publication and binding snapshot_ids from accepted DB state",
    )
    select.add_argument(
        "--output", type=Path, required=True,
        help="output path for cloe-source-selection-v1 JSON (created with O_EXCL, 0o600)",
    )


add_ops_context_subparsers = add_ops_context_commands
