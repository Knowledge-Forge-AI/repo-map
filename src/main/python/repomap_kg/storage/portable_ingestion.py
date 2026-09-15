"""Trusted projection of validated portable bundle rows into one stage."""

from __future__ import annotations

from types import MappingProxyType
from collections.abc import Mapping
from typing import cast

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from repomap_kg.storage.staged_rows import PreparedStageRows
from repomap_kg.storage.staging_checksums import FamilyChecksum, checksum_family
from repomap_kg.storage.staging_family_catalog import family_privacy_classifications
from repomap_kg.storage.staging_family_contracts import (
    PrivacyClassification,
    STAGING_FAMILY_DESCRIPTORS,
)


def prepare_portable_bundle_rows(
    bundle: PublicationBundle,
    *,
    stage_id: str,
) -> PreparedStageRows:
    """Replace only the non-authoritative placeholder after validation."""

    if bundle.row_stage_contract != "stage-unassigned-v1":
        raise ValueError("current portable stage contract is required")
    if tuple(bundle.families) != PUBLICATION_FAMILIES:
        raise ValueError("portable bundle families are incomplete")
    projected: dict[str, tuple[dict[str, object], ...]] = {}
    checksums: dict[str, FamilyChecksum] = {}
    for family in PUBLICATION_FAMILIES:
        rows = bundle.families[family]
        if any(row.get("stage_id") != "stage-unassigned" for row in rows):
            raise ValueError("portable bundle stage identity is invalid")
        family_rows = tuple({**row, "stage_id": stage_id} for row in rows)
        projected[family] = family_rows
        checksums[family] = checksum_family(
            ({key: value for key, value in row.items() if key != "stage_id"} for row in family_rows),
            identity_fields=STAGING_FAMILY_DESCRIPTORS[family].identity_columns,
        )
    row_counts: dict[str, int] = {
        family: checksums[family].row_count for family in PUBLICATION_FAMILIES
    }
    if row_counts != bundle.family_counts:
        raise ValueError("portable bundle family counts are inconsistent")
    return PreparedStageRows(
        family_rows=MappingProxyType(projected),
        checksums=MappingProxyType(checksums),
        row_counts=MappingProxyType(row_counts),
        normalized_byte_counts=MappingProxyType(
            {family: checksums[family].normalized_byte_count for family in PUBLICATION_FAMILIES}
        ),
        privacy_classifications=cast(
            Mapping[str, PrivacyClassification], family_privacy_classifications()
        ),
        files=row_counts["files"],
    )


__all__ = ("prepare_portable_bundle_rows",)
