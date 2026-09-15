"""Repository-bounded path resolution for static Nix extraction."""

from __future__ import annotations

from pathlib import PurePosixPath


def resolve_repo_path(relative_path: str, literal: str) -> str | None:
    clean_literal = literal.strip().rstrip(";,)]}").strip()
    if clean_literal.startswith("${self}/"):
        return _normalize_path_components(clean_literal.removeprefix("${self}/"))
    if not (clean_literal.startswith("./") or clean_literal.startswith("../")):
        return None
    base = PurePosixPath(relative_path.replace("\\", "/")).parent
    return _normalize_path_components(str(base / clean_literal))


def _normalize_path_components(path: str) -> str | None:
    parts: list[str] = []
    for part in path.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "." if not parts else "/".join(parts)


__all__ = ["resolve_repo_path"]
