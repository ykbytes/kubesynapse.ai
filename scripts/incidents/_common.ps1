# Shared helpers for KubeSynapse incident scripts (PowerShell).
# Source this file via:  . (Join-Path $PSScriptRoot "_common.ps1")
#
# Provides: Resolve-KubeSynapseContext, info, ok, warn, err
# Returns a hashtable with: Token, GatewayUrl

function info { param([string]$Message) Write-Host "[INFO] $Message" -ForegroundColor Blue }
function ok   { param([string]$Message) Write-Host "[OK]   $Message" -ForegroundColor Green }
function warn { param([string]$Message) Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function err  { param([string]$Message) Write-Host "[ERROR] $Message" -ForegroundColor Red }

function Resolve-KubeSynapseContext {
  param([int]$Port = 8080)

  $GatewayUrl = $env:KUBESYNAPSE_GATEWAY_URL
  $OwnPf = $false

  if (-not $GatewayUrl) {
    $Existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $Existing) {
      info "No listener on port $Port — starting port-forward to kubesynapse-api-gateway..."
      Start-Process -NoNewWindow -FilePath kubectl -ArgumentList @(
        "port-forward","-n","kubesynapse","svc/kubesynapse-api-gateway","${Port}:8080"
      ) | Out-Null
      $OwnPf = $true
      Start-Sleep -Seconds 4
    }
    $GatewayUrl = "http://127.0.0.1:${Port}"
  }

  $Token = $env:KUBESYNAPSE_API_TOKEN
  if (-not $Token) {
    try {
      $SecretJson = kubectl get secret kubesynapse-llm-api-keys -n kubesynapse -o json --ignore-not-found
      if ($SecretJson) {
        $SecretObj = $SecretJson | ConvertFrom-Json
        $Encoded = $SecretObj.data.API_GATEWAY_SHARED_TOKEN
        if ($Encoded) {
          $Token = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Encoded))
          ok "Loaded gateway token from kubesynapse-llm-api-keys"
        }
      }
    } catch {}
  }
  if (-not $Token) {
    $SharedTokenSecret = kubectl get secret kubesynapse-shared-auth -n kubesynapse -o json --ignore-not-found
    if ($SharedTokenSecret) {
      $Obj = $SharedTokenSecret | ConvertFrom-Json
      $Enc = $Obj.data.token
      if ($Enc) { $Token = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Enc)) }
    }
  }
  if (-not $Token) {
    throw "Could not resolve KUBESYNAPSE_API_TOKEN. Set the env var or install the platform with a shared token secret."
  }

  return @{ Token = $Token; GatewayUrl = $GatewayUrl; OwnPortForward = $OwnPf }
}

