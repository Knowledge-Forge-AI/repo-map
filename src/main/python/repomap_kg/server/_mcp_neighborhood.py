"""Configured neighborhood schema and strict opt-in limit validation."""

from typing import Any

from repomap_kg.server._ops_records import McpOpsError


def neighborhood_properties() -> dict[str, Any]:
    return {
        "graph_id": {"type": "string"},
        "node": {"type": "string"},
        "direction": {"type": "string", "enum": ["both", "in", "out"], "default": "both"},
        "depth": {"type": "integer", "default": 1},
        "node_limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "edge_limit": {"type": "integer", "minimum": 1, "maximum": 100},
    }


def optional_neighborhood_limit(name: str, value: Any) -> int | None:
    """Ellipsis means omitted; an explicitly supplied null is invalid."""
    if value is Ellipsis:
        return None
    if type(value) is not int or not 1 <= value <= 100:
        raise McpOpsError(f"{name} must be an integer between 1 and 100")
    return value
