import unittest

from repomap_kg.extractors.config.nix import extract_nix_file_observations, resolve_repo_path


class NixExtractorImportsAndPathsUnitTests(unittest.TestCase):
    def test_input_reference_observations_are_multi_source_opt_in(self):
        content = "{ inputs, ... }: inputs.composition.nixosModules.default\n"

        legacy = extract_nix_file_observations(
            "flake.nix", content, flake_ref="fixture"
        )
        multi_source = extract_nix_file_observations(
            "flake.nix",
            content,
            flake_ref="entry",
            include_input_references=True,
        )

        self.assertFalse(any(item.kind == "nix.input_ref" for item in legacy))
        reference = next(
            item for item in multi_source if item.kind == "nix.input_ref"
        )
        self.assertEqual(reference.metadata["input_name"], "composition")
        self.assertEqual(reference.metadata["module_name"], "default")

    def test_extracts_explicit_nixos_module_export_mappings(self):
        content = (
            "{ ... }:\n"
            "{\n"
            "  # nixosModules.commented = ./modules/commented.nix;\n"
            "  /* nixosModules.block = ./modules/block.nix; */\n"
            "  nixosModules.default = import ./modules/default.nix;\n"
            "  nixosModules.literal = ./modules/literal.nix;\n"
            "  nixosModules = {\n"
            "    nested = import ./modules/nested.nix;\n"
            "    path = ./modules/path.nix; # inline comment\n"
            "  };\n"
            "}\n"
        )
        legacy_observations = extract_nix_file_observations(
            "flake.nix",
            content,
            flake_ref="target",
            include_input_references=False,
        )
        self.assertFalse(any(item.kind == "nix.module_export" for item in legacy_observations))

        observations = extract_nix_file_observations(
            "flake.nix",
            content,
            flake_ref="target",
            include_input_references=True,
        )

        exports = [
            item for item in observations if item.kind == "nix.module_export"
        ]

        self.assertEqual(
            [
                (
                    item.metadata["module_name"],
                    item.metadata["export_path"],
                    item.metadata["resolved_path"],
                    item.metadata["literal_syntax"],
                )
                for item in exports
            ],
            [
                (
                    "default",
                    "nixosModules.default",
                    "modules/default.nix",
                    "import",
                ),
                (
                    "literal",
                    "nixosModules.literal",
                    "modules/literal.nix",
                    "path",
                ),
                (
                    "nested",
                    "nixosModules.nested",
                    "modules/nested.nix",
                    "import",
                ),
                (
                    "path",
                    "nixosModules.path",
                    "modules/path.nix",
                    "path",
                ),
            ],
        )
        self.assertTrue(all(item.metadata["flake_ref"] == "target" for item in exports))

    def test_module_export_mapping_rejects_unproved_output_shapes(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ inputs, ... }:\n"
                "{\n"
                "  nixosModules = inputs.modules.nixosModules;\n"
                "  nixosModules.generated = makeModule ./modules/generated.nix;\n"
                "}\n"
            ),
            flake_ref="target",
            include_input_references=True,
        )

        exports = [
            item for item in observations if item.kind == "nix.module_export"
        ]

        self.assertEqual(exports, [])

    def test_extracts_static_imports_from_import_calls_and_imports_list(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ ... }:\n"
                "let\n"
                "  base = import ./nix/base.nix;\n"
                "in {\n"
                "  imports = [ ./modules/one.nix ./modules/two.nix ];\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        imports = [item for item in observations if item.kind == "nix.import"]

        self.assertEqual([item.target for item in imports], [
            "file:nix/base.nix",
            "file:modules/one.nix",
            "file:modules/two.nix",
        ])
        self.assertEqual([item.start_line for item in imports], [3, 5, 5])
        self.assertTrue(all(item.confidence == "heuristic" for item in imports))
        self.assertEqual(imports[0].metadata["syntax"], "import")
        self.assertEqual(imports[1].metadata["syntax"], "imports-list")

    def test_extracts_static_imports_from_multiline_imports_list(self):
        observations = extract_nix_file_observations(
            "nix/modules/default.nix",
            (
                "{ ... }: {\n"
                "  imports = [\n"
                "    ./one.nix\n"
                "    ../shared/two.nix\n"
                "  ];\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        imports = [item for item in observations if item.kind == "nix.import"]

        self.assertEqual([item.target for item in imports], [
            "file:nix/modules/one.nix",
            "file:nix/shared/two.nix",
        ])
        self.assertEqual([item.start_line for item in imports], [3, 4])

    def test_imports_list_ignores_non_nix_paths(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            "{ ... }: { imports = [ ./module.nix ./README.md ]; }\n",
            flake_ref="fixture",
        )

        imports = [item for item in observations if item.kind == "nix.import"]

        self.assertEqual([item.target for item in imports], ["file:module.nix"])

    def test_repo_escaping_import_uses_unknown_placeholder(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            "{ ... }: import ../outside.nix\n",
            flake_ref="fixture",
        )

        imports = [item for item in observations if item.kind == "nix.import"]

        self.assertEqual(imports[0].target, "unknown:file:repo-escaping-nix-import")
        self.assertEqual(imports[0].metadata["resolution"], "unknown")
        self.assertEqual(
            imports[0].metadata["dynamic_reason"],
            "repo-escaping-nix-import",
        )

    def test_extracts_raw_only_path_references(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  packages.aarch64-darwin.default = ./pkgs/default.nix;\n"
                "  scripts = [ ./bin/tool ./config/settings.json ];\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        path_refs = [item for item in observations if item.kind == "nix.path_ref"]

        self.assertEqual([item.target for item in path_refs], [
            "file:pkgs/default.nix",
            "file:bin/tool",
            "file:config/settings.json",
        ])
        self.assertEqual([item.metadata["resolution"] for item in path_refs], [
            "local",
            "local",
            "local",
        ])

    def test_repo_escaping_path_reference_uses_unknown_placeholder(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            "{ self }: { scripts = [ ../outside/tool ]; }\n",
            flake_ref="fixture",
        )

        path_ref = next(item for item in observations if item.kind == "nix.path_ref")

        self.assertEqual(path_ref.target, "unknown:file:repo-escaping-nix-path-ref")
        self.assertEqual(path_ref.metadata["resolution"], "unknown")

    def test_resolve_repo_path_normalizes_relative_and_self_paths(self):
        self.assertEqual(
            resolve_repo_path("nix/module.nix", "./child.nix"),
            "nix/child.nix",
        )
        self.assertEqual(
            resolve_repo_path("nix/module.nix", "../lib/shared.nix"),
            "lib/shared.nix",
        )
        self.assertEqual(resolve_repo_path("flake.nix", "${self}/bin/tool"), "bin/tool")
        self.assertIsNone(resolve_repo_path("flake.nix", "../outside.nix"))
        self.assertIsNone(resolve_repo_path("flake.nix", "pkgs.hello"))
