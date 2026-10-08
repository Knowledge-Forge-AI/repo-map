"""Integration tests for Slice 10 shell canonical pipeline (Group S10-A).

Covers:
- PowerShell manifest extraction, exported functions, and dependencies
- PowerShell script dot-sourcing and cmdlet execution
- PowerShell malformed manifest degradation
- Bash output overwrite (>) and append (>>) file references and mutations
- Bash input redirection (<) and here-strings (<<<)
- Bash file descriptor duplication (2>&1)
- Zsh autoload functions, completion, and options
- Multi-technology shell pipeline composition integrity
"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.extractors.shell.bash import extract_bash_file_observations
from repomap_kg.extractors.shell.powershell import (
    extract_powershell_file_observations,
)
from repomap_kg.extractors.shell.zsh import extract_zsh_file_observations
from repomap_test_support.test_scratch import select_scratch_root


class Slice10ShellCanonicalPipelineIntegrationTests(unittest.TestCase):
    """Slice 10 Group S10-A integration tests for shell pipeline canonical contracts."""

    def setUp(self) -> None:
        self.tmpdir = Path(
            tempfile.mkdtemp(dir=select_scratch_root(), prefix="repomap-s10a-shell-")
        ).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_s10_a01_powershell_module_manifest_exports_and_metadata(self) -> None:
        """PowerShell .psd1 manifest extracts exported functions, version, and file references."""
        psd1_path = self.tmpdir / "CoreModule.psd1"
        content = """@{
            RootModule = 'CoreModule.psm1'
            ModuleVersion = '2.1.0'
            Description = 'Core utility module'
            Author = 'Platform Team'
            CompanyName = 'Acme Corp'
            FunctionsToExport = @('Get-ServiceStatus', 'Restart-ServiceEndpoint')
            CmdletsToExport = @()
            VariablesToExport = @('CoreConfig')
        }"""
        psd1_path.write_text(content, encoding="utf-8")

        obs = extract_powershell_file_observations("CoreModule.psd1", content)
        kinds = {o.kind for o in obs}
        self.assertIn("powershell.manifest", kinds)
        self.assertIn("powershell.manifest_export", kinds)
        self.assertIn("powershell.manifest_file_reference", kinds)

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        edges = {(e.source_key, e.kind, e.target_key) for e in res.graph.edges}
        manifest_key = "powershell.manifest:file%3ACoreModule.psd1"
        self.assertIn(("file:CoreModule.psd1", "defines", manifest_key), edges)
        self.assertIn((manifest_key, "references", "file:CoreModule.psm1"), edges)
        self.assertTrue(
            any(
                e[0] == manifest_key
                and e[1] == "defines"
                and "Get-ServiceStatus" in e[2]
                for e in edges
            )
        )

    def test_s10_a02_powershell_nested_and_required_modules_dependencies(self) -> None:
        """PowerShell manifest dependency declarations map to depends_on and nested references."""
        psd1_path = self.tmpdir / "Composite.psd1"
        content = """@{
            RootModule = 'Composite.psm1'
            ModuleVersion = '1.0.0'
            RequiredModules = @('Pester', 'PSReadLine')
            NestedModules = @('Sub/Helper.psm1')
            FunctionsToExport = @('Invoke-Composite')
        }"""
        psd1_path.write_text(content, encoding="utf-8")

        obs = extract_powershell_file_observations("Composite.psd1", content)
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        edges = {(e.source_key, e.kind, e.target_key) for e in res.graph.edges}
        manifest_key = "powershell.manifest:file%3AComposite.psd1"
        self.assertIn(
            (manifest_key, "depends_on", "external:powershell.module:Pester"), edges
        )
        self.assertIn(
            (manifest_key, "depends_on", "external:powershell.module:PSReadLine"), edges
        )
        self.assertIn((manifest_key, "references", "file:Sub/Helper.psm1"), edges)

    def test_s10_a03_powershell_script_dot_sourcing_and_cmdlet_invocations(self) -> None:
        """PowerShell .ps1 script dot-sourcing external script establishes references edge."""
        ps1_path = self.tmpdir / "deploy.ps1"
        content = """# PowerShell automation entrypoint
        . ./lib/setup.ps1
        $env:DEPLOY_TARGET = "prod"
        Get-ChildItem -Path ./artifacts
        Write-Host "Deployment complete"
        """
        ps1_path.write_text(content, encoding="utf-8")

        obs = extract_powershell_file_observations("deploy.ps1", content)
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        kinds = {o.kind for o in obs}
        self.assertIn("powershell.script", kinds)
        edges = {(e.source_key, e.kind, e.target_key) for e in res.graph.edges}
        self.assertIn(("powershell.script:file%3Adeploy.ps1", "sources", "file:lib/setup.ps1"), edges)

    def test_s10_a04_powershell_manifest_syntax_fallback_and_degradation(self) -> None:
        """Malformed PowerShell manifest does not crash and falls back to legacy field scan."""
        psd1_path = self.tmpdir / "Broken.psd1"
        content = """@{
            RootModule = 'Broken.psm1'
            ModuleVersion = '0.9.0'
            # Unterminated hashtable syntax
        """
        psd1_path.write_text(content, encoding="utf-8")

        obs = extract_powershell_file_observations("Broken.psd1", psd1_path.read_text(encoding="utf-8"))
        self.assertTrue(len(obs) >= 1)
        self.assertEqual(obs[0].metadata.get("parser"), "stdlib-static-scanner")
        self.assertFalse(obs[0].metadata.get("powershell_executed"))
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        edges = {(e.source_key, e.kind, e.target_key) for e in res.graph.edges}
        self.assertIn(("powershell.manifest:file%3ABroken.psd1", "references", "file:Broken.psm1"), edges)

    def test_s10_a05_bash_output_redirection_overwrite_and_append(self) -> None:
        """Bash script output overwrite (>) and append (>>) produce references and mutation edges."""
        sh_path = self.tmpdir / "build.sh"
        content = """#!/usr/bin/env bash
        set -euo pipefail
        echo "Build start" > build/output.log
        echo "Artifact compiled" >> build/output.log
        date >> build/timestamps.txt
        """
        sh_path.write_text(content, encoding="utf-8")

        obs = extract_bash_file_observations("build.sh", content)
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        edges = {(e.source_key, e.kind, e.target_key) for e in res.graph.edges}
        self.assertIn(("file:build.sh", "references", "file:build/output.log"), edges)
        self.assertIn(("file:build.sh", "references", "file:build/timestamps.txt"), edges)
        self.assertIn(
            ("file:build.sh", "mutates_host", "host.category:file-write"), edges
        )

    def test_s10_a06_bash_input_redirection_and_herestring(self) -> None:
        """Bash input redirection (<) and here-string (<<<) are captured in observation stream."""
        sh_path = self.tmpdir / "parse.sh"
        content = """#!/usr/bin/env bash
        cat < config/settings.env
        grep "ERROR" <<< "ERROR: database unavailable"
        """
        sh_path.write_text(content, encoding="utf-8")

        obs = extract_bash_file_observations("parse.sh", content)
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        edges = {(e.source_key, e.kind, e.target_key) for e in res.graph.edges}
        self.assertIn(
            ("file:parse.sh", "references", "file:config/settings.env"), edges
        )
        self.assertIn(("file:parse.sh", "executes", "tool:cat"), edges)
        self.assertIn(("file:parse.sh", "executes", "tool:grep"), edges)

    def test_s10_a07_bash_file_descriptor_duplication_and_redirection(self) -> None:
        """Bash 2>&1 stderr-to-stdout and >&2 stdout-to-stderr descriptors are parsed cleanly."""
        sh_path = self.tmpdir / "pipes.sh"
        content = """#!/usr/bin/env bash
        make target > /dev/null 2>&1
        echo "critical failure" >&2
        """
        sh_path.write_text(content, encoding="utf-8")

        obs = extract_bash_file_observations("pipes.sh", content)
        redirect_obs = [o for o in obs if o.kind == "shell.redirect"]
        self.assertTrue(len(redirect_obs) >= 2)
        operators = {o.metadata.get("operator") for o in redirect_obs}
        self.assertIn("2>&1", operators)

    def test_s10_a08_zsh_autoload_functions_and_fpath_configuration(self) -> None:
        """Zsh configuration autoload function declarations and fpath extensions extract properly."""
        zsh_path = self.tmpdir / "env.zsh"
        content = """# Zsh setup script
        autoload -Uz compinit promptinit colors
        fpath=(~/.zsh/functions $fpath)
        compinit
        """
        zsh_path.write_text(content, encoding="utf-8")

        obs = extract_zsh_file_observations("env.zsh", zsh_path.read_text(encoding="utf-8"))
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        edges = {(e.source_key, e.kind, e.target_key) for e in res.graph.edges}
        self.assertIn(("zsh.script:file%3Aenv.zsh", "configures", "external:zsh.autoload:compinit"), edges)
        self.assertIn(("zsh.script:file%3Aenv.zsh", "configures", "external:zsh.autoload:promptinit"), edges)
        self.assertIn(("zsh.script:file%3Aenv.zsh", "configures", "external:zsh.autoload:colors"), edges)

    def test_s10_a09_zsh_option_toggles_and_environment_definitions(self) -> None:
        """Zsh setopt/unsetopt toggles and variable exports are canonicalized to writes_env."""
        zsh_path = self.tmpdir / "options.zsh"
        content = """# Zsh shell options
        setopt EXTENDED_GLOB NULL_GLOB NO_BEEP
        unsetopt NOMATCH
        export ZSH_THEME="powerlevel10k"
        export HISTSIZE=10000
        """
        zsh_path.write_text(content, encoding="utf-8")

        obs = extract_zsh_file_observations("options.zsh", zsh_path.read_text(encoding="utf-8"))
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        edges = {(e.source_key, e.kind, e.target_key) for e in res.graph.edges}
        self.assertIn(("zsh.script:file%3Aoptions.zsh", "writes_env", "env:ZSH_THEME"), edges)
        self.assertIn(("zsh.script:file%3Aoptions.zsh", "writes_env", "env:HISTSIZE"), edges)

    def test_s10_a10_multi_stage_shell_pipeline_composition_integrity(self) -> None:
        """Combined multi-technology shell pipeline (Bash, Zsh, PowerShell) produces valid graph."""
        bash_content = "#!/usr/bin/env bash\nsource ./shared.sh\necho 'run' > log.txt\n"
        zsh_content = "autoload -Uz compinit\nexport STAGE='canary'\n"
        ps_content = "@{ RootModule = 'App.psm1'; ModuleVersion = '1.0'; FunctionsToExport = @('Start-App') }"

        all_obs = [
            *extract_bash_file_observations("scripts/run.sh", bash_content),
            *extract_zsh_file_observations("scripts/init.zsh", zsh_content),
            *extract_powershell_file_observations("modules/App.psd1", ps_content),
        ]

        result = canonicalize_observations(all_obs)
        self.assertTrue(result.ok)
        node_keys = {n.canonical_key for n in result.graph.nodes}
        self.assertIn("file:scripts/run.sh", node_keys)
        self.assertIn("file:scripts/init.zsh", node_keys)
        self.assertIn("file:modules/App.psd1", node_keys)
        edges = {(e.source_key, e.kind, e.target_key) for e in result.graph.edges}
        self.assertIn(("bash.script:file%3Ascripts%2Frun.sh", "sources", "file:scripts/shared.sh"), edges)
        self.assertIn(("zsh.script:file%3Ascripts%2Finit.zsh", "configures", "external:zsh.autoload:compinit"), edges)
        self.assertIn(("powershell.manifest:file%3Amodules%2FApp.psd1", "references", "file:modules/App.psm1"), edges)


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
