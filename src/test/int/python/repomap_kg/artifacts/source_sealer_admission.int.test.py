from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
import os
from pathlib import Path

import pytest

from common_lore_index.artifacts import ArtifactLimits
from common_lore_index.artifacts.source_sealer import seal_configured_sources
from common_lore_index.artifacts.store import FileSystemArtifactStore
from common_lore_index.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from common_lore_index.graph.multi_source_capture import MultiSourceCaptureError
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig


def _graph(root: Path) -> OpsGraphConfig:
    binding = OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id("fixture-graph", "entry"),
        source_definition_id="src1:entry",
        alias="entry",
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(root),
        root_path_expanded=str(root),
        repository_name="fixture",
        logical_root=".",
        privacy="public-dev",
        evidence_retention="metadata-only",
        extractor_profile="default",
        include_paths=(),
        exclude_paths=(),
        selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared",
        enabled=True,
        role="entry",
        input_name=None,
    )
    return OpsGraphConfig(
        id="fixture-graph",
        name="Fixture",
        root_path="",
        root_path_expanded="",
        repository_name="fixture",
        privacy="public-dev",
        enabled=True,
        mcp_visible=True,
        extractor_profile="default",
        refresh_policy="manual",
        source_bindings=(binding,),
        explicit_source_bindings=True,
    )


@pytest.mark.parametrize(
    ("limits", "message"),
    (
        (ArtifactLimits(max_artifacts=1), "artifact count bounds exceeded"),
        (ArtifactLimits(max_total_bytes=1), "artifact byte bounds exceeded"),
        (ArtifactLimits(max_path_bytes=3), "artifact path bounds exceeded"),
    ),
)
def test_lower_inventory_limit_refuses_before_filesystem_store_write(
    tmp_path, limits, message
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.py").write_text("ONE = 1\n", encoding="utf-8")
    (source / "two.py").write_text("TWO = 2\n", encoding="utf-8")
    store = FileSystemArtifactStore(tmp_path / "store")

    with pytest.raises(ValueError, match=message):
        seal_configured_sources(
            _graph(source),
            store,
            extractor_generation="eg1:portable",
            canonicalizer_generation="kg1:portable",
            limits=limits,
        )

    assert tuple((tmp_path / "store" / "objects").iterdir()) == ()
    assert tuple((tmp_path / "store" / "temporary").iterdir()) == ()


def test_exact_lower_limits_preserve_streamed_manifest_and_content(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    content = b"VALUE = 1\n"
    (source / "main.py").write_bytes(content)
    store = FileSystemArtifactStore(tmp_path / "store")
    limits = ArtifactLimits(
        max_artifacts=1,
        max_total_bytes=len(content),
        max_path_bytes=len("main.py"),
    )

    manifest, manifest_reference, _candidate = seal_configured_sources(
        _graph(source),
        store,
        extractor_generation="eg1:portable",
        canonicalizer_generation="kg1:portable",
        limits=limits,
    )

    assert manifest.total_files == 1
    assert manifest.total_bytes == len(content)
    assert store.read(manifest_reference) == manifest.canonical_bytes()
    assert store.read(manifest.entries[0].reference) == content


def test_default_path_limit_refuses_long_inventory_before_store_write(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    parent = source
    for _index in range(6):
        parent /= "a" * 180
        parent.mkdir()
    (parent / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    store = FileSystemArtifactStore(tmp_path / "store")

    with pytest.raises(MultiSourceCaptureError, match="source inventory is invalid") as error:
        seal_configured_sources(
            _graph(source),
            store,
            extractor_generation="eg1:portable",
            canonicalizer_generation="kg1:portable",
        )

    assert error.value.category == "source_invalid"
    assert tuple((tmp_path / "store" / "objects").iterdir()) == ()


def test_empty_source_and_repeated_sealing_preserve_object_custody(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "empty.py").write_bytes(b"")
    store = FileSystemArtifactStore(tmp_path / "store")
    limits = ArtifactLimits(
        max_artifacts=1,
        max_total_bytes=1,
        max_path_bytes=len("empty.py"),
    )

    first, first_manifest_ref, first_candidate = seal_configured_sources(
        _graph(source),
        store,
        extractor_generation="eg1:portable",
        canonicalizer_generation="kg1:portable",
        limits=limits,
    )
    object_paths = tuple(sorted(path.name for path in (tmp_path / "store" / "objects").iterdir()))
    second, second_manifest_ref, second_candidate = seal_configured_sources(
        _graph(source),
        store,
        extractor_generation="eg1:portable",
        canonicalizer_generation="kg1:portable",
        limits=limits,
    )

    assert first == second
    assert first_manifest_ref == second_manifest_ref
    assert first_candidate == second_candidate
    assert first.total_bytes == 0
    assert store.read(first.entries[0].reference) == b""
    assert tuple(sorted(path.name for path in (tmp_path / "store" / "objects").iterdir())) == object_paths


def test_midcopy_mutation_cleans_temp_and_preserves_preexisting_object(
    tmp_path, monkeypatch
):
    import common_lore_index.artifacts.source_sealer as sealer_mod

    source = tmp_path / "source"
    source.mkdir()
    content = b"A" * (2 * 1024 * 1024)
    path = source / "main.py"
    path.write_bytes(content)
    store = FileSystemArtifactStore(tmp_path / "store")
    preexisting = store.put(b"preexisting")
    original_open = sealer_mod.open_source_body

    @contextmanager
    def mutating_open(*args, **kwargs):
        with original_open(*args, **kwargs) as body:
            def chunks():
                first = next(body)
                path.write_bytes(b"B" * len(content))
                yield first
                yield from body

            yield chunks()

    monkeypatch.setattr(sealer_mod, "open_source_body", mutating_open)
    with pytest.raises(ValueError, match="source changed while sealing"):
        seal_configured_sources(
            _graph(source),
            store,
            extractor_generation="eg1:portable",
            canonicalizer_generation="kg1:portable",
        )
    path.write_bytes(content)

    assert store.read(preexisting) == b"preexisting"
    assert tuple(sorted(path.name for path in (tmp_path / "store" / "objects").iterdir())) == (
        preexisting.content_digest.removeprefix("sha256:"),
    )
    assert tuple((tmp_path / "store" / "temporary").iterdir()) == ()


def test_partial_store_failure_preserves_error_and_cleans_temp(tmp_path):
    class FailingStore(FileSystemArtifactStore):
        def put(self, content, **kwargs):
            if kwargs.get("media_type") == "application/octet-stream":
                def failing_chunks():
                    iterator = iter(content)
                    yield next(iterator)
                    raise RuntimeError("store failed during source copy")

                return super().put(failing_chunks(), **kwargs)
            return super().put(content, **kwargs)

    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_bytes(b"A" * (2 * 1024 * 1024))
    store = FailingStore(tmp_path / "store")
    with pytest.raises(RuntimeError, match="store failed during source copy"):
        seal_configured_sources(
            _graph(source),
            store,
            extractor_generation="eg1:portable",
            canonicalizer_generation="kg1:portable",
        )
    assert tuple((tmp_path / "store" / "objects").iterdir()) == ()
    assert tuple((tmp_path / "store" / "temporary").iterdir()) == ()


def test_symlinked_root_prefix_is_accepted_after_resolution(tmp_path):
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    alias_root = tmp_path / "alias-root"
    alias_root.symlink_to(real_root, target_is_directory=True)
    content = b"VALUE = 1\n"
    (real_root / "main.py").write_bytes(content)
    store = FileSystemArtifactStore(tmp_path / "store")

    manifest, _manifest_reference, _candidate = seal_configured_sources(
        _graph(alias_root),
        store,
        extractor_generation="eg1:portable",
        canonicalizer_generation="kg1:portable",
    )

    assert store.read(manifest.entries[0].reference) == content


@pytest.mark.parametrize(
    "mutation", ["none", "symlink", "hardlink", "directory", "size", "executable", "missing", "replaced"],
)
def test_fallback_source_open_uses_real_identity_checks_and_preserves_store_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    import common_lore_index.artifacts._source_sealing_io as source_io
    import common_lore_index.artifacts.source_sealer as sealer

    source = tmp_path / "source"
    parent = source / "package"
    parent.mkdir(parents=True)
    path = parent / "main.py"
    content = b"VALUE = 1\n"
    path.write_bytes(content)
    store = FileSystemArtifactStore(tmp_path / "store")
    sentinel = store.put(b"preexisting object")
    original_open = sealer.open_source_body
    monkeypatch.setattr(source_io, "_supports_dir_fd", lambda: False)

    @contextmanager
    def controlled_open(
        root: Path, relative_path: str, *, expected_size: int,
        expected_digest: str, expected_executable: bool,
    ) -> Iterator[Iterator[bytes]]:
        moved = path.with_name("moved.py")
        if mutation == "symlink":
            path.rename(moved)
            path.symlink_to(moved)
        elif mutation == "hardlink":
            os.link(path, moved)
        elif mutation == "directory":
            path.unlink()
            path.mkdir()
        elif mutation == "size":
            path.write_bytes(content[:-1])
        elif mutation == "executable":
            path.chmod(0o700)
        with original_open(
            root, relative_path, expected_size=expected_size,
            expected_digest=expected_digest, expected_executable=expected_executable,
        ) as body:
            if mutation in {"missing", "replaced"}:
                path.rename(moved)  # keep the opened inode and its link count unchanged
                if mutation == "replaced":
                    path.write_bytes(content)
            yield body

    monkeypatch.setattr(sealer, "open_source_body", controlled_open)
    if mutation == "none":
        manifest, reference, _candidate = seal_configured_sources(
            _graph(source), store, extractor_generation="eg1:portable",
            canonicalizer_generation="kg1:portable",
        )
        assert store.read(reference) == manifest.canonical_bytes()
        assert store.read(manifest.entries[0].reference) == content
    else:
        with pytest.raises(ValueError, match="source (changed while sealing|inventory is not sealable)"):
            seal_configured_sources(
                _graph(source), store, extractor_generation="eg1:portable",
                canonicalizer_generation="kg1:portable",
            )
        assert [p.name for p in (tmp_path / "store" / "objects").iterdir()] == [
            sentinel.content_digest.removeprefix("sha256:"),
        ]
    assert store.read(sentinel) == b"preexisting object"
    assert list((tmp_path / "store" / "temporary").iterdir()) == []
