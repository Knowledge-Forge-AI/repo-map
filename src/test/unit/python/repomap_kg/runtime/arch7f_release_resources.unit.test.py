import ast
import hashlib
import struct
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.runtime import release, release_manifest
from common_lore_index.runtime.commands import (
    render_compose_yaml,
    render_server_dockerfile,
)
from common_lore_index.runtime.local import setup_local_runtime
from common_lore_index.runtime.plan import build_local_runtime_plan
from common_lore_index.runtime.release import DebPackage, PlatformPackages, validate_package_manifest
from repomap_test_support import d12_dynamic_linkage as linkage


REPO_ROOT = Path(__file__).resolve().parents[6]
LIBPQ5 = "18.4-1.pgdg120+1"


def _deb(name: str, version: str = LIBPQ5) -> DebPackage:
    """A distinct deterministic SHA-256 per package keeps every negative attributable (ADR 0089 B2)."""
    return DebPackage(name, version, "arm64", hashlib.sha256(f"{name}={version}".encode()).hexdigest())


def _platform(**changes: Any) -> PlatformPackages:
    item = PlatformPackages(
        postgres_config_digest="sha256:" + "b" * 64,
        pgdg_source=("/etc/apt/sources.list.d/pgdg.list", "c" * 64),
        pgdg_keyring=("/usr/local/share/keyrings/postgres-archive-keyring.gpg", "d" * 64),
        key_fingerprints=("B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8",),
        libpq_path="/usr/lib/aarch64-linux-gnu/libpq.so.5.18", libpq_sha256="e" * 64, libpq5_version=LIBPQ5,
        builder=(_deb("libpq5"), _deb("libpq-dev"), _deb("gcc", "4:12.2.0-3")),
        closure=(_deb("libgdbm6", "1.23-3"), _deb("libgdbm-compat4", "1.23-3")),
        lib_dynload=("_dbm",),
    )
    return item._replace(**changes)


def _probe_helpers(snippet: str) -> subprocess.CompletedProcess[str]:
    program = release.RELEASE_PROBE_HELPERS_PY + "import sys\n" + snippet
    return subprocess.run([sys.executable, "-I", "-c", program], capture_output=True, text=True, check=False)


def _elf(*segment_types: int) -> bytes:
    header = b"\x7fELF" + bytes((2, 1, 1)) + bytes(9)
    header += struct.pack("<HHIQQQIHHHHHH", 3, 183, 1, 0, 64, 0, 0, 64, 56, len(segment_types), 0, 0, 0)
    return header + b"".join(struct.pack("<I", kind) + bytes(52) for kind in segment_types)


def test_release_metadata_pins_psycopg_and_preserves_migration_paths() -> None:
    metadata = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = tomllib.loads(metadata)["project"]

    assert 'requires = ["setuptools==83.0.0"]' in metadata
    assert project["dependencies"] == ["typing-extensions==4.16.0"]
    assert project["optional-dependencies"]["postgres"] == ["psycopg[c]==3.3.6"]
    assert set(project["optional-dependencies"]) == {
        "test",
        "scale-tools",
        "static-analysis",
        "postgres",
    }
    assert not any(
        driver in requirement.lower()
        for requirement in project["dependencies"]
        for driver in ("psycopg", "libpq", "pg8000", "asyncpg")
    )
    for destination in (
        '"share/common-lore-index/rdbms"',
        '"share/common-lore-index/rdbms/2026/06"',
        '"share/common-lore-index/rdbms/2026/07"',
        '"share/common-lore-index/rdbms/2026/09"',
        '"share/common-lore-index/coordinator-rdbms"',
        '"share/common-lore-index/coordinator-rdbms/2026/07"',
        '"share/common-lore-index/coordinator-rdbms/2026/10"',
    ):
        assert destination in metadata


def test_projected_public_metadata_preserves_migration_paths_and_psycopg_isolation() -> None:
    metadata = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert tomllib.loads(metadata)["project"]["version"] in {"0.1.0", "0.0.3"}
    private_metadata = metadata.replace('version = "0.0.3"', 'version = "0.1.0"', 1)
    public_metadata = private_metadata.replace('version = "0.1.0"', 'version = "0.0.3"', 1)
    public_project = tomllib.loads(public_metadata)["project"]
    assert public_project["version"] == "0.0.3"
    assert public_project["dependencies"] == ["typing-extensions==4.16.0"]
    assert public_project["optional-dependencies"]["postgres"] == [
        "psycopg[c]==3.3.6"
    ]
    assert not any(
        driver in requirement.lower()
        for requirement in public_project["dependencies"]
        for driver in ("psycopg", "libpq", "pg8000", "asyncpg")
    )
    for destination in (
        '"share/common-lore-index/rdbms"',
        '"share/common-lore-index/rdbms/2026/06"',
        '"share/common-lore-index/rdbms/2026/07"',
        '"share/common-lore-index/rdbms/2026/09"',
        '"share/common-lore-index/coordinator-rdbms"',
        '"share/common-lore-index/coordinator-rdbms/2026/07"',
        '"share/common-lore-index/coordinator-rdbms/2026/10"',
    ):
        assert destination in public_metadata


def test_release_dockerfile_uses_only_pinned_build_and_runtime_resources() -> None:
    dockerfile = render_server_dockerfile()

    assert (
        "postgres:16.15-trixie@sha256:"
        "1beaa3084eee2676f20a9cd9928f0bf2c5bf674f8e49f81017912183d377c61c"
        in dockerfile
    )
    assert (
        "python:3.12-slim-trixie@sha256:"
        "aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159"
        in dockerfile
    )
    # ADR 0090 D1: the exact approved Go index, tagged with its version.
    assert release.GO_RELEASE_VERSION == "1.26.10"
    assert release.GO_RELEASE_IMAGE == (
        "golang:1.26.10-bookworm@sha256:632dff7351799a5a9954a48dc06670ade72ee44e8c351cdc0e5a57af2fea21af"
    )
    assert release.GO_RELEASE_IMAGE.startswith(f"golang:{release.GO_RELEASE_VERSION}-bookworm@sha256:")
    assert f"FROM {release.GO_RELEASE_IMAGE} AS go-helper\n" in dockerfile
    assert "ARG POSTGRES_IMAGE" not in dockerfile
    assert "ARG PYTHON_IMAGE" not in dockerfile
    assert "ARG GO_IMAGE" not in dockerfile
    assert "FROM ${" not in dockerfile
    assert dockerfile.count("go build") == 1
    assert "CGO_ENABLED=0 GOTOOLCHAIN=local GOOS=" in dockerfile and dockerfile.count("GOTOOLCHAIN=") == 1
    assert "setuptools==83.0.0 --hash=sha256:" in dockerfile
    assert (
        'python -m pip install --no-cache-dir --no-index --no-deps --no-build-isolation ".[postgres]"'
        in dockerfile
    )
    assert "--no-build-isolation .\n" not in dockerfile
    assert "installed_graph == source_graph" in dockerfile
    assert "installed_control == source_control" in dockerfile
    assert "python -m pip uninstall -y pip setuptools wheel packaging" in dockerfile
    assert "packaging==26.3 --hash=sha256:" in dockerfile and "python -m pip check" in dockerfile
    assert "/usr/local/lib/python3.12/ensurepip /usr/local/include" in dockerfile
    assert "find_spec('pip') is None" in dockerfile
    assert "find_spec('setuptools') is None" in dockerfile
    assert "/usr/share/doc/repomap-kg/go/LICENSE" in dockerfile
    assert "COPY --from=go-helper /usr/local/go/PATENTS /usr/share/doc/repomap-kg/go/PATENTS\n" in dockerfile
    assert "&& test -s /usr/share/doc/repomap-kg/go/PATENTS \\\n" in dockerfile
    assert "/usr/local/lib/python3.12/LICENSE.txt" in dockerfile
    # ADR 0089: no /usr/lib overlay; an unfrozen manifest refuses before any apt or backend work.
    assert "COPY --from=python-runtime /usr/lib" not in dockerfile
    assert "apt-get" not in dockerfile and "package manifest unresolved" in dockerfile
    assert "postgresql-client" not in dockerfile
    assert "REPOMAP_PACKAGED_PSQL=/usr/lib/postgresql/16/bin/psql" in dockerfile
    assert "REPOMAP_PACKAGED_PG_DUMP=/usr/bin/pg_dump" in dockerfile
    assert "REPOMAP_PACKAGED_PG_RESTORE=/usr/bin/pg_restore" in dockerfile
    assert "command -v go" in dockerfile
    assert "! command -v go" in dockerfile
    assert "PYTHONPATH" not in dockerfile
    assert "assert pq.__impl__ == 'c'" in dockerfile
    assert 'io.repomap.release.libpq="unresolved"' in dockerfile


def test_frozen_manifest_compares_package_additions_in_one_c_byte_order() -> None:
    dockerfile = render_server_dockerfile({"arm64": _platform()}, 180004)
    steps = [line for line in dockerfile.splitlines() if "comm -13" in line]
    assert len(steps) == 2, "builder and closure each compare their additions"
    for line in steps:
        # The postgres base sets LANG=en_US.utf8, where libgdbm-compat4/libgdbm6 and
        # libpq-dev/libpq5 collate differently from Python's sorted() expectation.
        assert line.index("export LC_ALL=C && ") < line.index("sort") < line.index("comm -23"), line
    assert steps[0].lstrip().startswith("arm64) printf ") and " | sha256sum -c - && export LC_ALL=C" in steps[0]
    assert steps[1].lstrip().startswith("arm64) export LC_ALL=C && "), steps[1]
    assert ("printf '%s\\n' 'ii  gcc:arm64=4:12.2.0-3' 'ii  libpq-dev:arm64=18.4-1.pgdg120+1' "
            "'ii  libpq5:arm64=18.4-1.pgdg120+1' > /tmp/repomap-apt/exp") in steps[0], steps[0]
    assert ("printf '%s\\n' 'ii  libgdbm-compat4:arm64=1.23-3' 'ii  libgdbm6:arm64=1.23-3' "
            "> /tmp/repomap-apt/exp") in steps[1], steps[1]
    assert "REPOMAP_EXPECT_MINIMUM_LIBPQ=170000" in dockerfile


def test_runtime_stage_refreshes_linker_cache_once_after_closure_before_python() -> None:
    assert release_manifest.D12_CANDIDATE_PACKAGE_MANIFEST["amd64"].closure == ()
    assert len(_platform().closure) == 2
    default_df = render_server_dockerfile()
    amd_df = render_server_dockerfile(
        release_manifest.D12_CANDIDATE_PACKAGE_MANIFEST,
        release_manifest.D12_CANDIDATE_LIBPQ_VERSION,
    )
    fixture_df = render_server_dockerfile({"arm64": _platform()}, 180004)
    assert "apt-get" not in default_df
    assert (
        'ADR 0089 D3 package manifest unresolved for ${TARGETARCH}; '
        "refusing before package or backend execution" in default_df
    )
    assert "    amd64) true ;; \\\n    *) exit 1 ;; \\\n    esac\nRUN ldconfig\n" in amd_df
    assert "rm -rf /var/lib/apt/lists/* ;; \\\n    *) exit 1 ;; \\\n    esac\nRUN ldconfig\n" in fixture_df
    for rendered in (default_df, amd_df, fixture_df):
        before_runtime, runtime_stage = rendered.split(
            f"FROM {release.POSTGRES_RELEASE_IMAGE} AS runtime\n", 1
        )
        assert "ldconfig" not in before_runtime
        assert rendered.count("ldconfig") == 1
        assert runtime_stage.splitlines().count("RUN ldconfig") == 1
        copy_idx = runtime_stage.index("COPY --from=python-runtime /usr/local /usr/local\n")
        closure_idx = runtime_stage.index('RUN case "${TARGETARCH}" in \\\n', copy_idx)
        closure_end = runtime_stage.index("    esac\n", closure_idx) + len("    esac\n")
        ldconfig_idx = runtime_stage.index("RUN ldconfig\n")
        first_python_idx = runtime_stage.index('RUN package_root="$(python -c ')
        probe_idx = runtime_stage.index("python -I /tmp/repomap-release-probe.py")
        assert copy_idx < closure_idx < closure_end == ldconfig_idx < first_python_idx < probe_idx
        assert not [
            line for line in runtime_stage[:ldconfig_idx].splitlines()
            if "python" in line and not line.startswith("COPY --from=python-runtime")
        ]
        assert (
            f"COPY <<'REPOMAP_PY' /tmp/repomap-release-probe.py\n"
            f"{release.RELEASE_FINAL_PROBE_PY}REPOMAP_PY\n" in runtime_stage
        )
        assert 'assert "not found" not in linked, f"{path}: {linked}"' in runtime_stage


REPEATS = "repeats a package name, SHA-256 or file"


@pytest.mark.parametrize("change, message", [
    ({"builder": (_deb("libpq5"), _deb("libpq-dev", "18.3-1.pgdg120+1"))}, "libpq-dev and libpq5 differ"),
    ({"builder": (_deb("libpq-dev"),)}, "libpq-dev and libpq5 differ"),
    ({"pgdg_source": ("etc/apt/pgdg.list", "c" * 64)}, "trust file identity"),
    ({"pgdg_keyring": ("/usr/share/../keyrings/k.gpg", "d" * 64)}, "trust file identity"),
    ({"pgdg_keyring": ("/usr/share/keyrings/k.gpg $(id)", "d" * 64)}, "trust file identity"),
    ({"pgdg_source": ("/etc/apt/sources.list.d/pgdg.list", "C" * 64)}, "trust file identity"),
    ({"key_fingerprints": ()}, "fingerprints"),
    ({"key_fingerprints": ("b97b0afcaa1a47f044f244a07fcc7d46accc4cf8",)}, "fingerprints"),
    ({"postgres_config_digest": "b" * 64}, "base or libpq file identity"),
    ({"libpq_path": "/usr/local/lib/libpq.so.5.18"}, "base or libpq file identity"),
    ({"libpq_sha256": "e" * 63}, "base or libpq file identity"),
    ({"lib_dynload": ("_dbm; rm",)}, "lib-dynload"),
    ({"closure": (_deb("libgdbm6", "1.23-3")._replace(architecture="amd64"),)}, "identity is incomplete"),
    ({"closure": (_deb("libgdbm6", "1.23 3"),)}, "identity is incomplete"),
    ({"builder": (*_platform().builder, _deb("gcc", "4:12.2.0-4"))}, REPEATS),
    ({"closure": (_deb("libgdbm6", "1.23-3"), _deb("libgdbm-compat4", "1.23-3")._replace(
        sha256=_deb("libgdbm6", "1.23-3").sha256))}, REPEATS),
    ({"closure": (_deb("libgdbm6", "1.23-3"),) * 2}, REPEATS),
    # Duplicates are checked last, so this keeps the libpq message.
    ({"builder": (_deb("libpq5"), _deb("libpq-dev", "18.3-1.pgdg120+1")._replace(sha256=_deb("libpq5").sha256))},
     "libpq-dev and libpq5 differ"),
])
def test_frozen_manifest_refuses_incomplete_unsafe_or_inconsistent_identity(
    change: dict[str, Any], message: str,
) -> None:
    validate_package_manifest({"arm64": _platform()}, 180004)
    with pytest.raises(ValueError, match=message):
        validate_package_manifest({"arm64": _platform(**change)}, 180004)
    with pytest.raises(ValueError, match="bounded cancel_safe"):  # the incumbent bound needs libpq >= 17
        validate_package_manifest({"arm64": _platform()}, 160013)


def test_release_probe_subprocesses_fail_closed_and_read_elf_headers_without_running_them(tmp_path: Path) -> None:
    for refused in ('run(sys.executable, "-c", "import sys; sys.exit(2)", codes=(0, 1))',
                    'run(sys.executable, "-c", "import sys; sys.stderr.write(\'warning\')")'):
        completed = _probe_helpers(refused)
        assert completed.returncode == 1 and "exited" in completed.stderr, (refused, completed)
    (tmp_path / "dynamic.so").write_bytes(_elf(1, 2))
    (tmp_path / "static").write_bytes(_elf(1, 1))
    names = ["libpq.pxd", "libpq.so.5", "libpq-1a2b.so.5.17", "libpq.a", "libpq-fe.h", "pq.cpython-312.so"]
    accepted = _probe_helpers(
        'print(run(sys.executable, "-c", "import sys; sys.stderr.write(\'absent\'); sys.exit(1)", codes=(0, 1)))\n'
        f'print(dynamic({str(tmp_path / "dynamic.so")!r}), dynamic({str(tmp_path / "static")!r}))\n'
        f'print([name for name in {names!r} if LIBRARY_FILE.search(name)])\n')
    expected_lines = ["(1, '')", "True False", "['libpq.so.5', 'libpq-1a2b.so.5.17', 'libpq.a']"]
    assert accepted.stdout.splitlines() == expected_lines, accepted
    assert f'LIBRARY_FILE = re.compile(r"{linkage.LIBRARY_FILE.pattern}")' in release.RELEASE_PROBE_HELPERS_PY
    probe = release.RELEASE_FINAL_PROBE_PY
    assert "check=False).stdout" not in probe and 'p.name.startswith("libpq")' not in probe
    assert 'run("dpkg", "--verify", "libpq5", codes=(0, 1))' in probe and "has_cancel_safe(), \"bounded" in probe


def test_release_probe_child_imports_psycopg_before_its_eager_bind_module_loop() -> None:
    """The fresh LD_BIND_NOW child initializes psycopg before its psycopg_c modules (ADR 0089 R-F1)."""
    (child,) = [node for node in ast.walk(ast.parse(release.RELEASE_FINAL_PROBE_PY)) if isinstance(node, ast.Call)
                and ast.unparse(node.func) == "run" and ast.unparse(node.args[0]) == "sys.executable"]
    assert isinstance(child.args[3], ast.Constant) and ast.unparse(child.args[4]) == "*modules", ast.unparse(child)
    body = [ast.unparse(node) for node in ast.parse(str(child.args[3].value)).body]
    assert body[0].startswith("import psycopg") and "import_module" in body[1], body


def test_build_tool_closure_is_pip_checked_and_removed_before_the_final_image() -> None:
    assert release.RELEASE_BUILD_ONLY_MODULES == ("pip", "setuptools", "wheel", "packaging")
    requirements = {name.split("==")[0] for name in release.RELEASE_WHEEL_REQUIREMENTS}
    assert requirements == {"packaging", "psycopg", "setuptools", "typing-extensions", "wheel"}
    dockerfile = render_server_dockerfile()
    assert dockerfile.index("python -m pip check") < dockerfile.index("pip uninstall -y pip setuptools wheel packaging")
    assert "['pip', 'setuptools', 'wheel', 'packaging'] if find_spec(m)] == []" in dockerfile


def test_license_assets_ship_in_the_wheel_and_the_image_with_the_inspected_source() -> None:
    package_data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"][
        "package-data"]["common_lore_index"]
    assets = sorted(path.name for path in (REPO_ROOT / "src/main/python/common_lore_index/third_party_licenses").iterdir())
    assert package_data == ["third_party_licenses/*.json", "third_party_licenses/*.txt"]
    assert assets == ["GPL-3.0.txt", "psycopg-LICENSE.txt", "psycopg-c-numutils-PostgreSQL.txt", "psycopg-source.json"]
    dockerfile = render_server_dockerfile()
    assert 'install -D -m 0444 "/tmp/repomap-build/psycopg_c-3.3.6.tar.gz" "/build/psycopg-c-source/' in dockerfile
    assert "COPY --from=python-runtime /build/psycopg-c-source/ /usr/share/doc/repomap-kg/psycopg/source/" in dockerfile
    for asset in assets:
        assert f"test -s /usr/share/doc/repomap-kg/psycopg/{asset}" in dockerfile, asset
    numutils = (REPO_ROOT / "src/main/python/common_lore_index/third_party_licenses/psycopg-c-numutils-PostgreSQL.txt")
    text = numutils.read_text(encoding="utf-8")
    assert " * Portions Copyright (c) 1996-2020, PostgreSQL Global Development Group\n" in text
    assert " * Portions Copyright (c) 1994, Regents of the University of California\n" in text
    assert "IN NO EVENT SHALL THE UNIVERSITY OF CALIFORNIA BE LIABLE" in text


def test_packaged_modules_import_only_the_postgres_extra_driver() -> None:
    package_root = REPO_ROOT / "src/main/python/common_lore_index"
    third_party: set[str] = set()
    for path in package_root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, (ast.Attribute, ast.Name))
                and getattr(node.func, "attr", getattr(node.func, "id", None))
                in {"import_module", "__import__"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                names = [node.args[0].value]
            else:
                continue
            third_party.update(
                top
                for top in (name.split(".")[0] for name in names)
                if top and top not in sys.stdlib_module_names and top != "common_lore_index"
            )

    assert third_party == {"psycopg"}


def test_release_notices_cover_binary_runtime_redistribution() -> None:
    notices = (REPO_ROOT / "docs/legal/third-party-notices.md").read_text(
        encoding="utf-8"
    )

    assert "## Go runtime and standard library" in notices
    assert "BSD-3-Clause" in notices
    assert "/usr/share/doc/repomap-kg/go/LICENSE" in notices
    assert "/usr/share/doc/repomap-kg/go/PATENTS" in notices and "Packaged version: `1.26.10`" in notices
    assert "## Python runtime and standard library" in notices
    assert "PSF-2.0" in notices
    assert "/usr/local/lib/python3.12/LICENSE.txt" in notices


def test_docker_context_is_an_explicit_release_input_allowlist() -> None:
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert dockerignore.startswith("**\n")
    assert "!pyproject.toml\n" in dockerignore
    assert "!README.md\n" in dockerignore
    assert "!src/main/python/**\n" in dockerignore
    assert "!src/main/resources/**\n" in dockerignore
    assert "!src/main/go/**\n" in dockerignore


def test_compose_uses_the_same_pinned_postgres_release_image(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    setup_local_runtime(home)
    plan = build_local_runtime_plan(home)
    compose = render_compose_yaml(plan)

    assert (
        "image: postgres:16.15-trixie@sha256:"
        "1beaa3084eee2676f20a9cd9928f0bf2c5bf674f8e49f81017912183d377c61c"
        in compose
    )
    assert "postgres:16-alpine" not in compose
    assert f"image: repomap-runtime:{plan.identity.home_hash}" in compose
    assert f"repomap-runtime-{plan.identity.home_hash}" not in compose
