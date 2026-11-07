"""Stable negative safety evidence for operations report payloads."""

from __future__ import annotations


def _refresh_safety_markers() -> dict[str, bool]:
    return {
        "source_trees_mutated": False,
        "destructive_db_actions": False,
        "server_memory_read": False,
        "source_acquisition": False,
        "expanded_mcp_tools": False,
        "remote_exposure": False,
        "watch_daemon_started": False,
    }


def _preflight_safety_markers() -> dict[str, bool]:
    return {
        "storage_written": False,
        "source_tree_mutated": False,
        "server_memory_mutated": False,
        "server_memory_read": False,
        "source_acquisition": False,
        "destructive_db_actions": False,
        "remote_exposure": False,
        "watch_daemon_started": False,
    }


def _graph_readback_safety_markers() -> dict[str, bool]:
    return {
        "graph_root_read": False,
        "storage_written": False,
        "source_tree_mutated": False,
        "server_memory_mutated": False,
        "server_memory_read": False,
        "source_acquisition": False,
        "destructive_db_actions": False,
        "remote_exposure": False,
        "watch_daemon_started": False,
    }


__all__ = [
    "_graph_readback_safety_markers",
    "_preflight_safety_markers",
    "_refresh_safety_markers",
]
