"""Helper functions, route classification, and constants for bulk ingestion."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import tomllib

from repomap_kg.ops.ingestion.bulk_config_values import (
    bool_value,
    normalized_path_tuple,
    optional_string,
    required_bool,
    required_positive_int,
    required_string,
    required_table,
    resolve_config_root,
    string_tuple,
    table,
)
from repomap_kg.ops.ingestion.bulk_records import (
    BulkIncludedFile,
    BulkManifest,
    BulkPolicyError,
    BulkSourceConfig,
)

ALLOWED_SOURCE_TYPES = frozenset({"local.directory"})
ALLOWED_POLICY_STATUSES = frozenset({"allowed", "allowed_with_limits"})
ALLOWED_CORPUS_KINDS = frozenset(
    {
        "generic_local_corpus",
        "email_export",
        "eml_export",
        "mbox_export",
        "document_corpus",
        "source_code_corpus",
        "saved_page_corpus",
        "static_artifact_corpus",
        "report_corpus",
        "warc_corpus",
        "feed_corpus",
        "mixed_corpus",
    }
)
DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "vendor",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".gradle",
        "target",
        "build",
        "dist",
        ".next",
        ".nuxt",
        ".cache",
        ".Trash",
        "Mail",
        "Maildir",
        "Thunderbird",
        "Outlook",
        "Apple Mail",
        "Gmail",
        "Profiles",
    }
)
ARCHIVE_EXTENSIONS = frozenset(
    {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".bz2", ".xz"}
)
WARC_EXTENSIONS = frozenset({".warc", ".warc.gz"})
EXTENSION_ROUTES = {
    ".eml": "eml",
    ".mbox": "mbox",
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "config",
    ".jsonl": "config",
    ".jsonc": "config",
    ".toml": "config",
    ".yaml": "config",
    ".yml": "config",
    ".xml": "config",
    ".plist": "config",
    ".txt": "document",
    ".csv": "document",
    ".tsv": "document",
    ".tex": "document",
    ".latex": "document",
    ".odt": "document",
    ".ods": "document",
    ".ott": "document",
    ".ots": "document",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "javascript",
    ".mts": "javascript",
    ".cts": "javascript",
    ".tsx": "javascript",
    ".rb": "ruby",
    ".rake": "ruby",
    ".gemspec": "ruby",
    ".py": "python",
    ".nix": "nix",
    ".ps1": "powershell",
    ".psd1": "powershell",
    ".psm1": "powershell",
    ".awk": "awk",
    ".sh": "shell",
    ".bash": "bash",
    ".bats": "bats",
    ".zunit": "zunit",
    ".zsh": "zsh",
    ".rss": "feed",
    ".atom": "feed",
}
SPECIAL_FILENAME_ROUTES = {
    "Rakefile": "ruby",
    "Gemfile": "ruby",
    "Vagrantfile": "ruby",
}


def classify_bulk_route(path: Path) -> str | None:
    name = path.name
    if name in SPECIAL_FILENAME_ROUTES:
        return SPECIAL_FILENAME_ROUTES[name]
    suffixes = [suffix.lower() for suffix in path.suffixes]
    if len(suffixes) >= 2 and "".join(suffixes[-2:]) in WARC_EXTENSIONS:
        return "warc"
    if suffixes and suffixes[-1] in WARC_EXTENSIONS:
        return "warc"
    if suffixes and suffixes[-1] in ARCHIVE_EXTENSIONS:
        return "archive"
    return EXTENSION_ROUTES.get(path.suffix.lower())


def route_included(config: BulkSourceConfig, path: Path, route: str) -> bool:
    if not config.include_extensions:
        return True
    allowed = frozenset(item.lower() for item in config.include_extensions)
    if path.name in SPECIAL_FILENAME_ROUTES:
        return path.name in config.include_extensions or route in allowed or ".rb" in allowed
    suffix = path.suffix.lower()
    if len(path.suffixes) >= 2 and "".join(path.suffixes[-2:]).lower() in allowed:
        return True
    return suffix in allowed


def deterministic_run_id(
    config: BulkSourceConfig,
    included: Sequence[BulkIncludedFile],
) -> str:
    inventory = [
        {
            "relative_path": item.relative_path,
            "route": item.route,
            "byte_count": item.byte_count,
            "sha256": item.sha256,
        }
        for item in included
    ]
    payload = {
        "source_id": config.source_id,
        "source_type": config.source_type,
        "corpus_kind": config.corpus_kind,
        "policy_status": config.policy_status,
        "root_path_summary": root_path_summary(config),
        "limits": {
            "max_files": config.max_files,
            "max_total_bytes": config.max_total_bytes,
            "max_file_bytes": config.max_file_bytes,
            "max_depth": config.max_depth,
            "follow_symlinks": config.follow_symlinks,
            "include_hidden": config.include_hidden,
        },
        "include_extensions": config.include_extensions,
        "excluded_directories": config.excluded_directories,
        "excluded_paths": config.excluded_paths,
        "inventory": inventory,
    }
    return "bulk-" + sha256_json(payload)[:24]


def manifest_digest(manifest: BulkManifest) -> str:
    payload = manifest.to_jsonable()
    payload["manifest_sha256"] = ""
    return sha256_json(payload)


def root_path_summary(config: BulkSourceConfig) -> str:
    configured = config.root_path_configured
    if Path(configured).is_absolute():
        return "absolute-path-sha256:" + sha256_text(configured)[:16]
    return Path(configured).as_posix()


def relative_to_root(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def depth(relative_path: str) -> int:
    return len(Path(relative_path).parts)


def is_excluded_path(relative_path: str, excluded_paths: Sequence[str]) -> bool:
    return any(
        relative_path == excluded or relative_path.startswith(f"{excluded}/")
        for excluded in excluded_paths
    )


def safe_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: object) -> str:
    return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


def ensure_contained(path: Path, root: Path, name: str) -> None:
    if not is_contained(path, root):
        raise BulkPolicyError(f"{name} escapes repository root")


def is_contained(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def load_bulk_source_config(path: Path | str) -> BulkSourceConfig:
    config_path = Path(path).resolve()
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise BulkPolicyError(f"invalid bulk config: {error}") from error

    source = required_table(payload, "source")
    limits = required_table(payload, "limits")
    include = table(payload, "include")
    exclude = table(payload, "exclude")
    retention = table(payload, "retention")
    redaction = table(payload, "redaction")

    source_id = required_string(source, "source_id")
    source_type = required_string(source, "source_type")
    corpus_kind = required_string(source, "corpus_kind")
    policy_status = required_string(source, "policy_status")
    root_path_configured = required_string(source, "root_path")

    if source_type not in ALLOWED_SOURCE_TYPES:
        raise BulkPolicyError(f"unsupported source_type: {source_type}")
    if policy_status not in ALLOWED_POLICY_STATUSES:
        raise BulkPolicyError(f"source policy status is not allowed: {policy_status}")
    if corpus_kind not in ALLOWED_CORPUS_KINDS:
        raise BulkPolicyError(f"unsupported corpus_kind: {corpus_kind}")
    if "://" in root_path_configured:
        raise BulkPolicyError("root_path must be a local filesystem path")

    resolved_root = resolve_config_root(config_path, root_path_configured)
    if not resolved_root.exists():
        raise BulkPolicyError("root_path does not exist")
    if not resolved_root.is_dir():
        raise BulkPolicyError("root_path must be a directory for local.directory")

    return BulkSourceConfig(
        config_path=config_path,
        source_id=source_id,
        source_type=source_type,
        corpus_kind=corpus_kind,
        policy_status=policy_status,
        root_path_configured=root_path_configured,
        resolved_root=resolved_root,
        max_files=required_positive_int(limits, "max_files"),
        max_total_bytes=required_positive_int(limits, "max_total_bytes"),
        max_file_bytes=required_positive_int(limits, "max_file_bytes"),
        max_depth=required_positive_int(limits, "max_depth"),
        follow_symlinks=required_bool(limits, "follow_symlinks"),
        include_hidden=bool_value(limits.get("include_hidden", False), "include_hidden"),
        include_extensions=string_tuple(include.get("extensions", ())),
        excluded_directories=string_tuple(exclude.get("directories", ())),
        excluded_paths=normalized_path_tuple(exclude.get("paths", ())),
        retention_policy=optional_string(retention.get("policy")),
        redaction_profile=optional_string(redaction.get("profile")),
        sensitivity=optional_string(redaction.get("sensitivity")),
    )

