"""Static Go file, module, and workspace metadata extraction."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath

from repomap_kg.extractors.languages.go_metadata_scanner import scan_go_directives
from repomap_kg.extractors.languages.go_metadata_support import (
    EXTRACTOR,
    EXTRACTOR_VERSION,
    local_target as _local_target,
    module_target as _module_target,
    observation as _observation,
    require_fields as _require_fields,
    retract_bounds as _retract_bounds,
)
from repomap_kg.observations.raw import RawObservation


GOOS_NAMES = frozenset(
    {
        "aix",
        "android",
        "darwin",
        "dragonfly",
        "freebsd",
        "illumos",
        "ios",
        "js",
        "linux",
        "netbsd",
        "openbsd",
        "plan9",
        "solaris",
        "wasip1",
        "windows",
    }
)
GOARCH_NAMES = frozenset(
    {
        "386",
        "amd64",
        "arm",
        "arm64",
        "loong64",
        "mips",
        "mips64",
        "mips64le",
        "mipsle",
        "ppc64",
        "ppc64le",
        "riscv64",
        "s390x",
        "wasm",
    }
)
MODULE_DIRECTIVES = frozenset(
    {"module", "go", "toolchain", "require", "replace", "exclude", "retract"}
)
WORKSPACE_DIRECTIVES = frozenset({"go", "toolchain", "use", "replace"})


def detect_go_generated_marker(content: str, max_lines: int = 40) -> int | None:
    for line_number, line in enumerate(content.splitlines()[:max_lines], start=1):
        if line.startswith("// Code generated ") and line.rstrip().endswith(
            " DO NOT EDIT."
        ):
            return line_number
        if line.lstrip().startswith("package "):
            return None
    return None


def detect_go_filename_constraints(
    relative_path: str,
) -> tuple[str | None, str | None, bool]:
    name = PurePosixPath(relative_path).name
    test_file = name.endswith("_test.go")
    stem = name[: -len("_test.go")] if test_file else name.removesuffix(".go")
    parts = stem.split("_")
    goos = None
    goarch = None
    if len(parts) >= 3 and parts[-2] in GOOS_NAMES and parts[-1] in GOARCH_NAMES:
        goos, goarch = parts[-2], parts[-1]
    elif len(parts) >= 2 and parts[-1] in GOOS_NAMES:
        goos = parts[-1]
    elif len(parts) >= 2 and parts[-1] in GOARCH_NAMES:
        goarch = parts[-1]
    return goos, goarch, test_file


def extract_go_metadata_observations(
    relative_path: str, content: str
) -> tuple[RawObservation, ...]:
    path = PurePosixPath(relative_path)
    if path.suffix == ".go":
        return (_go_file_observation(relative_path, content),)
    if path.name == "go.mod":
        return _metadata_observations(relative_path, content, document_kind="module")
    if path.name == "go.work":
        return _metadata_observations(
            relative_path, content, document_kind="workspace"
        )
    return ()


def _go_file_observation(relative_path: str, content: str) -> RawObservation:
    goos, goarch, test_file = detect_go_filename_constraints(relative_path)
    marker_line = detect_go_generated_marker(content)
    return RawObservation(
        kind="go.file",
        source_id=f"{relative_path}#go-file",
        path=relative_path,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=EXTRACTOR_VERSION,
        start_line=marker_line,
        end_line=marker_line,
        name=relative_path,
        metadata={
            "file_kind": "test" if test_file else "source",
            "test_file": test_file,
            "generated": marker_line is not None,
            "generated_marker_line": marker_line,
            "vendor": "vendor" in PurePosixPath(relative_path).parts,
            "goos": goos,
            "goarch": goarch,
            "static_only": True,
            "code_executed": False,
        },
    )

def _metadata_observations(
    relative_path: str, content: str, *, document_kind: str
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    ordinals: defaultdict[str, int] = defaultdict(int)
    owner_module_path: str | None = None
    allowed = MODULE_DIRECTIVES if document_kind == "module" else WORKSPACE_DIRECTIVES

    if document_kind == "workspace":
        observations.append(
            _observation(
                relative_path,
                "go.workspace",
                1,
                0,
                name=relative_path,
                metadata={"directive": "workspace"},
            )
        )

    for directive, fields, line_number, comment_text in scan_go_directives(content):
        ordinal = ordinals[directive]
        ordinals[directive] += 1
        if directive == "__parse_error__":
            observations.append(
                _observation(
                    relative_path,
                    "go.metadata_parse_error",
                    line_number,
                    ordinal,
                    name="document",
                    confidence="unknown",
                    metadata={
                        "directive": "document",
                        "error_kind": fields[0],
                        "bounded_message": fields[1][:160],
                    },
                )
            )
            continue
        if directive not in allowed:
            observations.append(
                _observation(
                    relative_path,
                    "go.metadata_unknown",
                    line_number,
                    ordinal,
                    name=directive,
                    confidence="unknown",
                    metadata={"directive": directive, "field_count": len(fields)},
                )
            )
            continue
        try:
            if document_kind == "module":
                new_items, owner_module_path = _module_directive_observations(
                    relative_path,
                    directive,
                    fields,
                    line_number,
                    ordinal,
                    comment_text,
                    owner_module_path,
                )
            else:
                new_items = _workspace_directive_observations(
                    relative_path,
                    directive,
                    fields,
                    line_number,
                    ordinal,
                )
            observations.extend(new_items)
        except ValueError as error:
            observations.append(
                _observation(
                    relative_path,
                    "go.metadata_parse_error",
                    line_number,
                    ordinal,
                    name=directive,
                    confidence="unknown",
                    metadata={
                        "directive": directive,
                        "error_kind": "invalid-directive",
                        "bounded_message": str(error)[:160],
                    },
                )
            )
    return tuple(observations)


def _module_directive_observations(
    path: str,
    directive: str,
    fields: tuple[str, ...],
    line: int,
    ordinal: int,
    comment_text: str,
    owner: str | None,
) -> tuple[tuple[RawObservation, ...], str | None]:
    owner_metadata = {"owner_module_path": owner} if owner else {}
    if directive == "module":
        _require_fields(directive, fields, 1)
        owner = fields[0]
        return (
            (
                _observation(
                    path,
                    "go.module",
                    line,
                    ordinal,
                    name=owner,
                    metadata={"directive": directive},
                ),
            ),
            owner,
        )
    if directive in {"go", "toolchain"}:
        _require_fields(directive, fields, 1)
        kind = "go.module_go_version" if directive == "go" else "go.module_toolchain"
        return (
            (
                _observation(
                    path,
                    kind,
                    line,
                    ordinal,
                    name=fields[0],
                    metadata={"directive": directive, **owner_metadata},
                ),
            ),
            owner,
        )
    if directive in {"require", "exclude"}:
        _require_fields(directive, fields, 2)
        kind = "go.module_require" if directive == "require" else "go.module_exclude"
        metadata = {"version": fields[1], **owner_metadata}
        if directive == "require":
            metadata["indirect"] = comment_text == "indirect"
        return (
            (
                _observation(
                    path,
                    kind,
                    line,
                    ordinal,
                    name=fields[0],
                    target=_module_target(fields[0], fields[1]),
                    metadata=metadata,
                ),
            ),
            owner,
        )
    if directive == "replace":
        replacement = _replacement_observation(
            path, "go.module_replace", fields, line, ordinal, owner_metadata
        )
        return ((replacement,), owner)
    if not fields:
        raise ValueError("retract requires a version or interval")
    value = " ".join(fields)
    low, high = _retract_bounds(value)
    observation = _observation(
        path,
        "go.module_retract",
        line,
        ordinal,
        name=value,
        metadata={
            "low": low,
            "high": high,
            "rationale_present": bool(comment_text),
            **owner_metadata,
        },
    )
    return ((observation,), owner)


def _workspace_directive_observations(
    path: str,
    directive: str,
    fields: tuple[str, ...],
    line: int,
    ordinal: int,
) -> tuple[RawObservation, ...]:
    owner = {"owner_workspace_path": path}
    if directive in {"go", "toolchain"}:
        _require_fields(directive, fields, 1)
        kind = "go.workspace_go_version" if directive == "go" else "go.workspace_toolchain"
        return (
            _observation(
                path,
                kind,
                line,
                ordinal,
                name=fields[0],
                metadata={"directive": directive, **owner},
            ),
        )
    if directive == "use":
        _require_fields(directive, fields, 1)
        normalized = _local_target(path, fields[0])
        return (
            _observation(
                path,
                "go.workspace_use",
                line,
                ordinal,
                name=normalized.removeprefix("file:"),
                target=normalized,
                metadata={
                    "resolved_under_root": normalized.startswith("file:"),
                    **owner,
                },
            ),
        )
    return (_replacement_observation(path, "go.workspace_replace", fields, line, ordinal, owner),)


def _replacement_observation(
    path: str,
    kind: str,
    fields: tuple[str, ...],
    line: int,
    ordinal: int,
    owner_metadata: dict[str, object],
) -> RawObservation:
    if "=>" not in fields:
        raise ValueError("replace requires =>")
    split = fields.index("=>")
    old = fields[:split]
    replacement = fields[split + 1 :]
    if not old or not replacement or len(old) > 2 or len(replacement) > 2:
        raise ValueError("replace has invalid field count")
    replacement_value = replacement[0]
    local = replacement_value.startswith((".", "/"))
    target = _local_target(path, replacement_value) if local else _module_target(
        replacement_value, replacement[1] if len(replacement) == 2 else None
    )
    return _observation(
        path,
        kind,
        line,
        ordinal,
        name=old[0],
        target=target,
        metadata={
            "old_version": old[1] if len(old) == 2 else None,
            "replacement_kind": "local" if local else "module",
            "replacement": replacement_value if not local else "<repository-relative>",
            "replacement_version": replacement[1] if len(replacement) == 2 else None,
            **owner_metadata,
        },
    )
