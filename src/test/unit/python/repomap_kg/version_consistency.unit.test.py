from __future__ import annotations

from pathlib import Path
import tomllib

import repomap_kg


def test_version_consistency() -> None:
    pyproject_path = Path(__file__).resolve().parents[5] / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject = tomllib.load(f)
    pyproject_version = pyproject["project"]["version"]
    assert pyproject_version == "0.0.1"
    assert repomap_kg.__version__ == "0.0.1"
    assert repomap_kg.__version__ == pyproject_version
