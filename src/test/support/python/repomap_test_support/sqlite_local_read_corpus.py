"""Public-safe SQLite Local read-parity inputs (REPOMAP-PRODUCT3-SQLITE-LOCAL4-READ-PARITY1).

``write_polyglot_source`` is a tiny real source tree whose default extraction
yields nonempty Python, Terraform, OpenAPI, Express/Jest and Nix summaries next to
the shell graph shape the earlier SQLite Local tests rely on.
``read_corpus_bundle`` is a crafted raw-observation corpus that reaches the
summary predicate branches (boolean spellings, ``?`` on objects and arrays,
``LIKE`` wildcards, NULL operands under ``<>``/``NOT LIKE``, method case,
tfvars paths, Nix sections/shapes/patterns) and the ``jsonb::text`` edge cases
observation search depends on (key-length order, separators, escapes,
non-ASCII and large integers; the bundle domain excludes floats). Nothing
here is private data.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.staged_ingestion import build_staged_rows
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_test_support.sqlite_local_fixtures import write_shell_source

POLYGLOT_FILES: dict[str, str] = {
    "pkg/__init__.py": "",
    "pkg/app.py": (
        "from flask import Flask\n\napp = Flask(__name__)\n\n\n@app.route(\"/health\")\n"
        "def health():\n    return \"ok\"\n\n\nclass Worker:\n    def run(self):\n        return 1\n"
    ),
    "pyproject.toml": (
        '[project]\nname = "polyglot-demo"\nversion = "0.1.0"\ndependencies = ["flask>=3"]\n\n'
        '[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n\n'
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    ),
    "tests/test_app.py": (
        "import pytest\n\n\n@pytest.fixture\ndef value():\n    return 1\n\n\n"
        "def test_value(value):\n    assert value == 1\n"
    ),
    "infra/main.tf": (
        'terraform {\n  required_version = ">= 1.5"\n  required_providers {\n'
        '    aws = {\n      source  = "hashicorp/aws"\n      version = "~> 5.0"\n    }\n  }\n}\n\n'
        'provider "aws" {\n  region = "us-east-1"\n}\n\nvariable "name" {\n  type = string\n}\n\n'
        'resource "aws_s3_bucket" "b" {\n  bucket = var.name\n}\n\n'
        'output "id" {\n  value = aws_s3_bucket.b.id\n}\n\n'
        'module "net" {\n  source = "./modules/net"\n}\n'
    ),
    "infra/modules/net/main.tf": 'variable "cidr" {\n  type = string\n}\n',
    "api/openapi.yaml": (
        "openapi: 3.0.3\ninfo:\n  title: Demo\n  version: 1.0.0\nservers:\n  - url: https://api.example.test\n"
        "paths:\n  /items/{id}:\n    get:\n      operationId: getItem\n      parameters:\n"
        "        - name: id\n          in: path\n          required: true\n          schema:\n"
        "            type: string\n      responses:\n        '200':\n          description: ok\n"
        "          content:\n            application/json:\n              schema:\n"
        "                $ref: '#/components/schemas/Item'\n"
        "components:\n  schemas:\n    Item:\n      type: object\n      properties:\n"
        "        id:\n          type: string\n"
    ),
    "web/package.json": (
        '{\n  "name": "web-demo",\n  "version": "1.0.0",\n  "main": "server.js",\n'
        '  "scripts": {"test": "jest"},\n  "dependencies": {"express": "^4.19.0"},\n'
        '  "devDependencies": {"jest": "^29.0.0"}\n}\n'
    ),
    "web/server.js": (
        'const express = require("express");\n\nconst app = express();\n\n'
        'app.get("/items/:id", (req, res) => {\n  res.json({ id: req.params.id });\n});\n\n'
        "module.exports = app;\n"
    ),
    "flake.nix": (
        '{\n  description = "polyglot demo";\n'
        '  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";\n'
        "  outputs = { self, nixpkgs }: {\n"
        "    packages.x86_64-linux.default = nixpkgs.legacyPackages.x86_64-linux.hello;\n"
        '    apps.x86_64-linux.default = { type = "app"; program = "${self}/run.sh"; };\n'
        "    devShells.x86_64-linux.default = nixpkgs.legacyPackages.x86_64-linux.mkShell { };\n"
        "  };\n}\n"
    ),
    "web/app.test.js": (
        'const app = require("./server");\n\ndescribe("app", () => {\n'
        '  test("exports an app", () => {\n    expect(app).toBeDefined();\n  });\n});\n'
    ),
}


def write_polyglot_source(root: Path) -> Path:
    """The shell graph files plus one tiny file set per summary family."""
    write_shell_source(root)
    for relative, text in POLYGLOT_FILES.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _observation(kind: str, path: str, index: int, metadata: Mapping[str, Any], **fields: Any) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{path}#corpus:{index}",
        path=path,
        confidence="extracted",
        extractor="corpus",
        extractor_version="1",
        metadata=metadata,
        **fields,
    )


# (kind, path, metadata, extra top-level fields). Each row exists to move or
# deliberately not move one PostgreSQL predicate; missing keys are NULL cases.
CorpusRow = tuple[str, str, dict[str, Any], dict[str, Any]]
CORPUS_ROWS: tuple[CorpusRow, ...] = (
    ("file", "src/tool.py", {"language": "python", "role": "source"}, {}),
    ("file", "flake.nix", {"language": "nix", "role": "source"}, {}),
    ("file", "sub/flake.nix", {"role": "source"}, {}),
    ("file", "infra/main.tf", {"language": "terraform", "role": "source"}, {}),
    ("python.package_file", "requirements-dev.txt", {"file_family": "requirements-dev"}, {}),
    ("python.package_file", "reqs.in", {"source_format": "python-requirements"}, {}),
    ("python.package_file", "Requirements.txt", {"file_family": "Requirements"}, {}),
    ("python.pyproject", "pyproject.toml", {"project_name": "repo-map-kg"}, {}),
    ("python.test_file", "tests/test_repomapXkg.py", {}, {}),
    ("python.pytest_fixture", "tests/conftest.py", {}, {}),
    ("python.test_fixture", "tests/test_unit.py", {}, {}),
    ("python.fastapi_dependency", "app/deps.py", {}, {}),
    ("python.reference", "requirements.txt",
     {"reference_kind": "direct_url", "not_fetched": True, "source_format": "python-requirements"},
     {"target": "https://example.test/pkg.whl"}),
    ("python.reference", "requirements.txt", {"reference_kind": "index_url", "not_fetched": "yes"}, {}),
    ("python.reference", "requirements.txt", {"reference_kind": "local_path", "not_fetched": "off"},
     {"target": "file:vendor/pkg"}),
    ("python.reference", "setup.cfg", {"not_fetched": "t", "direct_url": "on"}, {}),
    ("python.reference", "app/main.py", {"framework": "django", "resolution": "local"}, {}),
    ("python.redaction", "settings.py", {"redaction_reason": "private-index-credential"}, {}),
    ("python.redaction", "settings.py", {"redaction_reason": "django-secret"}, {}),
    ("python.parse_error", "gen.py", {"error_kind": "dynamic-import", "dynamic": False}, {}),
    ("python.parse_error", "big.py", {"error_kind": "node-limit"}, {}),
    ("python.parse_error", "odd.py", {"dynamic": 1}, {}),
    ("terraform.file", "main.tf", {"file_family": "tf"}, {}),
    ("terraform.file", "terraform.tfvars", {"file_family": "tfvars"}, {}),
    ("terraform.file", "env/terraform.tfvars", {"file_family": "tfvars"}, {}),
    ("terraform.file", "prod.auto.tfvars", {"file_family": "tfvars"}, {}),
    ("terraform.file", "custom.tfvars", {"file_family": "tfvars"}, {}),
    ("terraform.reference", "main.tf", {"reference_kind": "module_source_local", "not_fetched": True}, {}),
    ("terraform.reference", "main.tf", {"reference_kind": "module_source", "not_fetched": "true"}, {}),
    ("terraform.reference", "main.tf", {"not_fetched": True}, {}),
    ("terraform.reference", "main.tf", {"reference_kind": "required_version"}, {}),
    ("terraform.required_provider", "main.tf", {"version_constraint": "~> 5.0"}, {}),
    ("terraform.required_provider", "main.tf", {"version_constraint": None}, {}),
    ("terraform.variable", "terraform.tfvars", {"profile": "terraform_tfvars"}, {}),
    ("terraform.redaction", "backend.tf",
     {"redaction_reason": "secret-prone-terraform-attribute", "field_name": "access_key"}, {}),
    ("terraform.parse_error", "bad.tf", {"error_kind": "block-limit"}, {}),
    ("terraform.parse_error", "worse.tf", {"error_kind": "unterminated-block"}, {}),
    ("terraform.parse_error", "unknown.tf", {}, {}),
    ("openapi.document", "api.yaml", {"spec_family": "openapi3"}, {}),
    ("openapi.document", "legacy.json", {"spec_family": "swagger2"}, {}),
    ("openapi.operation", "api.yaml", {"method": "get"}, {}),
    ("openapi.operation", "api.yaml", {"method": "Post"}, {}),
    ("openapi.operation", "api.yaml", {}, {}),
    ("openapi.reference", "api.yaml", {"reference_scope": "remote", "not_fetched": "1"}, {}),
    ("openapi.reference", "api.yaml", {"reference_scope": "external_docs", "not_fetched": True}, {}),
    ("openapi.reference", "api.yaml", {"reference_scope": "internal"}, {}),
    ("openapi.redaction", "api.yaml", {"redaction_reason": "openapi-example-summary-only"}, {}),
    ("openapi.server", "api.yaml", {"redaction_reason": "credentialed-url"}, {}),
    ("openapi.parse_error", "api.yaml", {"error_kind": "openapi-path-limit"}, {}),
    ("config.parse_error", "broken.yaml", {"error_kind": "malformed-openapi-yaml"}, {}),
    ("config.document", "app.json", {"document_role": "app"}, {}),
    ("config.reference", "app.json", {"pointer": "/extends"}, {"target": "file:base.json"}),
    ("express.route", "web/server.js", {"dynamic": "false"}, {}),
    ("express.route", "web/server.js", {"dynamic": True}, {}),
    ("jest.test", "web/app.test.js", {}, {}),
    ("next.route", "web/app/route.js", {}, {}),
    ("js.framework_reference", "web/server.js", {"reference_kind": "environment"}, {}),
    ("js.parse_error", "web/big.js", {"error_kind": "framework-selector-limit"}, {}),
    ("nix.app", "flake.nix",
     {"program_resolution": "local", "flake_ref": "self", "system": "x86_64-linux", "name": "hello"}, {}),
    ("nix.app", "flake.nix", {"program": None, "flake_ref": "self", "system": "", "name": "run"}, {}),
    ("nix.path_ref", "flake.nix", {"resolution": "repo-escaping"}, {"target": "unknown:file:../x"}),
    ("nix.flake_input", "flake.nix", {"has_url": True, "has_follows": "true", "source_type": "github"}, {}),
    ("nix.output_section", "flake.nix",
     {"section": "packages", "section_family": "output", "shape": "direct_assignment"}, {}),
    ("nix.dynamic_output_shape", "flake.nix", {"pattern": "flake-utils"}, {}),
    ("nix.unsupported_flake_shape", "flake.nix", {"pattern": "imported_outputs"}, {}),
    ("nix.import", "flake.nix", {"dynamic_reason": "interpolated"}, {"target": "unknown:import"}),
    ("NIX.app", "flake.nix", {}, {}),
    ("config.path", "settings.json", {"pointer": "/token", "redacted": "yes"}, {}),
    ("config.redaction", "settings.json", {}, {}),
    ("custom.note", "docs/100% done_\\x.md",
     {"b": 150, "aa": {"z": [1, "two", None]}, "c": "Ärger \"quoted\"\ttab", "e": 10**20, "d": -7},
     {"name": "Ünïcode Name"}),
)


def read_corpus_bundle(
    graph_id: str = "portable-fixture", *, extra_rows: tuple[CorpusRow, ...] = ()
) -> PublicationBundle:
    """The crafted corpus (plus any caller rows) as one validated portable bundle."""
    observations = tuple(
        _observation(kind, path, index, metadata, **extra)
        for index, (kind, path, metadata, extra) in enumerate((*CORPUS_ROWS, *extra_rows))
    )
    prepared = build_staged_rows(observations, repository_name=graph_id, stage_id="stage-unassigned")
    try:
        families = {
            family: tuple(dict(row) for row in prepared.family_rows[family])
            for family in PUBLICATION_FAMILIES
        }
    finally:
        prepared.close()
    return PublicationBundle.create(
        request_id="job-sqlite-corpus",
        job_id="job-sqlite-corpus",
        attempt=1,
        graph_id=graph_id,
        candidate_id="cand1:" + "1" * 64,
        snapshot_manifest_id="snapmanifest1:" + "2" * 64,
        snapshot_vector=(("bind1:" + "3" * 64, 1, "snap1:" + "4" * 64),),
        source_generation="sg1:" + "5" * 64,
        config_generation="cg1:" + "6" * 64,
        extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        families=families,
        row_stage_contract="stage-unassigned-v1",
    )


__all__ = ("CORPUS_ROWS", "POLYGLOT_FILES", "CorpusRow", "read_corpus_bundle", "write_polyglot_source")
