#!/usr/bin/env python3
"""Deterministic Coverage 7.15.4 runtime characterization and causal evidence generator."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE_PATH = REPO_ROOT / "tools/test_sandbox/Dockerfile"
LOCKFILE_PATH = REPO_ROOT / "tools/ci/pre_review_python.lock"
EVIDENCE_DIR = REPO_ROOT / "tools/ci/evidence"
DEFAULT_IMAGE = "repomap-test-sandbox:py313-go125-docker294-v1"


def get_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_container_cmd(image: str, command: str) -> str:
    res = subprocess.run(
        ["docker", "run", "--rm", image, "sh", "-c", command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def generate_characterization(image: str) -> dict[str, object]:
    probe_script = r"""
python3 -c '
import base64, glob, hashlib, inspect, json, os, site, sys
import coverage

sp_dirs = site.getsitepackages()
cov_loc = os.path.dirname(coverage.__file__)
loc_class = "site_packages" if any(cov_loc.startswith(sp) for sp in sp_dirs) else "other"
pths = glob.glob(sp_dirs[0] + "/*.pth")
a1_pth = next((p for p in pths if os.path.basename(p) == "a1_coverage.pth"), None)
pth_len = 0
pth_sha = ""
pth_b64 = ""
pth_has_process_startup = False
if a1_pth and os.path.isfile(a1_pth):
    raw = open(a1_pth, "rb").read()
    pth_len = len(raw)
    pth_sha = hashlib.sha256(raw).hexdigest()
    pth_b64 = base64.b64encode(raw).decode("ascii")
    pth_has_process_startup = b"coverage.process_startup" in raw

import importlib.util
sc_spec = importlib.util.find_spec("sitecustomize")
sc_origin = "absent"
if sc_spec is not None:
    origin_str = str(sc_spec.origin or "")
    sc_origin = "site_packages" if any(origin_str.startswith(sp) for sp in sp_dirs) else "other"

assert coverage.__version__ == "7.15.4", f"Expected coverage 7.15.4, got {coverage.__version__}"
sig = inspect.signature(coverage.process_startup)
sig_params = {k: str(v.default) for k, v in sig.parameters.items()}

out = {
    "python_version": sys.version.split()[0],
    "coverage_version": coverage.__version__,
    "coverage_location_classification": loc_class,
    "pth_relative_location": os.path.basename(a1_pth) if a1_pth else None,
    "pth_byte_length": pth_len,
    "pth_sha256": pth_sha,
    "pth_safe_base64": pth_b64,
    "sitecustomize_present": sc_spec is not None,
    "sitecustomize_origin": sc_origin,
    "process_startup_origin": getattr(coverage.process_startup, "__module__", "unknown"),
    "process_startup_parameters": sig_params,
    "hypothesis_verdict": (
        "confirmed_a1_coverage_pth_installed_by_coverage_wheel"
        if a1_pth and pth_has_process_startup
        else "disproved_a1_coverage_pth_hypothesis"
    ),
}
print(json.dumps(out))
'
"""
    raw_json = run_container_cmd(image, probe_script)
    payload = json.loads(raw_json)

    return {
        "schema": "repomap-coverage-runtime-evidence-v1",
        "provenance": {
            "dockerfile_sha256": get_file_sha256(DOCKERFILE_PATH),
            "lockfile_sha256": get_file_sha256(LOCKFILE_PATH),
            "image_classification": "test_sandbox_monolithic_dind",
        },
        "characterization": payload,
    }


def generate_causal_reproduction(image: str) -> dict[str, object]:
    causal_script = r"""
python3 -c '
import json, os, site, sqlite3, subprocess, tempfile

def test_case():
    with tempfile.TemporaryDirectory() as td:
        rc_path = os.path.join(td, ".coveragerc")
        cov_data = os.path.join(td, ".coverage")
        with open(rc_path, "w") as f:
            f.write(f"[run]\ndata_file = {cov_data}\n")
        app_path = os.path.join(td, "app.py")
        with open(app_path, "w") as f:
            f.write("def run():\n    return 42\nrun()\n")
        
        env = dict(os.environ, COVERAGE_PROCESS_START=rc_path)
        cmd = ["python3", app_path]
        res = subprocess.run(cmd, env=env, cwd=td, capture_output=True, text=True)
        created = os.path.exists(cov_data)
        schema_ver = None
        file_count = 0
        if created:
            try:
                conn = sqlite3.connect(f"file:{cov_data}?mode=ro", uri=True)
                cursor = conn.cursor()
                cursor.execute("SELECT version FROM coverage_schema LIMIT 1")
                row = cursor.fetchone()
                schema_ver = row[0] if row else None
                cursor.execute("SELECT COUNT(*) FROM file")
                cnt_row = cursor.fetchone()
                file_count = cnt_row[0] if cnt_row else 0
                conn.close()
            except sqlite3.Error:
                schema_ver = None
                file_count = 0
        return {
            "exit_code": res.returncode,
            "shard_created": created,
            "schema_version": schema_ver,
            "measured_file_count": file_count,
        }

res_with = test_case()
sp_dirs = site.getsitepackages()
pth = os.path.join(sp_dirs[0], "a1_coverage.pth")
pth_bak = pth + ".disabled"
if os.path.exists(pth):
    os.rename(pth, pth_bak)
try:
    res_without = test_case()
finally:
    if os.path.exists(pth_bak):
        os.rename(pth_bak, pth)

out = {
    "scenario_with_a1_coverage_pth": res_with,
    "scenario_without_a1_coverage_pth": res_without,
    "causal_mechanism_verified": (
        res_with["shard_created"] is True
        and res_without["shard_created"] is False
    ),
    "causal_verdict": (
        "a1_coverage_pth_is_causal_mechanism"
        if res_with["shard_created"] and not res_without["shard_created"]
        else "hypothesis_not_confirmed"
    ),
}
print(json.dumps(out))
'
"""
    raw_json = run_container_cmd(image, causal_script)
    payload = json.loads(raw_json)

    return {
        "schema": "repomap-coverage-causal-reproduction-v1",
        "provenance": {
            "dockerfile_sha256": get_file_sha256(DOCKERFILE_PATH),
            "lockfile_sha256": get_file_sha256(LOCKFILE_PATH),
        },
        "causal_evidence": payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="sandbox docker image")
    args = parser.parse_args()

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    char_data = generate_characterization(args.image)
    char_file = EVIDENCE_DIR / "coverage-runtime-7.15.4.json"
    char_file.write_text(json.dumps(char_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote characterization evidence: {char_file}")

    causal_data = generate_causal_reproduction(args.image)
    causal_file = EVIDENCE_DIR / "coverage-runtime-7.15.4-causal-reproduction.json"
    causal_file.write_text(json.dumps(causal_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote causal reproduction evidence: {causal_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
