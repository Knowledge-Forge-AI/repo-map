"""Canonicalization dispatch metadata.

This module is intentionally data-only for CANON-DISPATCH0: the public
orchestration loop remains in ``canonicalization.main``.
"""

from __future__ import annotations

DISPATCH_ORDER = (
    "file",
    "awk",
    "zunit",
    "zsh",
    "bats",
    "bash",
    "legacy-shell",
    "powershell",
    "python",
    "ruby",
    "javascript",
    "email",
    "nix",
    "markdown",
    "config",
    "tfjson-profile-raw",
    "js5-framework-raw",
    "html",
    "xml",
    "css",
    "feed",
    "warc",
    "document",
    "unsupported",
)

TFJSON_PROFILE_RAW_OBSERVATION_KINDS = frozenset(
    {
        "ecosystem.config_profile",
        "ecosystem.package",
        "ecosystem.script",
        "ecosystem.dependency",
        "ecosystem.tool",
        "ecosystem.framework_hint",
        "ecosystem.reference",
        "ecosystem.redaction",
        "ecosystem.parse_error",
        "npm.package",
        "npm.script",
        "npm.dependency",
        "typescript.config",
        "typescript.reference",
        "angular.project",
        "angular.target",
        "jest.config",
        "nest.config",
        "playwright.config",
        "terraform.file",
        "terraform.block",
        "terraform.provider",
        "terraform.resource",
        "terraform.data_source",
        "terraform.module",
        "terraform.variable",
        "terraform.output",
        "terraform.local",
        "terraform.backend",
        "terraform.required_provider",
        "terraform.required_version",
        "terraform.reference",
        "terraform.moved",
        "terraform.import",
        "terraform.check",
        "terraform.removed",
        "terraform.parse_error",
        "terraform.redaction",
        "kubernetes.resource",
        "argocd.application",
        "liquibase.changelog",
        "liquibase.changeset",
        "docker.reference",
    }
)

JS5_FRAMEWORK_RAW_OBSERVATION_KINDS = frozenset(
    {
        "js.framework_profile",
        "js.runtime_profile",
        "js.package_context",
        "js.route_handler",
        "js.middleware",
        "js.controller",
        "js.provider",
        "js.module_binding",
        "js.test_config",
        "js.dom_selector",
        "js.dom_event",
        "js.ajax_reference",
        "js.server_entrypoint",
        "js.client_entrypoint",
        "js.framework_reference",
        "node.entrypoint",
        "node.export",
        "node.require",
        "express.app",
        "express.router",
        "express.route",
        "express.middleware",
        "express.error_handler",
        "nest.module",
        "nest.controller",
        "nest.provider",
        "nest.route",
        "nest.decorator",
        "next.route",
        "next.page",
        "next.api_route",
        "next.app_route",
        "next.component",
        "jest.suite",
        "jest.test",
        "jest.expectation",
        "jest.mock",
        "jquery.selector",
        "jquery.event",
        "jquery.ajax",
        "jquery.plugin_reference",
    }
)

POWERSHELL_FILE_KINDS = frozenset(
    ("powershell.script", "powershell.module", "powershell.manifest")
)

POWERSHELL_REFERENCE_KINDS = frozenset(
    (
        "powershell.import_module",
        "powershell.using_module",
        "powershell.dot_source",
        "powershell.manifest_dependency",
        "powershell.manifest_file_reference",
        "powershell.manifest_export",
        "powershell.network_call",
        "powershell.remoting",
    )
)

POWERSHELL_RAW_ONLY_KINDS = frozenset(
    (
        "powershell.param",
        "powershell.requires",
        "powershell.command_argument",
        "powershell.pipeline",
        "powershell.alias_command",
        "powershell.splat",
        "powershell.alias_definition",
        "powershell.splat_assignment",
        "powershell.dynamic_invocation",
        "powershell.secret_like",
        "powershell.manifest_field",
        "powershell.manifest_private_data",
        "powershell.file_read",
        "powershell.file_write",
        "powershell.registry_read",
        "powershell.registry_write",
    )
)

BASH_MAPPED_KINDS = frozenset(
    (
        "shell.script",
        "shell.function",
        "shell.command",
        "shell.external_command",
        "shell.source",
        "shell.env_read",
        "shell.env_write",
        "shell.file_read",
        "shell.file_write",
        "shell.host_mutation",
        "shell.network_call",
        "shell.package_manager",
    )
)

BASH_RAW_ONLY_KINDS = frozenset(
    (
        "bash.shell_option",
        "bash.shopt",
        "bash.alias",
        "bash.array_assignment",
        "bash.associative_array_assignment",
        "bash.trap",
        "bash.arithmetic",
        "bash.test_expression",
        "bash.case_pattern",
        "shell.assignment",
        "shell.export",
        "shell.command_argument",
        "shell.pipeline",
        "shell.command_chain",
        "shell.redirect",
        "shell.heredoc",
        "shell.process_substitution",
        "shell.command_substitution",
        "shell.dynamic_invocation",
        "shell.secret_like",
    )
)

BATS_RAW_ONLY_KINDS = frozenset(
    (
        "bats.setup",
        "bats.teardown",
        "bats.setup_file",
        "bats.teardown_file",
        "bats.skip",
        "bats.output_expectation",
        "bats.status_expectation",
        "shell.dynamic_invocation",
        "shell.secret_like",
    )
)

ZUNIT_RAW_ONLY_KINDS = frozenset(
    (
        "zunit.test_name",
        "zunit.dynamic_test",
        "zunit.parameterized_case",
        "zunit.skip",
        "zunit.todo",
        "zunit.secret_like",
    )
)

AWK_MAPPED_KINDS = frozenset(
    (
        "awk.program",
        "awk.function",
        "awk.builtin_call",
        "awk.user_function_call",
        "awk.file_read",
        "awk.file_write",
        "awk.pipe_read",
        "awk.pipe_write",
        "awk.system_call",
        "awk.include",
        "awk.extension",
    )
)

AWK_RAW_ONLY_KINDS = frozenset(
    (
        "awk.begin",
        "awk.end",
        "awk.pattern_action",
        "awk.variable_assignment",
        "awk.field_reference",
        "awk.record_reference",
        "awk.dynamic_expression",
        "awk.redirect",
        "awk.secret_like",
    )
)

ZSH_MAPPED_KINDS = frozenset(
    (
        "zsh.script",
        "zsh.startup_file",
        "shell.function",
        "shell.source",
        "shell.command",
        "shell.external_command",
        "zsh.autoload",
        "zsh.zmodload",
        "zsh.completion_function",
        "zsh.plugin_manager",
        "zsh.plugin",
        "shell.env_read",
        "shell.env_write",
        "shell.file_read",
        "shell.file_write",
        "shell.network_call",
        "shell.package_manager",
        "shell.host_mutation",
    )
)

ZSH_RAW_ONLY_KINDS = frozenset(
    (
        "zsh.option",
        "zsh.fpath",
        "zsh.zstyle",
        "zsh.bindkey",
        "zsh.compinit",
        "zsh.theme",
        "zsh.prompt",
        "zsh.array_assignment",
        "zsh.associative_array_assignment",
        "zsh.parameter_expansion",
        "zsh.glob_qualifier",
        "zsh.extended_glob",
        "zsh.path_reference",
        "zsh.dynamic_invocation",
        "shell.assignment",
        "shell.export",
        "shell.command_argument",
        "shell.pipeline",
        "shell.command_chain",
        "shell.redirect",
        "shell.heredoc",
        "shell.process_substitution",
        "shell.command_substitution",
        "shell.dynamic_invocation",
        "shell.secret_like",
    )
)
