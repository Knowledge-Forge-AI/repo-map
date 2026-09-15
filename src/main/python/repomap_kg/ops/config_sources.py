"""Source placeholder parsing for RepoMap local operations configuration."""

from __future__ import annotations

from typing import Any

from repomap_kg.ops.config_helpers import (
    OpsConfigDiagnostic,
    required_bool,
    required_text,
    unknown_field_diagnostics,
)
from repomap_kg.ops.config_records import OpsSourcePlaceholder, OpsSourcesConfig


def parse_sources_section(payload: Any) -> tuple[OpsSourcesConfig, list[OpsConfigDiagnostic]]:
    diagnostics: list[OpsConfigDiagnostic] = []
    if payload is None:
        return OpsSourcesConfig(), diagnostics
    if not isinstance(payload, dict):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "invalid-sources-section",
                "sources",
                "sources must be a table",
            )
        )
        return OpsSourcesConfig(), diagnostics
    known_sources = frozenset(("feed", "github", "api"))
    diagnostics.extend(unknown_field_diagnostics(payload, known_sources, "sources"))
    feed = parse_source_placeholders(payload.get("feed", []), "feed", diagnostics)
    github = parse_source_placeholders(
        payload.get("github", []), "github", diagnostics
    )
    api = parse_source_placeholders(payload.get("api", []), "api", diagnostics)
    return OpsSourcesConfig(feed=feed, github=github, api=api), diagnostics


def parse_source_placeholders(
    payload: Any,
    source_type: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> tuple[OpsSourcePlaceholder, ...]:
    if payload in (None, {}):
        return ()
    if not isinstance(payload, list):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "invalid-source-section",
                f"sources.{source_type}",
                "source section must be an array of tables",
            )
        )
        return ()
    sources: list[OpsSourcePlaceholder] = []
    for index, item in enumerate(payload):
        path = f"sources.{source_type}[{index}]"
        if not isinstance(item, dict):
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "invalid-source-entry",
                    path,
                    "source entry must be a table",
                )
            )
            continue
        source_id = required_text(item, "id", f"{path}.id", diagnostics)
        graph_id = required_text(item, "graph_id", f"{path}.graph_id", diagnostics)
        enabled = required_bool(item, "enabled", f"{path}.enabled", diagnostics)
        metadata = {
            key: value
            for key, value in item.items()
            if key not in ("id", "graph_id", "enabled")
        }
        if enabled:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "source-acquisition-deferred",
                    f"{path}.enabled",
                    f"{source_type} source {source_id!r} is parsed but not acquired",
                )
            )
        sources.append(
            OpsSourcePlaceholder(
                source_type=source_type,
                id=source_id or "",
                graph_id=graph_id or "",
                enabled=bool(enabled),
                metadata=metadata,
            )
        )
    return tuple(sources)
