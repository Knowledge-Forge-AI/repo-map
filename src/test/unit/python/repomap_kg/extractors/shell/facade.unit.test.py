import unittest

from repomap_kg.extractors.shell.base import (
    extract_shell_command_observations,
    extract_shell_observations,
)


class ShellExtractorUnitTests(unittest.TestCase):
    def test_extract_shell_command_observations_preserves_tool_call_evidence(self):
        observations = extract_shell_command_observations(
            "bin/tool",
            "#!/usr/bin/env bash\n\nnix build .#checks\n",
        )

        self.assertEqual(len(observations), 1)
        observation = observations[0]
        self.assertEqual(observation.kind, "shell.command")
        self.assertEqual(observation.source_id, "bin/tool#call:3:nix-build")
        self.assertEqual(observation.path, "bin/tool")
        self.assertEqual(observation.start_line, 3)
        self.assertEqual(observation.end_line, 3)
        self.assertEqual(observation.name, "nix build")
        self.assertEqual(observation.target, "tool:nix")
        self.assertEqual(observation.confidence, "heuristic")
        self.assertEqual(observation.extractor, "repo-shell")
        self.assertEqual(observation.metadata["argv"], ["nix", "build", ".#checks"])

    def test_extract_shell_command_observations_skips_non_command_lines(self):
        observations = extract_shell_command_observations(
            "scripts/check.sh",
            (
                "#!/usr/bin/env bash\n"
                "# comment\n"
                "if true; then\n"
                "  echo ok\n"
                "fi\n"
                "FOO=bar\n"
            ),
        )

        self.assertEqual([observation.name for observation in observations], ["echo ok"])
        self.assertEqual(observations[0].source_id, "scripts/check.sh#call:4:echo-ok")

    def test_extract_shell_observations_emits_sourced_file_edges(self):
        observations = extract_shell_observations(
            "bin/tool",
            (
                "#!/usr/bin/env bash\n"
                "source ../lib/common.sh\n"
                ". ./helpers.sh\n"
                "source \"$DYNAMIC\"\n"
                "nix build .#checks\n"
            ),
        )

        sources = [
            observation
            for observation in observations
            if observation.kind == "shell.source"
        ]
        commands = [
            observation
            for observation in observations
            if observation.kind == "shell.command"
        ]
        self.assertEqual([source.target for source in sources], [
            "file:lib/common.sh",
            "file:bin/helpers.sh",
        ])
        self.assertEqual(sources[0].source_id, "bin/tool#source:2:lib-common-sh")
        self.assertEqual(sources[0].name, "../lib/common.sh")
        self.assertEqual(sources[0].start_line, 2)
        self.assertEqual(sources[0].confidence, "heuristic")
        self.assertEqual(sources[0].metadata["resolved_path"], "lib/common.sh")
        self.assertEqual([command.name for command in commands], ["nix build"])

    def test_extract_shell_observations_emits_environment_reads_and_writes(self):
        observations = extract_shell_observations(
            "bin/tool",
            (
                "#!/usr/bin/env bash\n"
                'PATH="$PWD/bin:$PATH"\n'
                "FOO=bar nix build .#checks\n"
                'echo "$PATH"\n'
            ),
        )

        env = [
            observation
            for observation in observations
            if observation.kind == "shell.env"
        ]
        commands = [
            observation
            for observation in observations
            if observation.kind == "shell.command"
        ]
        self.assertEqual(
            [
                (
                    observation.metadata["operation"],
                    observation.name,
                    observation.start_line,
                    observation.target,
                )
                for observation in env
            ],
            [
                ("write", "PATH", 2, "env:PATH"),
                ("read", "PWD", 2, "env:PWD"),
                ("read", "PATH", 2, "env:PATH"),
                ("write", "FOO", 3, "env:FOO"),
                ("read", "PATH", 4, "env:PATH"),
            ],
        )
        self.assertEqual(env[0].source_id, "bin/tool#env-write:2:path")
        self.assertEqual(env[0].metadata["value"], "$PWD/bin:$PATH")
        self.assertEqual(env[0].metadata["scope"], "shell")
        self.assertEqual(env[3].metadata["scope"], "command")
        self.assertEqual(
            [command.name for command in commands],
            ["nix build", "echo $PATH"],
        )

    def test_extract_shell_observations_marks_assignment_only_lines_as_shell_scope(self):
        observations = extract_shell_observations(
            "scripts/env.sh",
            "FOO=bar BAR=baz\n",
        )

        env = [
            observation
            for observation in observations
            if observation.kind == "shell.env"
        ]
        commands = [
            observation
            for observation in observations
            if observation.kind == "shell.command"
        ]
        self.assertEqual(
            [(observation.name, observation.metadata["scope"]) for observation in env],
            [("FOO", "shell"), ("BAR", "shell")],
        )
        self.assertEqual(commands, [])

    def test_extract_shell_observations_deduplicates_environment_reads_per_line(self):
        observations = extract_shell_observations(
            "bin/tool",
            'echo "$PATH:${PATH:-/bin}:$PATH"\n',
        )

        env = [
            observation
            for observation in observations
            if observation.kind == "shell.env"
        ]
        self.assertEqual(
            [
                (observation.metadata["operation"], observation.name)
                for observation in env
            ],
            [("read", "PATH")],
        )

    def test_extract_shell_observations_skips_unresolved_sources(self):
        observations = extract_shell_observations(
            "bin/tool",
            (
                "source /etc/profile\n"
                "source ../../outside.sh\n"
                'source "$DYNAMIC"\n'
                "source\n"
                "nix --version\n"
            ),
        )

        sources = [
            observation
            for observation in observations
            if observation.kind == "shell.source"
        ]
        commands = [
            observation
            for observation in observations
            if observation.kind == "shell.command"
        ]
        self.assertEqual(sources, [])
        self.assertEqual([command.name for command in commands], ["nix"])

    def test_extract_shell_observations_skips_invalid_shell_syntax(self):
        observations = extract_shell_observations(
            "bin/tool",
            'echo "unterminated\n',
        )

        self.assertEqual(observations, ())

    def test_extract_shell_observations_classifies_host_mutating_commands(self):
        observations = extract_shell_observations(
            "scripts/maintain.sh",
            (
                "#!/usr/bin/env bash\n"
                "brew install postgresql\n"
                "nix profile install nixpkgs#ripgrep\n"
                "sudo launchctl bootout system/com.example.agent\n"
                "darwin-rebuild switch --flake ~/.flakes/nix-darwin\n"
                "nix build .#checks\n"
            ),
        )

        mutations = [
            observation
            for observation in observations
            if observation.kind == "shell.host_mutation"
        ]
        self.assertEqual(
            [
                (
                    observation.name,
                    observation.target,
                    observation.metadata["category"],
                    observation.metadata["tool"],
                    observation.metadata["privileged"],
                )
                for observation in mutations
            ],
            [
                (
                    "brew install",
                    "host:package-management",
                    "package-management",
                    "brew",
                    False,
                ),
                (
                    "nix profile install",
                    "host:package-management",
                    "package-management",
                    "nix",
                    False,
                ),
                (
                    "launchctl bootout",
                    "host:service-management",
                    "service-management",
                    "launchctl",
                    True,
                ),
                (
                    "darwin-rebuild switch",
                    "host:system-activation",
                    "system-activation",
                    "darwin-rebuild",
                    False,
                ),
            ],
        )
        self.assertEqual(
            mutations[0].source_id,
            "scripts/maintain.sh#host-mutation:2:package-management-brew-install",
        )
        self.assertEqual(
            mutations[2].metadata["effective_argv"],
            ["launchctl", "bootout", "system/com.example.agent"],
        )
        self.assertEqual(mutations[2].metadata["argv"][0], "sudo")

    def test_extract_shell_observations_classifies_host_filesystem_mutations(self):
        observations = extract_shell_observations(
            "scripts/maintain.sh",
            (
                "#!/usr/bin/env bash\n"
                "sudo rm -rf /Library/Caches/example\n"
                "mv build/tool /usr/local/bin/tool\n"
                "cp scripts/tool ~/.local/bin/tool\n"
                "rm build/output\n"
                "cp /etc/hosts ./hosts.copy\n"
            ),
        )

        mutations = [
            observation
            for observation in observations
            if observation.kind == "shell.host_mutation"
        ]
        self.assertEqual(
            [
                (
                    observation.name,
                    observation.target,
                    observation.metadata["category"],
                    observation.metadata["tool"],
                    observation.metadata["privileged"],
                    observation.metadata["reason"],
                )
                for observation in mutations
            ],
            [
                (
                    "rm",
                    "host:filesystem-mutation",
                    "filesystem-mutation",
                    "rm",
                    True,
                    "rm host filesystem path",
                ),
                (
                    "mv",
                    "host:filesystem-mutation",
                    "filesystem-mutation",
                    "mv",
                    False,
                    "mv host filesystem path",
                ),
                (
                    "cp",
                    "host:filesystem-mutation",
                    "filesystem-mutation",
                    "cp",
                    False,
                    "cp host filesystem path",
                ),
            ],
        )
        self.assertEqual(
            mutations[0].source_id,
            "scripts/maintain.sh#host-mutation:2:filesystem-mutation-rm",
        )
        self.assertEqual(
            mutations[0].metadata["effective_argv"],
            ["rm", "-rf", "/Library/Caches/example"],
        )
        self.assertEqual(mutations[0].metadata["argv"][0], "sudo")

    def test_extract_shell_observations_skips_non_mutating_commands(self):
        observations = extract_shell_observations(
            "scripts/check.sh",
            (
                "#!/usr/bin/env bash\n"
                "nix build .#checks\n"
                "git status --short\n"
                "echo ok\n"
            ),
        )

        self.assertEqual(
            [
                observation
                for observation in observations
                if observation.kind == "shell.host_mutation"
            ],
            [],
        )


if __name__ == "__main__":
    unittest.main()
