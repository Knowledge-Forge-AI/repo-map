"""Captured projections cannot omit the mandatory publisher validation inputs."""

from __future__ import annotations

from dataclasses import replace

import pytest

from common_lore_index.retrieval.publication_binding import CorrespondenceRefusal, check_correspondence
from repomap_test_support.retrieval_evaluation_query_fixture import build_fixture_projection


@pytest.mark.parametrize("field", ["manifest_reference", "bundle_reference", "receipt_reference", "spool_dir"])
def test_missing_publisher_validation_input_refuses_instead_of_available(field: str) -> None:
    inputs, _ = build_fixture_projection()
    if field == "manifest_reference":
        candidate = replace(inputs, manifest_reference=None)
    elif field == "bundle_reference":
        candidate = replace(inputs, bundle_reference=None)
    elif field == "receipt_reference":
        candidate = replace(inputs, receipt_reference=None)
    else:
        candidate = replace(inputs, spool_dir=None)
    with pytest.raises(CorrespondenceRefusal, match="required"):
        check_correspondence(candidate)
