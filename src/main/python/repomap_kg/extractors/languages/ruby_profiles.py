"""Ruby observation construction and ecosystem profile helpers."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.languages.ruby_helpers import (
    _first_literal,
    _path_target,
    _safe_summary,
    _sanitize_url,
)
from repomap_kg.graph.keys import external_key, external_url_key
from repomap_kg.observations.raw import RawObservation


EXTRACTOR = "repo-ruby"
PARSER = "stdlib-ruby-lexical"

VAGRANT_BOX_RE = re.compile(r'config\.vm\.box\s*=\s*(["\'])(.*?)\1')
VAGRANT_PROVIDER_RE = re.compile(r'config\.vm\.provider\s*(["\'])(.*?)\1')
VAGRANT_NETWORK_RE = re.compile(r'config\.vm\.network\s+(["\'])(.*?)\1')
VAGRANT_SYNCED_RE = re.compile(
    r'config\.vm\.synced_folder\s+(["\'])(.*?)\1\s*,\s*(["\'])(.*?)\3'
)
VAGRANT_PROVISION_RE = re.compile(r"config\.vm\.provision\b")
GEM_RE = re.compile(r'^\s*gem\s+(["\'])(.*?)\1(?P<tail>.*)$')
GEM_SOURCE_RE = re.compile(r'^\s*source\s+(["\'])(.*?)\1')
GEMSPEC_DEP_RE = re.compile(
    r"\badd_(?:runtime_|development_)?dependency\s*\(?\s*([\"'])(.*?)\1(?P<tail>.*)$"
)


def _observation(*, kind: str, relative_path: str, source_id: str, metadata: dict[str, Any], confidence: str = "extracted", start_line: int | None = None, name: str | None = None, target: str | None = None) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=source_id,
        path=relative_path,
        confidence=confidence,
        extractor=EXTRACTOR,
        extractor_version=__version__,
        start_line=start_line,
        end_line=start_line,
        name=name,
        target=target,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _definition_observation(kind: str, relative_path: str, profile: str, line_number: int, name: str, target: str, *, source_key: str, metadata: dict[str, Any]) -> RawObservation:
    payload = {
        "format": "ruby",
        "profile": profile,
        "profiles": [profile],
        "parser": PARSER,
        "source_key": source_key,
        "identity_strength": "symbolic",
    }
    payload.update(metadata)
    return _observation(
        kind=kind,
        relative_path=relative_path,
        source_id=f"{relative_path}#{kind}:{name}:{line_number}",
        start_line=line_number,
        name=name,
        target=target,
        metadata=payload,
    )


def _reference_observation(relative_path: str, profile: str, line_number: int, reference_kind: str, raw_value: str, target: str, source_key: str, *, resolution_reason: str, extra_metadata: dict[str, Any] | None = None) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": "ruby",
        "profile": profile,
        "profiles": [profile],
        "parser": PARSER,
        "reference_kind": reference_kind,
        "raw_value_summary": _safe_summary(raw_value),
        "source_key": source_key,
        "target_key": target,
        "resolution_reason": resolution_reason,
        "not_fetched": True,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return _observation(
        kind="ruby.reference",
        relative_path=relative_path,
        source_id=f"{relative_path}#ruby-reference:{reference_kind}:{line_number}:{len(raw_value)}",
        start_line=line_number,
        name=reference_kind,
        target=target,
        metadata=metadata,
    )


def _vagrant_observations(relative_path: str, profile: str, line_number: int, line: str, source_key: str, repository_paths: frozenset[str] | None) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    if match := VAGRANT_BOX_RE.search(line):
        box_name = match.group(2)
        target = external_key("vagrant-box", box_name)
        observations.append(
            _vagrant_config(relative_path, line_number, "box", profile, source_key)
        )
        observations.append(
            _reference_observation(
                relative_path,
                profile,
                line_number,
                "vagrant_box",
                box_name,
                target,
                source_key,
                resolution_reason="external-vagrant-box",
                extra_metadata={"vagrant_key": "box"},
            )
        )
    if match := VAGRANT_PROVIDER_RE.search(line):
        provider = match.group(2)
        observations.append(
            _vagrant_config(
                relative_path,
                line_number,
                "provider",
                profile,
                source_key,
                value_summary=provider,
            )
        )
    if match := VAGRANT_NETWORK_RE.search(line):
        network_name = match.group(2)
        observations.append(
            _vagrant_config(
                relative_path,
                line_number,
                "network",
                profile,
                source_key,
                value_summary=network_name,
            )
        )
    if match := VAGRANT_SYNCED_RE.search(line):
        local_path = match.group(2)
        target = _path_target(local_path, repository_paths)
        observations.append(
            _vagrant_config(
                relative_path,
                line_number,
                "synced_folder",
                profile,
                source_key,
            )
        )
        observations.append(
            _reference_observation(
                relative_path,
                profile,
                line_number,
                "vagrant_synced_folder",
                local_path,
                target,
                source_key,
                resolution_reason="repo-local" if target.startswith("file:") else "path",
                extra_metadata={"vagrant_key": "synced_folder"},
            )
        )
    if VAGRANT_PROVISION_RE.search(line):
        observations.append(
            _vagrant_config(
                relative_path,
                line_number,
                "provision",
                profile,
                source_key,
                redacted=True,
                dynamic=True,
                redaction_reason="provisioner-command-body-omitted",
            )
        )
    return tuple(observations)


def _vagrant_config(relative_path: str, line_number: int, vagrant_key: str, profile: str, source_key: str, *, value_summary: str | None = None, redacted: bool = False, dynamic: bool = False, redaction_reason: str | None = None) -> RawObservation:
    return _observation(
        kind="ruby.vagrant_config",
        relative_path=relative_path,
        source_id=f"{relative_path}#ruby-vagrant:{vagrant_key}:{line_number}",
        start_line=line_number,
        name=vagrant_key,
        metadata={
            "format": "ruby",
            "profile": profile,
            "parser": PARSER,
            "dsl_name": "vagrant",
            "vagrant_key": vagrant_key,
            "value_summary": _safe_summary(value_summary) if value_summary else None,
            "source_key": source_key,
            "redacted": redacted,
            "dynamic": dynamic,
            "redaction_reason": redaction_reason,
        },
    )


def _gemfile_observations(relative_path: str, profile: str, line_number: int, line: str, source_key: str) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    if source_match := GEM_SOURCE_RE.match(line):
        source_url = _sanitize_url(source_match.group(2))
        target = external_url_key(source_url)
        observations.append(
            _reference_observation(
                relative_path,
                profile,
                line_number,
                "gem_source",
                source_url,
                target,
                source_key,
                resolution_reason="external-url",
            )
        )
    if gem_match := GEM_RE.match(line):
        gem_name = gem_match.group(2)
        observations.extend(
            _gem_dependency_observations(
                relative_path,
                profile,
                line_number,
                gem_name,
                gem_match.group("tail"),
                source_key,
                "gemfile",
            )
        )
    return tuple(observations)


def _gemspec_observations(relative_path: str, profile: str, line_number: int, line: str, source_key: str) -> tuple[RawObservation, ...]:
    if dep_match := GEMSPEC_DEP_RE.search(line):
        return _gem_dependency_observations(
            relative_path,
            profile,
            line_number,
            dep_match.group(2),
            dep_match.group("tail"),
            source_key,
            "gemspec",
        )
    return ()


def _gem_dependency_observations(relative_path: str, profile: str, line_number: int, gem_name: str, requirement_tail: str, source_key: str, dependency_source: str) -> tuple[RawObservation, ...]:
    target = external_key("ruby-gem", gem_name)
    requirement_summary = _first_literal(requirement_tail)
    dependency = _observation(
        kind="ruby.gem_dependency",
        relative_path=relative_path,
        source_id=f"{relative_path}#ruby-gem:{gem_name}:{line_number}",
        start_line=line_number,
        name=gem_name,
        target=target,
        metadata={
            "format": "ruby",
            "profile": profile,
            "parser": PARSER,
            "gem_name": gem_name,
            "gem_requirement_summary": _safe_summary(requirement_summary),
            "dependency_source": dependency_source,
            "source_key": source_key,
        },
    )
    reference = _reference_observation(
        relative_path,
        profile,
        line_number,
        "gem_dependency",
        gem_name,
        target,
        source_key,
        resolution_reason="external-ruby-gem",
    )
    return (dependency, reference)
