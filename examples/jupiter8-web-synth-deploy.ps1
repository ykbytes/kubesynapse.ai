param(
    [string]$Namespace = "default",
    [int]$ReadyTimeoutSeconds = 240
)

$ErrorActionPreference = "Stop"
$bundle = Join-Path $PSScriptRoot "jupiter8-web-synth-bundle.yaml"

function Invoke-Kubectl {
    param([string[]]$Args)
    Write-Host "kubectl $($Args -join ' ')"
    & kubectl @Args
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl command failed: kubectl $($Args -join ' ')"
    }
}

Write-Host "=== Deploying Jupiter-8 Web Synth bundle ===" -ForegroundColor Cyan

Write-Host "[0/3] Removing previous workflow run (if any)..." -ForegroundColor Yellow
& kubectl -n $Namespace delete agentworkflow jupiter8-web-synth --ignore-not-found | Out-Null

Write-Host "[1/3] Applying bundle..." -ForegroundColor Yellow
Invoke-Kubectl -Args @("-n", $Namespace, "apply", "-f", $bundle)

Write-Host "[2/3] Waiting for agent pods..." -ForegroundColor Yellow
Invoke-Kubectl -Args @(
    "-n", $Namespace,
    "wait",
    "--for=condition=ready",
    "pod",
    "-l",
    "agent-name in (j8-web-architect,j8-web-builder)",
    "--timeout=$($ReadyTimeoutSeconds)s"
)

Write-Host "[3/3] Workflow submitted." -ForegroundColor Yellow
Write-Host "Monitor with:" -ForegroundColor Gray
Write-Host "  kubectl -n $Namespace get agentworkflow jupiter8-web-synth -w"
Write-Host "  kubectl -n $Namespace logs -f -l agent-name=j8-web-builder"
