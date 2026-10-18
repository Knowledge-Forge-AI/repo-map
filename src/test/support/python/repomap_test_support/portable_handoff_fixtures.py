"""Public, deliberately synthetic handoff narratives and native source text.

The separate routed_locator helper reuses actual Markdown extraction,
canonicalization, disposable SQLite publication and public MCP dispatch.
File observations and snapshot manifests in that support remain synthetic.
Fixture source is only read, never executed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

NATIVE_TEXT = '# café 雪\r\ndef normalize(value):\r\n    return value.strip()\r\n'


def native_reference(identifier: str = "native") -> dict[str, Any]:
    return {"id": identifier, "repository_identity": "repo1:public-fixture",
            "root": {"key": "checkout", "origin": "caller_mapping"},
            "source_relative_path": "src/native.py", "range": [2, 3],
            "origin": "native", "selection": "direct"}


def selected_record() -> dict[str, Any]:
    """Authored content, not an extractor/model-derived conclusion."""
    return {"version": 1, "task": "Inspect café 雪 normalization",
            "references": [native_reference()],
            "findings": [{"id": "F1", "kind": "finding", "text": "Selected return calls strip.",
                          "evidence_ids": ["native"]},
                         {"id": "F2", "kind": "inference", "text": "Other behavior remains uncertain.",
                          "evidence_ids": ["native"]}],
            "questions": ["Does the caller allow None?"],
            "next_checks": ['Review callers; $(touch NEVER_EXECUTE); `echo inert`'],
            "negative_searches": [{"surface": "canonical node key/kind/display_name",
                                   "scope": "fixture graph, code", "query": "__all__",
                                   "outcome": "no_match", "complete": True, "has_more": False}]}


def write_native(workspace: Path) -> None:
    (workspace / "src").mkdir(parents=True)
    (workspace / "src/native.py").write_bytes(NATIVE_TEXT.encode("utf-8"))


def routed_locator(tmp_path: Path, monkeypatch: Any) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    # Imports deliberately stay in this test-only helper, outside native-only use.
    from repomap_kg.server import mcp
    from repomap_test_support.node_location_fixtures import BINDING, DOC, GRAPH, locator_home

    home, _ = locator_home(tmp_path)
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    reply = mcp.handle_tool_call("repomap_node_locations", {
        "graph_id": GRAPH, "canonical_key": DOC, "evidence_role": "direct", "detail": "compact",
    })
    assert not reply.get("isError")
    lead = reply["structuredContent"]
    assert lead["status"] == "located" and len(lead["locations"]) == 1
    row = lead["locations"][0]
    binding = lead["bindings"][row["binding"]]
    assert binding["binding_id"] == BINDING
    ref = {"id": "locator", "repository_identity": lead["repository_identity"],
           "root": {"key": BINDING, "origin": "stored_binding"},
           "source_relative_path": row["source_relative_path"],
           "range": None if row["start_line"] is None else [row["start_line"], row["end_line"]],
           "origin": "locator", "selection": "direct",
           "provenance": {"canonical_key": lead["canonical_key"], "graph_id": lead["graph"]["graph_id"],
                          "binding_id": binding["binding_id"], "run_id": row["run_id"],
                          "publication_relation": row["publication_relation"],
                          "freshness": lead["freshness"], "ambiguity": lead["ambiguity"],
                          "has_more": lead["has_more"], "evidence_role": row["evidence_role"],
                          "location_scope": lead["location_scope"]}}
    workspace = tmp_path / "local-source"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs/guide.md").write_text("Fixture guide.\n", encoding="utf-8")
    return ref, workspace, reply
