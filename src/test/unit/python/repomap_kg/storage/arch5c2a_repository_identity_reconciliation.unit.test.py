import pytest

from repomap_kg.storage import (
    StorageSchemaError,
    repository_identity_reconciliation_sql,
    repository_identity_state_sql,
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
