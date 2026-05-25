. "$PSScriptRoot\01-setup.ps1" -StartPortForward
. "$PSScriptRoot\02-deploy.ps1"
. "$PSScriptRoot\03-exercise.ps1"

Write-Host ""
Write-Host "Run cleanup when done:" -ForegroundColor Cyan
Write-Host ".\clie2etests\04-cleanup.ps1" -ForegroundColor Yellow
