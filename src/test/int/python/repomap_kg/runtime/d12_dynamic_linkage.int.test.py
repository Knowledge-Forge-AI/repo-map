"""ADR 0089 D2/D6 and ADR 0097 probes of the dependency-only Python 3.12 image.

The repository-owned ``TestImageManager`` materializes its canonical
dependency-only image (a managed, non-ledger test-runtime cache, never a D12
candidate build). That image builds psycopg-c 3.3.6 from the hash-bound sdist
against the base distribution's ``libpq-dev`` and keeps only its ``libpq5``.
Network-less probe containers run this repository's stdlib linkage, package
classifier, and single-process ``/usr/local`` linker-cache/missing-SONAME
mechanism checks. Passing proves the C implementation, header/runtime
equality, ``DT_NEEDED`` dynamic linkage, single loaded/verified ``dpkg``-owned
libpq, and ``ldconfig`` cache recovery of this test image only; it is not
release-image or assembled-product evidence, whose libpq and loader
configuration belong to the PostgreSQL base.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

import pytest

from repomap_kg.runtime import python_payload
from repomap_kg.runtime.commands import PYTHON_PAYLOAD_SOURCE
from repomap_kg.runtime.release import (
    PSYCOPG_RELEASE_VERSION,
    RELEASE_FINAL_PACKAGE_CHECK_PY,
    RELEASE_FINAL_PROBE_PY,
    RELEASE_PROBE_HELPERS_PY,
)
from repomap_test_support import d12_core_image as d12
from repomap_test_support import d12_dynamic_linkage as linkage
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_run import active_resource_run
from repomap_test_support.resource_test_images import ensure_canonical_runtime_image

REPO_ROOT = Path(__file__).resolve().parents[6]
VERSIONS = "REPOMAP_DEPENDENCY_VERSIONS="
CUSTODY = "REPOMAP_APT_PREREQUISITES="


def _materialized_versions(run_root: Path, prefix: str = VERSIONS) -> dict[str, object] | None:
    """One materializer result line from this run's retained runtime evidence, if it built."""
    def strings(value: object):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    for path in sorted(run_root.glob("test-runtime-*.evidence.json")):
        for text in strings(json.loads(path.read_text(encoding="utf-8"))):
            for line in text.splitlines():
                if line.startswith(prefix):
                    return dict(json.loads(line.removeprefix(prefix)))
    return None


def test_dependency_only_runtime_links_system_libpq_dynamically() -> None:
    boundary = d12.locate_run_boundary()
    run = active_resource_run()
    assert run is not None, "the dependency-only probe requires the canonical resource run"
    client = boundary.client
    image_id = ensure_canonical_runtime_image(
        repo_root=REPO_ROOT, resource_run=run, client=client, boundary=boundary
    )
    owner = CurrentRunDockerContainers(run, client)
    identity = owner.create(
        image_id,
        ["-I", "-c", linkage.probe_source(), "probe"],
        role="d12-dynamic-linkage-probe",
        entrypoint=["python"],
        network_mode="none",
    )
    try:
        container = client.containers.get(identity)
        container.start()
        status = container.wait(timeout=300).get("StatusCode", 1)
        output = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
        errors = container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
    finally:
        owner.cleanup(identity)
    owner.verify_baseline()
    assert status == 0, f"linkage probe failed with {status}: {errors[-4000:]}"
    report = json.loads(output.splitlines()[-1])
    print("D12_DYNAMIC_LINKAGE=" + json.dumps(report, sort_keys=True))
    failures = linkage.assess(report, psycopg_version=PSYCOPG_RELEASE_VERSION)
    assert not failures, failures
    versions = _materialized_versions(Path(run.layout.run_root))
    print(VERSIONS + json.dumps(versions, sort_keys=True))
    if versions is not None:  # built in this run: build-time and loaded facts must agree
        assert versions["implementation"] == "c" and versions["libpq"] == report["libpq_runtime"], versions
        assert versions["libpq5"] == versions["libpq_dev"] == report["loaded_libpq"][0]["owner_version"], versions
        # ADR 0089: native prerequisites came only from the frozen, hash-bound manifest.
        custody = _materialized_versions(Path(run.layout.run_root), CUSTODY)
        assert custody is not None and custody["manifest_sha256"] == versions["apt_manifest_sha256"], custody
        added, executable = custody["added"], versions["pg_config_executable"]
        assert isinstance(added, list) and isinstance(executable, dict), (custody, versions)
        assert any(str(item).startswith("libpq5:") and str(item).endswith(f"={versions['libpq5']}") for item in added)
        assert versions["owners"] == {"pg_config": executable["package"], "libpq-fe.h": "libpq-dev",
                                      "libpq.so.5": "libpq5"}, versions
    loaded = report["loaded_libpq"][0]
    assert loaded["real_path"].startswith("/usr/lib/"), loaded
    assert {Path(item["path"]).name.split(".")[0] for item in report["extensions"]} >= {"_psycopg", "pq"}
    # ADR 0096 Decision 3: execute the shared final package classifier against the connected
    # dependency-only runtime image (observing its own container files) and exported SDK package
    # names under an explicitly unqualified root (proving compiler-name refusal only, not SDK
    # payload qualification). Positive native amd64 qualification of gcc-14-base on the assembled
    # PostgreSQL image remains hosted-only; arm64 runtime or compiler/dev names refuse without skip.
    assert Path("/usr/bin/dpkg-query").is_file()
    sdk_rows = [
        line.split("\t")
        for line in subprocess.run(
            ["dpkg-query", "-W", "-f=${Package}\t${db:Status-Abbrev}\n"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    ]
    sdk_package_names = [name for name, st in sdk_rows if st.startswith("ii")]
    pkg_script = (
        RELEASE_PROBE_HELPERS_PY
        + RELEASE_FINAL_PACKAGE_CHECK_PY
        + "import json\n"
        "arch = run('dpkg', '--print-architecture')[1]\n"
        "q = run('dpkg-query', '-W', '-f=${Package}\\t${db:Status-Abbrev}\\n')[1].splitlines()\n"
        "pkgs = [r.split('\\t')[0] for r in q if r.split('\\t')[1].startswith('ii')]\n"
        f"sdk_package_names = {sdk_package_names!r}\n"
        "print(json.dumps({'arch': arch, 'runtime_live': forbidden_packages(pkgs), "
        "'unqualified': forbidden_packages(pkgs, root='/nonexistent'), "
        "'with_tooling': forbidden_packages([*pkgs, 'gcc', 'binutils', 'cpp', 'libpq-dev']), "
        "'sdk_compiler_names_refused': forbidden_packages(sdk_package_names, root='/nonexistent')}))\n"
    )
    pkg_cid = owner.create(
        image_id,
        ["-I", "-c", pkg_script],
        role="d12-dynamic-linkage-pkg-probe",
        entrypoint=["python"],
        network_mode="none",
    )
    try:
        pkg_container = client.containers.get(pkg_cid)
        pkg_container.start()
        pkg_status = pkg_container.wait(timeout=120).get("StatusCode", 1)
        pkg_stdout = pkg_container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
        pkg_stderr = pkg_container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
    finally:
        owner.cleanup(pkg_cid)
    owner.verify_baseline()
    assert pkg_status == 0, f"package classifier probe failed with {pkg_status}: {pkg_stderr[-2000:]}"
    pkg_report = json.loads(pkg_stdout.splitlines()[-1])
    print("D12_PACKAGE_CLASSIFIER=" + json.dumps(pkg_report, sort_keys=True))
    assert isinstance(pkg_report["runtime_live"], list)
    assert {"gcc", "binutils", "cpp", "libpq-dev"} <= set(pkg_report["with_tooling"])
    assert {"gcc", "binutils", "cpp", "libpq-dev"} <= set(pkg_report["sdk_compiler_names_refused"])
    assert "gcc-14-base" in pkg_report["unqualified"]
    if pkg_report["arch"] != "amd64":
        assert pkg_report["runtime_live"] == ["gcc-14-base"]


def _select_final_probe_elf_block(probe_source: str = RELEASE_FINAL_PROBE_PY) -> tuple[str, str]:
    if not probe_source.startswith(RELEASE_PROBE_HELPERS_PY):
        raise ValueError("RELEASE_FINAL_PROBE_PY must begin with RELEASE_PROBE_HELPERS_PY")
    tree = ast.parse(probe_source)
    stdlib_imports: list[ast.Import] = []
    local_indices: list[int] = []
    elves_indices: list[int] = []
    for idx, stmt in enumerate(tree.body):
        if isinstance(stmt, ast.ImportFrom):
            bound = {alias.asname or alias.name for alias in stmt.names}
            if bound & {"os", "pathlib"}:
                raise ValueError("stdlib import binding os/pathlib must be a plain ast.Import")
        elif isinstance(stmt, ast.Import):
            modules = [alias.name for alias in stmt.names]
            bound = {alias.asname or alias.name.split(".")[0] for alias in stmt.names}
            if "pathlib" in bound or {"os", "pathlib"} <= bound:
                if not ({"os", "pathlib"} <= bound) or any(
                    mod == "psycopg" or mod.startswith("psycopg.")
                    or mod.split(".")[0] not in sys.stdlib_module_names
                    for mod in modules
                ):
                    raise ValueError(f"invalid or non-stdlib import in selected statement: {modules!r}")
                stdlib_imports.append(stmt)
        elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            if stmt.targets[0].id == "local":
                local_indices.append(idx)
            elif stmt.targets[0].id == "elves":
                elves_indices.append(idx)
    if len(stdlib_imports) != 1:
        raise ValueError(f"expected exactly one stdlib import binding os/pathlib, found {len(stdlib_imports)}")
    if len(local_indices) != 1 or len(elves_indices) != 1 or elves_indices[0] != local_indices[0] + 2:
        raise ValueError("missing or ambiguous local/elves assignment structure in RELEASE_FINAL_PROBE_PY")
    start = local_indices[0]
    if start + 3 >= len(tree.body):
        raise ValueError("incomplete /usr/local ELF block in RELEASE_FINAL_PROBE_PY")
    local_stmt, libpq_assert, elves_stmt, elf_loop = tree.body[start : start + 4]
    if not isinstance(libpq_assert, ast.Assert) or "LIBRARY_FILE" not in ast.unparse(libpq_assert.test):
        raise ValueError("missing private-libpq guard after local assignment")
    if not (isinstance(elf_loop, ast.For) and isinstance(elf_loop.target, ast.Name) and elf_loop.target.id == "path"):
        raise ValueError("missing dynamic-ELF loop after elves assignment")
    loop_src = ast.unparse(elf_loop)
    if not all(tok in loop_src for tok in ("elves", "dynamic", "ldd", "not found", "owner")):
        raise ValueError("dynamic-ELF loop missing required ldd/owner predicates")
    selected_nodes: list[ast.stmt] = [stdlib_imports[0], local_stmt, libpq_assert, elves_stmt, elf_loop]
    for node in ast.walk(ast.Module(body=selected_nodes, type_ignores=[])):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node is not stdlib_imports[0]:
            raise ValueError("unexpected import inside selected ELF block")
        if isinstance(node, ast.Name) and node.id == "psycopg":
            raise ValueError("psycopg reference forbidden in selected ELF block")
    stdlib_src = ast.get_source_segment(probe_source, stdlib_imports[0]) or ast.unparse(stdlib_imports[0])
    block_src = "\n".join(
        ast.get_source_segment(probe_source, stmt) or ast.unparse(stmt)
        for stmt in (local_stmt, libpq_assert, elves_stmt, elf_loop)
    )
    return stdlib_src, block_src


def test_dependency_only_runtime_linker_cache_and_missing_soname_mechanism() -> None:
    stdlib_import_src, elf_block_src = _select_final_probe_elf_block(RELEASE_FINAL_PROBE_PY)
    assert "psycopg" not in stdlib_import_src and "psycopg" not in elf_block_src
    prefix = RELEASE_PROBE_HELPERS_PY + RELEASE_FINAL_PACKAGE_CHECK_PY
    assert RELEASE_FINAL_PROBE_PY.startswith(prefix)
    with pytest.raises(ValueError):
        _select_final_probe_elf_block(RELEASE_FINAL_PROBE_PY.removeprefix(RELEASE_PROBE_HELPERS_PY))
    for bad_probe in (
        RELEASE_FINAL_PROBE_PY.replace("import hashlib, ", "import hashlib, psycopg, ", 1),
        RELEASE_FINAL_PROBE_PY.replace("local = [", "other_local = [", 1),
        RELEASE_FINAL_PROBE_PY + "\nlocal = []\n",
        RELEASE_FINAL_PROBE_PY.replace("LIBRARY_FILE.search(p.name)", "False", 1),
        RELEASE_FINAL_PROBE_PY.replace("for path in (p for p in elves", "for item in (p for p in elves", 1),
    ):
        assert bad_probe != RELEASE_FINAL_PROBE_PY and bad_probe.startswith(prefix)
        with pytest.raises(ValueError):
            _select_final_probe_elf_block(bad_probe)

    boundary = d12.locate_run_boundary()
    run = active_resource_run()
    assert run is not None, "the linker-cache mechanism probe requires the canonical resource run"
    client = boundary.client
    image_id = ensure_canonical_runtime_image(
        repo_root=REPO_ROOT, resource_run=run, client=client, boundary=boundary
    )
    owner = CurrentRunDockerContainers(run, client)
    payload_source_path = REPO_ROOT / PYTHON_PAYLOAD_SOURCE
    assert payload_source_path.resolve() == Path(python_payload.__file__).resolve()
    payload_source_bytes = payload_source_path.read_bytes()
    mechanism_script = (
        RELEASE_PROBE_HELPERS_PY
        + stdlib_import_src
        + "\n"
        + "import contextlib, io, types\n"
        + f"_PAYLOAD_SOURCE_BYTES = {payload_source_bytes!r}\n"
        + f"_ELF_BLOCK_SRC = {elf_block_src!r}\n"
        + "_ELF_BLOCK_CODE = compile(_ELF_BLOCK_SRC, '<release_final_probe_elf_block>', 'exec')\n"
        + "_ORIG_RUN = run\n"
        + "_MOVED_ACTIVE = False\n"
        + "def _guarded_run(*command, codes=(0,)):\n"
        + "    if _MOVED_ACTIVE and command and 'python' in os.path.basename(str(command[0])).lower():\n"
        + "        raise RuntimeError(f'forbidden Python interpreter spawn while library moved: {command!r}')\n"
        + "    return _ORIG_RUN(*command, codes=codes)\n"
        + "run = _guarded_run\n"
        + "def _exec_elf_block():\n"
        + "    for _k in ('local', 'elves', 'path', 'linked', 'target'):\n"
        + "        globals().pop(_k, None)\n"
        + "    exec(_ELF_BLOCK_CODE, globals())\n"
        + "cache_path = pathlib.Path('/etc/ld.so.cache')\n"
        + "real_libpython = pathlib.Path(os.path.realpath('/usr/local/lib/libpython3.12.so.1.0'))\n"
        + "moved_libpython = pathlib.Path('/root/libpython3.12.so.1.0.ci70-moved')\n"
        + "assert sys.dont_write_bytecode\n"
        + "assert cache_path.is_file() and real_libpython.is_file() and not moved_libpython.exists()\n"
        + "_payload_mod = types.ModuleType('_repomap_ci70_python_payload')\n"
        + f"_payload_mod.__file__ = '<{PYTHON_PAYLOAD_SOURCE}>'\n"
        + "sys.modules[_payload_mod.__name__] = _payload_mod\n"
        + "exec(compile(_PAYLOAD_SOURCE_BYTES, _payload_mod.__file__, 'exec'), _payload_mod.__dict__)\n"
        + "_native_machine = _payload_mod.platform.machine()\n"
        + "assert _native_machine in _payload_mod.NATIVE, f'unsupported machine: {_native_machine!r}'\n"
        + "_native_arch = _payload_mod.NATIVE[_native_machine]\n"
        + "_expected_entry = _payload_mod.PYTHON_PAYLOAD_EXCLUSIONS[_native_arch]\n"
        + "assert pathlib.Path(_expected_entry.path).is_file(), _expected_entry.path\n"
        + "_payload_stdout = io.StringIO()\n"
        + "with contextlib.redirect_stdout(_payload_stdout):\n"
        + "    _payload_exit = _payload_mod.main([_native_arch])\n"
        + "_payload_lines = [line for line in _payload_stdout.getvalue().splitlines() if line.strip()]\n"
        + "assert len(_payload_lines) == 1, len(_payload_lines)\n"
        + "_payload_report = json.loads(_payload_lines[0])\n"
        + "assert _payload_exit == 0 and _payload_report.get('result') == 'trimmed', _payload_report.get('reasons')\n"
        + "assert _payload_report.get('reasons') == [] and _payload_report.get('schema') == _payload_mod.SCHEMA\n"
        + "assert _payload_report.get('architecture') == _native_arch, _payload_report\n"
        + "_expected_excl = {**_expected_entry._asdict(), 'missing': list(_expected_entry.missing),\n"
        + "    'baseline_imports': len(_expected_entry.baseline_imports),\n"
        + "    'reason': 'unusable Tk bridge: Tcl/Tk libraries are absent from the base'}\n"
        + "_retained = _payload_report.get('retained')\n"
        + "assert _payload_report.get('exclusion') == _expected_excl, _payload_report.get('exclusion')\n"
        + "assert isinstance(_retained, dict) and _retained.get('preserved') is True, _retained\n"
        + "assert _retained.get('excluded_absent') is True and _retained.get('unresolved') == [], _retained\n"
        + "assert not pathlib.Path(_expected_entry.path).exists(), _expected_entry.path\n"
        + "assert cache_path.is_file() and real_libpython.is_file() and not moved_libpython.exists()\n"
        + "os.unlink(cache_path)\n"
        + "assert not cache_path.exists()\n"
        + "try:\n"
        + "    _exec_elf_block()\n"
        + "except (AssertionError, SystemExit) as exc:\n"
        + "    phase1_diag = str(exc)\n"
        + "    phase1_path = str(globals().get('path', ''))\n"
        + "    phase1_elves = len(globals().get('elves') or ())\n"
        + "else:\n"
        + "    raise RuntimeError('expected unlinked ld.so.cache ELF block refusal did not occur')\n"
        + "assert 'libpython3.12.so.1.0 => not found' in phase1_diag, phase1_diag\n"
        + "assert phase1_path.startswith('/usr/local/') and phase1_elves > 0, (phase1_path, phase1_elves)\n"
        + "run('ldconfig')\n"
        + "assert cache_path.is_file()\n"
        + "_exec_elf_block()\n"
        + "phase2_local = len(globals().get('local') or ())\n"
        + "phase2_elves = len(globals().get('elves') or ())\n"
        + "assert phase2_local > 0 and phase2_elves > 0, (phase2_local, phase2_elves)\n"
        + "try:\n"
        + "    os.replace(real_libpython, moved_libpython)\n"
        + "    _MOVED_ACTIVE = True\n"
        + "    assert not real_libpython.exists() and moved_libpython.is_file()\n"
        + "    try:\n"
        + "        _exec_elf_block()\n"
        + "    except (AssertionError, SystemExit) as exc:\n"
        + "        phase3_diag = str(exc)\n"
        + "        phase3_path = str(globals().get('path', ''))\n"
        + "        phase3_elves = len(globals().get('elves') or ())\n"
        + "    else:\n"
        + "        raise RuntimeError('expected moved-library ELF block refusal did not occur')\n"
        + "finally:\n"
        + "    _MOVED_ACTIVE = False\n"
        + "    if moved_libpython.exists():\n"
        + "        os.replace(moved_libpython, real_libpython)\n"
        + "assert real_libpython.is_file() and not moved_libpython.exists()\n"
        + "assert 'libpython3.12.so.1.0 => not found' in phase3_diag, phase3_diag\n"
        + "assert phase3_path.startswith('/usr/local/') and phase3_elves > 0, (phase3_path, phase3_elves)\n"
        + "print('D12_LINKER_CACHE_MECHANISM=' + json.dumps({\n"
        + "    'scope': 'python_test_base_mechanism_only',\n"
        + "    'postgresql_assembled_runtime_observed': False,\n"
        + "    'payload_preparation': {'architecture': _payload_report['architecture'],\n"
        + "        'result': _payload_report['result'], 'excluded_module': _payload_report['exclusion']['module'],\n"
        + "        'excluded_path': _payload_report['exclusion']['path'],\n"
        + "        'excluded_sha256': _payload_report['exclusion']['sha256'],\n"
        + "        'preserved': _retained['preserved'], 'excluded_absent': _retained['excluded_absent']},\n"
        + "    'library_path': str(real_libpython),\n"
        + "    'library_restored': bool(real_libpython.is_file() and not moved_libpython.exists()),\n"
        + "    'phase1_failed_path': phase1_path,\n"
        + "    'phase1_diagnostic': phase1_diag,\n"
        + "    'phase2_local_files': phase2_local,\n"
        + "    'phase2_elf_checked': phase2_elves,\n"
        + "    'phase3_failed_path': phase3_path,\n"
        + "    'phase3_diagnostic': phase3_diag,\n"
        + "}, sort_keys=True))\n"
    )
    mech_cid = owner.create(
        image_id,
        ["-I", "-B", "-c", mechanism_script],
        role="d12-linker-cache-mechanism-probe",
        entrypoint=["python"],
        network_mode="none",
    )
    try:
        mech_container = client.containers.get(mech_cid)
        mech_container.start()
        mech_status = mech_container.wait(timeout=180).get("StatusCode", 1)
        mech_stdout = mech_container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
        mech_stderr = mech_container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
    finally:
        owner.cleanup(mech_cid)
    owner.verify_baseline()
    assert mech_status == 0, f"linker-cache mechanism probe failed with {mech_status}: {mech_stderr[-4000:]}"
    mech_line = mech_stdout.splitlines()[-1]
    assert mech_line.startswith("D12_LINKER_CACHE_MECHANISM="), mech_line
    mech_report = json.loads(mech_line.removeprefix("D12_LINKER_CACHE_MECHANISM="))
    print(mech_line)
    assert mech_report["scope"] == "python_test_base_mechanism_only"
    assert mech_report["postgresql_assembled_runtime_observed"] is False
    prep = mech_report["payload_preparation"]
    expected_exclusion = python_payload.PYTHON_PAYLOAD_EXCLUSIONS[prep["architecture"]]
    assert prep == {
        "architecture": expected_exclusion.architecture, "result": "trimmed",
        "excluded_module": expected_exclusion.module, "excluded_path": expected_exclusion.path,
        "excluded_sha256": expected_exclusion.sha256, "preserved": True, "excluded_absent": True,
    }
    assert mech_report["library_restored"] is True
    assert mech_report["phase1_failed_path"].startswith("/usr/local/")
    assert "libpython3.12.so.1.0 => not found" in mech_report["phase1_diagnostic"]
    assert mech_report["phase2_local_files"] > 0 and mech_report["phase2_elf_checked"] > 0
    assert mech_report["phase3_failed_path"].startswith("/usr/local/")
    assert "libpython3.12.so.1.0 => not found" in mech_report["phase3_diagnostic"]
