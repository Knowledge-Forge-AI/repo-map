from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from ci.bootstrap_pre_review import verify_python_distribution


_PSYCOPG_C_INIT = (
    "import sys\n"
    "if 'psycopg' not in sys.modules:\n"
    "    raise ImportError('the psycopg package should be imported before psycopg_c')\n"
    "__version__ = '3.3.6'\n"
)


def _build_synthetic_python_root(root: Path) -> tuple[Path, Path, Path]:
    owner_root = root / "sealed-python"
    bin_dir = owner_root / "bin"
    site_dir = owner_root / "site-packages"
    bin_dir.mkdir(parents=True)
    site_dir.mkdir(parents=True)
    python_bin = bin_dir / "python"
    quoted_site = shlex.quote(str(site_dir))
    quoted_exec = shlex.quote(sys.executable)
    python_bin.write_text(
        "#!/bin/sh\n"
        "unset COVERAGE_PROCESS_START COVERAGE_CHILD_MANIFEST_DIR COVERAGE_FILE\n"
        f"PYTHONPATH={quoted_site} exec {quoted_exec} -S \"$@\"\n",
        encoding="utf-8",
    )
    python_bin.chmod(0o755)
    return owner_root, python_bin, site_dir


def _write_dist(
    site_dir: Path,
    module_name: str,
    dist_name: str,
    version: str,
    body: str = "__version__ = '1.0'\n",
) -> Path:
    pkg_dir = site_dir / module_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    init_file = pkg_dir / "__init__.py"
    init_file.write_text(body, encoding="utf-8")
    dist_info = site_dir / f"{dist_name.replace('-', '_')}-{version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {dist_name}\nVersion: {version}\n",
        encoding="utf-8",
    )
    return init_file


def test_verify_python_distribution_loads_psycopg_before_psycopg_c(tmp_path: Path) -> None:
    owner_root, python_bin, site_dir = _build_synthetic_python_root(tmp_path)
    _write_dist(site_dir, "psycopg", "psycopg", "3.3.6", "__version__ = '3.3.6'\n")
    _write_dist(site_dir, "psycopg_c", "psycopg-c", "3.3.6", _PSYCOPG_C_INIT)

    verify_python_distribution(python_bin, "psycopg", "psycopg", "3.3.6", owner_root)
    verify_python_distribution(python_bin, "psycopg_c", "psycopg-c", "3.3.6", owner_root)


def test_verify_python_distribution_does_not_preload_psycopg_for_unrelated_modules(
    tmp_path: Path,
) -> None:
    owner_root, python_bin, site_dir = _build_synthetic_python_root(tmp_path)
    _write_dist(
        site_dir,
        "psycopg",
        "psycopg",
        "3.3.6",
        "raise RuntimeError('unrelated module attestation must not import psycopg')\n",
    )
    _write_dist(
        site_dir,
        "sample_mod",
        "sample-mod",
        "1.2.3",
        "import sys\nassert 'psycopg' not in sys.modules\n",
    )

    verify_python_distribution(python_bin, "sample_mod", "sample-mod", "1.2.3", owner_root)


def test_verify_python_distribution_refuses_psycopg_c_when_psycopg_missing(
    tmp_path: Path,
) -> None:
    owner_root, python_bin, site_dir = _build_synthetic_python_root(tmp_path)
    _write_dist(site_dir, "psycopg_c", "psycopg-c", "3.3.6", _PSYCOPG_C_INIT)

    with pytest.raises(subprocess.CalledProcessError):
        verify_python_distribution(python_bin, "psycopg_c", "psycopg-c", "3.3.6", owner_root)


def test_verify_python_distribution_refuses_version_mismatch(tmp_path: Path) -> None:
    owner_root, python_bin, site_dir = _build_synthetic_python_root(tmp_path)
    _write_dist(site_dir, "psycopg", "psycopg", "3.3.6", "__version__ = '3.3.6'\n")
    _write_dist(site_dir, "psycopg_c", "psycopg-c", "3.3.6", "__version__ = '3.3.6'\n")

    with pytest.raises(
        RuntimeError,
        match="sealed Python dependency attestation failed for psycopg-c",
    ):
        verify_python_distribution(python_bin, "psycopg_c", "psycopg-c", "3.3.5", owner_root)

    with pytest.raises(
        RuntimeError,
        match="sealed Python dependency attestation failed for psycopg",
    ):
        verify_python_distribution(python_bin, "psycopg", "psycopg", "3.3.5", owner_root)


def test_verify_python_distribution_refuses_module_outside_owner_root_and_symlink_escape(
    tmp_path: Path,
) -> None:
    owner_root, python_bin, site_dir = _build_synthetic_python_root(tmp_path)
    _write_dist(site_dir, "psycopg", "psycopg", "3.3.6", "__version__ = '3.3.6'\n")

    outside_pkg = tmp_path / "outside" / "escaped_mod"
    outside_pkg.mkdir(parents=True)
    (outside_pkg / "__init__.py").write_text("__version__ = '1.0.0'\n", encoding="utf-8")
    (site_dir / "escaped_mod").symlink_to(outside_pkg, target_is_directory=True)
    dist_info = site_dir / "escaped_mod-1.0.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: escaped-mod\nVersion: 1.0.0\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="sealed Python dependency attestation failed for psycopg",
    ):
        verify_python_distribution(
            python_bin,
            "psycopg",
            "psycopg",
            "3.3.6",
            tmp_path / "wrong-owner",
        )

    with pytest.raises(
        RuntimeError,
        match="sealed Python dependency attestation failed for escaped-mod",
    ):
        verify_python_distribution(python_bin, "escaped_mod", "escaped-mod", "1.0.0", owner_root)


def test_verify_python_distribution_refuses_missing_module_or_metadata(
    tmp_path: Path,
) -> None:
    owner_root, python_bin, site_dir = _build_synthetic_python_root(tmp_path)
    _write_dist(site_dir, "psycopg", "psycopg", "3.3.6", "__version__ = '3.3.6'\n")

    with pytest.raises(subprocess.CalledProcessError):
        verify_python_distribution(python_bin, "missing_mod", "psycopg", "3.3.6", owner_root)

    with pytest.raises(subprocess.CalledProcessError):
        verify_python_distribution(python_bin, "psycopg", "missing-dist", "3.3.6", owner_root)
