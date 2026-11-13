"""A real sealed multi-chunk source shared by portable worker integration owners."""
from pathlib import Path
from common_lore_index.artifacts.source_sealer import seal_configured_sources
from common_lore_index.artifacts.store import FileSystemArtifactStore
from common_lore_index.coordinator._portable_capability import PortableExecutionCapability
from repomap_test_support.portable_publication_fixtures import create_single_source_graph_config

def spool_case(tmp_path: Path, *, functions: int = 1):
    tmp_path.chmod(0o700)
    source = tmp_path / "source"
    source.mkdir()
    (source / "public.py").write_text(
        "".join(f"def function_{index}():\n    return {index}\n\n" for index in range(functions)),
        encoding="utf-8",
    )
    config = create_single_source_graph_config(source, graph_id="spool-custody", repository_name="public-spool")
    store_root = tmp_path / "store"
    store_root.mkdir(mode=0o700)
    store = FileSystemArtifactStore(store_root)
    manifest, reference, candidate_id = seal_configured_sources(
        config, store, extractor_generation="eg1:spool", canonicalizer_generation="kg1:spool",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    sentinel = workspace / "unrelated-sentinel"
    sentinel.write_bytes(b"preserved")
    capability = PortableExecutionCapability(
        schema_version=1, job_id="job-spool-custody", attempt=1, graph_id=manifest.graph_id,
        store_root=store_root, workspace_root=workspace, manifest_reference=reference,
        source_generation=manifest.source_generation, config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation, canonicalizer_generation=manifest.canonicalizer_generation,
        max_artifact_bytes=64 * 1024 * 1024, max_bundle_bytes=64 * 1024 * 1024,
    )
    return config, store, manifest, candidate_id, capability, sentinel
