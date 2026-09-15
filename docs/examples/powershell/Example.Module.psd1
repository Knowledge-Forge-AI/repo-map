@{
    RootModule = 'Example.Module.psm1'
    ModuleVersion = '0.1.0'
    GUID = '11111111-2222-3333-4444-555555555555'
    Author = 'Example Author'
    CompanyName = 'Example Company'
    RequiredModules = @(
        'Microsoft.PowerShell.Management'
    )
    RequiredAssemblies = @()
    ScriptsToProcess = @()
    TypesToProcess = @()
    FormatsToProcess = @()
    NestedModules = @()
    FunctionsToExport = @(
        'Get-ExampleReport',
        'Set-ExampleServiceState',
        'Register-ExampleTask'
    )
    CmdletsToExport = @()
    AliasesToExport = @()
    PrivateData = @{
        PSData = @{
            Tags = @('repomap', 'static-fixture')
            ProjectUri = 'https://example.invalid/repomap/powershell-fixture'
        }
    }
}
