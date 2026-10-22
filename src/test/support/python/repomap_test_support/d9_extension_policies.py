"""Test support for D9-B trusted policies, live qualification probes and synthetic extension artifacts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import json
import subprocess
import sys
from typing import Any

from repomap_kg.runtime._extension_restore_policy import (
    ExtensionReplayBounds,
    TrustedArtifactQualification,
    TrustedExtensionRestorePolicy,
    TrustedExtensionRule,
    TrustedOptionalCapabilityContract,
)
from repomap_kg.runtime._extension_restore_qualification import (
    engine_image_content_id,
    parse_client_version,
)
from repomap_kg.runtime._extension_restore_target import (
    _EXT_ARTIFACT_PROBE_SH,
)

SYNTHETIC_EXT_NAMES = ("ext_alpha", "ext_beta", "ext_gamma", "ext_cfg")
DEFAULT_TEST_ENGINE_IMAGE_ID = "sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb"
DEFAULT_TEST_INSPECT_IMAGE = "postgres:16-alpine"
UNIT_TEMPLATE_BASELINE = hashlib.sha256(b"unit-template1-baseline").hexdigest()
DEFAULT_REPLAY_BOUNDS = ExtensionReplayBounds(timeout_seconds=300.0, max_output_bytes=1024 * 1024)
DEFAULT_ARTIFACT_QUALIFICATION = TrustedArtifactQualification(
    allowed_server_versions=("16.4",), allowed_os_arch_abis=("x86_64-pc-linux-musl",),
    allowed_engine_image_ids=(DEFAULT_TEST_ENGINE_IMAGE_ID,), allowed_client_versions=("16.4",),
    template_baselines=((DEFAULT_TEST_ENGINE_IMAGE_ID, UNIT_TEMPLATE_BASELINE),),
)
UNIT_VECTOR_CONTROL_SHA256 = hashlib.sha256(b"vector-control-0.8.7").hexdigest()
UNIT_VECTOR_SCRIPT_SHA256 = hashlib.sha256(b"vector-script-0.8.7").hexdigest()
UNIT_VECTOR_LIBRARY_SHA256 = hashlib.sha256(b"vector-lib-0.8.7").hexdigest()


def _alpha_control_text(default_version: str = "1.1") -> str:
    return f"comment = 'Synthetic D9-B alpha extension'\ndefault_version = '{default_version}'\nschema = 'ext_alpha_s'\nrelocatable = false\n"


SYNTHETIC_EXT_FILES: dict[str, str] = {
    "ext_alpha.control": _alpha_control_text("1.1"),
    "ext_alpha--1.0.sql": "CREATE DOMAIN ext_alpha_s.alpha_label AS text CHECK (value <> '');\nCREATE FUNCTION ext_alpha_s.alpha_version() RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT '1.0'::text $$;\n",
    "ext_alpha--1.1.sql": "CREATE DOMAIN ext_alpha_s.alpha_label AS text CHECK (value <> '');\nCREATE FUNCTION ext_alpha_s.alpha_version() RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT '1.1'::text $$;\n",
    "ext_beta.control": "comment = 'Synthetic D9-B beta extension'\ndefault_version = '1.0'\nschema = 'ext_beta_s'\nrelocatable = false\nrequires = 'ext_alpha'\n",
    "ext_beta--1.0.sql": "CREATE DOMAIN ext_beta_s.beta_code AS ext_alpha_s.alpha_label;\nCREATE FUNCTION ext_beta_s.beta_probe() RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT ext_alpha_s.alpha_version() || ':beta-1.0' $$;\n",
    "ext_gamma.control": "comment = 'Synthetic D9-B gamma extension'\ndefault_version = '1.0'\nschema = 'ext_gamma_s'\nrelocatable = false\nrequires = 'ext_beta, ext_alpha'\n",
    "ext_gamma--1.0.sql": "CREATE DOMAIN ext_gamma_s.gamma_tag AS ext_beta_s.beta_code;\nCREATE FUNCTION ext_gamma_s.gamma_probe() RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT ext_beta_s.beta_probe() || ':gamma-1.0' $$;\n",
    "ext_cfg.control": "comment = 'Synthetic D9-B extconfig extension'\ndefault_version = '1.0'\nschema = 'ext_cfg_s'\nrelocatable = false\n",
    "ext_cfg--1.0.sql": (
        "CREATE SEQUENCE ext_cfg_s.cfg_seq START WITH 10;\n"
        "CREATE TABLE ext_cfg_s.cfg_items (\n    id bigint PRIMARY KEY DEFAULT nextval('ext_cfg_s.cfg_seq'),\n    k text NOT NULL,\n    is_user boolean NOT NULL DEFAULT true\n);\n"
        "SELECT pg_catalog.pg_extension_config_dump('ext_cfg_s.cfg_items', 'WHERE is_user');\nSELECT pg_catalog.pg_extension_config_dump('ext_cfg_s.cfg_seq', '');\n"
    ),
}


def synthetic_ext_sha256(filename: str) -> str:
    return hashlib.sha256(SYNTHETIC_EXT_FILES[filename].encode("utf-8")).hexdigest()


def probe_live_container_qualification(
    container_name: str, *, template_baseline_sha256: str, user: str = "repo_map_test", database: str = "repomap_test", runtime: str = "docker",
) -> TrustedArtifactQualification:
    """Observe exact server, ABI, Engine content ID and client versions; bind a separately established template1 reference."""
    items = json.loads(subprocess.run([runtime, "inspect", container_name], capture_output=True, text=True, check=True).stdout)
    image_id = engine_image_content_id(items[0].get("Image"))
    assert image_id is not None, f"container {container_name} has no Engine image content ID"
    sql = "SELECT current_setting('server_version') || '|' || COALESCE(NULLIF(substring(version() FROM ' on ([^,]+)'), ''), 'unavailable');"
    res = subprocess.run([runtime, "exec", "-i", container_name, "psql", "-U", user, "-d", database, "-X", "-tAc", sql], capture_output=True, text=True, check=True)
    ver, abi = res.stdout.strip().split("|", 1)
    clients = set()
    for binary in ("pg_dump", "pg_restore", "psql"):
        out = subprocess.run([runtime, "exec", "-i", container_name, f"/usr/bin/{binary}", "--version"], capture_output=True, text=True, check=True).stdout
        parsed = parse_client_version(out.splitlines()[0] if out else "")
        assert parsed is not None, f"could not parse exact {binary} version from {out!r}"
        clients.add(parsed)
    return TrustedArtifactQualification(
        allowed_server_versions=(ver.strip(),), allowed_os_arch_abis=(abi.strip(),), allowed_engine_image_ids=(image_id,),
        allowed_client_majors=tuple(sorted({int(c.split(".", 1)[0]) for c in clients})), allowed_client_versions=tuple(sorted(clients)),
        template_baselines=((image_id, template_baseline_sha256),),
    )


def probe_live_extension_digests(container_name: str, ext_name: str, ext_version: str, *, runtime: str = "docker") -> tuple[str, str, str | None]:
    res = subprocess.run([runtime, "exec", "-i", container_name, "sh", "-euc", _EXT_ARTIFACT_PROBE_SH, "sh", ext_name, ext_version], capture_output=True, text=True, check=True)
    c_sha, s_sha, l_sha = (part.strip().lower() for part in res.stdout.strip().split(":", 2))
    return c_sha, s_sha, (None if l_sha == "none" else l_sha)


def adr0077_pgvector_extension_policy(
    *, owner: str = "repomap", reader_role: str = "candidate_fixture_reader", writer_role: str = "candidate_fixture_enrichment",
    exact_versions: tuple[str, ...] = ("0.8.7",), policy_id: str = "adr0077-disposable-pgvector-v1",
    artifact_qualification: TrustedArtifactQualification | None = None, container_name: str | None = None,
    template_baseline_sha256: str | None = None, replay_bounds: ExtensionReplayBounds = DEFAULT_REPLAY_BOUNDS,
) -> TrustedExtensionRestorePolicy:
    """Build a trusted D9-B policy for the ADR 0077 disposable pgvector fixture."""
    qual, c_sha, s_sha = artifact_qualification, UNIT_VECTOR_CONTROL_SHA256, UNIT_VECTOR_SCRIPT_SHA256
    l_sha: str | None = UNIT_VECTOR_LIBRARY_SHA256
    if container_name is not None:
        if qual is None:
            assert template_baseline_sha256 is not None, "a separately established template1 reference is required"
            qual = probe_live_container_qualification(container_name, user=owner, template_baseline_sha256=template_baseline_sha256)
        c_sha, s_sha, l_sha = probe_live_extension_digests(container_name, "vector", exact_versions[0])
    opt_cap = TrustedOptionalCapabilityContract(
        capability_id="adr0077-semantic-candidates", experimental_context="adr0077-disposable-pgvector",
        extension_schema="repomap_vector", application_schemas=("repomap_enrichment",),
        enrichment_reader_role=reader_role, enrichment_writer_role=writer_role,
    )
    vec_rule = TrustedExtensionRule(
        name="vector", allowed_database_roles=("graph",), exact_versions=exact_versions, required_schema="repomap_vector",
        allowed_owners=(owner,), declaration_identity="adr0077:vector", ownership_classification="unclassified",
        experimental_context="adr0077-disposable-pgvector", relocatable=True, allowed_dependent_schemas=("repomap_enrichment",),
        readiness_probe_sql="SELECT '[1,2,3]'::repomap_vector.vector OPERATOR(repomap_vector.<=>) '[1,2,3]'::repomap_vector.vector;",
        control_sha256=c_sha, script_sha256=s_sha, library_sha256=l_sha, optional_capability=opt_cap,
    )
    return TrustedExtensionRestorePolicy(
        policy_id=policy_id, allow_extension_v2=True, artifact_qualification=qual or DEFAULT_ARTIFACT_QUALIFICATION,
        extensions=(vec_rule,), replay_bounds=replay_bounds,
    )


def synthetic_multilevel_extension_policy(
    *, owner: str = "repomap", alpha_versions: tuple[str, ...] = ("1.0",), alpha_default_version: str = "1.1",
    include_beta: bool = True, include_gamma: bool = True, include_cfg: bool = False, policy_id: str = "synthetic-multilevel-v1",
    artifact_qualification: TrustedArtifactQualification | None = None, database_roles: tuple[str, ...] = ("graph",),
    replay_bounds: ExtensionReplayBounds = DEFAULT_REPLAY_BOUNDS,
) -> TrustedExtensionRestorePolicy:
    """Build a trusted D9-B policy for synthetic SQL-only extensions."""
    alpha_script_ver = alpha_versions[0] if f"ext_alpha--{alpha_versions[0]}.sql" in SYNTHETIC_EXT_FILES else "1.0"
    common: dict[str, Any] = {"allowed_database_roles": database_roles, "allowed_owners": (owner,), "relocatable": False}
    specs: list[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], str, str, str]] = [
        ("ext_alpha", alpha_versions, (), ("public", "app_ext", "ext_beta_s", "ext_gamma_s"), "SELECT ext_alpha_s.alpha_version();",
         hashlib.sha256(_alpha_control_text(alpha_default_version).encode("utf-8")).hexdigest(), synthetic_ext_sha256(f"ext_alpha--{alpha_script_ver}.sql")),
    ]
    if include_beta:
        specs.append(("ext_beta", ("1.0",), ("ext_alpha",), ("public", "app_ext", "ext_gamma_s"), "SELECT ext_beta_s.beta_probe();",
                      synthetic_ext_sha256("ext_beta.control"), synthetic_ext_sha256("ext_beta--1.0.sql")))
    if include_gamma:
        specs.append(("ext_gamma", ("1.0",), ("ext_alpha", "ext_beta"), ("public", "app_ext"), "SELECT ext_gamma_s.gamma_probe();",
                      synthetic_ext_sha256("ext_gamma.control"), synthetic_ext_sha256("ext_gamma--1.0.sql")))
    if include_cfg:
        specs.append(("ext_cfg", ("1.0",), (), ("public", "app_ext"), "SELECT 1;", synthetic_ext_sha256("ext_cfg.control"), synthetic_ext_sha256("ext_cfg--1.0.sql")))
    rules = tuple(
        TrustedExtensionRule(
            name=name, exact_versions=versions, required_schema=f"{name}_s", declaration_identity=f"test:{name}", prerequisites=prereqs,
            allowed_dependent_schemas=dep_schemas, readiness_probe_sql=probe, control_sha256=ctrl, script_sha256=script, **common,
        )
        for name, versions, prereqs, dep_schemas, probe, ctrl, script in specs
    )
    return TrustedExtensionRestorePolicy(
        policy_id=policy_id, allow_extension_v2=True, artifact_qualification=artifact_qualification or DEFAULT_ARTIFACT_QUALIFICATION,
        extensions=rules, replay_bounds=replay_bounds,
    )


def _exec_root(runner: Any, runtime: str, container: str, script: str, *args: str) -> Any:
    return runner([runtime, "exec", "-i", "-u", "root", container, "sh", "-uc", script, "sh", *args], capture_output=True)


_INSTALL_ONE_SH = (
    'f="$(pg_config --sharedir)/extension/$1"; '
    'if ! ( set -C; umask 022; cat > "$f" ) 2>/dev/null; then cat >/dev/null; echo COLLISION; exit 0; fi; '
    'echo "CREATED $(stat -c %d:%i "$f")"'
)
_REMOVE_OWNED_SH = (
    'f="$(pg_config --sharedir)/extension/$1"; [ -e "$f" ] || [ -L "$f" ] || { echo ABSENT; exit 0; }; '
    '[ ! -L "$f" ] && [ "$(stat -c %d:%i "$f")" = "$2" ] || { echo REPLACED; exit 0; }; rm -f "$f" && echo REMOVED'
)


@contextmanager
def installed_synthetic_extensions(
    container_runtime: str, container_name: str, *, runner: Any = subprocess.run, alpha_default_version: str = "1.1",
    include_alpha_1_0: bool = True, receipts: list[tuple[str, str]] | None = None,
) -> Iterator[None]:
    """Install synthetic SQL-only extension files without touching preexisting paths; remove only proven-owned files."""
    files = dict(SYNTHETIC_EXT_FILES)
    files["ext_alpha.control"] = _alpha_control_text(alpha_default_version)
    if not include_alpha_1_0:
        files.pop("ext_alpha--1.0.sql", None)
    owned: list[tuple[str, str]] = []
    outcomes = receipts if receipts is not None else []
    try:
        for fname, body in files.items():
            res = runner([container_runtime, "exec", "-i", "-u", "root", container_name, "sh", "-uc", _INSTALL_ONE_SH, "sh", fname], input=body.encode("utf-8"), capture_output=True)
            out = res.stdout.decode("utf-8", errors="replace").strip()
            if res.returncode != 0 or not out.startswith("CREATED "):
                raise RuntimeError(f"synthetic extension file {fname!r} was not exclusively created: {out or res.returncode!r}")
            owned.append((fname, out.split(" ", 1)[1]))
        yield
    finally:
        primary = sys.exc_info()[1]
        failures = []
        for fname, ident in reversed(owned):
            out = _exec_root(runner, container_runtime, container_name, _REMOVE_OWNED_SH, fname, ident).stdout.decode("utf-8", errors="replace").strip()
            outcomes.append((fname, out or "UNKNOWN"))
            if out not in ("REMOVED", "ABSENT"):
                failures.append(f"{fname}:{out or 'UNKNOWN'}")
        if failures and primary is not None:
            primary.add_note(f"synthetic extension cleanup incomplete: {', '.join(failures)}")
        elif failures:
            raise RuntimeError(f"synthetic extension cleanup incomplete: {', '.join(failures)}")


def tamper_extension_script_in_container(container_runtime: str, container_name: str, filename: str, *, runner: Any = subprocess.run) -> None:
    """Append in place (same inode) to alter an owned synthetic artifact's SHA-256."""
    script = 'printf "\\n-- tampered\\n" >> "$(pg_config --sharedir)/extension/$1"'
    res = _exec_root(runner, container_runtime, container_name, script, filename)
    if res.returncode != 0:
        raise RuntimeError(f"tamper of {filename!r} failed")


def hide_extension_script_in_container(container_runtime: str, container_name: str, filename: str, *, runner: Any = subprocess.run) -> Any:
    """Rename an owned artifact aside (same inode) and return a restorer, so cleanup identity is preserved."""
    script = 'd="$(pg_config --sharedir)/extension"; mv "$d/$1" "$d/.$1.hidden"'
    if _exec_root(runner, container_runtime, container_name, script, filename).returncode != 0:
        raise RuntimeError(f"hiding {filename!r} failed")

    def restore() -> None:
        back = 'd="$(pg_config --sharedir)/extension"; mv "$d/.$1.hidden" "$d/$1"'
        if _exec_root(runner, container_runtime, container_name, back, filename).returncode != 0:
            raise RuntimeError(f"restoring {filename!r} failed")

    return restore


def control_extension_policy(owner: str, qualification: TrustedArtifactQualification) -> TrustedExtensionRestorePolicy:
    return synthetic_multilevel_extension_policy(
        owner=owner, include_beta=False, include_gamma=False, policy_id="synthetic-control-v1",
        artifact_qualification=qualification, database_roles=("control",),
    )
