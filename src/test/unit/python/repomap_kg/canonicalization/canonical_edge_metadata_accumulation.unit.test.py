import hashlib
import json
import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.canonicalization.value_helpers import (
    _append_distinct_json_values,
)


class _CountingString(str):
    comparisons = 0
    hashes = 0

    def __eq__(self, other):
        type(self).comparisons += 1
        return super().__eq__(other)

    def __hash__(self):
        type(self).hashes += 1
        return super().__hash__()

    @classmethod
    def reset(cls):
        cls.comparisons = 0
        cls.hashes = 0

    @classmethod
    def work(cls):
        return cls.comparisons + cls.hashes


def _host_mutation(index, *, counted):
    value_type = _CountingString if counted else str
    tool = value_type(f"tool-{index:03d}")
    reason = value_type(f"install package-{index:03d}")
    package = value_type(f"package-{index:03d}")
    argv = [tool, "install", package]
    return RawObservation(
        kind="shell.host_mutation",
        source_id=f"scripts/fan-in.sh#host-mutation:{index}:{tool}",
        path="scripts/fan-in.sh",
        start_line=index,
        end_line=index,
        target="host:package-management",
        confidence="heuristic",
        extractor="repo-shell",
        extractor_version="0.1.0",
        metadata={
            "tool": tool,
            "category": "package-management",
            "argv": argv,
            "effective_argv": argv,
            "privileged": False,
            "reason": reason,
        },
    )


class CanonicalEdgeMetadataAccumulationUnitTests(unittest.TestCase):
    def test_distinct_values_preserve_python_json_equality_and_first_seen_order(self):
        existing = [
            True,
            [1, {"a": "x", "b": 2}],
            {"items": [1, 2]},
            ("tuple", 1),
        ]
        incoming = [
            1,
            1.0,
            [1, {"b": 2, "a": "x"}],
            {"items": [1, 2]},
            ("tuple", 1),
            {"items": [2, 1]},
            "new",
            "new",
        ]

        merged = _append_distinct_json_values(existing, incoming)

        self.assertEqual(
            merged,
            [
                True,
                [1, {"a": "x", "b": 2}],
                {"items": [1, 2]},
                ("tuple", 1),
                {"items": [2, 1]},
                "new",
            ],
        )

    def test_distinct_values_fallback_preserves_unhashable_equality(self):
        merged = _append_distinct_json_values([{1, 2}], [{2, 1}, {2, 3}])

        self.assertEqual(merged, [{1, 2}, {2, 3}])

    def test_adversarial_edge_fan_in_has_near_linear_keyed_work(self):
        work_by_size = []
        for size in (16, 32, 64):
            _CountingString.reset()
            result = canonicalize_observations(
                [_host_mutation(index, counted=True) for index in range(1, size + 1)]
            )
            self.assertTrue(result.ok)
            self.assertEqual(len(result.graph.edges), 1)
            work_by_size.append(_CountingString.work())

        ratios = [
            current / previous
            for previous, current in zip(work_by_size, work_by_size[1:])
        ]
        self.assertTrue(
            all(1.5 <= ratio <= 2.2 for ratio in ratios),
            msg=f"work={work_by_size}, ratios={ratios}",
        )

    def test_serialized_metadata_identity_and_graph_digest_match_baseline(self):
        observations = [
            _host_mutation(1, counted=False),
            _host_mutation(2, counted=False),
            _host_mutation(1, counted=False),
            _host_mutation(3, counted=False),
        ]

        payload = canonicalize_observations(observations).to_dict()
        edge = payload["edges"][0]
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        self.assertEqual(
            edge["edge_key"],
            "canonical-edge:2c33ec4b27a739b62d4d4be0d1fbda4a1aef846ed33d2d29b43fb94dc637ade5",
        )
        self.assertEqual(edge["metadata"]["tools"], ["tool-001", "tool-002", "tool-003"])
        self.assertEqual(
            digest,
            "549f2d3170d7ab695c26df18e2d17e5fb3c025f1b7ecb060e64bc0c6660f5e0b",
        )


if __name__ == "__main__":
    unittest.main()
