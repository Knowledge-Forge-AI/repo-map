# Static extraction fixture only. Do not execute.
param(
    [string]$ApiToken = "FAKE_TOKEN_VALUE"
)

$Authorization = "Bearer EXAMPLE_SHOULD_NOT_LEAK"
$PatValue = "fake-pat-value"
$helper = Join-Path $PSScriptRoot "dynamic.ps1"
$Command = "Write-Output"
$ScriptText = "Write-Output dynamic"

. $helper
& $Command "dynamic call"
Invoke-Expression $ScriptText
