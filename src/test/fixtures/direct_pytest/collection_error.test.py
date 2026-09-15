"""One collection error, launched as a standalone pytest subprocess.

The error is a failed module-level import rather than a syntax error, so the
file stays valid Python and repository-wide byte-compilation and length checks
still parse it. pytest fails collection either way, which is what the lifecycle
test needs.

See `passing.test.py` for why this lives outside `testpaths`.
"""

import importlib

importlib.import_module("repomap_kg_module_that_does_not_exist")


def test_never_runs() -> None:
    raise AssertionError("collection fails before this can run")
