# build-mcp-images.ps1 — Windows wrapper for scripts/build-mcp-images.sh
#
# This script delegates to the WSL bash implementation, which stages the
# mcp-sidecars directory under /tmp to avoid OneDrive xattr/permission
# issues during Docker builds.
#
# Usage:
#   .\scripts\build-mcp-images.ps1
#   $env:REGISTRY="quay.io/yakdhane"; $env:PUSH="1"; .\scripts\build-mcp-images.ps1
#   $env:SERVERS="code-exec git database"; .\scripts\build-mcp-images.ps1

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$bashScript = (Join-Path $repoRoot "scripts/build-mcp-images.sh").Replace("\", "/")

$parts = @()
if ($env:REGISTRY) { $parts += "REGISTRY=$($env:REGISTRY)" }
if ($env:PUSH) { $parts += "PUSH=$($env:PUSH)" }
if ($env:SERVERS) { $parts += "SERVERS=$($env:SERVERS)" }
if ($env:PLATFORMS) { $parts += "PLATFORMS=$($env:PLATFORMS)" }
if ($env:STAGE_DIR) { $parts += "STAGE_DIR=$($env:STAGE_DIR)" }
$parts += "bash `"$bashScript`""

$command = $parts -join " "
Write-Host "Delegating to WSL: wsl -c `"$command`""
& wsl -c $command
if ($LASTEXITCODE -ne 0) {
    throw "build-mcp-images.sh failed with exit code $LASTEXITCODE"
}
