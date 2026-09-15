from __future__ import annotations



API_RECORD_EXPORTS = (
    "ApiAcquireSummary",
    "ApiEndpointConfig",
    "ApiPlanManifest",
    "ApiPolicyError",
    "ApiRequestPlan",
    "ApiResponseRecord",
    "ApiSourceConfig",
    "ApiTransportResponse",
)


def test_rootpkg27_api_reexports_record_contracts() -> None:
    import repomap_kg.ops.ingestion.api as api
    import repomap_kg.ops.ingestion.api_records as records
    for name in API_RECORD_EXPORTS:
        assert getattr(api, name) is getattr(records, name)
