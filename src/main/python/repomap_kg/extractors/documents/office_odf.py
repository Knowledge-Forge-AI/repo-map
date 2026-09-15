"""OpenDocument package extraction for conservative office documents."""

from __future__ import annotations

import io
import posixpath
import zipfile
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree

from repomap_kg import __version__
from repomap_kg.extractors.documents.office_common import (
    PARSER_NAME,
    _column_type_summary,
    _parse_error,
    _pointer_for_slug,
    _slugify,
)
from repomap_kg.extractors.documents.office_references import (
    EXTRACTOR_NAME,
    ODF_NAMESPACES,
    ODF_SAFE_PARTS,
    _contains_secret_marker,
    _odf_href_values,
    _odf_manifest_references,
    _odf_reference,
    _q,
    _redacted_or_summary,
    _Reference,
    _reference_observations,
    _safe_value_summary,
)
from repomap_kg.graph.keys import (
    document_column_key,
    document_file_key,
    document_section_key,
    document_sheet_key,
    document_table_key,
)
from repomap_kg.observations.raw import RawObservation


ODF_FORMATS = {
    ".odt": ("odt", False, "text"),
    ".ott": ("ott", True, "text"),
    ".ods": ("ods", False, "spreadsheet"),
    ".ots": ("ots", True, "spreadsheet"),
}
DEFAULT_MAX_PACKAGE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_FILE_COUNT = 128
DEFAULT_MAX_PART_BYTES = 8 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


def extract_odf_file_observations(
    relative_path: str,
    package_bytes: bytes,
    *,
    repository_paths: frozenset[str] | None = None,
    max_package_bytes: int = DEFAULT_MAX_PACKAGE_BYTES,
    max_total_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_file_count: int = DEFAULT_MAX_FILE_COUNT,
    max_part_bytes: int = DEFAULT_MAX_PART_BYTES,
) -> tuple[RawObservation, ...]:
    suffix = PurePosixPath(relative_path).suffix.lower()
    format_info = ODF_FORMATS.get(suffix)
    if format_info is None:
        return ()
    document_format, template, document_family = format_info
    if len(package_bytes) > max_package_bytes:
        return (
            _parse_error(
                relative_path,
                document_format,
                "zip-package-size-limit",
                "ODF package exceeds configured compressed byte limit",
                line_number=None,
            ),
        )
    try:
        with zipfile.ZipFile(io.BytesIO(package_bytes)) as package:
            members = package.infolist()
            safety_error = _odf_package_safety_error(
                relative_path,
                document_format,
                members,
                max_total_uncompressed_bytes=max_total_uncompressed_bytes,
                max_file_count=max_file_count,
                max_part_bytes=max_part_bytes,
            )
            if safety_error is not None:
                return (safety_error,)
            parts: dict[str, bytes] = {}
            for member in members:
                if member.filename in ODF_SAFE_PARTS:
                    parts[member.filename] = package.read(member)
    except (OSError, zipfile.BadZipFile):
        return (
            _parse_error(
                relative_path,
                document_format,
                "malformed-zip",
                "ODF package is not a valid ZIP archive",
                line_number=None,
            ),
        )
    parsed_parts: dict[str, ElementTree.Element] = {}
    for part_name, part_bytes in parts.items():
        if _xml_bytes_are_dangerous(part_bytes):
            return (
                _parse_error(
                    relative_path,
                    document_format,
                    "dangerous-xml",
                    f"ODF part {part_name} contains disallowed XML constructs",
                    line_number=None,
                ),
            )
        try:
            parsed_parts[part_name] = ElementTree.fromstring(part_bytes)
        except ElementTree.ParseError as error:
            return (
                _parse_error(
                    relative_path,
                    document_format,
                    "malformed-xml",
                    f"ODF part {part_name} is malformed: {error}",
                    line_number=None,
                ),
            )

    content_root = parsed_parts.get("content.xml")
    if content_root is None:
        return (
            _parse_error(
                relative_path,
                document_format,
                "missing-content-xml",
                "ODF package does not contain content.xml",
                line_number=None,
            ),
        )
    package_metadata = _odf_package_metadata(
        package_bytes,
        members,
        parsed_parts,
        document_format=document_format,
        template=template,
    )
    if document_family == "spreadsheet":
        return _extract_odf_spreadsheet(
            relative_path,
            content_root,
            parsed_parts,
            document_format=document_format,
            template=template,
            package_metadata=package_metadata,
            repository_paths=repository_paths,
        )
    return _extract_odf_text_document(
        relative_path,
        content_root,
        parsed_parts,
        document_format=document_format,
        template=template,
        package_metadata=package_metadata,
        repository_paths=repository_paths,
    )


def _odf_package_safety_error(
    relative_path: str,
    document_format: str,
    members: list[zipfile.ZipInfo],
    *,
    max_total_uncompressed_bytes: int,
    max_file_count: int,
    max_part_bytes: int,
) -> RawObservation | None:
    if len(members) > max_file_count:
        return _parse_error(
            relative_path,
            document_format,
            "zip-file-count-limit",
            "ODF package exceeds configured file-count limit",
            line_number=None,
        )
    total_uncompressed = 0
    for member in members:
        name = member.filename
        normalized = posixpath.normpath(name)
        if (
            name.startswith("/")
            or "\\" in name
            or normalized == ".."
            or normalized.startswith("../")
        ):
            return _parse_error(
                relative_path,
                document_format,
                "zip-path-traversal",
                "ODF package contains a path traversal or absolute entry",
                line_number=None,
            )
        total_uncompressed += member.file_size
        if total_uncompressed > max_total_uncompressed_bytes:
            return _parse_error(
                relative_path,
                document_format,
                "zip-uncompressed-limit",
                "ODF package exceeds configured uncompressed byte limit",
                line_number=None,
            )
        if member.file_size > max_part_bytes:
            return _parse_error(
                relative_path,
                document_format,
                "zip-part-size-limit",
                "ODF package part exceeds configured per-part byte limit",
                line_number=None,
            )
        if (
            member.compress_size > 0
            and member.file_size > 1024 * 1024
            and member.file_size / member.compress_size > MAX_COMPRESSION_RATIO
        ):
            return _parse_error(
                relative_path,
                document_format,
                "zip-compression-ratio-limit",
                "ODF package has a suspicious compression ratio",
                line_number=None,
            )
    return None


def _xml_bytes_are_dangerous(part_bytes: bytes) -> bool:
    lowered = part_bytes[:2048].lower()
    return b"<!doctype" in lowered or b"<!entity" in lowered


def _odf_package_metadata(
    package_bytes: bytes,
    members: list[zipfile.ZipInfo],
    parsed_parts: dict[str, ElementTree.Element],
    *,
    document_format: str,
    template: bool,
) -> dict[str, Any]:
    total_uncompressed = sum(member.file_size for member in members)
    skipped_parts = [
        member.filename for member in members if member.filename not in ODF_SAFE_PARTS
    ]
    metadata: dict[str, Any] = {
        "format": document_format,
        "parser": PARSER_NAME,
        "package_parser": "stdlib-zipfile",
        "document_kind": document_format,
        "template": template,
        "package_byte_count": len(package_bytes),
        "package_part_count": len(members),
        "parsed_part_count": len(parsed_parts),
        "skipped_part_count": len(skipped_parts),
        "total_uncompressed_bytes": total_uncompressed,
        "macro_script_ignored": True,
    }
    title = _odf_meta_title(parsed_parts.get("meta.xml"))
    if title is not None:
        metadata["title_summary"] = title
    style_count = _odf_style_count(parsed_parts.get("styles.xml"))
    if style_count:
        metadata["style_count"] = style_count
    return metadata


def _extract_odf_text_document(
    relative_path: str,
    content_root: ElementTree.Element,
    parsed_parts: dict[str, ElementTree.Element],
    *,
    document_format: str,
    template: bool,
    package_metadata: dict[str, Any],
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    document_key = document_file_key(relative_path)
    parent_map = _parent_map(content_root)
    headings = list(content_root.iter(_q("text", "h")))
    paragraphs = [
        paragraph
        for paragraph in content_root.iter(_q("text", "p"))
        if not _has_ancestor(paragraph, parent_map, _q("table", "table"))
    ]
    tables = list(content_root.iter(_q("table", "table")))
    references: list[_Reference] = []
    observations: list[RawObservation] = []
    current_source_key = document_key
    heading_count = 0
    for element in content_root.iter():
        if element.tag == _q("text", "h"):
            heading_count += 1
            heading = _element_text(element)
            pointer = _pointer_for_slug("sections", _slugify(heading))
            current_source_key = document_section_key(relative_path, pointer)
            observations.append(
                RawObservation(
                    kind="document.odf_text",
                    source_id=f"{relative_path}#odf-heading:{heading_count}",
                    path=relative_path,
                    name=pointer,
                    target=current_source_key,
                    confidence="extracted",
                    extractor=EXTRACTOR_NAME,
                    extractor_version=__version__,
                    metadata={
                        "format": document_format,
                        "parser": PARSER_NAME,
                        "document_key": document_key,
                        "source_part": "content.xml",
                        "pointer": pointer,
                        "heading_level": _odf_heading_level(element),
                        "heading_summary": _redacted_or_summary(heading),
                        "redacted": _contains_secret_marker(heading),
                    },
                )
            )
        elif element.tag == _q("text", "p"):
            for href in _odf_href_values(element):
                references.append(
                    _odf_reference(
                        relative_path,
                        href,
                        source_key=current_source_key,
                        repository_paths=repository_paths,
                        reference_kind="url",
                        resolution_reason="odf-xlink-href",
                    )
                )

    table_observations, table_references = _odf_table_observations(
        relative_path,
        tables,
        document_format=document_format,
        document_key=document_key,
        table_prefix="tables",
        parent_kind="table",
        repository_paths=repository_paths,
    )
    references.extend(table_references)
    references.extend(
        _odf_manifest_references(
            relative_path,
            parsed_parts.get("META-INF/manifest.xml"),
            source_key=document_key,
            repository_paths=repository_paths,
        )
    )
    metadata = {
        **package_metadata,
        "paragraph_count": len(paragraphs),
        "heading_count": len(headings),
        "table_count": len(tables),
        "sheet_count": 0,
        "reference_count": len(references),
        "formulas_evaluated": False,
        "formula_count": 0,
    }
    return (
        RawObservation(
            kind="document.odf_document",
            source_id=f"{relative_path}#odf-document",
            path=relative_path,
            confidence="extracted",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            target=document_key,
            metadata=metadata,
        ),
        *observations,
        *table_observations,
        *_reference_observations(relative_path, references, document_format),
    )


def _extract_odf_spreadsheet(
    relative_path: str,
    content_root: ElementTree.Element,
    parsed_parts: dict[str, ElementTree.Element],
    *,
    document_format: str,
    template: bool,
    package_metadata: dict[str, Any],
    repository_paths: frozenset[str] | None,
) -> tuple[RawObservation, ...]:
    document_key = document_file_key(relative_path)
    tables = list(content_root.iter(_q("table", "table")))
    references = _odf_manifest_references(
        relative_path,
        parsed_parts.get("META-INF/manifest.xml"),
        source_key=document_key,
        repository_paths=repository_paths,
    )
    table_observations, table_references = _odf_table_observations(
        relative_path,
        tables,
        document_format=document_format,
        document_key=document_key,
        table_prefix="sheets",
        parent_kind="sheet",
        repository_paths=repository_paths,
    )
    references.extend(table_references)
    row_counts = [
        observation.metadata.get("row_count", 0)
        for observation in table_observations
        if observation.kind == "document.odf_sheet"
    ]
    column_counts = [
        observation.metadata.get("column_count", 0)
        for observation in table_observations
        if observation.kind == "document.odf_sheet"
    ]
    formula_count = sum(_odf_formula_count(table) for table in tables)
    metadata = {
        **package_metadata,
        "paragraph_count": 0,
        "heading_count": 0,
        "table_count": len(tables),
        "sheet_count": len(tables),
        "row_count_summary": max(row_counts) if row_counts else 0,
        "column_count_summary": max(column_counts) if column_counts else 0,
        "reference_count": len(references),
        "formulas_evaluated": False,
        "formula_count": formula_count,
    }
    return (
        RawObservation(
            kind="document.odf_document",
            source_id=f"{relative_path}#odf-document",
            path=relative_path,
            confidence="extracted",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            target=document_key,
            metadata=metadata,
        ),
        *table_observations,
        *_reference_observations(relative_path, references, document_format),
    )


def _odf_table_observations(
    relative_path: str,
    tables: list[ElementTree.Element],
    *,
    document_format: str,
    document_key: str,
    table_prefix: str,
    parent_kind: str,
    repository_paths: frozenset[str] | None,
) -> tuple[list[RawObservation], list[_Reference]]:
    observations: list[RawObservation] = []
    references: list[_Reference] = []
    for table_index, table in enumerate(tables, start=1):
        table_name = _odf_table_name(table) or f"{parent_kind}-{table_index}"
        pointer = _pointer_for_slug(table_prefix, _slugify(table_name))
        rows = _odf_table_rows(table)
        header = rows[0] if rows else []
        data_rows = rows[1:] if rows else []
        column_count = max((len(row) for row in rows), default=0)
        parent_key = (
            document_sheet_key(relative_path, pointer)
            if parent_kind == "sheet"
            else document_table_key(relative_path, pointer)
        )
        kind = "document.odf_sheet" if parent_kind == "sheet" else "document.odf_table"
        observations.append(
            RawObservation(
                kind=kind,
                source_id=f"{relative_path}#odf-{parent_kind}:{table_index}",
                path=relative_path,
                name=pointer,
                target=parent_key,
                confidence="extracted",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata={
                    "format": document_format,
                    "parser": PARSER_NAME,
                    "document_key": document_key,
                    "source_part": "content.xml",
                    "pointer": pointer,
                    "display_name": _redacted_or_summary(table_name),
                    "row_count": len(data_rows),
                    "column_count": column_count,
                    "header_present": bool(header),
                    "redacted": _contains_secret_marker(table_name),
                    "formula_count": _odf_formula_count(table),
                    "formulas_evaluated": False,
                },
            )
        )
        for column_index in range(column_count):
            values = [row[column_index] for row in data_rows if column_index < len(row)]
            raw_column_name = (
                header[column_index] if column_index < len(header) else f"column-{column_index + 1}"
            )
            redacted = _contains_secret_marker(raw_column_name) or any(
                _contains_secret_marker(value) for value in values
            )
            column_pointer = f"{pointer}/columns/{_slugify(raw_column_name) or f'column-{column_index + 1}'}"
            observations.append(
                RawObservation(
                    kind="document.odf_column",
                    source_id=f"{relative_path}#odf-{parent_kind}:{table_index}:column:{column_index + 1}",
                    path=relative_path,
                    name=column_pointer,
                    target=document_column_key(relative_path, column_pointer),
                    confidence="extracted",
                    extractor=EXTRACTOR_NAME,
                    extractor_version=__version__,
                    metadata={
                        "format": document_format,
                        "parser": PARSER_NAME,
                        "source_part": "content.xml",
                        "pointer": column_pointer,
                        "parent_key": parent_key,
                        "column_index": column_index + 1,
                        "column_name_summary": "[redacted]"
                        if redacted
                        else _safe_value_summary(raw_column_name),
                        "type_summary": "redacted"
                        if redacted
                        else _column_type_summary(values),
                        "non_empty_count": len([value for value in values if value.strip()]),
                        "redacted": redacted,
                        "redaction_reason": "secret-prone-column-or-value"
                        if redacted
                        else None,
                    },
                )
            )
        for href in _odf_href_values(table):
            references.append(
                _odf_reference(
                    relative_path,
                    href,
                    source_key=parent_key,
                    repository_paths=repository_paths,
                    reference_kind="url",
                    resolution_reason="odf-table-href",
                )
            )
    return observations, references

def _parent_map(root: ElementTree.Element) -> dict[ElementTree.Element, ElementTree.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _has_ancestor(
    element: ElementTree.Element,
    parent_map: dict[ElementTree.Element, ElementTree.Element],
    tag: str,
) -> bool:
    parent = parent_map.get(element)
    while parent is not None:
        if parent.tag == tag:
            return True
        parent = parent_map.get(parent)
    return False


def _element_text(element: ElementTree.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _odf_heading_level(element: ElementTree.Element) -> int:
    value = element.attrib.get(_q("text", "outline-level"))
    if value is None:
        return 1
    try:
        return max(1, int(value))
    except ValueError:
        return 1


def _odf_table_name(table: ElementTree.Element) -> str | None:
    name = table.attrib.get(_q("table", "name"))
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _odf_table_rows(table: ElementTree.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.findall(_q("table", "table-row")):
        row_values: list[str] = []
        for cell in row.findall(_q("table", "table-cell")):
            repeat = _odf_repeat_count(cell)
            cell_text = _element_text(cell)
            row_values.extend([cell_text] * repeat)
        rows.append(row_values)
    return rows


def _odf_repeat_count(cell: ElementTree.Element) -> int:
    value = cell.attrib.get(_q("table", "number-columns-repeated"))
    if value is None:
        return 1
    try:
        return min(100, max(1, int(value)))
    except ValueError:
        return 1


def _odf_formula_count(table: ElementTree.Element) -> int:
    return sum(
        1
        for element in table.iter()
        if any(key.endswith("}formula") for key in element.attrib)
    )


def _odf_meta_title(root: ElementTree.Element | None) -> str | None:
    if root is None:
        return None
    title = root.find(f".//{_q('dc', 'title')}")
    if title is None:
        return None
    text = _element_text(title)
    if not text or _contains_secret_marker(text):
        return None
    return _safe_value_summary(text)


def _odf_style_count(root: ElementTree.Element | None) -> int:
    if root is None:
        return 0
    return len(list(root.iter(_q("style", "style"))))
