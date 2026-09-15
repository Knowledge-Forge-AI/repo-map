from __future__ import annotations



def test_bulk_manifest_summary_payload_read_bulk_manifest_payloads_api_manifest_summary_payload_read_api_manifest_payloads_bulk_summary_from_storage_payload_api_summary_from_storage_payload_manifest_records_contracts(
    tmp_path,
) -> None:
    import repomap_kg.storage.summary_rows_manifest as summary_rows_manifest
    bulk_manifest = tmp_path / ".repomap" / "bulk-runs" / "source" / "run" / "manifest.json"
    bulk_manifest.parent.mkdir(parents=True)
    bulk_manifest.write_text(
        """{
            "bulk_run_id": "bulk-1",
            "source_id": "source-1",
            "corpus_kind": "email_export",
            "policy_status": "accepted",
            "file_count_included": 3,
            "file_count_skipped": 2,
            "total_bytes_included": 123,
            "extractor_counts": {"python": 1},
            "diagnostic_counts": {"policy": 2},
            "redaction_counts": {"private_path": 1},
            "skipped_files": [{"reason": "archive_deferred"}],
            "limit_hit": true,
            "limit_reason": "max_files_exceeded,max_depth_exceeded"
        }""",
        encoding="utf-8",
    )
    bad_bulk_manifest = (
        tmp_path / ".repomap" / "bulk-runs" / "source" / "bad" / "manifest.json"
    )
    bad_bulk_manifest.parent.mkdir(parents=True)
    bad_bulk_manifest.write_text("[not an object]", encoding="utf-8")

    bulk_payloads = summary_rows_manifest.read_bulk_manifest_payloads(
        tmp_path / ".repomap" / "bulk-runs",
        root_path=tmp_path.resolve(),
    )
    assert len(bulk_payloads) == 2

    bulk_summary_payload = summary_rows_manifest.bulk_manifest_summary_payload(tmp_path)
    assert bulk_summary_payload["bulk_runs"] == 1
    assert bulk_summary_payload["sources"] == 1
    assert bulk_summary_payload["source_ids"] == ["source-1"]
    assert bulk_summary_payload["file_count_included"] == 3
    assert bulk_summary_payload["redaction_counts"] == {"private_path": 1}
    assert bulk_summary_payload["diagnostic_counts"] == {
        "manifest_parse_error": 1,
        "policy": 2,
    }
    assert bulk_summary_payload["archive_deferred"] == 1
    assert bulk_summary_payload["limit_hit_count"] == 1
    assert bulk_summary_payload["max_files_hit_count"] == 1
    assert bulk_summary_payload["max_depth_hit_count"] == 1

    bulk_summary = summary_rows_manifest.bulk_summary_from_storage_payload(
        bulk_summary_payload
    )
    assert bulk_summary.to_dict()["source_ids"] == ("source-1",)
    assert bulk_summary.to_dict()["no_external_fetch"] is True

    api_manifest = tmp_path / ".repomap" / "api-runs" / "source" / "run" / "manifest.json"
    api_manifest.parent.mkdir(parents=True)
    api_manifest.write_text(
        """{
            "api_run_id": "api-1",
            "source_id": "source-1",
            "source_type": "github.api",
            "api_source_class": "github",
            "provider_name": "github",
            "provider_product": "issues",
            "policy_status": "accepted",
            "no_network": false,
            "no_mutation": false,
            "no_credentials_resolved": false,
            "no_scheduler": false,
            "requests": [{
                "endpoint_name": "repo",
                "method": "GET",
                "downstream_route": "json",
                "response_type": "application/json"
            }],
            "responses": [{
                "endpoint_name": "repo",
                "response_byte_count": 12,
                "redacted": true,
                "artifact_path": "artifact.json"
            }]
        }""",
        encoding="utf-8",
    )
    bad_api_manifest = (
        tmp_path / ".repomap" / "api-runs" / "source" / "bad" / "manifest.json"
    )
    bad_api_manifest.parent.mkdir(parents=True)
    bad_api_manifest.write_text("not-json", encoding="utf-8")

    api_payloads = summary_rows_manifest.read_api_manifest_payloads(
        tmp_path / ".repomap" / "api-runs",
        root_path=tmp_path.resolve(),
    )
    assert len(api_payloads) == 2

    api_summary_payload = summary_rows_manifest.api_manifest_summary_payload(tmp_path)
    assert api_summary_payload["api_runs"] == 1
    assert api_summary_payload["sources"] == 1
    assert api_summary_payload["endpoint_names"] == ["repo"]
    assert api_summary_payload["methods"] == {"GET": 1}
    assert api_summary_payload["redacted_responses"] == 1
    assert api_summary_payload["diagnostic_counts"] == {"manifest_parse_error": 1}
    assert api_summary_payload["no_network"] is False
    assert api_summary_payload["no_mutation"] is False
    assert api_summary_payload["no_credentials_resolved"] is False
    assert api_summary_payload["no_scheduler"] is False

    api_summary = summary_rows_manifest.api_summary_from_storage_payload(
        api_summary_payload
    )
    assert api_summary.to_dict()["source_ids"] == ("source-1",)
    assert api_summary.to_dict()["no_provider_specific_behavior"] is True
