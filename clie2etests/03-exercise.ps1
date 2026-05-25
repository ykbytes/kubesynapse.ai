. "$PSScriptRoot\common.ps1"

$resourceDir = Join-Path $PSScriptRoot "resources"
$payloadPath = Join-Path $resourceDir "webhook-payload.json"

Write-Section "Profile and auth surfaces"
Invoke-Cli profile list
Invoke-Cli auth me
Invoke-Cli auth config

Write-Section "Provider and skills surfaces"
Invoke-Cli providers list
Invoke-Cli providers show github-copilot
Invoke-Cli providers models github-copilot
Invoke-Cli providers health github-copilot
Invoke-Cli skills list

Write-Section "Policy surfaces"
Invoke-Cli runs policies
Invoke-Cli runs policy-show cli-e2e-policy

Write-Section "Agent CRUD and execution surfaces"
Invoke-Cli agents list
Invoke-Cli agents show cli-e2e-agent
Invoke-Cli invoke cli-e2e-agent "Reply with exactly: hello from cli e2e"
Invoke-Cli chat send cli-e2e-agent "Reply with exactly: chat ok"
Invoke-Cli logs cli-e2e-agent --tail 50

Write-Section "Credential surfaces"
Invoke-Cli credentials git-set cli-e2e-agent --method token --token dummy-cli-e2e-token
Invoke-Cli credentials git-show cli-e2e-agent
Invoke-Cli credentials github-set cli-e2e-agent --token dummy-cli-e2e-github-token
Invoke-Cli credentials github-show cli-e2e-agent
Invoke-Cli credentials git-delete cli-e2e-agent --yes
Invoke-Cli credentials github-delete cli-e2e-agent --yes

Write-Section "Admin surfaces"
Invoke-Cli admin users
& agentctl admin user-create --username cli-e2e-viewer --password Viewer1234 --role viewer --display-name "CLI E2E Viewer" 2>$null
$userId = Get-UserIdByUsername "cli-e2e-viewer"
if ($null -ne $userId) {
    Invoke-Cli admin user-update $userId --display-name "CLI E2E Viewer Updated" --active
}
Invoke-Cli admin users

Write-Section "Workflow surfaces"
Invoke-Cli workflows list
Invoke-Cli workflows show cli-e2e-workflow
Invoke-Cli workflows trigger cli-e2e-workflow "Generate a tiny release note for the CLI e2e test"
Start-Sleep -Seconds 6
Invoke-Cli workflows status cli-e2e-workflow
Invoke-Cli workflows logs cli-e2e-workflow --tail 100

Write-Section "Approval surfaces"
$approvals = Invoke-CliJson runs approvals
if ($approvals -and $approvals.Count -gt 0) {
    $approvalName = $approvals[0].approval_name
    Invoke-Cli runs approve $approvalName --reason "CLI E2E approval"
    Start-Sleep -Seconds 6
    Invoke-Cli workflows status cli-e2e-workflow
}

Write-Section "Webhook surfaces"
Invoke-Cli webhooks list
Invoke-Cli webhooks show cli-e2e-webhook
$payload = Get-Content $payloadPath -Raw
$dispatchJson = & agentctl --output json webhooks dispatch cli-e2e-webhook --payload $payload
if ($LASTEXITCODE -ne 0) {
    throw "webhook dispatch failed"
}
$dispatch = $dispatchJson | Out-String | ConvertFrom-Json
if ($dispatch.matched_triggers -gt 0) {
    Invoke-Cli webhooks trigger-show cli-e2e-webhook
}
Invoke-Cli webhooks triggers

Write-Section "Observability and artifacts"
Invoke-Cli observatory health
Invoke-Cli observatory metrics --window 1h
Invoke-Cli observatory traces --limit 10
Invoke-Cli artifacts list --agent cli-e2e-agent
Invoke-Cli observatory export --output (Join-Path $PSScriptRoot "traces-export.json")

Write-Section "Exercise complete"
