import json
import unittest

from repomap_kg.extractors.shell.zsh import extract_zsh_file_observations


SCRIPT_PATH = "scripts/advanced.zsh"
STATIC_FLAGS = (
    "value_expanded", "glob_expanded", "filesystem_checked", "target_count_known",
    "command_executed", "host_mutation_proven", "network_called", "file_opened",
    "plugin_loaded", "plugin_installed", "shell_executed", "zsh_executed",
)


def extract(*lines):
    return extract_zsh_file_observations(SCRIPT_PATH, "\n".join(lines) + "\n")


def at(observations, kind, line_number):
    return [
        item for item in observations
        if item.kind == kind and item.start_line == line_number
    ]


def only(observations, kind, line_number):
    matches = at(observations, kind, line_number)
    assert len(matches) == 1, f"{kind} at line {line_number}: {len(matches)} matches"
    return matches[0]


def secret_sources(observations, line_number):
    return {
        item.metadata["secret_source"]: item
        for item in at(observations, "shell.secret_like", line_number)
    }


def dynamic_reasons(observations, line_number):
    return {
        item.metadata["dynamic_reason"]
        for item in at(observations, "zsh.dynamic_invocation", line_number)
    }


class ZshArrayRefusalContractTests(unittest.TestCase):
    def test_array_operation_is_derived_from_where_the_variable_reappears(self):
        observations = extract(
            "files=($files extra)",
            "dirs=(extra ${dirs})",
            "plain=(one two)",
        )

        appended = only(observations, "zsh.array_assignment", 1).metadata
        prepended = only(observations, "zsh.array_assignment", 2).metadata
        assigned = only(observations, "zsh.array_assignment", 3).metadata
        self.assertEqual(appended["operation"], "append")
        self.assertEqual(prepended["operation"], "prepend")
        self.assertEqual(assigned["operation"], "assign")
        for metadata in (appended, prepended):
            self.assertEqual(metadata["element_count"], 2)
            self.assertEqual(metadata["static_element_count"], 1)
            self.assertEqual(metadata["dynamic_element_count"], 1)
            self.assertEqual(metadata["redacted_element_count"], 0)
            self.assertFalse(metadata["array_expanded"] or metadata["runtime_state_known"])
            self.assertFalse(metadata["raw_value_stored"])
        self.assertEqual(assigned["static_element_count"], 2)

    def test_secret_like_array_name_is_flagged_without_inspecting_elements(self):
        observations = extract("api_token_list=(one two)")

        array = only(observations, "zsh.array_assignment", 1)
        self.assertEqual(array.name, "api_token_list")
        self.assertEqual(array.metadata["redacted_element_count"], 0)
        secret = secret_sources(observations, 1)["array_element"]
        self.assertEqual(secret.name, "api_token_list")
        self.assertEqual(secret.metadata["redaction_reason"], "secret-like-name")
        self.assertFalse(secret.metadata["raw_value_stored"])

    def test_non_associative_declarations_are_refused_as_arrays_and_maps(self):
        observations = extract("typeset -i counter", "local scratch", "typeset -a listed")

        for line_number in (1, 2, 3):
            self.assertEqual(at(observations, "zsh.array_assignment", line_number), [])
            self.assertEqual(
                at(observations, "zsh.associative_array_assignment", line_number), []
            )
        self.assertEqual(
            {item.name for item in observations if item.kind == "shell.assignment"}, set()
        )

    def test_associative_pairs_split_static_and_dynamic_keys_and_values(self):
        observations = extract(
            "typeset -A route_map=([$DIR]=/api [static]=$HOME_VALUE)",
            "typeset -A odd_pairs=(a 1 b)",
        )

        route = only(observations, "zsh.associative_array_assignment", 1)
        self.assertEqual(route.name, "route_map")
        counts = {
            key: route.metadata[key]
            for key in (
                "pair_count", "static_key_count", "dynamic_key_count", "redacted_key_count",
                "static_value_count", "dynamic_value_count", "redacted_value_count",
            )
        }
        self.assertEqual(
            counts,
            {
                "pair_count": 2, "static_key_count": 1, "dynamic_key_count": 1,
                "redacted_key_count": 0, "static_value_count": 1,
                "dynamic_value_count": 1, "redacted_value_count": 0,
            },
        )
        self.assertNotIn("associative_array", secret_sources(observations, 1))
        self.assertFalse(route.metadata["raw_value_stored"] or route.metadata["array_expanded"])

        odd = only(observations, "zsh.associative_array_assignment", 2)
        self.assertEqual(odd.metadata["pair_count"], 1)
        self.assertEqual(odd.metadata["static_key_count"], 1)
        self.assertEqual(odd.metadata["static_value_count"], 1)

    def test_secret_like_associative_declaration_is_flagged_by_name_alone(self):
        observations = extract("typeset -A auth_headers")

        declared = only(observations, "zsh.associative_array_assignment", 1)
        self.assertEqual(declared.name, "auth_headers")
        self.assertEqual(declared.metadata["pair_count"], 0)
        self.assertEqual(declared.metadata["declaration_keyword"], "typeset")
        secret = secret_sources(observations, 1)["associative_array"]
        self.assertEqual(secret.name, "auth_headers")
        self.assertEqual(secret.metadata["redaction_reason"], "secret-like-value")
        self.assertFalse(secret.metadata["raw_value_stored"])


class ZshParameterExpansionRefusalContractTests(unittest.TestCase):
    def test_secret_like_parameter_name_is_hidden_and_reported_separately(self):
        observations = extract("copy=${(U)api_token}")

        expansion = only(observations, "zsh.parameter_expansion", 1)
        self.assertEqual(expansion.name, "U")
        self.assertIsNone(expansion.metadata["parameter_name"])
        self.assertTrue(expansion.metadata["redacted"])
        self.assertEqual(expansion.metadata["redaction_reason"], "secret-like-name")
        self.assertEqual(expansion.metadata["context"], "assignment")
        self.assertNotIn("dynamic_reason", expansion.metadata)
        secret = secret_sources(observations, 1)["parameter_expansion"]
        self.assertEqual(secret.name, "api_token")
        self.assertEqual(secret.metadata["redaction_reason"], "secret-like-name")
        self.assertFalse(secret.metadata["raw_value_stored"])
        self.assertEqual(dynamic_reasons(observations, 1), {"parameter_expansion"})

    def test_unrecognised_flags_and_computed_names_stay_unresolved(self):
        observations = extract(
            "echo ${(k)mapping}",
            "echo ${(U)${inner}}",
            "echo ${(U)$(whoami)}",
        )

        unknown_flag = only(observations, "zsh.parameter_expansion", 1)
        self.assertEqual(unknown_flag.name, "unknown")
        self.assertEqual(unknown_flag.metadata["flag_summary"], "unknown")
        self.assertEqual(unknown_flag.metadata["parameter_name"], "mapping")
        self.assertEqual(unknown_flag.metadata["context"], "command_argument")
        self.assertNotIn("dynamic_reason", unknown_flag.metadata)
        self.assertNotIn("redacted", unknown_flag.metadata)

        computed = only(observations, "zsh.parameter_expansion", 2)
        self.assertEqual(computed.name, "U")
        self.assertIsNone(computed.metadata["parameter_name"])
        self.assertEqual(computed.metadata["dynamic_reason"], "computed_parameter")

        substituted = only(observations, "zsh.parameter_expansion", 3)
        self.assertIsNone(substituted.metadata["parameter_name"])
        self.assertEqual(substituted.metadata["dynamic_reason"], "command_substitution")
        for item in (unknown_flag, computed, substituted):
            self.assertEqual(item.confidence, "heuristic")
            self.assertFalse(
                item.metadata["value_expanded"]
                or item.metadata["command_executed"]
                or item.metadata["raw_value_stored"]
            )

    def test_expansion_context_follows_prompt_zstyle_and_unparsable_lines(self):
        observations = extract(
            "PROMPT=${(U)user_name}",
            "zstyle ':completion:*' format ${(U)fmt}",
            "${(U)stray} 'unterminated",
        )

        contexts = {
            line_number: only(observations, "zsh.parameter_expansion", line_number)
            for line_number in (1, 2, 3)
        }
        self.assertEqual(contexts[1].metadata["context"], "prompt")
        self.assertEqual(contexts[1].metadata["parameter_name"], "user_name")
        self.assertEqual(contexts[2].metadata["context"], "zstyle")
        self.assertEqual(contexts[2].metadata["parameter_name"], "fmt")
        self.assertEqual(contexts[3].metadata["context"], "unknown")
        self.assertEqual(contexts[3].metadata["parameter_name"], "stray")
        self.assertEqual(dynamic_reasons(observations, 1), {"parameter_expansion", "dynamic_prompt"})
        self.assertEqual(dynamic_reasons(observations, 2), {"parameter_expansion"})

    def test_quoted_expansions_are_not_modelled(self):
        observations = extract(
            'echo "${(U)double_quoted}"',
            "echo '${(U)single_quoted}'",
        )

        self.assertEqual([item for item in observations if item.kind == "zsh.parameter_expansion"], [])
        self.assertEqual([item for item in observations if item.kind == "zsh.dynamic_invocation"], [])


class ZshGlobAndDynamicMarkerRefusalContractTests(unittest.TestCase):
    def test_recursive_glob_without_qualifier_is_unexpanded_syntax(self):
        observations = extract("ls **/*.py")

        feature = only(observations, "zsh.extended_glob", 1)
        self.assertEqual(feature.name, "recursive_glob")
        self.assertEqual(feature.metadata["feature"], "recursive_glob")
        self.assertEqual(feature.metadata["pattern_summary"], "**/*.py")
        self.assertEqual(at(observations, "zsh.glob_qualifier", 1), [])
        path = only(observations, "zsh.path_reference", 1)
        self.assertEqual(path.metadata["path_kind"], "glob")
        self.assertEqual(path.metadata["target_kind"], "dynamic")
        self.assertEqual(path.name, "[dynamic]")
        self.assertEqual(path.confidence, "unknown")
        self.assertFalse(path.metadata["raw_value_stored"])
        for item in (feature, path):
            self.assertFalse(any(item.metadata[flag] for flag in STATIC_FLAGS if flag in item.metadata))

    def test_directory_and_symlink_qualifiers_are_recognised_but_unknown_ones_are_not(self):
        observations = extract("ls *(/)", "ls *(@)", "ls *(x)", "ls *.txt")

        directory = only(observations, "zsh.glob_qualifier", 1)
        symlink = only(observations, "zsh.glob_qualifier", 2)
        self.assertEqual(directory.metadata["qualifier_summary"], "/")
        self.assertEqual(symlink.metadata["qualifier_summary"], "@")
        for item in (directory, symlink):
            self.assertEqual(item.metadata["glob_pattern_kind"], "qualified")
            self.assertEqual(item.metadata["pattern_kind"], "static")
            self.assertEqual(only(observations, "zsh.extended_glob", item.start_line).name, "qualifier")
            self.assertEqual(
                only(observations, "zsh.path_reference", item.start_line).metadata["path_kind"],
                "qualified_glob",
            )
        for line_number in (3, 4):
            for kind in ("zsh.glob_qualifier", "zsh.extended_glob", "zsh.path_reference"):
                self.assertEqual(at(observations, kind, line_number), [])

    def test_dynamic_glob_directory_is_a_marker_not_a_path_reference(self):
        observations = extract("ls $base_dir/*.zsh")

        self.assertEqual(dynamic_reasons(observations, 1), {"dynamic_glob"})
        marker = only(observations, "zsh.dynamic_invocation", 1)
        self.assertEqual(marker.confidence, "unknown")
        self.assertEqual(marker.metadata["target_kind"], "dynamic")
        self.assertFalse(
            marker.metadata["command_executed"]
            or marker.metadata["plugin_loaded"]
            or marker.metadata["network_called"]
        )
        for kind in ("zsh.extended_glob", "zsh.glob_qualifier", "zsh.path_reference"):
            self.assertEqual(at(observations, kind, 1), [])

    def test_prompt_marker_requires_a_prompt_variable_with_a_dynamic_value(self):
        observations = extract(
            "PS1='%n@%m $(git_branch) %~'",
            "PS2='> '",
            'MOTD="$USER"',
        )

        self.assertEqual(dynamic_reasons(observations, 1), {"dynamic_prompt"})
        self.assertEqual(dynamic_reasons(observations, 2), set())
        self.assertEqual(dynamic_reasons(observations, 3), set())

    def test_plugin_loader_marker_requires_a_loading_subcommand(self):
        observations = extract("zinit ice wait", "zplug load", "zinit update", "zplug check")

        self.assertEqual(dynamic_reasons(observations, 1), {"plugin_loader"})
        self.assertEqual(dynamic_reasons(observations, 2), {"plugin_loader"})
        self.assertEqual(dynamic_reasons(observations, 3), set())
        self.assertEqual(dynamic_reasons(observations, 4), set())
        for item in at(observations, "zsh.dynamic_invocation", 1) + at(observations, "zsh.dynamic_invocation", 2):
            self.assertFalse(item.metadata["plugin_loaded"] or item.metadata["plugin_installed"])

    def test_static_extraction_payload_never_contains_secret_values_or_raw_source(self):
        observations = extract(
            "copy=${(U)api_token}",
            "typeset -A auth_headers",
            "api_token_list=(FAKE_ZSH_ARRAY_TOKEN two)",
        )

        payload = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        self.assertNotIn("FAKE_ZSH_ARRAY_TOKEN", payload)
        array = only(observations, "zsh.array_assignment", 3)
        self.assertEqual(array.metadata["redacted_element_count"], 1)
        self.assertEqual(array.metadata["static_element_count"], 1)
        self.assertEqual(
            secret_sources(observations, 3)["array_element"].metadata["redaction_reason"],
            "secret-like-value",
        )


if __name__ == "__main__":
    unittest.main()
