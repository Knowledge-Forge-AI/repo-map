import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from repomap_kg.ops.direct_publication import publish_observation_generation
from repomap_kg.storage import LoadSummary
from repomap_kg.graph.multi_source import graph_source_binding_id
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.graph_files import GraphFileFilters, query_graph_files
from repomap_test_support.cli_in_process import run_repo_map_in_process


def publish_acquisition_summary(
    postgres,
    summary,
    *,
    repository_name: str,
    root_path: Path | str,
) -> LoadSummary:
    """Publish retained acquisition observations for an explicit test fixture."""

    return publish_observation_generation(
        postgres.psql_args,
        summary.raw_observations,
        repository_name=repository_name,
        root_path=str(root_path),
        psql_command=postgres.psql_command,
    )


class FakeOpener:
    def __init__(self, response_or_error):
        self.response_or_error = response_or_error
        self.request = None
        self.timeout = None

    def open(self, request, *, timeout):
        self.request = request
        self.timeout = timeout
        if isinstance(self.response_or_error, Exception):
            raise self.response_or_error
        return self.response_or_error


class FakeResponse:
    def __init__(self, status, body, headers):
        self.status = status
        self._body = body
        self.headers = headers

    def getcode(self):
        return self.status

    def read(self, limit):
        return self._body[:limit]


class FakeBody:
    def __init__(self, body):
        self.body = body

    def read(self, limit=-1):
        if limit < 0:
            return self.body
        return self.body[:limit]

    def close(self):
        return None


class IntFakeGitHubOpener:
    def __init__(self, *, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self.headers = headers
        self.body = body
        self.requests: list[object] = []

    def open(self, request, timeout):
        self.requests.append(request)
        return IntFakeGitHubResponse(
            status=self.status,
            headers=self.headers,
            body=self.body,
        )


class IntFakeGitHubResponse:
    def __init__(self, *, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    def getcode(self):
        return self.status

    def read(self, _size):
        return self.body


def fake_loader(_psql_args, _observations, **_kwargs):
    return LoadSummary(repository_id=1, run_id=1, files=1)


def fixed_clock() -> datetime:
    return datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)


def source_fixture(filename: str) -> Path:
    return test_fixture_root() / "source_ingestion" / "feed_sources" / filename


def archive_source_fixture(filename: str) -> Path:
    return source_ingestion_fixture_root() / "archive_sources" / filename


def warc_source_fixture(filename: str) -> Path:
    return source_ingestion_fixture_root() / "warc_sources" / filename


def copy_warc_fixture_root(parent: Path) -> Path:
    root = parent / "source_ingestion"
    root.mkdir()
    shutil.copytree(
        source_ingestion_fixture_root() / "warc_artifacts",
        root / "warc_artifacts",
    )
    shutil.copytree(
        source_ingestion_fixture_root() / "warc_sources",
        root / "warc_sources",
    )
    return root


def write_warc_source_config(
    path: Path,
    *,
    artifact_path: str = "warc_artifacts/example.warc",
    policy_status: str = "allowed",
    max_artifact_bytes: int = 1048576,
    extra: str = "",
) -> Path:
    path.write_text(
        "\n".join(
            [
                "[source]",
                'id = "example-warc-error-case"',
                'type = "saved_page.archive"',
                'display_name = "Example WARC Error Case"',
                "",
                "[policy]",
                f'status = "{policy_status}"',
                f"max_artifact_bytes = {max_artifact_bytes}",
                "max_file_count = 10",
                "max_warc_records = 100",
                "max_record_bytes = 1048576",
                "max_total_payload_bytes = 1048576",
                'retention_policy = "materialize-safe-payloads"',
                "requires_manual_review = false",
                "",
                "[artifact]",
                f'path = "{artifact_path}"',
                'kind = "warc"',
                'profile = "warc-local-archive"',
                extra,
            ]
        ),
        encoding="utf-8",
    )
    return path


def int_warc_record(
    record_type: str,
    record_id: str | None,
    target_uri: str | None,
    body: bytes,
    *,
    content_type: str,
    include_date: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    headers = {
        "WARC-Type": record_type,
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
    }
    if record_id is not None:
        headers["WARC-Record-ID"] = f"<{record_id}>"
    if include_date:
        headers["WARC-Date"] = "2026-06-30T12:00:00Z"
    if target_uri is not None:
        headers["WARC-Target-URI"] = target_uri
    if extra_headers:
        headers.update(extra_headers)
    return (
        b"WARC/1.1\r\n"
        + b"".join(
            f"{key}: {value}\r\n".encode("utf-8")
            for key, value in headers.items()
        )
        + b"\r\n"
        + body
        + b"\r\n\r\n"
    )


def test_fixture_root() -> Path:
    return Path(__file__).parents[3] / "fixtures"


def source_ingestion_fixture_root() -> Path:
    return test_fixture_root() / "source_ingestion"


def bulk_fixture_root() -> Path:
    return test_fixture_root() / "bulk"


def api_fixture_root() -> Path:
    return test_fixture_root() / "api"


def github_api_fixture_root() -> Path:
    return test_fixture_root() / "github_api"


def assert_public_path_readback(config_path, psql_command, roots):
    """Check the public graph-files contract on a published source fixture."""
    config = load_ops_config(config_path)
    if len(roots) == 2:
        _assert_public_path_filters(config, psql_command)
        _assert_public_path_cli(config_path, psql_command, roots)
        return
    for filters in (GraphFileFilters(path="modules/default.nix"),
                    GraphFileFilters(path_prefix="modules/")):
        page = query_graph_files(config, "fixture-graph", filters=filters,
                                 psql_command=psql_command)
        assert [(row.canonical_key, row.path) for row in page.records] == [
            ("file:root/modules/default.nix", "modules/default.nix")
        ]


def _assert_public_path_filters(config, psql_command):
    keys = ["file:composition/modules/default.nix", "file:entry/modules/default.nix"]
    for filters in (GraphFileFilters(path="modules/default.nix"),
                    GraphFileFilters(path_prefix="modules/")):
        page = query_graph_files(config, "fixture-graph", filters=filters,
                                 psql_command=psql_command)
        assert [row.canonical_key for row in page.records] == keys
        assert {row.path for row in page.records} == {"modules/default.nix"}
        assert {row.binding_alias for row in page.records} == {"entry", "composition"}
        assert {row.binding_id for row in page.records} == {
            graph_source_binding_id("fixture-graph", alias)
            for alias in ("entry", "composition")
        }
        assert all(row.snapshot_id and row.candidate_id for row in page.records)
        for offset in range(3):
            part = query_graph_files(config, "fixture-graph", filters=filters,
                                     limit=1, offset=offset, psql_command=psql_command)
            assert [row.canonical_key for row in part.records] == keys[offset:offset + 1]
            assert part.has_more is (offset == 0)
    for filters in (GraphFileFilters(path="entry/modules/default.nix"),
                    GraphFileFilters(path_prefix="entry/modules/")):
        page = query_graph_files(config, "fixture-graph", filters=filters,
                                 psql_command=psql_command)
        # Metadata-less referenced nodes may expose an alias-prefixed public path.
        assert not set(keys).intersection(row.canonical_key for row in page.records)


def _assert_public_path_cli(config_path, psql_command, roots):
    for path, expected_count in (("modules/default.nix", 2), ("absent.nix", 0)):
        code, stdout, stderr = run_repo_map_in_process(
            "ops", "graph-files", "--config", str(config_path),
            "--graph", "fixture-graph", "--psql-command", psql_command,
            "--path", path, "--json",
        )
        assert code == 0, stderr
        payload = json.loads(stdout)
        assert payload["result"] == "success" and payload["schema_version"] == 1
        records = payload["files"]
        assert len(records) == expected_count
        assert payload["pagination"]["has_more"] is False
        if records:
            assert {row["path"] for row in records} == {path}
            assert {row["source_binding"]["alias"] for row in records} == {"entry", "composition"}
            assert len({row["canonical_key"] for row in records}) == 2
        assert all(str(root) not in stdout + stderr for root in roots)
