"""Deterministic public-safe test fixtures for Run25 acquisition and publication scenarios."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from repomap_kg.ops.ingestion.github_api import (
    GitHubApiSourceConfig,
    GitHubRequestPlan,
    GitHubTransportResponse,
)


@dataclass
class Run25DeterministicGitHubTransport:
    """Offline deterministic transport returning public-safe fixture responses."""

    status_code: int = 200
    remaining_rate: str = "58"
    canned_bodies: Mapping[str, bytes] | None = None
    error: Exception | None = None

    def fetch(
        self,
        config: GitHubApiSourceConfig,
        request: GitHubRequestPlan,
    ) -> GitHubTransportResponse:
        if self.error is not None:
            raise self.error

        headers = {
            "content-type": "application/json; charset=utf-8",
            "x-ratelimit-limit": "60",
            "x-ratelimit-remaining": str(self.remaining_rate),
            "x-ratelimit-used": "2",
            "x-ratelimit-reset": "1782921600",
        }
        rate_limit = {
            "x-ratelimit-limit": "60",
            "x-ratelimit-remaining": str(self.remaining_rate),
            "x-ratelimit-used": "2",
            "x-ratelimit-reset": "1782921600",
        }

        if self.canned_bodies and request.endpoint_name in self.canned_bodies:
            body = self.canned_bodies[request.endpoint_name]
        elif "issues" in request.endpoint_name or "pulls" in request.endpoint_name:
            body = json.dumps([
                {
                    "id": 101,
                    "title": "Public Issue",
                    "secret_note": "fixture-secret-note",
                    "html_url": "https://user:token123@github.com/test-owner/test-repo/issues/101",
                }
            ]).encode("utf-8")
        else:
            payload = {
                "id": 1,
                "name": config.repository,
                "full_name": f"{config.owner}/{config.repository}",
                "private": False,
                "description": "Deterministic public safe fixture repository",
                "clone_url": "https://user:ghp_faketoken@github.com/test-owner/test-repo.git",
                "secret_null": None,
                "secret_bool": True,
                "secret_number": 42,
                "secret_array": ["confidential-item-1"],
                "secret_object": {"internal_key": "private_value"},
            }
            body = json.dumps(payload).encode("utf-8")

        return GitHubTransportResponse(
            status_code=self.status_code,
            body=body,
            response_type="application/json",
            headers=headers,
            rate_limit=rate_limit,
        )


def make_run25_github_source_toml(
    *,
    source_id: str = "github-run25-fixture",
    owner: str = "run25-owner",
    repository: str = "run25-repo",
    visibility: str = "public",
    credential_mode: str = "none_public_readonly",
    transport: str = "github_public_rest",
    fixture_path: str | None = None,
    max_requests: int = 10,
    max_bytes: int = 1048576,
    max_items: int = 50,
    endpoint_path: str = "/repos/{owner}/{repo}",
    mutation_allowed: bool = False,
    consent_mutation_allowed: bool = False,
    extra_source: str = "",
    extra_consent: str = "",
    extra_body: str = "",
) -> str:
    """Build a public-safe TOML configuration for GitHub API ingestion."""
    lines = [
        "[source]",
        f'source_id = "{source_id}"',
        'source_type = "api.rest"',
        'api_source_class = "api.github.repository"',
        'provider_name = "GitHub"',
        'provider_product = "GitHub REST API"',
        'policy_status = "allowed_with_limits"',
        f'owner = "{owner}"',
        f'repository = "{repository}"',
        f'repository_visibility = "{visibility}"',
        'read_only = true',
        f'mutation_allowed = {"true" if mutation_allowed else "false"}',
        f'credential_mode = "{credential_mode}"',
    ]
    if extra_source:
        lines.append(extra_source)

    lines.extend([
        "",
        "[consent]",
        'consent_ref = "local_consent_ref:github-run25"',
        'authorized_operations = ["read"]',
        'authorized_data_classes = ["repository_metadata", "issues", "pull_requests"]',
        'revoked = false',
        f'mutation_allowed = {"true" if consent_mutation_allowed else "false"}',
    ])
    if extra_consent:
        lines.append(extra_consent)

    lines.extend([
        "",
        "[limits]",
        f"max_requests_per_run = {max_requests}",
        "max_requests_per_minute = 30",
        "max_pages_per_endpoint = 1",
        f"max_items_per_endpoint = {max_items}",
        f"max_bytes_per_run = {max_bytes}",
        "max_concurrent_requests = 1",
        "max_retries = 0",
        "",
        "[retention]",
        'policy = "local_user_controlled"',
        'raw_response_retention = "minimized"',
        'redacted_response_retention = "retain"',
        "",
        "[redaction]",
        'profile = "strict"',
        'sensitivity = "public_metadata"',
    ])
    if transport == "github_public_rest":
        lines.extend([
            "",
            "[acquisition]",
            'transport = "github_public_rest"',
            'base_url = "https://api.github.com"',
            "timeout_seconds = 10",
            "follow_redirects = false",
            'user_agent = "RepoMap/1.0"',
        ])
    elif transport == "fixture":
        lines.extend([
            "",
            "[acquisition]",
            'transport = "fixture"',
        ])

    lines.extend([
        "",
        "[[endpoints]]",
        'name = "repository"',
        'method = "GET"',
        f'path = "{endpoint_path}"',
        'purpose = "Export repository metadata"',
        'response_type = "application/json"',
        "max_page_size = 1",
        'pagination = "none"',
        'downstream_route = "config"',
        'data_class = "repository_metadata"',
    ])
    if fixture_path is not None:
        lines.append(f'fixture_response_path = "{fixture_path}"')
    if extra_body:
        lines.append(extra_body)
    return "\n".join(lines) + "\n"


def populate_run25_archive_source(artifact_root: Path) -> None:
    """Populate an archive artifact directory with polyglot and boundary files."""
    artifact_root.mkdir(parents=True, exist_ok=True)

    (artifact_root / "readme.md").write_text("# Readme\n", encoding="utf-8")
    (artifact_root / "notes.markdown").write_text("Notes\n", encoding="utf-8")
    (artifact_root / "run.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    (artifact_root / "build.bash").write_text("#!/bin/bash\necho build\n", encoding="utf-8")
    (artifact_root / "check.bats").write_text("@test 'sample' { true; }\n", encoding="utf-8")
    (artifact_root / "parse.awk").write_text("{ print $1 }\n", encoding="utf-8")
    (artifact_root / "env.zsh").write_text("export FOO=1\n", encoding="utf-8")
    (artifact_root / "suite.zunit").write_text("@test 'z' { assert true }\n", encoding="utf-8")
    (artifact_root / "app.py").write_text("print('repomap')\n", encoding="utf-8")
    (artifact_root / "default.nix").write_text("{ pkgs ? import <nixpkgs> {} }: {}\n", encoding="utf-8")
    (artifact_root / "setup.ps1").write_text("Write-Output 'ok'\n", encoding="utf-8")
    (artifact_root / "module.psm1").write_text("function Test-Mod { 'mod' }\n", encoding="utf-8")
    (artifact_root / "manifest.psd1").write_text("@{ ModuleVersion = '1.0' }\n", encoding="utf-8")
    (artifact_root / "spec.ts").write_text("const x: number = 1;\n", encoding="utf-8")
    (artifact_root / "entry.mts").write_text("export const m = 2;\n", encoding="utf-8")
    (artifact_root / "common.cts").write_text("module.exports = { c: 3 };\n", encoding="utf-8")
    (artifact_root / "view.tsx").write_text("export const Comp = () => null;\n", encoding="utf-8")
    (artifact_root / "style.css").write_text("body { color: red; }\n", encoding="utf-8")
    (artifact_root / "page.html").write_text("<html></html>\n", encoding="utf-8")
    (artifact_root / "data.json").write_text('{"key": "val"}', encoding="utf-8")
    (artifact_root / "settings.jsonc").write_text('{"key": "val" /* comment */}', encoding="utf-8")
    (artifact_root / "events.jsonl").write_text('{"event": 1}\n', encoding="utf-8")
    (artifact_root / "conf.toml").write_text('title = "test"\n', encoding="utf-8")
    (artifact_root / "feed.xml").write_text('<rss version="2.0"></rss>\n', encoding="utf-8")
    (artifact_root / "App.plist").write_text('<plist version="1.0"></plist>\n', encoding="utf-8")

    (artifact_root / "link_to_readme.md").symlink_to("readme.md")

    deep_dir = artifact_root / "d1" / "d2" / "d3" / "d4" / "d5" / "d6"
    deep_dir.mkdir(parents=True, exist_ok=True)
    (deep_dir / "deep_file.txt").write_text("deep\n", encoding="utf-8")

    (artifact_root / "oversized.bin").write_bytes(b"Z" * 32768)


def populate_run25_bulk_source(repo_root: Path) -> None:
    """Populate repository root with polyglot source files for bulk plan extraction."""
    repo_root.mkdir(parents=True, exist_ok=True)

    files = {
        "script.sh": "#!/bin/sh\necho shell\n",
        "tool.bash": "#!/bin/bash\necho bash\n",
        "case.bats": "@test 'bats' { true; }\n",
        "filter.awk": "{ print $0 }\n",
        "env.zsh": "print zsh\n",
        "test.zunit": "@test 'z' { assert true }\n",
        "script.rb": "puts 'ruby'\n",
        "package.nix": "{ pkgs ? import <nixpkgs> {} }: {}\n",
        "deploy.ps1": "Write-Host 'ps1'\n",
        "layout.css": "div { margin: 0; }\n",
        "document.txt": "Plain document text.\n",
        "table.csv": "col1,col2\nval1,val2\n",
        "data.tsv": "col1\tcol2\nval1\tval2\n",
        "article.latex": "\\documentclass{article}\n\\begin{document}\nhello\n\\end{document}\n",
        "rss_feed.json": '{"feed": {"title": "Test JSON Feed"}}\n',
        "atom_feed.xml": '<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title></feed>\n',
    }
    for filename, text in files.items():
        (repo_root / filename).write_text(text, encoding="utf-8")
    (repo_root / "binary.unknown").write_bytes(b"unrecognized_binary_data")


def snapshot_directory_state(target_dir: Path) -> dict[str, str]:
    """Capture relative paths and SHA256 hashes of all files in target_dir."""
    snapshot: dict[str, str] = {}
    if not target_dir.exists():
        return snapshot
    for child in sorted(target_dir.rglob("*")):
        if child.is_file():
            rel = child.relative_to(target_dir).as_posix()
            snapshot[rel] = hashlib.sha256(child.read_bytes()).hexdigest()
    return snapshot


def assert_owned_artifacts_preserved(
    target_dir: Path,
    expected_snapshot: dict[str, str],
) -> None:
    """Assert all previously owned files remain present with unmodified contents."""
    current_snapshot = snapshot_directory_state(target_dir)
    for path, expected_sha in expected_snapshot.items():
        if path not in current_snapshot:
            raise AssertionError(f"owned artifact was deleted: {path}")
        if current_snapshot[path] != expected_sha:
            raise AssertionError(
                f"owned artifact was mutated: {path} (expected {expected_sha}, got {current_snapshot[path]})"
            )
