"""Study relation names, identity, table DDL, profiles and the pure catalog SQL expressions.

Readback, fences, index registration and cleanup are the catalog owner's unit
cases; the pgvector owner proves the same SQL against a disposable catalog.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from common_lore_index.storage.semantic_candidates import EmbeddingProfile
from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_study_schema import (
    SCHEMA_CODES, StudyEmbeddingProfile, StudyNames, StudySchemaRefusal, index_catalog_sql, index_comment,
    index_item_sql, inventory_items_sql, make_study_identity, profile_fields, quote, rls_item, table_ddl_sql,
)

SID = "sha256:" + "1" * 64
NAMES = StudyNames(SID)
FORBIDDEN = re.compile(r"IF NOT EXISTS|CASCADE|\bGRANT\b|\bREVOKE\b|\bANALYZE\b|ALTER |OWNER TO|enable_|CREATE ROLE|"
                       r"CREATE SCHEMA|CREATE EXTENSION|pgcrypto|random_page_cost|SET (LOCAL )?(?!ROLE)", re.I)


def _code(call: Any, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(StudySchemaRefusal) as error:
        call(*args, **kwargs)
    return error.value.code


def test_names_are_pure_fixed_pattern_functions_of_study_and_owner() -> None:
    assert re.fullmatch(r"ptx_batch_[0-9a-f]{24}", NAMES.batch_table)
    assert NAMES.entry_table == "ptx_entry_" + NAMES.h and NAMES == StudyNames(SID)
    v1, ptx = NAMES.batch_id(1, ARM_V1), NAMES.batch_id(2, ARM_PTX)
    assert re.fullmatch(r"ptx1-g1-v1-[0-9a-f]{16}", v1) and re.fullmatch(r"ptx1-g2-ptx-[0-9a-f]{16}", ptx)
    assert re.fullmatch(r"ptx_hnsw384_[0-9a-f]{32}", NAMES.index_name(v1))
    assert NAMES.temp_name(v1, "cal-01", 1) != NAMES.temp_name(v1, "cal-01", 2)
    assert StudyNames("sha256:" + "2" * 64).h != NAMES.h
    for bad in ("sha256:" + "A" * 64, "1" * 64, None):
        assert _code(StudyNames, bad) == "study_identity_invalid"
    assert _code(StudyNames, SID, "w5_experiment_reader") == "study_identity_invalid"
    for generation, arm in ((3, ARM_V1), (1, "canonical-node-v3"), (True, ARM_V1)):
        assert _code(NAMES.batch_id, generation, arm) == "study_identity_invalid"
    assert _code(quote, "ptx_batch_" + NAMES.h + "; DROP") == "study_identity_invalid"


def test_study_identity_binds_pins_closure_and_nonce() -> None:
    base = {"task_pins_identity": "sha256:" + "3" * 64, "q_source_closure": "sha256:" + "4" * 64, "nonce": "5" * 32}
    identity = make_study_identity(**base)
    for name, value in (("task_pins_identity", "sha256:" + "6" * 64), ("q_source_closure", "sha256:" + "7" * 64),
                        ("nonce", "8" * 32)):
        assert make_study_identity(**{**base, name: value}) != identity
    for name, value in (("nonce", "5" * 31), ("nonce", "G" * 32), ("q_source_closure", "4" * 64)):
        assert _code(make_study_identity, **{**base, name: value}) == "study_identity_invalid"


def test_table_ddl_has_exact_constraints_and_an_explicit_not_null_v2_descriptor() -> None:
    sql = table_ddl_sql(NAMES)
    assert FORBIDDEN.search(sql) is None and sql.count("CREATE TABLE ") == 2 and sql.count("COMMENT ON TABLE") == 2
    batch_ddl, entry_ddl = sql.split("CREATE TABLE ")[1], sql.split("CREATE TABLE ")[2]
    assert batch_ddl.count("CHECK (") == 14 and batch_ddl.count("UNIQUE (") == 2 and batch_ddl.count("PRIMARY KEY") == 1
    assert entry_ddl.count("CHECK (") == 4 and entry_ddl.count("FOREIGN KEY") == 1 and "RESTRICT" not in entry_ddl
    assert "CHECK (NOT (arm = 'canonical-node-v1' AND capability <> 'complete'))" in batch_ddl
    assert "descriptor_identity IS NULL AND NOT truncated" in entry_ddl
    # A NULL descriptor would otherwise satisfy the regex check vacuously (section 18.1).
    assert f"(arm = '{ARM_PTX}' AND descriptor_identity IS NOT NULL AND descriptor_identity ~ " in entry_ddl
    assert "abs(repomap_vector.vector_norm(embedding) - 1) < 0.00001" in entry_ddl


def test_catalog_expressions_describe_every_child_kind_and_the_index_definition() -> None:
    item = index_item_sql("c", "i")
    for fragment in ("pg_catalog.pg_get_indexdef(c.oid)", "i.indisvalid", "i.indisready", "i.indislive",
                     "obj_description(c.oid, 'pg_class')", "pg_get_userbyid(c.relowner)", "c.relpersistence"):
        assert fragment in item
    inventory = inventory_items_sql("ARRAY['1'::oid]")
    for fragment in ("pg_catalog.pg_index", "pg_catalog.pg_trigger", "NOT xt.tgisinternal", "pg_catalog.pg_rewrite",
                     "pg_catalog.pg_policy", "relrowsecurity", "relforcerowsecurity"):
        assert fragment in inventory
    assert rls_item(7) == "rls|7|false|false"
    batch_id = NAMES.batch_id(1, ARM_PTX)
    query = index_catalog_sql(NAMES, batch_id)
    assert f"'{NAMES.index_name(batch_id)}'" in query and "'item'," in query and FORBIDDEN.search(query) is None
    assert index_comment(NAMES, batch_id) == f"cloe-public-text-study:v1:{SID}:hnsw:{batch_id}"


def test_profiles_are_arm_typed_and_never_cross_substituted() -> None:
    study = StudyEmbeddingProfile("synthetic", "1", "fixture", "1")
    production = EmbeddingProfile("synthetic", "1", "fixture", "1", 384)
    identity, fields = profile_fields(study, ARM_PTX)
    assert fields["representation_version"] == ARM_PTX and identity != production.identity
    assert profile_fields(production, ARM_V1)[1]["representation_version"] == ARM_V1
    assert _code(profile_fields, study, ARM_V1) == "study_profile_invalid"
    assert _code(profile_fields, production, ARM_PTX) == "study_profile_invalid"
    assert _code(profile_fields, EmbeddingProfile("synthetic", "1", "fixture", "1", 3), ARM_V1) == "study_profile_invalid"
    for bad in (StudyEmbeddingProfile("synthetic", "1", "fixture", "1", dimensions=768),
                StudyEmbeddingProfile("synthetic", "1", "fixture", "1", representation_version=ARM_V1),
                StudyEmbeddingProfile("bad model", "1", "fixture", "1")):
        assert _code(lambda: bad.identity) == "study_profile_invalid"


def test_refusal_codes_are_closed() -> None:
    with pytest.raises(ValueError):
        StudySchemaRefusal("not_a_code")
    assert {"study_catalog_children", "study_index_unregistered", "study_index_catalog"} <= SCHEMA_CODES
