"""Shared structured-configuration format contracts."""

from __future__ import annotations

import re


PLIST_XML_FORMAT = "plist-xml"
PLIST_XML_SAFETY_MODE = "pre-scan-no-doctype-entity-no-external-resources"
GENERIC_XML_FORMAT = "xml"
GENERIC_XML_SAFETY_MODE = "pre-scan-no-doctype-entity-no-external-resources"
UNSAFE_XML_DECLARATION_PATTERN = re.compile(
    r"<!\s*(?:DOCTYPE|ENTITY)\b",
    re.IGNORECASE,
)
UNSAFE_PROCESSING_INSTRUCTION_PATTERN = re.compile(
    r"<\?(?!xml(?:\s|\?>))",
    re.IGNORECASE,
)
PLIST_ROOT_PATTERN = re.compile(r"<\s*plist(?:\s|>)", re.IGNORECASE)

YAML_FORMAT = "yaml"
YAML_PARSER = "stdlib-yaml-conservative"
YAML_MAX_FILE_BYTES = 1_048_576
YAML_MAX_DOCUMENTS = 64
YAML_MAX_NODES = 25_000
YAML_MAX_DEPTH = 64
YAML_MAX_SCALAR_LENGTH = 4_096
YAML_MAX_ALIASES = 512
YAML_TAG_PATTERN = re.compile(r"^![A-Za-z0-9_./:-]+$")
YAML_ANCHOR_PATTERN = re.compile(r"^&[A-Za-z0-9_.-]+$")
YAML_ALIAS_PATTERN = re.compile(r"^\*[A-Za-z0-9_.-]+$")
YAML_SIMPLE_IMAGE_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?"
    r"(?:@[A-Za-z0-9:_-]+)?$"
)


class PlistXmlSafetyError(ValueError):
    """Raised when XML content uses constructs XML1 refuses to parse."""


class PlistXmlParseError(ValueError):
    """Raised when XML content is not a supported plist structure."""


class GenericXmlSafetyError(ValueError):
    """Raised when generic XML content uses constructs XML2 refuses to parse."""
