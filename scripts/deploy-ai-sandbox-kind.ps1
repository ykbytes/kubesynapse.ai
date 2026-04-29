param(
    [string]$ReleaseName = "ai-sandbox",
    [string]$Namespace = "ai-agent-sandbox",
    [string]$ValuesFile = "deploy/values.ai-sandbox.kind-local.yaml",
    [string[]]$ExtraValuesFiles = @(),
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

try {
    $helmArgs = @(
        "upgrade",
        $ReleaseName,
        "./charts/kubesynapse",
        "-n",
        $Namespace,
        "--reuse-values",
        "--server-side=true",
        "--force-conflicts",
        "-f",
        $ValuesFile
    )

    foreach ($extraValuesFile in $ExtraValuesFiles) {
        if ([string]::IsNullOrWhiteSpace($extraValuesFile)) {
            continue
        }

        $helmArgs += @("-f", $extraValuesFile)
    }

    $skillsCatalogFile = Join-Path $repoRoot "catalog/skills-catalog.json"
    if (Test-Path $skillsCatalogFile) {
        $helmArgs += @("--set-file", "skillsCatalog.catalogJson=./catalog/skills-catalog.json")
    }

    if ($DryRun) {
        $helmArgs += "--dry-run"
    }

    & helm @helmArgs
    if ($LASTEXITCODE -ne 0) {
        throw "helm upgrade failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}