"""Runtime coercion and invalid-input assertions for MCP helper tests."""

from collections.abc import Callable
from typing import Any
from unittest import TestCase

from repomap_kg.server import ops as mcp_ops


def assert_mcp_validation_cases(case: TestCase) -> None:
    case.assertEqual(mcp_ops.validate_query("  repo  "), "repo")
    case.assertEqual(mcp_ops.validate_limit(500), mcp_ops.MAX_SEARCH_LIMIT)
    # These fixtures intentionally exercise coercion and invalid runtime inputs.
    coercible_offset: Any = "3"
    case.assertEqual(mcp_ops.validate_offset(coercible_offset), 3)
    invalid_cases: tuple[tuple[Callable[[Any], object], Any], ...] = (
        (mcp_ops.validate_query, ""),
        (mcp_ops.validate_query, "x" * (mcp_ops.MAX_QUERY_LENGTH + 1)),
        (mcp_ops.validate_limit, 0),
        (mcp_ops.validate_limit, "bad"),
        (mcp_ops.validate_offset, -1),
        (mcp_ops.validate_offset, "bad"),
    )
    for func, value in invalid_cases:
        with case.subTest(helper=func.__name__, value=value):
            with case.assertRaises(mcp_ops.McpOpsError):
                func(value)
