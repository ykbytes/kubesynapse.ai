$ErrorActionPreference = "Stop"

if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

$ns = "default"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path

$manifestFiles = @(
    "project-context.yaml",
    "policy.yaml",
    "agent.yaml",
    "workflow.yaml"
)

$activeAgents = @(
    "ai300-researcher",
    "ai300-exam-writer",
    "ai300-qa-reviewer"
)

$obsoleteAgents = @(
    "ai300-exam-agent"
)

function Assert-LastExitCode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$CommandName failed with exit code $LASTEXITCODE"
    }
}

function Wait-ForStatefulSet {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    kubectl rollout status "statefulset/$Name" -n $ns --timeout=180s | Out-Host
    Assert-LastExitCode "kubectl rollout status statefulset/$Name"
}

function Wait-ForStatefulSetDeletion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $exists = kubectl get "statefulset/$Name" -n $ns --ignore-not-found -o name
    Assert-LastExitCode "kubectl get statefulset/$Name"
    if ($exists) {
        kubectl wait --for=delete "statefulset/$Name" -n $ns --timeout=180s | Out-Host
        Assert-LastExitCode "kubectl wait --for=delete statefulset/$Name"
    }
}

Write-Host "=== Deploying AI-300 Exam Generator ===" -ForegroundColor Cyan

Write-Host "`n[1/5] Removing obsolete agents..." -ForegroundColor Yellow
foreach ($agent in $obsoleteAgents) {
    kubectl delete aiagent $agent -n $ns --ignore-not-found | Out-Host
    Assert-LastExitCode "kubectl delete aiagent $agent"
    Wait-ForStatefulSetDeletion -Name "${agent}-sandbox"
}

Write-Host "`n[2/5] Validating manifests..." -ForegroundColor Yellow
foreach ($file in $manifestFiles) {
    kubectl apply --dry-run=server -f (Join-Path $dir $file) -n $ns | Out-Host
    Assert-LastExitCode "kubectl apply --dry-run=server -f $file"
}

Write-Host "`n[3/5] Applying context, policy, agents, and workflow..." -ForegroundColor Yellow
foreach ($file in $manifestFiles) {
    kubectl apply -f (Join-Path $dir $file) -n $ns | Out-Host
    Assert-LastExitCode "kubectl apply -f $file"
}

Write-Host "`n[4/5] Waiting for active sandboxes..." -ForegroundColor Yellow
foreach ($agent in $activeAgents) {
    Wait-ForStatefulSet -Name "${agent}-sandbox"
}

Write-Host "`n[5/5] Verifying live resources..." -ForegroundColor Yellow
kubectl get aiagent -n $ns | Out-Host
Assert-LastExitCode "kubectl get aiagent"
kubectl get agentworkflow ai300-exam-generation -n $ns | Out-Host
Assert-LastExitCode "kubectl get agentworkflow ai300-exam-generation"

foreach ($agent in $activeAgents) {
    kubectl get aiagent $agent -n $ns | Out-Host
    Assert-LastExitCode "kubectl get aiagent $agent"
}

foreach ($agent in $obsoleteAgents) {
    $remaining = kubectl get aiagent $agent -n $ns --ignore-not-found -o name
    Assert-LastExitCode "kubectl get aiagent $agent"
    if ($remaining) {
        throw "Obsolete agent still present: $agent"
    }
}

Write-Host "`nAI-300 Exam Generator deployed." -ForegroundColor Green
Write-Host "Workflow: ai300-exam-generation" -ForegroundColor Cyan
Write-Host "Agents:   ai300-researcher, ai300-exam-writer, ai300-qa-reviewer" -ForegroundColor Cyan
Write-Host "Trigger:  POST /workflows/ai300-exam-generation/trigger via API gateway" -ForegroundColor Cyan
