# Static extraction example only. Do not execute.
# This file contains fake public-safe command shapes for RepoMap fixtures.

#requires -Version 7.0
using module ./Example.Shared.psm1

param(
    [string]$InputPath = ".\data\input.json",
    [SecureString]$ApiToken,
    [string]$DynamicCommand = "Write-Output"
)

function Invoke-ExampleMaintenance {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [string]$OutputDirectory = ".\out",
        [string]$RegistryPath = "HKCU:\Software\ExampleVendor\ExampleApp"
    )

    Import-Module Microsoft.PowerShell.Management
    . "$PSScriptRoot\Example.Shared.ps1"

    $homePath = $env:USERPROFILE
    $env:EXAMPLE_MODE = "static-fixture"
    $headers = @{
        Authorization = "Bearer EXAMPLE_REDACT_ME"
    }

    gci -Path $InputPath |
        Where-Object { $_.Length -gt 0 } |
        ForEach-Object {
            Set-Content -Path (Join-Path $OutputDirectory "$($_.BaseName).txt") -Value "example"
        }

    Set-ItemProperty -Path $RegistryPath -Name Enabled -Value 1
    Invoke-WebRequest -Uri "https://example.invalid/api/status" -Headers $headers
    Invoke-Command -ComputerName "example-host.invalid" -ScriptBlock { Get-Service }

    $splat = @{
        Path = $OutputDirectory
        ItemType = "Directory"
    }
    New-Item @splat

    & $DynamicCommand "dynamic command placeholder"
}

function Invoke-ExampleExternalTools {
    git status --short
    winget install Example.Package
    docker compose ps
}
