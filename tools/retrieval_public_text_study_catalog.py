"""Study relation readback, child-object inventory fences, owned index and cleanup SQL (study section 18.2).

One SQL item grammar describes every child of the two recorded relations:
each index (OID, name, table OID, ``pg_get_indexdef`` with access method,
opclass, expression, predicate and options, readiness, comment, owner and
persistence), every non-internal trigger, rule and policy, and one row-level
security item per relation. ``StudyCatalog.fence_sql`` requires the recorded
relations unchanged AND that inventory exactly equal to the recorded constraint
indexes plus the registered owned HNSW indexes. Every use and the cleanup run
it; cleanup runs it before any ``DROP`` because ``DROP TABLE ... RESTRICT``
silently removes a table's own indexes and internal triggers.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from common_lore_index.storage.sql_core import sql_literal
from retrieval_public_text_study_schema import (
    BATCH_COLUMNS, BATCH_CONSTRAINT_KINDS, BATCH_ID, DIMENSIONS, ENTRY_COLUMNS, ENTRY_CONSTRAINT_KINDS, SCHEMA,
    StudyNames, fingerprint_sql, index_comment, index_item_sql, inventory_items_sql, qualified, quote, require,
    rls_item, table_ddl_sql,
)
from retrieval_semantic_ann_contracts import _normalized_sql

CONSTRAINT_KEYS = {
    "batch": Counter({("p", ("batch_id",)): 1, ("u", ("batch_id", "arm", "dimensions")): 1,
                      ("u", ("study_identity", "generation", "arm")): 1}),
    "entry": Counter({("p", ("batch_id", "canonical_key", "source_binding_id")): 1}),
}
RELATION_FIELDS = frozenset({
    "oid", "schema", "name", "owner", "relkind", "relpersistence", "comment", "definition_sha256", "columns",
    "constraint_kinds", "children", "constraint_indexes",
})
CONSTRAINT_INDEX_FIELDS = frozenset({
    "oid", "name", "contype", "columns", "access_method", "has_predicate", "has_expressions", "valid", "ready", "item",
})
INDEX_CATALOG_FIELDS = frozenset({
    "present", "index_oid", "table_oid", "index_schema", "index_name", "table_name", "attribute_count", "key_count",
    "access_method", "opclass_schema", "opclass_name", "is_valid", "is_ready", "owner", "comment", "expression",
    "predicate", "reloptions", "item",
})
CLEANUP_KINDS = ("batch", "entry", "constraint_index", "index")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[a-z0-9_]{1,63}\Z")
_MAX_ITEM = 8192


def _ascii_item(value: object, prefix: str, suffix: str) -> bool:
    return (type(value) is str and value.isascii() and len(value) <= _MAX_ITEM and value.startswith(prefix)
            and value.endswith(suffix) and "\n" not in value)


def _constraint_indexes_sql() -> str:
    return ("(SELECT json_agg(json_build_object('oid', xc.oid::bigint, 'name', xc.relname, 'contype', con.contype::text,"
            " 'columns', (SELECT json_agg(a.attname ORDER BY k.ord) FROM unnest(xi.indkey::int2[]) WITH ORDINALITY"
            " k(attnum, ord) JOIN pg_catalog.pg_attribute a ON a.attrelid = xi.indrelid AND a.attnum = k.attnum),"
            " 'access_method', am.amname, 'has_predicate', xi.indpred IS NOT NULL,"
            " 'has_expressions', xi.indexprs IS NOT NULL, 'valid', xi.indisvalid, 'ready', xi.indisready,"
            f" 'item', {index_item_sql('xc', 'xi')}) ORDER BY xc.relname::text COLLATE \"C\")"
            " FROM pg_catalog.pg_index xi JOIN pg_catalog.pg_class xc ON xc.oid = xi.indexrelid"
            " JOIN pg_catalog.pg_am am ON am.oid = xc.relam JOIN pg_catalog.pg_constraint con"
            " ON con.conindid = xc.oid AND con.conrelid = xi.indrelid AND con.contype IN ('p', 'u')"
            " WHERE xi.indrelid = rel.oid)")


def relation_state_sql(names: StudyNames) -> str:
    parts = []
    for key, table in (("batch", names.batch_table), ("entry", names.entry_table)):
        parts.append(
            f"'{key}', (SELECT json_build_object('oid', rel.oid::bigint, 'schema', n.nspname, 'name', rel.relname, "
            "'owner', pg_catalog.pg_get_userbyid(rel.relowner), 'relkind', rel.relkind::text, "
            "'relpersistence', rel.relpersistence::text, 'comment', pg_catalog.obj_description(rel.oid, 'pg_class'), "
            f"'definition_sha256', {fingerprint_sql('rel.oid')}, 'columns', (SELECT json_agg(json_build_array("
            "a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod)) ORDER BY a.attnum) FROM pg_catalog.pg_attribute a"
            " WHERE a.attrelid = rel.oid AND a.attnum > 0 AND NOT a.attisdropped), 'constraint_kinds', (SELECT "
            "json_agg(k.contype::text ORDER BY k.contype) FROM pg_catalog.pg_constraint k WHERE k.conrelid = rel.oid),"
            " 'children', (SELECT json_agg(inventory.item ORDER BY inventory.item COLLATE \"C\") FROM ("
            f"{inventory_items_sql('ARRAY[rel.oid]')}) inventory), 'constraint_indexes', {_constraint_indexes_sql()})"
            " FROM pg_catalog.pg_class rel JOIN pg_catalog.pg_namespace n ON n.oid = rel.relnamespace"
            f" WHERE n.nspname = '{SCHEMA}' AND rel.relname = {sql_literal(table)})")
    return "SELECT json_build_object(" + ", ".join(parts) + ")::text;"


@dataclass(frozen=True)
class RelationIdentity:
    name: str
    oid: int
    fingerprint: str


@dataclass(frozen=True)
class ChildIndex:
    """One constraint-backed index recorded at creation, with its exact catalog item."""

    relation: str
    oid: int
    name: str
    item: str


@dataclass(frozen=True)
class CreationRecord:
    """Private creation identity: both relations and their constraint-index children."""

    names: StudyNames
    batch: RelationIdentity
    entry: RelationIdentity
    children: tuple[ChildIndex, ...]

    def to_private_dict(self) -> dict[str, Any]:
        return {"study_identity": self.names.study_identity, "owner": self.names.owner, **{
            key: {"name": rel.name, "oid": rel.oid, "definition_sha256": rel.fingerprint}
            for key, rel in (("batch", self.batch), ("entry", self.entry))},
            "children": [{"relation": c.relation, "oid": c.oid, "name": c.name, "item": c.item} for c in self.children]}


def _constraint_children(raw: object, key: str, oid: int, owner: str) -> tuple[ChildIndex, ...]:
    require(type(raw) is list, "study_catalog_children")
    assert isinstance(raw, list)
    found: Counter[tuple[str, tuple[str, ...]]] = Counter()
    children = []
    for item in raw:
        require(isinstance(item, Mapping) and set(item) == CONSTRAINT_INDEX_FIELDS, "study_catalog_children")
        index_oid, name, columns = item["oid"], item["name"], item["columns"]
        require(type(index_oid) is int and index_oid > 0 and type(name) is str and _NAME.fullmatch(name) is not None
                and type(columns) is list and all(type(c) is str for c in columns)
                and (item["access_method"], item["has_predicate"], item["has_expressions"], item["valid"],
                     item["ready"]) == ("btree", False, False, True, True)
                and _ascii_item(item["item"], f"index|{index_oid}|{name}|{oid}|", f"|true|true|true||{owner}|p"),
                "study_catalog_children")
        found[(item["contype"], tuple(columns))] += 1
        children.append(ChildIndex(key, index_oid, name, item["item"]))
    require(found == CONSTRAINT_KEYS[key], "study_catalog_children")
    return tuple(children)


def _relation(payload: object, names: StudyNames, key: str) -> tuple[RelationIdentity, tuple[ChildIndex, ...]]:
    table, columns, kinds = ((names.batch_table, BATCH_COLUMNS, BATCH_CONSTRAINT_KINDS) if key == "batch"
                             else (names.entry_table, ENTRY_COLUMNS, ENTRY_CONSTRAINT_KINDS))
    require(isinstance(payload, Mapping) and set(payload) == RELATION_FIELDS, "study_relation_readback")
    assert isinstance(payload, Mapping)
    oid, fingerprint = payload["oid"], payload["definition_sha256"]
    require(type(oid) is int and oid > 0 and type(fingerprint) is str and _HEX64.fullmatch(fingerprint) is not None
            and (payload["schema"], payload["name"]) == (SCHEMA, table), "study_relation_readback")
    require(payload["owner"] == names.owner, "study_relation_owner")
    require((payload["relkind"], payload["relpersistence"]) == ("r", "p"), "study_relation_kind")
    require(payload["comment"] == names.comment(key), "study_relation_comment")
    raw_columns = payload["columns"]
    require(type(raw_columns) is list and tuple(tuple(item) for item in raw_columns if type(item) is list)
            == columns, "study_relation_columns")
    raw_kinds = payload["constraint_kinds"]
    require(type(raw_kinds) is list and all(type(k) is str for k in raw_kinds)
            and Counter(raw_kinds) == Counter(kinds), "study_relation_constraints")
    children = _constraint_children(payload["constraint_indexes"], key, oid, names.owner)
    observed = payload["children"]
    require(type(observed) is list and Counter(observed) == Counter([c.item for c in children] + [rls_item(oid)]),
            "study_catalog_children")
    return RelationIdentity(table, oid, fingerprint), children


def parse_relation_state(payload: object, names: StudyNames) -> CreationRecord:
    require(isinstance(payload, Mapping) and set(payload) == {"batch", "entry"}, "study_relation_readback")
    assert isinstance(payload, Mapping)
    batch, batch_children = _relation(payload["batch"], names, "batch")
    entry, entry_children = _relation(payload["entry"], names, "entry")
    return CreationRecord(names, batch, entry, batch_children + entry_children)


def build_create_sql(names: StudyNames) -> str:
    """One SERIALIZABLE transaction: owner/privilege/before-absence fence, two tables, comments, readback."""
    batch, entry = qualified(names.batch_table), qualified(names.entry_table)
    return f"""BEGIN ISOLATION LEVEL SERIALIZABLE;
DO $ptx_create$
BEGIN
    IF current_user <> {sql_literal(names.owner)} THEN
        RAISE EXCEPTION 'study relations require the HNSW owner';
    END IF;
    IF NOT has_schema_privilege(current_user, '{SCHEMA}', 'CREATE') THEN
        RAISE EXCEPTION 'study owner lacks CREATE on the enrichment schema';
    END IF;
    IF to_regclass({sql_literal(batch)}) IS NOT NULL OR to_regclass({sql_literal(entry)}) IS NOT NULL THEN
        RAISE EXCEPTION 'study relation already exists';
    END IF;
END;
$ptx_create$;
{table_ddl_sql(names)}
{relation_state_sql(names)}
COMMIT;"""


@dataclass(frozen=True)
class IndexIdentity:
    """One registered owned HNSW index; produced only by ``parse_index_catalog``."""

    name: str
    batch_id: str
    oid: int
    table_oid: int
    item: str


def _index_bound(names: StudyNames, record: CreationRecord, index: object) -> bool:
    if type(index) is not IndexIdentity or type(index.batch_id) is not str or BATCH_ID.fullmatch(index.batch_id) is None:
        return False
    return (index.name == names.index_name(index.batch_id) and type(index.oid) is int and index.oid > 0
            and index.table_oid == record.entry.oid
            and _ascii_item(index.item, f"index|{index.oid}|{index.name}|{record.entry.oid}|",
                            f"|true|true|true|{index_comment(names, index.batch_id)}|{names.owner}|p"))


@dataclass(frozen=True)
class StudyCatalog:
    """Immutable creation record plus explicitly registered owned indexes; no hidden registry."""

    record: CreationRecord
    indexes: tuple[IndexIdentity, ...] = ()

    def __post_init__(self) -> None:
        record = self.record
        require(type(record) is CreationRecord and type(self.indexes) is tuple, "study_index_unregistered")
        require(all(_index_bound(record.names, record, index) for index in self.indexes), "study_index_unregistered")
        oids = [index.oid for index in self.indexes] + [child.oid for child in record.children]
        require(len({i.batch_id for i in self.indexes}) == len(self.indexes) and len(set(oids)) == len(oids),
                "study_index_unregistered")

    @property
    def names(self) -> StudyNames:
        return self.record.names

    def with_index(self, index: IndexIdentity) -> StudyCatalog:
        return StudyCatalog(self.record, (*self.indexes, index))

    def index_for(self, batch_id: str) -> IndexIdentity | None:
        return next((index for index in self.indexes if index.batch_id == batch_id), None)

    def expected_items(self) -> tuple[str, ...]:
        record = self.record
        return tuple(sorted([c.item for c in record.children] + [i.item for i in self.indexes]
                            + [rls_item(record.batch.oid), rls_item(record.entry.oid)]))

    def _relations_sql(self) -> str:
        record, clauses = self.record, []
        for key, rel in (("batch", record.batch), ("entry", record.entry)):
            clauses.append(
                "EXISTS (SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
                f" WHERE c.oid = '{rel.oid}'::oid AND n.nspname = '{SCHEMA}' AND c.relname = {sql_literal(rel.name)}"
                " AND c.relkind = 'r' AND c.relpersistence = 'p'"
                f" AND pg_catalog.pg_get_userbyid(c.relowner) = {sql_literal(record.names.owner)}"
                f" AND pg_catalog.obj_description(c.oid, 'pg_class') = {sql_literal(record.names.comment(key))}"
                f" AND {fingerprint_sql('c.oid')} = {sql_literal(rel.fingerprint)})")
        return " AND ".join(clauses)

    def fence_sql(self) -> str:
        """Boolean SQL: recorded relations unchanged AND the child inventory exactly as recorded/registered."""
        items = self.expected_items()
        oids = f"ARRAY['{self.record.batch.oid}'::oid, '{self.record.entry.oid}'::oid]"
        expected = "ARRAY[" + ", ".join(sql_literal(item) for item in items) + "]::text[]"
        inventory = inventory_items_sql(oids)
        return (f"({self._relations_sql()} AND (SELECT count(*) FROM ({inventory}) inventory) = {len(items)}"
                f" AND NOT EXISTS (SELECT inventory.item FROM ({inventory}) inventory EXCEPT SELECT unnest({expected})))")

    def to_private_dict(self) -> dict[str, Any]:
        return {**self.record.to_private_dict(), "indexes": [
            {"name": i.name, "batch_id": i.batch_id, "oid": i.oid, "item": i.item} for i in self.indexes]}


def build_index_sql(catalog: StudyCatalog, batch_id: str) -> str:
    """One owned partial HNSW index per imported batch, default build parameters, behind the full fence."""
    names = catalog.names
    require(type(batch_id) is str and BATCH_ID.fullmatch(batch_id) is not None
            and catalog.index_for(batch_id) is None, "study_identity_invalid")
    index = quote(names.index_name(batch_id))
    return f"""BEGIN;
DO $ptx_index$
BEGIN
    IF current_user <> {sql_literal(names.owner)} OR NOT {catalog.fence_sql()} THEN
        RAISE EXCEPTION 'study relation identity changed';
    END IF;
END;
$ptx_index$;
CREATE INDEX {index} ON {qualified(names.entry_table)} USING hnsw
    ((embedding::repomap_vector.vector({DIMENSIONS})) repomap_vector.vector_cosine_ops)
    WHERE batch_id = {sql_literal(batch_id)} AND dimensions = {DIMENSIONS};
COMMENT ON INDEX {SCHEMA}.{index} IS {sql_literal(index_comment(names, batch_id))};
COMMIT;"""


def parse_index_catalog(payload: object, catalog: StudyCatalog, batch_id: str) -> IndexIdentity:
    """Closed keys, strict types, exact method/opclass/expression/predicate/readiness/owner/comment/OIDs/item."""
    names, record = catalog.names, catalog.record
    require(isinstance(payload, Mapping) and set(payload) == INDEX_CATALOG_FIELDS and payload["present"] is True
            and type(batch_id) is str and BATCH_ID.fullmatch(batch_id) is not None, "study_index_catalog")
    assert isinstance(payload, Mapping)
    strings = ("index_schema", "index_name", "table_name", "access_method", "opclass_schema", "opclass_name", "owner",
               "comment", "expression", "predicate", "item")
    require(all(type(payload[name]) is str for name in strings)
            and all(type(payload[name]) is int for name in ("index_oid", "table_oid", "attribute_count", "key_count"))
            and type(payload["reloptions"]) is list, "study_index_catalog")
    expected = {f"(batch_id='{batch_id}'::text)and(dimensions={DIMENSIONS})",
                f"(batch_id='{batch_id}')and(dimensions={DIMENSIONS})"}
    require(
        payload["index_oid"] > 0 and payload["table_oid"] == record.entry.oid
        and (payload["index_schema"], payload["index_name"], payload["table_name"])
        == (SCHEMA, names.index_name(batch_id), names.entry_table)
        and (payload["attribute_count"], payload["key_count"], payload["reloptions"]) == (1, 1, [])
        and (payload["access_method"], payload["opclass_schema"], payload["opclass_name"])
        == ("hnsw", "repomap_vector", "vector_cosine_ops")
        and payload["is_valid"] is True and payload["is_ready"] is True and payload["owner"] == names.owner
        and payload["comment"] == index_comment(names, batch_id)
        and _normalized_sql(payload["expression"]) in {f"embedding::repomap_vector.vector({DIMENSIONS})",
                                                       f"(embedding)::repomap_vector.vector({DIMENSIONS})"}
        and _normalized_sql(payload["predicate"]) in expected, "study_index_catalog")
    identity = IndexIdentity(names.index_name(batch_id), batch_id, payload["index_oid"], payload["table_oid"],
                             payload["item"])
    require(_index_bound(names, record, identity), "study_index_catalog")
    return identity


def cleanup_objects(names: StudyNames, catalog: StudyCatalog | None) -> tuple[tuple[str, str, int | None], ...]:
    """Every object whose absence cleanup must prove, each with its own recorded OID."""
    if catalog is None:
        return (("batch", names.batch_table, None), ("entry", names.entry_table, None))
    record = catalog.record
    return (("batch", record.batch.name, record.batch.oid), ("entry", record.entry.name, record.entry.oid),
            *(("constraint_index", c.name, c.oid) for c in record.children),
            *(("index", i.name, i.oid) for i in catalog.indexes))


def build_cleanup_sql(catalog: StudyCatalog) -> str:
    """Lock, then the full fence BEFORE any drop; then RESTRICT drops (owned indexes, entry, batch)."""
    names = catalog.names
    drops = "".join(f"DROP INDEX {SCHEMA}.{quote(index.name)} RESTRICT;\n" for index in catalog.indexes)
    return f"""BEGIN;
LOCK TABLE {qualified(names.batch_table)}, {qualified(names.entry_table)} IN ACCESS EXCLUSIVE MODE;
DO $ptx_cleanup$
BEGIN
    IF current_user <> {sql_literal(names.owner)} OR NOT {catalog.fence_sql()} THEN
        RAISE EXCEPTION 'cleanup_failed:relation_identity_changed';
    END IF;
END;
$ptx_cleanup$;
{drops}DROP TABLE {qualified(names.entry_table)} RESTRICT;
DROP TABLE {qualified(names.batch_table)} RESTRICT;
COMMIT;"""


def _objects_ok(objects: Sequence[tuple[str, str, int | None]]) -> bool:
    return bool(objects) and all(
        type(item) is tuple and len(item) == 3 and item[0] in CLEANUP_KINDS and type(item[1]) is str
        and _NAME.fullmatch(item[1]) is not None and (item[2] is None or (type(item[2]) is int and item[2] > 0))
        for item in objects)


def absence_sql(names: StudyNames, objects: Sequence[tuple[str, str, int | None]]) -> str:
    """Independent per-object absence readback by schema/name and by recorded OID."""
    require(_objects_ok(objects), "study_cleanup_readback")
    rows = []
    for _kind, name, oid in objects:
        by_oid = "0" if oid is None else f"(SELECT count(*) FROM pg_catalog.pg_class WHERE oid = '{oid}'::oid)"
        rows.append("json_build_object('by_name', (SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog."
                    f"pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = '{SCHEMA}' AND c.relname = "
                    f"{sql_literal(name)}), 'by_oid', {by_oid})")
    return (f"SELECT json_build_object('study_identity', {sql_literal(names.study_identity)}, 'objects', "
            f"json_build_array({', '.join(rows)}))::text;")


def parse_absence(payload: object, names: StudyNames, objects: Sequence[tuple[str, str, int | None]]) -> tuple[bool, ...]:
    """One absence fact per object, in object order; any other shape refuses."""
    require(isinstance(payload, Mapping) and set(payload) == {"study_identity", "objects"}
            and payload["study_identity"] == names.study_identity and type(payload["objects"]) is list
            and len(payload["objects"]) == len(objects), "study_cleanup_readback")
    assert isinstance(payload, Mapping)
    result = []
    for row in payload["objects"]:
        require(isinstance(row, Mapping) and set(row) == {"by_name", "by_oid"} and type(row["by_name"]) is int
                and type(row["by_oid"]) is int and row["by_name"] >= 0 and row["by_oid"] >= 0, "study_cleanup_readback")
        result.append(row["by_name"] == 0 and row["by_oid"] == 0)
    return tuple(result)


__all__ = [
    "CLEANUP_KINDS", "CONSTRAINT_INDEX_FIELDS", "CONSTRAINT_KEYS", "ChildIndex", "CreationRecord",
    "INDEX_CATALOG_FIELDS", "IndexIdentity", "RELATION_FIELDS", "RelationIdentity", "StudyCatalog", "absence_sql",
    "build_cleanup_sql", "build_create_sql", "build_index_sql", "cleanup_objects", "parse_absence",
    "parse_index_catalog", "parse_relation_state", "relation_state_sql",
]
