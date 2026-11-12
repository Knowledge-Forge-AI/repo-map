"""Stream validation owns partially initialized row writers until transfer."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from common_lore_index.artifacts import _bundle_stream_parse as parser_module
from common_lore_index.artifacts._bundle_stream_parse import StreamingBundleParser
from common_lore_index.artifacts._bundle_stream_encode import PublicationExpectation
from common_lore_index.artifacts.receipt import ExtractionReceipt
from common_lore_index.artifacts.store import FileSystemArtifactStore
from common_lore_index.storage.row_spool import RowSpoolWriter
from repomap_test_support.portable_publication_fixtures import _bundle


def _inputs(tmp_path: Path) -> tuple[bytes, PublicationExpectation, ExtractionReceipt]:
    bundle = _bundle()
    raw = bundle.canonical_bytes()
    store_root = tmp_path / "store"
    store_root.mkdir(mode=0o700)
    store = FileSystemArtifactStore(store_root)
    reference = store.put(
        raw, media_type="application/x-repomap-publication-bundle-v1+jsonl",
        record_format="canonical-jsonl-v1", privacy=bundle.privacy,
    )
    expectation = PublicationExpectation.from_bundle(bundle, mutating_owner_count=1)
    receipt = ExtractionReceipt.create(
        request_id=bundle.request_id, job_id=bundle.job_id, attempt=bundle.attempt, graph_id=bundle.graph_id,
        worker_capability_identity=expectation.worker_capability_identity, contract_version="1.0",
        source_generation=bundle.source_generation, config_generation=bundle.config_generation,
        extractor_generation=bundle.extractor_generation, canonicalizer_generation=bundle.canonicalizer_generation,
        snapshot_manifest_id=bundle.snapshot_manifest_id, snapshot_vector=bundle.snapshot_vector,
        resolver_identity=bundle.resolver_identity, extractor_capability_identity=bundle.extractor_capability_identity,
        canonicalizer_identity=bundle.canonicalizer_identity,
        semantic_contract_identity=bundle.semantic_contract_identity, quality_rule_identity=bundle.quality_rule_identity,
        outcome="completed", cancellation="not-requested", bundle_reference=reference, bundle_id=bundle.bundle_id,
        family_counts=bundle.family_counts, diagnostic_category=None, diagnostic_summary=(),
        producer_identity="producer1:conformance-python", attestation_class="untrusted-self-assertion",
    )
    return raw, expectation, receipt


@pytest.mark.parametrize("fail_after", [0, 3, 6])
def test_partial_writer_setup_failure_reclaims_every_created_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_after: int,
) -> None:
    raw, expected, receipt = _inputs(tmp_path)
    spool_root = tmp_path / "spools"
    spool_root.mkdir()
    marker = RuntimeError("synthetic fourth writer allocation refusal")
    created: list[RowSpoolWriter] = []

    def create_writer(*, dir: Path | str | None = None) -> RowSpoolWriter:
        if len(created) == fail_after:
            raise marker
        writer = RowSpoolWriter(dir=dir)
        created.append(writer)
        return writer

    leftovers: tuple[Path, ...] = ()
    try:
        monkeypatch.setattr(parser_module, "RowSpoolWriter", create_writer)
        with pytest.raises(RuntimeError) as caught:
            StreamingBundleParser(spool_dir=spool_root).parse_and_validate(
                io.BytesIO(raw), expected, receipt, stage_id="stage-custody",
            )
        assert caught.value is marker and len(created) == fail_after
        leftovers = tuple(spool_root.iterdir())
    finally:
        for writer in created:
            writer.abort()
    assert leftovers == ()


class Interrupted(BaseException):
    """In-process interruption, without a native test control mechanism."""


@pytest.mark.parametrize("fail_after", [0, 3, 6])
def test_partial_finish_reclaims_both_transferred_and_unfinished_spools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_after: int,
) -> None:
    raw, expected, receipt = _inputs(tmp_path)
    spool_root = tmp_path / "spools"
    spool_root.mkdir()
    marker = Interrupted()
    writers: list[RowSpoolWriter] = []
    finished = 0

    class Writer(RowSpoolWriter):
        def finish(self):
            nonlocal finished
            if finished == fail_after:
                raise marker
            spool = super().finish()
            finished += 1
            return spool

    def create_writer(*, dir=None):
        writer = Writer(dir=dir)
        writers.append(writer)
        return writer

    try:
        monkeypatch.setattr(parser_module, "RowSpoolWriter", create_writer)
        with pytest.raises(Interrupted) as caught:
            StreamingBundleParser(spool_dir=spool_root).parse_and_validate(
                io.BytesIO(raw), expected, receipt, stage_id="stage-custody",
            )
        assert caught.value is marker
        assert finished == fail_after and len(writers) == 7
        assert all(writer._handle.closed for writer in writers)
        assert not tuple(spool_root.iterdir())
    finally:
        for writer in writers:
            writer._handle.close()
            writer.path.unlink(missing_ok=True)


def test_link_close_failure_does_not_release_returned_spools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, expected, receipt = _inputs(tmp_path)
    spool_root = tmp_path / "spools"
    spool_root.mkdir()
    original_close = parser_module.DiskFamilyLinkValidator.close
    marker = Interrupted()

    def close(validator):
        original_close(validator)
        raise marker

    monkeypatch.setattr(parser_module.DiskFamilyLinkValidator, "close", close)
    with pytest.raises(Interrupted) as caught:
        StreamingBundleParser(spool_dir=spool_root).parse_and_validate(
            io.BytesIO(raw), expected, receipt, stage_id="stage-custody",
        )
    assert caught.value is marker
    assert not tuple(spool_root.iterdir())


def test_secondary_abort_failure_preserves_parse_error_and_finishes_cleanup_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, expected, receipt = _inputs(tmp_path)
    spool_root = tmp_path / "spools"
    spool_root.mkdir()
    primary = Interrupted()
    aborted: list[int] = []

    class Writer(RowSpoolWriter):
        def write_row(self, row):
            raise primary

        def abort(self):
            super().abort()
            aborted.append(id(self))
            if len(aborted) == 1:
                raise OSError("synthetic abort refusal after release")

    monkeypatch.setattr(parser_module, "RowSpoolWriter", Writer)
    with pytest.raises(Interrupted) as caught:
        StreamingBundleParser(spool_dir=spool_root).parse_and_validate(
            io.BytesIO(raw), expected, receipt, stage_id="stage-custody",
        )
    assert caught.value is primary
    assert len(aborted) == len(set(aborted)) == 7
    assert not tuple(spool_root.iterdir())
