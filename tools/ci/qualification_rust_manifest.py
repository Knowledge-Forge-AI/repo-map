"""Closed manifest and source-closure checks for the Rust native gate."""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

SCHEMA = "cloe-rust-pilot-qualification-manifest-v1"
WINDOW = "RUST-PILOT-QW1"
GOLD_SCHEMA = "cloe-rust-pilot-gold-v1"
EXPECTED_ITEM_CLAIMS = 420
EXPECTED_SOURCES = (
    "q01_all_items.rs", "q02_long_positions.rs", "q03_crlf_bom.rs",
    "q03_unicode_raw.rs", "q04_malformed_scopes.rs", "q04_missing_brace.rs",
    "q05_build/build.rs", "q05_cfg_macros.rs", "q06_invalid_utf8.rs",
    "stress_ambiguity.rs", "stress_attributes.rs", "stress_depth.rs",
    "unsupported_forms.rs",
)
EXPECTED_GOLDS = tuple(
    path.replace("/", "__").removesuffix(".rs") + ".gold.json" for path in EXPECTED_SOURCES
)
EXPECTED_FILES = EXPECTED_SOURCES + tuple("golds/" + name for name in EXPECTED_GOLDS)
EXPECTED_SCENARIOS = {
    "arm64": ("Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q09", "Q10", "Q11", "Q12"),
    "amd64": ("Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q09", "Q10", "Q12"),
    "t1": ("Q08", "Q13", "Q14"),
}
GUEST_FILES = (
    "src/main/python/common_lore_index/extractors/rust_pilot/guest/setup_writer.py",
    "src/main/python/common_lore_index/extractors/rust_pilot/guest/install_readback.py",
    "src/main/python/common_lore_index/extractors/rust_pilot/guest/runtime_probe.py",
    "src/main/python/common_lore_index/extractors/rust_pilot/guest/parse_helper.py",
    "src/main/python/common_lore_index/extractors/rust_pilot/guest/containment_probes.py",
)
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
FORBIDDEN_TOPS = frozenset({"psycopg", "psycopg2", "sqlalchemy", "storage",
                             "staged_ingestion", "publication", "worker"})
GOLD_KEYS = frozenset({
    "build_script_name", "completeness", "fixture", "input_bytes", "input_sha256",
    "item_list", "items", "line_count", "outcome", "scenarios", "schema", "unsupported",
})


class ManifestError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _map(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestError(code)
    return value


def _text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(code)
    return value


def _hex(value: object, pattern: re.Pattern[str], code: str) -> str:
    value = _text(value, code)
    if pattern.fullmatch(value) is None:
        raise ManifestError(code)
    return value


def _relative(value: object, code: str) -> str:
    text = _text(value, code)
    path = Path(text)
    if path.is_absolute() or str(path) != text or "\\" in text or any(part in ("", ".", "..") for part in path.parts):
        raise ManifestError(code)
    return text


def _read_json(path: Path) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ManifestError("duplicate_json_key")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except ManifestError:
        raise
    except (OSError, UnicodeDecodeError, ValueError):
        raise ManifestError("json_invalid") from None


def _digest(path: Path) -> tuple[int, str]:
    try:
        data = path.read_bytes()
    except OSError:
        raise ManifestError("bound_file_missing") from None
    return len(data), hashlib.sha256(data).hexdigest()


def _check_guest(repo_root: Path, relative: str, expected: str) -> None:
    path = repo_root / relative
    size, actual = _digest(path)
    if size == 0 or actual != expected:
        raise ManifestError("guest_digest_mismatch")
    try:
        source = path.read_text(encoding="ascii")
        tree = ast.parse(source, filename=relative)
    except (OSError, UnicodeDecodeError, SyntaxError):
        raise ManifestError("guest_source_invalid") from None
    dynamic = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "importlib":
            if tuple(alias.name for alias in node.names) != ("import_module",):
                raise ManifestError("guest_importlib_scope")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    dynamic += 1
                if alias.name.split(".", 1)[0] in FORBIDDEN_TOPS:
                    raise ManifestError("guest_forbidden_import")
    if "importlib.import_module" in source:
        if source.count('for name in ("tree_sitter", "tree_sitter_rust"):') != 1:
            raise ManifestError("guest_dynamic_import_loop")
        if source.count("importlib.import_module(name)") != 1:
            raise ManifestError("guest_dynamic_import_loop")
    if dynamic and "importlib.import_module" not in source:
        raise ManifestError("guest_dynamic_import")


def _check_closure(repo_root: Path, closure: Mapping[str, Any]) -> None:
    from ci.qualification_rust_closure import ClosureRefused, required_sources

    raw_paths = closure.get("python_paths")
    from ci.qualification_rust_shape import source_digests

    digests = source_digests(closure)
    if (not isinstance(raw_paths, list) or not raw_paths
            or any(not isinstance(path, str) for path in raw_paths)
            or set(raw_paths) != set(digests)):
        raise ManifestError("closure_path_set")
    listed = {_relative(raw, "closure_path") for raw in raw_paths}
    if len(listed) != len(raw_paths):
        raise ManifestError("closure_duplicate")
    guest_init = "src/main/python/common_lore_index/extractors/rust_pilot/guest/__init__.py"
    try:
        required = required_sources(repo_root) | set(GUEST_FILES) | {guest_init}
    except (ClosureRefused, OSError, SyntaxError):
        raise ManifestError("closure_import_refused") from None
    if listed != required:
        raise ManifestError("closure_transitive_set_mismatch")
    for relative in sorted(listed):
        path = repo_root / relative
        if path.resolve() != path or not path.is_file():
            raise ManifestError("closure_path")
        expected = _hex(digests.get(relative), HEX64, "closure_digest")
        size, actual = _digest(path)
        if size == 0 or actual != expected:
            raise ManifestError("closure_digest_mismatch")
    for node in ast.parse((repo_root / guest_init).read_bytes()).body:
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            raise ManifestError("guest_namespace_not_inert")
    guest_digests = _map(closure.get("guest_digests"), "guest_digests")
    if set(guest_digests) != set(GUEST_FILES):
        raise ManifestError("guest_path_set")
    for relative in GUEST_FILES:
        _check_guest(repo_root, relative, _hex(guest_digests.get(relative), HEX64, "guest_digest"))
    lock = _map(closure.get("component_lock"), "component_lock")
    lock_path = _relative(lock.get("path"), "component_lock_path")
    if lock_path != "src/main/python/common_lore_index/extractors/rust_pilot/component_lock.py":
        raise ManifestError("component_lock_path")
    _size, actual = _digest(repo_root / lock_path)
    if actual != _hex(lock.get("sha256"), HEX64, "component_lock_digest"):
        raise ManifestError("component_lock_mismatch")
    from common_lore_index.extractors.rust_pilot.guest_sources import helper_closure_sha256, load_guest_sources
    from common_lore_index.extractors.rust_pilot.probe_material import PROBE_SOURCE_SHA256
    if helper_closure_sha256(load_guest_sources(), PROBE_SOURCE_SHA256) != _hex(
            closure.get("helper_closure_sha256"), HEX64, "helper_closure_digest"):
        raise ManifestError("helper_closure_mismatch")
    from common_lore_index.extractors.rust_pilot.prepared_profile import profile_bytes
    profiles = _map(closure.get("profile_digests"), "profile_digests")
    for arch, cpu in (("amd64", "x86_64"), ("arm64", "aarch64")):
        if hashlib.sha256(profile_bytes(cpu)).hexdigest() != _hex(profiles.get(arch), HEX64, "profile_digest"):
            raise ManifestError("profile_digest_mismatch")


def _check_fixtures(repo_root: Path, fixture: Mapping[str, Any]) -> None:
    if fixture.get("root") != "src/test/fixtures/rust_pilot" or fixture.get("expected_item_claims") != 420:
        raise ManifestError("fixture_root")
    files = _map(fixture.get("files"), "fixture_files")
    if set(files) != set(EXPECTED_FILES):
        raise ManifestError("fixture_file_set")
    claims = 0
    for relative in EXPECTED_SOURCES:
        entry = _map(files.get(relative), "fixture_source_entry")
        gold_name = _relative(entry.get("gold"), "fixture_gold_name")
        expected_gold = "golds/" + relative.replace("/", "__").removesuffix(".rs") + ".gold.json"
        if gold_name != expected_gold or not isinstance(entry.get("scenario"), str):
            raise ManifestError("fixture_gold_binding")
        expected_bytes = entry.get("bytes")
        expected_sha = _hex(entry.get("sha256"), HEX64, "fixture_source_digest")
        size, actual = _digest(repo_root / fixture["root"] / relative)
        if type(expected_bytes) is not int or size != expected_bytes or actual != expected_sha:
            raise ManifestError("fixture_source_mismatch")
        gold = _read_json(repo_root / fixture["root"] / gold_name)
        if set(gold) != GOLD_KEYS or gold.get("schema") != GOLD_SCHEMA:
            raise ManifestError("gold_schema")
        if gold.get("fixture") != relative or gold.get("scenarios") != [entry["scenario"]]:
            raise ManifestError("gold_fixture_binding")
        if gold.get("input_bytes") != size or gold.get("input_sha256") != actual:
            raise ManifestError("gold_input_binding")
        if not isinstance(gold.get("items"), list) or not isinstance(gold.get("unsupported"), list):
            raise ManifestError("gold_document_shape")
        claims += len(gold["items"])
    if claims != EXPECTED_ITEM_CLAIMS:
        raise ManifestError("gold_claim_count")
    for relative in EXPECTED_GOLDS:
        entry = _map(files.get("golds/" + relative), "fixture_gold_entry")
        size, actual = _digest(repo_root / fixture["root"] / "golds" / relative)
        if size != entry.get("bytes") or actual != _hex(entry.get("sha256"), HEX64, "fixture_gold_digest"):
            raise ManifestError("fixture_gold_mismatch")


def _check_wheels(repo_root: Path, value: object) -> None:
    from common_lore_index.extractors.rust_pilot.component_lock import DOCKER_ARCH_BY_CPU, WHEELS

    locked = {(DOCKER_ARCH_BY_CPU[wheel.cpu], wheel.filename): wheel for wheel in WHEELS}
    if not isinstance(value, list) or len(value) != 4:
        raise ManifestError("wheel_budget")
    amd, arm, names = 0, 0, set()
    for raw in value:
        wheel = _map(raw, "wheel_record")
        name = _text(wheel.get("name"), "wheel_name")
        if Path(name).name != name or name in names:
            raise ManifestError("wheel_name")
        names.add(name)
        architecture, state = wheel.get("architecture"), wheel.get("state")
        if state != ("pending" if architecture == "amd64" else "held"):
            raise ManifestError("wheel_state")
        if architecture not in {"amd64", "arm64"}:
            raise ManifestError("wheel_architecture")
        url = _text(wheel.get("url"), "wheel_url")
        if not url.startswith("https://files.pythonhosted.org/packages/") or "?" in url or "#" in url:
            raise ManifestError("wheel_url")
        if type(wheel.get("bytes")) is not int or wheel["bytes"] <= 0:
            raise ManifestError("wheel_size")
        _hex(wheel.get("sha256"), HEX64, "wheel_digest")
        expected = locked.get((architecture, name))
        if expected is None or (name, url, wheel["bytes"], wheel["sha256"]) != (
                expected.filename, expected.url, expected.size, expected.sha256):
            raise ManifestError("wheel_lock_mismatch")
        amd += architecture == "amd64"
        arm += architecture == "arm64"
    if (amd, arm) != (2, 2):
        raise ManifestError("wheel_budget")


def _check_incumbent(incumbent: Mapping[str, Any]) -> None:
    if incumbent.get("semantics") != "actual-file-only":
        raise ManifestError("incumbent_semantics")
    _relative(incumbent.get("report_path"), "incumbent_path")
    _hex(incumbent.get("sha256"), HEX64, "incumbent_digest")
    for key in ("files_key", "items_key", "input_digests_key", "navigation_key",
                "graph_quality_key", "discovery_ms_key", "schema"):
        _text(incumbent.get(key), "incumbent_" + key)
    fixture_digests = incumbent.get("fixture_digests")
    if not isinstance(fixture_digests, Mapping) or set(fixture_digests) != set(EXPECTED_SOURCES):
        raise ManifestError("incumbent_fixture_digests")
    for digest in fixture_digests.values():
        _hex(digest, HEX64, "incumbent_fixture_digest")


def validate_manifest(path: Path, repo_root: Path) -> dict[str, Any]:
    from ci.qualification_rust_shape import ShapeRefused, validate_shape

    document = _map(_read_json(path), "manifest_mapping")
    try:
        validate_shape(document)
    except ShapeRefused as error:
        raise ManifestError(str(error)) from None
    if document.get("schema") != SCHEMA or document.get("window") != WINDOW:
        raise ManifestError("manifest_identity")
    if document.get("candidate_binding") != "sealed_d12.pr_binding":
        raise ManifestError("candidate_binding")
    checkpoint = _map(document.get("source_checkpoint"), "source_checkpoint")
    _hex(checkpoint.get("sha"), HEX40, "checkpoint_sha")
    _hex(checkpoint.get("tree"), HEX40, "checkpoint_tree")
    sdk = _map(document.get("sdk"), "sdk_mapping")
    if sdk.get("architecture") != "amd64" or sdk.get("image_id_binding") != "sealed_d12.sdk_materialization.sdk_image_id":
        raise ManifestError("sdk_binding")
    _hex(sdk.get("recipe_sha256"), HEX64, "sdk_recipe_digest")
    _hex(sdk.get("profile_sha256"), HEX64, "sdk_profile_digest")
    recipes = _map(sdk.get("recipe_files"), "sdk_recipe_files")
    for relative, digest in recipes.items():
        _relative(relative, "sdk_recipe_path")
        _hex(digest, HEX64, "sdk_recipe_file_digest")
    _check_closure(repo_root, _map(document.get("closure"), "closure_mapping"))
    if sdk["profile_sha256"] != document["closure"]["profile_digests"]["amd64"]:
        raise ManifestError("sdk_profile_binding")
    fixture = _map(document.get("fixture"), "fixture_mapping")
    _check_fixtures(repo_root, fixture)
    _check_wheels(repo_root, document.get("wheels"))
    incumbent = _map(document.get("incumbent"), "incumbent_mapping")
    _check_incumbent(incumbent)
    fixture_digests = _map(incumbent.get("fixture_digests"), "incumbent_fixture_digests")
    fixture_files = _map(fixture.get("files"), "fixture_files")
    if any(fixture_digests.get(path) != _map(fixture_files[path], "fixture_source_entry").get("sha256")
           for path in EXPECTED_SOURCES):
        raise ManifestError("incumbent_fixture_binding")
    scenarios = _map(document.get("scenarios"), "scenarios")
    for name, expected in EXPECTED_SCENARIOS.items():
        if tuple(scenarios.get(name, ())) != expected:
            raise ManifestError("scenario_set")
    navigation = _map(document.get("navigation"), "navigation")
    tasks = navigation.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 5:
        raise ManifestError("navigation_task_count")
    for task in tasks:
        if not isinstance(task, Mapping) or any(not isinstance(task.get(key), str) or not task[key]
                                                for key in ("fixture", "name", "namespace", "incumbent_key")):
            raise ManifestError("navigation_task_shape")
        if task["fixture"] not in EXPECTED_SOURCES:
            raise ManifestError("navigation_fixture")
    if _map(document["incumbent"], "incumbent").get("navigation_key") != navigation.get("incumbent_key"):
        raise ManifestError("navigation_binding")
    budget = _map(document.get("budget"), "budget")
    if (budget.get("commands"), budget.get("amd_wheel_transfers"), budget.get("arm_wheel_transfers"),
            budget.get("redirects"), budget.get("retries")) != (1, 2, 0, False, False):
        raise ManifestError("budget")
    if document.get("stopping") != "one-command-over-whole-manifest" or document.get("replacement") != "none":
        raise ManifestError("stopping_policy")
    return dict(document)


def fixture_paths(document: Mapping[str, Any], repo_root: Path) -> tuple[Path, Path]:
    root = repo_root / str(_map(document["fixture"], "fixture")["root"])
    return root, root / "golds"
