"""Conservative static Ruby and Ruby-DSL extraction."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.languages.ruby_helpers import (
    REFERENCE_SCHEMES,
    SECRET_MARKERS,
    _Scope,
    _current_owner,
    _current_route_key,
    _current_source_key,
    _current_test_case_key,
    _dynamic_reasons,
    _first_literal,
    _is_dynamic_literal,
    _is_minitest_class,
    _is_secret_prone,
    _literal_type,
    _looks_like_route_profile,
    _method_owner,
    _normalize_posix,
    _normalize_relative_path,
    _opens_block,
    _owner_key_for_scope,
    _path_target,
    _pop_scope,
    _qualify_name,
    _require_target,
    _safe_summary,
    _sanitize_url,
    _strip_comment,
)
from repomap_kg.graph.keys import (
    external_key,
    external_url_key,
    file_key,
    ruby_class_key,
    ruby_constant_key,
    ruby_file_key,
    ruby_method_key,
    ruby_module_key,
    ruby_route_key,
    ruby_singleton_method_key,
    ruby_test_case_key,
    ruby_test_method_key,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.languages.ruby_profiles import (
    GEMSPEC_DEP_RE,
    GEM_RE,
    GEM_SOURCE_RE,
    VAGRANT_BOX_RE,
    VAGRANT_NETWORK_RE,
    VAGRANT_PROVIDER_RE,
    VAGRANT_PROVISION_RE,
    VAGRANT_SYNCED_RE,
    _definition_observation,
    _gem_dependency_observations,
    _gemfile_observations,
    _gemspec_observations,
    _observation,
    _reference_observation,
    _vagrant_config,
    _vagrant_observations,
)



EXTRACTOR = "repo-ruby"
PARSER = "stdlib-ruby-lexical"
MAX_FILE_BYTES = 512 * 1024
ROUTE_METHODS = frozenset(("get", "post", "put", "patch", "delete", "options", "head"))

MODULE_RE = re.compile(r"^\s*module\s+([A-Z]\w*(?:::[A-Z]\w*)*)\b")
CLASS_RE = re.compile(
    r"^\s*class\s+([A-Z]\w*(?:::[A-Z]\w*)*)"
    r"(?:\s*<\s*([A-Z]\w*(?:::[A-Z]\w*)*))?\b"
)
DEF_RE = re.compile(
    r"^\s*def\s+(self\.[A-Za-z_]\w*[!?=]?|"
    r"[A-Z]\w*(?:::[A-Z]\w*)*\.[A-Za-z_]\w*[!?=]?|"
    r"[A-Za-z_]\w*[!?=]?)\b"
)
CONSTANT_RE = re.compile(r"^\s*([A-Z]\w*)\s*=\s*(.+)$")
REQUIRE_RE = re.compile(r'^\s*(require|require_relative|load)\s*\(?\s*(["\'])(.*?)\2')
INCLUDE_RE = re.compile(r"^\s*(include|extend)\s+([A-Z]\w*(?:::[A-Z]\w*)*)\b")
ROUTE_RE = re.compile(
    r"""^\s*(get|post|put|patch|delete|options|head)\s*\(?\s*(["'])(.*?)\2"""
)
ERB_RE = re.compile(r"^\s*(erb|haml|slim)\s+(?::([A-Za-z_]\w*)|([\"'])(.*?)\3)")
RAKE_DESC_RE = re.compile(r'^\s*desc\s+(["\'])(.*?)\1')
RAKE_NAMESPACE_RE = re.compile(r"^\s*namespace\s+(?::([A-Za-z_]\w*)|([\"'])(.*?)\2)")
RAKE_TASK_RE = re.compile(r"^\s*task\s+(?::([A-Za-z_]\w*)|([\"'])(.*?)\2)")
ENV_RE = re.compile(r'ENV(?:\.fetch)?\s*\[\s*(["\'])(.*?)\1\s*\]|ENV\.fetch\(\s*(["\'])(.*?)\3')
MINITEST_DESCRIBE_RE = re.compile(
    r'^\s*describe\s+(?:(["\'])(.*?)\1|([A-Z]\w*(?:::[A-Z]\w*)*))\s+do\b'
)
MINITEST_IT_RE = re.compile(r'^\s*it\s+(["\'])(.*?)\1\s+do\b')
SINATRA_DSL_RE = re.compile(r"^\s*(set|configure|before|after|helpers)\b")


def extract_ruby_file_observations(
    relative_path: str,
    content: str,
    *,
    repository_paths: frozenset[str] | None = None,
) -> tuple[RawObservation, ...]:
    """Extract safe, static Ruby facts from local text."""

    profile = _detect_profile(relative_path, content)
    observations: list[RawObservation] = []
    file_canonical_key = ruby_file_key(relative_path)
    observations.append(
        _observation(
            kind="ruby.file",
            relative_path=relative_path,
            source_id=f"{relative_path}#ruby-file",
            name=relative_path,
            target=file_canonical_key,
            metadata={
                "format": "ruby",
                "profile": profile,
                "profiles": [profile],
                "parser": PARSER,
                "file_bytes": len(content.encode("utf-8", errors="replace")),
            },
        )
    )

    if len(content.encode("utf-8", errors="replace")) > MAX_FILE_BYTES:
        observations.append(
            _parse_error(
                relative_path,
                "file-size-limit",
                "ruby file exceeds static scanner limit",
                profile,
                1,
            )
        )
        return tuple(observations)

    stack: list[_Scope] = []
    last_rake_desc: str | None = None
    spec_case_count = 0
    spec_method_counts: dict[str, int] = {}
    lines = content.splitlines()
    for line_number, raw_line in enumerate(lines, start=1):
        line = _strip_comment(raw_line)
        stripped = line.strip()
        if not stripped:
            continue

        for dynamic_reason in _dynamic_reasons(stripped):
            observations.append(
                _parse_error(
                    relative_path,
                    f"dynamic-{dynamic_reason}",
                    "dynamic Ruby construct kept as diagnostic",
                    profile,
                    line_number,
                    dynamic_reason=dynamic_reason,
                )
            )

        env_match = ENV_RE.search(stripped)
        if env_match:
            env_name = env_match.group(2) or env_match.group(4) or ""
            observations.append(
                _diagnostic_observation(
                    relative_path,
                    profile,
                    line_number,
                    "env-reference",
                    env_name,
                    redacted=_is_secret_prone(env_name),
                )
            )

        if stripped == "end" or stripped.startswith("end "):
            _pop_scope(stack)
            continue

        module_match = MODULE_RE.match(stripped)
        if module_match:
            name = _qualify_name(module_match.group(1), stack)
            target = ruby_module_key(name)
            observations.append(
                _definition_observation(
                    "ruby.module",
                    relative_path,
                    profile,
                    line_number,
                    name,
                    target,
                    source_key=file_canonical_key,
                    metadata={"qualified_name": name},
                )
            )
            stack.append(_Scope("module", name, canonical_key=target))
            continue

        class_match = CLASS_RE.match(stripped)
        if class_match:
            name = _qualify_name(class_match.group(1), stack)
            superclass = class_match.group(2)
            target = ruby_class_key(name)
            metadata: dict[str, Any] = {"qualified_name": name}
            if superclass:
                metadata["superclass"] = superclass
            observations.append(
                _definition_observation(
                    "ruby.class",
                    relative_path,
                    profile,
                    line_number,
                    name,
                    target,
                    source_key=file_canonical_key,
                    metadata=metadata,
                )
            )
            test_case_key = None
            if _is_minitest_class(superclass, profile):
                test_case_key = ruby_test_case_key(relative_path, name)
                observations.append(
                    _definition_observation(
                        "ruby.test_case",
                        relative_path,
                        "minitest",
                        line_number,
                        name,
                        test_case_key,
                        source_key=file_canonical_key,
                        metadata={
                            "qualified_name": name,
                            "test_framework": "minitest",
                        },
                    )
                )
            stack.append(
                _Scope(
                    "class",
                    name,
                    canonical_key=target,
                    test_case_key=test_case_key,
                )
            )
            continue

        if profile == "minitest":
            describe_match = MINITEST_DESCRIBE_RE.match(stripped)
            if describe_match:
                spec_case_count += 1
                describe_text = describe_match.group(2) or describe_match.group(3) or ""
                test_case_name = f"describe[{spec_case_count}]"
                test_case_key = ruby_test_case_key(relative_path, test_case_name)
                observations.append(
                    _definition_observation(
                        "ruby.test_case",
                        relative_path,
                        "minitest",
                        line_number,
                        test_case_name,
                        test_case_key,
                        source_key=file_canonical_key,
                        metadata={
                            "qualified_name": test_case_name,
                            "test_framework": "minitest",
                            "test_name_summary": _safe_summary(describe_text),
                            "identity_strength": "structural",
                        },
                    )
                )
                stack.append(
                    _Scope(
                        "test_case",
                        test_case_name,
                        canonical_key=test_case_key,
                        test_case_key=test_case_key,
                    )
                )
                continue

            it_match = MINITEST_IT_RE.match(stripped)
            test_case_key = _current_test_case_key(stack)
            if it_match and test_case_key:
                method_count = spec_method_counts.get(test_case_key, 0) + 1
                spec_method_counts[test_case_key] = method_count
                method_name = f"it[{method_count}]"
                target_test = ruby_test_method_key(test_case_key, method_name)
                observations.append(
                    _definition_observation(
                        "ruby.test_method",
                        relative_path,
                        "minitest",
                        line_number,
                        method_name,
                        target_test,
                        source_key=test_case_key,
                        metadata={
                            "test_case_key": test_case_key,
                            "method_name": method_name,
                            "test_framework": "minitest",
                            "test_name_summary": _safe_summary(it_match.group(2)),
                            "identity_strength": "structural",
                        },
                    )
                )
                stack.append(_Scope("test_method", method_name, canonical_key=target_test))
                continue

        def_match = DEF_RE.match(stripped)
        if def_match:
            method_token = def_match.group(1)
            owner, method_name, singleton = _method_owner(method_token, stack)
            if owner and method_name:
                target = (
                    ruby_singleton_method_key(owner, method_name)
                    if singleton
                    else ruby_method_key(owner, method_name)
                )
                owner_key = _owner_key_for_scope(owner, stack) or file_canonical_key
                kind = "ruby.singleton_method" if singleton else "ruby.method"
                observations.append(
                    _definition_observation(
                        kind,
                        relative_path,
                        profile,
                        line_number,
                        method_name,
                        target,
                        source_key=owner_key,
                        metadata={
                            "qualified_name": f"{owner}.{method_name}",
                            "owner": owner,
                            "method_name": method_name,
                        },
                    )
                )
                test_case_key = _current_test_case_key(stack)
                if test_case_key and method_name.startswith("test_"):
                    target_test = ruby_test_method_key(test_case_key, method_name)
                    observations.append(
                        _definition_observation(
                            "ruby.test_method",
                            relative_path,
                            "minitest",
                            line_number,
                            method_name,
                            target_test,
                            source_key=test_case_key,
                            metadata={
                                "test_case_key": test_case_key,
                                "method_name": method_name,
                                "test_framework": "minitest",
                            },
                        )
                    )
                stack.append(_Scope("method", method_name, canonical_key=target))
                continue

        const_match = CONSTANT_RE.match(stripped)
        if const_match:
            constant_name = const_match.group(1)
            owner = _current_owner(stack) or "Object"
            target = ruby_constant_key(owner, constant_name)
            redacted = _is_secret_prone(constant_name)
            metadata = {
                "owner": owner,
                "constant_name": constant_name,
                "value_type": _literal_type(const_match.group(2)),
                "redacted": redacted,
            }
            if redacted:
                metadata["redaction_reason"] = "secret-prone-constant-name"
            observations.append(
                _definition_observation(
                    "ruby.constant",
                    relative_path,
                    profile,
                    line_number,
                    constant_name,
                    target,
                    source_key=_owner_key_for_scope(owner, stack) or file_canonical_key,
                    metadata=metadata,
                )
            )

        req_match = REQUIRE_RE.match(stripped)
        if req_match:
            require_form = req_match.group(1)
            raw_value = req_match.group(3)
            observations.extend(
                _require_observations(
                    relative_path,
                    profile,
                    line_number,
                    require_form,
                    raw_value,
                    file_canonical_key,
                    repository_paths,
                )
            )

        include_match = INCLUDE_RE.match(stripped)
        if include_match:
            kind_name = include_match.group(1)
            target_module = include_match.group(2)
            observations.append(
                _observation(
                    kind=f"ruby.{kind_name}",
                    relative_path=relative_path,
                    source_id=f"{relative_path}#ruby-{kind_name}:{line_number}",
                    start_line=line_number,
                    name=target_module,
                    target=target_module,
                    metadata={
                        "format": "ruby",
                        "profile": profile,
                        "parser": PARSER,
                        "module_name": target_module,
                        "source_key": _current_source_key(stack) or file_canonical_key,
                    },
                )
            )

        route_match = ROUTE_RE.match(stripped)
        if route_match and _looks_like_route_profile(profile, content, relative_path):
            route_method = route_match.group(1)
            route_pattern = route_match.group(3)
            if _is_dynamic_literal(route_pattern):
                observations.append(
                    _parse_error(
                        relative_path,
                        "dynamic-route",
                        "dynamic Ruby route was not canonicalized",
                        profile,
                        line_number,
                        dynamic_reason="route",
                    )
                )
            else:
                pointer = f"/routes/{route_method}:{route_pattern}"
                target = ruby_route_key(relative_path, pointer)
                route_profile = "sinatra" if profile == "sinatra" else "hanami"
                observations.append(
                    _definition_observation(
                        "ruby.route",
                        relative_path,
                        route_profile,
                        line_number,
                        f"{route_method} {route_pattern}",
                        target,
                        source_key=file_canonical_key,
                        metadata={
                            "route_method": route_method,
                            "route_pattern": route_pattern,
                            "route_pointer": pointer,
                        },
                    )
                )
                stack.append(_Scope("route", pointer, canonical_key=target, route_key=target))
                continue

        erb_match = ERB_RE.match(stripped)
        if erb_match and profile == "sinatra":
            template_name = erb_match.group(2) or erb_match.group(4)
            if template_name:
                template_path = f"views/{template_name}.{erb_match.group(1)}"
                observations.append(
                    _reference_observation(
                        relative_path,
                        profile,
                        line_number,
                        "template",
                        template_name,
                        _path_target(template_path, repository_paths),
                        _current_route_key(stack) or file_canonical_key,
                        resolution_reason="repo-local",
                    )
                )

        if profile == "vagrantfile":
            observations.extend(
                _vagrant_observations(
                    relative_path,
                    profile,
                    line_number,
                    stripped,
                    file_canonical_key,
                    repository_paths,
                )
            )

        if profile == "rake":
            desc_match = RAKE_DESC_RE.match(stripped)
            if desc_match:
                last_rake_desc = desc_match.group(2)
            task_match = RAKE_TASK_RE.match(stripped)
            if task_match:
                task_name = task_match.group(1) or task_match.group(3) or "unknown"
                observations.append(
                    _observation(
                        kind="ruby.dsl",
                        relative_path=relative_path,
                        source_id=f"{relative_path}#ruby-task:{task_name}:{line_number}",
                        start_line=line_number,
                        name=task_name,
                        metadata={
                            "format": "ruby",
                            "profile": "rake",
                            "parser": PARSER,
                            "dsl_name": "task",
                            "task_name": task_name,
                            "description_summary": last_rake_desc,
                            "source_key": file_canonical_key,
                        },
                    )
                )
                last_rake_desc = None
            namespace_match = RAKE_NAMESPACE_RE.match(stripped)
            if namespace_match:
                namespace_name = namespace_match.group(1) or namespace_match.group(3) or "unknown"
                observations.append(
                    _observation(
                        kind="ruby.dsl",
                        relative_path=relative_path,
                        source_id=(
                            f"{relative_path}#ruby-namespace:"
                            f"{namespace_name}:{line_number}"
                        ),
                        start_line=line_number,
                        name=namespace_name,
                        metadata={
                            "format": "ruby",
                            "profile": "rake",
                            "parser": PARSER,
                            "dsl_name": "namespace",
                            "namespace_name": namespace_name,
                            "source_key": file_canonical_key,
                        },
                    )
                )

        if profile == "gemfile":
            observations.extend(
                _gemfile_observations(
                    relative_path,
                    profile,
                    line_number,
                    stripped,
                    file_canonical_key,
                )
            )

        if profile == "gemspec":
            observations.extend(
                _gemspec_observations(
                    relative_path,
                    profile,
                    line_number,
                    stripped,
                    file_canonical_key,
                )
            )

        if profile == "sinatra" and SINATRA_DSL_RE.match(stripped):
            dsl_name = SINATRA_DSL_RE.match(stripped).group(1)
            observations.append(
                _observation(
                    kind="ruby.dsl",
                    relative_path=relative_path,
                    source_id=f"{relative_path}#ruby-sinatra-dsl:{dsl_name}:{line_number}",
                    start_line=line_number,
                    name=dsl_name,
                    metadata={
                        "format": "ruby",
                        "profile": "sinatra",
                        "parser": PARSER,
                        "dsl_name": dsl_name,
                        "source_key": _current_source_key(stack) or file_canonical_key,
                    },
                )
            )

        if _opens_block(stripped):
            stack.append(_Scope("block", f"block:{line_number}"))

    return tuple(observations)


def _detect_profile(relative_path: str, content: str) -> str:
    path = PurePosixPath(relative_path)
    filename = path.name
    lower_path = relative_path.lower()
    if filename == "Vagrantfile":
        return "vagrantfile"
    if filename == "Gemfile":
        return "gemfile"
    if filename.endswith(".gemspec"):
        return "gemspec"
    if filename == "Rakefile" or filename.endswith(".rake"):
        return "rake"
    if lower_path == "config/routes.rb" or "hanami::app" in content.lower():
        return "hanami"
    if "sinatra" in content.lower():
        return "sinatra"
    if "minitest" in content.lower() or lower_path.startswith("test/"):
        return "minitest"
    return "generic_ruby"




def _require_observations(relative_path: str, profile: str, line_number: int, require_form: str, raw_value: str, source_key: str, repository_paths: frozenset[str] | None) -> tuple[RawObservation, ...]:
    target, reason = _require_target(relative_path, require_form, raw_value, repository_paths)
    metadata = {
        "format": "ruby",
        "profile": profile,
        "parser": PARSER,
        "require_form": require_form,
        "require_path": _safe_summary(raw_value),
        "source_key": source_key,
        "target_key": target,
        "not_loaded": True,
    }
    return (
        _observation(
            kind="ruby.require",
            relative_path=relative_path,
            source_id=f"{relative_path}#ruby-require:{line_number}",
            start_line=line_number,
            name=raw_value,
            target=target,
            metadata=metadata,
        ),
        _reference_observation(
            relative_path,
            profile,
            line_number,
            require_form,
            raw_value,
            target,
            source_key,
            resolution_reason=reason,
        ),
    )




def _parse_error(relative_path: str, error_kind: str, message: str, profile: str, line_number: int, *, dynamic_reason: str | None = None) -> RawObservation:
    metadata = {
        "format": "ruby",
        "profile": profile,
        "parser": PARSER,
        "error_kind": error_kind,
        "message_summary": message,
        "dynamic": dynamic_reason is not None,
        "dynamic_reason": dynamic_reason,
        "recovered": True,
    }
    return _observation(
        kind="ruby.parse_error",
        relative_path=relative_path,
        source_id=f"{relative_path}#ruby-parse-error:{line_number}:{error_kind}",
        confidence="unknown",
        start_line=line_number,
        name=error_kind,
        metadata=metadata,
    )


def _diagnostic_observation(relative_path: str, profile: str, line_number: int, diagnostic_kind: str, name: str, *, redacted: bool) -> RawObservation:
    metadata = {
        "format": "ruby",
        "profile": profile,
        "parser": PARSER,
        "diagnostic_kind": diagnostic_kind,
        "redacted": redacted,
        "redaction_reason": "secret-prone-env-name" if redacted else None,
        "dynamic": True,
        "dynamic_reason": "environment",
    }
    return _observation(
        kind="ruby.dsl",
        relative_path=relative_path,
        source_id=f"{relative_path}#ruby-env:{line_number}",
        start_line=line_number,
        name=name,
        metadata=metadata,
    )
