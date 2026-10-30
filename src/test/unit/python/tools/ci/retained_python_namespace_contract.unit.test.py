"""Pure ADR0123 namespace projection contracts for ownership and baselines."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Callable

import pytest

from ci.retained_python_contract import LineagePolicyError
from ci.retained_python_namespace_contract import (
    NEW_PREFIX,
    NEW_ROOT,
    OLD_PREFIX,
    OLD_ROOT,
    NamespaceProjectionError,
    audit_namespace_documents,
    project_baseline,
    project_ownership_manifest,
    rewrite_module,
    rewrite_namespace_text,
    rewrite_product_path,
)
from ci.retained_python_records import BASELINE_SCHEMA


Mutation = Callable[[dict], None]
CODE = "attr-defined"
TYPED = 'Module "{root}.graph" has no attribute "missing"'
OPAQUE = hashlib.sha256(b"opaque untranslated mypy preimage").hexdigest()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def entry(prefix: str, ownership_class: str = "python_retained", tier: str = "T1-future") -> dict:
    return {
        "architecture_box": "go_control_and_api",
        "disposition": "retained_python_ratcheted",
        "enforcement_tier": tier,
        "justification": f"Keep {OLD_ROOT}.__main__ and `{prefix}` prose unchanged.",
        "match": "subtree",
        "module_prefix": prefix,
        "ownership_class": ownership_class,
    }


def manifest(*entries: dict) -> bytes:
    document = {
        "entries": list(entries) or [
            entry(OLD_ROOT),
            entry(f"{OLD_ROOT}.contract", "cross_language_contract", "T0"),
            entry(f"{OLD_ROOT}.legacy", "transitional_python", "T2"),
        ],
        "resolution": "longest-component-prefix-wins",
        "schema": "repomap-python-type-ownership-v1",
    }
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()


def ruff(path: str, message: str, count: int = 1) -> dict:
    return {"path": path, "code": "F401", "message": message,
            "fingerprint": sha(f"{path}\0F401\0{message}"), "count": count}


def baseline(root: str, digest: str, typed_fingerprint: str) -> dict:
    prefix = f"src/main/python/{root}/"
    keys = f"{prefix}graph/keys.py"
    findings = [ruff(keys, "`os` imported but unused"),
                ruff(keys, f"`{root}.graph.env_key` imported but unused", 2)]
    return {
        "schema": BASELINE_SCHEMA,
        "ownership": {"manifest_path": "tools/ci/python_type_ownership.json", "sha256": digest},
        "tools": {"mypy": "2.1.0", "ruff": "0.16.2", "ruff_rules": ["F"], "ruff_target_version": "py312"},
        "selection": {
            "ownership_classes": ["cross_language_contract", "python_retained"],
            "tiers": ["T0", "T1-future", "T1-seed"],
            "modules": [
                {"module": root, "path": f"{prefix}__init__.py",
                 "ownership_class": "python_retained", "tier": "T1-future"},
                {"module": f"{root}.contract", "path": f"{prefix}contract.py",
                 "ownership_class": "cross_language_contract", "tier": "T0"},
                {"module": f"{root}.graph", "path": f"{prefix}graph/__init__.py",
                 "ownership_class": "python_retained", "tier": "T1-future"},
                {"module": f"{root}.graph.keys", "path": keys,
                 "ownership_class": "python_retained", "tier": "T1-future"},
            ],
        },
        "ruff": {"findings": sorted(findings, key=lambda item: (
            item["path"], item["code"], item["message"], item["fingerprint"]))},
        "mypy": {"findings": [
            {"module": f"{root}.graph", "path": f"{prefix}graph/__init__.py", "error_code": CODE,
             "normalized_fingerprint": typed_fingerprint, "count": 2},
            {"module": f"{root}.graph.keys", "path": keys, "error_code": "misc",
             "normalized_fingerprint": OPAQUE, "count": 1},
        ]},
        "migration_direction_imports": {"edges": [
            {"source_module": f"{root}.graph.keys", "source_path": keys,
             "target_module": f"{root}.legacy", "target_tier": "T2"},
        ]},
        "file_length": {"warning_limit": 400, "failure_limit": 1000,
                        "ceilings": [{"path": keys, "line_count": 512}]},
    }


def translation(before: str | None = None, after: str | None = None) -> dict:
    before = TYPED.format(root=OLD_ROOT) if before is None else before
    after = TYPED.format(root=NEW_ROOT) if after is None else after
    return {"error_code": CODE, "before_fingerprint": sha(f"{CODE}\0{before}"),
            "after_fingerprint": sha(f"{CODE}\0{after}"), "before_message": before, "after_message": after}


OWNERSHIP_BEFORE = manifest()
OWNERSHIP_AFTER = OWNERSHIP_BEFORE.replace(b'"module_prefix": "repomap_kg', b'"module_prefix": "common_lore_index')
BEFORE = baseline(OLD_ROOT, hashlib.sha256(OWNERSHIP_BEFORE).hexdigest(), sha(f"{CODE}\0{TYPED.format(root=OLD_ROOT)}"))
AFTER = baseline(NEW_ROOT, hashlib.sha256(OWNERSHIP_AFTER).hexdigest(), sha(f"{CODE}\0{TYPED.format(root=NEW_ROOT)}"))


def test_root_constants_and_error_lineage_are_exact() -> None:
    assert (OLD_ROOT, NEW_ROOT) == ("repomap_kg", "common_lore_index")
    assert (OLD_PREFIX, NEW_PREFIX) == ("src/main/python/repomap_kg/", "src/main/python/common_lore_index/")
    assert issubclass(NamespaceProjectionError, LineagePolicyError)


def test_module_and_path_rewrite_exact_root_boundaries() -> None:
    assert rewrite_module("repomap_kg") == "common_lore_index"
    assert rewrite_module("repomap_kg.cli.__main__") == "common_lore_index.cli.__main__"
    assert rewrite_product_path(f"{OLD_PREFIX}third_party_licenses/LICENSE.txt") == (
        f"{NEW_PREFIX}third_party_licenses/LICENSE.txt")


@pytest.mark.parametrize("value", [
    "repomap_kgx", "repomap_kg_extra.cli", "xrepomap_kg", "common_lore_index", "common_lore_index.cli",
    "repomap_kg.", "repomap_kg..cli", ".repomap_kg", "repomap_kg.cli-x", "repomap_kg/cli",
    "repomap_kg.cli\n", "", "repomap-kg", 3, None, b"repomap_kg",
])
def test_module_rewrite_refuses_unknown_look_alike_new_and_malformed(value: str) -> None:
    with pytest.raises(NamespaceProjectionError, match="namespace module"):
        rewrite_module(value)


@pytest.mark.parametrize("value", [
    OLD_PREFIX, f"{OLD_PREFIX}a/", f"{OLD_PREFIX}a//b.py", f"{OLD_PREFIX}../x.py", f"{OLD_PREFIX}a/../b.py",
    f"{OLD_PREFIX}./a.py", f"{OLD_PREFIX}a\\b.py", f"/{OLD_PREFIX}a.py", f"./{OLD_PREFIX}a.py",
    "src/main/python/repomap_kg_extra/a.py", f"{NEW_PREFIX}a.py", "src/main/python/repomap_kg",
    f"{OLD_PREFIX}a\0.py", 7, None,
])
def test_product_path_rewrite_refuses_escape_empty_and_foreign_prefix(value: str) -> None:
    with pytest.raises(NamespaceProjectionError, match="product path"):
        rewrite_product_path(value)


def test_namespace_text_rewrites_only_exact_spellings() -> None:
    text = ("`repomap_kg.a` src/main/python/repomap_kg/x.py repomap_kg repomap_kgx xrepomap_kg "
            "repomap_kg_extra share/repomap_kg repomap-kg pkg.repomap_kg")
    assert rewrite_namespace_text(text) == (
        "`common_lore_index.a` src/main/python/common_lore_index/x.py common_lore_index repomap_kgx "
        "xrepomap_kg repomap_kg_extra share/repomap_kg repomap-kg pkg.repomap_kg")
    with pytest.raises(NamespaceProjectionError, match="successor root"):
        rewrite_namespace_text("repomap_kg and common_lore_index")


def test_ownership_projection_changes_only_prefix_values() -> None:
    assert project_ownership_manifest(OWNERSHIP_BEFORE) == OWNERSHIP_AFTER
    assert b"Keep repomap_kg.__main__ and `repomap_kg.contract` prose" in OWNERSHIP_AFTER
    spaced = OWNERSHIP_BEFORE.replace(b'"module_prefix": ', b'"module_prefix"\t :  ')
    assert project_ownership_manifest(spaced) == spaced.replace(
        b'"module_prefix"\t :  "repomap_kg', b'"module_prefix"\t :  "common_lore_index')


@pytest.mark.parametrize("raw", [
    manifest(entry(OLD_ROOT), entry(OLD_ROOT)),
    manifest(entry(f"{OLD_ROOT}.b"), entry(f"{OLD_ROOT}.a")),
    manifest(entry("repomap_kgx")),
    manifest(entry(NEW_ROOT)),
    manifest(entry(OLD_ROOT) | {"note": "unknown"}),
    manifest(entry(OLD_ROOT, "python_retained", "T0")),
    manifest(entry(OLD_ROOT) | {"match": "prefix"}),
    OWNERSHIP_BEFORE.replace(b'"match": "subtree",', b'"match": "subtree", "match": "subtree",', 1),
    OWNERSHIP_BEFORE.replace(b'"repomap_kg.contract"', b'"repomap_kg.\\u0063ontract"'),
    OWNERSHIP_BEFORE.replace(b"repomap-python-type-ownership-v1", b"repomap-python-type-ownership-v2"),
    b"\xff" + OWNERSHIP_BEFORE,
    b"[]",
])
def test_ownership_projection_refuses_invalid_or_colliding_manifests(raw: bytes) -> None:
    with pytest.raises(NamespaceProjectionError):
        project_ownership_manifest(raw)


def project(before: dict, rows: object = None) -> dict:
    return dict(project_baseline(
        before,
        ownership_sha256=hashlib.sha256(OWNERSHIP_AFTER).hexdigest(),
        mypy_translations=[translation()] if rows is None else rows,
    ))


def test_baseline_projection_is_exact_reordered_and_preserves_debt() -> None:
    before = copy.deepcopy(BEFORE)
    assert project(before) == AFTER
    assert before == BEFORE
    assert [item["message"] for item in BEFORE["ruff"]["findings"]][0].startswith("`os`")
    assert [item["message"] for item in AFTER["ruff"]["findings"]][0].startswith("`common_lore_index")


def test_untranslated_fingerprint_retains_its_exact_ceiling() -> None:
    projected = project(BEFORE, rows=())
    assert projected["mypy"]["findings"][0]["normalized_fingerprint"] == BEFORE["mypy"]["findings"][0][
        "normalized_fingerprint"]
    assert projected["mypy"]["findings"][1]["normalized_fingerprint"] == OPAQUE
    assert [item["count"] for item in projected["mypy"]["findings"]] == [2, 1]


def _set(section: str, index: int, field: str, value: object) -> Mutation:
    def mutate(document: dict) -> None:
        container = document["selection" if section == "modules" else section]
        records = container[{"ruff": "findings", "mypy": "findings", "modules": "modules",
                             "migration_direction_imports": "edges", "file_length": "ceilings"}[section]]
        records[index][field] = value
    return mutate


@pytest.mark.parametrize("mutation,reason", [
    (_set("modules", 3, "module", "repomap_kgx.keys"), "namespace root"),
    (_set("modules", 0, "module", NEW_ROOT), "namespace root"),
    (_set("modules", 3, "path", "src/main/python/repomap_kg_extra/keys.py"), "predecessor prefix"),
    (_set("ruff", 0, "fingerprint", "0" * 64), "Ruff predecessor fingerprint"),
    (_set("ruff", 1, "message", "`repomap_kg.graph.tool_key` imported but unused"), "Ruff predecessor"),
    (_set("mypy", 0, "module", "other.graph"), "namespace root"),
    (_set("migration_direction_imports", 0, "target_module", "repomap_kgx.legacy"), "namespace root"),
    (_set("migration_direction_imports", 0, "target_module", f"{NEW_ROOT}.legacy"), "namespace root"),
    (_set("file_length", 0, "path", "src/main/python/other/keys.py"), "predecessor prefix"),
    (lambda document: document.update(extra={}), "predecessor baseline is invalid"),
    (lambda document: document["tools"].update(ruff="0.16.3"), "predecessor baseline is invalid"),
])
def test_baseline_projection_refuses_partial_unknown_or_tampered_records(
    mutation: Mutation, reason: str
) -> None:
    before = copy.deepcopy(BEFORE)
    mutation(before)
    with pytest.raises(NamespaceProjectionError, match=reason):
        project(before)


def test_baseline_projection_refuses_mypy_identity_collision() -> None:
    before = copy.deepcopy(BEFORE)
    colliding = dict(before["mypy"]["findings"][0], normalized_fingerprint=AFTER["mypy"]["findings"][0][
        "normalized_fingerprint"], count=1)
    before["mypy"]["findings"][:1] = sorted([before["mypy"]["findings"][0], colliding],
                                            key=lambda item: item["normalized_fingerprint"])
    with pytest.raises(NamespaceProjectionError, match="collides mypy"):
        project(before)


def test_baseline_projection_refuses_invalid_successor_digest() -> None:
    with pytest.raises(NamespaceProjectionError, match="digest"):
        project_baseline(BEFORE, ownership_sha256="A" * 64, mypy_translations=[translation()])


@pytest.mark.parametrize("rows,reason", [
    ([translation() | {"before_fingerprint": "0" * 64}], "forged"),
    ([translation() | {"after_fingerprint": "0" * 64}], "forged"),
    ([translation(after='Module "common_lore_index.graph" has no attribute "other"')], "exact namespace rewrite"),
    ([translation(after='Module "repomap_kg.graph" has no attribute "missing"')], "exact namespace rewrite"),
    ([translation(before='Name "x" is not defined', after='Name "x" is not defined')], "identity"),
    ([translation(), translation()], "duplicate"),
    ([translation(), translation('Module "repomap_kg.cli" has no attribute "x"',
                                 'Module "common_lore_index.cli" has no attribute "x"')], "unused"),
    ([translation() | {"note": "extra"}], "fields"),
    ([{key: value for key, value in translation().items() if key != "after_message"}], "fields"),
    ([translation() | {"error_code": ""}], "values"),
    ([translation('Module "repomap_kg.graph" line 12', 'Module "common_lore_index.graph" line 12')],
     "normalized"),
    ([translation('Module  "repomap_kg.graph"', 'Module  "common_lore_index.graph"')], "normalized"),
    ("rows", "row sequence"),
    ([["row"]], "fields"),
])
def test_mypy_translations_refuse_forged_identity_duplicate_and_unused(rows: object, reason: str) -> None:
    with pytest.raises(NamespaceProjectionError, match=reason):
        project(BEFORE, rows=rows)


def audit(after: dict, *, ownership_after: bytes = OWNERSHIP_AFTER, rows: object = None) -> None:
    audit_namespace_documents(
        BEFORE, after, ownership_before=OWNERSHIP_BEFORE, ownership_after=ownership_after,
        mypy_translations=[translation()] if rows is None else rows,
    )


def test_audit_accepts_exact_projection() -> None:
    audit(copy.deepcopy(AFTER))


def _insert_module(document: dict) -> None:
    document["selection"]["modules"].insert(2, {
        "module": f"{NEW_ROOT}.extra", "path": f"{NEW_PREFIX}extra.py",
        "ownership_class": "python_retained", "tier": "T1-future"})


def _retarget(document: dict) -> None:
    document["selection"]["modules"][1].update(ownership_class="python_retained", tier="T1-seed")


def _retouch(document: dict) -> None:
    document["ruff"]["findings"][1] = ruff(f"{NEW_PREFIX}graph/keys.py", "`sys` imported but unused")


@pytest.mark.parametrize("mutation,reason", [
    (_set("ruff", 0, "count", 3), "adds Ruff debt"),
    (_set("ruff", 0, "count", 1), "erases Ruff debt"),
    (_retouch, "changes Ruff debt"),
    (lambda document: document["mypy"]["findings"].pop(), "erases mypy debt"),
    (_set("mypy", 0, "count", 3), "adds mypy debt"),
    (_set("mypy", 1, "normalized_fingerprint", "f" * 64), "changes mypy debt"),
    (lambda document: document["migration_direction_imports"]["edges"].clear(), "erases import-edge debt"),
    (_set("migration_direction_imports", 0, "target_tier", "T3"), "changes import-edge debt"),
    (_set("file_length", 0, "line_count", 450), "erases file-length debt"),
    (_set("file_length", 0, "line_count", 600), "adds file-length debt"),
    (lambda document: document["selection"]["modules"].pop(), "erases selected modules"),
    (_insert_module, "adds selected modules"),
    (_retarget, "changes selected modules"),
    (lambda document: document["tools"].update(ruff="0.16.3"), "successor baseline is invalid"),
    (lambda document: document["selection"].update(tiers=["T0", "T1-future"]), "successor baseline is invalid"),
    (lambda document: document.update(extra={}), "successor baseline is invalid"),
    (lambda document: document["ownership"].update(manifest_path="tools/ci/other.json"), "ownership record"),
])
def test_audit_refuses_hidden_debt_policy_and_selection_changes(mutation: Mutation, reason: str) -> None:
    after = copy.deepcopy(AFTER)
    mutation(after)
    with pytest.raises(NamespaceProjectionError, match=reason):
        audit(after)


def test_audit_binds_manifest_bytes_and_exact_manifest_projection() -> None:
    with pytest.raises(NamespaceProjectionError, match="successor ownership digest"):
        audit(copy.deepcopy(AFTER), ownership_after=OWNERSHIP_AFTER + b"\n")
    changed = OWNERSHIP_AFTER.replace(b"prose unchanged", b"prose rewritten", 1)
    after = copy.deepcopy(AFTER)
    after["ownership"]["sha256"] = hashlib.sha256(changed).hexdigest()
    with pytest.raises(NamespaceProjectionError, match="not the exact projection"):
        audit(after, ownership_after=changed)
    retiered = OWNERSHIP_AFTER.replace(b'"enforcement_tier": "T2"', b'"enforcement_tier": "T3"').replace(
        b'"transitional_python"', b'"planned_go"')
    after["ownership"]["sha256"] = hashlib.sha256(retiered).hexdigest()
    with pytest.raises(NamespaceProjectionError, match="not the exact projection"):
        audit(after, ownership_after=retiered)
    with pytest.raises(NamespaceProjectionError, match="predecessor ownership digest"):
        audit_namespace_documents(BEFORE, copy.deepcopy(AFTER), ownership_before=OWNERSHIP_BEFORE + b" ",
                                  ownership_after=OWNERSHIP_AFTER, mypy_translations=[translation()])


def test_audit_requires_the_same_translation_table() -> None:
    with pytest.raises(NamespaceProjectionError, match="changes mypy debt"):
        audit(copy.deepcopy(AFTER), rows=())
    untranslated = copy.deepcopy(AFTER)
    untranslated["mypy"]["findings"][0]["normalized_fingerprint"] = BEFORE["mypy"]["findings"][0][
        "normalized_fingerprint"]
    with pytest.raises(NamespaceProjectionError, match="changes mypy debt"):
        audit(untranslated)
    audit(untranslated, rows=())


def test_audit_errors_are_bounded_without_private_payloads() -> None:
    after = copy.deepcopy(AFTER)
    after["ruff"]["findings"][1] = ruff(f"{NEW_PREFIX}graph/keys.py", "`private-token-8c1f` imported but unused")
    with pytest.raises(NamespaceProjectionError) as caught:
        audit(after)
    assert "private-token-8c1f" not in str(caught.value)
    assert len(str(caught.value)) < 120
