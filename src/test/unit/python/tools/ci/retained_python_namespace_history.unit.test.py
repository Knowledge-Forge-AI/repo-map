"""Namespace authority checks actual source/Git history and refuses hidden changes."""
import copy
import ast
import hashlib
import json

import pytest

from ci.retained_python_contract import LineagePolicyError, RatchetContractError
from ci.retained_python_namespace_evidence import NamespaceProofLedger
from ci.retained_python_namespace_history import (
    LEDGER_PATH, SCHEMA, load_history, parse_records, source_map_digest,
)
from ci.retained_python_ratchet_lineage import audit_candidate_lineage
from repomap_test_support.namespace_projection_fixture import (
    OLD_MODULE_PATH as MODULE_PATH, namespace_case, write_case,
)
from repomap_test_support.retained_ratchet_fixture import (
    BASELINE_PATH, SCOPE_PATH, commit_all, git, write_json,
)
from ci.retained_python_namespace_evidence import document_digest


def test_current_root_import_scan_keeps_edges_and_refuses_lookalikes():
    from ci.python_type_check import _project_imports
    from ci.python_type_ownership import PRODUCT_MODULE_ROOT, is_product_module
    root = PRODUCT_MODULE_ROOT
    assert is_product_module(root) and is_product_module(root + ".retained")
    assert not is_product_module(root + "x.retained")
    tree = ast.parse(f"import {root}.retained\nimport {root}x.lookalike\n")
    assert _project_imports(tree, root, {}) == (root + ".retained",)


def audit(case):
    return audit_candidate_lineage(case.repo, BASELINE_PATH, case.after, SCOPE_PATH,
                                   trusted_genesis_sha256=document_digest(case.before))


def test_actual_worktree_namespace_edge_and_committed_replay(tmp_path):
    case = namespace_case(tmp_path)
    result = audit(case)
    assert result.candidate_transition and result.namespace_transitions == 1
    commit_all(case.repo, "project namespace with exact authority")
    result = audit(case)
    assert not result.candidate_transition and result.namespace_transitions == 1
    assert result.committed_transitions == 1


def test_namespace_rename_without_its_authority_is_still_refused(tmp_path):
    case = namespace_case(tmp_path)
    write_json(case.repo / LEDGER_PATH, {"schema": SCHEMA, "records": []})
    with pytest.raises(LineagePolicyError, match="authority"):
        audit(case)


@pytest.mark.parametrize("change", ["extra", "missing", "copy", "mode", "symlink"])
def test_source_census_and_file_identity_are_not_inferred_from_documents(tmp_path, change):
    case = namespace_case(tmp_path)
    target = case.repo / case.new_path
    if change == "extra":
        target.with_name("extra.py").write_text("value = 2\n")
    elif change == "missing":
        target.unlink()
    elif change == "copy":
        (case.repo / MODULE_PATH).write_text("value = 1\n")
    elif change == "mode":
        target.chmod(0o755)
    else:
        target.unlink()
        target.symlink_to(case.repo / "tools/ci/python_type_ownership.json")
    with pytest.raises(LineagePolicyError):
        audit(case)


def test_resealed_unrelated_code_edit_is_refused(tmp_path):
    case = namespace_case(tmp_path)
    target = case.repo / case.new_path
    target.write_text("value = 2\n")
    case.record["source_files"][0]["after_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    case.record["source_map_sha256"] = source_map_digest(case.record["source_files"])
    write_case(case)
    with pytest.raises(LineagePolicyError, match="closed rewrite"):
        audit(case)


def test_wrong_source_parent_and_double_consumption_are_refused(tmp_path):
    case = namespace_case(tmp_path)
    ledger = NamespaceProofLedger(case.repo, case.source_commit)
    with pytest.raises(LineagePolicyError, match="source revision"):
        ledger.authorize(case.genesis, None, case.before, case.after, {"schema": "repomap-retained-python-scope-transitions-v2", "records": []},
                         projection_edges=set())
    registry = {"schema": "repomap-retained-python-scope-transitions-v2", "records": []}
    assert ledger.authorize(case.source_commit, None, case.before, case.after, registry, projection_edges=set())
    ledger.finish()
    with pytest.raises(LineagePolicyError, match="twice"):
        ledger.authorize(case.source_commit, None, case.before, case.after, registry, projection_edges=set())


def test_namespace_authority_cannot_relabel_an_export_proof(tmp_path):
    case = namespace_case(tmp_path)
    target = commit_all(case.repo, "namespace target")
    ledger = NamespaceProofLedger(case.repo, target)
    with pytest.raises(LineagePolicyError, match="export proof"):
        ledger.authorize(case.source_commit, target, case.before, case.after,
                         {"schema": "repomap-retained-python-scope-transitions-v2", "records": []},
                         projection_edges={(target, case.source_commit)})


def test_namespace_edge_cannot_also_consume_ordinary_scope_authority(tmp_path):
    case = namespace_case(tmp_path)
    row = case.record
    scope = {
        "old_ownership_manifest_sha256": row["before_manifest_sha256"],
        "new_ownership_manifest_sha256": row["after_manifest_sha256"],
        "old_selected_set_sha256": row["before_selection_sha256"],
        "new_selected_set_sha256": row["after_selection_sha256"],
        "source_commit": case.source_commit, "source_manifest_sha256": row["before_manifest_sha256"],
        "phase": "SYNTHETIC-SCOPE", "reason": "Competing authority for one namespace edge",
        "status_path": "tools/ci/synthetic-scope-exit.md", "changes": [],
    }
    ledger = NamespaceProofLedger(case.repo, case.source_commit)
    with pytest.raises(LineagePolicyError, match="ordinary scope authority"):
        ledger.authorize(case.source_commit, None, case.before, case.after,
                         {"schema": "repomap-retained-python-scope-transitions-v2", "records": [scope]},
                         projection_edges=set())


def test_unconsumed_namespace_authority_cannot_hide_in_unchanged_baseline(tmp_path):
    case = namespace_case(tmp_path)
    write_json(case.repo / BASELINE_PATH, case.before)
    with pytest.raises(LineagePolicyError, match="unused"):
        audit_candidate_lineage(case.repo, BASELINE_PATH, case.before, SCOPE_PATH,
                                trusted_genesis_sha256=document_digest(case.before))


@pytest.mark.parametrize("change", ["mutate", "delete-reintroduce", "delete-empty"])
def test_all_initialized_ledger_history_is_append_only(tmp_path, change):
    case = namespace_case(tmp_path)
    path = case.repo / LEDGER_PATH
    if change != "delete-empty":
        commit_all(case.repo, "namespace projection")
    else:
        git(case.repo, "checkout", "--", LEDGER_PATH)
    saved = path.read_bytes()
    if change == "mutate":
        case.record["id"] = "synthetic.changed"
        write_case(case)
    else:
        path.unlink()
        commit_all(case.repo, "delete initialized ledger")
        path.write_bytes(saved)
    with pytest.raises(LineagePolicyError, match="append-only|deleted"):
        load_history(case.repo, git(case.repo, "rev-parse", "HEAD").stdout.strip())


def test_divergent_merge_cannot_drop_namespace_authority(tmp_path):
    case = namespace_case(tmp_path)
    primary = git(case.repo, "branch", "--show-current").stdout.strip()
    git(case.repo, "checkout", "-q", "-b", "projected-side")
    commit_all(case.repo, "namespace side")
    git(case.repo, "checkout", "-q", primary)
    (case.repo / "primary.txt").write_text("primary\n")
    commit_all(case.repo, "advance source side")
    git(case.repo, "merge", "-q", "--no-ff", "--no-commit", "projected-side")
    write_json(case.repo / LEDGER_PATH, {"schema": SCHEMA, "records": []})
    commit_all(case.repo, "drop side authority at merge")
    with pytest.raises(LineagePolicyError, match="append-only"):
        load_history(case.repo, git(case.repo, "rev-parse", "HEAD").stdout.strip())


def test_shallow_clone_cannot_establish_namespace_lineage(tmp_path):
    case = namespace_case(tmp_path)
    commit_all(case.repo, "namespace target")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "--depth=1", case.repo.as_uri(), str(clone))
    with pytest.raises(RatchetContractError, match="shallow"):
        audit_candidate_lineage(clone, BASELINE_PATH, case.after, SCOPE_PATH,
                                trusted_genesis_sha256=document_digest(case.before))


@pytest.mark.parametrize("change", ["unknown-field", "bad-path", "empty-map", "duplicate-key", "duplicate-id", "duplicate-edge"])
def test_namespace_ledger_schema_cannot_admit_unbound_material(tmp_path, change):
    case = namespace_case(tmp_path)
    record = copy.deepcopy(case.record)
    rows = [record]
    if change == "unknown-field":
        record["surplus"] = True
    elif change == "bad-path":
        record["source_files"][0]["after_path"] = "../escape.py"
    elif change == "empty-map":
        record["source_files"] = []
    elif change in {"duplicate-id", "duplicate-edge"}:
        extra = copy.deepcopy(record)
        if change == "duplicate-edge":
            extra["id"] = "synthetic.other"
        rows.append(extra)
    raw = json.dumps({"schema": SCHEMA, "records": rows}).encode()
    if change == "duplicate-key":
        raw = raw.replace(b'"schema":', b'"schema": "ignored", "schema":', 1)
    with pytest.raises(LineagePolicyError):
        parse_records(raw)
