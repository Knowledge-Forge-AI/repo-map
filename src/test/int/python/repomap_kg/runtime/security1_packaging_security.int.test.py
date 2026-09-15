import json
import os
import subprocess
import tarfile
import textwrap
import unicodedata
import zipfile
from pathlib import Path

import pytest


BACKEND_PYTHON_ENV = "SECURITY1_SETUPTOOLS_PYTHON"


def _backend_python() -> str:
    backend_python = os.environ.get(BACKEND_PYTHON_ENV)
    if backend_python is None:
        pytest.skip(f"{BACKEND_PYTHON_ENV} is required")
    return backend_python


def _run_backend_script(
    script: str,
    *arguments: str,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        (_backend_python(), "-c", script, *arguments),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_manifest_exclusion_matches_canonical_unicode_equivalents() -> None:
    script = textwrap.dedent(
        """
        import json
        import sys
        import unicodedata

        from setuptools.command.egg_info import FileList

        nfc_name = unicodedata.normalize("NFC", sys.argv[1])
        nfd_name = unicodedata.normalize("NFD", nfc_name)
        file_list = FileList()
        file_list.files = [nfd_name, "public.txt"]
        file_list.global_exclude(nfc_name)
        print(json.dumps({
            "equivalent": unicodedata.normalize("NFC", nfd_name) == nfc_name,
            "byte_distinct": nfc_name.encode() != nfd_name.encode(),
            "remaining": file_list.files,
        }))
        """
    )

    result = _run_backend_script(script, "secret_café.txt")
    observed = json.loads(result.stdout)

    assert observed["equivalent"] is True
    assert observed["byte_distinct"] is True
    assert observed["remaining"] == ["public.txt"]


def _write_fixture(root: Path) -> tuple[str, str]:
    nfc_name = unicodedata.normalize("NFC", "secret_café.txt")
    nfd_name = unicodedata.normalize("NFD", nfc_name)
    (root / "fixture_module.py").write_text(
        'MESSAGE = "public fixture"\n',
        encoding="utf-8",
    )
    (root / "public.txt").write_text("public fixture\n", encoding="utf-8")
    (root / nfd_name).write_text("excluded fixture\n", encoding="utf-8")
    (root / "unrelated.log").write_text("not packaged\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [build-system]
            requires = ["setuptools"]
            build-backend = "setuptools.build_meta"

            [project]
            name = "security1-unicode-fixture"
            version = "1.0.0"
            requires-python = ">=3.10"

            [tool.setuptools]
            py-modules = ["fixture_module"]
            """
        ).lstrip(),
        encoding="utf-8",
    )
    (root / "MANIFEST.in").write_text(
        "include fixture_module.py\n"
        "global-include *.txt\n"
        f"global-exclude {nfc_name}\n",
        encoding="utf-8",
    )
    return nfc_name, nfd_name


def _build_fixture(root: Path, output: Path) -> tuple[Path, Path]:
    subprocess.run(
        (
            _backend_python(),
            "-m",
            "build",
            "--no-isolation",
            "--sdist",
            "--wheel",
            "--outdir",
            str(output),
            str(root),
        ),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return (
        next(output.glob("*.tar.gz")),
        next(output.glob("*.whl")),
    )


def _normalized_sdist_names(archive_path: Path) -> tuple[str, ...]:
    with tarfile.open(archive_path, "r:gz") as archive:
        return tuple(
            sorted(
                unicodedata.normalize("NFC", member.name)
                for member in archive.getmembers()
                if member.isfile()
            )
        )


def test_sdist_excludes_alternate_normalization_and_is_repeatable(
    tmp_path: Path,
) -> None:
    manifests: list[tuple[str, ...]] = []
    nfc_name = ""
    for build_number in (1, 2):
        fixture = tmp_path / f"fixture-{build_number}"
        output = tmp_path / f"dist-{build_number}"
        fixture.mkdir()
        output.mkdir()
        nfc_name, nfd_name = _write_fixture(fixture)
        stored_names = tuple(path.name for path in fixture.iterdir())
        assert any(
            unicodedata.normalize("NFC", name) == nfc_name
            for name in stored_names
        )
        assert unicodedata.normalize("NFC", nfd_name) == nfc_name

        sdist, wheel = _build_fixture(fixture, output)
        manifests.append(_normalized_sdist_names(sdist))
        with zipfile.ZipFile(wheel) as archive:
            wheel_names = tuple(archive.namelist())

        assert any(name.endswith("/public.txt") for name in manifests[-1])
        assert any(
            name.endswith("/fixture_module.py") for name in manifests[-1]
        )
        assert not any(nfc_name in name for name in manifests[-1])
        assert not any(name.endswith("/unrelated.log") for name in manifests[-1])
        assert any(name.endswith("fixture_module.py") for name in wheel_names)
        assert not any(nfc_name in name for name in wheel_names)
        assert not any("unrelated.log" in name for name in wheel_names)
        assert not any(
            str(tmp_path) in name
            for name in (*manifests[-1], *wheel_names)
        )

    assert manifests[0] == manifests[1]
