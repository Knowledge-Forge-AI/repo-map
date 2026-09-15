from collections.abc import Callable
import json
from typing import NamedTuple
from unittest.mock import patch

from repomap_kg.storage import (
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    JSFrameworkSummaryRecord,
    CanonicalStorageSummaryRecord,
)

from repomap_test_support.mcp_server import McpServerTestSupport


class ReadOnlyCase(NamedTuple):
    label: str
    patch_target: str | None
    patch_value: object
    call: Callable[[], dict[str, object]]
    graph: Callable[[dict[str, object]], object]
    extra: Callable[[dict[str, object]], None]


class SearchCase(NamedTuple):
    label: str
    call: Callable[[], dict[str, object]]
    target: str
    include_raw: bool | None
    payload: dict[str, object]
    first_key: str


class McpServerReadOnlyContractUnitTests(McpServerTestSupport):
    def test_mcp_harden2_graph_backed_tools_share_read_only_contract(self):
        from repomap_kg.server.mcp import (
            repomap_graph_status,
            repomap_js_framework_summary,
            repomap_list_graphs,
            repomap_neighborhood,
            repomap_project_summary,
        )

        config_path = self.write_visible_ops_config()

        def storage_summary(root_path: str, repository_name: str):
            return CanonicalStorageSummaryRecord(
                root_path=root_path,
                repository_name=repository_name,
                latest_run_id=44,
                runs=1,
                files=2,
                raw_observations=13,
                canonical_nodes=3,
                canonical_edges=4,
                canonical_evidence=5,
            )

        def js_framework_summary(root_path: str, repository_name: str):
            return JSFrameworkSummaryRecord(
                root_path=root_path,
                repository_name=repository_name,
                framework_observations=6,
                framework_profiles={"node": 1},
                node={},
                express={},
                nest={},
                next={},
                jest={},
                jquery={},
                generic_js={},
                diagnostics={},
                safety={"no_execution": True},
            )

        neighborhood = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
                canonical_key="python.module:pkg.app",
                graph_key_version=1,
                kind="python.module",
                display_name="pkg.app",
                confidence="extracted",
                conflict=False,
                metadata={},
                first_seen_run_id=1,
                last_seen_run_id=2,
            ),
            nodes=(),
            edges=(),
        )

        def first_graph(payload: dict[str, object]) -> object:
            graphs = payload["graphs"]
            assert isinstance(graphs, (list, tuple))
            return graphs[0]

        def check_status_extra(payload: dict[str, object]) -> None:
            storage = payload["storage"]
            assert isinstance(storage, dict)
            self.assertEqual(
                storage["latest_run_consistency"],
                {"complete_without_finished_at": False},
            )
            self.assertEqual(storage["latest_run_status"], "complete")
            self.assertEqual(storage["raw_observations"], 9)

        def check_project_extra(payload: dict[str, object]) -> None:
            summary = payload["summary"]
            assert isinstance(summary, dict)
            self.assertEqual(summary["root_path"], "[graph-root]")
            counts = summary["counts"]
            assert isinstance(counts, dict)
            self.assertEqual(counts["canonical_nodes"], 3)

        def check_js_extra(payload: dict[str, object]) -> None:
            self.assertEqual(payload["summary_kind"], "js_framework")
            summary = payload["summary"]
            assert isinstance(summary, dict)
            self.assertEqual(summary["root_path"], "[graph-root]")
            self.assertEqual(summary["framework_observations"], 6)

        def check_neighborhood_extra(payload: dict[str, object]) -> None:
            self.assertEqual(payload["depth"], 1)
            result = payload["result"]
            assert isinstance(result, dict)
            center = result["center"]
            assert isinstance(center, dict)
            self.assertEqual(center["canonical_key"], "python.module:pkg.app")

        cases: list[ReadOnlyCase] = [
            ReadOnlyCase(
                label="list_graphs",
                patch_target=None,
                patch_value=None,
                call=repomap_list_graphs,
                graph=first_graph,
                extra=lambda payload: self.assertEqual(payload["graph_count"], 2),
            ),
            ReadOnlyCase(
                label="graph_status",
                patch_target="repomap_kg.server.ops.query_refresh_status",
                patch_value={
                    "repo-map": self.synthetic_refresh_status(
                        latest_run_status="complete",
                        latest_run_finished_at="2026-07-01T00:01:00Z",
                        raw_observations=9,
                        canonical_nodes=8,
                        canonical_edges=7,
                    )
                },
                call=lambda: repomap_graph_status(graph_id="repo-map"),
                graph=lambda payload: payload["graph"],
                extra=check_status_extra,
            ),
            ReadOnlyCase(
                label="project_summary",
                patch_target="repomap_kg.server.ops.query_canonical_storage_summary",
                patch_value=storage_summary("/tmp/fixture", "fixture"),
                call=lambda: repomap_project_summary(graph_id="repo-map"),
                graph=lambda payload: payload["graph"],
                extra=check_project_extra,
            ),
            ReadOnlyCase(
                label="js_framework_summary",
                patch_target="repomap_kg.server.ops.query_js_framework_summary",
                patch_value=js_framework_summary("/tmp/fixture", "fixture"),
                call=lambda: repomap_js_framework_summary(graph_id="repo-map"),
                graph=lambda payload: payload["graph"],
                extra=check_js_extra,
            ),
            ReadOnlyCase(
                label="neighborhood",
                patch_target="repomap_kg.server.ops.query_canonical_neighborhood",
                patch_value=neighborhood,
                call=lambda: repomap_neighborhood(
                    graph_id="repo-map",
                    node="python.module:pkg.app",
                ),
                graph=lambda payload: payload["graph"],
                extra=check_neighborhood_extra,
            ),
        ]

        with self.patch_ops_config(config_path):
            for case in cases:
                with self.subTest(tool=case.label):
                    if case.patch_target is None:
                        payload = case.call()
                    else:
                        with patch(
                            case.patch_target,
                            return_value=case.patch_value,
                        ):
                            payload = case.call()

                    self.assert_read_only_payload(payload)
                    self.assert_public_graph_payload(case.graph(payload))
                    case.extra(payload)
    def test_mcp_harden2_search_payloads_share_bounded_result_contract(self):
        from repomap_kg.server.mcp import (
            repomap_search_files,
            repomap_search_nodes,
            repomap_search_observations,
        )

        config_path = self.write_visible_ops_config()
        cases: list[SearchCase] = [
            SearchCase(
                label="nodes",
                call=lambda: repomap_search_nodes(
                    graph_id="repo-map",
                    query="pkg",
                    limit=1,
                    offset=2,
                ),
                target="nodes",
                include_raw=None,
                payload={
                    "results": [
                        {
                            "canonical_key": "python.module:pkg.app",
                            "kind": "python.module",
                            "display_name": "pkg.app",
                            "metadata": {"token": "mcp-harden2-fake-token"},
                        },
                        {
                            "canonical_key": "python.module:pkg.extra",
                            "kind": "python.module",
                            "display_name": "pkg.extra",
                            "metadata": {},
                        },
                    ],
                    "total": 7,
                    "has_more": False,
                },
                first_key="canonical_key",
            ),
            SearchCase(
                label="observations",
                call=lambda: repomap_search_observations(
                    graph_id="repo-map",
                    query="command",
                    limit=1,
                    offset=2,
                    include_raw=False,
                ),
                target="observations",
                include_raw=False,
                payload={
                    "results": [
                        {
                            "ordinal": 1,
                            "kind": "command.reference",
                            "path": "synthetic/config.txt",
                            "source_id": "synthetic/config.txt#command:1",
                            "metadata": {"secret": "mcp-harden2-fake-secret"},
                        },
                        {
                            "ordinal": 2,
                            "kind": "command.reference",
                            "path": "synthetic/config.txt",
                            "source_id": "synthetic/config.txt#command:2",
                            "metadata": {},
                        },
                    ],
                    "total": 7,
                    "has_more": False,
                },
                first_key="source_id",
            ),
            SearchCase(
                label="files",
                call=lambda: repomap_search_files(
                    graph_id="repo-map",
                    query="app",
                    limit=1,
                    offset=2,
                ),
                target="files",
                include_raw=None,
                payload={
                    "results": [
                        {
                            "path": "src/pkg/app.py",
                            "language": "python",
                            "role": "source",
                        },
                        {
                            "path": "src/pkg/extra.py",
                            "language": "python",
                            "role": "source",
                        },
                    ],
                    "total": 7,
                    "has_more": False,
                },
                first_key="path",
            ),
        ]

        with self.patch_ops_config(config_path):
            for case in cases:
                with self.subTest(target=case.target):
                    with patch(
                        "repomap_kg.server.ops.query_mcp_search",
                        return_value=case.payload,
                    ) as query:
                        payload = case.call()

                    self.assert_read_only_payload(payload)
                    self.assert_public_graph_payload(payload["graph"])
                    self.assertEqual(payload["target"], case.target)
                    self.assertEqual(payload["limit"], 1)
                    self.assertEqual(payload["offset"], 2)
                    self.assertEqual(payload["result_count"], 1)
                    self.assertEqual(payload["total"], 7)
                    self.assertTrue(payload["has_more"])
                    self.assertEqual(
                        query.call_args.kwargs["target"],
                        case.target,
                    )
                    self.assertEqual(query.call_args.kwargs["limit"], 1)
                    self.assertEqual(query.call_args.kwargs["offset"], 2)
                    results = payload["results"]
                    assert isinstance(results, list)
                    first_res = results[0]
                    assert isinstance(first_res, dict)
                    self.assertIn(case.first_key, first_res)
                    serialized = json.dumps(payload, sort_keys=True)
                    self.assertNotIn("mcp-harden2-fake-token", serialized)
                    self.assertNotIn("mcp-harden2-fake-secret", serialized)
                    if case.include_raw is not None:
                        self.assert_raw_payload_policy(
                            payload,
                            include_raw=case.include_raw,
                        )
                        self.assertFalse(query.call_args.kwargs["include_raw"])
                        self.assertNotIn("payload", first_res)
