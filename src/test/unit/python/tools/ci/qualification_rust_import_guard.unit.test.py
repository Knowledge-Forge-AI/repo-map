"""Execute the real import hook in a fresh interpreter without host parser imports."""

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[6]


@pytest.mark.parametrize("fault", ["none", "absent", "drift"])
def test_pinned_import_guard_refuses_unbound_or_changed_source(tmp_path: Path, fault: str) -> None:
    code = r'''
from pathlib import Path
import hashlib, importlib.util, sys
root, temporary, fault = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(root / "tools"))
from ci.qualification_rust_import_guard import HostImportRefused, host_import_guard
tools = temporary / "tools"
tools.mkdir()
source = tools / "qualification_guard_fixture.py"
source.write_bytes(b"raise AssertionError('find_spec must not execute the fixture')\n")
digests = {"tools/qualification_guard_fixture.py": hashlib.sha256(source.read_bytes()).hexdigest()}
if fault == "absent":
    digests.clear()
elif fault == "drift":
    source.write_bytes(source.read_bytes() + b"# changed\n")
sys.path.insert(0, str(tools))
before = tuple(sys.meta_path)
try:
    with host_import_guard(temporary, digests):
        spec = importlib.util.find_spec("qualification_guard_fixture")
        assert spec.origin == str(source)
except HostImportRefused:
    assert fault != "none"
else:
    assert fault == "none"
assert tuple(sys.meta_path) == before
assert "qualification_guard_fixture" not in sys.modules
'''
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(ROOT), str(tmp_path), fault],
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
