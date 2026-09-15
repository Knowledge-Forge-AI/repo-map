"""One passing test, launched as a standalone pytest subprocess.

Lives outside `testpaths` and outside both `TEST_ROOTS`, so the ordinary suite
never collects it, but still beneath `src/test/` so the common conftest — the
thing actually under test — is loaded exactly as it would be for a real direct
invocation.
"""

import json
import os
from pathlib import Path


def test_records_where_its_temporary_directory_resolved(tmp_path):
    Path(os.environ["DIRECT_PYTEST_RECORD"]).write_text(
        json.dumps({"tmp_path": str(tmp_path)}), encoding="utf-8"
    )
    assert tmp_path.is_dir()
