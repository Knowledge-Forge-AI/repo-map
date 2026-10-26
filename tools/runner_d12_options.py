"""D12 core-image and Route B system admission CLI options for the canonical test runner."""

from __future__ import annotations

import argparse
from typing import Any

INNER_SANDBOX_SYSTEM_PROOF_PATH = "/run/repomap-d12-system-proof.json"


def add_d12_runner_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the D12 profile arguments and the system-only Route B proof option."""
    parser.add_argument(
        "--d12-core-image-profile",
        choices=("linux/arm64", "linux/amd64"),
        default=None,
        help="ADR 0087 D12-A one-owner candidate build profile (exact scoped int node only)",
    )
    parser.add_argument(
        "--d12-core-image-source-sha256",
        default=None,
        help="frozen D12 build-context digest the checkout must still match",
    )
    parser.add_argument(
        "--d12-core-image-budget-ledger",
        default=None,
        help="D12 write-ahead build ledger; host admission consumes its matching entry",
    )
    parser.add_argument(
        "--d12-core-image-preflight",
        action="store_true",
        help="non-consuming E1 exploration mode of the D12 profile; never builds or opens a ledger",
    )
    parser.add_argument(
        "--d12-system-proof-json",
        default=None,
        help="path to the one-use D12 system admission proof JSON (accepted only for --suite system)",
    )


def validate_d12_system_proof_option(args: Any) -> None:
    """Reject --d12-system-proof-json on non-system suites or with blank paths."""
    raw_proof = getattr(args, "d12_system_proof_json", None)
    if raw_proof is None:
        return
    if getattr(args, "suite", None) != "system":
        raise RuntimeError("--d12-system-proof-json is only valid with --suite system")
    if not str(raw_proof).strip():
        raise RuntimeError("--d12-system-proof-json requires a non-empty path")
