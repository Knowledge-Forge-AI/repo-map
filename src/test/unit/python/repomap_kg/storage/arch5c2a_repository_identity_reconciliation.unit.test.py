import re

import pytest

from repomap_kg.storage import (
    StorageSchemaError,
    repository_identity_reconciliation_sql,
    repository_identity_state_sql,
    repository_upsert_sql,
)


def test_repository_identity_sql_escapes_private_inputs() -> None:
    state_sql = repository_identity_state_sql(
        "repo1:public-fixture",
        "/workspace/fixture's-root",
    )
    reconciliation_sql = repository_identity_reconciliation_sql(
        "repo1:public-fixture",
        "fixture's-name",
        "/workspace/fixture's-root",
    )

    assert "fixture''s-root" in state_sql
    assert "fixture''s-name" in reconciliation_sql
    assert reconciliation_sql.startswith("BEGIN;\n")
    assert reconciliation_sql.endswith("COMMIT;\n")


@pytest.mark.parametrize(
    ("identity", "name", "root", "message"),
    [
        ("invalid", "fixture", "/workspace/fixture", "identity is invalid"),
        ("repo1:fixture", "", "/workspace/fixture", "name is invalid"),
        ("repo1:fixture", "bad\x00name", "/workspace/fixture", "name is invalid"),
        ("repo1:fixture", "fixture", "", "source location is invalid"),
        (
            "repo1:fixture",
            "fixture",
            "/workspace/bad\x00root",
            "source location is invalid",
        ),
    ],
)
def test_repository_identity_sql_rejects_invalid_inputs(
    identity: str,
    name: str,
    root: str,
    message: str,
) -> None:
    with pytest.raises(StorageSchemaError, match=message):
        repository_identity_reconciliation_sql(identity, name, root)


def test_repository_identity_reconciliation_sql_survivor_ordering() -> None:
    sql = repository_identity_reconciliation_sql(
        "repo1:public-fixture",
        "public-fixture",
        "/workspace/target",
    )

    expected_survivor_ordering = (
        "CREATE TEMP TABLE repomap_identity_survivor ON COMMIT DROP AS\n"
        "SELECT id\n"
        "FROM repositories\n"
        "ORDER BY\n"
        "    (repository_identity = 'repo1:public-fixture') DESC NULLS LAST,\n"
        "    (root_path = '/workspace/target') DESC,\n"
        "    id\n"
        "LIMIT 1;\n"
        "ALTER TABLE repomap_identity_survivor ADD PRIMARY KEY (id);"
    )
    assert expected_survivor_ordering in sql


def test_repository_identity_reconciliation_sql_keeper_ordering_and_contracts() -> None:
    sql = repository_identity_reconciliation_sql(
        "repo1:public-fixture",
        "public-fixture",
        "/workspace/target",
    )

    assert "repomap_file_map" in sql
    assert "repomap_node_map" in sql
    assert "repomap_evidence_map" in sql
    assert "repomap_canonical_node_map" in sql
    assert "repomap_canonical_edge_map" in sql

    keeper_matches = re.findall(
        r"repository_id\s*=\s*\(\s*SELECT id FROM repomap_identity_survivor\s*\)\s*\)\s*DESC,\s*id",
        sql,
    )
    assert len(keeper_matches) == 6

    assert "WHERE repository_identity IS NOT NULL" in sql
    assert "AND repository_identity <> 'repo1:public-fixture'" in sql
    assert "RAISE EXCEPTION 'conflicting stable repository identity';" in sql

    expected_authority_ordering = (
        "SELECT repository_id\n"
        "FROM graph_publication_authority\n"
        "ORDER BY\n"
        "    singleton_fencing_epoch DESC,\n"
        "    graph_lease_fencing_epoch DESC,\n"
        "    repository_id DESC\n"
        "LIMIT 1;"
    )
    assert expected_authority_ordering in sql

    assert "DELETE FROM repositories\nWHERE id <> (SELECT id FROM repomap_identity_survivor);" in sql
    assert (
        "UPDATE repositories\n"
        "SET name = 'public-fixture',\n"
        "    root_path = '/workspace/target',\n"
        "    repository_identity = 'repo1:public-fixture'\n"
        "WHERE id = (SELECT id FROM repomap_identity_survivor);"
    ) in sql


def test_repository_upsert_sql_contracts() -> None:
    legacy_sql = repository_upsert_sql("legacy-repo", "/workspace/legacy")
    assert "INSERT INTO repositories(name, root_path)" in legacy_sql
    assert "ON CONFLICT (root_path) DO UPDATE SET name = EXCLUDED.name" in legacy_sql

    stable_sql = repository_upsert_sql(
        "stable-repo", "/workspace/stable", "repo1:stable-id"
    )
    assert "INSERT INTO repositories(name, root_path, repository_identity)" in stable_sql
    assert "ON CONFLICT (repository_identity)" in stable_sql
    assert "WHERE repository_identity IS NOT NULL DO UPDATE" in stable_sql

    with pytest.raises(StorageSchemaError, match="stable repository identity is invalid"):
        repository_upsert_sql("bad", "/workspace/bad", "invalid-identity")


def test_repository_identity_state_sql_structure() -> None:
    sql = repository_identity_state_sql("repo1:target", "/workspace/root")
    assert "SELECT count(*)," in sql
    assert "count(*) FILTER (WHERE repository_identity = 'repo1:target')" in sql
    assert (
        "count(*) FILTER (WHERE repository_identity IS NOT NULL AND repository_identity <> 'repo1:target')"
        in sql
    )
    assert "count(*) FILTER (WHERE root_path = '/workspace/root')" in sql
    assert "FROM repositories;" in sql
