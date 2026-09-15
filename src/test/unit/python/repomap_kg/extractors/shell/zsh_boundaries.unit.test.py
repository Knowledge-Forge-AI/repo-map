import unittest
from repomap_kg.extractors.shell.zsh import extract_zsh_file_observations

class ShellZshBoundariesUnitTests(unittest.TestCase):
    def test_zsh_advanced_patterns_and_completions(self):
        zsh_script = """#!/usr/bin/env zsh
autoload -Uz compinit && compinit
setopt EXTENDED_GLOB
setopt PROMPT_SUBST

typeset -A config_map
config_map=(env production port 8080)

function setup_env() {
    export APP_ENV="${(U)config_map[env]}"
    print -P "%F{green}Loaded config%f"
    for file in **/*(.); do
        print "Found regular file: $file"
    done
}

setup_env
"""
        obs = extract_zsh_file_observations("config/env.zsh", zsh_script)
        self.assertEqual(obs[0].kind, "zsh.script")
        kinds = {o.kind for o in obs}
        self.assertIn("shell.function", kinds)

if __name__ == "__main__":
    unittest.main()
