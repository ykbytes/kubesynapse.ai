. "$PSScriptRoot\common.ps1"

$resourceDir = Join-Path $PSScriptRoot "resources"

Write-Section "Applying policy"
Invoke-Cli apply (Join-Path $resourceDir "cli-e2e-policy.yaml")

Write-Section "Applying agents"
Invoke-Cli apply (Join-Path $resourceDir "cli-e2e-agent.yaml")
Invoke-Cli apply (Join-Path $resourceDir "cli-e2e-reviewer.yaml")

Write-Section "Applying workflow"
Invoke-Cli apply (Join-Path $resourceDir "cli-e2e-workflow.yaml")

Write-Section "Creating webhook"
& agentctl webhooks delete cli-e2e-webhook --yes 2>$null
Invoke-Cli webhooks create cli-e2e-webhook --workflow cli-e2e-workflow --event custom --secret cli-e2e-secret

Write-Section "Deployment summary"
Invoke-Cli runs policies
Invoke-Cli agents list
Invoke-Cli workflows list
Invoke-Cli webhooks list
