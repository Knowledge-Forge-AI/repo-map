"""XML and plist configuration raw observation extraction."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from pathlib import PurePosixPath
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.config.format_contracts import (
    GENERIC_XML_FORMAT,
    GENERIC_XML_SAFETY_MODE,
    PLIST_ROOT_PATTERN,
    PLIST_XML_FORMAT,
    PLIST_XML_SAFETY_MODE,
    UNSAFE_PROCESSING_INSTRUCTION_PATTERN,
    UNSAFE_XML_DECLARATION_PATTERN,
    GenericXmlSafetyError,
    PlistXmlParseError,
    PlistXmlSafetyError,
)
from repomap_kg.graph.keys import (
    dynamic_key,
    env_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
    xml_attribute_key,
    xml_document_key,
    xml_element_key,
)
from repomap_kg.extractors.config.xml_references import (
    _detect_xml_references,
    _looks_like_xml_file_key,
    _xml_file_reference,
    _xml_reference_observations,
)
from repomap_kg.observations.raw import RawObservation


def _generic_helper(name: str) -> Any:
    from repomap_kg.extractors.config import generic_contracts as generic

    return getattr(generic, name)


def _extractor_name() -> str:
    return _generic_helper("EXTRACTOR_NAME")


def _plist_xml_format() -> str:
    return _generic_helper("PLIST_XML_FORMAT")


def _plist_xml_safety_mode() -> str:
    return _generic_helper("PLIST_XML_SAFETY_MODE")


def _generic_xml_format() -> str:
    return _generic_helper("GENERIC_XML_FORMAT")


def _generic_xml_safety_mode() -> str:
    return _generic_helper("GENERIC_XML_SAFETY_MODE")


def _unsafe_xml_declaration_pattern() -> re.Pattern[str]:
    return _generic_helper("UNSAFE_XML_DECLARATION_PATTERN")


def _unsafe_processing_instruction_pattern() -> re.Pattern[str]:
    return _generic_helper("UNSAFE_PROCESSING_INSTRUCTION_PATTERN")


def _plist_root_pattern() -> re.Pattern[str]:
    return _generic_helper("PLIST_ROOT_PATTERN")


def _parse_error_observation(*args: Any, **kwargs: Any) -> RawObservation:
    return _generic_helper("_parse_error_observation")(*args, **kwargs)


def _structure_observations(*args: Any, **kwargs: Any) -> tuple[Any, Any]:
    return _generic_helper("_structure_observations")(*args, **kwargs)


def _document_observation(*args: Any, **kwargs: Any) -> RawObservation:
    return _generic_helper("_document_observation")(*args, **kwargs)


def _parser_name(format_name: str) -> str:
    return _generic_helper("_parser_name")(format_name)


def _value_type(value: Any) -> str:
    return _generic_helper("_value_type")(value)


def _is_secret_key(key: str) -> bool:
    return _generic_helper("_is_secret_key")(key)


def _safe_value_summary(value: Any) -> Any:
    return _generic_helper("_safe_value_summary")(value)


def _safe_error_message(error: Any | None, message: str | None) -> str:
    return _generic_helper("_safe_error_message")(error, message)


def _normalized_key(value: str) -> str:
    return _generic_helper("_normalized_key")(value)


def _is_url(value: str) -> bool:
    return _generic_helper("_is_url")(value)


def _is_dynamic_value(value: str) -> bool:
    return _generic_helper("_is_dynamic_value")(value)


def _resolve_repo_path(relative_path: str, value: str) -> str | None:
    return _generic_helper("_resolve_repo_path")(relative_path, value)


def _normalize_repo_path(value: str) -> str | None:
    return _generic_helper("_normalize_repo_path")(value)


def _reference(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _generic_helper("_reference")(*args, **kwargs)


def _extract_plist_xml_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    try:
        _check_safe_plist_xml(content)
        root = ElementTree.fromstring(content)
        parsed = _plist_root_value(root)
    except PlistXmlSafetyError as error:
        return (
            _parse_error_observation(
                relative_path,
                format_name=_plist_xml_format(),
                error_kind="unsafe-xml-construct",
                message=str(error),
                recovered=False,
            ),
        )
    except ElementTree.ParseError as error:
        return (
            _parse_error_observation(
                relative_path,
                format_name=_plist_xml_format(),
                error_kind="malformed-plist-xml",
                message=str(error),
                start_line=_xml_parse_error_line(error),
                recovered=False,
            ),
        )
    except PlistXmlParseError as error:
        return (
            _parse_error_observation(
                relative_path,
                format_name=_plist_xml_format(),
                error_kind="unsupported-plist-shape",
                message=str(error),
                recovered=False,
            ),
        )
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name=_plist_xml_format(),
        confidence="extracted",
        content=content,
    )
    document = _document_observation(
        relative_path,
        format_name=_plist_xml_format(),
        parser=_parser_name(_plist_xml_format()),
        confidence="extracted",
        top_level_type=_value_type(parsed),
        path_count=len(path_observations),
        record_count=None,
        parse_error_count=0,
    )
    return (document, *path_observations, *reference_observations)


def _extract_generic_xml_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    try:
        _check_safe_generic_xml(content)
        root = ElementTree.fromstring(content)
    except GenericXmlSafetyError as error:
        return (
            _xml_parse_error_observation(
                relative_path,
                error_kind="unsafe-xml-construct",
                message=str(error),
                recovered=False,
            ),
        )
    except ElementTree.ParseError as error:
        return (
            _xml_parse_error_observation(
                relative_path,
                error_kind="malformed-xml",
                message=str(error),
                start_line=_xml_parse_error_line(error),
                recovered=False,
            ),
        )

    namespaces = _xml_namespace_summary(content)
    root_parts = _xml_name_parts(root.tag)
    document_role = _generic_xml_document_role(relative_path, root, namespaces)
    elements: list[RawObservation] = []
    attributes: list[RawObservation] = []
    references: list[RawObservation] = []
    _walk_xml_element(
        relative_path,
        root,
        pointer=f"/{root_parts['local_name']}",
        document_role=document_role,
        content=content,
        elements=elements,
        attributes=attributes,
        references=references,
    )
    document = RawObservation(
        kind="xml.document",
        source_id=f"{relative_path}#xml-document",
        path=relative_path,
        target=xml_document_key(relative_path),
        confidence="extracted",
        extractor=_extractor_name(),
        extractor_version=__version__,
        metadata={
            "format": _generic_xml_format(),
            "parser": _parser_name(_generic_xml_format()),
            "safety_mode": _generic_xml_safety_mode(),
            "root_tag": root_parts["display_name"],
            "root_local_name": root_parts["local_name"],
            "root_namespace_uri": root_parts.get("namespace_uri"),
            "namespace_summary": namespaces,
            "document_role": document_role,
            "parse_error_count": 0,
            "element_count": len(elements),
            "attribute_count": len(attributes),
            "reference_count": len(references),
        },
    )
    return (document, *elements, *attributes, *references)


def _looks_like_plist_xml(content: str) -> bool:
    return bool(_plist_root_pattern().search(content))


def _check_safe_plist_xml(content: str) -> None:
    if _unsafe_xml_declaration_pattern().search(content):
        raise PlistXmlSafetyError(
            "doctype and entity declarations are not supported"
        )
    if _unsafe_processing_instruction_pattern().search(content):
        raise PlistXmlSafetyError(
            "non-XML processing instructions are not supported"
        )


def _check_safe_generic_xml(content: str) -> None:
    if _unsafe_xml_declaration_pattern().search(content):
        raise GenericXmlSafetyError(
            "doctype and entity declarations are not supported"
        )
    if _unsafe_processing_instruction_pattern().search(content):
        raise GenericXmlSafetyError(
            "non-XML processing instructions are not supported"
        )


def _xml_parse_error_line(error: ElementTree.ParseError) -> int | None:
    position = getattr(error, "position", None)
    if isinstance(position, tuple) and position:
        line = position[0]
        if isinstance(line, int) and line > 0:
            return line
    return None


def _plist_root_value(root: ElementTree.Element) -> Any:
    if _xml_local_name(root.tag) != "plist":
        raise PlistXmlParseError("root element is not plist")
    children = list(root)
    if len(children) != 1:
        raise PlistXmlParseError("plist root must contain exactly one value element")
    return _plist_value(children[0])


def _plist_value(element: ElementTree.Element) -> Any:
    tag = _xml_local_name(element.tag)
    if tag == "dict":
        return _plist_dict(element)
    if tag == "array":
        return [_plist_value(child) for child in element]
    if tag in ("string", "date", "data"):
        return (element.text or "").strip()
    if tag == "integer":
        text = (element.text or "").strip()
        try:
            return int(text)
        except ValueError as error:
            raise PlistXmlParseError("integer value is malformed") from error
    if tag == "real":
        text = (element.text or "").strip()
        try:
            return float(text)
        except ValueError as error:
            raise PlistXmlParseError("real value is malformed") from error
    if tag == "true":
        return True
    if tag == "false":
        return False
    raise PlistXmlParseError(f"unsupported plist value element: {tag}")


def _plist_dict(element: ElementTree.Element) -> dict[str, Any]:
    children = list(element)
    result: dict[str, Any] = {}
    index = 0
    while index < len(children):
        key_element = children[index]
        if _xml_local_name(key_element.tag) != "key":
            raise PlistXmlParseError("dict entries must begin with key elements")
        key = (key_element.text or "").strip()
        if not key:
            raise PlistXmlParseError("dict key must not be empty")
        index += 1
        if index >= len(children):
            raise PlistXmlParseError("dict key is missing a value element")
        if key in result:
            raise PlistXmlParseError("duplicate dict keys are not supported")
        value_element = children[index]
        if _xml_local_name(value_element.tag) == "key":
            raise PlistXmlParseError("dict key is missing a value element")
        result[key] = _plist_value(value_element)
        index += 1
    return result


def _xml_local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag


def _xml_name_parts(name: str) -> dict[str, str]:
    if name.startswith("{"):
        namespace_uri, local_name = name[1:].split("}", 1)
        return {
            "display_name": local_name,
            "local_name": local_name,
            "namespace_uri": namespace_uri,
        }
    return {"display_name": name, "local_name": name}


def _xml_attribute_parts(name: str) -> dict[str, str]:
    parts = _xml_name_parts(name)
    namespace_uri = parts.get("namespace_uri")
    if namespace_uri == "http://www.w3.org/2001/XMLSchema-instance":
        parts["display_name"] = f"xsi:{parts['local_name']}"
    return parts


def _xml_namespace_summary(content: str) -> list[dict[str, str]]:
    namespace_pattern = re.compile(
        r"\sxmlns(?::(?P<prefix>[A-Za-z_][\w.-]*))?=\"(?P<uri>[^\"]+)\""
    )
    summary = []
    seen: set[tuple[str, str]] = set()
    for match in namespace_pattern.finditer(content):
        prefix = match.group("prefix") or ""
        uri = match.group("uri")
        key = (prefix, uri)
        if key in seen:
            continue
        seen.add(key)
        summary.append({"prefix": prefix, "uri": uri})
    return summary


def _generic_xml_document_role(
    relative_path: str,
    root: ElementTree.Element,
    namespaces: list[dict[str, str]],
) -> str:
    root_local = _xml_local_name(root.tag)
    namespace_uris = {item["uri"] for item in namespaces}
    path = PurePosixPath(relative_path)
    if path.name == "pom.xml" or (
        root_local == "project"
        and "http://maven.apache.org/POM/4.0.0" in namespace_uris
    ):
        return "maven-pom"
    if root_local == "beans" or any(
        uri.startswith("http://www.springframework.org/schema/")
        for uri in namespace_uris
    ):
        return "spring-config"
    if path.suffix == ".xml":
        return "xml-config"
    return "config"


def _walk_xml_element(
    relative_path: str,
    element: ElementTree.Element,
    *,
    pointer: str,
    document_role: str,
    content: str,
    elements: list[RawObservation],
    attributes: list[RawObservation],
    references: list[RawObservation],
) -> None:
    parts = _xml_name_parts(element.tag)
    local_name = parts["local_name"]
    redacted = _is_secret_xml_element(element)
    element_key = xml_element_key(relative_path, pointer)
    metadata = _xml_element_metadata(
        element,
        pointer=pointer,
        document_role=document_role,
        redacted=redacted,
    )
    elements.append(
        RawObservation(
            kind="xml.element",
            source_id=f"{relative_path}#xml-element:{pointer}",
            path=relative_path,
            name=pointer,
            target=element_key,
            confidence="extracted",
            extractor=_extractor_name(),
            extractor_version=__version__,
            metadata=metadata,
        )
    )
    text = (element.text or "").strip()
    if text:
        references.extend(
            _xml_reference_observations(
                relative_path,
                value=text,
                key_context=local_name,
                source_key=element_key,
                source_kind="xml.element",
                pointer=pointer,
                attribute_name=None,
                redacted=redacted,
            )
        )
    for attr_name, attr_value in sorted(element.attrib.items()):
        attr_parts = _xml_attribute_parts(attr_name)
        attr_display_name = attr_parts["display_name"]
        attr_redacted = redacted or _is_secret_key(attr_display_name)
        semantic_key = _xml_attribute_semantic_key(
            attr_display_name,
            element,
            element_local_name=local_name,
        )
        attr_key = xml_attribute_key(relative_path, pointer, attr_display_name)
        attr_metadata = _xml_attribute_metadata(
            attr_value,
            attr_parts=attr_parts,
            pointer=pointer,
            semantic_key=semantic_key,
            redacted=attr_redacted,
        )
        attributes.append(
            RawObservation(
                kind="xml.attribute",
                source_id=(
                    f"{relative_path}#xml-attribute:{pointer}:{attr_display_name}"
                ),
                path=relative_path,
                name=attr_display_name,
                target=attr_key,
                confidence="extracted",
                extractor=_extractor_name(),
                extractor_version=__version__,
                metadata=attr_metadata,
            )
        )
        references.extend(
            _xml_reference_observations(
                relative_path,
                value=attr_value,
                key_context=semantic_key,
                source_key=attr_key,
                source_kind="xml.attribute",
                pointer=pointer,
                attribute_name=attr_display_name,
                redacted=attr_redacted,
            )
        )
    for child, child_pointer in _xml_child_pointers(element, pointer):
        _walk_xml_element(
            relative_path,
            child,
            pointer=child_pointer,
            document_role=document_role,
            content=content,
            elements=elements,
            attributes=attributes,
            references=references,
        )


def _xml_child_pointers(
    element: ElementTree.Element,
    parent_pointer: str,
) -> tuple[tuple[ElementTree.Element, str], ...]:
    children = list(element)
    totals: dict[str, int] = {}
    for child in children:
        local = _xml_local_name(child.tag)
        totals[local] = totals.get(local, 0) + 1
    seen: dict[str, int] = {}
    result = []
    for child in children:
        local = _xml_local_name(child.tag)
        seen[local] = seen.get(local, 0) + 1
        segment = local if seen[local] == 1 else f"{local}[{seen[local]}]"
        result.append((child, f"{parent_pointer}/{segment}"))
    return tuple(result)


def _xml_element_metadata(
    element: ElementTree.Element,
    *,
    pointer: str,
    document_role: str,
    redacted: bool,
) -> dict[str, Any]:
    parts = _xml_name_parts(element.tag)
    children = list(element)
    metadata: dict[str, Any] = {
        "format": _generic_xml_format(),
        "parser": _parser_name(_generic_xml_format()),
        "safety_mode": _generic_xml_safety_mode(),
        "element_name": parts["display_name"],
        "local_name": parts["local_name"],
        "xml_pointer": pointer,
        "attribute_count": len(element.attrib),
        "child_count": len(children),
        "identity_mode": "structural-document",
        "role_hint": _xml_role_hint(element, document_role=document_role),
        "redacted": redacted,
    }
    if "namespace_uri" in parts:
        metadata["namespace_uri"] = parts["namespace_uri"]
    if redacted:
        metadata["redaction_reason"] = "secret-prone-key"
    else:
        text = (element.text or "").strip()
        if text and not _is_placeholder_heavy(text):
            summary = _safe_value_summary(text)
            if summary is not None:
                metadata["text_summary"] = summary
    metadata.update(_xml_domain_metadata(element, document_role=document_role))
    return metadata


def _xml_attribute_metadata(
    value: str,
    *,
    attr_parts: dict[str, str],
    pointer: str,
    semantic_key: str,
    redacted: bool,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "format": _generic_xml_format(),
        "parser": _parser_name(_generic_xml_format()),
        "safety_mode": _generic_xml_safety_mode(),
        "element_pointer": pointer,
        "attribute_name": attr_parts["display_name"],
        "local_name": attr_parts["local_name"],
        "semantic_key": semantic_key,
        "value_type": "string",
        "redacted": redacted,
    }
    if "namespace_uri" in attr_parts:
        metadata["namespace_uri"] = attr_parts["namespace_uri"]
    if redacted:
        metadata["redaction_reason"] = "secret-prone-key"
        return metadata
    summary = _safe_value_summary(value)
    if summary is not None:
        metadata["value_summary"] = summary
    return metadata


def _xml_role_hint(
    element: ElementTree.Element,
    *,
    document_role: str,
) -> str:
    local = _xml_local_name(element.tag)
    if document_role == "spring-config":
        if local == "bean":
            return "spring-bean"
        if local == "property":
            return "spring-property"
    if document_role == "maven-pom":
        if local == "dependency":
            return "maven-dependency"
        if local == "plugin":
            return "maven-plugin"
        if _xml_parentish_property_name(local):
            return "maven-property"
    return "unknown"


def _xml_domain_metadata(
    element: ElementTree.Element,
    *,
    document_role: str,
) -> dict[str, Any]:
    local = _xml_local_name(element.tag)
    metadata: dict[str, Any] = {}
    if document_role == "spring-config" and local == "bean":
        bean_id = element.attrib.get("id")
        class_name = element.attrib.get("class")
        if bean_id:
            metadata["bean_id"] = bean_id
        if class_name:
            metadata["class_name"] = class_name
    if document_role == "spring-config" and local == "property":
        property_name = element.attrib.get("name")
        ref = element.attrib.get("ref")
        if property_name:
            metadata["property_name"] = property_name
        if ref:
            metadata["bean_ref"] = ref
    if document_role == "maven-pom" and local in ("project", "dependency", "plugin"):
        child_values = _xml_direct_child_texts(element)
        if "groupId" in child_values:
            metadata["maven_group_id"] = child_values["groupId"]
        if "artifactId" in child_values:
            metadata["maven_artifact_id"] = child_values["artifactId"]
        if "version" in child_values:
            metadata["maven_version"] = child_values["version"]
    return metadata


def _xml_direct_child_texts(element: ElementTree.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in element:
        local = _xml_local_name(child.tag)
        text = (child.text or "").strip()
        if text and local not in values and not _is_secret_key(local):
            values[local] = text
    return values


def _xml_parentish_property_name(local_name: str) -> bool:
    return local_name not in (
        "project",
        "modelVersion",
        "groupId",
        "artifactId",
        "version",
        "dependencies",
        "dependency",
        "build",
        "plugins",
        "plugin",
    )


def _xml_attribute_semantic_key(
    attr_name: str,
    element: ElementTree.Element,
    *,
    element_local_name: str,
) -> str:
    semantic_parts = [attr_name, element_local_name]
    xml_name_attr = element.attrib.get("name")
    if isinstance(xml_name_attr, str) and xml_name_attr.strip():
        semantic_parts.append(xml_name_attr)
    return "_".join(_normalized_key(part) for part in semantic_parts)


def _is_secret_xml_element(element: ElementTree.Element) -> bool:
    local = _xml_local_name(element.tag)
    if _is_secret_key(local):
        return True
    xml_name_attr = element.attrib.get("name")
    return isinstance(xml_name_attr, str) and _is_secret_key(xml_name_attr)


def _is_placeholder_heavy(value: str) -> bool:
    return "${" in value or "$(" in value or "{{" in value


def _xml_parse_error_observation(
    relative_path: str,
    *,
    error_kind: str,
    message: str,
    start_line: int | None = None,
    recovered: bool,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": _generic_xml_format(),
        "parser": _parser_name(_generic_xml_format()),
        "safety_mode": _generic_xml_safety_mode(),
        "error_kind": error_kind,
        "message_summary": _safe_error_message(None, message),
        "recovered": recovered,
    }
    if start_line is not None:
        metadata["line_number"] = start_line
    return RawObservation(
        kind="xml.parse_error",
        source_id=f"{relative_path}#xml-parse-error:{start_line or 'document'}",
        path=relative_path,
        start_line=start_line,
        end_line=start_line,
        confidence="unknown",
        extractor=_extractor_name(),
        extractor_version=__version__,
        metadata=metadata,
    )
