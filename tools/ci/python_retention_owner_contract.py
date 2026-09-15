"""Closed owner context for loader and generated measurement recipes.

These maintained source templates include imports, initializers, callers and
cleanup. A declaration digest cannot authorize a different surrounding program.
They are parsed as inert data and never executed.
"""

import ast

from ci.python_retention_owner_helper import SOURCE as HELPER
from ci.python_retention_owner_iso import SOURCE as ISO
from ci.python_retention_owner_base import SOURCE as BASE
from ci.python_retention_owner_sampling import SOURCE as SAMPLING
from ci.python_retention_owner_caller import SOURCE as CALLER
from ci.python_retention_owner_arcs import SOURCE as ARCS
from ci.python_retention_owner_capability import SOURCE as CAPABILITY

CONTRACTS = {
    "src/test/unit/python/repomap_kg/ingestion_api_bulk/helper_branches.unit.test.py": HELPER,
    "src/test/unit/python/tools/test_iso1_runner.unit.test.py": ISO,
    "src/test/unit/python/tools/scale28_r1_dependency_boundary.unit.test.py": BASE,
    "src/test/unit/python/tools/scale28_r1_psutil_readers.unit.test.py": SAMPLING,
    "src/test/unit/python/tools/test_runner_coverage_child.unit.test.py": CALLER,
    "src/test/unit/python/tools/test_runner_coverage_child_export.unit.test.py": ARCS,
    "src/test/unit/python/tools/test_runner_coverage_capability.unit.test.py": CAPABILITY,
}


def validate_owner_context(owner: str, tree: ast.Module) -> None:
    """Reject changed bindings, callers, fixture lifetime or measurement ownership."""
    source = CONTRACTS.get(owner)
    if source is None:
        raise ValueError("closed recipe has no maintained owner contract")
    if ast.dump(tree, include_attributes=False) != ast.dump(ast.parse(source), include_attributes=False):
        raise ValueError("closed recipe owner context differs from maintained contract")
