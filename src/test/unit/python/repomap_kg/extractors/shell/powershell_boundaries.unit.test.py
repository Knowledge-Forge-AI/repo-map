import unittest
from repomap_kg.extractors.shell.powershell import extract_powershell_file_observations
from repomap_kg.extractors.shell.powershell_manifest_parser import _parse_manifest_document

class ShellPowerShellBoundariesUnitTests(unittest.TestCase):
    def test_powershell_manifest_and_script_extraction(self):
        ps1_script = """
Param(
    [string]$TargetEnv = "prod"
)

function Publish-Artifact {
    [CmdletBinding()]
    Param([string]$Path)
    Write-Host "Publishing to $TargetEnv"
    irm -Uri "https://api.example.com/publish" -Method Post
}

Publish-Artifact -Path "./dist"
"""
        obs = extract_powershell_file_observations("scripts/Publish.ps1", ps1_script)
        self.assertEqual(obs[0].kind, "powershell.script")
        kinds = {o.kind for o in obs}
        self.assertIn("powershell.function", kinds)
        self.assertIn("powershell.command", kinds)

    def test_powershell_manifest_document_parsing(self):
        manifest_text = """@{
    ModuleVersion = '1.0.0'
    GUID = 'd1f8a9b2-3c4e-5f6a-7b8c-9d0e1f2a3b4c'
    Author = 'Test Author'
    Description = "Module for testing `"escaped`" strings and 'nested' quotes"
    FunctionsToExport = @('Get-Test', 'Set-Test')
}"""
        doc = _parse_manifest_document(manifest_text)
        self.assertIsNotNone(doc)

    def test_powershell_rich_manifest_extraction(self):
        manifest = """@{
    RootModule = 'Core.psm1'
    ModuleVersion = '1.2.3'
    GUID = 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d'
    Author = 'Dev'
    Description = 'Testing rich manifest fields'
    RequiredModules = @(
        'SimpleDep',
        @{ ModuleName = 'AdvancedDep'; ModuleVersion = '2.1.0'; RequiredVersion = '2.1.0'; MaximumVersion = '3.0.0'; GUID = '11111111-2222-3333-4444-555555555555' },
        42
    )
    RequiredAssemblies = @('System.Xml.dll', 'MyLib.dll')
    ScriptsToProcess = @('setup.ps1')
    NestedModules = @('sub/nested.psm1')
    TypesToProcess = @('types.ps1xml')
    FormatsToProcess = @('formats.ps1xml')
    FileList = @('data.txt', 'readme.md')
    FunctionsToExport = @('Get-Service', 'Set-Service')
    CmdletsToExport = @('Get-CustomCmdlet')
    AliasesToExport = @('gserv')
    VariablesToExport = @('MyVar')
    DscResourcesToExport = @('MyDsc')
    PrivateData = @{
        PSData = @{
            Tags = @('tag1', 'tag2')
            ProjectUri = 'https://example.com'
        }
    }
}"""
        obs = extract_powershell_file_observations("manifest.psd1", manifest)
        kinds = {o.kind for o in obs}
        self.assertIn("powershell.manifest", kinds)
        self.assertIn("powershell.manifest_dependency", kinds)
        self.assertIn("powershell.manifest_export", kinds)
        self.assertIn("powershell.manifest_private_data", kinds)
        self.assertIn("powershell.manifest_file_reference", kinds)
        self.assertIn("powershell.manifest_field", kinds)

    def test_powershell_legacy_fallback_extraction(self):
        legacy_manifest = """
ModuleVersion = '1.0.0'
NestedModules = @(
    'Helper.psm1',
    'Extra.psm1'
)
Custom = $something_unknown
"""
        obs = extract_powershell_file_observations("legacy.psd1", legacy_manifest)
        self.assertEqual(len(obs), 4)
        names = {o.name for o in obs}
        self.assertIn("ModuleVersion", names)
        self.assertIn("NestedModules", names)
        self.assertIn("Custom", names)


if __name__ == "__main__":
    unittest.main()
