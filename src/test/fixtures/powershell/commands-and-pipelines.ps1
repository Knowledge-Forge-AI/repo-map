# Static extraction fixture only. Do not execute.

function Invoke-CommandFixture {
    [CmdletBinding()]
    param(
        [string] $Path,
        [string] $ApiToken
    )

    # Get-ChildItem -Path ./comment-should-not-be-extracted
    $Message = "Remove-Item should not be extracted from strings"
    $OnlyAssignment = "Copy-Item ./source ./dest"
    $Headers = @{ Authorization = "Bearer FAKE_PIPELINE_SECRET" }
    $Params = @{ Path = $Path; Filter = "*.json" }

    Get-ChildItem -Path $Path -Filter "*.json" -Force |
        Where-Object { $_.Length -gt 0 } |
        ForEach-Object { Write-Output $_.Name }

    gci @Params
    cat ./README.md
    Invoke-RestMethod -Uri "https://example.invalid/api" -Headers @{ Authorization = "Bearer FAKE_INLINE_SECRET" } -ApiKey "FAKE_ARG_SECRET"

    git status --short
    docker compose ps
    kubectl get pods
    terraform plan
    winget install Example.Package
    choco install example
    scoop install example
    npm test
    python -m pytest
    pwsh -NoProfile -File ./script.ps1

    & $Command
}
