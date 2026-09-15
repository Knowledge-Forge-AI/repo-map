"""One deliberately failing test, launched as a standalone pytest subprocess.

See `passing.test.py` for why this lives outside `testpaths`: it must fail when
it is run, so the ordinary suite must never collect it.
"""

import json
import os
from pathlib import Path


def test_fails_on_purpose(tmp_path):
    Path(os.environ["DIRECT_PYTEST_RECORD"]).write_text(
        json.dumps({"tmp_path": str(tmp_path)}), encoding="utf-8"
    )
    assert False, "this fixture fails on purpose"
