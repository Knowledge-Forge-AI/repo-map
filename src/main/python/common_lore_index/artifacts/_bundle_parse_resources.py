"""Custody of parser temporaries through validation and successful transfer."""
from __future__ import annotations

from types import TracebackType

from common_lore_index.artifacts._bundle_stream_links import DiskFamilyLinkValidator
from common_lore_index.storage.row_spool import RowSpool, RowSpoolWriter
from common_lore_index.storage.staging_family_rows import StageFamily


class BundleParseResources:
    """Register each acquisition immediately; release only after link cleanup."""

    def __init__(self) -> None:
        self.writers: dict[StageFamily, RowSpoolWriter] = {}
        self.spools: dict[StageFamily, RowSpool] = {}
        self.links: DiskFamilyLinkValidator | None = None
        self.transfer = False

    def finish_rows(self) -> dict[StageFamily, RowSpool]:
        for family, writer in self.writers.items():
            self.spools[family] = writer.finish()
        return self.spools

    def __enter__(self) -> BundleParseResources:
        return self

    def __exit__(
        self, _type: type[BaseException] | None,
        primary: BaseException | None, _trace: TracebackType | None,
    ) -> None:
        cleanup_error: BaseException | None = None
        if self.links is not None:
            try:
                self.links.close()
            except BaseException as error:
                cleanup_error = error
        if primary is not None or cleanup_error is not None or not self.transfer:
            for spool in self.spools.values():
                try:
                    spool.close()
                except BaseException as error:
                    if cleanup_error is None:
                        cleanup_error = error
            for writer in self.writers.values():
                try:
                    writer.abort()
                except BaseException as error:
                    if cleanup_error is None:
                        cleanup_error = error
        if primary is None and cleanup_error is not None:
            raise cleanup_error
