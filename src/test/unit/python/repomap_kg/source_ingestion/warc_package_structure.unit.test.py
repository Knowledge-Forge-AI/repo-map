from __future__ import annotations



WARC_RECORD_EXPORTS = (
    "WarcImportSummary",
    "WarcManifest",
    "WarcRecordSummary",
    "WarcSourceConfig",
)


def test_rootpkg26_source_reexports_warc_records_and_config_loader() -> None:
    import common_lore_index.ops.ingestion.source as source
    import common_lore_index.ops.ingestion.source_warc_records as records
    import common_lore_index.ops.ingestion.source_warc_config as config
    for name in WARC_RECORD_EXPORTS:
        assert getattr(source, name) is getattr(records, name)
    assert source.load_warc_source_config is config.load_warc_source_config
