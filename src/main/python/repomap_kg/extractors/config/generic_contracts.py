"""Neutral contracts shared by structured configuration extractors."""

from repomap_kg.extractors.config.format_contracts import (
    GENERIC_XML_FORMAT,
    GENERIC_XML_SAFETY_MODE,
    PLIST_ROOT_PATTERN,
    PLIST_XML_FORMAT,
    PLIST_XML_SAFETY_MODE,
    UNSAFE_PROCESSING_INSTRUCTION_PATTERN,
    UNSAFE_XML_DECLARATION_PATTERN,
    YAML_ALIAS_PATTERN,
    YAML_ANCHOR_PATTERN,
    YAML_FORMAT,
    YAML_MAX_ALIASES,
    YAML_MAX_DEPTH,
    YAML_MAX_DOCUMENTS,
    YAML_MAX_FILE_BYTES,
    YAML_MAX_NODES,
    YAML_MAX_SCALAR_LENGTH,
    YAML_PARSER,
    YAML_SIMPLE_IMAGE_PATTERN,
    YAML_TAG_PATTERN,
)
from repomap_kg.extractors.config.generic_observations import (
    _document_observation,
    _parse_error_observation,
    _safe_error_message,
)
from repomap_kg.extractors.config.generic_profile_helpers import (
    EXTRACTOR_NAME,
    _profile_observation,
    _stable_text_sha256,
    _stable_value_sha256,
    _url_has_credentials,
    _value_shape,
)
from repomap_kg.extractors.config.generic_reference_contracts import (
    _file_reference,
    _reference,
)
from repomap_kg.extractors.config.generic_structure import (
    _is_clear_command_name,
    _line_for_pointer,
    _parser_name,
    _structure_observations,
)
from repomap_kg.extractors.config.generic_values import (
    SECRET_PRONE_KEYS,
    _is_dynamic_value,
    _is_secret_key,
    _is_secret_pointer,
    _is_url,
    _looks_like_container_image,
    _looks_like_secret_scalar,
    _normalize_repo_path,
    _normalized_key,
    _resolve_repo_path,
    _safe_value_summary,
    _stable_array_members,
    _value_type,
    _yaml_documents,
)
