"""Study names, identity, profiles, closed codes, table DDL and catalog SQL expressions (sections 8, 18.1-18.2).

Every statement runs as the existing HNSW owner in ``repomap_enrichment``. No
role, grant, schema, extension, ``IF NOT EXISTS``, ``CASCADE``, owner change or
``ANALYZE`` is emitted. Identifiers come only from fixed patterns derived from
the study identity; values use ``sql_literal``. This owner also holds the pure
catalog SQL expressions (child item grammar, fingerprint, owned-index catalog
query); the records, fences, registration and cleanup that use them live in
``retrieval_public_text_study_catalog``, and the batch import in
``retrieval_public_text_study_queries``.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from common_lore_index.storage.semantic_candidates import EmbeddingProfile, checked_identity, digest_json
from common_lore_index.storage.sql_core import sql_literal
from retrieval_public_text_request import ARM_PTX, ARM_V1, STUDY_PHASE
from retrieval_semantic_ann_sql import DEFAULT_OWNER_IDENTITY

STUDY_SCHEMA = "cloe-public-text-study-v1"
STUDY_PROFILE_SCHEMA = "cloe-public-text-study-profile-v1"
OWNER = DEFAULT_OWNER_IDENTITY
SCHEMA = "repomap_enrichment"
DIMENSIONS = 384
MAX_ROWS = 500
COMMENT_PREFIX = "cloe-public-text-study:v1:"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_IDENT = re.compile(r"(ptx_batch|ptx_entry)_[0-9a-f]{24}\Z|ptx_hnsw384_[0-9a-f]{32}\Z|ptx_ann_[0-9a-f]{16}\Z")
BATCH_ID = re.compile(r"ptx1-g([12])-(v1|ptx)-[0-9a-f]{16}\Z")
BATCH_COLUMNS = tuple((name, "text") for name in (
    "batch_id", "study_identity", "arm", "repository_identity", "receipt_identity", "source_generation",
    "config_generation", "extractor_generation", "canonicalizer_generation", "publication_bundle_id",
    "snapshot_manifest_id", "profile_identity", "model", "model_version", "generator", "generator_version",
    "representation_version", "normalization", "metric", "privacy_class", "input_identity", "seal_identity",
    "capability",
)) + (("generation", "integer"), ("run_id", "bigint"), ("dimensions", "integer"), ("row_count", "integer"))
ENTRY_COLUMNS = (
    ("batch_id", "text"), ("arm", "text"), ("canonical_key", "text"), ("source_binding_id", "text"),
    ("snapshot_id", "text"), ("input_digest", "text"), ("descriptor_identity", "text"), ("truncated", "boolean"),
    ("dimensions", "integer"), ("embedding", "repomap_vector.vector"),
)
BATCH_CONSTRAINT_KINDS = {"c": 14, "p": 1, "u": 2}
ENTRY_CONSTRAINT_KINDS = {"c": 4, "f": 1, "p": 1}
SCHEMA_CODES = frozenset({
    "study_identity_invalid", "study_profile_invalid", "study_relation_readback", "study_relation_owner",
    "study_relation_kind", "study_relation_comment", "study_relation_columns", "study_relation_constraints",
    "study_catalog_children", "study_import_invalid", "study_entry_mismatch", "study_publication_mismatch",
    "study_index_catalog", "study_index_unregistered", "study_cleanup_readback",
})


class StudySchemaRefusal(ValueError):
    """Closed refusal before or after SQL; the message is the code only."""

    def __init__(self, code: str) -> None:
        if code not in SCHEMA_CODES:
            raise ValueError("unknown study schema code")
        super().__init__(code)
        self.code = code


def require(condition: bool, code: str) -> None:
    if not condition:
        raise StudySchemaRefusal(code)


def hex_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_ok(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def quote(name: str) -> str:
    require(type(name) is str and _IDENT.fullmatch(name) is not None, "study_identity_invalid")
    return '"' + name + '"'


def qualified(name: str) -> str:
    return f'{SCHEMA}.{quote(name)}'


def make_study_identity(*, task_pins_identity: str, q_source_closure: str, nonce: str) -> str:
    require(digest_ok(task_pins_identity) and digest_ok(q_source_closure)
            and type(nonce) is str and _NONCE.fullmatch(nonce) is not None, "study_identity_invalid")
    return str(digest_json({
        "schema": STUDY_SCHEMA, "phase": STUDY_PHASE, "allocation": "PUBLICTEXT-CAL1", "declaration": 2,
        "task_pins_identity": task_pins_identity, "q_source_closure": q_source_closure, "nonce": nonce,
    }))


@dataclass(frozen=True)
class StudyNames:
    """All study object names are pure functions of the study identity and owner."""

    study_identity: str
    owner: str = OWNER

    def __post_init__(self) -> None:
        require(digest_ok(self.study_identity) and self.owner == OWNER, "study_identity_invalid")

    @property
    def h(self) -> str:
        return hex_digest(f"{self.study_identity}|{self.owner}")[:24]

    @property
    def batch_table(self) -> str:
        return "ptx_batch_" + self.h

    @property
    def entry_table(self) -> str:
        return "ptx_entry_" + self.h

    def batch_id(self, generation: int, arm: str) -> str:
        require(type(generation) is int and generation in (1, 2) and arm in (ARM_V1, ARM_PTX), "study_identity_invalid")
        label = "v1" if arm == ARM_V1 else "ptx"
        return f"ptx1-g{generation}-{label}-" + hex_digest(f"{self.study_identity}|{generation}|{arm}")[:16]

    def index_name(self, batch_id: str) -> str:
        return "ptx_hnsw384_" + hex_digest(f"{self.study_identity}|{batch_id}|{self.owner}")[:32]

    def temp_name(self, batch_id: str, task_id: str, repetition: int) -> str:
        return "ptx_ann_" + hex_digest(f"{self.study_identity}|{batch_id}|{task_id}|{repetition}")[:16]

    def comment(self, kind: str) -> str:
        return f"{COMMENT_PREFIX}{self.study_identity}:{kind}"


@dataclass(frozen=True)
class StudyEmbeddingProfile:
    """The v2 arm's own profile; it is never passed to a production builder."""

    model: str
    model_version: str
    generator: str
    generator_version: str
    representation_version: str = ARM_PTX
    normalization: str = "l2-unit"
    metric: str = "cosine"
    dimensions: int = DIMENSIONS

    def validate(self) -> StudyEmbeddingProfile:
        try:
            for value in (self.model, self.model_version, self.generator, self.generator_version):
                checked_identity(value)
        except ValueError:
            raise StudySchemaRefusal("study_profile_invalid") from None
        require((self.representation_version, self.normalization, self.metric, type(self.dimensions), self.dimensions)
                == (ARM_PTX, "l2-unit", "cosine", int, DIMENSIONS), "study_profile_invalid")
        return self

    @property
    def identity(self) -> str:
        self.validate()
        return str(digest_json({"schema": STUDY_PROFILE_SCHEMA, **self.__dict__}))


def profile_fields(profile: EmbeddingProfile | StudyEmbeddingProfile, arm: str) -> tuple[str, dict[str, str]]:
    """(identity, string fields): v1 uses the exact production profile, v2 only the study profile."""
    require(type(profile) is (EmbeddingProfile if arm == ARM_V1 else StudyEmbeddingProfile)
            and profile.dimensions == DIMENSIONS, "study_profile_invalid")
    try:
        identity = profile.identity
    except ValueError:
        raise StudySchemaRefusal("study_profile_invalid") from None
    names = ("model", "model_version", "generator", "generator_version", "representation_version",
             "normalization", "metric")
    return identity, {name: str(getattr(profile, name)) for name in names}


def table_ddl_sql(names: StudyNames) -> str:
    """The two study tables and their comments; a v2 descriptor is explicitly NOT NULL (section 18.1)."""
    batch, entry = qualified(names.batch_table), qualified(names.entry_table)
    digest = "'^sha256:[0-9a-f]{64}$'"
    v1, v2 = sql_literal(ARM_V1), sql_literal(ARM_PTX)
    text_columns = ",\n    ".join(f"{name} text NOT NULL" for name, kind in BATCH_COLUMNS if kind == "text")
    return f"""CREATE TABLE {batch} (
    {text_columns},
    generation integer NOT NULL, run_id bigint NOT NULL, dimensions integer NOT NULL, row_count integer NOT NULL,
    PRIMARY KEY (batch_id), UNIQUE (batch_id, arm, dimensions), UNIQUE (study_identity, generation, arm),
    CHECK (study_identity = {sql_literal(names.study_identity)}), CHECK (arm IN ({v1}, {v2})),
    CHECK (representation_version = arm), CHECK (generation BETWEEN 1 AND 2), CHECK (run_id > 0),
    CHECK (dimensions = {DIMENSIONS}), CHECK (normalization = 'l2-unit'), CHECK (metric = 'cosine'),
    CHECK (privacy_class = 'public'), CHECK (capability IN ('complete', 'token_partial')),
    CHECK (NOT (arm = {v1} AND capability <> 'complete')), CHECK (row_count BETWEEN 1 AND {MAX_ROWS}),
    CHECK (input_identity ~ {digest}), CHECK (seal_identity ~ {digest})
);
CREATE TABLE {entry} (
    batch_id text NOT NULL, arm text NOT NULL, canonical_key text NOT NULL, source_binding_id text NOT NULL,
    snapshot_id text NOT NULL, input_digest text NOT NULL, descriptor_identity text, truncated boolean NOT NULL,
    dimensions integer NOT NULL, embedding repomap_vector.vector NOT NULL,
    PRIMARY KEY (batch_id, canonical_key, source_binding_id),
    FOREIGN KEY (batch_id, arm, dimensions) REFERENCES {batch} (batch_id, arm, dimensions),
    CHECK (input_digest ~ {digest}),
    CHECK ((arm = {v1} AND descriptor_identity IS NULL AND NOT truncated)
        OR (arm = {v2} AND descriptor_identity IS NOT NULL AND descriptor_identity ~ {digest})),
    CHECK (repomap_vector.vector_dims(embedding) = dimensions),
    CHECK (abs(repomap_vector.vector_norm(embedding) - 1) < 0.00001)
);
COMMENT ON TABLE {batch} IS {sql_literal(names.comment("batch"))};
COMMENT ON TABLE {entry} IS {sql_literal(names.comment("entry"))};"""


def index_item_sql(cls: str, idx: str) -> str:
    """The single index item expression shared by readback, registration and every fence."""
    return (f"'index|' || {cls}.oid::text || '|' || {cls}.relname::text || '|' || {idx}.indrelid::text || '|' || "
            f"pg_catalog.pg_get_indexdef({cls}.oid) || '|' || {idx}.indisvalid::text || '|' || "
            f"{idx}.indisready::text || '|' || {idx}.indislive::text || '|' || "
            f"COALESCE(pg_catalog.obj_description({cls}.oid, 'pg_class'), '') || '|' || "
            f"pg_catalog.pg_get_userbyid({cls}.relowner)::text || '|' || {cls}.relpersistence::text")


def inventory_items_sql(oids: str) -> str:
    """Every child item of the relations in the ``oid[]`` expression ``oids``."""
    return (f"SELECT {index_item_sql('xc', 'xi')} AS item FROM pg_catalog.pg_index xi"
            f" JOIN pg_catalog.pg_class xc ON xc.oid = xi.indexrelid WHERE xi.indrelid = ANY({oids})"
            " UNION ALL SELECT 'trigger|' || xt.tgrelid::text || '|' || xt.tgname::text FROM pg_catalog.pg_trigger xt"
            f" WHERE xt.tgrelid = ANY({oids}) AND NOT xt.tgisinternal"
            " UNION ALL SELECT 'rule|' || xr.ev_class::text || '|' || xr.rulename::text FROM pg_catalog.pg_rewrite xr"
            f" WHERE xr.ev_class = ANY({oids})"
            " UNION ALL SELECT 'policy|' || xp.polrelid::text || '|' || xp.polname::text FROM pg_catalog.pg_policy xp"
            f" WHERE xp.polrelid = ANY({oids})"
            " UNION ALL SELECT 'rls|' || xk.oid::text || '|' || xk.relrowsecurity::text || '|' ||"
            f" xk.relforcerowsecurity::text FROM pg_catalog.pg_class xk WHERE xk.oid = ANY({oids})")


def rls_item(oid: int) -> str:
    return f"rls|{oid}|false|false"


def fingerprint_sql(oid_sql: str) -> str:
    """Builtin sha256 over ordered column rows plus sorted constraint definitions (no pgcrypto)."""
    return (
        "encode(sha256(convert_to(coalesce((SELECT string_agg(a.attname || '|' || "
        "pg_catalog.format_type(a.atttypid, a.atttypmod) || '|' || a.attnotnull::text, E'\\n' ORDER BY a.attnum) "
        f"FROM pg_catalog.pg_attribute a WHERE a.attrelid = {oid_sql} AND a.attnum > 0 AND NOT a.attisdropped), '')"
        " || E'\\n--\\n' || coalesce((SELECT string_agg(pg_catalog.pg_get_constraintdef(k.oid, true), E'\\n' "
        "ORDER BY pg_catalog.pg_get_constraintdef(k.oid, true) COLLATE \"C\") FROM pg_catalog.pg_constraint k "
        f"WHERE k.conrelid = {oid_sql}), ''), 'UTF8')), 'hex')"
    )


def index_comment(names: StudyNames, batch_id: str) -> str:
    return f"{COMMENT_PREFIX}{names.study_identity}:hnsw:{batch_id}"


def index_catalog_sql(names: StudyNames, batch_id: str) -> str:
    """Catalog shape of the owned index (study names), never a caller assertion."""
    return f"""SELECT json_build_object('present', c.oid IS NOT NULL, 'index_oid', c.oid::bigint,
    'table_oid', i.indrelid::bigint, 'index_schema', n.nspname, 'index_name', c.relname,
    'table_name', t.relname, 'attribute_count', i.indnatts, 'key_count', i.indnkeyatts,
    'access_method', am.amname, 'opclass_schema', opn.nspname, 'opclass_name', op.opcname,
    'is_valid', i.indisvalid, 'is_ready', i.indisready, 'owner', pg_catalog.pg_get_userbyid(c.relowner),
    'comment', pg_catalog.obj_description(c.oid, 'pg_class'),
    'expression', pg_catalog.pg_get_expr(i.indexprs, i.indrelid),
    'predicate', pg_catalog.pg_get_expr(i.indpred, i.indrelid),
    'reloptions', COALESCE(c.reloptions, ARRAY[]::text[]),
    'item', CASE WHEN i.indexrelid IS NULL THEN NULL ELSE {index_item_sql('c', 'i')} END)::text
FROM (SELECT 1) one
LEFT JOIN pg_catalog.pg_namespace n ON n.nspname = '{SCHEMA}'
LEFT JOIN pg_catalog.pg_class c ON c.relnamespace = n.oid AND c.relname = {sql_literal(names.index_name(batch_id))}
LEFT JOIN pg_catalog.pg_index i ON i.indexrelid = c.oid
LEFT JOIN pg_catalog.pg_class t ON t.oid = i.indrelid
LEFT JOIN pg_catalog.pg_am am ON am.oid = c.relam
LEFT JOIN pg_catalog.pg_opclass op ON op.oid = i.indclass[0]
LEFT JOIN pg_catalog.pg_namespace opn ON opn.oid = op.opcnamespace;"""


__all__ = [
    "BATCH_COLUMNS", "BATCH_CONSTRAINT_KINDS", "BATCH_ID", "COMMENT_PREFIX", "DIMENSIONS", "ENTRY_COLUMNS",
    "ENTRY_CONSTRAINT_KINDS", "MAX_ROWS", "OWNER", "SCHEMA", "SCHEMA_CODES", "StudyEmbeddingProfile", "StudyNames",
    "StudySchemaRefusal", "digest_ok", "fingerprint_sql", "hex_digest", "index_catalog_sql", "index_comment",
    "index_item_sql", "inventory_items_sql", "make_study_identity", "profile_fields", "qualified", "quote", "require",
    "rls_item", "table_ddl_sql",
]
