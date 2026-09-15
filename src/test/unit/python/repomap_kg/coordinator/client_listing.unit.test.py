from unittest.mock import patch

from repomap_kg.coordinator.client import LocalCoordinatorClient


def test_client_list_jobs_uses_only_bounded_listing_fields(tmp_path):
    token = tmp_path / "token"
    token.write_text("secret", encoding="utf-8")
    token.chmod(0o600)
    client = LocalCoordinatorClient(tmp_path / "coordinator.sock", token)
    with patch.object(client, "_request", return_value={"jobs": []}) as request:
        assert client.list_jobs(limit=12, graph_id="repo-map", cursor="opaque") == {
            "jobs": []
        }
    request.assert_called_once_with(
        "list",
        {"limit": 12, "graph_id": "repo-map", "cursor": "opaque"},
    )
