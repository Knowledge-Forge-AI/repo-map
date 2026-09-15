# Static extraction fixture only. Do not execute.
using module ./Example.Shared.psm1

function Get-ExampleReport {
    [CmdletBinding()]
    param(
        [string]$Path = ".\reports"
    )

    Get-ChildItem -Path $Path -Filter "*.json"
}

function script:Invoke-ScopedThing {
    param([string]$Name)
    Write-Output $Name
}

Export-ModuleMember -Function Get-ExampleReport, Invoke-ScopedThing
