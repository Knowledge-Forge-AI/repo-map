@{
    RootModule = 'Example.Module.psm1'
    ModuleVersion = '0.1.0'
    GUID = '11111111-2222-3333-4444-555555555555'
    RequiredModules = @(
        'Microsoft.PowerShell.Management'
    )
    FunctionsToExport = @(
        'Get-ExampleReport',
        'Invoke-ScopedThing'
    )
    PrivateData = @{
        PSData = @{
            Tags = @('repomap', 'static-fixture')
        }
    }
}
