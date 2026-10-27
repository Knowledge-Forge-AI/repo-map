"""ADR 0098 component probes for PostgreSQL base /usr/local/include and fail-closed rmdir."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import shlex
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from repomap_kg.runtime import commands, release_manifest
from repomap_kg.runtime.release import (
    POSTGRES_RELEASE_IMAGE, RELEASE_FINAL_PACKAGE_CHECK_PY, RELEASE_FINAL_PROBE_PY, RELEASE_PROBE_HELPERS_PY,
)
from repomap_test_support import d12_core_image as d12
from repomap_test_support.d12_image_probes import _tmpfs
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_run import active_resource_run
from repomap_test_support.resource_test_images import ensure_canonical_runtime_image

REPO_ROOT = Path(__file__).resolve().parents[6]
_DAEMON_ARCH_TO_PLATFORM = {
    "aarch64": "linux/arm64", "arm64": "linux/arm64", "x86_64": "linux/amd64", "amd64": "linux/amd64",
}
_BUDGET_KEYS = (
    "managed_system_candidate_image_build_count", "product_or_build_profile_build_count",
    "unmanaged_build_count", "unmanaged_pull_count",
)
_POSTGRES_INCLUDE_OBSERVE_SH = (
    "set -eu\n"
    "arch=$(dpkg --print-architecture); machine=$(uname -m)\n"
    "test -d /usr/local; test ! -L /usr/local\n"
    "test -e /usr/local/include; test -d /usr/local/include; test ! -L /usr/local/include\n"
    "kind=$(stat -c '%F' /usr/local/include); test \"$kind\" = 'directory'\n"
    "found=$(find /usr/local/include -mindepth 1 -maxdepth 1); test -z \"$found\"\n"
    "printf '{\"arch\":\"%s\",\"machine\":\"%s\",\"path\":\"/usr/local/include\","
    "\"kind\":\"%s\",\"is_symlink\":false,\"is_dir\":true,\"entry_count\":0,\"empty\":true}\\n' "
    "\"$arch\" \"$machine\" \"$kind\"\n"
)
_MECHANISM_BODY_PY = """
import shutil, subprocess, uuid
_CODE = compile(_HEADER_OPERAND_SRC, '<release_final_probe_header_operand>', 'eval')
def _op() -> bool: return bool(eval(_CODE, {'os': os}))
def _rmdir() -> int:
    return subprocess.run(list(_RMDIR_ARGV), capture_output=True, text=True, check=False).returncode
def _snap(root: pathlib.Path) -> dict[str, tuple[object, ...]]:
    out: dict[str, tuple[object, ...]] = {}
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink(): out[rel] = ('symlink', os.readlink(p), p.lstat().st_mode)
        elif p.is_dir(): out[rel] = ('dir', p.stat().st_mode)
        elif p.is_file():
            raw = p.read_bytes()
            out[rel] = ('file', hashlib.sha256(raw).hexdigest(), len(raw), p.stat().st_mode)
        else: raise RuntimeError(f'unexpected entry kind: {rel}')
    return out
inc = pathlib.Path('/usr/local/include')
uid = f'{os.getpid()}-{uuid.uuid4().hex[:8]}'
retained = pathlib.Path(f'/usr/local/.include.ci71-retained-{uid}')
sym_dir = pathlib.Path(f'/usr/local/.include.ci71-target-{uid}')
dangling = pathlib.Path(f'/usr/local/.include.ci71-dangling-{uid}')
def _clean_fixture(fx: dict[str, object]) -> None:
    kind = fx['kind']
    if kind == 'empty_dir':
        assert inc.is_dir() and not inc.is_symlink() and os.listdir(inc) == []
        os.rmdir(inc)
    elif kind == 'nonempty_header_dir':
        hname = str(fx['header_name']); hp = inc / hname
        assert inc.is_dir() and not inc.is_symlink() and os.listdir(inc) == [hname]
        assert hp.is_file() and not hp.is_symlink()
        assert hashlib.sha256(hp.read_bytes()).hexdigest() == fx['header_sha256']
        os.unlink(hp); os.rmdir(inc)
    elif kind == 'directory_symlink':
        assert inc.is_symlink() and os.readlink(inc) == fx['target']
        os.unlink(inc)
        assert sym_dir.is_dir() and not sym_dir.is_symlink() and os.listdir(sym_dir) == []
        os.rmdir(sym_dir)
    elif kind == 'dangling_symlink':
        assert inc.is_symlink() and os.readlink(inc) == fx['target']
        os.unlink(inc)
    elif kind == 'regular_file':
        assert inc.is_file() and not inc.is_symlink()
        assert hashlib.sha256(inc.read_bytes()).hexdigest() == fx['sha256']
        os.unlink(inc)
    else: raise RuntimeError(f'unknown controlled fixture: {kind!r}')
had_orig = os.path.lexists(inc)
assert not os.path.lexists(retained) and (not had_orig or (inc.is_dir() and not inc.is_symlink()))
orig_snap = _snap(inc) if had_orig else {}
if had_orig: shutil.move(inc, retained)
active: dict[str, object] | None = None
try:
    active = {'kind': 'empty_dir'}; os.mkdir(inc, 0o755)
    assert os.path.exists('/usr/local/include') is True and _op() is False
    empty_rc = _rmdir(); assert empty_rc == 0 and not os.path.lexists(inc); active = None
    assert os.path.exists('/usr/local/include') is False and _op() is True
    missing_rc = _rmdir(); assert missing_rc != 0 and not os.path.lexists(inc) and _op() is True
    h_name = 'psycopg_ci71_public.h'
    h_bytes = b'/* controlled public header */\\n#define CI71_PUBLIC_HEADER 1\\n'
    h_sha = hashlib.sha256(h_bytes).hexdigest()
    active = {'kind': 'nonempty_header_dir', 'header_name': h_name, 'header_sha256': h_sha}
    os.mkdir(inc, 0o755); (inc / h_name).write_bytes(h_bytes)
    assert os.path.exists('/usr/local/include') is True and _op() is False
    nonempty_rc = _rmdir(); assert nonempty_rc != 0 and inc.is_dir() and not inc.is_symlink()
    assert (inc / h_name).read_bytes() == h_bytes and _op() is False; _clean_fixture(active)
    active = {'kind': 'directory_symlink', 'target': str(sym_dir)}
    os.mkdir(sym_dir, 0o755); os.symlink(sym_dir, inc)
    assert os.path.exists('/usr/local/include') is True and _op() is False
    sym_rc = _rmdir(); assert sym_rc != 0 and inc.is_symlink() and os.readlink(inc) == str(sym_dir)
    assert sym_dir.is_dir() and os.path.exists('/usr/local/include') is True and _op() is False
    _clean_fixture(active); assert not os.path.lexists(dangling)
    active = {'kind': 'dangling_symlink', 'target': str(dangling)}; os.symlink(dangling, inc)
    assert inc.is_symlink() and os.path.lexists('/usr/local/include') is True
    assert os.path.exists('/usr/local/include') is False and _op() is True
    dang_rc = _rmdir(); assert dang_rc != 0 and inc.is_symlink() and os.readlink(inc) == str(dangling)
    assert not os.path.lexists(dangling) and os.path.exists('/usr/local/include') is False and _op() is True
    _clean_fixture(active)
    reg_bytes = b'controlled ordinary file at /usr/local/include\\n'
    active = {'kind': 'regular_file', 'sha256': hashlib.sha256(reg_bytes).hexdigest()}
    inc.write_bytes(reg_bytes); assert inc.is_file() and not inc.is_symlink()
    assert os.path.exists('/usr/local/include') is True and _op() is False
    reg_rc = _rmdir(); assert reg_rc != 0 and inc.is_file() and inc.read_bytes() == reg_bytes and _op() is False
finally:
    if active is not None: _clean_fixture(active); active = None
    assert not os.path.lexists(inc) and not os.path.lexists(sym_dir) and not os.path.lexists(dangling)
    if had_orig and os.path.lexists(retained): shutil.move(retained, inc)
assert not os.path.lexists(retained) and (
    (inc.is_dir() and not inc.is_symlink() and _snap(inc) == orig_snap) if had_orig else not os.path.lexists(inc)
)
print('D12_RUNTIME_INCLUDE_MECHANISM=' + json.dumps({
    'scope': 'python_runtime_header_operand_and_rmdir_mechanism_only',
    'build_only_modules_proved_absent': False, 'full_probe_or_assembled_image_proved': False,
    'selected_rmdir_command': list(_RMDIR_ARGV), 'selected_header_operand': _HEADER_OPERAND_SRC,
    'original_include_entries': len(orig_snap), 'original_include_restored': True,
    'fixtures': {
        'empty_dir': {'before_operand': False, 'rmdir_rc': empty_rc, 'after_operand': True},
        'missing_path': {'rmdir_rc': missing_rc, 'operand': True},
        'nonempty_header_dir': {'rmdir_rc': nonempty_rc, 'bytes_preserved': True, 'operand': False},
        'directory_symlink': {'rmdir_rc': sym_rc, 'symlink_preserved': True, 'os_path_exists': True, 'operand': False},
        'dangling_symlink': {'rmdir_rc': dang_rc, 'symlink_preserved': True, 'os_path_exists': False, 'operand': True},
        'regular_file': {'rmdir_rc': reg_rc, 'bytes_preserved': True, 'operand': False},
    },
}, sort_keys=True))
"""


def _verify_postgres_base_config(client: Any, platform: str) -> dict[str, object]:
    bases = d12.verify_bases(client, platform, (POSTGRES_RELEASE_IMAGE,))
    pg_base = dict(bases[POSTGRES_RELEASE_IMAGE])
    if pg_base.get("platform") != platform or pg_base.get("config_digest_verified") is not True:
        raise d12.D12ProfileError(f"PostgreSQL base config digest verification unavailable for {platform}: {pg_base}")
    return pg_base


def _select_runtime_rmdir_command(dockerfile_text: str) -> tuple[str, ...]:
    marker = f"FROM {POSTGRES_RELEASE_IMAGE} AS runtime\n"
    if dockerfile_text.count(marker) != 1:
        raise ValueError("expected exactly one PostgreSQL runtime stage in rendered Dockerfile")
    before_runtime, runtime_stage = dockerfile_text.split(marker, 1)
    if "rmdir" in before_runtime:
        raise ValueError("unexpected rmdir in builder stages before runtime stage")
    rmdir_lines = [ln.strip() for ln in runtime_stage.splitlines() if ln.strip().startswith("RUN ") and "rmdir" in ln]
    if len(rmdir_lines) != 1:
        raise ValueError(f"expected one runtime RUN rmdir instruction, found {len(rmdir_lines)}")
    run_line = rmdir_lines[0]
    if f"RUN ldconfig\n{run_line}\n" not in runtime_stage:
        raise ValueError("runtime rmdir must immediately follow RUN ldconfig")
    first_python = 'RUN package_root="$(python -c '
    if first_python not in runtime_stage or runtime_stage.index(run_line) >= runtime_stage.index(first_python):
        raise ValueError("runtime rmdir must precede the first runtime Python invocation")
    raw_cmd = run_line.removeprefix("RUN ").strip()
    if any(sep in raw_cmd for sep in ("&&", "||", ";", "|")):
        raise ValueError(f"runtime rmdir must not chain or suppress exit status: {raw_cmd!r}")
    argv = tuple(shlex.split(raw_cmd))
    if argv != ("rmdir", "/usr/local/include") or any(arg.startswith("-") for arg in argv):
        raise ValueError(f"unexpected runtime rmdir command arguments: {argv!r}")
    return argv


def _select_final_probe_header_operand(probe_source: str = RELEASE_FINAL_PROBE_PY) -> tuple[str, str]:
    prefix = RELEASE_PROBE_HELPERS_PY + RELEASE_FINAL_PACKAGE_CHECK_PY
    if not probe_source.startswith(prefix):
        raise ValueError("RELEASE_FINAL_PROBE_PY must begin with helper and package-check prefixes")
    prefix_len = len(ast.parse(prefix).body)
    tree = ast.parse(probe_source)
    final_asserts = [
        s for s in tree.body
        if isinstance(s, ast.Assert) and ("build_only" in ast.unparse(s) or "/usr/local/include" in ast.unparse(s))
    ]
    if len(final_asserts) != 1 or len(tree.body) <= prefix_len + 1 or final_asserts[0] is not tree.body[-2]:
        raise ValueError("missing or ambiguous final build_only/include compound assert")
    os_imports: list[tuple[int, ast.Import]] = []
    for idx, stmt in enumerate(tree.body):
        if isinstance(stmt, ast.ImportFrom) and "os" in {a.asname or a.name for a in stmt.names}:
            raise ValueError("os must be bound by a plain top-level stdlib import")
        if isinstance(stmt, ast.Import) and "os" in {a.asname or a.name.split(".")[0] for a in stmt.names}:
            modules = [a.name for a in stmt.names]
            if idx >= len(tree.body) - 2 or any(
                m == "psycopg" or m.startswith("psycopg.") or m.split(".")[0] not in sys.stdlib_module_names
                for m in modules
            ):
                raise ValueError(f"invalid or non-stdlib os import statement: {modules!r}")
            os_imports.append((idx, stmt))
    body_os = [stmt for idx, stmt in os_imports if idx >= prefix_len]
    if not os_imports or len(body_os) != 1 or os_imports[-1][1] is not body_os[0]:
        raise ValueError(f"expected one final-body stdlib import binding os, found {len(body_os)}")
    selected = os_imports[-1][1]
    if not {"hashlib", "json", "os", "pathlib"} <= {a.asname or a.name.split(".")[0] for a in selected.names}:
        raise ValueError("selected os import missing required stdlib bindings")
    test_expr = final_asserts[0].test
    if not (isinstance(test_expr, ast.BoolOp) and isinstance(test_expr.op, ast.And) and len(test_expr.values) == 2):
        raise ValueError("final absence assert must be a two-conjunct boolean And")
    left, right = test_expr.values
    if (
        not isinstance(left, ast.UnaryOp) or not isinstance(left.op, ast.Not)
        or not isinstance(left.operand, ast.ListComp)
        or ast.unparse(left) != "not [m for m in build_only if iu.find_spec(m)]"
    ):
        raise ValueError("unexpected build_only module conjunct in final absence assert")
    if not (isinstance(right, ast.UnaryOp) and isinstance(right.op, ast.Not)):
        raise ValueError("header operand must be a unary Not expression")
    call = right.operand
    if (
        not isinstance(call, ast.Call) or call.keywords or len(call.args) != 1
        or not isinstance(call.args[0], ast.Constant) or call.args[0].value != "/usr/local/include"
        or not isinstance(call.func, ast.Attribute) or call.func.attr != "exists"
        or not isinstance(call.func.value, ast.Attribute) or call.func.value.attr != "path"
        or not isinstance(call.func.value.value, ast.Name) or call.func.value.value.id != "os"
    ):
        raise ValueError("header operand must be not os.path.exists('/usr/local/include')")
    stdlib_src = ast.get_source_segment(probe_source, selected) or ast.unparse(selected)
    operand_src = ast.get_source_segment(probe_source, right)
    if (
        operand_src != 'not os.path.exists("/usr/local/include")'
        or ast.unparse(ast.parse(operand_src, mode="eval").body) != ast.unparse(right)
    ):
        raise ValueError("header operand source segment mismatch")
    return stdlib_src, operand_src


def test_postgres_release_base_has_empty_real_usr_local_include_directory() -> None:
    boundary = d12.locate_run_boundary()
    run = active_resource_run()
    assert run is not None, "PostgreSQL base include hygiene probe requires active resource run"
    client = boundary.client
    budget_before = boundary.projection()
    daemon_arch = str(client.info().get("Architecture") or "")
    native_platform = _DAEMON_ARCH_TO_PLATFORM.get(daemon_arch)
    assert native_platform is not None and native_platform in d12.PLATFORMS, daemon_arch
    assert d12.platform_availability(native_platform, daemon_arch, ()) == {
        "platform": native_platform, "execution": "native", "builder_platforms": [],
    }
    pg_digest = POSTGRES_RELEASE_IMAGE.split("@", 1)[1]
    fallback_attrs = {
        "Os": "linux", "Architecture": native_platform.split("/", 1)[1],
        "Id": pg_digest, "RepoDigests": [f"postgres@{pg_digest}"],
    }
    fallback_client = SimpleNamespace(
        images=SimpleNamespace(get=lambda _ref: SimpleNamespace(attrs=fallback_attrs))
    )
    fallback_verified = d12.verify_bases(fallback_client, native_platform, (POSTGRES_RELEASE_IMAGE,))
    assert fallback_verified[POSTGRES_RELEASE_IMAGE]["config_digest_verified"] is False
    with pytest.raises(d12.D12ProfileError, match="config digest verification unavailable"):
        _verify_postgres_base_config(fallback_client, native_platform)

    pg_base = _verify_postgres_base_config(client, native_platform)
    assert pg_base["config_digest_verified"] is True
    assert pg_base["id"] == d12.BASE_CONFIG_DIGESTS[pg_digest][native_platform]
    tmpfs_map = _tmpfs(client, POSTGRES_RELEASE_IMAGE)
    assert tmpfs_map and "/var/lib/postgresql/data" in tmpfs_map, tmpfs_map

    owner = CurrentRunDockerContainers(run, client)
    cid = owner.create(
        POSTGRES_RELEASE_IMAGE, ["-c", _POSTGRES_INCLUDE_OBSERVE_SH],
        role="d12-postgres-base-include-hygiene", entrypoint=["sh"],
        network_mode="none", read_only=True, tmpfs=tmpfs_map, platform=native_platform,
    )
    try:
        container = client.containers.get(cid)
        assert container.attrs.get("Image") == pg_base["id"]
        assert container.attrs.get("HostConfig", {}).get("ReadonlyRootfs") is True
        assert container.attrs.get("HostConfig", {}).get("NetworkMode") == "none"
        assert container.attrs.get("Config", {}).get("Entrypoint") == ["sh"]
        mounts = [m for m in container.attrs.get("Mounts") or [] if m.get("Type") in ("bind", "volume")]
        assert not mounts, mounts
        container.start()
        status = container.wait(timeout=120).get("StatusCode", 1)
        output = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
        errors = container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
    finally:
        owner.cleanup(cid)
    owner.verify_baseline()
    budget_after = boundary.projection()
    assert budget_after == budget_before and [budget_after[k] for k in _BUDGET_KEYS] == [0, 0, 0, 0]
    assert status == 0, f"postgres base include observation failed ({status}): {errors[-2000:]}"
    obs = json.loads(output.splitlines()[-1])
    assert obs["arch"] == native_platform.split("/", 1)[1]
    assert obs["path"] == "/usr/local/include" and obs["kind"] == "directory"
    assert obs["is_dir"] is True and obs["is_symlink"] is False
    assert obs["empty"] is True and obs["entry_count"] == 0
    report = {
        "scope": "postgres_base_component_only", "platform": native_platform, "execution": "native",
        "config_digest_verified": True, "rootfs_read_only": True, "network_mode": "none",
        "tmpfs_paths": sorted(tmpfs_map), "amd64_qualified_from_arm64": False,
        "assembled_image_qualified": False, "gates_main_system_builder": False, "observation": obs,
    }
    print("D12_POSTGRES_BASE_INCLUDE_HYGIENE=" + json.dumps(report, sort_keys=True))


def test_dependency_only_runtime_rmdir_and_header_operand_fail_closed_mechanism() -> None:
    rendered_candidate = d12.recipe_text()
    assert rendered_candidate == commands.render_server_dockerfile(
        manifest=release_manifest.D12_CANDIDATE_PACKAGE_MANIFEST,
        libpq_version=release_manifest.D12_CANDIDATE_LIBPQ_VERSION,
    )
    rmdir_argv = _select_runtime_rmdir_command(rendered_candidate)
    assert rmdir_argv == ("rmdir", "/usr/local/include")
    stdlib_import_src, header_operand_src = _select_final_probe_header_operand(RELEASE_FINAL_PROBE_PY)
    assert "psycopg" not in stdlib_import_src and "hashlib" in stdlib_import_src and "pathlib" in stdlib_import_src
    assert header_operand_src == 'not os.path.exists("/usr/local/include")'

    run_rmdir = "RUN rmdir /usr/local/include\n"
    for bad_df in (
        rendered_candidate.replace(f"FROM {POSTGRES_RELEASE_IMAGE} AS runtime\n", "", 1),
        rendered_candidate.replace(run_rmdir, "", 1),
        rendered_candidate.replace(run_rmdir, "RUN rmdir -p /usr/local/include\n", 1),
        rendered_candidate.replace(run_rmdir, "RUN rmdir /usr/local/include || true\n", 1),
        rendered_candidate.replace(f"RUN ldconfig\n{run_rmdir}", f"{run_rmdir}RUN ldconfig\n", 1),
    ):
        with pytest.raises(ValueError):
            _select_runtime_rmdir_command(bad_df)

    and_operand = ' and not os.path.exists("/usr/local/include")'
    for bad_probe, err_match in (
        (RELEASE_FINAL_PROBE_PY.removeprefix(RELEASE_PROBE_HELPERS_PY), "helper and package-check prefixes"),
        (RELEASE_FINAL_PROBE_PY.replace("import hashlib, ", "import hashlib, psycopg, ", 1), "non-stdlib os import"),
        (RELEASE_FINAL_PROBE_PY.replace(", os, pathlib, sys", ", pathlib, sys", 1), "expected one final-body stdlib"),
        (RELEASE_FINAL_PROBE_PY.replace("import psycopg\n", "import os\nimport psycopg\n", 1), "final-body stdlib"),
        (RELEASE_FINAL_PROBE_PY + 'assert not os.path.exists("/usr/local/include")\n', "missing or ambiguous final"),
        (RELEASE_FINAL_PROBE_PY.replace(and_operand, "", 1), "two-conjunct boolean And"),
        (RELEASE_FINAL_PROBE_PY.replace(and_operand, ' or not os.path.exists("/usr/local/include")', 1), "boolean And"),
        (RELEASE_FINAL_PROBE_PY.replace("os.path.exists(", "os.path.isdir(", 1), "header operand must be"),
        (RELEASE_FINAL_PROBE_PY.replace('"/usr/local/include"', '"/usr/local"', 1), "header operand must be"),
    ):
        with pytest.raises(ValueError, match=err_match):
            _select_final_probe_header_operand(bad_probe)

    boundary = d12.locate_run_boundary()
    run = active_resource_run()
    assert run is not None, "runtime rmdir mechanism probe requires active resource run"
    client = boundary.client
    native_platform = _DAEMON_ARCH_TO_PLATFORM[str(client.info().get("Architecture") or "")]
    image_id = ensure_canonical_runtime_image(
        repo_root=REPO_ROOT, resource_run=run, client=client, boundary=boundary
    )
    owner = CurrentRunDockerContainers(run, client)
    mechanism_script = (
        f"{stdlib_import_src}\n_RMDIR_ARGV = {rmdir_argv!r}\n"
        f"_HEADER_OPERAND_SRC = {header_operand_src!r}\n{_MECHANISM_BODY_PY}"
    )
    mech_cid = owner.create(
        image_id, ["-I", "-B", "-c", mechanism_script],
        role="d12-runtime-include-mechanism-probe", entrypoint=["python"], network_mode="none",
    )
    try:
        mech_container = client.containers.get(mech_cid)
        mech_container.start()
        mech_status = mech_container.wait(timeout=120).get("StatusCode", 1)
        mech_stdout = mech_container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
        mech_stderr = mech_container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
    finally:
        owner.cleanup(mech_cid)
    owner.verify_baseline()
    assert [boundary.projection()[k] for k in _BUDGET_KEYS] == [0, 0, 0, 0]
    assert mech_status == 0, f"mechanism probe failed ({mech_status}): {mech_stderr[-2000:]}"
    mech_line = mech_stdout.splitlines()[-1]
    assert mech_line.startswith("D12_RUNTIME_INCLUDE_MECHANISM="), mech_line
    mech_report = json.loads(mech_line.removeprefix("D12_RUNTIME_INCLUDE_MECHANISM="))
    mech_report["platform"] = native_platform
    print("D12_RUNTIME_INCLUDE_MECHANISM=" + json.dumps(mech_report, sort_keys=True))
    assert mech_report["scope"] == "python_runtime_header_operand_and_rmdir_mechanism_only"
    assert mech_report["build_only_modules_proved_absent"] is False
    assert mech_report["full_probe_or_assembled_image_proved"] is False
    assert mech_report["selected_rmdir_command"] == ["rmdir", "/usr/local/include"]
    assert mech_report["selected_header_operand"] == 'not os.path.exists("/usr/local/include")'
    assert mech_report["original_include_restored"] is True and mech_report["original_include_entries"] >= 0
    fx = mech_report["fixtures"]
    assert fx["empty_dir"] == {"before_operand": False, "rmdir_rc": 0, "after_operand": True}
    assert fx["missing_path"]["rmdir_rc"] != 0 and fx["missing_path"]["operand"] is True
    assert fx["nonempty_header_dir"]["rmdir_rc"] != 0 and fx["nonempty_header_dir"]["bytes_preserved"] is True
    assert fx["nonempty_header_dir"]["operand"] is False and fx["regular_file"]["operand"] is False
    assert fx["directory_symlink"]["rmdir_rc"] != 0 and fx["directory_symlink"]["os_path_exists"] is True
    assert fx["directory_symlink"]["operand"] is False and fx["directory_symlink"]["symlink_preserved"] is True
    assert fx["dangling_symlink"]["rmdir_rc"] != 0 and fx["dangling_symlink"]["os_path_exists"] is False
    assert fx["dangling_symlink"]["operand"] is True and fx["dangling_symlink"]["symlink_preserved"] is True
    assert fx["regular_file"]["rmdir_rc"] != 0 and fx["regular_file"]["bytes_preserved"] is True
