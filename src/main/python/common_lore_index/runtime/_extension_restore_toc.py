"""Derived TOC planning bound to the archive TOC and catalog facts for D9-B extension_v2."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from common_lore_index.runtime._backup_provenance import (
    BASELINE_EXTENSION_NAME,
    MAX_TOC_OUTPUT_BYTES,
    parse_and_verify_toc_provenance,
    provenance_error,
)
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime.local import LocalRuntimeDiagnostic


@dataclass(frozen=True)
class DerivedTocPlan:
    """Verified derived TOC list bound to original archive TOC and catalog facts."""

    database: str
    original_toc_sha256: str
    derived_toc_bytes: bytes
    derived_toc_sha256: str
    total_entry_count: int
    selected_dump_ids: tuple[int, ...]
    excluded_entries: tuple[dict[str, object], ...]
    extension_comments: tuple[str, ...] = ()


def _parse_comment_extension_name(comment_tail: str, known_extensions: set[str]) -> str | None:
    if not comment_tail.startswith("EXTENSION "):
        return None
    ext_tail = comment_tail[len("EXTENSION ") :]
    candidates = [ext_tail[:-1]] if ext_tail.endswith(" ") else []
    candidates.append(ext_tail)
    prefix, sep, _owner = ext_tail.rpartition(" ")
    if sep and prefix:
        candidates.append(prefix)
    for cand in candidates:
        if cand in known_extensions:
            return cand
    return ""


def build_derived_toc_plan(
    raw_toc_bytes: bytes,
    *,
    database: str,
    database_catalog: Mapping[str, object],
    expected_toc_sha256: str,
) -> DerivedTocPlan:
    if len(raw_toc_bytes) > MAX_TOC_OUTPUT_BYTES:
        raise provenance_error(
            "backup-toc-inconsistent", database, f"TOC exceeded {MAX_TOC_OUTPUT_BYTES} bytes"
        )
    cfg_raw = database_catalog.get("extension_config_tables")
    if isinstance(cfg_raw, list) and cfg_raw:
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-extension-config-unsupported",
                    database,
                    "extension configuration tables/sequences are unsupported",
                ),
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-restore-unsupported",
                    database,
                    f"backup restore unsupported for {database}: extension-config-table-unsupported",
                ),
            )
        )
    toc_obs = parse_and_verify_toc_provenance(
        raw_toc_bytes, database=database, database_catalog=database_catalog
    )
    if (
        not isinstance(expected_toc_sha256, str)
        or len(expected_toc_sha256) != 64
        or toc_obs.toc_sha256 != expected_toc_sha256.lower()
    ):
        raise provenance_error(
            "backup-toc-inconsistent",
            database,
            "archive TOC digest mismatch against manifest binding",
        )
    installed_raw = database_catalog.get("installed_extensions")
    if not isinstance(installed_raw, list):
        raise provenance_error("backup-toc-inconsistent", database, "installed_extensions missing")
    non_baseline_exts: dict[str, str] = {}
    for item in installed_raw:
        if not isinstance(item, Mapping):
            raise provenance_error("backup-toc-inconsistent", database, "invalid extension entry")
        ext_name, ext_schema = str(item.get("name") or ""), str(item.get("schema") or "")
        if not ext_name or not ext_schema:
            raise provenance_error(
                "backup-toc-inconsistent", database, "incomplete extension entry"
            )
        if ext_name != BASELINE_EXTENSION_NAME:
            non_baseline_exts[ext_name] = ext_schema

    known_extensions = set(non_baseline_exts) | {BASELINE_EXTENSION_NAME}
    precreated_schemas = {
        sch for sch in non_baseline_exts.values() if sch not in ("public", "pg_catalog")
    }

    toc_text = raw_toc_bytes.decode("utf-8")
    selected_lines: list[str] = []
    selected_dump_ids: list[int] = []
    excluded_entries: list[dict[str, object]] = []
    seen_dump_ids: set[int] = set()
    seen_ext_entries: set[str] = set()
    seen_ext_comments: set[str] = set()
    seen_schema_entries: set[str] = set()
    entry_count = 0

    for raw_line in toc_text.split("\n"):
        line = raw_line.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith(";"):
            selected_lines.append(line)
            continue
        dump_id_str, after_semi = line.split(";", 1)
        dump_id = int(dump_id_str.strip())
        if dump_id in seen_dump_ids:
            raise provenance_error(
                "backup-toc-inconsistent", database, f"duplicate TOC dump_id {dump_id}"
            )
        seen_dump_ids.add(dump_id)
        entry_count += 1
        rest = after_semi.lstrip(" ").split(" ", 2)[2]

        if rest == "EXTENSION" or rest.startswith("EXTENSION "):
            ext_tail = rest[len("EXTENSION - ") :]
            ext_name = ext_tail[:-1] if ext_tail.endswith(" ") else ext_tail
            if ext_name not in known_extensions or ext_name in seen_ext_entries:
                raise provenance_error(
                    "backup-toc-inconsistent",
                    database,
                    f"unexpected or duplicate TOC EXTENSION {ext_name!r}",
                )
            seen_ext_entries.add(ext_name)
            excluded_entries.append(
                {
                    "dump_id": dump_id,
                    "kind": "EXTENSION",
                    "object_name": ext_name,
                    "reason": "preinstalled-extension",
                }
            )
            continue

        if rest.startswith("COMMENT - "):
            ext_comment_name = _parse_comment_extension_name(
                rest[len("COMMENT - ") :], known_extensions
            )
            if ext_comment_name is not None:
                if not ext_comment_name:
                    raise provenance_error(
                        "backup-toc-inconsistent",
                        database,
                        "COMMENT ON EXTENSION references unknown extension",
                    )
                if ext_comment_name == BASELINE_EXTENSION_NAME:
                    excluded_entries.append(
                        {
                            "dump_id": dump_id,
                            "kind": "COMMENT_EXTENSION",
                            "object_name": ext_comment_name,
                            "reason": "preinstalled-extension-comment",
                        }
                    )
                    continue
                seen_ext_comments.add(ext_comment_name)

        if rest == "SCHEMA" or rest.startswith("SCHEMA "):
            sch_tail = rest[len("SCHEMA - ") :]
            sch_name = sch_tail[:-1] if sch_tail.endswith(" ") else sch_tail.rpartition(" ")[0]
            if sch_name in seen_schema_entries:
                raise provenance_error(
                    "backup-toc-inconsistent", database, f"duplicate TOC SCHEMA {sch_name!r}"
                )
            seen_schema_entries.add(sch_name)
            if sch_name in precreated_schemas:
                excluded_entries.append(
                    {
                        "dump_id": dump_id,
                        "kind": "SCHEMA",
                        "object_name": sch_name,
                        "reason": "precreated-extension-schema",
                    }
                )
                continue

        selected_lines.append(line)
        selected_dump_ids.append(dump_id)

    if (set(non_baseline_exts) - seen_ext_entries) or (precreated_schemas - seen_schema_entries):
        raise provenance_error(
            "backup-toc-inconsistent",
            database,
            "TOC missing expected preinstalled extension or schema entries",
        )

    derived_text = "\n".join(selected_lines)
    if not derived_text.endswith("\n"):
        derived_text += "\n"
    derived_bytes = derived_text.encode("utf-8")
    return DerivedTocPlan(
        database=database,
        original_toc_sha256=toc_obs.toc_sha256,
        derived_toc_bytes=derived_bytes,
        derived_toc_sha256=hashlib.sha256(derived_bytes).hexdigest(),
        total_entry_count=entry_count,
        selected_dump_ids=tuple(selected_dump_ids),
        excluded_entries=tuple(excluded_entries),
        extension_comments=tuple(sorted(seen_ext_comments)),
    )
