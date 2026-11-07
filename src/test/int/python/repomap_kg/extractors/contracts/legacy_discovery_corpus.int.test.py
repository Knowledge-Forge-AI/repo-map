"""Connected static discovery registry, lifecycle and deterministic graph contract."""

from __future__ import annotations
from pathlib import Path
from common_lore_index.canonicalization import canonicalize_observations
from common_lore_index.extractors.contracts.legacy_registry import (
    LEGACY_ENTRYPOINTS,
    is_legacy_extractor_name,
    legacy_lifecycle_facts,
)
from common_lore_index.graph.discovery import discover_observations


CORPUS = {
    "src/app.py": """import json
from pathlib import Path
def greet(name):
    Path("markers/python-write").write_text("unexpected")
    return json.dumps({"name": name})
""",
    "src/routes.py": """from flask import Flask
app = Flask(__name__)
@app.get('/health')
def health():
    return 'ok'
""",
    "tests/test_app.py": """def test_greet():
    assert True
""",
    "src/bad.py": "def broken(:\n    return 1\n",
    "web/index.mjs": """import { render } from './view.tsx';
export function start() { return render(); }
""",
    "web/router.cjs": """const express = require('express');
const app = express();
app.get('/health', function health(req, res) { res.send('ok'); });
module.exports = app;
""",
    "web/view.tsx": "export const render = () => null;\n",
    "web/routes.ts": "export const route = '/health';\n",
    "web/bad.js": "const dynamic = import(`./${name}.js`);\n",
    "Gemfile": "source 'https://rubygems.org'\ngem 'rack'\n",
    "Rakefile": "task :check do\n  puts 'ok'\nend\n",
    "app/controllers/health.rb": """class HealthController < ApplicationController
  def show
    render plain: 'ok'
  end
end
""",
    "config/routes.rb": """Rails.application.routes.draw do
  get '/health', to: 'health#show'
end
""",
    "test/health_test.rb": """class HealthTest < Minitest::Test
  def test_health
    assert true
  end
end
""",
    "bad.rb": "require 'sinatra'\nget \"/items/#{id}\" do\nend\n",
    "scripts/entry.sh": """#!/bin/sh
. ./scripts/common.sh
export APP_MODE=check
touch markers/shell-write
printf '%s\\n' "$APP_MODE"
""",
    "scripts/common.sh": """#!/bin/sh
helper() { printf '%s\\n' helper; }
""",
    "scripts/entry.bash": """#!/usr/bin/env bash
set -euo pipefail
trap 'printf done' EXIT
source scripts/common.sh
export DEPLOY_MODE=static
helper
""",
    ".zshrc": """source scripts/common.zsh
export ZSH_MODE=interactive
""",
    "scripts/common.zsh": """#!/usr/bin/env zsh
helper() { print helper; }
source ./scripts/entry.sh
""",
    "completions/_app": """#compdef app
_app() { _arguments '1: :->command'; }
""",
    "scripts/process.awk": """BEGIN { count = 0 }
{ count += 1 }
END { print count }
""",
    "tests/cli.bats": """#!/usr/bin/env bats
@test 'smoke' { run true; [ "$status" -eq 0 ]; }
""",
    "tests/cli.zunit": """describe 'cli'
test 'smoke' {
  run true
  assert $state equals 0
}
""",
    "modules/App.psd1": """@{
  RootModule = 'App.psm1'
  ModuleVersion = '1.0.0'
  FunctionsToExport = @('Get-AppStatus')
  NestedModules = @('Sub.psm1')
  Description = 'static manifest marker: markers/psd1-write'
}
""",
    "modules/App.psm1": "function Get-AppStatus { 'ok' }\n",
    "flake.nix": """{
  description = "static fixture";
  outputs = { self }: {
    packages.x86_64-linux.default = "package";
  };
}
""",
    "infra/main.tf": """terraform { required_version = ">= 1.0" }
resource "null_resource" "example" {
  provisioner "local-exec" { command = "touch markers/tf-write" }
}
""",
    "api/openapi.yaml": """openapi: "3.0.0"
info:
  title: Static API
  version: "1"
paths:
  /health:
    get:
      responses:
        "200":
          description: ok
""",
    "infra/bad.tf": "resource \"null_resource\" \"broken\" {\n",
    "api/bad/openapi.yaml": "openapi: [malformed array instead of string\n",
    "docs/README.md": """# Fixture

See [the API](../api/openapi.yaml).

```python
print('static fixture')
```
""",
    "docs/bad-frontmatter.md": "---\ntitle: Fixture\n# missing closing delimiter\n",
    "web/index.html": """<!doctype html>
<html><head><link rel="stylesheet" href="site.css"></head>
<body class="health"><h1 id="welcome">Health</h1></body></html>
""",
    "web/bad.html": "<html><body><section><p>unterminated",
    "web/site.css": ".health { color: green; }\n",
    "web/bad.css": ".health { color: red;\n",
    "docs/config.xml": "<root><item name=\"one\" /></root>\n",
    "docs/bad.xml": "<root><item></root>\n",
    "feeds/news.xml": """<rss version="2.0"><channel>
<title>News</title><item><guid>one</guid><title>One</title>
<link>https://example.invalid/one</link></item>
</channel></rss>
""",
    "feeds/bad.xml": "<rss><channel>\n",
    "mail/notice.eml": """Message-ID: <notice@example.invalid>
Date: Fri, 02 Jan 2026 03:04:05 +0000
From: Fixture Writer <writer@example.invalid>
To: Reader <reader@example.invalid>
Subject: Static notice
Content-Type: text/plain; charset=utf-8

Static body.
""",
    "mail/bad.eml": "From: bad@example.invalid\nSubject: no message identity\n\nbody\n",
}
VALID_FAMILIES = {
    "src/app.py": ("python.",),
    "src/routes.py": ("python.",),
    "tests/test_app.py": ("python.",),
    "web/index.mjs": ("js.",),
    "web/router.cjs": ("js.",),
    "web/view.tsx": ("js.",),
    "web/routes.ts": ("js.",),
    "Gemfile": ("ruby.",),
    "Rakefile": ("ruby.",),
    "app/controllers/health.rb": ("ruby.",),
    "config/routes.rb": ("ruby.",),
    "test/health_test.rb": ("ruby.",),
    "scripts/entry.sh": ("shell.",),
    "scripts/common.sh": ("shell.",),
    "scripts/entry.bash": ("bash.", "shell."),
    ".zshrc": ("zsh.",),
    "scripts/common.zsh": ("zsh.",),
    "completions/_app": ("zsh.",),
    "scripts/process.awk": ("awk.",),
    "tests/cli.bats": ("bats.",),
    "tests/cli.zunit": ("zunit.",),
    "modules/App.psd1": ("powershell.",),
    "modules/App.psm1": ("powershell.",),
    "flake.nix": ("nix.",),
    "infra/main.tf": ("terraform.",),
    "api/openapi.yaml": ("openapi.", "config."),
    "docs/README.md": ("markdown.",),
    "web/index.html": ("html.",),
    "web/site.css": ("css.",),
    "docs/config.xml": ("xml.", "config."),
    "feeds/news.xml": ("feed.",),
    "mail/notice.eml": ("email.",),
}
LIMITED_OR_MALFORMED_EXPECTATIONS = {
    "src/bad.py": (("python.parse_error", "error_kind", ("malformed-python",)),),
    "web/bad.js": (("js.parse_error", "error_kind", ("dynamic-interpolation", "dynamic-dynamic-import")),),
    "bad.rb": (("ruby.parse_error", "error_kind", ("dynamic-interpolation",)),),
    "infra/bad.tf": (("terraform.parse_error", "error_kind", ("terraform-unclosed-block",)),),
    "api/bad/openapi.yaml": (("config.parse_error", "error_kind", ("malformed-yaml",)), ("openapi.parse_error", "error_kind", ("malformed-openapi-yaml",))),
    "docs/bad-frontmatter.md": (("markdown.frontmatter", "parse_status", ("malformed",)), ("markdown.frontmatter", "malformed_reason", ("missing-closing-delimiter",))),
    "web/bad.html": (("html.parse_error", "error_kind", ("recoverable-unclosed-elements",)),),
    "web/bad.css": (("css.parse_error", "error_kind", ("malformed-rule-block",)),),
    "docs/bad.xml": (("xml.parse_error", "error_kind", ("malformed-xml",)),),
    "feeds/bad.xml": (("feed.parse_error", "error_kind", ("xml-parse-error",)),),
    "mail/bad.eml": (("email.parse_error", "error_kind", ("missing-or-invalid-message-id",)),),
}
MARKERS = tuple(f"markers/{name}" for name in
                ("psd1-write", "tf-write", "python-write", "shell-write"))

def _materialize(root: Path) -> Path:
    for relative, content in CORPUS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root

def _rows(observations, path: str):
    return [item for item in observations if item.path == path]


def _registered_names_by_selector() -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for entry in LEGACY_ENTRYPOINTS.values():
        for selector in entry.selectors:
            names.setdefault(selector, set()).update(entry.extractor_names)
    return names

def _assert_registered_owners(observations) -> None:
    file_languages = {
        item.path: item.metadata["language"]
        for item in observations
        if item.kind == "file"
    }
    assert set(file_languages) == set(CORPUS)
    allowed = _registered_names_by_selector()
    wildcard = allowed.get("*", set())
    observation_emitters = allowed.get("observations", set())
    for item in observations:
        assert item.path in file_languages
        assert is_legacy_extractor_name(item.extractor), (item.path, item.extractor)
        if item.extractor in observation_emitters:
            assert item.kind == "css.selector_match"
            continue
        candidates = allowed.get(file_languages[item.path], set()) | wildcard
        assert item.extractor in candidates, (
            item.path,
            file_languages[item.path],
            item.kind,
            item.extractor,
        )

def test_legacy_registry_owns_cross_language_static_corpus(tmp_path: Path) -> None:
    root = _materialize(tmp_path / "legacy-corpus")
    observations = discover_observations(root)
    repeat = discover_observations(root)

    assert observations == repeat
    _assert_registered_owners(observations)
    kinds = {item.kind for item in observations}
    assert {
        "python.import", "python.flask_route", "python.test_file",
        "js.import", "js.export", "js.route",
        "ruby.gem_dependency", "ruby.dsl", "ruby.route", "ruby.test_case",
        "shell.source", "shell.export", "bash.trap",
        "zsh.startup_file", "zsh.completion_function",
        "awk.program", "bats.test_case", "zunit.test_case",
        "powershell.manifest", "nix.output_section", "terraform.resource",
        "openapi.operation", "markdown.document", "html.document",
        "css.selector", "xml.element", "feed.item", "email.message",
    } <= kinds
    assert not any((root / marker).exists() for marker in MARKERS)
    for path, prefixes in VALID_FAMILIES.items():
        rows = _rows(observations, path)
        assert any(item.kind != "file" and item.kind.startswith(prefix)
                   for item in rows for prefix in prefixes), (path, {i.kind for i in rows})
    for path, expectations in LIMITED_OR_MALFORMED_EXPECTATIONS.items():
        rows = _rows(observations, path)
        assert "file" in {item.kind for item in rows}
        for kind, metadata_key, expected_values in expectations:
            actual_values = {
                item.metadata.get(metadata_key)
                for item in rows
                if item.kind == kind
            }
            assert set(expected_values) <= actual_values, (
                path,
                kind,
                metadata_key,
                actual_values,
            )
    assert not any((root / marker).exists() for marker in MARKERS)

def test_legacy_registry_is_lifecycle_neutral_and_rust_opt_in_is_not_legacy() -> None:
    registered = {
        name
        for entry in LEGACY_ENTRYPOINTS.values()
        for name in entry.extractor_names
    }
    assert registered
    assert "rust-pilot-tree-sitter" not in registered
    assert not is_legacy_extractor_name("rust-pilot-tree-sitter")
    for name in registered:
        facts = legacy_lifecycle_facts(name)
        assert facts["capability_set"] == "undeclared"
        assert facts["installed"] == "undeclared"
        assert facts["admitted"] == "undeclared"
        assert facts["attempted"] == "unavailable"
        assert facts["exercised"] == "unavailable"
        assert facts["achieved"] == "unavailable"
        assert facts["effect_basis"] == "legacy-construction-declaration"
        assert facts["effect_enforcement"] == "unavailable"
        assert facts["effect_observation"] == "unavailable"

def test_legacy_discovery_canonical_graph_is_repeatable_and_nonempty(tmp_path: Path) -> None:
    root = _materialize(tmp_path / "legacy-corpus")
    first_observations = discover_observations(root)
    first = canonicalize_observations(first_observations)
    replay = canonicalize_observations(discover_observations(root))

    assert first.ok
    assert first.to_json() == replay.to_json()
    assert first.graph.raw_observation_count == len(first_observations)
    assert first.graph.nodes and first.graph.edges and first.graph.evidence
    assert first.graph.node_evidence_links and first.graph.edge_evidence_links
    node_kinds = {node.kind for node in first.graph.nodes}
    assert {
        "python.module", "js.file", "ruby.file", "bash.script", "zsh.script",
        "awk.program", "bats.file", "zunit.file", "feed.document", "email.message",
    } <= node_kinds
    file_keys = {node.canonical_key for node in first.graph.nodes if node.kind == "file"}
    assert {f"file:{path}" for path in CORPUS} <= file_keys
    assert not any((root / marker).exists() for marker in MARKERS)
