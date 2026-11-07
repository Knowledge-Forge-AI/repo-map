"""Focused H01-H12 portable record behavior; no fixture source execution."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import portable_handoff as handoff_module
import source_navigation_consumer as consumer_module
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from repomap_test_support.portable_handoff_fixtures import (
    NATIVE_TEXT, routed_locator, selected_record, write_native,
)

ROOT = Path(__file__).resolve().parents[5]
assert Path(handoff_module.__file__).resolve() == ROOT / "tools/portable_handoff.py"
API = vars(handoff_module)
export, load, render, recheck = (API[name] for name in ("export", "load", "render", "recheck"))
HandoffError = API["HandoffError"]


def mapping(workspace: Path | str) -> dict:
    return {("repo1:public-fixture", "caller_mapping", "checkout"): workspace}


def test_h01_h02_h10_pure_unicode_roundtrip_order_and_markdown() -> None:
    record = selected_record()
    record["questions"].append('# heading\n<script>alert("hi")</script> [link](https://invalid)\n===\n1. item')
    with patch.object(Path, "open", side_effect=AssertionError("source read")), \
         patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
        payload = export(record)
        restored = load(payload.encode("utf-8"))
        markdown = render(restored)
    assert restored == record and export(restored) == payload
    assert "café 雪" in payload and "café 雪" in markdown
    assert markdown == render(record)
    assert "<script>" not in markdown and "$(touch" not in markdown and "\n# heading" not in markdown
    assert "src/native.py" in markdown and "&#47;" not in markdown
    assert "\\# heading\n  &lt;script&gt;" in markdown
    assert "\n  \\=\\=\\=\n  1\\. item" in markdown
    assert "  - **Key:** checkout" in markdown
    assert markdown.index("Selected return") < markdown.index("Other behavior")
    assert "graph_id" not in payload and "binding_id" not in payload
    assert restored["next_checks"] == record["next_checks"]


def test_h03_h04_h07_actual_routed_locator_native_relocation_and_consumer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from common_lore_index.server import mcp

    ref, workspace, reply = routed_locator(tmp_path / "routed", monkeypatch)
    record = selected_record()
    record["references"].append(ref)
    write_native(workspace)
    assert ref["range"] is None and ref["provenance"]["publication_relation"] == "accepted_run"
    original = export(record)
    with patch.object(mcp, "handle_tool_call", side_effect=AssertionError("unexpected graph call")):
        observed = recheck(load(original), ["native", "locator"], {**mapping(workspace),
                           (ref["repository_identity"], ref["root"]["origin"], ref["root"]["key"]): workspace}, lambda ref, text: bool(text))
        assert all(row["source_check"] is True for row in observed)
        for source, check in zip(record["references"], observed):
            source["recorded_content"] = check["content"]
        serialized = export(record)
        relocated = tmp_path / "second-workspace"
        write_native(relocated)
        (relocated / "docs").mkdir()
        (relocated / "docs/guide.md").write_text("Fixture guide.\n", encoding="utf-8")
        checks = recheck(load(serialized), ["native", "locator"], {**mapping(relocated),
                         (ref["repository_identity"], ref["root"]["origin"], ref["root"]["key"]): relocated}, lambda ref, text: bool(text))
        assert [row["outcome"] for row in checks] == ["matching", "matching"]
        assert record["references"][1]["range"] is None and checks[1]["inspected_range"] == [1, 1]
        navigate = vars(consumer_module)["navigate"]
        # Existing consumer's caller-local mapping slot; no stored binding invented for native evidence.
        consumer = navigate(graph_id="absent", repository_identity="repo1:public-fixture",
                            bindings={"local-slot": relocated}, tool_call=mcp.handle_tool_call,
                            handoff={"repository_identity": "repo1:public-fixture", "binding_id": "local-slot",
                                     "source_relative_path": "src/native.py", "start_line": 2, "end_line": 3},
                            source_check=lambda text: "return value.strip()" in text)
        assert consumer["outcome"] == "verified" and consumer["graph_calls"] == 0
    assert reply["structuredContent"]["freshness"] == "unverified"
    assert load(serialized)["references"][1]["provenance"] == ref["provenance"]


def test_h05_h06_changed_missing_unmapped_bounds_and_assertions_are_independent(tmp_path: Path) -> None:
    write_native(tmp_path)
    record = selected_record()
    observed = recheck(record, ["native"], mapping(tmp_path))[0]
    record["references"][0]["recorded_content"] = observed["content"]
    for identifier in ("changed", "missing", "unmapped", "large"):
        ref = copy.deepcopy(record["references"][0]); ref["id"] = identifier
        ref["assertions"] = ["verified=true (externally asserted)"]
        record["references"].append(ref)
    record["references"][1]["source_relative_path"] = "changed.py"
    (tmp_path / "changed.py").write_text("# moved\n# changed\n# changed\n", encoding="utf-8")
    record["references"][2]["source_relative_path"] = "absent.py"
    record["references"][3]["root"]["key"] = "unmapped"
    record["references"][4]["range"] = [1, 81]
    before = export(record)
    checks = recheck(load(before), [r["id"] for r in record["references"]], mapping(tmp_path), lambda r, t: "return" in t)
    assert [c["outcome"] for c in checks] == ["matching", "changed", "missing", "unmapped", "out_of_bound"]
    assert checks[0]["source_check"] is True and checks[1]["predicate"] == "failed"
    assert all("source_check" not in c for c in checks[1:])
    assert export(record) == before
    # A forged recorded hash is compared to an actual read; it cannot bypass it.
    record["references"][0]["recorded_content"] = {**observed["content"], "origin": "external", "sha256": "0" * 64}
    assert recheck(record, ["native"], mapping(tmp_path))[0]["outcome"] == "changed"


def test_h07_digest_domains_crlf_and_path_only_excerpt(tmp_path: Path) -> None:
    write_native(tmp_path)
    record = selected_record()
    first = recheck(record, ["native"], mapping(tmp_path))[0]
    expected = "".join(NATIVE_TEXT.splitlines(keepends=True)[1:3]).encode("utf-8")
    assert first["content"]["sha256"] == hashlib.sha256(expected).hexdigest()
    ref = record["references"][0]
    ref["range"] = None
    (tmp_path / "src/native.py").write_text("line\n" * 90, encoding="utf-8")
    excerpt = recheck(record, ["native"], mapping(tmp_path))[0]
    assert excerpt["inspected_range"] == [1, 80] and ref["range"] is None
    assert excerpt["content"]["domain"] == "file" and excerpt["content"]["range"] is None
    assert excerpt["content"]["sha256"] == hashlib.sha256(("line\n" * 90).encode()).hexdigest()
    # Deliberately mislabeled external hash is not compared against the range domain.
    ref["recorded_content"] = {**excerpt["content"], "origin": "external",
                               "sha256": hashlib.sha256(("line\n" * 80).encode()).hexdigest()}
    assert recheck(record, ["native"], mapping(tmp_path))[0]["outcome"] == "changed"
    ref["recorded_content"]["sha256"] = hashlib.sha256(("line\n" * 90).encode()).hexdigest()
    assert recheck(record, ["native"], mapping(tmp_path))[0]["outcome"] == "matching"
    (tmp_path / "src/native.py").write_text("line\n" * 91, encoding="utf-8")
    assert recheck(record, ["native"], mapping(tmp_path))[0]["outcome"] == "changed"
    ref["recorded_content"] = {**excerpt["content"], "domain": "range", "range": [1, 80],
                               "sha256": hashlib.sha256(("line\n" * 80).encode()).hexdigest()}
    assert recheck(record, ["native"], mapping(tmp_path))[0]["outcome"] == "matching"


@pytest.mark.parametrize("omitted", ["provenance", "has_more", "ambiguity", "location_scope",
                                    "publication_relation", "evidence_role"])
def test_h08_locator_requires_explicit_current_selection_facts(omitted: str, tmp_path: Path) -> None:
    write_native(tmp_path)
    record = selected_record()
    ref = record["references"][0]
    ref.update(origin="locator", provenance={"has_more": False, "ambiguity": "single_stored_location",
               "location_scope": "accepted_run", "publication_relation": "accepted_run", "evidence_role": "direct"})
    if omitted == "provenance":
        del ref["provenance"]
    else:
        del ref["provenance"][omitted]
    roots = {**mapping(tmp_path), ("repo1:public-fixture", "checkout"): tmp_path}
    with patch.object(Path, "open", side_effect=AssertionError("uncertain read")):
        assert recheck(load(export(record)), ["native"], roots)[0]["reason"] == "uncertain_reference"


def test_h04_mapping_origin_is_part_of_the_explicit_identity(tmp_path: Path) -> None:
    write_native(tmp_path)
    record = selected_record()
    bound = copy.deepcopy(record["references"][0])
    bound.update(id="stored")
    bound["root"]["origin"] = "stored_binding"
    record["references"].append(bound)
    checks = recheck(record, ["native", "stored"], mapping(tmp_path))
    assert [c["outcome"] for c in checks] == ["observed", "unmapped"]
    # A missing root is a mapping failure, distinct from a missing file under an existing root.
    assert recheck(record, ["native"], mapping(tmp_path / "absent"))[0]["reason"] == "missing_root"


def test_h05_recorded_range_shrink_reports_drift(tmp_path: Path) -> None:
    write_native(tmp_path)
    record = selected_record()
    record["references"][0]["recorded_content"] = recheck(record, ["native"], mapping(tmp_path))[0]["content"]
    (tmp_path / "src/native.py").write_text("one line\n", encoding="utf-8")
    observed = recheck(record, ["native"], mapping(tmp_path), lambda r, t: True)[0]
    assert observed["outcome"] == "changed" and observed["reason"] == "recorded_range_missing"
    assert "content" not in observed and "source_check" not in observed


def test_h09_future_version_reports_version_before_new_fields() -> None:
    record = selected_record()
    record.update(version=2, future_field="new data")
    with pytest.raises(HandoffError, match="unsupported handoff version"):
        load(json.dumps(record))


@pytest.mark.parametrize("selection,origin,facts", [
    ("ambiguous", "locator", {"has_more": True, "ambiguity": "multiple_stored_locations"}),
    ("historical", "historical", {"publication_relation": "historical_run", "revision": "historical-revision"}),
    ("unknown", "unknown", {"freshness": "unknown"}),
    ("direct", "locator", {"has_more": True}),
    ("direct", "locator", {"location_scope": "historical_only"}),
])
def test_h08_uncertain_references_are_preserved_without_reading(selection: str, origin: str, facts: dict) -> None:
    record = selected_record(); ref = record["references"][0]
    ref.update(selection=selection, origin=origin, provenance=facts, range=None)
    with patch.object(Path, "open", side_effect=AssertionError("uncertain read")):
        assert load(export(record)) == record
        assert recheck(record, ["native"], {})[0]["reason"] == "uncertain_reference"
    search = load(export(record))["negative_searches"][0]
    assert search["complete"] is True and search["surface"] == "canonical node key/kind/display_name"
    assert "source" not in search["outcome"]


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(version=2), lambda r: r.update(version=True),
    lambda r: r["findings"][0].update(evidence_ids=["dangling"]),
    lambda r: r["references"].append(copy.deepcopy(r["references"][0])),
    lambda r: r["references"][0].update(range=[None, 2]),
    lambda r: r["references"][0].update(host_root="/untrusted"),
    lambda r: r["references"][0].update(verified=True),
    lambda r: r.update(questions=["x"] * 33),
    lambda r: r.update(task="x" * 4097),
])
def test_h09_invalid_records_are_local_errors(mutation) -> None:
    record = selected_record(); mutation(record)
    with pytest.raises(HandoffError): export(record)
    with pytest.raises(HandoffError): load(json.dumps(record))


@pytest.mark.parametrize("payload", [b'\xff', '{', '[]', '{"version":1,"version":1}', '"text"', '[' * 5000])
def test_h09_malformed_load(payload: str | bytes) -> None:
    with pytest.raises(HandoffError): load(payload)


def test_h09_utf8_budget_never_silently_drops_uncertainty() -> None:
    record = selected_record(); record["questions"] = ["雪" * 4096] * 6
    before = copy.deepcopy(record)
    with pytest.raises(HandoffError, match="budget.*reduce"): export(record)
    with pytest.raises(HandoffError, match="budget.*reduce"): load(json.dumps(record, ensure_ascii=False))
    assert record == before


@pytest.mark.parametrize("path", ["../outside", "/outside", "https://invalid/path", "a/../b", "a\\b", "~root/x", "a//b"])
def test_h10_unsafe_paths_never_load(path: str) -> None:
    record = selected_record(); record["references"][0]["source_relative_path"] = path
    with pytest.raises(HandoffError): load(json.dumps(record))


def test_h10_mapping_symlink_bounds_selection_and_predicate_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"; write_native(workspace)
    record = selected_record()
    for invalid in (Path("relative"), "not-a-path"):
        assert recheck(record, ["native"], mapping(invalid))[0]["reason"] == "invalid_mapping"
    outside = tmp_path / "outside.py"; outside.write_text("outside\n", encoding="utf-8")
    (workspace / "escape.py").symlink_to(outside)
    ref = record["references"][0]; ref["source_relative_path"] = "escape.py"
    assert recheck(record, ["native"], mapping(workspace))[0]["outcome"] == "not_checked"
    ref["source_relative_path"] = "src/native.py"
    with patch.object(Path, "open", side_effect=AssertionError("unselected read")):
        assert recheck(record, [], mapping(workspace)) == []
    with pytest.raises(HandoffError): recheck(record, ["dangling"], mapping(workspace))
    def broken(ref: dict, text: str) -> bool:
        raise RuntimeError("private callback detail")
    check = recheck(record, ["native"], mapping(workspace), broken)[0]
    assert check["predicate"] == "error" and "source_check" not in check
    assert "private callback" not in json.dumps(check)
    (workspace / "src/native.py").write_bytes(b"x" * 65_537)
    assert recheck(record, ["native"], mapping(workspace))[0]["outcome"] == "out_of_bound"
    (workspace / "src/native.py").write_bytes(b"\xff")
    assert recheck(record, ["native"], mapping(workspace))[0]["outcome"] == "not_checked"
    (workspace / "src/native.py").write_text("only one line\n", encoding="utf-8")
    assert recheck(record, ["native"], mapping(workspace))[0]["reason"] == "range_beyond_file"


def test_h02_clean_process_without_graph_import_and_inert_actions(tmp_path: Path) -> None:
    script = '''import runpy,sys
from pathlib import Path
api=runpy.run_path(sys.argv[1])
fixture=runpy.run_path(sys.argv[2])
workspace=Path(sys.argv[3]);fixture['write_native'](workspace)
r=fixture['selected_record']()
assert api['load'](api['export'](r))==r
api['render'](r)
assert api['recheck'](r,['native'],{('repo1:public-fixture','caller_mapping','checkout'):workspace})[0]['outcome']=='observed'
assert not any(k.startswith('common_lore_index') for k in sys.modules)
assert not (workspace/'NEVER_EXECUTE').exists()
'''
    subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script,
                    str(ROOT / "tools/portable_handoff.py"),
                    str(ROOT / "src/test/support/python/repomap_test_support/portable_handoff_fixtures.py"),
                    str(tmp_path / "isolated")], check=True, capture_output=True, text=True)
