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
