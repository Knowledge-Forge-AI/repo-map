"""Canonical graph key builders, parser, and validator."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from repomap_kg.graph._key_namespaces import _SEGMENT_COUNTS


GRAPH_KEY_VERSION = 1
SAFE_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
HEX_CHARS = frozenset("0123456789ABCDEF")
MAX_GO_PATH_IDENTITY_BYTES = 4096
MAX_GO_NAME_IDENTITY_BYTES = 512


class GraphKeyError(ValueError):
    """Raised when a canonical graph key cannot be built or parsed."""


@dataclass(frozen=True)
class ParsedGraphKey:
    graph_key_version: int
    namespace: str
    segments: tuple[str, ...]
    key: str
    path: str | None = None


@dataclass(frozen=True)
class GraphKeyValidation:
    valid: bool
    error: str | None = None


def file_key(path: str | os.PathLike[str]) -> str:
    components = _normalize_file_components(path)
    return "file:" + "/".join(_encode_segment(component) for component in components)


def tool_key(name: str) -> str:
    return _key("tool", name)


def env_key(name: str) -> str:
    return _key("env", name)


def host_category_key(category: str) -> str:
    return _key("host.category", category)


def python_module_key(name: str) -> str:
    return _key("python.module", name)


def python_class_key(module: str, class_name: str) -> str:
    return _key("python.class", module, class_name)


def python_function_key(module: str, function_name: str) -> str:
    return _key("python.function", module, function_name)


def python_method_key(module: str, class_name: str, method_name: str) -> str:
    return _key("python.method", module, class_name, method_name)


def go_module_key(module_path: str) -> str:
    return _key(
        "go.module",
        _bounded_go_path_identity(module_path),
    )


def go_package_key(import_path: str, package_name: str) -> str:
    return _key(
        "go.package",
        _bounded_go_package_import_path(import_path),
        _bounded_go_identity(package_name, MAX_GO_NAME_IDENTITY_BYTES),
    )


def go_type_key(package_key: str, declaration_name: str) -> str:
    return _key(
        "go.type",
        _coerce_go_package_key(package_key),
        _bounded_go_identity(declaration_name, MAX_GO_NAME_IDENTITY_BYTES),
    )


def go_function_key(package_key: str, declaration_name: str) -> str:
    return _key(
        "go.function",
        _coerce_go_package_key(package_key),
        _bounded_go_identity(declaration_name, MAX_GO_NAME_IDENTITY_BYTES),
    )


def go_method_key(
    package_key: str,
    receiver_base: str,
    declaration_name: str,
) -> str:
    return _key(
        "go.method",
        _coerce_go_package_key(package_key),
        _bounded_go_identity(receiver_base, MAX_GO_NAME_IDENTITY_BYTES),
        _bounded_go_identity(declaration_name, MAX_GO_NAME_IDENTITY_BYTES),
    )


def go_const_key(package_key: str, declaration_name: str) -> str:
    return _key(
        "go.const",
        _coerce_go_package_key(package_key),
        _bounded_go_identity(declaration_name, MAX_GO_NAME_IDENTITY_BYTES),
    )


def go_var_key(package_key: str, declaration_name: str) -> str:
    return _key(
        "go.var",
        _coerce_go_package_key(package_key),
        _bounded_go_identity(declaration_name, MAX_GO_NAME_IDENTITY_BYTES),
    )


def nix_app_key(flake_ref: str, system: str, name: str) -> str:
    return _key("nix.app", flake_ref, system, name)


def nix_package_key(flake_ref: str, system: str, name: str) -> str:
    return _key("nix.package", flake_ref, system, name)


def nix_dev_shell_key(flake_ref: str, system: str, name: str) -> str:
    return _key("nix.devShell", flake_ref, system, name)


def nix_check_key(flake_ref: str, system: str, name: str) -> str:
    return _key("nix.check", flake_ref, system, name)


def nix_output_key(flake_ref: str, output_path: str) -> str:
    return _key("nix.output", flake_ref, output_path)


def doc_page_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("doc.page", _coerce_file_key(path_or_file_key))


def doc_section_key(path_or_file_key: str | os.PathLike[str], anchor: str) -> str:
    return _key("doc.section", _coerce_file_key(path_or_file_key), anchor)


def doc_adr_key(number: str) -> str:
    return _key("doc.adr", number)


def doc_skill_key(name: str) -> str:
    return _key("doc.skill", name)


def external_url_key(url: str) -> str:
    return _key("external.url", url)


def config_document_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("config.document", _coerce_file_key(path_or_file_key))


def config_path_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("config.path", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def css_document_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("css.document", _coerce_file_key(path_or_file_key))


def css_rule_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("css.rule", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def css_selector_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key(
        "css.selector",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
    )


def css_custom_property_key(
    path_or_file_key: str | os.PathLike[str], property_name: str
) -> str:
    return _key("css.custom_property", _coerce_file_key(path_or_file_key), property_name)


def html_document_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("html.document", _coerce_file_key(path_or_file_key))


def html_element_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("html.element", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def html_anchor_key(path_or_file_key: str | os.PathLike[str], fragment: str) -> str:
    return _key("html.anchor", _coerce_file_key(path_or_file_key), fragment)


def xml_document_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("xml.document", _coerce_file_key(path_or_file_key))


def xml_element_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("xml.element", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def xml_attribute_key(
    path_or_file_key: str | os.PathLike[str],
    pointer: str,
    attribute_name: str,
) -> str:
    return _key(
        "xml.attribute",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
        attribute_name,
    )


def feed_document_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("feed.document", _coerce_file_key(path_or_file_key))


def feed_channel_key(feed_document_canonical_key: str, channel_id: str) -> str:
    return _key(
        "feed.channel",
        _coerce_namespace_key(feed_document_canonical_key, "feed.document"),
        channel_id,
    )


def feed_item_key(feed_channel_canonical_key: str, item_id: str) -> str:
    return _key(
        "feed.item",
        _coerce_namespace_key(feed_channel_canonical_key, "feed.channel"),
        item_id,
    )


def feed_author_key(feed_channel_canonical_key: str, author_id: str) -> str:
    return _key(
        "feed.author",
        _coerce_namespace_key(feed_channel_canonical_key, "feed.channel"),
        author_id,
    )


def feed_category_key(feed_channel_canonical_key: str, category_id: str) -> str:
    return _key(
        "feed.category",
        _coerce_namespace_key(feed_channel_canonical_key, "feed.channel"),
        category_id,
    )


def warc_document_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("warc.document", _coerce_file_key(path_or_file_key))


def warc_record_key(warc_document_canonical_key: str, record_id: str) -> str:
    return _key(
        "warc.record",
        _coerce_namespace_key(warc_document_canonical_key, "warc.document"),
        record_id,
    )


def document_file_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("document.file", _coerce_file_key(path_or_file_key))


def document_section_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key(
        "document.section",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
    )


def document_table_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key(
        "document.table",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
    )


def document_sheet_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key(
        "document.sheet",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
    )


def document_column_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key(
        "document.column",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
    )


def document_latex_command_key(
    path_or_file_key: str | os.PathLike[str], pointer: str
) -> str:
    return _key(
        "document.latex_command",
        _coerce_file_key(path_or_file_key),
        _coerce_pointer(pointer),
    )


def ruby_file_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("ruby.file", _coerce_file_key(path_or_file_key))


def ruby_module_key(name: str) -> str:
    return _key("ruby.module", name)


def ruby_class_key(class_name: str) -> str:
    return _key("ruby.class", class_name)


def ruby_method_key(owner: str, method_name: str) -> str:
    return _key("ruby.method", owner, method_name)


def ruby_singleton_method_key(owner: str, method_name: str) -> str:
    return _key("ruby.singleton_method", owner, method_name)


def ruby_constant_key(owner: str, constant_name: str) -> str:
    return _key("ruby.constant", owner, constant_name)


def ruby_test_case_key(path_or_file_key: str | os.PathLike[str], name: str) -> str:
    return _key("ruby.test_case", _coerce_file_key(path_or_file_key), name)


def ruby_test_method_key(test_case_canonical_key: str, method_name: str) -> str:
    return _key(
        "ruby.test_method",
        _coerce_namespace_key(test_case_canonical_key, "ruby.test_case"),
        method_name,
    )


def ruby_route_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("ruby.route", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def js_file_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("js.file", _coerce_file_key(path_or_file_key))


def js_module_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("js.module", _coerce_file_key(path_or_file_key))


def js_function_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("js.function", _coerce_file_key(path_or_file_key), _coerce_js_pointer(pointer))


def js_class_key(path_or_file_key: str | os.PathLike[str], class_name: str) -> str:
    return _key("js.class", _coerce_file_key(path_or_file_key), class_name)


def js_method_key(js_class_canonical_key: str, method_name: str) -> str:
    return _key(
        "js.method",
        _coerce_namespace_key(js_class_canonical_key, "js.class"),
        method_name,
    )


def js_variable_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("js.variable", _coerce_file_key(path_or_file_key), _coerce_js_pointer(pointer))


def js_component_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("js.component", _coerce_file_key(path_or_file_key), _coerce_js_pointer(pointer))


def js_test_suite_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("js.test_suite", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def js_test_case_key(owner_canonical_key: str, pointer: str) -> str:
    parsed = parse_key(owner_canonical_key)
    if parsed.namespace not in ("js.file", "js.test_suite"):
        raise GraphKeyError("js.test_case keys require js.file or js.test_suite owner")
    return _key("js.test_case", owner_canonical_key, _coerce_pointer(pointer))


def js_route_key(path_or_file_key: str | os.PathLike[str], pointer: str) -> str:
    return _key("js.route", _coerce_file_key(path_or_file_key), _coerce_pointer(pointer))


def bash_script_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("bash.script", _coerce_file_key(path_or_file_key))


def bash_function_key(
    path_or_file_key: str | os.PathLike[str], function_name: str
) -> str:
    return _key("bash.function", _coerce_file_key(path_or_file_key), function_name)


def bats_file_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("bats.file", _coerce_file_key(path_or_file_key))


def bats_test_case_key(
    path_or_file_key: str | os.PathLike[str], test_identity: str
) -> str:
    return _key("bats.test_case", _coerce_file_key(path_or_file_key), test_identity)


def bats_expectation_key(
    path_or_file_key: str | os.PathLike[str],
    test_identity: str,
    line_number: int | str,
    assertion_name: str,
) -> str:
    test_key = bats_test_case_key(path_or_file_key, test_identity)
    return _key("bats.expectation", test_key, str(line_number), assertion_name)


def awk_program_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("awk.program", _coerce_file_key(path_or_file_key))


def awk_function_key(
    path_or_file_key: str | os.PathLike[str], function_name: str
) -> str:
    return _key("awk.function", _coerce_file_key(path_or_file_key), function_name)


def zsh_script_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("zsh.script", _coerce_file_key(path_or_file_key))


def zsh_function_key(
    path_or_file_key: str | os.PathLike[str], function_name: str
) -> str:
    return _key("zsh.function", _coerce_file_key(path_or_file_key), function_name)


def zunit_file_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("zunit.file", _coerce_file_key(path_or_file_key))


def zunit_suite_key(
    path_or_file_key: str | os.PathLike[str], suite_identity: str
) -> str:
    return _key("zunit.suite", _coerce_file_key(path_or_file_key), suite_identity)


def zunit_test_case_key(
    path_or_file_key: str | os.PathLike[str], test_identity: str
) -> str:
    return _key("zunit.test_case", _coerce_file_key(path_or_file_key), test_identity)


def zunit_hook_key(
    path_or_file_key: str | os.PathLike[str],
    hook_kind: str,
    line_number: int | str,
) -> str:
    return _key("zunit.hook", _coerce_file_key(path_or_file_key), hook_kind, str(line_number))


def zunit_assertion_key(
    path_or_file_key: str | os.PathLike[str],
    line_number: int | str,
    assertion_name: str,
) -> str:
    return _key(
        "zunit.assertion",
        _coerce_file_key(path_or_file_key),
        str(line_number),
        assertion_name,
    )


def zunit_expectation_key(
    path_or_file_key: str | os.PathLike[str],
    line_number: int | str,
    expectation_kind: str,
) -> str:
    return _key(
        "zunit.expectation",
        _coerce_file_key(path_or_file_key),
        str(line_number),
        expectation_kind,
    )


def zunit_command_under_test_key(
    path_or_file_key: str | os.PathLike[str],
    line_number: int | str,
    command_identity: str,
) -> str:
    return _key(
        "zunit.command_under_test",
        _coerce_file_key(path_or_file_key),
        str(line_number),
        command_identity,
    )


def zunit_mock_key(
    path_or_file_key: str | os.PathLike[str],
    line_number: int | str,
    command_identity: str,
) -> str:
    return _key(
        "zunit.mock",
        _coerce_file_key(path_or_file_key),
        str(line_number),
        command_identity,
    )


def zunit_stub_key(
    path_or_file_key: str | os.PathLike[str],
    line_number: int | str,
    command_identity: str,
) -> str:
    return _key(
        "zunit.stub",
        _coerce_file_key(path_or_file_key),
        str(line_number),
        command_identity,
    )


def powershell_script_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("powershell.script", _coerce_file_key(path_or_file_key))


def powershell_module_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("powershell.module", _coerce_file_key(path_or_file_key))


def powershell_manifest_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("powershell.manifest", _coerce_file_key(path_or_file_key))


def powershell_function_key(
    path_or_file_key: str | os.PathLike[str], function_name: str
) -> str:
    return _key("powershell.function", _coerce_file_key(path_or_file_key), function_name)


def powershell_manifest_export_key(
    manifest_canonical_key: str, export_kind: str, export_name: str
) -> str:
    return _key(
        "powershell.export",
        _coerce_namespace_key(manifest_canonical_key, "powershell.manifest"),
        export_kind,
        export_name,
    )


def email_message_key(path_or_file_key: str | os.PathLike[str], identity: str) -> str:
    return _key("email.message", _coerce_file_key(path_or_file_key), identity)


def email_mailbox_key(path_or_file_key: str | os.PathLike[str]) -> str:
    return _key("email.mailbox", _coerce_file_key(path_or_file_key))


def email_address_key(address_identity: str) -> str:
    return _key("email.address", address_identity)


def email_part_key(email_message_canonical_key: str, pointer: str) -> str:
    return _key(
        "email.part",
        _coerce_namespace_key(email_message_canonical_key, "email.message"),
        _coerce_pointer(pointer),
    )


def email_attachment_stub_key(
    email_message_canonical_key: str, pointer: str
) -> str:
    return _key(
        "email.attachment_stub",
        _coerce_namespace_key(email_message_canonical_key, "email.message"),
        _coerce_pointer(pointer),
    )


def email_thread_hint_key(email_message_canonical_key: str, pointer: str) -> str:
    return _key(
        "email.thread_hint",
        _coerce_namespace_key(email_message_canonical_key, "email.message"),
        _coerce_pointer(pointer),
    )


def dynamic_key(domain: str, reason: str) -> str:
    return _key("dynamic", domain, reason)


def external_key(domain: str, stable_name: str) -> str:
    return _key("external", domain, stable_name)


def unknown_key(domain: str, reason: str) -> str:
    return _key("unknown", domain, reason)


def parse_key(key: str) -> ParsedGraphKey:
    if not isinstance(key, str):
        raise GraphKeyError("canonical key must be a string")
    if not key:
        raise GraphKeyError("canonical key is required")
    namespace, separator, remainder = key.partition(":")
    if not separator:
        raise GraphKeyError("canonical key must include a namespace separator")
    if namespace == "file":
        segments = _parse_file_segments(remainder)
        return ParsedGraphKey(
            graph_key_version=GRAPH_KEY_VERSION,
            namespace=namespace,
            segments=segments,
            key=key,
            path="/".join(segments),
        )
    expected_count = _SEGMENT_COUNTS.get(namespace)
    if expected_count is None:
        raise GraphKeyError(f"unknown canonical key namespace: {namespace}")
    raw_segments = remainder.split(":")
    if len(raw_segments) != expected_count:
        raise GraphKeyError(f"{namespace} keys require {expected_count} segments")
    segments = tuple(_decode_segment(segment) for segment in raw_segments)
    return ParsedGraphKey(
        graph_key_version=GRAPH_KEY_VERSION,
        namespace=namespace,
        segments=segments,
        key=key,
    )


def validate_key(key: Any) -> GraphKeyValidation:
    try:
        parse_key(key)
    except GraphKeyError as error:
        return GraphKeyValidation(valid=False, error=str(error))
    return GraphKeyValidation(valid=True)


def _bounded_go_identity(value: str, maximum_bytes: int) -> str:
    if not isinstance(value, str) or not value:
        raise GraphKeyError("Go canonical identity component is required")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise GraphKeyError(
            f"Go canonical identity component exceeds {maximum_bytes} UTF-8 bytes"
        )
    return value


def _bounded_go_path_identity(value: str) -> str:
    value = _bounded_go_identity(value, MAX_GO_PATH_IDENTITY_BYTES)
    if (
        value != value.strip()
        or value.startswith(("/", "~"))
        or "\\" in value
        or ":" in value
        or any(character.isspace() for character in value)
    ):
        raise GraphKeyError("Go module identity must be a non-local slash path")
    components = value.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise GraphKeyError("Go module identity must not traverse directories")
    return value


def _bounded_go_package_import_path(value: str) -> str:
    value = _bounded_go_identity(value, MAX_GO_PATH_IDENTITY_BYTES)
    fallback_prefix = "repo-relative:"
    if not value.startswith(fallback_prefix):
        return _bounded_go_path_identity(value)
    relative = value[len(fallback_prefix) :]
    if relative == ".":
        return value
    if (
        not relative
        or relative.startswith(("/", "~"))
        or "\\" in relative
        or ":" in relative
        or any(character.isspace() for character in relative)
        or any(component in {"", ".", ".."} for component in relative.split("/"))
    ):
        raise GraphKeyError("Go package fallback identity must be repository-relative")
    return value


def _coerce_go_package_key(key: str) -> str:
    parsed = parse_key(key)
    if parsed.namespace != "go.package":
        raise GraphKeyError("go.package keys require a go.package parent key")
    _bounded_go_package_import_path(parsed.segments[0])
    _bounded_go_identity(parsed.segments[1], MAX_GO_NAME_IDENTITY_BYTES)
    return key


def _key(namespace: str, *segments: str) -> str:
    expected_count = _SEGMENT_COUNTS[namespace]
    if len(segments) != expected_count:
        raise GraphKeyError(f"{namespace} keys require {expected_count} segments")
    return namespace + ":" + ":".join(_encode_segment(segment) for segment in segments)


def _coerce_file_key(path_or_file_key: str | os.PathLike[str]) -> str:
    if isinstance(path_or_file_key, str) and path_or_file_key.startswith("file:"):
        parsed = parse_key(path_or_file_key)
        if parsed.namespace != "file":
            raise GraphKeyError("documentation page keys require a file key")
        return path_or_file_key
    return file_key(path_or_file_key)


def _coerce_namespace_key(key: str, namespace: str) -> str:
    parsed = parse_key(key)
    if parsed.namespace != namespace:
        raise GraphKeyError(f"{namespace} keys require a {namespace} parent key")
    return key


def _coerce_pointer(pointer: str) -> str:
    if not isinstance(pointer, str) or not pointer:
        raise GraphKeyError("config pointer is required")
    if not pointer.startswith("/"):
        raise GraphKeyError("config pointer must be normalized")
    return pointer


def _coerce_js_pointer(pointer: str) -> str:
    if not isinstance(pointer, str) or not pointer.strip():
        raise GraphKeyError("JavaScript pointer is required")
    return pointer


def _normalize_file_components(path: str | os.PathLike[str]) -> tuple[str, ...]:
    if isinstance(path, PurePath):
        raw_path = path.as_posix()
    elif isinstance(path, os.PathLike):
        raw_path = os.fspath(path)
    elif isinstance(path, str):
        raw_path = path
    else:
        raise GraphKeyError("file path must be a string or path-like object")
    if not isinstance(raw_path, str) or not raw_path:
        raise GraphKeyError("file path is required")
    raw_path = raw_path.replace("\\", "/")
    if raw_path.startswith("/"):
        raise GraphKeyError("file path must not be absolute")
    components: list[str] = []
    for component in raw_path.split("/"):
        if component in ("", "."):
            continue
        if component == "..":
            if not components:
                raise GraphKeyError("file path must not escape the repository")
            components.pop()
            continue
        components.append(component)
    if not components:
        return (".",)
    return tuple(components)


def _parse_file_segments(path_text: str) -> tuple[str, ...]:
    if not path_text:
        raise GraphKeyError("file key requires a path")
    raw_segments = path_text.split("/")
    if any(segment == "" for segment in raw_segments):
        raise GraphKeyError("file key path must not contain empty components")
    segments = tuple(_decode_segment(segment) for segment in raw_segments)
    if segments == (".",):
        return segments
    if "." in segments:
        raise GraphKeyError("file key path must be normalized")
    if ".." in segments:
        raise GraphKeyError("file key path must not escape the repository")
    return segments


def _encode_segment(segment: str) -> str:
    if not isinstance(segment, str) or not segment:
        raise GraphKeyError("canonical key segment is required")
    parts: list[str] = []
    for byte in segment.encode("utf-8"):
        character = chr(byte)
        if character in SAFE_CHARS:
            parts.append(character)
        else:
            parts.append(f"%{byte:02X}")
    return "".join(parts)


def _decode_segment(segment: str) -> str:
    if segment == "":
        raise GraphKeyError("canonical key segment is required")
    decoded = bytearray()
    index = 0
    while index < len(segment):
        character = segment[index]
        if character == "%":
            decoded.append(_decode_percent_byte(segment, index))
            index += 3
            continue
        if character not in SAFE_CHARS:
            raise GraphKeyError(
                f"reserved character {character!r} must be percent-encoded"
            )
        decoded.append(ord(character))
        index += 1
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GraphKeyError("percent-encoded segment is not valid UTF-8") from error


def _decode_percent_byte(segment: str, index: int) -> int:
    escape = segment[index : index + 3]
    if len(escape) != 3:
        raise GraphKeyError("malformed percent escape")
    if escape[1].upper() != escape[1] or escape[2].upper() != escape[2]:
        raise GraphKeyError("percent escapes must use uppercase hex digits")
    if escape[1] not in HEX_CHARS or escape[2] not in HEX_CHARS:
        raise GraphKeyError("malformed percent escape")
    return int(escape[1:], 16)
