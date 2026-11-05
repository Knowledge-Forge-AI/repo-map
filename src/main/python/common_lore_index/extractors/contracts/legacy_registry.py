"""Closed legacy extractor baseline v1 (ADR 0050 D17, ADR 0154).

Membership records continuity of identities present at ADR 0050's acceptance
on 2026-08-12, through reviewed namespace and source-owner moves. It grants no
dependency, capability, containment or native-code exception. Capability sets
are undeclared and lifecycle facts are
undeclared or unavailable; absence of evidence never reads as achievement.

Identity is module and symbol names, never source hashes, so reviewed bug
fixes do not require registry edits. Lookups are exact: no prefix, directory
wildcard, extractor string or copied record can admit a new owner. The
registry holds strings only and never imports or loads code from them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from common_lore_index.extractors.contracts.vocabulary import (
    UNAVAILABLE,
    UNDECLARED,
    ContractError,
)

LEGACY_BASELINE_ID = "cloe-legacy-extractor-baseline-v1"
DISCOVERY_DISPATCH = "common_lore_index.graph.discovery.extract_observations_from_repository_files"
DISCOVERY_ADAPTERS = "common_lore_index.graph.discovery_extractors"
LEGACY_EFFECT_BASIS = "legacy-construction-declaration"

_X = "common_lore_index.extractors."
_C, _D, _L, _S = _X + "config.", _X + "documents.", _X + "languages.", _X + "shell."


@dataclass(frozen=True)
class LegacyEntrypoint:
    """One dispatch call site in the legacy discovery pipeline."""

    name: str
    defining_module: str
    stage: str
    selectors: tuple[str, ...]
    implementation: str
    extractor_names: tuple[str, ...]
    execution_boundary: str


def _entry(name: str, module: str, stage: str, selectors: tuple[str, ...],
           implementation: str, names: tuple[str, ...],
           boundary: str = "pure-python") -> LegacyEntrypoint:
    return LegacyEntrypoint(name, module, stage, selectors, implementation, names, boundary)


def _adapter(name: str, selectors: tuple[str, ...], implementation: str,
             *names: str) -> LegacyEntrypoint:
    return _entry(name, DISCOVERY_ADAPTERS, "S3", selectors, implementation, names)


_SHELL = ("repo-shell",)
_ENTRYPOINTS = (
    _entry("FileInfo.to_observation", "common_lore_index.graph.discovery_records", "S1",
           ("*",), "common_lore_index.graph.discovery_records.FileInfo.to_observation",
           ("repo-discovery",)),
    _entry("PythonModuleIndex.from_python_paths", _L + "python_modules", "S2", ("python",),
           _L + "python_modules.PythonModuleIndex.from_python_paths", ()),
    _entry("markdown_anchor_index", DISCOVERY_ADAPTERS, "S2", ("markdown",),
           _D + "markdown_structure.markdown_anchors_for_content", ()),
    _adapter("extract_go_metadata_observations_from_file", ("go", "go-module", "go-workspace"),
             _L + "go_metadata.extract_go_metadata_observations", "repo-go-metadata"),
    _adapter("extract_markdown_file_observations_from_file", ("markdown",),
             _D + "markdown.extract_markdown_file_observations", "repo-markdown"),
    _adapter("extract_shell_file_observations", ("shell",),
             _S + "base.extract_shell_observations", *_SHELL),
    _adapter("extract_bash_file_observations_from_file", ("bash",),
             _S + "bash.extract_bash_file_observations", "repo-bash", "repo-shell", "repo-zsh"),
    _adapter("extract_bats_file_observations_from_file", ("bats",),
             _S + "bats.extract_bats_file_observations", "repo-bats", "repo-shell"),
    _adapter("extract_awk_file_observations_from_file", ("awk",),
             _S + "awk.extract_awk_file_observations", "repo-awk", "repo-shell"),
    _adapter("extract_zsh_file_observations_from_file", ("zsh",),
             _S + "zsh.extract_zsh_file_observations", "repo-bash", "repo-shell", "repo-zsh"),
    _adapter("extract_zunit_file_observations_from_file", ("zunit",),
             _S + "zunit.extract_zunit_file_observations", "repo-shell", "repo-zunit"),
    _adapter("extract_config_file_observations_from_file",
             ("python-requirements", "json", "jsonc", "jsonl", "toml", "terraform", "plist",
              "xml", "yaml"),
             _C + "generic.extract_config_file_observations", "repo-config"),
    _adapter("extract_python_file_observations_from_file", ("python",),
             _L + "python.extract_python_file_observations", "repo-python"),
    _adapter("extract_ruby_file_observations_from_file", ("ruby",),
             _L + "ruby.extract_ruby_file_observations", "repo-ruby"),
    _adapter("extract_javascript_file_observations_from_file", ("javascript",),
             _L + "javascript.extract_javascript_file_observations", "repo-js"),
    _adapter("extract_eml_file_observations_from_file", ("eml",),
             _D + "email.extract_eml_file_observations", "repo-email"),
    _adapter("extract_mbox_file_observations_from_file", ("mbox",),
             _D + "email.extract_mbox_file_observations", "repo-email"),
    _adapter("extract_nix_file_observations_from_file", ("nix",),
             _C + "nix.extract_nix_file_observations", "repo-nix"),
    _adapter("extract_powershell_file_observations_from_file", ("powershell",),
             _S + "powershell.extract_powershell_file_observations", "repo-powershell"),
    _adapter("extract_feed_file_observations_from_file", ("json", "xml"),
             _D + "feed.extract_feed_file_observations", "repo-feed"),
    _adapter("extract_html_file_observations_from_file", ("html",),
             _D + "html.extract_html_file_observations", "repo-html"),
    _adapter("extract_css_file_observations_from_file", ("css",),
             _D + "css.extract_css_file_observations", "repo-css"),
    # The adapter dispatches both the plain and the ODF implementation through
    # the ``office`` facade, whose import closure bounds both.
    _adapter("extract_document_file_observations_from_file",
             ("text", "csv", "tsv", "latex", "odf"),
             _D + "office.extract_document_file_observations", "repo-documents"),
    _entry("extract_go_repository_observations", _L + "golang", "S4", ("go",),
           _L + "golang.extract_go_repository_observations", ("repo-go-ast", "repo-go-context"),
           "subprocess"),
    _entry("extract_css_selector_match_observations", _D + "css_html_matching", "S4",
           ("observations",), _D + "css_html_matching.extract_css_selector_match_observations",
           ("repo-css-html-matcher",)),
)

LEGACY_ENTRYPOINTS: Mapping[str, LegacyEntrypoint] = MappingProxyType(
    {entry.name: entry for entry in _ENTRYPOINTS}
)

_BASH = ("_bash_side_effect_observations", "bash", "bash_arguments", "bash_command_lines",
         "bash_commands", "bash_constructs", "bash_environment", "bash_identity",
         "bash_redirects", "bash_side_effects")
_ZSH = ("zsh", "zsh_advanced", "zsh_command_observations", "zsh_command_scanning",
        "zsh_configuration", "zsh_identity", "zsh_side_effects")
_POWERSHELL = ("powershell", "powershell_aliases", "powershell_common", "powershell_manifest",
               "powershell_side_effects", "powershell_splats", "powershell_structure")
_SHARED = _X + "shared.observations"  # emits its callers' parameter value
_INGESTION = "common_lore_index.ops.ingestion."

# Exact modules whose ``RawObservation`` constructions emit each extractor name,
# with constants, import aliases, helper getattr and caller parameters resolved.
# A module that only passes a name to a shared builder is attributed through
# that builder; ``shared.observations`` therefore owns its callers' names.
LEGACY_EXTRACTOR_OWNERS: Mapping[str, frozenset[str]] = MappingProxyType({
    "repo-discovery": frozenset({"common_lore_index.graph.discovery_records"}),
    "repo-config": frozenset(_C + name for name in (
        "generic_observations", "generic_profile_helpers", "generic_structure", "javascript",
        "openapi_helpers", "python", "terraform_hcl_observations", "xml", "xml_references")),
    "repo-nix": frozenset(_C + name for name in ("nix", "nix_inputs", "nix_portable_refs")),
    "repo-css": frozenset({_D + "css"}),
    "repo-css-html-matcher": frozenset({_D + "css_html_matching"}),
    "repo-email": frozenset({_D + "email_common", DISCOVERY_ADAPTERS}),
    "repo-feed": frozenset({_D + "feed"}),
    "repo-html": frozenset({_D + "html"}),
    "repo-markdown": frozenset({_D + "markdown"}),
    "repo-documents": frozenset({DISCOVERY_ADAPTERS, *(_D + name for name in (
        "office_common", "office_odf", "office_plain", "office_references"))}),
    "repo-go-metadata": frozenset({_L + "go_metadata", _L + "go_metadata_support"}),
    "repo-go-ast": frozenset({_L + "go_protocol"}),
    "repo-go-context": frozenset({_L + "go_repository_context"}),
    "repo-js": frozenset({_L + "javascript_observations"}),
    "repo-python": frozenset(_L + name for name in (
        "python", "python_imports", "python_symbols", "python_tests", "python_web_observations")),
    "repo-ruby": frozenset({_L + "ruby_profiles"}),
    "repo-shell": frozenset({_S + "base"}),
    "repo-bash": frozenset({_SHARED, *(_S + name for name in _BASH)}),
    "repo-bats": frozenset(_S + name for name in ("bats", "bats_helpers", "bats_observations")),
    "repo-awk": frozenset(_S + name for name in ("awk", "awk_calls", "awk_runtime")),
    "repo-zsh": frozenset({_SHARED, *(_S + name for name in _ZSH)}),
    "repo-zunit": frozenset({_S + "zunit", _S + "zunit_helpers"}),
    "repo-powershell": frozenset(_S + name for name in _POWERSHELL),
    "api-documented-rest-ingestion": frozenset({_INGESTION + "_api_observations"}),
    "github-api-fixture-ingestion": frozenset({_INGESTION + "github_api_observations"}),
    "source-ingestion": frozenset(_INGESTION + name for name in (
        "_source_warc_extraction", "_source_warc_manifest", "source_feed")),
})
SOURCE_INGESTION_NAMES = frozenset(
    {"api-documented-rest-ingestion", "github-api-fixture-ingestion", "source-ingestion"}
)


class LegacyMembershipError(ContractError):
    """Refusal of an exact legacy membership check."""


def legacy_entrypoint(name: object) -> LegacyEntrypoint:
    """Return the registered entrypoint for an exact dispatch name."""

    entry = LEGACY_ENTRYPOINTS.get(_exact_text(name, "not_legacy_entrypoint"))
    if entry is None:
        raise LegacyMembershipError("not_legacy_entrypoint")
    return entry


def _exact_text(value: object, code: str) -> str:
    if not isinstance(value, str) or type(value) is not str:
        raise LegacyMembershipError(code)
    return value


def require_registered_entrypoint(record: object) -> LegacyEntrypoint:
    """Accept only the registry's own record object, never an equal copy."""

    if not isinstance(record, LegacyEntrypoint) or type(record) is not LegacyEntrypoint:
        raise LegacyMembershipError("unregistered_record")
    if LEGACY_ENTRYPOINTS.get(record.name) is not record:
        raise LegacyMembershipError("unregistered_record")
    return record


def is_legacy_extractor_name(name: object) -> bool:
    return isinstance(name, str) and type(name) is str and name in LEGACY_EXTRACTOR_OWNERS


def require_legacy_owner(extractor_name: object, owner_module: object) -> None:
    """Refuse a module emitting a legacy extractor name it does not own.

    This is how a new owner hiding behind a legacy name is refused: the check
    is an exact set membership with no prefix or package-wildcard matching.
    """

    name = _exact_text(extractor_name, "unknown_extractor_name")
    module = _exact_text(owner_module, "unregistered_owner")
    owners = LEGACY_EXTRACTOR_OWNERS.get(name)
    if owners is None:
        raise LegacyMembershipError("unknown_extractor_name")
    if module not in owners:
        raise LegacyMembershipError("unregistered_owner")


def legacy_lifecycle_facts(extractor_name: object) -> Mapping[str, str]:
    """Return the five lifecycle facts for a legacy member: none is achieved.

    The baseline records no installation or admission decision and no
    attempt-scoped capability evidence, so capability lifecycle facts are
    undeclared or unavailable rather than inferred from continuity.
    """

    if not is_legacy_extractor_name(extractor_name):
        raise LegacyMembershipError("unknown_extractor_name")
    return MappingProxyType({
        "capability_set": UNDECLARED,
        "installed": UNDECLARED,
        "admitted": UNDECLARED,
        "attempted": UNAVAILABLE,
        "exercised": UNAVAILABLE,
        "achieved": UNAVAILABLE,
        "effect_basis": LEGACY_EFFECT_BASIS,
        "effect_enforcement": UNAVAILABLE,
        "effect_observation": UNAVAILABLE,
    })
