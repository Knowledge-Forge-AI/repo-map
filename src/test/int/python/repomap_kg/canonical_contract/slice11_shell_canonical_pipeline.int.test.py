"""Integration tests for Slice 11 shell canonical pipeline (Group S11-A).

Covers:
- S11-A01: PowerShell manifest GUID and dependency identity metadata
- S11-A02: PowerShell dynamic RequiredModules target versus literal resolution
- S11-A03: PowerShell PrivateData.PSData metadata composition
- S11-A04: PowerShell network-command reference metadata
- S11-A05: Bash input process-substitution attribution (<(command))
- S11-A06: Bash output process-substitution attribution (>(command))
- S11-A07: PowerShell manifest file-reference literal and unresolved alternatives
- S11-A08: Zsh autoload options and parameter metadata
- S11-A09: Zsh plugin-manager source and reference attribution (zplug)
- S11-A10: Zsh #compdef directive metadata composition
"""

from __future__ import annotations

import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.extractors.shell.bash import extract_bash_file_observations
from repomap_kg.extractors.shell.powershell import (
    extract_powershell_file_observations,
)
from repomap_kg.extractors.shell.zsh import extract_zsh_file_observations


class Slice11ShellCanonicalPipelineIntegrationTests(unittest.TestCase):
    """Slice 11 Group S11-A integration tests for shell canonical contracts."""

    def test_s11_a01_powershell_module_manifest_guid_and_identity_metadata(self) -> None:
        """PowerShell manifest extracts dependency GUID and canonicalizes module dependencies."""
        content = """@{
            RootModule = 'CoreModule.psm1'
            ModuleVersion = '3.0.0'
            RequiredModules = @(
                @{ ModuleName = 'Pester'; GUID = 'd3b07384-d113-40a2-a7d1-0f402f065a3c'; ModuleVersion = '5.5.0' }
            )
        }"""
        obs = extract_powershell_file_observations("CoreModule.psd1", content)
        dep_obs = [o for o in obs if o.kind == "powershell.manifest_dependency"]
        self.assertEqual(len(dep_obs), 1)
        self.assertEqual(dep_obs[0].metadata.get("guid"), "d3b07384-d113-40a2-a7d1-0f402f065a3c")
        self.assertEqual(dep_obs[0].metadata.get("module_name"), "Pester")

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        edges = {(e.source_key, e.kind, e.target_key) for e in res.graph.edges}
        manifest_key = "powershell.manifest:file%3ACoreModule.psd1"
        self.assertIn((manifest_key, "depends_on", "external:powershell.module:Pester"), edges)

    def test_s11_a02_powershell_dynamic_required_modules_versus_literal(self) -> None:
        """Contrasts literal RequiredModules with dynamic or variable references."""
        content = """@{
            RootModule = 'MixedDeps.psm1'
            ModuleVersion = '1.0.0'
            RequiredModules = @('PSReadLine', "$DynamicEnvModule")
        }"""
        obs = extract_powershell_file_observations("MixedDeps.psd1", content)
        dep_obs = [o for o in obs if o.kind == "powershell.manifest_dependency"]
        literal_deps = [d for d in dep_obs if d.name == "PSReadLine"]
        self.assertEqual(len(literal_deps), 1)
        unknown_deps = [d for d in dep_obs if d.metadata.get("unknown_reason") == "dynamic-string"]
        self.assertEqual(len(unknown_deps), 1)

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        edges = {(e.source_key, e.kind, e.target_key) for e in res.graph.edges}
        manifest_key = "powershell.manifest:file%3AMixedDeps.psd1"
        self.assertIn((manifest_key, "depends_on", "external:powershell.module:PSReadLine"), edges)

    def test_s11_a03_powershell_manifest_private_data_psdata_metadata(self) -> None:
        """PowerShell manifest extracts PrivateData.PSData metadata observations."""
        content = """@{
            RootModule = 'PackageInfo.psm1'
            ModuleVersion = '1.0.0'
            PrivateData = @{
                PSData = @{
                    ProjectUri = 'https://github.com/example/powershell-tool'
                    Tags = @('Automation', 'CrossPlatform')
                }
            }
        }"""
        obs = extract_powershell_file_observations("PackageInfo.psd1", content)
        pd_obs = [o for o in obs if o.kind == "powershell.manifest_private_data"]
        self.assertTrue(len(pd_obs) >= 1)
        names = {o.name for o in pd_obs if o.name is not None}
        self.assertTrue(any("PSData" in n for n in names))
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)

    def test_s11_a04_powershell_network_command_reference_metadata(self) -> None:
        """Inert PowerShell extraction attributes network commands and URI arguments."""
        content = """
        Invoke-WebRequest -Uri 'https://api.example.com/status' -Method Get
        Write-Output "done"
        """
        obs = extract_powershell_file_observations("fetch.ps1", content)
        cmd_obs = [o for o in obs if o.name == "Invoke-WebRequest"]
        self.assertTrue(len(cmd_obs) >= 1)
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)

    def test_s11_a05_bash_input_process_substitution_attribution(self) -> None:
        """Bash input process substitution <(cmd) is extracted and attributed."""
        content = """#!/usr/bin/env bash
        diff <(sort left.txt) <(sort right.txt)
        """
        obs = extract_bash_file_observations("compare.sh", content)
        subs = [o for o in obs if o.kind == "shell.process_substitution"]
        self.assertEqual(len(subs), 2)
        for s in subs:
            self.assertEqual(s.metadata.get("direction"), "input")
            self.assertEqual(s.metadata.get("resolution"), "dynamic")
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)

    def test_s11_a06_bash_output_process_substitution_attribution(self) -> None:
        """Bash output process substitution >(cmd) is extracted with output direction."""
        content = """#!/usr/bin/env bash
        cat raw_data.csv | tee >(gzip -c > backup.csv.gz) | cut -d, -f1
        """
        obs = extract_bash_file_observations("pipeline.sh", content)
        subs = [o for o in obs if o.kind == "shell.process_substitution"]
        self.assertTrue(len(subs) >= 1)
        out_subs = [s for s in subs if s.metadata.get("direction") == "output"]
        self.assertEqual(len(out_subs), 1)
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)

    def test_s11_a07_powershell_manifest_file_reference_unresolved_alternative(self) -> None:
        """PowerShell manifest file references distinguish existing and unresolvable targets."""
        content = """@{
            RootModule = 'Scripted.psm1'
            ModuleVersion = '1.0.0'
            ScriptsToProcess = @('init.ps1', 'helpers/missing.ps1', 'CustomModule')
        }"""
        obs = extract_powershell_file_observations("Scripted.psd1", content)
        file_refs = [o for o in obs if o.kind == "powershell.manifest_file_reference"]
        self.assertEqual(len(file_refs), 4)
        resolvable = [r for r in file_refs if r.metadata.get("resolution") == "static"]
        unresolved = [r for r in file_refs if r.metadata.get("resolution") == "module-name"]
        self.assertEqual(len(resolvable), 3)
        self.assertEqual(len(unresolved), 1)
        self.assertIn("file:init.ps1", {r.target for r in resolvable})
        self.assertIsNone(unresolved[0].target)
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)

    def test_s11_a08_zsh_autoload_options_and_parameter_metadata(self) -> None:
        """Zsh autoload directive extracts flags (-U, -z) and targets."""
        content = """
        autoload -Uz compinit promptinit
        compinit
        """
        obs = extract_zsh_file_observations("env.zsh", content)
        autoload_obs = [o for o in obs if o.kind == "zsh.autoload"]
        self.assertTrue(len(autoload_obs) >= 1)
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)

    def test_s11_a09_zsh_plugin_manager_zplug_attribution(self) -> None:
        """Zsh zplug plugin declarations produce manager and plugin observations."""
        content = """
        zplug "zsh-users/zsh-syntax-highlighting"
        zplug "plugins/git"
        zplug load
        """
        obs = extract_zsh_file_observations("plugins.zsh", content)
        mgr_obs = [o for o in obs if o.kind == "zsh.plugin_manager"]
        plug_obs = [o for o in obs if o.kind == "zsh.plugin"]
        self.assertTrue(len(mgr_obs) >= 1)
        self.assertTrue(len(plug_obs) >= 2)
        plug_names = {p.name for p in plug_obs}
        self.assertIn("zsh-users/zsh-syntax-highlighting", plug_names)
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)

    def test_s11_a10_zsh_compdef_directive_metadata_composition(self) -> None:
        """Zsh #compdef header directive extracts completion function identity."""
        content = """#compdef mytool git-flow
        _arguments '1:action:(start stop status)'
        """
        obs = extract_zsh_file_observations("_mytool", content)
        comp_obs = [o for o in obs if o.kind == "zsh.completion_function"]
        self.assertEqual(len(comp_obs), 1)
        self.assertEqual(comp_obs[0].metadata.get("compdef_target"), "mytool")
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
