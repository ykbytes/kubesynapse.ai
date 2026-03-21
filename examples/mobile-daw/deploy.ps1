# deploy.ps1 — Deploy BeatForge Mobile DAW workflow to Minikube
# Usage: .\deploy.ps1

$ErrorActionPreference = "Stop"
$ns = "default"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=== Deploying BeatForge Mobile DAW (v2 — 3-step workflow) ===" -ForegroundColor Cyan

# 0. Clean up any existing resources
Write-Host "`n[0/3] Cleaning up old resources..." -ForegroundColor Yellow
kubectl delete agentworkflow mobile-daw -n $ns 2>$null
kubectl delete aiagent daw-agent -n $ns 2>$null
Start-Sleep -Seconds 5

# 1. Apply project context ConfigMap
Write-Host "`n[1/3] Applying project context..." -ForegroundColor Yellow
kubectl apply -f "$dir\project-context.yaml" -n $ns

# 2. Apply AIAgent
Write-Host "`n[2/3] Applying DAW agent..." -ForegroundColor Yellow
kubectl apply -f "$dir\daw-agent.yaml" -n $ns

# Wait for agent pod to be created
Write-Host "  Waiting for agent pod to appear..." -ForegroundColor Gray
$attempts = 0
do {
    Start-Sleep -Seconds 3
    $pod = kubectl get pods -n $ns -l agent-name=daw-agent --no-headers 2>$null
    $attempts++
} while (-not $pod -and $attempts -lt 20)

if ($pod) {
    Write-Host "  Pod found: $($pod.Split()[0])" -ForegroundColor Green
    Write-Host "  Waiting for pod readiness (up to 120s)..." -ForegroundColor Gray
    kubectl wait --for=condition=ready pod -l agent-name=daw-agent -n $ns --timeout=120s
} else {
    Write-Host "  WARNING: Agent pod not found after 60s, proceeding anyway..." -ForegroundColor Red
}

# 3. Apply workflow (starts execution immediately)
Write-Host "`n[3/3] Applying workflow (starts 3-step execution)..." -ForegroundColor Yellow
kubectl apply -f "$dir\workflow.yaml" -n $ns

Write-Host "`n=== Deployment complete ===" -ForegroundColor Green
Write-Host "Steps: foundation (5 turns) -> implement (8 turns) -> polish (5 turns)" -ForegroundColor Cyan
Write-Host "Monitor at: http://localhost:3000" -ForegroundColor Cyan
Write-Host "API at:     http://localhost:8080" -ForegroundColor Cyan
Write-Host "`nUseful commands:" -ForegroundColor Gray
Write-Host "  kubectl get agentworkflow mobile-daw -n $ns -w"
Write-Host "  kubectl logs -f -l agent-name=daw-agent -n $ns"
