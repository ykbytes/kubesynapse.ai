param(
  [string]$Registry = "ghcr.io/your-org",
    [string]$Version = "latest",
    [string]$OutputDir = "dist",
  [string]$ContainerCli = "podman",
    [switch]$Push
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outputPath = Join-Path $repoRoot $OutputDir

$images = @(
    @{ Name = "ai-operator"; Context = "operator" },
    @{ Name = "ai-agent-runtime"; Context = "agent-runtime" },
  @{ Name = "ai-goose-runtime"; Context = "goose-runtime" },
    @{ Name = "ai-opencode-runtime"; Context = "opencode-runtime" },
    @{ Name = "ai-api-gateway"; Context = "api-gateway" },
    @{ Name = "ai-agent-sandbox-web-ui"; Context = "web-ui" },
    @{ Name = "mcp-github-adapter"; Context = "mcp-sidecars"; Dockerfile = "mcp-sidecars/github-adapter/Dockerfile" }
)

New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

Push-Location $repoRoot
try {
    foreach ($image in $images) {
        $tag = "$Registry/$($image.Name):$Version"
    $buildArgs = @("build")
    if ($ContainerCli -eq "podman") {
      $buildArgs += @("--format", "docker")
    }
    if ($image.ContainsKey("Dockerfile")) {
      $buildArgs += @("-f", (Join-Path $repoRoot $image.Dockerfile))
    }
    $buildArgs += @("-t", $tag, (Join-Path $repoRoot $image.Context))
        Write-Host "Building $tag from $($image.Context)"
    & $ContainerCli @buildArgs
        if ($LASTEXITCODE -ne 0) {
      throw "$ContainerCli build failed for $tag"
        }

        if ($Push) {
            Write-Host "Pushing $tag"
      & $ContainerCli push $tag
            if ($LASTEXITCODE -ne 0) {
        throw "$ContainerCli push failed for $tag"
            }
        }
    }

    $valuesPath = Join-Path $outputPath "ai-agent-sandbox-bundle-values.yaml"
    @"
# Fill in real secrets and ingress settings before deploying this bundle.
operator:
  image:
    repository: "$Registry/ai-operator"
    tag: "$Version"
  workerImage:
    repository: "$Registry/ai-operator"
    tag: "$Version"

agentRuntime:
  image:
    repository: "$Registry/ai-agent-runtime"
    tag: "$Version"

gooseRuntime:
  image:
    repository: "$Registry/ai-goose-runtime"
    tag: "$Version"

opencodeRuntime:
  image:
    repository: "$Registry/ai-opencode-runtime"
    tag: "$Version"

apiGateway:
  image:
    repository: "$Registry/ai-api-gateway"
    tag: "$Version"
  ingressHost: "agents.example.com"

webUi:
  image:
    repository: "$Registry/ai-agent-sandbox-web-ui"
    tag: "$Version"

mcpHub:
  servers:
    github:
      image: "$Registry/mcp-github-adapter:$Version"

platformSecrets:
  mode: native
  native:
    openaiApiKey: "replace-me"
    openrouterApiKey: "replace-me"
    anthropicApiKey: "replace-me"
    litellmMasterKey: "replace-me"
    apiGatewaySharedToken: "replace-me-with-a-long-random-bearer-token"
"@ | Set-Content -Path $valuesPath -Encoding UTF8

    & helm lint (Join-Path $repoRoot "charts/ai-agent-sandbox") -f $valuesPath
    if ($LASTEXITCODE -ne 0) {
        throw "helm lint failed"
    }

    & helm package (Join-Path $repoRoot "charts/ai-agent-sandbox") -d $outputPath
    if ($LASTEXITCODE -ne 0) {
        throw "helm package failed"
    }

    Write-Host "Bundle ready in $outputPath"
}
finally {
    Pop-Location
}