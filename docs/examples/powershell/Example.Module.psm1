# Static extraction example only. Do not execute.
# This module contains fake public-safe command shapes for RepoMap fixtures.

function Get-ExampleReport {
    [CmdletBinding()]
    param(
        [string]$Path = ".\reports",
        [string]$ApiKey = "EXAMPLE_FAKE_KEY"
    )

    Get-ChildItem -Path $Path -Filter "*.json" |
        ConvertFrom-Json |
        Select-Object -Property Name, Status
}

function Set-ExampleServiceState {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [string]$Name = "ExampleService",
        [switch]$Enabled
    )

    if ($Enabled) {
        Set-Service -Name $Name -StartupType Automatic
        Start-Service -Name $Name
    } else {
        Set-Service -Name $Name -StartupType Disabled
    }
}

function Register-ExampleTask {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [string]$TaskName = "ExampleStaticFixture"
    )

    Register-ScheduledTask -TaskName $TaskName -Action "ExampleAction" -Trigger "ExampleTrigger"
}

Export-ModuleMember -Function Get-ExampleReport, Set-ExampleServiceState, Register-ExampleTask
