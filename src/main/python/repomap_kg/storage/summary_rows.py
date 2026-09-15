"""Storage summary record compatibility facade."""

from __future__ import annotations

from repomap_kg.storage.summary_rows_domains import (
    EmailSummaryRecord,
    OpenAPISummaryRecord,
    TerraformSummaryRecord,
    email_summary_from_storage_payload,
    openapi_summary_from_storage_payload,
    terraform_summary_from_storage_payload,
)
from repomap_kg.storage.summary_rows_languages import (
    JSFrameworkSummaryRecord,
    JSSummaryRecord,
    PythonSummaryRecord,
    RubySummaryRecord,
    js_framework_summary_from_storage_payload,
    js_summary_from_storage_payload,
    python_summary_from_storage_payload,
    ruby_summary_from_storage_payload,
)
from repomap_kg.storage.summary_rows_core import (
    _count_from_mapping as _count_from_mapping,
    _required_count_map_from_mapping as _required_count_map_from_mapping,
)
from repomap_kg.storage.summary_rows_manifest import (
    APISummaryRecord,
    BulkSummaryRecord,
    api_manifest_summary_payload,
    api_summary_from_storage_payload,
    bulk_manifest_summary_payload,
    bulk_summary_from_storage_payload,
    read_api_manifest_payloads,
    read_bulk_manifest_payloads,
)
from repomap_kg.storage.summary_rows_nix import (
    NixSummaryRecord,
    _nix_flake_inputs_from_payload as _nix_flake_inputs_from_payload,
    _nix_nested_count_map_from_payload as _nix_nested_count_map_from_payload,
    nix_summary_from_storage_payload,
)
from repomap_kg.storage.summary_rows_storage import (
    CanonicalLoadSummary,
    CanonicalStorageSummaryRecord,
    LoadSummary,
    canonical_load_summary_from_payload,
    canonical_storage_summary_from_payload,
    load_summary_from_payload,
)

__all__ = (
    "LoadSummary",
    "CanonicalLoadSummary",
    "CanonicalStorageSummaryRecord",
    "RubySummaryRecord",
    "JSSummaryRecord",
    "JSFrameworkSummaryRecord",
    "OpenAPISummaryRecord",
    "TerraformSummaryRecord",
    "PythonSummaryRecord",
    "NixSummaryRecord",
    "EmailSummaryRecord",
    "BulkSummaryRecord",
    "APISummaryRecord",
    "bulk_manifest_summary_payload",
    "read_bulk_manifest_payloads",
    "api_manifest_summary_payload",
    "read_api_manifest_payloads",
    "canonical_storage_summary_from_payload",
    "ruby_summary_from_storage_payload",
    "js_summary_from_storage_payload",
    "js_framework_summary_from_storage_payload",
    "openapi_summary_from_storage_payload",
    "terraform_summary_from_storage_payload",
    "python_summary_from_storage_payload",
    "nix_summary_from_storage_payload",
    "email_summary_from_storage_payload",
    "bulk_summary_from_storage_payload",
    "api_summary_from_storage_payload",
    "load_summary_from_payload",
    "canonical_load_summary_from_payload",
)
