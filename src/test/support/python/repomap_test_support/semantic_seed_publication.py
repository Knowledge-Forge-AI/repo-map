"""Support fixtures and portable publication builders for semantic seed integration tests.

Builds real multi-source portable publications from temporary source files on disk
using the maintained portable publication pipeline:
- seal_configured_sources
- execute_portable_extraction
- validate_portable_capture
- portable_publication_binding
- run_staged_portable_refresh
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
from typing import Any

import common_lore_index

from common_lore_index.artifacts.source_sealer import seal_configured_sources
from common_lore_index.artifacts.store import FileSystemArtifactStore
from common_lore_index.coordinator._portable_capability import PortableExecutionCapability
from common_lore_index.coordinator._portable_semantic_adapter import execute_portable_extraction
from common_lore_index.graph.multi_source import SourceKind, graph_source_binding_id, source_selection_policy_id
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.ops._portable_retention import _write_retained_result
from common_lore_index.ops.portable_refresh import (
    PortableCapture,
    portable_publication_binding,
    validate_portable_capture,
)
from common_lore_index.storage.psql import run_psql
from common_lore_index.storage.publication_readback import read_latest_publication
from common_lore_index.storage.semantic_candidate_import import build_embedding_import_sql
from common_lore_index.storage.semantic_candidates import (
    CandidatePublication,
    EmbeddingEntry,
    EmbeddingProfile,
)
from common_lore_index.storage.staged_ingestion import (
    new_direct_authority,
    run_staged_portable_refresh,
    stage_id_for_authority,
)


SEED_KEY = "python.module:src.common"


@dataclass(frozen=True)
class SeedPublicationContext:
    graph_id: str
    repository_name: str
    repository_identity: str
    publication: CandidatePublication
    graph_config: OpsGraphConfig
    binding_a_id: str
    binding_b_id: str
    snapshots: dict[str, str]
    source_a: Path
    source_b: Path
    store_root: Path


def build_seed_sources(root: Path) -> tuple[Path, Path]:
    """Create two source directories sharing a relative path (src/common.py)."""
    source_a = root / "source_a"
    source_b = root / "source_b"
    (source_a / "src").mkdir(parents=True, exist_ok=True)
    (source_b / "src").mkdir(parents=True, exist_ok=True)

    (source_a / "src" / "common.py").write_text(
        'def common_symbol() -> str:\n    return "common alpha"\n', encoding="utf-8"
    )
    (source_a / "src" / "worker_a.py").write_text(
        'def worker_a() -> str:\n    return "worker a"\n', encoding="utf-8"
    )
    (source_a / "src" / "unindexed.py").write_text(
        'def unindexed_node() -> str:\n    return "no vector"\n', encoding="utf-8"
    )

    (source_b / "src" / "common.py").write_text(
        'def common_symbol() -> str:\n    return "common beta"\n', encoding="utf-8"
    )
    (source_b / "src" / "worker_b.py").write_text(
        'def worker_b() -> str:\n    return "worker b"\n', encoding="utf-8"
    )
    (source_b / "src" / "service_b.py").write_text(
        'def service_b() -> str:\n    return "service b"\n', encoding="utf-8"
    )
    return source_a, source_b


def build_seed_graph_config(
    graph_id: str,
    repository_name: str,
    source_a: Path,
    source_b: Path,
) -> tuple[OpsGraphConfig, str, str]:
    """Construct multi-source OpsGraphConfig for source_a and source_b."""
    binding_a_id = graph_source_binding_id(graph_id, "src_a")
    binding_b_id = graph_source_binding_id(graph_id, "src_b")

    def _make_binding(alias: str, b_id: str, root_dir: Path) -> OpsGraphSourceBindingConfig:
        return OpsGraphSourceBindingConfig(
            schema_version=1, binding_id=b_id, source_definition_id=f"src1:{graph_id}-{alias[-1]}",
            alias=alias, revision=1, source_kind=SourceKind.FOLDER,
            root_path=str(root_dir), root_path_expanded=str(root_dir), repository_name=repository_name,
            logical_root=".", privacy="public-dev", evidence_retention="metadata-only",
            extractor_profile="default", include_paths=(), exclude_paths=(),
            selection_policy_id=source_selection_policy_id((), ()),
            resolution_policy="allow-declared", enabled=True, role="entry", input_name=None,
        )

    b_a = _make_binding("src_a", binding_a_id, source_a)
    b_b = _make_binding("src_b", binding_b_id, source_b)

    graph_config = OpsGraphConfig(
        id=graph_id, name=f"Seed Graph {graph_id}", root_path="", root_path_expanded="",
        repository_name=repository_name, privacy="public-dev", enabled=True, mcp_visible=True,
        extractor_profile="default", refresh_policy="manual", source_bindings=(b_a, b_b),
        explicit_source_bindings=True,
    )
    return graph_config, binding_a_id, binding_b_id


def publish_portable_seed_graph(
    postgres: Any,
    root: Path,
    *,
    graph_id: str = "seed-graph",
    repository_name: str = "seed-repo",
    repository_identity: str | None = None,
    revision: int = 1,
) -> SeedPublicationContext:
    """Build and publish one portable multi-source publication from disk."""
    repo_identity = repository_identity or f"repo1:{graph_id}"
    source_a, source_b = build_seed_sources(root)
    graph_config, binding_a_id, binding_b_id = build_seed_graph_config(
        graph_id, repository_name, source_a, source_b
    )

    store_root = root / f"store-{revision}"
    store_root.mkdir(mode=0o700, exist_ok=True)
    store = FileSystemArtifactStore(store_root)

    manifest, manifest_ref, candidate_id = seal_configured_sources(
        graph_config,
        store,
        extractor_generation=f"eg1:seed-{revision}",
        canonicalizer_generation=f"kg1:seed-{revision}",
    )

    authority = new_direct_authority(
        source_generation=manifest.source_generation,
        config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
    )
    job_id = str(authority.job_id or authority.operation_id)
    attempt = authority.attempt

    ws = root / f"ws-{revision}"
    ws.mkdir(mode=0o700, exist_ok=True)
    capability = PortableExecutionCapability(
        schema_version=1,
        job_id=job_id,
        attempt=attempt,
        graph_id=graph_id,
        store_root=store_root,
        workspace_root=ws,
        manifest_reference=manifest_ref,
        source_generation=manifest.source_generation,
        config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
        max_artifact_bytes=10 * 1024 * 1024,
        max_bundle_bytes=10 * 1024 * 1024,
    )

    extraction_result = execute_portable_extraction(
        capability,
        emit_progress=lambda *_: None,
        cancel_event=threading.Event(),
    )

    result_path = root / f"result-{revision}.json"
    _write_retained_result(
        result_path,
        manifest.manifest_id,
        (extraction_result.receipt_reference, extraction_result.bundle_reference),
    )

    stage_id = str(stage_id_for_authority(authority))
    capture = PortableCapture(
        graph=graph_config,
        store=store,
        manifest=manifest,
        candidate_id=candidate_id,
        authority=authority,
        result_path=result_path,
        workspace_root=ws,
        receipt_reference=extraction_result.receipt_reference,
        bundle_reference=extraction_result.bundle_reference,
    )
    receipt, validated = validate_portable_capture(capture, stage_id=stage_id)
    binding = portable_publication_binding(capture, receipt, validated, stage_id=stage_id)

    run_staged_portable_refresh(
        postgres.psql_args,
        validated,
        prepared_override=validated.to_prepared_stage_rows(),
        repository_name=repository_name,
        root_path=f"graph:{graph_id}",
        authority=authority,
        portable_binding=binding,
        repository_identity=repo_identity,
    )
    capture.mark_terminal(accepted=True)

    record = read_latest_publication(postgres.psql_args, psql_command=postgres.psql_command)
    assert record is not None
    publication = CandidatePublication(repo_identity, record)
    snapshots = {b: s for b, _, s in manifest.snapshot_vector}

    return SeedPublicationContext(
        graph_id=graph_id,
        repository_name=repository_name,
        repository_identity=repo_identity,
        publication=publication,
        graph_config=graph_config,
        binding_a_id=binding_a_id,
        binding_b_id=binding_b_id,
        snapshots=snapshots,
        source_a=source_a,
        source_b=source_b,
        store_root=store_root,
    )


def import_seed_embeddings(
    postgres: Any,
    context: SeedPublicationContext,
    *,
    rebuild_id: str,
    writer_role: str,
    profile: EmbeddingProfile,
) -> None:
    """Import embeddings for shared common.py and distinct worker files."""
    entries = (
        EmbeddingEntry(SEED_KEY, context.binding_a_id, (1.0, 0.0, 0.0), "sha256:" + "1" * 64),
        EmbeddingEntry(SEED_KEY, context.binding_b_id, (1.0, 0.0, 0.0), "sha256:" + "2" * 64),
        EmbeddingEntry("file:src_a/src/worker_a.py", context.binding_a_id, (1.0, 0.0, 0.0), "sha256:" + "3" * 64),
        EmbeddingEntry("file:src_b/src/worker_b.py", context.binding_b_id, (0.0, 1.0, 0.0), "sha256:" + "4" * 64),
        EmbeddingEntry("file:src_b/src/service_b.py", context.binding_b_id, (0.0, 0.0, 1.0), "sha256:" + "5" * 64),
    )
    sql = build_embedding_import_sql(
        context.publication,
        profile,
        entries,
        rebuild_id=rebuild_id,
        enrichment_principal=writer_role,
        public_safe=True,
    )
    text = f'SET ROLE "{writer_role}";\n' + sql
    run_psql(
        [postgres.psql_command, *postgres.psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=text,
    )


def write_seed_mcp_config(
    config_file: Path,
    postgres: Any,
    context: SeedPublicationContext,
) -> Path:
    """Write valid unified operations TOML config for MCP server."""
    host = getattr(postgres, "host", getattr(postgres, "socket_dir", "127.0.0.1"))
    port = getattr(postgres, "port", 5432)
    database = getattr(postgres, "database", "repomap_test")
    user = getattr(postgres, "user", "repo_map_test")

    content = f"""schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{host}"
port = {port}
database = "{database}"
user = "{user}"
password_env = "PGPASSWORD"

[[graphs]]
id = "{context.graph_id}"
name = "Seed Graph {context.graph_id}"
database = "{database}"
enabled = true
mcp_visible = true
refresh_policy = "manual"

[[graphs.source_bindings]]
schema_version = 1
binding_id = "{context.binding_a_id}"
source_definition_id = "src1:{context.graph_id}-a"
alias = "src_a"
revision = 1
kind = "folder"
root_path = "{context.source_a}"
repository_name = "{context.repository_name}"
logical_root = "."
privacy = "public-dev"
evidence_retention = "metadata-only"
extractor_profile = "default"
resolution_policy = "allow-declared"

[[graphs.source_bindings]]
schema_version = 1
binding_id = "{context.binding_b_id}"
source_definition_id = "src1:{context.graph_id}-b"
alias = "src_b"
revision = 1
kind = "folder"
root_path = "{context.source_b}"
repository_name = "{context.repository_name}"
logical_root = "."
privacy = "public-dev"
evidence_retention = "metadata-only"
extractor_profile = "default"
resolution_policy = "allow-declared"

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
"""
    config_file.write_text(content, encoding="utf-8")
    return config_file


def run_mcp_stdio_requests(
    config_path: Path,
    psql_command: str,
    requests: Sequence[dict[str, Any]],
    *,
    reader_role: str | None = None,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Traverse python -m common_lore_index.server.mcp subprocess via public stdio JSON-RPC."""
    import subprocess
    import sys


    env = os.environ.copy()
    # Parent pytest sys.path changes do not cross the interpreter boundary.
    env["PYTHONPATH"] = str(Path(common_lore_index.__file__).resolve().parent.parent)
    env["REPOMAP_OPS_CONFIG"] = str(config_path)
    env["REPOMAP_PSQL_COMMAND"] = psql_command
    if reader_role:
        env["PGOPTIONS"] = f"-c role={reader_role}"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    input_text = "".join(json.dumps(req) + "\n" for req in requests)
    proc = subprocess.run(
        [sys.executable, "-m", "common_lore_index.server.mcp"],
        input=input_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"MCP server subprocess exited with code {proc.returncode}: {proc.stderr}"
        )

    responses = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line:
            responses.append(json.loads(line))
    return responses
