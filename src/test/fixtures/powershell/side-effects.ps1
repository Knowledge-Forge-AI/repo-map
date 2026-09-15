# Static extraction fixture only. Do not execute.

function Invoke-SideEffectFixture {
    [CmdletBinding()]
    param(
        [string] $DynamicPath,
        [string] $ComputerName,
        [string] $Password
    )

    # Remove-Item -Path ./comment-only.txt
    $Message = "Set-ItemProperty -Path HKCU:\Software\StringOnly -Name Enabled -Value 1"

    $env:EXAMPLE_HOME
    $env:EXAMPLE_TOKEN = "FAKE_ENV_TOKEN"

    Get-Content -Path ./input.txt
    Get-ChildItem -Path ./logs
    Test-Path ./maybe.txt
    Set-Content -Path ./output.txt -Value "ok"
    Add-Content -Path ./output.txt -Value "more"
    New-Item -Path ./generated -ItemType Directory
    Remove-Item -Path ./old.txt
    Remove-Item -Path $DynamicPath
    Copy-Item -Path ./input.txt -Destination ./copy.txt
    Move-Item -Path $DynamicPath -Destination ./moved.txt

    Get-ItemProperty -Path HKCU:\Software\Example
    Set-ItemProperty -Path HKCU:\Software\Example -Name Enabled -Value 1
    New-ItemProperty -Path Registry::HKEY_CURRENT_USER\Software\Example -Name Enabled -Value 1
    Remove-ItemProperty -Path HKCU:\Software\Example -Name Enabled

    Set-Item Env:EXAMPLE_FLAG enabled

    Invoke-WebRequest -Uri "https://example.invalid/download" -OutFile ./download.txt -Headers @{ Authorization = "Bearer FAKE_NET_TOKEN" }
    Invoke-RestMethod -Uri "https://api.example.invalid/items" -Method Post -ApiKey "FAKE_API_KEY"
    Start-BitsTransfer -Source "https://example.invalid/file.zip" -Destination ./file.zip

    Invoke-Command -ComputerName "example-host" -ScriptBlock { Get-Date }
    Enter-PSSession -ComputerName $ComputerName
    New-PSSession -ComputerName "session-host"

    Start-Process -FilePath "notepad.exe" -ArgumentList "./fake.txt"
    Stop-Process -Name "ExampleProc"
    Start-Service -Name "ExampleService"
    Stop-Service -Name "ExampleService"
    Set-Service -Name "ExampleService" -StartupType Manual
    New-Service -Name "ExampleService2" -BinaryPathName "./service.exe"
    Register-ScheduledTask -TaskName "ExampleTask" -Action $Action
    Unregister-ScheduledTask -TaskName "ExampleTask" -Confirm:$false

    Install-Module -Name Example.Module
    Update-Module -Name Example.Module
    Uninstall-Module -Name Example.Module
    Install-Package -Name Example.Package
    Uninstall-Package -Name Example.Package
    winget install Example.Package
    choco upgrade example-tool
    scoop uninstall example-tool

    Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
    Set-AuthenticodeSignature -FilePath ./script.ps1 -Certificate $Certificate

    Get-Credential -UserName "example-user"
    ConvertTo-SecureString "FAKE_PASSWORD" -AsPlainText -Force
    New-Object System.Management.Automation.PSCredential ("example-user", $Password)

    & $Command
}
