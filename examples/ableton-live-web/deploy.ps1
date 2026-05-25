param(
    [string]$Namespace = "default",
    [switch]$TriggerWorkflow,
    [int]$ReadyTimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"

function Invoke-Kubectl {
    param([string[]]$Args)
    Write-Host "kubectl $($Args -join ' ')"
    & kubectl @Args
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl command failed: kubectl $($Args -join ' ')"
    }
}

$files = @(
    "project-context.yaml",
    "daw-agent.yaml",
    "workflow.yaml"
)

Push-Location $PSScriptRoot
try {
    foreach ($file in $files) {
        Invoke-Kubectl -Args @("-n", $Namespace, "apply", "-f", $file)
    }

    Invoke-Kubectl -Args @(
        "-n", $Namespace,
        "wait",
        "--for=condition=ready",
        "pod",
        "-l",
        "app=ai-agent",
        "--timeout=$($ReadyTimeoutSeconds)s"
    )

    if ($TriggerWorkflow) {
        Invoke-Kubectl -Args @(
            "-n", $Namespace,
            "annotate",
            "agentworkflow",
            "ableton-live-web",
            "kubesynapse.ai/trigger=$(Get-Date -Format o)",
            "--overwrite"
        )
    }

    Write-Host "Deployment complete."
    Write-Host "Check status with: kubectl -n $Namespace get agentworkflows ableton-live-web -o yaml"
} finally {
    Pop-Location
}
