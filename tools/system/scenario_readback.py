"""Bounded JSON and fixture status checks shared by system publication phases."""

from __future__ import annotations

import json
from typing import Any

from tools.system.config import SystemTestError

def _parse_json(stdout: str, message: str, *, include_output: bool = False) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        detail = f": {stdout}" if include_output else ""
        raise SystemTestError(f"{message}{detail}") from error
    if not isinstance(payload, dict):
        raise SystemTestError(f"{message} returned a non-object")
    return payload

def _fixture_status(payload: dict[str, Any], message: str) -> dict[str, Any]:
    graphs = payload.get("graphs", [])
    if not isinstance(graphs, list):
        raise SystemTestError("refresh-status graphs field is not a list")
    matches = [row for row in graphs if isinstance(row, dict) and row.get("graph_id") == "fixture"]
    if len(matches) != 1:
        raise SystemTestError(message)
    return matches[0]

