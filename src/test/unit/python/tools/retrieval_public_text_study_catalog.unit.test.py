"""Relation readback, child-object inventory fence, index registration, closed index catalog and cleanup.

These cases mutate real readback shapes and SQL text; the pgvector owner proves
the same builders, unknown/replaced children and per-object absence against a
disposable PostgreSQL catalog.
"""

from __future__ import annotations

import copy
from dataclasses import replace
import re
from typing import Any

import pytest

from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_study_catalog import (
    CONSTRAINT_INDEX_FIELDS, INDEX_CATALOG_FIELDS, IndexIdentity, StudyCatalog, absence_sql, build_cleanup_sql,
    build_create_sql, build_index_sql, cleanup_objects, parse_absence, parse_index_catalog, parse_relation_state,
)
from retrieval_public_text_study_schema import (
    BATCH_COLUMNS, ENTRY_COLUMNS, OWNER, StudyNames, StudySchemaRefusal, index_comment,
)

NAMES = StudyNames("sha256:" + "1" * 64)
FORBIDDEN = re.compile(r"IF NOT EXISTS|CASCADE|\bGRANT\b|\bREVOKE\b|\bANALYZE\b|OWNER TO|enable_", re.I)
CONSTRAINTS = {"batch": [("p", ["batch_id"]), ("u", ["batch_id", "arm", "dimensions"]),
                         ("u", ["study_identity", "generation", "arm"])],
               "entry": [("p", ["batch_id", "canonical_key", "source_binding_id"])]}


def _code(call: Any, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(StudySchemaRefusal) as error:
        call(*args, **kwargs)
    return error.value.code


def _constraint(key: str, number: int, rel_oid: int, contype: str, columns: list[str]) -> dict[str, Any]:
    oid, name = rel_oid * 10 + number, f"ptx_{key}_c{number}"
    item = (f"index|{oid}|{name}|{rel_oid}|CREATE UNIQUE INDEX {name} ON repomap_enrichment.t USING btree "
            f"({', '.join(columns)})|true|true|true||{OWNER}|p")
    return {"oid": oid, "name": name, "contype": contype, "columns": columns, "access_method": "btree",
            "has_predicate": False, "has_expressions": False, "valid": True, "ready": True, "item": item}


def _relation(key: str, oid: int) -> dict[str, Any]:
    table = NAMES.batch_table if key == "batch" else NAMES.entry_table
    columns = BATCH_COLUMNS if key == "batch" else ENTRY_COLUMNS
    kinds = ["c"] * 14 + ["p", "u", "u"] if key == "batch" else ["c"] * 4 + ["f", "p"]
    indexes = [_constraint(key, n, oid, t, c) for n, (t, c) in enumerate(CONSTRAINTS[key], 1)]
    return {"oid": oid, "schema": "repomap_enrichment", "name": table, "owner": OWNER, "relkind": "r",
            "relpersistence": "p", "comment": NAMES.comment(key), "definition_sha256": "a" * 64,
            "columns": [list(column) for column in columns], "constraint_kinds": sorted(kinds),
            "constraint_indexes": indexes, "children": sorted([i["item"] for i in indexes] + [f"rls|{oid}|false|false"])}


def _state() -> dict[str, Any]:
    return {"batch": _relation("batch", 101), "entry": _relation("entry", 102)}


def _catalog_payload(catalog: StudyCatalog, batch_id: str, oid: int = 301) -> dict[str, Any]:
    name = NAMES.index_name(batch_id)
    comment = index_comment(NAMES, batch_id)
    item = (f"index|{oid}|{name}|{catalog.record.entry.oid}|CREATE INDEX {name} ON repomap_enrichment.t USING hnsw "
            f"(((embedding)::repomap_vector.vector(384)) repomap_vector.vector_cosine_ops) WHERE "
            f"((batch_id = '{batch_id}'::text) AND (dimensions = 384))|true|true|true|{comment}|{OWNER}|p")
    return {"present": True, "index_oid": oid, "table_oid": catalog.record.entry.oid,
            "index_schema": "repomap_enrichment", "index_name": name, "table_name": NAMES.entry_table,
            "attribute_count": 1, "key_count": 1, "access_method": "hnsw", "opclass_schema": "repomap_vector",
            "opclass_name": "vector_cosine_ops", "is_valid": True, "is_ready": True, "owner": OWNER,
            "comment": comment, "expression": "((embedding)::repomap_vector.vector(384))",
            "predicate": f"((batch_id = '{batch_id}'::text) AND (dimensions = 384))", "reloptions": [], "item": item}


def _registered() -> tuple[StudyCatalog, IndexIdentity]:
    catalog = StudyCatalog(parse_relation_state(_state(), NAMES))
    batch_id = NAMES.batch_id(1, ARM_PTX)
    index = parse_index_catalog(_catalog_payload(catalog, batch_id), catalog, batch_id)
    return catalog.with_index(index), index


def test_readback_records_relations_and_exact_constraint_index_children() -> None:
    record = parse_relation_state(_state(), NAMES)
    assert (record.batch.oid, record.entry.oid) == (101, 102)
    assert [(c.relation, c.oid) for c in record.children] == [("batch", 1011), ("batch", 1012), ("batch", 1013),
                                                             ("entry", 1021)]
    assert record.to_private_dict()["entry"] == {"name": NAMES.entry_table, "oid": 102, "definition_sha256": "a" * 64}
    sql = build_create_sql(NAMES)
    assert sql.startswith("BEGIN ISOLATION LEVEL SERIALIZABLE;") and sql.rstrip().endswith("COMMIT;")
    assert sql.count("to_regclass(") == 2 and "'constraint_indexes'" in sql and "'children'" in sql
    assert FORBIDDEN.search(sql) is None


@pytest.mark.parametrize(("path", "value", "code"), [
    (("batch", "owner"), "w5_experiment_enrichment", "study_relation_owner"),
    (("entry", "relkind"), "v", "study_relation_kind"),
    (("batch", "relpersistence"), "u", "study_relation_kind"),
    (("entry", "comment"), "cloe-public-text-study:v1:foreign:entry", "study_relation_comment"),
    (("batch", "oid"), True, "study_relation_readback"),
    (("entry", "definition_sha256"), "z" * 64, "study_relation_readback"),
    (("batch", "schema"), "public", "study_relation_readback"),
    (("batch", "constraint_kinds"), ["c"] * 13 + ["p", "u", "u"], "study_relation_constraints"),
])
def test_relation_readback_tamper_refuses(path: tuple[str, str], value: object, code: str) -> None:
    state = _state()
    state[path[0]][path[1]] = value
    assert _code(parse_relation_state, state, NAMES) == code


@pytest.mark.parametrize("mutate", [
    lambda s: s["entry"]["children"].append("index|999|ptx_unknown|102|CREATE INDEX x|true|true|true||o|p"),
    lambda s: s["batch"]["children"].append("trigger|101|audit"),
    lambda s: s["entry"]["children"].append("rule|102|r"),
    lambda s: s["entry"]["children"].append("policy|102|p"),
    lambda s: s["entry"]["children"].__setitem__(-1, "rls|102|true|false"),
    lambda s: s["batch"]["constraint_indexes"].pop(),
    lambda s: s["batch"]["constraint_indexes"][0].update(access_method="hash"),
    lambda s: s["batch"]["constraint_indexes"][0].update(has_predicate=True),
    lambda s: s["entry"]["constraint_indexes"][0].update(valid=False),
    lambda s: s["entry"]["constraint_indexes"][0].update(columns=["batch_id"]),
    lambda s: s["entry"]["constraint_indexes"][0].update(extra=1),
    lambda s: s["entry"]["constraint_indexes"][0].update(item="index|1|x|102|def|true|true|true||o|p"),
    lambda s: s["entry"].update(constraint_indexes=None),
    lambda s: s["entry"].pop("children"),
])
def test_unknown_or_altered_children_refuse_at_creation(mutate: Any) -> None:
    state = _state()
    mutate(state)
    assert _code(parse_relation_state, state, NAMES) in {"study_catalog_children", "study_relation_readback"}
    assert set(_relation("entry", 1)["constraint_indexes"][0]) == CONSTRAINT_INDEX_FIELDS


def test_fence_requires_relations_and_the_exact_inventory_of_every_child() -> None:
    catalog, index = _registered()
    items = catalog.expected_items()
    assert items == tuple(sorted(items)) and index.item in items and "rls|101|false|false" in items
    assert len(items) == 4 + 1 + 2
    fence = catalog.fence_sql()
    assert "'101'::oid" in fence and "'102'::oid" in fence and f"= {len(items)}" in fence and " EXCEPT " in fence
    assert all(item.replace("'", "''") in fence for item in items)
    assert "NOT xt.tgisinternal" in fence and "pg_catalog.pg_policy" in fence and "relrowsecurity" in fence
    assert catalog.index_for(index.batch_id) == index and catalog.index_for(NAMES.batch_id(1, ARM_V1)) is None


def test_registration_is_immutable_explicit_and_bound_to_the_derived_name_and_entry_oid() -> None:
    catalog, index = _registered()
    base = StudyCatalog(catalog.record)
    assert base.indexes == () and catalog.indexes == (index,)
    for forged in (replace(index, name=NAMES.index_name(NAMES.batch_id(1, ARM_V1))), replace(index, table_oid=101),
                   replace(index, item=index.item.replace("|true|true|true|", "|false|true|true|")),
                   replace(index, oid=1011), replace(index, batch_id="ptx1-g3-ptx-" + "0" * 16)):
        assert _code(base.with_index, forged) == "study_index_unregistered"
    assert _code(catalog.with_index, index) == "study_index_unregistered"
    assert _code(StudyCatalog, catalog.record, [index]) == "study_index_unregistered"
    assert _code(build_index_sql, catalog, index.batch_id) == "study_identity_invalid"
    sql = build_index_sql(catalog, NAMES.batch_id(1, ARM_V1))
    assert catalog.fence_sql() in sql and "USING hnsw" in sql and " WITH (" not in sql and FORBIDDEN.search(sql) is None


@pytest.mark.parametrize(("name", "value"), [
    ("present", False), ("access_method", "ivfflat"), ("opclass_name", "vector_l2_ops"),
    ("opclass_schema", "public"), ("is_valid", False), ("is_ready", False), ("owner", "w5_experiment_reader"),
    ("comment", None), ("table_oid", 999), ("reloptions", ["m=32"]), ("key_count", 2), ("index_oid", "301"),
    ("index_oid", True), ("expression", "(embedding)::repomap_vector.vector(768)"), ("predicate", None),
    ("predicate", "((batch_id = 'ptx1-g1-v1-0000000000000000'::text) AND (dimensions = 384))"),
    ("item", None), ("item", "index|301|other"),
])
def test_index_catalog_tamper_refuses(name: str, value: object) -> None:
    catalog = StudyCatalog(parse_relation_state(_state(), NAMES))
    batch_id = NAMES.batch_id(1, ARM_PTX)
    payload = copy.deepcopy(_catalog_payload(catalog, batch_id))
    payload[name] = value
    assert _code(parse_index_catalog, payload, catalog, batch_id) == "study_index_catalog"


def test_index_catalog_missing_extra_or_non_mapping_fields_are_closed_refusals() -> None:
    catalog = StudyCatalog(parse_relation_state(_state(), NAMES))
    batch_id = NAMES.batch_id(1, ARM_PTX)
    payload = _catalog_payload(catalog, batch_id)
    assert set(payload) == INDEX_CATALOG_FIELDS
    for key in sorted(INDEX_CATALOG_FIELDS):
        assert _code(parse_index_catalog, {k: v for k, v in payload.items() if k != key}, catalog, batch_id) \
            == "study_index_catalog"
    bad_values: tuple[object, ...] = ({**payload, "acl": None}, [], None, "{}")
    for bad in bad_values:
        assert _code(parse_index_catalog, bad, catalog, batch_id) == "study_index_catalog"


def test_cleanup_fences_every_child_before_any_drop_and_drops_only_registered_indexes() -> None:
    catalog, index = _registered()
    sql = build_cleanup_sql(catalog)
    lock, fence, first_drop = sql.index("LOCK TABLE"), sql.index(catalog.fence_sql()), sql.index("DROP ")
    assert lock < fence < first_drop and "RAISE EXCEPTION 'cleanup_failed:relation_identity_changed'" in sql
    assert sql.count("DROP INDEX") == 1 and f'"{index.name}" RESTRICT' in sql and sql.count("DROP TABLE") == 2
    assert "CASCADE" not in sql and all(c.name not in sql.split("DROP INDEX")[1] for c in catalog.record.children)


def test_cleanup_objects_and_absence_are_per_object() -> None:
    catalog, index = _registered()
    objects = cleanup_objects(NAMES, catalog)
    assert [kind for kind, _n, _o in objects] == ["batch", "entry"] + ["constraint_index"] * 4 + ["index"]
    assert objects[-1] == ("index", index.name, index.oid)
    assert cleanup_objects(NAMES, None) == (("batch", NAMES.batch_table, None), ("entry", NAMES.entry_table, None))
    sql = absence_sql(NAMES, objects)
    assert sql.count("'by_name'") == len(objects) and f"'{index.oid}'::oid" in sql
    rows = [{"by_name": 0, "by_oid": 0}] * 6 + [{"by_name": 1, "by_oid": 1}]
    payload = {"study_identity": NAMES.study_identity, "objects": rows}
    assert parse_absence(payload, NAMES, objects) == (True,) * 6 + (False,)
    for bad in ({**payload, "objects": rows[:-1]}, {**payload, "study_identity": "sha256:" + "2" * 64},
                {**payload, "objects": rows[:-1] + [{"by_name": True, "by_oid": 0}]},
                {**payload, "objects": rows[:-1] + [{"by_name": 0}]}, {**payload, "extra": 1}):
        assert _code(parse_absence, bad, NAMES, objects) == "study_cleanup_readback"
    assert _code(absence_sql, NAMES, (("table", "x", None),)) == "study_cleanup_readback"
