# Static extraction fixture only. Do not execute.
@{
    RootModule = 'Advanced.Module.psm1'
    ModuleVersion = '1.2.3'
    GUID = '11111111-2222-3333-4444-555555555555'
    Author = 'RepoMap Fixture'
    CompanyName = 'Example Org'
    Copyright = '(c) 2026 Example'
    Description = 'Advanced manifest fixture'
    PowerShellVersion = '7.2'
    CompatiblePSEditions = @('Core', 'Desktop')
    DotNetFrameworkVersion = '4.8'
    CLRVersion = '4.0'
    ProcessorArchitecture = 'None'
    HelpInfoURI = 'https://example.invalid/help'
    DefaultCommandPrefix = 'Adv'
    RequiredModules = @(
        'ThreadJob'
        @{ ModuleName = 'Pester'; ModuleVersion = '5.0.0' }
        @{ ModuleName = 'ThreadJob'; RequiredVersion = '2.0.3'; GUID = '22222222-3333-4444-5555-666666666666' }
    )
    RequiredAssemblies = @('System.Text.Json', 'lib/Example.dll')
    ScriptsToProcess = @('scripts/init.ps1')
    TypesToProcess = @('types/Advanced.Types.ps1xml')
    FormatsToProcess = @('formats/Advanced.Format.ps1xml')
    NestedModules = @('Nested.Module.psm1')
    ModuleList = @('Advanced.Module.psm1')
    FileList = @('README.md')
    FunctionsToExport = @('Get-AdvancedThing', 'Invoke-AdvancedThing')
    CmdletsToExport = @()
    AliasesToExport = '*'
    VariablesToExport = @('AdvancedConfig')
    DscResourcesToExport = @('AdvancedResource')
    PrivateData = @{
        PSData = @{
            Tags = @('repomap', 'static-fixture')
            ProjectUri = 'https://example.invalid/project'
            LicenseUri = 'https://example.invalid/license'
            IconUri = 'https://example.invalid/icon.png'
            ReleaseNotes = 'Fixture release notes'
            Prerelease = 'alpha'
        }
        ApiToken = 'FAKE_MANIFEST_TOKEN'
        ApiKey = 'FAKE_MANIFEST_API_KEY'
        Password = 'FAKE_MANIFEST_PASSWORD'
        PatValue = 'fake-manifest-pat'
        Authorization = 'Bearer FAKE_MANIFEST_AUTH'
    }
    IsPreview = $true
    Count = 42
    OptionalValue = $null
    # FunctionsToExport = @('CommentedOut')
    GeneratedOn = (Get-Date)
    DynamicVersion = $Version
}
