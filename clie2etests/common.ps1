$ErrorActionPreference = "Stop"

function Write-Section {
    param([string]$Title)
    ""
    "=== $Title ==="
}

function Invoke-Cli {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & agentctl @Args
    if ($LASTEXITCODE -ne 0) {
        throw "agentctl failed: $($Args -join ' ')"
    }
}

function Invoke-CliJson {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    $output = & agentctl --output json @Args
    if ($LASTEXITCODE -ne 0) {
        throw "agentctl failed: $($Args -join ' ')"
    }
    if (-not $output) {
        return $null
    }
    return ($output | Out-String | ConvertFrom-Json)
}

function Ensure-PortForward {
    param(
        [string]$Context = "kind-kubesynapse-dev",
        [string]$Namespace = "kubesynapse",
        [string]$Service = "kubesynapse-api-gateway",
        [int]$LocalPort = 8080,
        [int]$RemotePort = 8080
    )

    try {
        $health = Invoke-WebRequest -Uri "http://localhost:$LocalPort/api/health" -UseBasicParsing -TimeoutSec 3
        if ($health.StatusCode -eq 200) {
            return
        }
    }
    catch {
    }

    Start-Process -WindowStyle Hidden -FilePath "kubectl" -ArgumentList @(
        "port-forward",
        "--namespace", $Namespace,
        "service/$Service",
        "${LocalPort}:${RemotePort}",
        "--context", $Context
    )
    Start-Sleep -Seconds 4

    $health = Invoke-WebRequest -Uri "http://localhost:$LocalPort/api/health" -UseBasicParsing -TimeoutSec 10
    if ($health.StatusCode -ne 200) {
        throw "Gateway port-forward did not become healthy on localhost:$LocalPort"
    }
}

function Get-UserIdByUsername {
    param([string]$Username)
    $users = Invoke-CliJson admin users
    foreach ($user in $users) {
        if ($user.username -eq $Username) {
            return [int]$user.id
        }
    }
    return $null
}
