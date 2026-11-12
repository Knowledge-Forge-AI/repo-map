"""Real retained-custody regressions that public-text preparation relies on.

Each case publishes the unchanged mixed-v1 fixture through the maintained
refresh path, then removes exactly one retained custody object while the live
working-copy roots remain present. The maintained readers must refuse rather
than fall back to the live files. No product source, fixture or gold changes.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

import pytest

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_publication import lexical_connection_parameters, resolve_ops_graph
from common_lore_index.ops.lexical_service import build_graph_lexical_generation
from common_lore_index.ops.portable_refresh import portable_attempts_parent
from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.retrieval.publication_binding import CorrespondenceErrorCode, CorrespondenceRefusal
from common_lore_index.storage.lexical_driver import LexicalStorageError, lexical_connection_scope
from common_lore_index.storage.lexical_probe import probe_lexical_runtime
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, binding_id_for_alias, materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home, write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus, publish_and_load_sqlite_corpus,
)


def _postgres_home(root: Path, database: Any) -> Path:
    working = materialize_mixed_v1_working_copy(root / "working")
    return write_mixed_v1_postgres_home(
        root / "home", working, host=database.host, port=database.port, database=database.database,
        user=database.user, password=database.password, declared_aliases=("core", "companion"))


@contextmanager
def _published(root: Path, backend: str) -> Iterator[Any]:
    if backend == "sqlite":
        working = materialize_mixed_v1_working_copy(root / "working")
        yield publish_and_load_sqlite_corpus(write_mixed_v1_sqlite_home(root / "home", working))
    else:
        assert backend == "postgresql"
        with temporary_postgres() as database:
            yield publish_and_load_postgres_corpus(_postgres_home(root, database), psql_command=database.psql_command)


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_missing_referenced_manifest_refuses_before_any_projection(tmp_path: Path, backend: str) -> None:
    with _published(tmp_path, backend) as state:
        inputs = state.projection_inputs()
        reference = inputs.manifest_reference.with_store_version(None)
        assert build_captured_text_projection(inputs, state.policy).projected_files
        assert state.store.verify(reference)
        assert state.store.delete(reference) is True
        assert not state.store.verify(reference)
        assert (tmp_path / "working" / "core").is_dir()
        with pytest.raises(CorrespondenceRefusal) as error:
            build_captured_text_projection(state.projection_inputs(), state.policy)
        assert error.value.code == CorrespondenceErrorCode.STORE_VERIFICATION_FAILED


@pytest.mark.parametrize("failure", ["missing_result", "missing_manifest_reference"])
def test_lexical_build_never_falls_back_from_missing_retained_custody(tmp_path: Path, failure: str) -> None:
    with temporary_postgres() as database:
        home = _postgres_home(tmp_path, database)
        state = publish_and_load_postgres_corpus(home, psql_command=database.psql_command)
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        receipt = state.projection_inputs().receipt
        token = hashlib.sha256(f"{receipt.attempt.job_id}\0{receipt.attempt.attempt}".encode("utf-8")).hexdigest()
        result = portable_attempts_parent(config, None) / token / "portable-result.json"
        assert result.parent == state.attempt_root and result.is_file()
        assert (tmp_path / "working" / "core").is_dir()
        if failure == "missing_result":
            result.unlink()
        else:
            payload = json.loads(result.read_bytes())
            assert isinstance(payload.pop("manifest"), dict)
            result.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(LexicalStorageError) as error:
            build_graph_lexical_generation(
                config, MIXED_V1_GRAPH_ID,
                selected_binding_ids=(binding_id_for_alias("core"),), authorize_body=True)
        assert error.value.code == "cloe_lexical_retained_artifacts_unavailable"
        assert (tmp_path / "working" / "core").is_dir()


def test_lexical_probe_refuses_before_schema_installation(tmp_path: Path) -> None:
    import os
    from test_sandbox_ownership import CHANNEL_ENV

    assert all(name not in os.environ for name in CHANNEL_ENV)
    with temporary_postgres() as database:
        home = _postgres_home(tmp_path, database)
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        parameters = lexical_connection_parameters(config, resolve_ops_graph(config, MIXED_V1_GRAPH_ID))
        with lexical_connection_scope(parameters, operation="public_text_probe") as connection:
            result = probe_lexical_runtime(connection)
        assert result.ready is False and result.schema_exists is False
        assert result.failure_reason == "lexical_schema_missing_or_unrecognized"
        with pytest.raises(LexicalStorageError) as error:
            result.require_ready()
        assert error.value.code == "lexical_schema_missing_or_unrecognized"

@pytest.mark.parametrize("missing_reference", ["bundle", "receipt"])
def test_lexical_build_refuses_missing_retained_bundle_or_receipt(
    tmp_path: Path, missing_reference: str
) -> None:
    with temporary_postgres() as database:
        home = _postgres_home(tmp_path, database)
        state = publish_and_load_postgres_corpus(home, psql_command=database.psql_command)
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        inputs = state.projection_inputs()
        reference = (
            inputs.bundle_reference
            if missing_reference == "bundle"
            else inputs.receipt_reference
        )
        assert reference is not None
        reference = reference.with_store_version(None)
        assert state.store.verify(reference)
        assert state.store.delete(reference) is True
        assert not state.store.verify(reference)
        assert (tmp_path / "working" / "core").is_dir()
        with pytest.raises(LexicalStorageError) as error:
            build_graph_lexical_generation(
                config,
                MIXED_V1_GRAPH_ID,
                selected_binding_ids=(binding_id_for_alias("core"),),
                authorize_body=True,
            )
        assert error.value.code == "cloe_lexical_retained_artifacts_unavailable"
        assert (tmp_path / "working" / "core").is_dir()
