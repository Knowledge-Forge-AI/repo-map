# Static extraction fixture only. Do not execute.
#requires -Version 7.2
using module ./Example.Module.psm1

param(
    [string]$Path = ".\data\input.json",
    [SecureString]$ApiToken
)

function Invoke-ExampleMaintenance {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string] $OutputDirectory
    )

    Import-Module Microsoft.PowerShell.Management
    . ./helpers/Example.Shared.ps1
    Get-ChildItem -Path $Path | Where-Object { $_.Length -gt 0 }
}
