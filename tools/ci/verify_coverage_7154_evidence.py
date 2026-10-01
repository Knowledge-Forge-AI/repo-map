"""Verify coverage 7.15.4 runtime characterization and causal reproduction evidence.

Verifies evidence artifacts in tools/ci/evidence/ against source Dockerfile,
lockfile, and expected causal invariants.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sys


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_evidence(repo_root: Path | None = None) -> bool:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent

    evidence_dir = repo_root / "tools" / "ci" / "evidence"
    dockerfile_path = repo_root / "tools" / "test_sandbox" / "Dockerfile"
    lockfile_path = repo_root / "tools" / "ci" / "pre_review_python.lock"

    if not dockerfile_path.is_file():
        raise FileNotFoundError(f"Missing Dockerfile: {dockerfile_path}")
    if not lockfile_path.is_file():
        raise FileNotFoundError(f"Missing lockfile: {lockfile_path}")

    expected_dockerfile_sha = _sha256_of_file(dockerfile_path)
    expected_lockfile_sha = _sha256_of_file(lockfile_path)

    char_path = evidence_dir / "coverage-runtime-7.15.4.json"
    causal_path = evidence_dir / "coverage-runtime-7.15.4-causal-reproduction.json"

    if not char_path.is_file():
        raise FileNotFoundError(f"Missing characterization evidence: {char_path}")
    if not causal_path.is_file():
        raise FileNotFoundError(f"Missing causal reproduction evidence: {causal_path}")

    # 1. Verify characterization evidence
    with open(char_path, "r", encoding="utf-8") as f:
        char_data = json.load(f)

    if char_data.get("schema") != "repomap-coverage-runtime-evidence-v1":
        raise ValueError(f"Unexpected characterization schema: {char_data.get('schema')}")

    char_prov = char_data.get("provenance", {})
    if char_prov.get("dockerfile_sha256") != expected_dockerfile_sha:
        raise ValueError(
            f"Characterization dockerfile SHA mismatch: {char_prov.get('dockerfile_sha256')} vs {expected_dockerfile_sha}"
        )
    if char_prov.get("lockfile_sha256") != expected_lockfile_sha:
        raise ValueError(
            f"Characterization lockfile SHA mismatch: {char_prov.get('lockfile_sha256')} vs {expected_lockfile_sha}"
        )

    char_body = char_data.get("characterization", {})
    if char_body.get("coverage_version") != "7.15.4":
        raise ValueError(f"Unexpected coverage version: {char_body.get('coverage_version')}")

    pth_b64 = char_body.get("pth_safe_base64", "")
    pth_raw = base64.b64decode(pth_b64)
    if len(pth_raw) != char_body.get("pth_byte_length"):
        raise ValueError("Decoded pth byte length mismatch")
    actual_pth_sha = hashlib.sha256(pth_raw).hexdigest()
    if actual_pth_sha != char_body.get("pth_sha256"):
        raise ValueError(f"PTH sha256 mismatch: {actual_pth_sha} vs {char_body.get('pth_sha256')}")

    # Recompute hypothesis verdict from observed evidence properties
    has_pth = char_body.get("pth_relative_location") == "a1_coverage.pth"
    has_process_startup = b"coverage.process_startup" in pth_raw
    expected_verdict = (
        "confirmed_a1_coverage_pth_installed_by_coverage_wheel"
        if has_pth and has_process_startup
        else "disproved_a1_coverage_pth_hypothesis"
    )
    if char_body.get("hypothesis_verdict") != expected_verdict:
        raise ValueError(f"Hypothesis verdict mismatch: {char_body.get('hypothesis_verdict')} vs {expected_verdict}")

    # 2. Verify causal reproduction evidence
    with open(causal_path, "r", encoding="utf-8") as f:
        causal_data = json.load(f)

    if causal_data.get("schema") != "repomap-coverage-causal-reproduction-v1":
        raise ValueError(f"Unexpected causal schema: {causal_data.get('schema')}")

    causal_prov = causal_data.get("provenance", {})
    if causal_prov.get("dockerfile_sha256") != expected_dockerfile_sha:
        raise ValueError("Causal dockerfile SHA mismatch")
    if causal_prov.get("lockfile_sha256") != expected_lockfile_sha:
        raise ValueError("Causal lockfile SHA mismatch")

    causal_body = causal_data.get("causal_evidence", {})
    with_pth = causal_body.get("scenario_with_a1_coverage_pth", {})
    without_pth = causal_body.get("scenario_without_a1_coverage_pth", {})

    with_created = bool(with_pth.get("shard_created"))
    without_created = bool(without_pth.get("shard_created"))
    with_count = with_pth.get("measured_file_count")
    without_count = without_pth.get("measured_file_count")
    if not isinstance(with_count, int) or not isinstance(without_count, int):
        raise ValueError(f"Invalid scenario measured_file_count: with={with_count}, without={without_count}")

    is_causal = with_created and with_count > 0 and not without_created and without_count == 0
    expected_causal_verdict = (
        "a1_coverage_pth_is_causal_mechanism"
        if is_causal
        else "hypothesis_not_confirmed"
    )
    if causal_body.get("causal_verdict") != expected_causal_verdict:
        raise ValueError(f"Unexpected causal verdict: {causal_body.get('causal_verdict')} vs {expected_causal_verdict}")
    if causal_body.get("causal_mechanism_verified") != is_causal:
        raise ValueError("Causal mechanism verification mismatch")

    return True


def main() -> int:
    try:
        verify_evidence()
        print("Coverage 7.15.4 runtime evidence verified successfully.")
        return 0
    except Exception as exc:
        print(f"Coverage 7.15.4 runtime evidence verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
