import json
import unittest
from pathlib import Path

from repomap_kg.storage import LoadSummary


class GitHubApiIngestionTestSupport(unittest.TestCase):
    def write_github_fixture(
        self,
        root: Path,
        *,
        policy_status: str = "allowed_with_limits",
        provider_name: str = "GitHub",
        provider_product: str = "GitHub REST API",
        source_type: str = "api.rest",
        api_source_class: str = "api.github.repository",
        owner: str = "fixture-owner",
        repository: str = "fixture-repo",
        repository_visibility: str = "public",
        credential_mode: str = "none_public_readonly",
        include_credentials: bool = False,
        credentials_ref: str = "local_secret_ref:fixture-github-token",
        include_consent: bool = True,
        consent_revoked: bool = False,
        consent_mutation_allowed: bool = False,
        authorized_operations: tuple[str, ...] = ("read",),
        authorized_data_classes: tuple[str, ...] = (
            "repository_metadata",
            "issues",
            "pull_requests",
            "releases",
            "actions",
        ),
        method: str = "GET",
        endpoint_path: str = "/repos/{owner}/{repo}",
        endpoint_names: tuple[str, ...] = ("repository",),
        pagination: str = "none",
        downstream_route: str = "config",
        fixture_response_path: str | None = None,
        transport_mode: str = "fixture",
        base_url: str = "https://api.github.com",
        follow_redirects: bool = False,
        user_agent: str = "repomap-kg-test",
        include_fixture_paths: bool = True,
        max_requests_per_run: int = 20,
        max_pages_per_endpoint: int = 1,
        max_bytes_per_run: int = 10485760,
        max_items_per_endpoint: int = 100,
        max_concurrent_requests: int = 1,
        max_retries: int = 0,
    ) -> Path:
        fixture = root / f"github-api-{len(list(root.glob('github-api-*')))}"
        fixture.mkdir()
        responses = fixture / "responses"
        responses.mkdir()
        self.write_github_responses(responses)
        credentials_block = (
            "\n[credentials]\n"
            f'credentials_ref = "{credentials_ref}"\n'
            if include_credentials
            else ""
        )
        consent_block = (
            "\n[consent]\n"
            'consent_ref = "local_consent_ref:github-public-fixture-2026-07"\n'
            f"authorized_operations = {json.dumps(list(authorized_operations))}\n"
            f"authorized_data_classes = {json.dumps(list(authorized_data_classes))}\n"
            f"revoked = {str(consent_revoked).lower()}\n"
            f"mutation_allowed = {str(consent_mutation_allowed).lower()}\n"
            if include_consent
            else ""
        )
        endpoint_blocks = []
        endpoint_map = {
            "repository": ("/repos/{owner}/{repo}", "responses/repository.json", 1),
            "issues": ("/repos/{owner}/{repo}/issues", "responses/issues.json", 100),
            "pulls": ("/repos/{owner}/{repo}/pulls", "responses/pulls.json", 100),
            "releases": ("/repos/{owner}/{repo}/releases", "responses/releases.json", 100),
            "actions_runs": (
                "/repos/{owner}/{repo}/actions/runs",
                "responses/actions-runs.json",
                100,
            ),
        }
        for name in endpoint_names:
            default_path, default_fixture, max_page_size = endpoint_map[name]
            path = endpoint_path if len(endpoint_names) == 1 else default_path
            response_path = fixture_response_path or default_fixture
            endpoint_blocks.append(
                "\n[[endpoints]]\n"
                f'name = "{name}"\n'
                f'method = "{method}"\n'
                f'path = "{path}"\n'
                f'purpose = "Export GitHub fixture {name} metadata"\n'
                'response_type = "application/json"\n'
                f"max_page_size = {max_page_size}\n"
                f'pagination = "{pagination}"\n'
                f'downstream_route = "{downstream_route}"\n'
                + (
                    f'fixture_response_path = "{response_path}"\n'
                    if include_fixture_paths
                    else ""
                )
            )
        config_path = fixture / "github-source.toml"
        config_path.write_text(
            "[source]\n"
            'source_id = "github-public-fixture"\n'
            f'source_type = "{source_type}"\n'
            f'api_source_class = "{api_source_class}"\n'
            f'provider_name = "{provider_name}"\n'
            f'provider_product = "{provider_product}"\n'
            f'policy_status = "{policy_status}"\n'
            f'owner = "{owner}"\n'
            f'repository = "{repository}"\n'
            f'repository_visibility = "{repository_visibility}"\n'
            "read_only = true\n"
            "mutation_allowed = false\n"
            f'credential_mode = "{credential_mode}"\n'
            f"{credentials_block}"
            "\n[acquisition]\n"
            f'transport = "{transport_mode}"\n'
            f'base_url = "{base_url}"\n'
            "timeout_seconds = 10\n"
            f"follow_redirects = {str(follow_redirects).lower()}\n"
            f"user_agent = {json.dumps(user_agent)}\n"
            f"{consent_block}"
            "\n[limits]\n"
            f"max_requests_per_run = {max_requests_per_run}\n"
            "max_requests_per_minute = 10\n"
            f"max_pages_per_endpoint = {max_pages_per_endpoint}\n"
            f"max_items_per_endpoint = {max_items_per_endpoint}\n"
            f"max_bytes_per_run = {max_bytes_per_run}\n"
            f"max_concurrent_requests = {max_concurrent_requests}\n"
            f"max_retries = {max_retries}\n"
            "\n[retention]\n"
            'policy = "local_user_controlled"\n'
            'raw_response_retention = "minimized"\n'
            'redacted_response_retention = "retain"\n'
            "\n[redaction]\n"
            'profile = "strict"\n'
            'sensitivity = "public_metadata"\n'
            f"{''.join(endpoint_blocks)}",
            encoding="utf-8",
        )
        return config_path

    def write_github_responses(self, responses: Path) -> None:
        (responses / "repository.json").write_text(
            json.dumps(
                {
                    "id": 1001,
                    "name": "fixture-repo",
                    "full_name": "fixture-owner/fixture-repo",
                    "private": False,
                    "clone_url": "https://fixture-github-token@example.invalid/fixture.git",
                    "ssh_url": "git@example.invalid:fixture-owner/fixture-repo.git",
                    "html_url": "https://example.invalid/fixture-owner/fixture-repo",
                    "secret": "fixture-secret-value",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (responses / "issues.json").write_text(
            json.dumps(
                [
                    {
                        "number": 1,
                        "title": "Fixture issue",
                        "body": "safe public issue body",
                        "author_association": "OWNER",
                        "token": "fixture-github-token",
                    }
                ],
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (responses / "pulls.json").write_text(
            json.dumps(
                [
                    {
                        "number": 2,
                        "title": "Fixture pull",
                        "diff_url": "https://example.invalid/fixture.diff",
                        "patch_url": "https://example.invalid/fixture.patch",
                    }
                ],
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (responses / "releases.json").write_text(
            json.dumps(
                [
                    {
                        "tag_name": "v1.0.0",
                        "tarball_url": "https://api.github.com/repos/fixture-owner/fixture-repo/tarball/v1.0.0",
                        "zipball_url": "https://api.github.com/repos/fixture-owner/fixture-repo/zipball/v1.0.0",
                    }
                ],
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (responses / "actions-runs.json").write_text(
            json.dumps(
                {
                    "workflow_runs": [
                        {
                            "id": 3001,
                            "name": "CI",
                            "status": "completed",
                            "conclusion": "success",
                            "logs_url": "https://api.github.com/repos/fixture-owner/fixture-repo/actions/runs/3001/logs?token=fixture-private-key",
                            "artifacts_url": "https://api.github.com/repos/fixture-owner/fixture-repo/actions/runs/3001/artifacts?token=fixture-private-key",
                        }
                    ]
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def fake_loader(self, calls: list[dict[str, object]]):
        def load(psql_args, observations, **kwargs):
            calls.append(
                {
                    "psql_args": tuple(psql_args),
                    "observations": tuple(observations),
                    **kwargs,
                }
            )
            return LoadSummary(repository_id=7, run_id=11, files=1)

        return load

class FakeGitHubTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def fetch(self, config, request):
        self.requests.append((config, request))
        return self.responses.pop(0)


class FakeGitHubOpener:
    def __init__(self, *, status, headers, body):
        self.status = status
        self.headers = headers
        self.body = body
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        return FakeGitHubHttpResponse(
            status=self.status,
            headers=self.headers,
            body=self.body,
        )


class FakeGitHubErrorOpener:
    def __init__(self, error):
        self.error = error

    def open(self, request, timeout):
        raise self.error


class FakeGitHubHttpResponse:
    def __init__(self, *, status, headers, body):
        self.status = status
        self.headers = headers
        self._body = body

    def getcode(self):
        return self.status

    def read(self, _size):
        return self._body


class FakeErrorBody:
    def __init__(self, body):
        self.body = body

    def read(self, _size):
        return self.body

    def close(self):
        return None


if __name__ == "__main__":
    unittest.main()
