"""Integration tests for Slice 12 manifest canonical pipeline (Group S12-A).

Covers:
- S12-A01: Manifest scalar/empty export alternatives
- S12-A02: Manifest export token categories
- S12-A03: Manifest field fallback metadata
- S12-A04: Manifest value shape retention
- S12-A05: Mixed manifest-array item handling
- S12-A06: Quoted manifest-string handling
- S12-A07: Manifest hashtable boundary recovery
- S12-A08: Manifest array boundary handling
- S12-A09: Manifest expression value selection
- S12-A10: Nested parenthesized expression boundary
"""

from __future__ import annotations

import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.extractors.shell.powershell import (
    extract_powershell_file_observations,
)


class Slice12ManifestCanonicalPipelineIntegrationTests(unittest.TestCase):
    """Slice 12 Group S12-A integration tests for manifest extraction and canonicalization."""

    def test_s12_a01_manifest_scalar_empty_export_alternatives(self) -> None:
        """Manifest scalar and empty export forms extract distinct observations and canonicalize."""
        content = """@{
            RootModule = 'Core.psm1'
            ModuleVersion = '1.0.0'
            FunctionsToExport = '*'
            AliasesToExport = @()
            CmdletsToExport = 'Get-Service'
        }"""
        obs = extract_powershell_file_observations("Core.psd1", content)
        exports = [o for o in obs if o.kind == "powershell.manifest_export"]
        self.assertTrue(len(exports) >= 2)
        wildcard_exports = [e for e in exports if e.metadata.get("wildcard") is True]
        scalar_exports = [e for e in exports if e.name == "Get-Service"]
        self.assertEqual(len(wildcard_exports), 1)
        self.assertEqual(len(scalar_exports), 1)

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        manifest_nodes = [n for n in res.graph.nodes if n.canonical_key == "powershell.manifest:file%3ACore.psd1"]
        self.assertEqual(len(manifest_nodes), 1)
        self.assertEqual(manifest_nodes[0].kind, "powershell.manifest")

    def test_s12_a02_manifest_export_token_categories(self) -> None:
        """Contrasts literal function export lists with wildcard cmdlet exports."""
        content = """@{
            RootModule = 'Exports.psm1'
            ModuleVersion = '2.0.0'
            FunctionsToExport = @('Get-Data', 'Set-Data')
            CmdletsToExport = '*'
        }"""
        obs = extract_powershell_file_observations("Exports.psd1", content)
        exports = [o for o in obs if o.kind == "powershell.manifest_export"]
        fn_exports = [e for e in exports if e.metadata.get("export_kind") == "function"]
        cmd_exports = [e for e in exports if e.metadata.get("export_kind") == "cmdlet"]
        self.assertEqual(len(fn_exports), 2)
        self.assertEqual(len(cmd_exports), 1)
        self.assertTrue(cmd_exports[0].metadata.get("wildcard"))

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        manifest_nodes = [n for n in res.graph.nodes if n.canonical_key == "powershell.manifest:file%3AExports.psd1"]
        self.assertEqual(len(manifest_nodes), 1)
        export_edges = [e for e in res.graph.edges if e.kind == "defines"]
        self.assertTrue(len(export_edges) >= 2)

    def test_s12_a03_manifest_field_fallback_metadata(self) -> None:
        """Extracts runtime and framework requirement fields into manifest field observations."""
        content = """@{
            RootModule = 'Runtime.psm1'
            ModuleVersion = '1.0.0'
            ClrVersion = '4.0'
            DotNetFrameworkVersion = '4.5'
        }"""
        obs = extract_powershell_file_observations("Runtime.psd1", content)
        field_obs = [o for o in obs if o.kind == "powershell.manifest_field"]
        names = {f.name for f in field_obs}
        self.assertIn("ClrVersion", names)
        self.assertIn("DotNetFrameworkVersion", names)

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        manifest_nodes = [n for n in res.graph.nodes if n.canonical_key == "powershell.manifest:file%3ARuntime.psd1"]
        self.assertEqual(len(manifest_nodes), 1)
        self.assertEqual(manifest_nodes[0].metadata.get("language"), "powershell")

    def test_s12_a04_manifest_value_shape_retention(self) -> None:
        """Retains value shapes for version numbers, arrays, and editions in manifest metadata."""
        content = """@{
            RootModule = 'Editions.psm1'
            ModuleVersion = '1.2.3.4'
            PowerShellVersion = '5.1'
            CompatiblePSEditions = @('Desktop', 'Core')
        }"""
        obs = extract_powershell_file_observations("Editions.psd1", content)
        field_obs = [o for o in obs if o.kind == "powershell.manifest_field"]
        edition_obs = [f for f in field_obs if f.name == "CompatiblePSEditions"]
        self.assertEqual(len(edition_obs), 1)
        self.assertEqual(edition_obs[0].metadata.get("value_type"), "string-array")
        self.assertEqual(edition_obs[0].metadata.get("values"), ["Desktop", "Core"])
        ps_ver = [f for f in field_obs if f.name == "PowerShellVersion"]
        self.assertEqual(len(ps_ver), 1)
        self.assertEqual(ps_ver[0].metadata.get("value_type"), "string")
        self.assertEqual(ps_ver[0].metadata.get("value"), "5.1")

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        manifest_nodes = [n for n in res.graph.nodes if n.canonical_key == "powershell.manifest:file%3AEditions.psd1"]
        self.assertEqual(len(manifest_nodes), 1)

    def test_s12_a05_mixed_manifest_array_item_handling(self) -> None:
        """Extracts heterogeneous arrays containing strings, integers, and nested hashtables."""
        content = """@{
            RootModule = 'Mixed.psm1'
            ModuleVersion = '1.0.0'
            FileList = @('data.csv', 100, @{ extra = 'config.json' })
        }"""
        obs = extract_powershell_file_observations("Mixed.psd1", content)
        field_obs = [o for o in obs if o.kind == "powershell.manifest_field" and o.name == "FileList"]
        self.assertEqual(len(field_obs), 1)
        self.assertEqual(field_obs[0].metadata.get("value_type"), "array")
        self.assertEqual(field_obs[0].metadata.get("value_shape"), ["string", "int", "hashtable"])

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        manifest_nodes = [n for n in res.graph.nodes if n.canonical_key == "powershell.manifest:file%3AMixed.psd1"]
        self.assertEqual(len(manifest_nodes), 1)

    def test_s12_a06_quoted_manifest_string_handling(self) -> None:
        """Decodes escaped single quotes and backtick-escaped double quotes in manifest strings."""
        content = """@{
            RootModule = 'Escapes.psm1'
            ModuleVersion = '1.0.0'
            Description = 'Tool with ''escaped'' quotes and "nested" tags'
        }"""
        obs = extract_powershell_file_observations("Escapes.psd1", content)
        desc_obs = [o for o in obs if o.name == "Description"]
        self.assertEqual(len(desc_obs), 1)
        self.assertIn("escaped", desc_obs[0].metadata.get("value", ""))

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        manifest_nodes = [n for n in res.graph.nodes if n.canonical_key == "powershell.manifest:file%3AEscapes.psd1"]
        self.assertEqual(len(manifest_nodes), 1)

    def test_s12_a07_manifest_hashtable_boundary_recovery(self) -> None:
        """Recovers gracefully from incomplete or malformed hashtable entries without failure."""
        content = """@{
            RootModule = 'Incomplete.psm1'
            ModuleVersion = '1.0.0'
            PrivateData = @{ KeyWithoutValue = }
        }"""
        obs = extract_powershell_file_observations("Incomplete.psd1", content)
        secret_obs = [o for o in obs if o.kind == "powershell.secret_like"]
        self.assertEqual(len(secret_obs), 1)
        self.assertEqual(secret_obs[0].name, "PrivateData.KeyWithoutValue")
        self.assertTrue(secret_obs[0].metadata.get("redacted"))

        field_obs = [o for o in obs if o.name == "KeyWithoutValue"]
        self.assertEqual(len(field_obs), 1)
        self.assertTrue(field_obs[0].metadata.get("redacted"))
        self.assertEqual(field_obs[0].metadata.get("unknown_reason"), "unsupported-manifest-value")

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        manifest_nodes = [n for n in res.graph.nodes if n.canonical_key == "powershell.manifest:file%3AIncomplete.psd1"]
        self.assertEqual(len(manifest_nodes), 1)

        # Graph isolation: malformed secret-like field produces no invented canonical nodes or edges
        keys = {n.canonical_key for n in res.graph.nodes}
        self.assertNotIn("symbol:KeyWithoutValue", keys)
        self.assertNotIn("file:KeyWithoutValue", keys)
        edge_targets = {e.target_key for e in res.graph.edges}
        self.assertEqual(edge_targets, {"powershell.manifest:file%3AIncomplete.psd1", "file:Incomplete.psm1"})

        # Paired contrast: well-formed PrivateData preserves string value_type
        clean_content = """@{
            RootModule = 'Incomplete.psm1'
            ModuleVersion = '1.0.0'
            PrivateData = @{ Setting = 'CleanValue' }
        }"""
        clean_obs = extract_powershell_file_observations("Incomplete.psd1", clean_content)
        clean_field = [o for o in clean_obs if o.name == "Setting"][0]
        self.assertEqual(clean_field.metadata.get("value_type"), "string")
        self.assertEqual(clean_field.metadata.get("value"), "CleanValue")

    def test_s12_a08_manifest_array_boundary_handling(self) -> None:
        """Handles empty array definitions and preserves manifest structure in canonical output."""
        content = """@{
            RootModule = 'EmptyArray.psm1'
            ModuleVersion = '1.0.0'
            ScriptsToProcess = @()
        }"""
        obs = extract_powershell_file_observations("EmptyArray.psd1", content)
        scripts_obs = [o for o in obs if o.name == "ScriptsToProcess"]
        self.assertEqual(len(scripts_obs), 1)

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        manifest_nodes = [n for n in res.graph.nodes if n.canonical_key == "powershell.manifest:file%3AEmptyArray.psd1"]
        self.assertEqual(len(manifest_nodes), 1)

    def test_s12_a09_manifest_expression_value_selection(self) -> None:
        """Extracts parenthesized and variable-expression values into unknown/dynamic observations."""
        content = """@{
            RootModule = 'Expr.psm1'
            ModuleVersion = '1.0.0'
            VariablesToExport = ($null)
        }"""
        obs = extract_powershell_file_observations("Expr.psd1", content)
        var_obs = [o for o in obs if o.name == "VariablesToExport"]
        self.assertEqual(len(var_obs), 1)

        export_obs = [o for o in obs if o.kind == "powershell.manifest_export"]
        self.assertEqual(len(export_obs), 1)
        self.assertEqual(export_obs[0].name, "[unknown]")
        self.assertEqual(export_obs[0].metadata.get("export_kind"), "variable")
        self.assertEqual(export_obs[0].metadata.get("resolution"), "unknown")

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        manifest_nodes = [n for n in res.graph.nodes if n.canonical_key == "powershell.manifest:file%3AExpr.psd1"]
        self.assertEqual(len(manifest_nodes), 1)

        export_nodes = [n for n in res.graph.nodes if n.kind == "powershell.export"]
        self.assertEqual(len(export_nodes), 1)
        self.assertEqual(export_nodes[0].display_name, "%5Bunknown%5D")
        self.assertIn("variable:%5Bunknown%5D", export_nodes[0].canonical_key)

        # Paired contrast: explicit literal variable exports known export symbol
        static_content = """@{
            RootModule = 'Expr.psm1'
            ModuleVersion = '1.0.0'
            VariablesToExport = @('KnownVar')
        }"""
        static_obs = extract_powershell_file_observations("Expr.psd1", static_content)
        static_res = canonicalize_observations(static_obs)
        static_export_nodes = [n for n in static_res.graph.nodes if n.kind == "powershell.export"]
        self.assertEqual(len(static_export_nodes), 1)
        self.assertEqual(static_export_nodes[0].display_name, "KnownVar")

    def test_s12_a10_nested_parenthesized_expression_boundary(self) -> None:
        """Parses nested parenthesized expressions within manifest items preserving downstream graph."""
        content = """@{
            RootModule = 'Nested.psm1'
            ModuleVersion = '1.0.0'
            NestedModules = @((( 'Inner.psm1' )))
        }"""
        obs = extract_powershell_file_observations("Nested.psd1", content)
        ref_obs = [
            o for o in obs
            if o.kind == "powershell.manifest_file_reference" and o.metadata.get("field") == "NestedModules"
        ]
        self.assertEqual(len(ref_obs), 1)
        self.assertEqual(ref_obs[0].name, "[unknown]")
        self.assertEqual(ref_obs[0].metadata.get("resolution"), "unknown")

        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        manifest_nodes = [n for n in res.graph.nodes if n.canonical_key == "powershell.manifest:file%3ANested.psd1"]
        self.assertEqual(len(manifest_nodes), 1)

        # Specifically discriminate nested module edge target from RootModule edge target
        nested_edges = [e for e in res.graph.edges if e.target_key == "file:%5Bunknown%5D"]
        self.assertEqual(len(nested_edges), 1)
        self.assertEqual(nested_edges[0].source_key, "powershell.manifest:file%3ANested.psd1")
        self.assertEqual(nested_edges[0].kind, "references")

        root_edges = [e for e in res.graph.edges if e.target_key == "file:Nested.psm1"]
        self.assertEqual(len(root_edges), 1)

        # Paired contrast: unnested string literal references the exact inner module file
        direct_content = """@{
            RootModule = 'Nested.psm1'
            ModuleVersion = '1.0.0'
            NestedModules = @('Inner.psm1')
        }"""
        direct_obs = extract_powershell_file_observations("Nested.psd1", direct_content)
        direct_res = canonicalize_observations(direct_obs)
        direct_inner_edges = [e for e in direct_res.graph.edges if e.target_key == "file:Inner.psm1"]
        self.assertEqual(len(direct_inner_edges), 1)


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
