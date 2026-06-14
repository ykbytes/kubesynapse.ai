param(
    [string]$ProfileName = "kind",
    [string]$Gateway = "http://localhost:8080",
    [string]$Namespace = "default",
    [string]$Username = "admin",
    [string]$Password = "YourAdminPasswordHere",
    [switch]$StartPortForward
)

. "$PSScriptRoot\common.ps1"

Write-Section "CLI E2E Setup"

if ($StartPortForward) {
    Write-Section "Ensuring port-forward"
    Ensure-PortForward
}

Write-Section "Configuring profile"
& agentctl profile update $ProfileName --gateway $Gateway --namespace $Namespace 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Cli profile create $ProfileName --gateway $Gateway --namespace $Namespace
}
Invoke-Cli profile use $ProfileName

Write-Section "Logging in"
Invoke-Cli auth login --username $Username --password $Password

Write-Section "Health checks"
Invoke-Cli health
Invoke-Cli auth me
Invoke-Cli auth config

Write-Section "Setup complete"
