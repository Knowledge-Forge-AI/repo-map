import unittest

from repomap_kg.extractors.config.nix import extract_nix_file_observations


class NixExtractorFlakeOutputUnitTests(unittest.TestCase):
    def test_extracts_flake_output_attr_paths(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  apps.aarch64-darwin.tool = { type = \"app\"; };\n"
                "  packages.aarch64-darwin.default = self.packages.${system}.tool;\n"
                "  devShells.aarch64-darwin.default = {};\n"
                "  checks.aarch64-darwin.unit = {};\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        output_observations = [
            item
            for item in observations
            if item.kind in {"nix.app", "nix.package", "nix.devShell", "nix.check"}
        ]

        self.assertEqual([item.kind for item in output_observations], [
            "nix.app",
            "nix.package",
            "nix.devShell",
            "nix.check",
        ])
        self.assertEqual(
            [item.target for item in output_observations],
            [
                "nix.app:fixture:aarch64-darwin:tool",
                "nix.package:fixture:aarch64-darwin:default",
                "nix.devShell:fixture:aarch64-darwin:default",
                "nix.check:fixture:aarch64-darwin:unit",
            ],
        )
        self.assertEqual(output_observations[0].metadata["attr_path"], "apps.aarch64-darwin.tool")
        self.assertEqual(output_observations[1].metadata["output_kind"], "package")

    def test_extracts_app_program_static_repo_paths(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  apps.aarch64-darwin.selfPath = {\n"
                "    type = \"app\";\n"
                "    program = \"${self}/bin/self-tool\";\n"
                "  };\n"
                "  apps.aarch64-darwin.toStringPath = {\n"
                "    program = toString ./bin/to-string-tool;\n"
                "  };\n"
                "  apps.aarch64-darwin.literalPath = {\n"
                "    program = ./bin/literal-tool;\n"
                "  };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app_observations = [item for item in observations if item.kind == "nix.app"]

        self.assertEqual(
            [(item.name, item.metadata.get("program_path")) for item in app_observations],
            [
                ("selfPath", "bin/self-tool"),
                ("toStringPath", "bin/to-string-tool"),
                ("literalPath", "bin/literal-tool"),
            ],
        )
        self.assertEqual(
            [item.metadata.get("program_resolution") for item in app_observations],
            ["local", "local", "local"],
        )

    def test_dynamic_app_program_is_recorded_without_fabricated_path(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self, name }: {\n"
                "  apps.aarch64-darwin.dynamic = {\n"
                "    program = \"${self}/${name}\";\n"
                "  };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app = next(item for item in observations if item.kind == "nix.app")

        self.assertEqual(app.target, "nix.app:fixture:aarch64-darwin:dynamic")
        self.assertNotIn("program_path", app.metadata)
        self.assertEqual(app.metadata["program_resolution"], "dynamic")
        self.assertEqual(app.metadata["dynamic_reason"], "nix-app-program-interpolation")

    def test_external_app_program_is_recorded_without_repo_program_path(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ pkgs }: {\n"
                "  apps.aarch64-darwin.external = {\n"
                "    program = \"${pkgs.hello}/bin/hello\";\n"
                "  };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app = next(item for item in observations if item.kind == "nix.app")

        self.assertNotIn("program_path", app.metadata)
        self.assertEqual(app.metadata["program_resolution"], "dynamic")

    def test_expression_app_program_is_recorded_as_external(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ pkgs }: {\n"
                "  apps.aarch64-darwin.external = {\n"
                "    program = pkgs.hello + \"/bin/hello\";\n"
                "  };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app = next(item for item in observations if item.kind == "nix.app")

        self.assertNotIn("program_path", app.metadata)
        self.assertEqual(app.metadata["program_resolution"], "external")

    def test_repo_escaping_literal_app_program_records_unknown_target(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  apps.aarch64-darwin.bad = {\n"
                "    program = ../outside/tool;\n"
                "  };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app = next(item for item in observations if item.kind == "nix.app")

        self.assertNotIn("program_path", app.metadata)
        self.assertEqual(app.metadata["program_resolution"], "unknown")
        self.assertEqual(
            app.metadata["program_target"],
            "unknown:file:repo-escaping-nix-app-program",
        )

    def test_repo_escaping_self_app_program_records_unknown_target(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  apps.aarch64-darwin.bad = {\n"
                "    program = \"${self}/../outside/tool\";\n"
                "  };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app = next(item for item in observations if item.kind == "nix.app")

        self.assertNotIn("program_path", app.metadata)
        self.assertEqual(app.metadata["program_resolution"], "unknown")
        self.assertEqual(
            app.metadata["program_target"],
            "unknown:file:repo-escaping-nix-app-program",
        )

    def test_app_without_program_has_no_program_metadata(self):
        observations = extract_nix_file_observations(
            "flake.nix",
            (
                "{ self }: {\n"
                "  apps.aarch64-darwin.noProgram = { type = \"app\"; };\n"
                "}\n"
            ),
            flake_ref="fixture",
        )

        app = next(item for item in observations if item.kind == "nix.app")

        self.assertNotIn("program", app.metadata)
        self.assertNotIn("program_path", app.metadata)

    def test_non_flake_nix_file_does_not_emit_flake_outputs(self):
        observations = extract_nix_file_observations(
            "nix/module.nix",
            "apps.aarch64-darwin.tool = { program = ./bin/tool; };\n",
            flake_ref="fixture",
        )

        self.assertEqual([item.kind for item in observations], ["nix.path_ref"])
