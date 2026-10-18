"""Tiny real static extractions, canonicalization, SQLite publication and calls.

File observations, snapshot manifests and publication labels are synthetic via
navigation_bundle. Python/Markdown relationship observations are real extractor
outputs. Fixture Python text must never execute. Mutation tests disclose changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from repomap_kg.graph.keys import doc_page_key
from repomap_kg.graph.multi_source import graph_source_binding_id
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from repomap_kg.server import mcp
from repomap_kg.storage.sqlite_local.connection import initialize_graph_database
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_test_support.navigation_search_fixtures import navigation_bundle
from repomap_test_support.sqlite_local_fixtures import graph_toml, local_binding, publication_for, write_sqlite_home

GRAPH = "related"
REPOSITORY = "repo1:related"
BINDING = graph_source_binding_id(GRAPH, "root")
MODULE = "python.module:pkg.alpha"
IMPORTED = "python.module:pkg.beta"
START = doc_page_key("root/docs/start.md")
GUIDE = doc_page_key("root/docs/guide.md")
OTHER = doc_page_key("root/docs/other.md")
SOURCES = {
    "pkg/alpha.py": "import pkg.beta\nraise RuntimeError('fixture source must never execute')\n",
    "pkg/beta.py": "def supported():\n    return 'fixture'\n",
    "docs/start.md": "[Guide](guide.md)\n[Other](other.md)\n",
    "docs/guide.md": "Guide fixture.\n",
    "docs/other.md": "Other fixture.\n",
}
# Authored oracle from the import and link above, independent of the adapter.
EXPECTED_IMPORTS = {(MODULE, "imports", IMPORTED)}
EXPECTED_LINKS = {(START, "links_to", GUIDE), (START, "links_to", OTHER)}


def related_home(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Only disposable SQLite stores; a separately mapped source for verification."""
    root = tmp_path / "never-acquired-source"
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, root)
                             + graph_toml("hidden", root, visible=False)
                             + graph_toml("disabled", root, enabled=False))
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    config.graph_store_root.mkdir(parents=True, mode=0o700)
    database = config.graph_store_root / f"{GRAPH}.sqlite3"
    initialize_graph_database(database, local_binding(GRAPH), applied_at="2026-10-15T00:00:00Z")
    bundle = navigation_bundle(GRAPH,
        markdown_sources={p: s for p, s in SOURCES.items() if p.endswith(".md")},
        python_sources={p: s for p, s in SOURCES.items() if p.endswith(".py")})
    publish_generation(database, publication_for(bundle, GRAPH), bundle.families, expected_generation=0)
    workspace = tmp_path / "caller-source"
    for name, content in SOURCES.items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return home, database, workspace


class CapturedCalls:
    """Public callable envelope recorder; never performs a fallback call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        event: dict[str, Any] = {"tool": name, "arguments": dict(arguments)}
        self.calls.append(event)
        reply = mcp.handle_tool_call(name, arguments)
        event["response"] = reply
        return reply
