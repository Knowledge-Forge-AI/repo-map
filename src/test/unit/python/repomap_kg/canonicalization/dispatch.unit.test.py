from __future__ import annotations

from collections.abc import Mapping

import pytest

from repomap_kg import canonicalization
from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.observations.raw import RawObservation


def test_dispatch_callable_is_the_public_facade_export() -> None:
    assert getattr(canonicalization, "canonicalize_observations") is canonicalize_observations


def _observation(
    kind: str,
    source_id: str,
    path: str,
    *,
    confidence: str = "extracted",
    extractor: str = "dispatch-test",
    extractor_version: str = "0.1.0",
    start_line: int | None = None,
    end_line: int | None = None,
    name: str | None = None,
    target: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=source_id,
        path=path,
        confidence=confidence,
        extractor=extractor,
        extractor_version=extractor_version,
        start_line=start_line,
        end_line=end_line,
        name=name,
        target=target,
        metadata={} if metadata is None else metadata,
    )


@pytest.mark.parametrize(
    (
        "observation",
        "expected_node_keys",
        "expected_edges",
        "expected_raw_kinds",
    ),
    (
        pytest.param(
            _observation(
                "file",
                "README.md",
                "README.md",
                metadata={"language": "markdown", "role": "documentation"},
            ),
            ("file:README.md",),
            (),
            ("file",),
            id="file",
        ),
        pytest.param(
            _observation(
                "config.document",
                "config/settings.json#config-document",
                "config/settings.json",
                target="config.document:file%3Aconfig%2Fsettings.json",
                extractor="repo-config",
                metadata={
                    "format": "json",
                    "parser": "stdlib-json",
                    "top_level_type": "object",
                    "document_role": "settings",
                    "path_count": 1,
                },
            ),
            (
                "config.document:file%3Aconfig%2Fsettings.json",
                "file:config/settings.json",
            ),
            (
                (
                    "file:config/settings.json",
                    "defines",
                    "config.document:file%3Aconfig%2Fsettings.json",
                ),
            ),
            ("config.document",),
            id="config-document",
        ),
        pytest.param(
            _observation(
                "markdown.document",
                "README.md#markdown-document",
                "README.md",
                target="doc.page:file%3AREADME.md",
                extractor="repo-markdown",
                metadata={
                    "doc_path": "README.md",
                    "doc_role": "readme",
                    "title": "RepoMap",
                    "frontmatter_present": False,
                },
            ),
            ("doc.page:file%3AREADME.md", "file:README.md"),
            (("file:README.md", "defines", "doc.page:file%3AREADME.md"),),
            ("markdown.document",),
            id="markdown-document",
        ),
        pytest.param(
            _observation(
                "feed.document",
                "feeds/rss.xml#feed-document",
                "feeds/rss.xml",
                target="feed.document:file%3Afeeds%2Frss.xml",
                extractor="repo-feed",
                metadata={"feed_format": "rss", "version": "2.0"},
            ),
            ("feed.document:file%3Afeeds%2Frss.xml", "file:feeds/rss.xml"),
            (
                (
                    "file:feeds/rss.xml",
                    "defines",
                    "feed.document:file%3Afeeds%2Frss.xml",
                ),
            ),
            ("feed.document",),
            id="feed-document",
        ),
        pytest.param(
            _observation(
                "shell.command",
                "bin/tool#cmd:1:nix",
                "bin/tool",
                start_line=1,
                end_line=1,
                target="tool:nix",
                confidence="heuristic",
                extractor="repo-shell",
                metadata={"command": "nix", "argv": ["nix", "build"]},
            ),
            ("file:bin/tool", "tool:nix"),
            (("file:bin/tool", "executes", "tool:nix"),),
            ("shell.command",),
            id="shell-command",
        ),
        pytest.param(
            _observation(
                "python.module",
                "src/main/python/pkg/app.py#module:pkg.app",
                "src/main/python/pkg/app.py",
                start_line=1,
                end_line=4,
                name="pkg.app",
                target="python.module:pkg.app",
                extractor="repo-python",
                metadata={
                    "module": "pkg.app",
                    "package_root": "src/main/python",
                    "parser": "ast",
                },
            ),
            ("file:src/main/python/pkg/app.py", "python.module:pkg.app"),
            (
                (
                    "file:src/main/python/pkg/app.py",
                    "defines",
                    "python.module:pkg.app",
                ),
            ),
            ("python.module",),
            id="python-module",
        ),
        pytest.param(
            _observation(
                "nix.import",
                "flake.nix#nix-import:2:modules-one-nix",
                "flake.nix",
                start_line=2,
                end_line=2,
                target="file:modules/one.nix",
                confidence="heuristic",
                extractor="repo-nix",
                metadata={
                    "import_path": "./modules/one.nix",
                    "resolved_path": "modules/one.nix",
                    "resolution": "local",
                    "syntax": "imports-list",
                },
            ),
            ("file:flake.nix", "file:modules/one.nix"),
            (("file:flake.nix", "sources", "file:modules/one.nix"),),
            ("nix.import",),
            id="nix-import",
        ),
        pytest.param(
            _observation(
                "email.mailbox",
                "mail/sample.mbox#mailbox",
                "mail/sample.mbox",
                target="email.mailbox:file%3Amail%2Fsample.mbox",
                extractor="repo-email",
                metadata={"mailbox_format": "mbox", "message_count": 1},
            ),
            ("email.mailbox:file%3Amail%2Fsample.mbox", "file:mail/sample.mbox"),
            (
                (
                    "file:mail/sample.mbox",
                    "defines",
                    "email.mailbox:file%3Amail%2Fsample.mbox",
                ),
            ),
            ("email.mailbox",),
            id="email-mailbox",
        ),
    ),
)
def test_dispatch_characterizes_representative_mapped_families(
    observation: RawObservation,
    expected_node_keys: tuple[str, ...],
    expected_edges: tuple[tuple[str, str, str], ...],
    expected_raw_kinds: tuple[str, ...],
) -> None:
    payload = canonicalize_observations([observation]).to_dict()

    assert payload["diagnostics"] == []
    assert tuple(node["canonical_key"] for node in payload["nodes"]) == expected_node_keys
    assert (
        tuple(
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        )
        == expected_edges
    )
    assert tuple(evidence["raw_kind"] for evidence in payload["evidence"]) == (
        expected_raw_kinds
    )
    assert payload["summary"]["raw_observations"] == 1


def test_dispatch_preserves_raw_only_and_unsupported_observation_order() -> None:
    observations = [
        _observation(
            "config.parse_error",
            "events.jsonl#config-parse-error:2",
            "events.jsonl",
            start_line=2,
            end_line=2,
            confidence="unknown",
            extractor="repo-config",
            metadata={
                "format": "jsonl",
                "parser": "stdlib-json",
                "error_kind": "malformed-jsonl-line",
                "message_summary": "Expecting value",
                "line_number": 2,
                "recovered": True,
            },
        ),
        _observation(
            "future.kind",
            "future#1",
            "future.txt",
            confidence="heuristic",
            extractor="fixture",
        ),
        _observation(
            "file",
            "README.md",
            "README.md",
            metadata={"language": "markdown"},
        ),
    ]

    payload = canonicalize_observations(observations).to_dict()

    assert [evidence["raw_kind"] for evidence in payload["evidence"]] == [
        "config.parse_error",
        "file",
    ]
    assert [evidence["evidence_key"].split(":", 2)[1] for evidence in payload["evidence"]] == [
        "0",
        "2",
    ]
    assert payload["diagnostics"] == [
        {
            "severity": "warning",
            "category": "unsupported_raw_observation_kind",
            "message": "raw observation kind is not supported: future.kind",
            "raw_observation_ordinal": 1,
            "raw_source_id": "future#1",
            "path": "future.txt",
            "field": "kind",
            "value": "future.kind",
            "placeholder_key": None,
        }
    ]
    assert payload["summary"]["raw_observations"] == 3
    assert payload["summary"]["warnings"] == 1


def test_dispatch_preserves_zsh_precedence_for_ambiguous_shell_command() -> None:
    observation = _observation(
        "shell.command",
        "zshrc#cmd:1:zpool",
        ".zshrc",
        start_line=1,
        end_line=1,
        target="tool:zpool",
        confidence="heuristic",
        extractor="repo-shell",
        metadata={
            "argv": ["zpool", "status"],
            "command": "zpool",
            "dialect": "zsh",
            "raw": "zpool status",
        },
    )

    payload = canonicalize_observations([observation]).to_dict()

    assert payload["diagnostics"] == []
    assert [node["canonical_key"] for node in payload["nodes"]] == [
        "tool:zpool",
        "zsh.script:file%3A.zshrc",
    ]
    assert [
        (edge["source_key"], edge["kind"], edge["target_key"])
        for edge in payload["edges"]
    ] == [("zsh.script:file%3A.zshrc", "command_intent", "tool:zpool")]
    assert payload["evidence"][0]["metadata"] == {
        "argv": ["zpool", "status"],
        "command": "zpool",
        "dialect": "zsh",
    }
    assert payload["summary"]["edge_evidence_links"] == 1
