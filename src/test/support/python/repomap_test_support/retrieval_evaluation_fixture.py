"""Deterministic mixed-v1 retrieval evaluation fixture materialization and config builders (S2)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from common_lore_index.graph.multi_source import graph_source_binding_id
from common_lore_index.retrieval.projection_policy import (
    BodyProjectionPolicy,
    ResolvedBindingPolicy,
)

MIXED_V1_GRAPH_ID = "mixed-v1"
MIXED_V1_BINDINGS: tuple[str, ...] = ("core", "companion", "feeds", "mailbox")
MIXED_V1_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3] / "fixtures" / "retrieval_evaluation" / "mixed-v1"
)


def binding_id_for_alias(alias: str, graph_id: str = MIXED_V1_GRAPH_ID) -> str:
    """Compute the canonical bind1: identifier for a mixed-v1 binding alias."""
    return graph_source_binding_id(graph_id, alias)


MIXED_V1_BINDING_IDS: dict[str, str] = {
    alias: binding_id_for_alias(alias) for alias in MIXED_V1_BINDINGS
}
MIXED_V1_ALIAS_BY_BINDING_ID: dict[str, str] = {
    binding_id: alias for alias, binding_id in MIXED_V1_BINDING_IDS.items()
}


def _load_python_sources_manifest() -> dict[str, Any]:
    manifest_path = MIXED_V1_FIXTURE_ROOT / "python-sources-v1.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("invalid python-sources-v1.json")
    return raw


def _generate_edge_case_files(companion_root: Path) -> None:
    gen_dir = companion_root / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)

    trunc_lines: list[str] = [
        "# Deterministic Truncatable Prose Reference (mixed-v1)",
        "",
        "TRUNCATABLE_PROSE_PREFIX_MARKER_V1: findable within projected 262144-byte prefix.",
        "",
    ]
    filler = "Deterministic reference paragraph line for bounded chunk and file truncation proof. "
    trunc_lines.extend(f"Line {idx:04d}: {filler}" for idx in range(3400))
    trunc_lines.append(
        "TRUNCATABLE_PROSE_BEYOND_CAP_MARKER_V1: located past the 262144-byte per-file projection cap."
    )
    (gen_dir / "truncatable_prose.md").write_bytes(("\n".join(trunc_lines) + "\n").encode("utf-8"))

    oversized_header = "OVERSIZED_EXCLUSIVE_SENTINEL_8841: over 1 MiB artifact input bound.\n"
    oversized_block = ("0123456789abcdef" * 5 + "\n") * 13500
    (gen_dir / "oversized_dump.txt").write_bytes((oversized_header + oversized_block).encode("utf-8"))

    long_line = "# Long line multibyte note\n" + ("Δ-quorum-λ-verified-" * 520) + "LONG_LINE_TAIL_MARKER_V1\n"
    (gen_dir / "long_line_notes.md").write_bytes(long_line.encode("utf-8"))

    crlf_bytes = (
        b"CRLF Normalized Notes\r\n"
        b"CRLF_NORMALIZED_CITATION_MARKER_V1: line two with crlf\r\n"
        b"Standalone CR line three\r"
        b"Final LF line four\n"
    )
    (gen_dir / "crlf_notes.txt").write_bytes(crlf_bytes)
    nul_bytes = (
        b"Deterministic NUL-byte rejection test fixture file for mixed-v1 companion corpus.\n"
        b"This header exceeds the one-hundred-sixty character text summary window so that\n"
        b"metadata payload observations remain valid JSONB while body decoding rejects NUL.\n"
        b"\x00BINARY_NUL_REJECTED_MARKER_V1\n"
    )
    (gen_dir / "binary_nul.txt").write_bytes(nul_bytes)
    (gen_dir / "invalid_utf8.txt").write_bytes(b"valid ascii header\n\xff\xfeINVALID_UTF8_REJECTED_MARKER_V1\n")


def materialize_mixed_v1_working_copy(
    target_root: Path,
    *,
    generation: int = 1,
) -> Path:
    """Materialize a complete mixed-v1 working copy for generation 1 or 2."""
    if generation not in (1, 2):
        raise ValueError(f"unsupported mixed-v1 generation: {generation!r}")
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    for alias in MIXED_V1_BINDINGS:
        shutil.copytree(MIXED_V1_FIXTURE_ROOT / alias, target_root / alias)

    py_manifest = _load_python_sources_manifest()
    py_files: dict[str, str] = dict(py_manifest["generation_1"])
    if generation == 2:
        for deleted_rel in py_manifest.get("generation_2_deleted", ()):
            py_files.pop(deleted_rel, None)
        for rel_path, content in py_manifest.get("generation_2_overrides", {}).items():
            py_files[rel_path] = content

    for rel_path, content in sorted(py_files.items()):
        dest = target_root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content.encode("utf-8"))

    for sh_rel in ("core/scripts/bootstrap.sh", "companion/deploy.sh"):
        sh_path = target_root / sh_rel
        if sh_path.is_file():
            os.chmod(sh_path, 0o755)

    _generate_edge_case_files(target_root / "companion")
    return target_root


def compute_working_copy_digests(
    working_copy_root: Path,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Compute sorted SHA-256 and byte-size inventory across all four binding roots."""
    inventory: dict[tuple[str, str], dict[str, Any]] = {}
    for alias in MIXED_V1_BINDINGS:
        binding_root = working_copy_root / alias
        if not binding_root.is_dir():
            continue
        for file_path in sorted(binding_root.rglob("*")):
            if not file_path.is_file():
                continue
            rel_posix = file_path.relative_to(binding_root).as_posix()
            raw = file_path.read_bytes()
            inventory[(alias, rel_posix)] = {
                "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
    return inventory


def build_mixed_v1_projection_policy(
    graph_id: str = MIXED_V1_GRAPH_ID,
    *,
    selected_aliases: Sequence[str] = ("core", "companion"),
) -> BodyProjectionPolicy:
    """Build the canonical W2 BodyProjectionPolicy for mixed-v1."""
    core_id = binding_id_for_alias("core", graph_id)
    companion_id = binding_id_for_alias("companion", graph_id)
    feeds_id = binding_id_for_alias("feeds", graph_id)
    mailbox_id = binding_id_for_alias("mailbox", graph_id)

    bindings = {
        core_id: ResolvedBindingPolicy(
            binding_id=core_id,
            alias="core",
            role="source",
            source_kind="folder",
            original_graph_privacy="public-dev",
            resolved_graph_privacy="public-dev",
            original_binding_privacy="public-dev",
            resolved_binding_privacy="public-dev",
            original_evidence_retention="full-authorized",
            resolved_evidence_retention="full-authorized",
        ),
        companion_id: ResolvedBindingPolicy(
            binding_id=companion_id,
            alias="companion",
            role="companion",
            source_kind="folder",
            original_graph_privacy="public-dev",
            resolved_graph_privacy="public-dev",
            original_binding_privacy="public-dev",
            resolved_binding_privacy="public-dev",
            original_evidence_retention="full-authorized",
            resolved_evidence_retention="full-authorized",
        ),
        feeds_id: ResolvedBindingPolicy(
            binding_id=feeds_id,
            alias="feeds",
            role="feeds",
            source_kind="folder",
            original_graph_privacy="public-dev",
            resolved_graph_privacy="public-dev",
            original_binding_privacy="public-dev",
            resolved_binding_privacy="public-dev",
            original_evidence_retention="metadata-only",
            resolved_evidence_retention="metadata-only",
        ),
        mailbox_id: ResolvedBindingPolicy(
            binding_id=mailbox_id,
            alias="mailbox",
            role="mailbox",
            source_kind="folder",
            original_graph_privacy="public-dev",
            resolved_graph_privacy="public-dev",
            original_binding_privacy="private-memory",
            resolved_binding_privacy="private-memory",
            original_evidence_retention="metadata-only",
            resolved_evidence_retention="metadata-only",
        ),
    }
    selected_ids = frozenset(binding_id_for_alias(a, graph_id) for a in selected_aliases)
    return BodyProjectionPolicy(
        graph_id=graph_id,
        selected_binding_ids=selected_ids,
        bindings=bindings,
    ).validate()


def _render_source_bindings_toml(working_copy_root: Path, graph_id: str) -> str:
    specs = (
        ("core", "public-dev", "full-authorized", "allow-declared", "source", ""),
        ("companion", "public-dev", "full-authorized", "allow-declared", "companion", 'exclude_paths = ["excluded_cache"]\n'),
        ("feeds", "public-dev", "metadata-only", "isolated", "feeds", ""),
        ("mailbox", "private-memory", "metadata-only", "isolated", "mailbox", ""),
    )
    chunks: list[str] = []
    for alias, priv, ret, res_pol, role, extra in specs:
        r_path = (working_copy_root / alias).resolve().as_posix()
        b_id = binding_id_for_alias(alias, graph_id)
        chunks.append(
            f'[[graphs.source_bindings]]\nschema_version = 1\nbinding_id = "{b_id}"\n'
            f'source_definition_id = "src1:mixed-v1-{alias}"\nalias = "{alias}"\nrevision = 1\n'
            f'kind = "folder"\nroot_path = "{r_path}"\nrepository_name = "mixed-v1-{alias}"\n'
            f'logical_root = "{alias}"\nprivacy = "{priv}"\nevidence_retention = "{ret}"\n'
            f'extractor_profile = "default"\n{extra}resolution_policy = "{res_pol}"\n'
            f'role = "{role}"\ninput_name = "{alias}"\nenabled = true\n'
        )
    return "\n".join(chunks)


def _prepare_home_dirs(home_root: Path) -> Path:
    home_root.mkdir(parents=True, exist_ok=True)
    os.chmod(home_root, 0o700)
    state_dir = home_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)
    mem_dir = home_root / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir


def write_mixed_v1_sqlite_home(
    home_root: Path,
    working_copy_root: Path,
    *,
    graph_id: str = MIXED_V1_GRAPH_ID,
) -> Path:
    """Write a complete SQLite Local RepoMap home for mixed-v1."""
    mem_dir = _prepare_home_dirs(home_root)
    toml_text = (
        f'schema_version = 1\n\n[storage]\nbackend = "sqlite"\n\n'
        f'[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n\n'
        f'[server_memory]\nenabled = false\npath = "{mem_dir.resolve().as_posix()}"\nmode = "read_only"\n\n'
        f'[[graphs]]\nid = "{graph_id}"\nname = "Mixed-v1 Retrieval Evaluation Corpus"\n'
        f'enabled = true\nmcp_visible = true\nrefresh_policy = "manual"\n\n'
        f"{_render_source_bindings_toml(working_copy_root, graph_id)}"
    )
    (home_root / "repomap.rpl.toml").write_text(toml_text, encoding="utf-8")
    return home_root


def write_mixed_v1_postgres_home(
    home_root: Path,
    working_copy_root: Path,
    *,
    graph_id: str = MIXED_V1_GRAPH_ID,
    host: str = "127.0.0.1",
    port: int = 55433,
    database: str = "repomap_mixed_v1",
    user: str = "repomap",
    password: str | None = None,
) -> Path:
    """Write a complete PostgreSQL RepoMap home for mixed-v1."""
    mem_dir = _prepare_home_dirs(home_root)
    pw_line = ""
    if password is not None:
        pw_file = home_root / "pgpass.secret"
        pw_file.write_text(password, encoding="utf-8")
        os.chmod(pw_file, 0o600)
        pw_line = f'password_file = "{pw_file.resolve().as_posix()}"\n'

    toml_text = (
        f'schema_version = 1\n\n[storage]\nbackend = "postgresql"\n\n'
        f'[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n\n'
        f'[postgres]\nhost = "{host}"\nport = {port}\ndatabase = "{database}"\nuser = "{user}"\n{pw_line}\n'
        f'[runtime]\ncoordinator_mode = "native"\nbind_host = "127.0.0.1"\n\n'
        f'[runtime.postgres]\ndirect_host_port_enabled = true\nhost_port = {port}\nbind_host = "{host}"\n\n'
        f'[server_memory]\nenabled = false\npath = "{mem_dir.resolve().as_posix()}"\nmode = "read_only"\n\n'
        f'[[graphs]]\nid = "{graph_id}"\nname = "Mixed-v1 Retrieval Evaluation Corpus"\n'
        f'database = "{database}"\nenabled = true\nmcp_visible = true\nrefresh_policy = "manual"\n\n'
        f"{_render_source_bindings_toml(working_copy_root, graph_id)}"
    )
    (home_root / "repomap.rpl.toml").write_text(toml_text, encoding="utf-8")
    return home_root


__all__ = [
    "MIXED_V1_ALIAS_BY_BINDING_ID",
    "MIXED_V1_BINDINGS",
    "MIXED_V1_BINDING_IDS",
    "MIXED_V1_FIXTURE_ROOT",
    "MIXED_V1_GRAPH_ID",
    "binding_id_for_alias",
    "build_mixed_v1_projection_policy",
    "compute_working_copy_digests",
    "materialize_mixed_v1_working_copy",
    "write_mixed_v1_postgres_home",
    "write_mixed_v1_sqlite_home",
]
