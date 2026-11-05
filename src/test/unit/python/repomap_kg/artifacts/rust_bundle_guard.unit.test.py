"""Direct endpoint/raw Rust claim refusal owner."""

from __future__ import annotations

from io import BytesIO
import json

import pytest

from common_lore_index.artifacts.rust_bundle_guard import GuardedBundleStream, reject_rust_claims


def test_orphan_rust_endpoint_is_refused_before_publication() -> None:
    with pytest.raises(ValueError, match="live parent witness"):
        reject_rust_claims({
            "canonical_edges": ({
                "source_canonical_key": "rust.source_file:file:src/lib.rs",
                "edge_kind": "contains",
                "target_canonical_key": "file:src/lib.rs",
            },),
        })


def test_stream_observer_refuses_rust_raw_and_canonical_claims() -> None:
    for family, record in (
        ("raw_observations", {"kind": "rust.parse"}),
        ("canonical_nodes", {"kind": "rust.function", "canonical_key": "rust.function:x:y"}),
    ):
        stream = GuardedBundleStream(BytesIO(
            (json.dumps({"frame": "record", "family": family, "record": record}) + "\n").encode("utf-8")
        ))
        with pytest.raises(ValueError, match="live parent witness"):
            stream.readline()


@pytest.mark.parametrize("family", [None, [], {}])
def test_stream_observer_leaves_malformed_family_bytes_for_the_schema_parser(family: object) -> None:
    wire = (json.dumps({"frame": "record", "family": family,
                        "record": {"kind": "rust.parse"}}) + "\n").encode()
    assert GuardedBundleStream(BytesIO(wire)).readline() == wire
