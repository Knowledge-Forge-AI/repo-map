"""Real accepted-publication boundaries for direct filesystem lexical capture."""

from __future__ import annotations

import json
from pathlib import Path

from common_lore_index.ops.config_local import (
    load_graph_registry_config_home,
    local_graph_binding,
)
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_publication import (
    lexical_connection_parameters,
    resolve_ops_graph,
)
from common_lore_index.retrieval.lexical_capture import capture_lexical_generation_plan
from common_lore_index.retrieval.lexical_policy import build_lexical_generation_policy
from common_lore_index.retrieval.projection_policy import ExclusionReason
from common_lore_index.storage.lexical_driver import lexical_connection_scope
from common_lore_index.storage.lexical_lifecycle import (
    AcceptedGraphPublicationRecord,
    read_accepted_graph_publication,
)
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
)


def _read_accepted_publication(config: OpsConfig) -> AcceptedGraphPublicationRecord:
    graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
    binding = local_graph_binding(graph)
    params = lexical_connection_parameters(config, graph, read_only=True)
    with lexical_connection_scope(params) as connection:
        accepted = read_accepted_graph_publication(
            connection,
            repository_identity=binding.repository_identity,
            repository_name=graph.repository_name,
            root_path=binding.root_path,
        )
    assert accepted is not None
    return accepted


def test_direct_filesystem_capture_uses_accepted_fence_and_policy_boundaries(
    tmp_path: Path,
) -> None:
    with temporary_postgres() as postgres:
        working_copy = materialize_mixed_v1_working_copy(tmp_path / "fixture-working-copy")
        home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home",
            working_copy,
            host=postgres.host,
            port=postgres.port,
            database=postgres.database,
            user=postgres.user,
            password=postgres.password,
            declared_aliases=("core", "companion"),
        )
        publish_and_load_postgres_corpus(home, psql_command=postgres.psql_command)
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        accepted = _read_accepted_publication(config)
        fence = accepted.to_publication_fence()

        core_id = binding_id_for_alias("core")
        synthetic_core = tmp_path / "PRIVATE_PATH_CANARY_V1" / "synthetic-core"
        private_root = synthetic_core / "private-data"
        private_root.mkdir(parents=True)
        (synthetic_core / "eligible.py").write_text(
            "PUBLIC_ELIGIBLE_BOUNDARY_MARKER_V1\n", encoding="utf-8"
        )
        (synthetic_core / "symlink.py").symlink_to(synthetic_core / "eligible.py")
        (synthetic_core / "unsupported.bin").write_bytes(b"unsupported format\n")
        (synthetic_core / "oversized.py").write_bytes(b"x" * 256)
        (private_root / "private-note.py").write_text(
            "CANARY_PRIVATE_THREAD_PAYLOAD_44102\n", encoding="utf-8"
        )

        policy = build_lexical_generation_policy(
            graph,
            selected_binding_ids=(core_id,),
            max_input_artifact_bytes=128,
            max_projected_file_bytes=128,
        )
        plan = capture_lexical_generation_plan(
            graph=graph,
            lexical_policy=policy,
            fence=fence,
            repository_id=accepted.repository_id,
            extraction_receipt_id=accepted.extraction_receipt_id,
            graph_candidate_id=accepted.graph_candidate_id,
            binding_roots_override={core_id: synthetic_core},
            private_roots=(private_root,),
            manifest=None,
            store=None,
        )

    assert len(plan.documents) == 1
    document = plan.documents[0]
    assert document.binding_id == core_id
    assert document.source_relative_path == "eligible.py"
    assert "PUBLIC_ELIGIBLE_BOUNDARY_MARKER_V1" in document.normalized_text

    omission_map = {
        (item.binding_id, item.source_relative_path): item.reason_code
        for item in plan.omissions
    }
    assert omission_map[(core_id, "symlink.py")] == ExclusionReason.UNSUPPORTED_SOURCE_FORMAT.value
    assert omission_map[(core_id, "unsupported.bin")] == ExclusionReason.UNSUPPORTED_SOURCE_FORMAT.value
    assert omission_map[(core_id, "oversized.py")] == ExclusionReason.ARTIFACT_OVERSIZED.value
    assert omission_map[(core_id, "private-data/private-note.py")] == (
        ExclusionReason.ARTIFACT_PRIVACY_FORBIDDEN.value
    )

    public_plan = {
        "lexical_generation_id": plan.lexical_generation_id,
        "repository_id": plan.repository_id,
        "run_id": plan.run_id,
        "publication_bundle_id": plan.publication_bundle_id,
        "snapshot_manifest_id": plan.snapshot_manifest_id,
        "extraction_receipt_id": plan.extraction_receipt_id,
        "graph_candidate_id": plan.graph_candidate_id,
        "documents": [
            {"path": item.source_relative_path, "text": item.normalized_text}
            for item in plan.documents
        ],
        "omissions": [item.to_dict() for item in plan.omissions],
    }
    encoded = json.dumps(public_plan, sort_keys=True)
    assert_canary_free(public_plan)
    assert str(synthetic_core) not in encoded
    assert str(private_root) not in encoded
    assert "PRIVATE_PATH_CANARY_V1" not in encoded
    assert "CANARY_PRIVATE_THREAD_PAYLOAD_44102" not in encoded

def test_direct_filesystem_capture_applies_companion_discovery_and_body_boundaries(
    tmp_path: Path,
) -> None:
    with temporary_postgres() as postgres:
        working_copy = materialize_mixed_v1_working_copy(tmp_path / "fixture-working-copy")
        home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home",
            working_copy,
            host=postgres.host,
            port=postgres.port,
            database=postgres.database,
            user=postgres.user,
            password=postgres.password,
            declared_aliases=("core", "companion"),
        )
        publish_and_load_postgres_corpus(home, psql_command=postgres.psql_command)
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        accepted = _read_accepted_publication(config)
        companion_id = binding_id_for_alias("companion")
        source_root = tmp_path / "PUBLIC_TEXT_SOURCE_BOUNDARY"
        (source_root / "excluded_cache").mkdir(parents=True)
        (source_root / "pkg").mkdir()
        (source_root / ".git").mkdir()
        (source_root / "eligible.py").write_text(
            "PUBLIC_COMPANION_ELIGIBLE_BOUNDARY_MARKER_V1\n", encoding="utf-8"
        )
        (source_root / ".git" / "hook.py").write_text(
            "PUBLIC_VCS_PAYLOAD_MUST_NOT_BE_READ\n", encoding="utf-8"
        )
        (source_root / "excluded_cache" / "cached.py").write_text(
            "PUBLIC_EXCLUDED_CACHE_MUST_NOT_BE_READ\n", encoding="utf-8"
        )
        (source_root / "pkg" / "inside.py").write_text(
            "PUBLIC_REGULAR_DIRECTORY_CONTENT_V1\n", encoding="utf-8"
        )
        (source_root / "symlink_dir").symlink_to(source_root / "pkg", target_is_directory=True)
        (source_root / "notice.eml").write_bytes(
            b"From: public@example.invalid\n\nPUBLIC_EMAIL_BODY_MUST_NOT_BE_READ\n"
        )
        (source_root / "releases.rss").write_bytes(
            b"<rss>PUBLIC_FEED_BODY_MUST_NOT_BE_READ</rss>\n"
        )

        policy = build_lexical_generation_policy(
            graph,
            selected_binding_ids=(companion_id,),
            max_input_artifact_bytes=128,
            max_projected_file_bytes=128,
        )
        plan = capture_lexical_generation_plan(
            graph=graph,
            lexical_policy=policy,
            fence=accepted.to_publication_fence(),
            repository_id=accepted.repository_id,
            extraction_receipt_id=accepted.extraction_receipt_id,
            graph_candidate_id=accepted.graph_candidate_id,
            binding_roots_override={companion_id: source_root},
            manifest=None,
            store=None,
        )

    assert {document.source_relative_path for document in plan.documents} == {"eligible.py", "pkg/inside.py"}
    omission_map = {
        item.source_relative_path: item.reason_code
        for item in plan.omissions
        if item.source_relative_path is not None
    }
    assert omission_map["symlink_dir"] == ExclusionReason.UNSUPPORTED_SOURCE_FORMAT.value
    assert omission_map["notice.eml"] == ExclusionReason.EMAIL_BODY_FORBIDDEN.value
    assert omission_map["releases.rss"] == ExclusionReason.FEED_BODY_FORBIDDEN.value
    assert ".git/hook.py" not in omission_map
    assert "excluded_cache/cached.py" not in omission_map
    assert_canary_free(
        {
            "documents": [document.normalized_text for document in plan.documents],
            "omissions": [item.to_dict() for item in plan.omissions],
        }
    )


def test_direct_filesystem_capture_omits_binding_absent_from_accepted_vector(
    tmp_path: Path,
) -> None:
    with temporary_postgres() as postgres:
        working_copy = materialize_mixed_v1_working_copy(tmp_path / "fixture-working-copy")
        home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home",
            working_copy,
            host=postgres.host,
            port=postgres.port,
            database=postgres.database,
            user=postgres.user,
            password=postgres.password,
            declared_aliases=("core", "companion"),
        )
        publish_and_load_postgres_corpus(home, psql_command=postgres.psql_command)
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        accepted = _read_accepted_publication(config)
        core_id = binding_id_for_alias("core")
        fence = accepted.to_publication_fence()
        assert any(binding_id == core_id for binding_id, _revision, _snapshot in fence.snapshot_vector)
        mismatched_fence = type(fence)(
            run_id=fence.run_id,
            publication_bundle_id=fence.publication_bundle_id,
            snapshot_manifest_id=fence.snapshot_manifest_id,
            snapshot_vector=tuple(
                entry for entry in fence.snapshot_vector if entry[0] != core_id
            ),
        ).validate()
        source_root = tmp_path / "PUBLIC_TEXT_FENCE_BOUNDARY"
        source_root.mkdir()
        (source_root / "eligible.py").write_text(
            "PUBLIC_FENCE_VECTOR_MARKER_V1\n", encoding="utf-8"
        )
        policy = build_lexical_generation_policy(
            graph,
            selected_binding_ids=(core_id,),
            max_input_artifact_bytes=128,
            max_projected_file_bytes=128,
        )
        plan = capture_lexical_generation_plan(
            graph=graph,
            lexical_policy=policy,
            fence=mismatched_fence,
            repository_id=accepted.repository_id,
            extraction_receipt_id=accepted.extraction_receipt_id,
            graph_candidate_id=accepted.graph_candidate_id,
            binding_roots_override={core_id: source_root},
            manifest=None,
            store=None,
        )

    assert plan.documents == ()
    assert [
        (item.binding_id, item.source_relative_path, item.reason_code)
        for item in plan.omissions
        if item.binding_id == core_id
    ] == [(core_id, None, "binding_absent_from_publication_vector")]


def test_direct_filesystem_capture_refuses_aggregate_input_budget_before_open(
    tmp_path: Path,
) -> None:
    with temporary_postgres() as postgres:
        working_copy = materialize_mixed_v1_working_copy(tmp_path / "fixture-working-copy")
        home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home",
            working_copy,
            host=postgres.host,
            port=postgres.port,
            database=postgres.database,
            user=postgres.user,
            password=postgres.password,
            declared_aliases=("core", "companion"),
        )
        publish_and_load_postgres_corpus(home, psql_command=postgres.psql_command)
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        accepted = _read_accepted_publication(config)
        core_id = binding_id_for_alias("core")
        source_root = tmp_path / "PUBLIC_TEXT_AGGREGATE_BOUNDARY"
        source_root.mkdir()
        (source_root / "a.py").write_bytes(b"12345678")
        (source_root / "b.py").write_bytes(b"abcdefgh")
        policy = build_lexical_generation_policy(
            graph,
            selected_binding_ids=(core_id,),
            max_input_artifact_bytes=8,
            max_aggregate_input_bytes=10,
            max_projected_file_bytes=128,
        )
        try:
            capture_lexical_generation_plan(
                graph=graph,
                lexical_policy=policy,
                fence=accepted.to_publication_fence(),
                repository_id=accepted.repository_id,
                extraction_receipt_id=accepted.extraction_receipt_id,
                graph_candidate_id=accepted.graph_candidate_id,
                binding_roots_override={core_id: source_root},
                manifest=None,
                store=None,
            )
        except ValueError as error:
            assert ExclusionReason.AGGREGATE_BUDGET_EXCEEDED.value in str(error)
        else:
            raise AssertionError("direct capture unexpectedly passed aggregate budget")
