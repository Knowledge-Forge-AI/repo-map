"""Shared PowerShell extractor lexical and redaction helpers."""

from __future__ import annotations

import posixpath
import re

from repomap_kg import __version__
from repomap_kg.observations.raw import RawObservation


EXTRACTOR_NAME = "repo-powershell"
SLUG_PATTERN = re.compile(r"[^0-9A-Za-z_.]+")
SECRET_MARKERS = (
    "password",
    "secret",
    "token",
    "key",
    "credential",
    "apikey",
    "pat",
)
SECRET_EXACT_NAMES = frozenset({"authorization"})


def _is_secret_like_name(name: str) -> bool:
    normalized = re.sub(r"[^0-9a-z]+", "", name.lower())
    if normalized in SECRET_EXACT_NAMES or normalized in SECRET_MARKERS:
        return True
    words = [
        item.lower()
        for item in re.findall(
            r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+",
            re.sub(r"[^0-9A-Za-z]+", " ", name),
        )
    ]
    if any(word in SECRET_MARKERS for word in words):
        return True
    return any(
        marker != "pat" and marker in normalized for marker in SECRET_MARKERS
    )


def _is_dynamic_token(token: str) -> bool:
    stripped = _strip_quotes(token)
    return "$" in stripped or stripped.startswith("&") or not stripped


def _strip_quotes(value: str) -> str:
    stripped = value.strip().rstrip(",;")
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _redacted_token_summary(token: str) -> str:
    stripped = token.strip()
    if not stripped:
        return "[empty]"
    if _is_secret_like_name(stripped):
        return "[redacted]"
    if len(stripped) > 80:
        return f"{stripped[:77]}..."
    return stripped


def slug(value: str) -> str:
    return SLUG_PATTERN.sub("-", value).strip("-").lower() or "powershell"


def _resolve_static_path(relative_path: str, token: str) -> str | None:
    normalized_token = _strip_quotes(token).replace("\\", "/")
    base = posixpath.dirname(relative_path)
    if normalized_token.lower().startswith("$psscriptroot/"):
        normalized_token = "." + normalized_token[len("$PSScriptRoot") :]
    if normalized_token.startswith("./") or normalized_token.startswith("../"):
        resolved = posixpath.normpath(posixpath.join(base, normalized_token))
        if resolved == "." or resolved.startswith("../"):
            return None
        return resolved
    return None


def _secret_like_observation(
    relative_path: str,
    start_line: int,
    name: str,
    *,
    secret_source: str,
    reason: str,
    end_line: int | None = None,
) -> RawObservation:
    return RawObservation(
        kind="powershell.secret_like",
        source_id=f"{relative_path}#secret-like:{start_line}:{slug(secret_source)}:{slug(name)}",
        path=relative_path,
        start_line=start_line,
        end_line=end_line or start_line,
        name=name,
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "secret_source": secret_source,
            "redacted": True,
            "redaction_reason": reason,
            "raw_value_stored": False,
            "static_only": True,
        },
    )
