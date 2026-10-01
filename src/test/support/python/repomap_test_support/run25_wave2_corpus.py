"""Deterministic multi-source corpus builders for Run25 Wave 2 scenarios.

Provides fixtures and graph configuration helpers across:
- Languages: Python web/routes, JavaScript Express/modules, Go protocol/context.
- Documents: HTML5 elements/anchors, CSS selectors/media, Markdown slugs/links,
  multi-doc YAML, Maven/Spring XML, Apple Plist.
- Config: Nix flakes/derivations, Terraform HCL/JSON, OpenAPI specifications.
- Shell: Bash functions/traps/mutations, Zsh arrays/styles, Awk BEGIN/END,
  PowerShell manifests/scripts, Bats, Zunit.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from repomap_kg.artifacts.manifest import PortableSnapshotManifest
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.source_sealer import seal_configured_sources
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig

# --- Compact Multi-Language & Document Fixtures ---

PY_SERVER_SRC = (
    "from flask import Flask, request, jsonify\n"
    "app = Flask(__name__)\n\n"
    '@app.route("/api/v1/health", methods=["GET"])\n'
    "def health_check():\n"
    '    return jsonify(status="healthy", code=200)\n\n'
    '@app.route("/api/v1/items/<int:item_id>", methods=["GET", "POST"])\n'
    "def manage_item(item_id):\n"
    '    if request.method == "POST":\n'
    '        return jsonify(action="created", id=item_id)\n'
    '    return jsonify(action="retrieved", id=item_id)\n'
)

JS_ROUTER_SRC = (
    "const express = require('express');\n"
    "const router = express.Router();\n\n"
    "router.get('/services', (req, res) => {\n"
    "    res.json({ services: ['auth', 'storage'] });\n"
    "});\n"
    "router.post('/services/:id/restart', (req, res) => {\n"
    "    res.json({ restarted: req.params.id });\n"
    "});\n"
    "module.exports = router;\n"
)

GO_SERVICE_SRC = (
    "package service\n\n"
    'import ("context"; "errors")\n\n'
    'type WorkerTask struct {\n    ID string `json:"id"`\n    Action string `json:"action"`\n}\n\n'
    "type TaskHandler interface {\n    Process(ctx context.Context, task *WorkerTask) error\n}\n\n"
    "func ExecuteTask(ctx context.Context, h TaskHandler, t *WorkerTask) error {\n"
    '    if t == nil { return errors.New("task is nil") }\n'
    "    return h.Process(ctx, t)\n"
    "}\n"
)

HTML_PAGE_SRC = (
    "<!doctype html>\n"
    '<html lang="en">\n<head>\n'
    '  <meta charset="utf-8">\n  <title>Wave2 Dashboard</title>\n'
    '  <link rel="stylesheet" href="../static/style.css">\n'
    '  <script src="../src/router.js"></script>\n'
    "  <style>.embedded-note { color: #333; }</style>\n"
    "</head>\n<body>\n"
    '  <header id="top-bar">\n'
    '    <h1 id="main-title">Wave2 Service Platform</h1>\n'
    '    <nav class="nav-menu primary-nav">\n'
    '      <a href="#main-title">Top</a>\n'
    '      <a href="../docs/overview.md">Docs</a>\n'
    '      <a href="https://example.com/api/v1">External</a>\n'
    '      <a href="mailto:support@example.com">Contact</a>\n'
    "    </nav>\n  </header>\n  <main>\n"
    '    <section id="content">\n'
    "      <p>Unclosed paragraph element for parser recovery check\n"
    '      <div class="card item-card">Content card</div>\n'
    "    </section>\n  </main>\n</body>\n</html>\n"
)

CSS_STYLE_SRC = (
    '@import url("theme.css");\n\n'
    ":root { --primary-bg: #f8f9fa; }\n"
    "#top-bar { background: var(--primary-bg); }\n"
    ".nav-menu.primary-nav { display: flex; margin: 0; }\n"
    ".card.item-card { padding: 12px; }\n"
    "@media (min-width: 768px) { body { font-size: 16px; } }\n"
)

MARKDOWN_DOC_SRC = (
    "# Wave2 System Overview\n\n"
    "Welcome to the Wave2 multi-source integration platform.\n\n"
    "## Architecture\n\n"
    "The system connects [HTML Dashboard](../templates/index.html#top-bar) with\n"
    "the [Python Backend](../app/server.py).\n\n"
    "See also <https://example.com/spec> for remote specifications.\n\n"
    "```python\ndef example_client():\n    import requests\n"
    '    return requests.get("/api/v1/health")\n```\n'
)

YAML_CONFIG_SRC = (
    "---\nservice: wave2-gateway\nversion: \"2.1.0\"\nreplicas: 3\n"
    "routes:\n  - path: /api/v1\n    target: backend\n    enabled: true\n...\n"
    "---\nservice: wave2-worker\nconcurrency: 4\nlogging:\n  level: INFO\n  format: json\n"
)

POM_XML_SRC = (
    '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
    "  <groupId>com.repomap.wave2</groupId>\n  <artifactId>wave2-parent</artifactId>\n  <version>1.0.0</version>\n"
    "  <dependencies>\n    <dependency>\n"
    "      <groupId>org.junit.jupiter</groupId>\n      <artifactId>junit-jupiter-api</artifactId>\n"
    "      <version>5.10.0</version>\n    </dependency>\n  </dependencies>\n</project>\n"
)

SPRING_BEANS_SRC = (
    '<beans xmlns="http://www.springframework.org/schema/beans">\n'
    '  <bean id="authProvider" class="com.repomap.security.AuthProvider">\n'
    '    <property name="secretKey" ref="keyStore"/>\n  </bean>\n'
    '  <bean id="keyStore" class="com.repomap.security.KeyStore"/>\n</beans>\n'
)

PLIST_XML_SRC = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<plist version="1.0">\n<dict>\n'
    "  <key>CFBundleIdentifier</key>\n  <string>com.repomap.wave2</string>\n"
    "  <key>CFBundleShortVersionString</key>\n  <string>1.0.0</string>\n"
    "  <key>SupportedModes</key>\n  <array>\n    <string>standalone</string>\n    <string>distributed</string>\n  </array>\n"
    "</dict>\n</plist>\n"
)

# --- Compact Config & Shell Fixtures ---

NIX_FLAKE_SRC = (
    '{\n  description = "Wave2 reproducible environment flake";\n'
    '  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";\n'
    "  outputs = { self, nixpkgs }: {\n"
    "    packages.x86_64-linux.default = {};\n"
    "    apps.x86_64-linux.gateway = {};\n"
    "    overlays.default = final: prev: {};\n"
    "  };\n}\n"
)

NIX_DEFAULT_SRC = (
    "{ pkgs ? import <nixpkgs> {} }:\n"
    "pkgs.stdenv.mkDerivation {\n"
    '  pname = "wave2-tool";\n  version = "0.2.0";\n  src = ./.;\n'
    "  buildInputs = [ pkgs.bash pkgs.python3 ];\n}\n"
)

TERRAFORM_MAIN_SRC = (
    'terraform {\n  required_version = ">= 1.5.0"\n'
    '  required_providers {\n    aws = {\n      source  = "hashicorp/aws"\n      version = "~> 5.0"\n    }\n  }\n'
    '  backend "s3" {\n    bucket = "repomap-tf-state"\n    key = "wave2/terraform.tfstate"\n    region = "us-east-1"\n  }\n}\n'
    'provider "aws" {\n  region = var.aws_region\n}\n'
    'resource "aws_s3_bucket" "wave2_bucket" {\n  bucket = "wave2-primary-store"\n}\n'
    'module "vpc" {\n  source = "./modules/vpc"\n  cidr = "10.0.0.0/16"\n}\n'
)

TERRAFORM_JSON_SRC = (
    '{"terraform": {"required_version": ">= 1.0.0"}, '
    '"resource": {"null_resource": {"cluster_init": [{"triggers": {"cluster_epoch": "1"}}]}}}\n'
)

OPENAPI_SPEC_SRC = (
    'openapi: "3.0.3"\ninfo:\n  title: "Wave2 Service API"\n  version: "1.0.0"\n'
    "paths:\n  /api/v1/deployments:\n    get:\n      operationId: listDeployments\n      summary: List deployments\n"
    '      responses:\n        "200":\n          description: OK\n          content:\n'
    '            application/json:\n              schema:\n                $ref: "#/components/schemas/DeploymentList"\n'
    "    post:\n      operationId: createDeployment\n      summary: Create deployment\n"
    '      responses:\n        "201":\n          description: Created\n'
    "components:\n  schemas:\n    DeploymentList:\n      type: array\n"
    '      items:\n        $ref: "#/components/schemas/Deployment"\n'
    "    Deployment:\n      type: object\n      properties:\n        id:\n          type: string\n        status:\n          type: string\n"
)

BASH_ORCHESTRATE_SRC = (
    "#!/usr/bin/env bash\nset -euo pipefail\n"
    'export DEPLOY_STAGE="production"\nexport REGION="us-east-1"\n'
    "source ./scripts/lib/utils.sh\ntrap cleanup EXIT SIGINT\n"
    'cleanup() { echo "Releasing deployment locks"; }\n'
    "deploy_pipeline() {\n"
    '    local target="$1"\n    echo "Deploying $target"\n'
    "    npm login --scope=@repomap\n    git credential approve < /dev/null\n"
    '    aws configure set region "$REGION"\n    gpg --import ./keys/release.gpg\n'
    "    cat input.txt > /tmp/out.log 2>&1\n    scp -r ./dist user@remote:/var/www\n"
    "}\ndeploy_pipeline \"primary-cluster\"\n"
)

BASH_UTILS_SRC = (
    "#!/usr/bin/env bash\nalias dcom='docker compose'\n"
    'log_msg() { local level="$1"; local message="$2"; echo "[$level] $message"; }\n'
)

ZSH_ENV_SRC = (
    "#!/bin/zsh\ntypeset -gA CLOUD_CLUSTERS\n"
    'CLOUD_CLUSTERS[primary]="us-east-1"\nCLOUD_CLUSTERS[dr]="us-west-2"\n'
    "zstyle ':completion:*' verbose yes\n"
    "zstyle ':completion:*:descriptions' format '%B%d%b'\n"
    'EXTRA_PATHS+=("/opt/tools/bin" "/usr/local/bin")\n'
    '# Search all submodules\nfor script in scripts/**/*.zsh; do autoload -Uz "$script"; done\n'
)

AWK_METRICS_SRC = (
    "#!/usr/bin/awk -f\n"
    'BEGIN { FS = ","; OFS = "\\t"; record_count = 0; error_count = 0 }\n'
    'NR > 1 { record_count++; if ($3 == "ERROR") { error_count++; print $1, $2, "flagged" } }\n'
    'END { print "Processed:", record_count, "Errors:", error_count }\n'
)

BATS_SUITE_SRC = (
    "#!/usr/bin/env bats\n\n"
    '@test "deployment stage is set" {\n'
    '  run bash -c \'echo "$DEPLOY_STAGE"\'\n'
    '  [ "$status" -eq 0 ]\n  [ "$output" = "production" ]\n}\n'
)

ZUNIT_RUNNER_SRC = "@test 'zsh clusters configured' {\n  assert 1 equals 1\n}\n"

POWERSHELL_MANIFEST_SRC = (
    "@{\n  RootModule = 'Wave2Module.psm1'\n  ModuleVersion = '1.2.0'\n"
    "  GUID = 'd1f5b5b0-58aa-46bc-926c-0e704bb491a1'\n"
    "  Author = 'RepoMap Test Team'\n  CompanyName = 'RepoMap'\n"
    "  FunctionsToExport = @('Start-WaveDeploy', 'Get-WaveStatus')\n  CmdletsToExport = @()\n}\n"
)

POWERSHELL_SCRIPT_SRC = (
    'param([string]$TargetTier = "production", [int]$RetryLimit = 3)\n'
    '$env:EXECUTION_TIER = $TargetTier\n'
    'Write-Output "Initiating deployment to $TargetTier with retry $RetryLimit"\n'
)

# --- Multi-Source Project Builders ---

def populate_run25_language_document_project(root: Path) -> dict[str, Path]:
    """Populate a multi-binding project covering languages and documents."""
    primary, secondary = root / "primary", root / "secondary"
    for d in (primary / "app", primary / "src", primary / "pkg/service",
              primary / "templates", primary / "static", primary / "docs", secondary):
        d.mkdir(parents=True, exist_ok=True)

    (primary / "app/server.py").write_text(PY_SERVER_SRC, encoding="utf-8")
    (primary / "src/router.js").write_text(JS_ROUTER_SRC, encoding="utf-8")
    (primary / "pkg/service/protocol.go").write_text(GO_SERVICE_SRC, encoding="utf-8")
    (primary / "templates/index.html").write_text(HTML_PAGE_SRC, encoding="utf-8")
    (primary / "static/style.css").write_text(CSS_STYLE_SRC, encoding="utf-8")
    (primary / "docs/overview.md").write_text(MARKDOWN_DOC_SRC, encoding="utf-8")
    (primary / "config.yaml").write_text(YAML_CONFIG_SRC, encoding="utf-8")
    (primary / "pom.xml").write_text(POM_XML_SRC, encoding="utf-8")
    (primary / "beans.xml").write_text(SPRING_BEANS_SRC, encoding="utf-8")
    (primary / "Info.plist").write_text(PLIST_XML_SRC, encoding="utf-8")

    (secondary / "theme.css").write_text(CSS_STYLE_SRC, encoding="utf-8")
    (secondary / "guide.md").write_text("# Secondary Guide\nRefer to primary index.\n", encoding="utf-8")
    (secondary / "settings.yaml").write_text("environment: test\n", encoding="utf-8")
    return {"primary": primary, "secondary": secondary}


def populate_run25_config_shell_project(root: Path) -> dict[str, Path]:
    """Populate a multi-binding project covering config and shell families."""
    infra, scripts = root / "infra", root / "scripts"
    for d in (infra, scripts / "scripts/lib", scripts / "keys"):
        d.mkdir(parents=True, exist_ok=True)

    (infra / "flake.nix").write_text(NIX_FLAKE_SRC, encoding="utf-8")
    (infra / "default.nix").write_text(NIX_DEFAULT_SRC, encoding="utf-8")
    (infra / "main.tf").write_text(TERRAFORM_MAIN_SRC, encoding="utf-8")
    (infra / "variables.tf").write_text('variable "aws_region" { default = "us-east-1" }\n', encoding="utf-8")
    (infra / "terraform.tf.json").write_text(TERRAFORM_JSON_SRC, encoding="utf-8")
    (infra / "openapi.yaml").write_text(OPENAPI_SPEC_SRC, encoding="utf-8")

    (scripts / "orchestrate.sh").write_text(BASH_ORCHESTRATE_SRC, encoding="utf-8")
    (scripts / "scripts/lib/utils.sh").write_text(BASH_UTILS_SRC, encoding="utf-8")
    (scripts / "keys/release.gpg").write_text("DUMMY_KEY_DATA\n", encoding="utf-8")
    (scripts / "input.txt").write_text("line1\nline2\n", encoding="utf-8")
    (scripts / "environment.zsh").write_text(ZSH_ENV_SRC, encoding="utf-8")
    (scripts / "metrics.awk").write_text(AWK_METRICS_SRC, encoding="utf-8")
    (scripts / "suite.bats").write_text(BATS_SUITE_SRC, encoding="utf-8")
    (scripts / "runner.zunit").write_text(ZUNIT_RUNNER_SRC, encoding="utf-8")
    (scripts / "Wave2Module.psd1").write_text(POWERSHELL_MANIFEST_SRC, encoding="utf-8")
    (scripts / "Wave2Module.psm1").write_text("function Start-WaveDeploy {}\n", encoding="utf-8")
    (scripts / "deploy.ps1").write_text(POWERSHELL_SCRIPT_SRC, encoding="utf-8")
    return {"infra": infra, "scripts": scripts}


def create_run25_wave2_graph_config(
    primary_dir: Path,
    secondary_dir: Path | None = None,
    *,
    graph_id: str = "wave2-graph",
    repository_name: str = "wave2-repo",
    privacy: str = "public-dev",
    exclude_secondary: tuple[str, ...] = (),
) -> OpsGraphConfig:
    """Build OpsGraphConfig supporting 1 or 2 source bindings."""
    bindings = [
        OpsGraphSourceBindingConfig(
            schema_version=1,
            binding_id=graph_source_binding_id(graph_id, "primary"),
            source_definition_id=f"src1:{graph_id}-primary",
            alias="primary", revision=1, source_kind=SourceKind.FOLDER,
            root_path=str(primary_dir), root_path_expanded=str(primary_dir),
            repository_name=f"{repository_name}-primary", logical_root=".",
            privacy=privacy, evidence_retention="metadata-only",
            extractor_profile="default", include_paths=(), exclude_paths=(),
            selection_policy_id=source_selection_policy_id((), ()),
            resolution_policy="allow-declared", enabled=True, role="entry", input_name=None,
        )
    ]
    if secondary_dir is not None:
        bindings.append(
            OpsGraphSourceBindingConfig(
                schema_version=1,
                binding_id=graph_source_binding_id(graph_id, "secondary"),
                source_definition_id=f"src1:{graph_id}-secondary",
                alias="secondary", revision=1, source_kind=SourceKind.FOLDER,
                root_path=str(secondary_dir), root_path_expanded=str(secondary_dir),
                repository_name=f"{repository_name}-secondary", logical_root=".",
                privacy=privacy, evidence_retention="metadata-only",
                extractor_profile="default", include_paths=(), exclude_paths=exclude_secondary,
                selection_policy_id=source_selection_policy_id((), exclude_secondary),
                resolution_policy="allow-declared", enabled=True, role="module", input_name="secondary",
            )
        )
    return OpsGraphConfig(
        id=graph_id, name="Wave2 Test Graph", root_path="", root_path_expanded="",
        repository_name=repository_name, privacy=privacy, enabled=True,
        mcp_visible=False, extractor_profile="", refresh_policy="manual",
        source_bindings=tuple(bindings), explicit_source_bindings=True,
    )


def seal_and_verify_run25_artifacts(
    graph: OpsGraphConfig,
    store_dir: Path,
) -> tuple[PortableSnapshotManifest, ArtifactReference, str]:
    """Seal configured sources to store and verify manifest decode roundtrip."""
    store = FileSystemArtifactStore(store_dir)
    manifest, reference, candidate_id = seal_configured_sources(
        graph, store, extractor_generation="eg1:wave2-fixture", canonicalizer_generation="kg1:wave2-fixture",
    )
    raw_manifest_bytes = store.read(reference)
    decoded = PortableSnapshotManifest.from_bytes(raw_manifest_bytes)
    assert decoded.manifest_id == manifest.manifest_id
    assert decoded.total_files == manifest.total_files
    assert decoded.total_bytes == manifest.total_bytes
    assert decoded.snapshot_vector == manifest.snapshot_vector
    return decoded, reference, candidate_id


def inject_malformed_yaml(file_path: Path) -> str:
    """Tamper YAML file with conflicting duplicate keys and return original text."""
    original = file_path.read_text(encoding="utf-8")
    tampered = original + "\nservice: duplicate-conflicting-key\nservice: error-state\n"
    file_path.write_text(tampered, encoding="utf-8")
    return original


def inject_malformed_plist(file_path: Path) -> str:
    """Tamper Plist XML file with missing value element and return original text."""
    original = file_path.read_text(encoding="utf-8")
    tampered = original.replace("<string>com.repomap.wave2</string>", "")
    file_path.write_text(tampered, encoding="utf-8")
    return original


def restore_file_content(file_path: Path, original: str) -> None:
    """Restore file to original content."""
    file_path.write_text(original, encoding="utf-8")


def snapshot_tree_hashes(directory: Path) -> dict[str, str]:
    """Capture relative path to SHA-256 hash map of all regular files in directory."""
    hashes: dict[str, str] = {}
    for p in sorted(directory.rglob("*")):
        if p.is_file() and not p.is_symlink():
            rel = p.relative_to(directory).as_posix()
            hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return hashes
