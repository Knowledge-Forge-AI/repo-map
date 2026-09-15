from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ci import python_fixture_authority as authority


REPO_ROOT = Path(__file__).resolve().parents[6]


def _write_synthetic_authority(
    tmp_path: Path,
    *,
    source: str = "value = 1\n",
    role: str = "inert_data",
    shape: str = "valid",
    consumer_source: str | None = None,
    provenance: object = None,
    rationale: str = "Static source consumed by the parser as fixture data.",
) -> tuple[Path, Path, Path]:
    fixture = tmp_path / "src/test/fixtures/case/sample.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(source, encoding="utf-8")
    consumer = tmp_path / "src/test/unit/python/consumer.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text(
        consumer_source
        or "from pathlib import Path\nfixture = Path('src/test/fixtures/case/sample.py')\n",
        encoding="utf-8",
    )
    mode = {
        "inert_data": "static_extraction",
        "executable_first_party": "direct_execution",
        "generated": "generated_input",
        "vendor": "vendor_input",
    }[role]
    manifest = tmp_path / "tools/ci/python_fixture_authority.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema": authority.SCHEMA,
                "version": 1,
                "fixture_root": authority.FIXTURE_ROOT,
                "entries": [
                    {
                        "path": "src/test/fixtures/case/sample.py",
                        "role": role,
                        "content_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                        "consumer": ["src/test/unit/python/consumer.py"],
                        "consumption_mode": mode,
                        "source_shape": shape,
                        "rationale": rationale,
                        "provenance": provenance,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest, fixture, consumer


def test_current_authority_covers_every_python_fixture() -> None:
    result = authority.validate_fixture_manifest(
        REPO_ROOT, authority.DEFAULT_MANIFEST_PATH
    )

    assert result["status"] == "passed"
    assert result["entry_count"] == 30
    assert result["role_counts"] == {
        "executable_first_party": 3,
        "generated": 0,
        "inert_data": 27,
        "vendor": 0,
    }
    assert result["source_shape_counts"] == {"malformed": 2, "valid": 28}
    assert authority.classify_fixture(
        "src/test/fixtures/direct_pytest/passing.test.py",
        authority.load_manifest(authority.DEFAULT_MANIFEST_PATH),
    ).role == "executable_first_party"


def test_content_digest_drift_fails_closed(tmp_path: Path) -> None:
    manifest, fixture, _ = _write_synthetic_authority(tmp_path)
    fixture.write_text("value = 2\n", encoding="utf-8")

    with pytest.raises(authority.FixtureAuthorityError, match="digest mismatch"):
        authority.validate_fixture_manifest(tmp_path, manifest)


def test_census_must_match_manifest(tmp_path: Path) -> None:
    manifest, fixture, _ = _write_synthetic_authority(tmp_path)
    extra = fixture.parent / "new.py"
    extra.write_text("value = 2\n", encoding="utf-8")

    with pytest.raises(authority.FixtureAuthorityError, match="does not cover"):
        authority.validate_fixture_manifest(tmp_path, manifest)


def test_malformed_fixture_requires_explicit_malformed_shape(tmp_path: Path) -> None:
    manifest, _, _ = _write_synthetic_authority(
        tmp_path, source="def broken(:\n", shape="malformed"
    )
    assert authority.validate_fixture_manifest(tmp_path, manifest)["status"] == "passed"

    malformed_manifest, _, _ = _write_synthetic_authority(
        tmp_path / "valid-shape", source="def broken(:\n", shape="valid"
    )
    with pytest.raises(authority.FixtureAuthorityError, match="does not parse"):
        authority.validate_fixture_manifest(tmp_path / "valid-shape", malformed_manifest)


def test_inert_fixture_execution_in_consumer_fails_closed(tmp_path: Path) -> None:
    manifest, _, _ = _write_synthetic_authority(
        tmp_path,
        consumer_source=(
            "from pathlib import Path\n"
            "import subprocess\n"
            "fixture = Path('src/test/fixtures/case/sample.py')\n"
            "subprocess.run([str(fixture)])\n"
        ),
    )

    with pytest.raises(authority.FixtureAuthorityError, match="executable consumer"):
        authority.validate_fixture_manifest(tmp_path, manifest)


def test_inert_fixture_source_execution_construct_fails_closed(tmp_path: Path) -> None:
    manifest, _, _ = _write_synthetic_authority(
        tmp_path, source="import subprocess\nsubprocess.run(['echo'])\n"
    )

    with pytest.raises(authority.FixtureAuthorityError, match="executable construct"):
        authority.validate_fixture_manifest(tmp_path, manifest)


@pytest.mark.parametrize("source", [
    "from builtins import eval as evaluate\nevaluate('1')\n",
    "import builtins as b\nb.exec('value = 1')\n",
    "from os import execv as launch\nlaunch('python', ['python'])\n",
    "import os\nos.fork()\n",
    "import os\nos.posix_spawn('python', ['python'], {})\n",
    "from subprocess import getoutput as launch\nlaunch('python')\n",
    "import subprocess\nsubprocess.getstatusoutput('python')\n",
    "from multiprocessing import Process as Worker\nWorker()\n",
    "import multiprocessing.pool\nmultiprocessing.pool.Pool()\n",
    "import ctypes\nctypes.CDLL('fixture')\n",
    "from pty import spawn as launch\nlaunch(['python'])\n",
])
def test_inert_fixture_execution_aliases_fail_without_execution(
    tmp_path: Path, source: str,
) -> None:
    manifest, _, _ = _write_synthetic_authority(tmp_path, source=source)
    with pytest.raises(authority.FixtureAuthorityError, match="executable construct"):
        authority.validate_fixture_manifest(tmp_path, manifest)


def test_executable_fixture_requires_static_execution_evidence(tmp_path: Path) -> None:
    manifest, _, _ = _write_synthetic_authority(
        tmp_path, role="executable_first_party"
    )

    with pytest.raises(authority.FixtureAuthorityError, match="lacks"):
        authority.validate_fixture_manifest(tmp_path, manifest)


@pytest.mark.parametrize("role", ("generated", "vendor"))
def test_generated_or_vendor_role_requires_specific_provenance(
    tmp_path: Path, role: str,
) -> None:
    manifest, _, _ = _write_synthetic_authority(
        tmp_path,
        role=role,
        provenance={
            "producer": "generated",
            "evidence_path": "tools/evidence.txt",
            "evidence_sha256": "0" * 64,
        },
    )

    with pytest.raises(authority.FixtureAuthorityError, match="provenance is generic"):
        authority.load_manifest(manifest)


def test_generated_provenance_binds_evidence_content(tmp_path: Path) -> None:
    manifest, _, _ = _write_synthetic_authority(tmp_path, role="generated")
    evidence = tmp_path / "tools/evidence.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("producer record\n", encoding="utf-8")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["entries"][0]["provenance"] = {
        "producer": "fixture compiler v1",
        "evidence_path": "tools/evidence.txt",
        "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
    }
    manifest.write_text(json.dumps(document), encoding="utf-8")

    assert authority.validate_fixture_manifest(tmp_path, manifest)["status"] == "passed"
    evidence.write_text("changed producer record\n", encoding="utf-8")
    with pytest.raises(authority.FixtureAuthorityError, match="evidence drift"):
        authority.validate_fixture_manifest(tmp_path, manifest)


def test_consumer_must_parse_and_name_fixture_family(tmp_path: Path) -> None:
    manifest, _, _ = _write_synthetic_authority(
        tmp_path, consumer_source="value = 'unrelated'\n"
    )

    with pytest.raises(authority.FixtureAuthorityError, match="does not statically name"):
        authority.validate_fixture_manifest(tmp_path, manifest)


def test_unlisted_consumer_execution_fails_closed(tmp_path: Path) -> None:
    manifest, _, _ = _write_synthetic_authority(tmp_path)
    hidden = tmp_path / "src/test/unit/python/hidden.py"
    hidden.write_text(
        "from pathlib import Path\n"
        "from subprocess import run\n"
        "fixture = Path('src/test/fixtures/case/sample.py')\n"
        "run([str(fixture)])\n",
        encoding="utf-8",
    )

    with pytest.raises(authority.FixtureAuthorityError, match="unlisted executable"):
        authority.validate_fixture_manifest(tmp_path, manifest)


def test_unlisted_fixture_import_fails_closed(tmp_path: Path) -> None:
    manifest, _, _ = _write_synthetic_authority(tmp_path)
    hidden = tmp_path / "src/test/unit/python/hidden_import.py"
    hidden.write_text(
        "from src.test.fixtures.case.sample import value\n"
        "assert value == 1\n",
        encoding="utf-8",
    )

    with pytest.raises(authority.FixtureAuthorityError, match="unlisted executable"):
        authority.validate_fixture_manifest(tmp_path, manifest)


def test_manifest_rejects_role_mode_mismatch(tmp_path: Path) -> None:
    manifest, _, _ = _write_synthetic_authority(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["entries"][0]["consumption_mode"] = "direct_execution"
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(authority.FixtureAuthorityError, match="role and consumption"):
        authority.load_manifest(manifest)


def test_empty_authority_is_valid_for_empty_fixture_census(tmp_path: Path) -> None:
    (tmp_path / authority.FIXTURE_ROOT).mkdir(parents=True)
    manifest = tmp_path / "tools/ci/python_fixture_authority.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema": authority.SCHEMA,
                "version": 1,
                "fixture_root": authority.FIXTURE_ROOT,
                "entries": [],
            }
        ),
        encoding="utf-8",
    )

    result = authority.validate_fixture_manifest(tmp_path, manifest)
    assert result["status"] == "passed"
    assert result["entry_count"] == 0
