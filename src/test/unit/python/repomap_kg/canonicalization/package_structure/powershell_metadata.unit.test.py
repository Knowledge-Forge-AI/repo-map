from __future__ import annotations

from typing import Any
import unittest

from repomap_kg.canonicalization import _shell_powershell_metadata as pm
from repomap_kg.graph.keys import GraphKeyError
from repomap_kg.observations.raw import RawObservation


POWERSHELL_METADATA_EXPORTS = (
    "_powershell_command_edge_metadata",
    "_powershell_command_name",
    "_powershell_container_key",
    "_powershell_container_node_metadata",
    "_powershell_define_edge_metadata",
    "_powershell_display_name",
    "_powershell_env_edge_metadata",
    "_powershell_file_node_metadata",
    "_powershell_file_target_key",
    "_powershell_file_target_key_from_observation",
    "_powershell_function_node_metadata",
    "_powershell_host_mutation_edge_metadata",
    "_powershell_manifest_dependency_edge_metadata",
    "_powershell_manifest_dependency_target_key",
    "_powershell_module_or_file_target_key",
    "_powershell_network_target_key",
    "_powershell_reference_edge_metadata",
    "_powershell_reference_parts",
    "_powershell_reference_source_metadata",
    "_powershell_remoting_target_key",
)


def _obs(
    kind: str,
    path: str,
    *,
    name: str | None = None,
    target: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id="src-1",
        path=path,
        confidence="extracted",
        extractor="test",
        extractor_version="1.0",
        name=name,
        target=target,
        metadata=metadata or {},
    )


class PowerShellMetadataUnitTests(unittest.TestCase):
    def test_rootpkg30_powershell_family_reexports_metadata_helpers(self) -> None:
        import repomap_kg.canonicalization.shell_powershell_family as family
        import repomap_kg.canonicalization._shell_powershell_metadata as metadata
        for name in POWERSHELL_METADATA_EXPORTS:
            self.assertIs(getattr(family, name), getattr(metadata, name))

    def test_file_and_container_keys_and_node_metadata(self):
        obs_mod = _obs("powershell.module", "tools/Module.psm1", metadata={"file_type": "module"})
        obs_man = _obs("powershell.manifest", "tools/Module.psd1")
        obs_scr = _obs("powershell.script", "tools/build.ps1")

        self.assertEqual(pm._powershell_file_target_key(obs_mod), "powershell.module:file%3Atools%2FModule.psm1")
        self.assertEqual(pm._powershell_file_target_key(obs_man), "powershell.manifest:file%3Atools%2FModule.psd1")
        self.assertEqual(pm._powershell_file_target_key(obs_scr), "powershell.script:file%3Atools%2Fbuild.ps1")

        self.assertEqual(pm._powershell_container_key("tools/Mod.psm1"), "powershell.module:file%3Atools%2FMod.psm1")
        self.assertEqual(pm._powershell_container_key("tools/Mod.psd1"), "powershell.manifest:file%3Atools%2FMod.psd1")
        self.assertEqual(pm._powershell_container_key("tools/Mod.ps1"), "powershell.script:file%3Atools%2FMod.ps1")

        node_mod = pm._powershell_file_node_metadata(obs_mod)
        self.assertEqual(node_mod["file_type"], "module")
        node_scr = pm._powershell_file_node_metadata(obs_scr)
        self.assertNotIn("file_type", node_scr)

        self.assertEqual(pm._powershell_container_node_metadata("a.psm1")["file_type"], "module")
        self.assertEqual(pm._powershell_container_node_metadata("a.psd1")["file_type"], "manifest")
        self.assertEqual(pm._powershell_container_node_metadata("a.ps1")["file_type"], "script")

    def test_function_and_define_edge_metadata(self):
        fn_meta = pm._powershell_function_node_metadata({"scope_prefix": "global", "function": "Invoke-Tool"})
        self.assertEqual(fn_meta["scope_prefix"], "global")
        self.assertEqual(fn_meta["function"], "Invoke-Tool")

        def_edge = pm._powershell_define_edge_metadata({
            "file_type": "module",
            "scope_prefix": "script",
            "function": "Get-Info",
            "export_kind": "cmdlet",
            "wildcard": True,
        })
        self.assertEqual(def_edge["functions"], ["Get-Info"])
        self.assertTrue(def_edge["wildcard_observed"])

    def test_command_name_and_command_edge_metadata(self):
        self.assertEqual(pm._powershell_command_name(_obs("cmd", "p", metadata={"normalized_command": "Get-ChildItem"})), "Get-ChildItem")
        self.assertEqual(pm._powershell_command_name(_obs("cmd", "p", metadata={"command_name": "dir"})), "dir")
        self.assertEqual(pm._powershell_command_name(_obs("cmd", "p", metadata={"original_token": "gci"})), "gci")
        self.assertEqual(pm._powershell_command_name(_obs("cmd", "p", name="pwsh")), "pwsh")
        self.assertEqual(pm._powershell_command_name(_obs("cmd", "p", target="tool:pwsh")), "pwsh")
        self.assertIsNone(pm._powershell_command_name(_obs("cmd", "p", target="tool:bad:key:extra")))
        self.assertIsNone(pm._powershell_command_name(_obs("cmd", "p")))

        cmd_meta = pm._powershell_command_edge_metadata(
            {
                "original_token": "gci",
                "command_family": "filesystem",
                "alias_expansion": "Get-ChildItem",
                "alias_source": "built-in",
                "argument_count": 3,
                "pipeline_id": "pipe-1",
                "pipeline_index": 0,
            },
            "Get-ChildItem",
        )
        self.assertEqual(cmd_meta["commands"], ["Get-ChildItem"])
        self.assertEqual(cmd_meta["argument_counts"], [3])
        self.assertEqual(cmd_meta["pipeline_ids"], ["pipe-1"])
        self.assertEqual(cmd_meta["pipeline_indexes"], [0])

    def test_env_and_host_mutation_edge_metadata(self):
        env_read = pm._powershell_env_edge_metadata({"redacted": True}, "powershell.env_read")
        self.assertEqual(env_read["operations"], ["read"])
        self.assertTrue(env_read["redacted_observed"])

        env_write = pm._powershell_env_edge_metadata({"redacted": False}, "powershell.env_write")
        self.assertEqual(env_write["operations"], ["write"])
        self.assertFalse(env_write["redacted_observed"])

        mut_edge = pm._powershell_host_mutation_edge_metadata({
            "mutation_category": "filesystem",
            "operation": "delete",
            "destructive": True,
            "target_redacted": False,
        })
        self.assertEqual(mut_edge["mutation_categories"], ["filesystem"])
        self.assertTrue(mut_edge["destructive_observed"])
        self.assertFalse(mut_edge["target_redacted_observed"])

    def test_reference_parts_dispatch_and_targets(self):
        # import_module
        obs_import = _obs(
            "powershell.import_module",
            "script.ps1",
            target="file:lib/helper.psm1",
            metadata={"network_executed": False},
        )
        src, tgt, rel, meta = pm._powershell_reference_parts(obs_import)
        self.assertEqual(rel, "imports")
        self.assertEqual(tgt, "file:lib/helper.psm1")

        # dot_source
        obs_dot = _obs(
            "powershell.dot_source",
            "script.ps1",
            metadata={"resolved_path": "lib/util.ps1"},
        )
        src, tgt, rel, meta = pm._powershell_reference_parts(obs_dot)
        self.assertEqual(rel, "sources")
        self.assertEqual(tgt, "file:lib/util.ps1")

        # manifest_dependency
        obs_dep_mod = _obs(
            "powershell.manifest_dependency",
            "Mod.psd1",
            metadata={"dependency_kind": "module", "module_name": "Pester"},
        )
        src, tgt, rel, meta = pm._powershell_reference_parts(obs_dep_mod)
        self.assertEqual(rel, "depends_on")
        self.assertEqual(tgt, "external:powershell.module:Pester")

        obs_dep_asm = _obs(
            "powershell.manifest_dependency",
            "Mod.psd1",
            metadata={"dependency_kind": "assembly", "assembly_name": "System.Text.Json"},
        )
        self.assertEqual(pm._powershell_manifest_dependency_target_key(obs_dep_asm), "external:powershell.assembly:System.Text.Json")

        # manifest_file_reference
        obs_file_ref = _obs(
            "powershell.manifest_file_reference",
            "Mod.psd1",
            metadata={"reference": "Sub.psm1"},
        )
        src, tgt, rel, meta = pm._powershell_reference_parts(obs_file_ref)
        self.assertEqual(rel, "references")
        self.assertEqual(tgt, "file:Sub.psm1")

        # manifest_export
        obs_export = _obs(
            "powershell.manifest_export",
            "Mod.psd1",
            name="Get-BuildInfo",
            metadata={"export_kind": "function"},
        )
        src, tgt, rel, meta = pm._powershell_reference_parts(obs_export)
        self.assertEqual(rel, "defines")
        self.assertIn("function", tgt)

        # network_call
        obs_net = _obs(
            "powershell.network_call",
            "script.ps1",
            metadata={"target_display": "https://api.github.com/status"},
        )
        src, tgt, rel, meta = pm._powershell_reference_parts(obs_net)
        self.assertEqual(rel, "references")
        self.assertIn("external.url", tgt)

        obs_net_dyn = _obs(
            "powershell.network_call",
            "script.ps1",
            metadata={"target_display": "[dynamic]"},
        )
        self.assertIn("powershell-network-target", pm._powershell_network_target_key(obs_net_dyn))

        # remoting
        obs_remote = _obs(
            "powershell.remoting",
            "script.ps1",
            metadata={"target_display": "server01.corp", "target_kind": "static", "remoting_executed": True},
        )
        src, tgt, rel, meta = pm._powershell_reference_parts(obs_remote)
        self.assertEqual(rel, "references")
        self.assertEqual(tgt, "external:powershell.remoting:server01.corp")
        self.assertTrue(meta["remoting_executed"])

        # unsupported kind raises GraphKeyError
        with self.assertRaises(GraphKeyError):
            pm._powershell_reference_parts(_obs("powershell.unknown_ref", "s.ps1"))

    def test_display_name_and_source_metadata_helpers(self):
        self.assertEqual(pm._powershell_display_name("powershell.module:file%3Aa.psm1", "tools/a.psm1"), "tools/a.psm1")
        self.assertEqual(pm._powershell_display_name("file:tools/build.ps1", "tools/build.ps1"), "tools/build.ps1")

        self.assertEqual(
            pm._powershell_reference_source_metadata("powershell.module:file%3Aa.psm1", "tools/a.psm1")["file_type"],
            "module",
        )
        self.assertEqual(pm._powershell_reference_source_metadata("file:tools/build.ps1", "tools/build.ps1"), {})


if __name__ == "__main__":
    unittest.main()
