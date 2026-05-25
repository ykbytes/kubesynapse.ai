. "$PSScriptRoot\common.ps1"

Write-Section "Deleting webhook"
& agentctl webhooks delete cli-e2e-webhook --yes 2>$null

Write-Section "Deleting workflow"
& agentctl workflows delete cli-e2e-workflow --yes 2>$null

Write-Section "Deleting agents"
& agentctl agents delete cli-e2e-agent --yes 2>$null
& agentctl agents delete cli-e2e-reviewer --yes 2>$null

Write-Section "Deleting policy"
& agentctl runs policy-delete cli-e2e-policy --yes 2>$null

Write-Section "Deleting temp user"
$userId = Get-UserIdByUsername "cli-e2e-viewer"
if ($null -ne $userId) {
    & agentctl admin user-delete $userId --yes 2>$null
}

Write-Section "Cleanup complete"
