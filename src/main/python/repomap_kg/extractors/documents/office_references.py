"""Document reference and safe-summary helpers for office extraction."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from repomap_kg import __version__
from repomap_kg.graph.keys import (
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


EXTRACTOR_NAME = "repo-documents"
MAX_TEXT_SUMMARY_CHARS = 160
SECRET_PRONE_MARKERS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "access_key",
    "refresh_token",
    "bearer",
    "auth",
    "ssn",
    "social_security",
    "tax_id",
    "account_number",
    "routing_number",
    "iban",
    "credit_card",
    "medical_record",
    "patient_id",
)
URL_PATTERN = re.compile(r"\b(?:https?://[^\s<>)]+|mailto:[^\s<>)]+)")
PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_./~-])(?:/|\.{1,2}/)?[A-Za-z0-9_${}~*?.-]+"
    r"(?:/[A-Za-z0-9_${}~*?.-]+)+"
)
ODF_NAMESPACES = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "manifest": "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
}
ODF_SAFE_PARTS = frozenset(
    ("content.xml", "meta.xml", "styles.xml", "META-INF/manifest.xml")
)
ODF_INTERNAL_REFERENCE_TARGET = unknown_key(
    "document.reference", "odf-internal-package-part"
)


@dataclass(frozen=True)
class _Reference:
    source_key: str
    raw_value: str
    target_key: str
    reference_kind: str
    resolution_reason: str
    line_number: int
    command: str | None = None


def _reference_observations(
    relative_path: str, references: list[_Reference], document_format: str
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for index, reference in enumerate(references):
        metadata: dict[str, Any] = {
            "format": document_format,
            "source_key": reference.source_key,
            "reference_kind": reference.reference_kind,
            "raw_value_summary": _safe_value_summary(reference.raw_value),
            "resolution_reason": reference.resolution_reason,
            "not_fetched": True,
            "redacted": False,
        }
        if reference.command is not None:
            metadata["command"] = reference.command
        observations.append(
            RawObservation(
                kind="document.reference",
                source_id=f"{relative_path}#document-reference:{reference.line_number}:{index}",
                path=relative_path,
                start_line=reference.line_number,
                end_line=reference.line_number,
                confidence="heuristic",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                target=reference.target_key,
                metadata=metadata,
            )
        )
    return observations


def _references_from_text(
    relative_path: str,
    text: str,
    line_number: int,
    *,
    source_key: str,
    repository_paths: frozenset[str] | None,
) -> list[_Reference]:
    if _contains_secret_marker(text):
        return []
    references: list[_Reference] = []
    consumed: list[tuple[int, int]] = []
    for match in URL_PATTERN.finditer(text):
        raw_value = match.group(0).rstrip(".,;")
        references.append(
            _reference_for_value(
                relative_path,
                raw_value,
                line_number,
                source_key=source_key,
                reference_kind="url",
                resolution_reason="url-literal",
                repository_paths=repository_paths,
            )
        )
        consumed.append(match.span())
    for match in PATH_PATTERN.finditer(text):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        raw_value = match.group(0).rstrip(".,;")
        references.append(
            _reference_for_value(
                relative_path,
                raw_value,
                line_number,
                source_key=source_key,
                reference_kind="file",
                resolution_reason="path-like-string",
                repository_paths=repository_paths,
            )
        )
    return references


def _latex_reference(
    relative_path: str,
    command: str,
    argument: str,
    line_number: int,
    source_key: str,
    *,
    repository_paths: frozenset[str] | None,
) -> _Reference | None:
    if not argument or _contains_secret_marker(argument):
        return None
    if command in ("input", "include"):
        value = argument if PurePosixPath(argument).suffix else f"{argument}.tex"
        return _reference_for_value(
            relative_path,
            value,
            line_number,
            source_key=source_key,
            reference_kind="file",
            resolution_reason=f"latex-{command}",
            repository_paths=repository_paths,
            command=command,
        )
    if command in ("includegraphics", "bibliography", "addbibresource"):
        value = argument
        if command in ("bibliography", "addbibresource") and not PurePosixPath(value).suffix:
            value = f"{value}.bib"
        return _reference_for_value(
            relative_path,
            value,
            line_number,
            source_key=source_key,
            reference_kind="file",
            resolution_reason=f"latex-{command}",
            repository_paths=repository_paths,
            command=command,
        )
    if command in ("url", "href"):
        return _reference_for_value(
            relative_path,
            argument,
            line_number,
            source_key=source_key,
            reference_kind="url",
            resolution_reason=f"latex-{command}",
            repository_paths=repository_paths,
            command=command,
        )
    return None


def _reference_for_value(
    relative_path: str,
    raw_value: str,
    line_number: int,
    *,
    source_key: str,
    reference_kind: str,
    resolution_reason: str,
    repository_paths: frozenset[str] | None,
    command: str | None = None,
) -> _Reference:
    target_key = _target_key_for_reference(relative_path, raw_value, repository_paths)
    return _Reference(
        source_key=source_key,
        raw_value=raw_value,
        target_key=target_key,
        reference_kind=reference_kind,
        resolution_reason=resolution_reason,
        line_number=line_number,
        command=command,
    )


def _target_key_for_reference(
    relative_path: str, raw_value: str, repository_paths: frozenset[str] | None
) -> str:
    try:
        split = urlsplit(raw_value)
    except ValueError:
        return unknown_key("external.url", "malformed-document-reference")
    if split.scheme in ("http", "https", "mailto"):
        return external_url_key(raw_value)
    if split.scheme and split.scheme not in ("",):
        return unknown_key("document.reference", "unsupported-scheme")
    if raw_value.startswith("/"):
        return external_key("file", "absolute-document-reference")
    if any(marker in raw_value for marker in ("$", "${", "{{", "}}", "~", "*", "?")):
        return dynamic_key("file", "dynamic-document-reference")
    base_dir = PurePosixPath(relative_path).parent
    candidate = posixpath.normpath((base_dir / raw_value).as_posix())
    if candidate.startswith("../") or candidate == "..":
        return unknown_key("file", "repo-escaping-document-reference")
    if repository_paths is not None and candidate not in repository_paths:
        # The value is still a syntactic local reference; keep a stable file target
        # so missing local artifacts are explainable without fabricating evidence.
        return file_key(candidate)
    return file_key(candidate)


def _q(prefix: str, local_name: str) -> str:
    return f"{{{ODF_NAMESPACES[prefix]}}}{local_name}"


def _odf_href_values(element: ElementTree.Element) -> list[str]:
    values: list[str] = []
    for child in element.iter():
        href = child.attrib.get(_q("xlink", "href"))
        if isinstance(href, str) and href.strip() and not _contains_secret_marker(href):
            values.append(href.strip())
    return values


def _odf_reference(
    relative_path: str,
    raw_value: str,
    *,
    source_key: str,
    repository_paths: frozenset[str] | None,
    reference_kind: str,
    resolution_reason: str,
) -> _Reference:
    return _Reference(
        source_key=source_key,
        raw_value=raw_value,
        target_key=_target_key_for_reference(relative_path, raw_value, repository_paths),
        reference_kind=reference_kind,
        resolution_reason=resolution_reason,
        line_number=1,
    )


def _odf_manifest_references(
    relative_path: str,
    manifest_root: ElementTree.Element | None,
    *,
    source_key: str,
    repository_paths: frozenset[str] | None,
) -> list[_Reference]:
    if manifest_root is None:
        return []
    references: list[_Reference] = []
    for entry in manifest_root.iter(_q("manifest", "file-entry")):
        full_path = entry.attrib.get(_q("manifest", "full-path"))
        if not isinstance(full_path, str) or not full_path or full_path in ("/", "."):
            continue
        if full_path in ODF_SAFE_PARTS or full_path.endswith("/"):
            continue
        if _contains_secret_marker(full_path):
            continue
        split = urlsplit(full_path)
        target_key = (
            _target_key_for_reference(relative_path, full_path, repository_paths)
            if split.scheme in ("http", "https", "mailto")
            else ODF_INTERNAL_REFERENCE_TARGET
        )
        references.append(
            _Reference(
                source_key=source_key,
                raw_value=full_path,
                target_key=target_key,
                reference_kind="package-part",
                resolution_reason="odf-manifest-entry",
                line_number=1,
            )
        )
    return references


def _safe_summary(content: str) -> str | None:
    if _contains_secret_marker(content):
        return None
    collapsed = " ".join(content.split())
    if not collapsed:
        return None
    return collapsed[:MAX_TEXT_SUMMARY_CHARS]


def _redacted_or_summary(value: str) -> str:
    if _contains_secret_marker(value):
        return "[redacted]"
    return _safe_value_summary(value)


def _safe_value_summary(value: str) -> str:
    if _contains_secret_marker(value):
        return "[redacted]"
    return " ".join(value.split())[:120]


def _contains_secret_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in SECRET_PRONE_MARKERS)
