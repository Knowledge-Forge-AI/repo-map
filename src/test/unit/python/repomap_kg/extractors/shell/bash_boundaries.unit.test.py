import unittest
from repomap_kg.extractors.shell.bash import extract_bash_file_observations
from repomap_kg.extractors.shell.bash_constructs import parse_alias_spec

class ShellBashBoundariesUnitTests(unittest.TestCase):
    def test_bash_constructs_and_side_effects(self):
        bash_script = """#!/bin/bash
set -euo pipefail
alias ll='ls -la'

deploy_app() {
    local env_name="$1"
    if [ "$env_name" = "production" ]; then
        curl -X POST https://api.example.com/deploy
        rm -rf /tmp/build_cache/*
        cat << 'EOF' > /tmp/deploy.log
deployment complete
EOF
    fi
}

deploy_app "staging" > /dev/null 2>&1
diff <(echo "a") <(echo "b")
"""
        obs = extract_bash_file_observations("scripts/deploy.sh", bash_script)
        self.assertEqual(obs[0].kind, "shell.script")
        kinds = {o.kind for o in obs}
        self.assertIn("shell.function", kinds)
        self.assertIn("shell.command", kinds)

    def test_bash_alias_helper(self):
        alias_name, target = parse_alias_spec("g=git")
        self.assertEqual(alias_name, "g")
        self.assertEqual(target, "git")

    def test_bash_side_effect_rules_boundaries(self):
        from repomap_kg.extractors.shell.bash_side_effect_rules import (
            container_operation_for,
            credential_operation,
            credential_target,
            first_operation,
            is_credential_command,
            last_positional,
            network_output_target,
            network_target,
            option_value,
            package_name_for_operation,
            security_policy_operation,
        )

        self.assertIsNone(last_positional([]))
        self.assertEqual(first_operation([], fallback="default"), "default")
        self.assertEqual(option_value(["-uadmin"], "-u"), "admin")
        self.assertEqual(network_output_target("wget", ["-O", "archive.tar"]), "archive.tar")
        self.assertEqual(network_target("scp", ["remote:file.txt"]), "remote:file.txt")
        self.assertIsNone(package_name_for_operation(["install"], "build"))
        self.assertEqual(package_name_for_operation(["install", "--flag", "pkg"], "install"), "pkg")
        self.assertTrue(is_credential_command("npm", ["login"]))
        self.assertTrue(is_credential_command("aws", ["configure"]))
        self.assertTrue(is_credential_command("git", ["credential"]))
        self.assertTrue(is_credential_command("gpg", ["--import"]))
        self.assertEqual(credential_operation("ssh-add", []), "ssh-add")
        self.assertIsNone(credential_target(["token"]))
        self.assertIsNone(security_policy_operation("unknown_cmd", [], "install"))
        self.assertIsNone(container_operation_for("docker", ["compose", "invalid"]))


if __name__ == "__main__":
    unittest.main()
