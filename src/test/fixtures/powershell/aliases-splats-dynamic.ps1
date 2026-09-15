# Static extraction fixture only. Do not execute.
Set-Alias -Name ll -Value Get-ChildItem
New-Alias k kubectl

$Params = @{
    Path = './data'
    Filter = '*.json'
    Force = $true
    ApiToken = 'FAKE_SPLAT_TOKEN'
    Count = 3
    DynamicPath = $InputPath
}

ll @Params
echo 'hello from alias'
curl -Uri 'https://example.invalid/ping'
wget 'https://example.invalid/file'
mkdir './generated'
rmdir './old'

& $Command
& "git" status
& './scripts/run.ps1'
Invoke-Expression $ScriptText
. $DynamicPath

<#
Remove-Item './block-comment.txt'
curl 'https://example.invalid/comment'
#>

$Text = "Remove-Item './string-only.txt'"
$OtherText = 'Set-ItemProperty HKCU:\Software\StringOnly -Name Enabled -Value 1'

$Map = @{
    curl = 'https://example.invalid/not-a-command'
    Remove-Item = './hashtable-entry.txt'
}

$Here = @"
Remove-Item './here-string.txt'
curl 'https://example.invalid/here'
"@

$LiteralHere = @'
Set-Content './literal-here.txt' -Value 'nope'
'@
