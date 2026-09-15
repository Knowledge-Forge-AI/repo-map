"""Common pytest scratch ownership.

``tools/run_tests.py`` is the primary owner and exports
``REPOMAP_TEST_RUN_ROOT`` before pytest starts. This conftest exists so that a
direct invocation such as ``pytest src/test/unit/python/...`` receives the same
authority instead of writing to the platform temporary directory.

The layout is applied at import time, not from ``pytest_configure``. pytest's
own tmpdir plugin builds its ``TempPathFactory`` from a ``tryfirst``
``pytest_configure`` hook, and a conftest's hook runs after that, which would
be too late to redirect ``basetemp``. Applying the environment while this
module is imported — during initial conftest collection — happens first, so
``TMPDIR`` is already the run root's own directory by the time pytest chooses
where to put its temporary tree.

That gives two different but equally owned spellings, and only one of them is
pinned:

* under ``tools/run_tests.py``, the runner passes an explicit
  ``--basetemp <run>/pt``;
* a standalone ``pytest`` uses pytest's own generated basename beneath
  ``<run>/tmp``.

Both stay inside the one run root, which is what the ownership contract
actually requires. A conftest cannot pin the standalone spelling to ``<run>/pt``
— see ``pytest_sessionfinish`` below for what it can own — and forcing it would
mean shipping this file as an installed plugin, which is not worth a cosmetic
path difference.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SUPPORT_ROOT = Path(__file__).resolve().parent / "support" / "python"
if str(_SUPPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUPPORT_ROOT))

from repomap_test_support.test_scratch import (  # noqa: E402
    ENV_RUN_ROOT,
    establish_run,
    finalize_run,
)
from repomap_test_support.build_profile_debt import (  # noqa: E402
    enforce_build_profile_authority,
)
from repomap_test_support.resource_run_test_support import (  # noqa: E402
    preserve_resource_run_process_state,
)

# Reuses an inherited REPOMAP_TEST_RUN_ROOT when the runner already allocated
# one, so a direct pytest invocation under the runner never creates a second
# run root.
_LAYOUT = establish_run().apply()


def pytest_report_header(config):
    return f"repomap test scratch: {_LAYOUT.run_root.name} ({ENV_RUN_ROOT})"


@pytest.fixture
def isolate_test_resource_run_process_state():
    """Prevent allocating-owner unit seams from poisoning later tests."""
    with preserve_resource_run_process_state():
        yield


def pytest_runtest_setup(item):
    """Refuse direct execution of visible build debt without build authority."""
    if item.get_closest_marker("requires_build_profile") is not None:
        enforce_build_profile_authority()


def pytest_sessionfinish(session, exitstatus):
    """Close the run this pytest process allocated.

    This is the one lifecycle owner for a standalone invocation. When pytest
    was launched by ``tools/run_tests.py`` the layout was inherited rather than
    allocated, so ``finalize_run`` returns without writing and the runner stays
    the terminal owner of its own run — there are never two finalizers
    competing for one manifest.

    Deliberately not an ``atexit`` handler: a process killed outright should
    leave its manifest ``running`` for an operator to find, rather than being
    reported as a clean finish it never had.
    """
    finalize_run(
        _LAYOUT,
        "passed" if int(exitstatus) == 0 else "failed",
        exit_status=int(exitstatus),
    )
