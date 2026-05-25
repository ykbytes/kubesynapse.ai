<#
.SYNOPSIS
  Deploy the GDPR Compliance Auditor demo.
#>
param(
    [string]$Namespace = "default",
    [string]$Context = "",
    [int]$WaitTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$kctx = if ($Context) { @("--context", $Context) } else { @() }

Write-Host "=== GDPR Compliance Auditor — Deploy ===" -ForegroundColor Cyan

$files = @("project-context.yaml", "agents.yaml", "policy.yaml", "workflow.yaml")
foreach ($f in $files) {
    if (-not (Test-Path $f)) { Write-Error "Missing: $f"; exit 1 }
}

Write-Host "[1/4] Applying project context..." -ForegroundColor Yellow
kubectl apply -f project-context.yaml -n $Namespace @kctx

Write-Host "[2/4] Applying agents (gdpr-scanner, gdpr-classifier, gdpr-report-writer)..." -ForegroundColor Yellow
kubectl apply -f agents.yaml -n $Namespace @kctx

Write-Host "[3/4] Applying policy..." -ForegroundColor Yellow
kubectl apply -f policy.yaml -n $Namespace @kctx

Write-Host "[4/4] Applying workflow..." -ForegroundColor Yellow
kubectl apply -f workflow.yaml -n $Namespace @kctx

$agents = @("gdpr-scanner", "gdpr-classifier", "gdpr-report-writer")
foreach ($agent in $agents) {
    Write-Host "Waiting for $agent sandbox..." -ForegroundColor Yellow
    $deadline = (Get-Date).AddSeconds($WaitTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $pod = kubectl get pods -n $Namespace -l "agent-name=$agent" -o json 2>$null @kctx | ConvertFrom-Json
        if ($pod.items.Count -gt 0 -and $pod.items[0].status.phase -eq "Running") {
            Write-Host "  $agent is Running" -ForegroundColor Green
            break
        }
        Start-Sleep -Seconds 5
    }
}

Write-Host ""
Write-Host "=== Deploy Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Trigger the audit:" -ForegroundColor Cyan
Write-Host "  agentctl workflows trigger gdpr-compliance-audit"
Write-Host ""
Write-Host "Find the report at:" -ForegroundColor Cyan
Write-Host "  Web UI > Agents > gdpr-report-writer > Workspace Files > compliance-report.md"
