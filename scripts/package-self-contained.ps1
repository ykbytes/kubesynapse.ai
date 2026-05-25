param(
  [string]$Registry = "ghcr.io/your-org",
    [string]$Version = "latest",
    [string]$OutputDir = "dist",
  [string]$ContainerCli = "docker",
    [switch]$Push
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outputPath = Join-Path $repoRoot $OutputDir

$images = @(
  @{ Name = "kubesynapse-operator"; Context = "operator" },
  @{ Name = "kubesynapse-opencode-rt"; Context = "opencode-runtime" },
  @{ Name = "kubesynapse-vibe-rt"; Context = "vibe-runtime" },
  @{ Name = "kubesynapse-api-gateway"; Context = "api-gateway" },
    @{ Name = "kubesynapse-web-ui"; Context = "web-ui" },
  @{ Name = "kubesynapse-pi-rt"; Context = "pi-runtime" },
  @{ Name = "litellm"; Context = "deploy/litellm"; Dockerfile = "deploy/litellm/Dockerfile" },
    @{ Name = "mcp-code-exec"; Context = "mcp-sidecars"; Dockerfile = "mcp-sidecars/code-exec/Dockerfile" },
    @{ Name = "mcp-web-search"; Context = "mcp-sidecars"; Dockerfile = "mcp-sidecars/web-search/Dockerfile" },
    @{ Name = "mcp-documents"; Context = "mcp-sidecars"; Dockerfile = "mcp-sidecars/documents/Dockerfile" },
    @{ Name = "mcp-browser"; Context = "mcp-sidecars"; Dockerfile = "mcp-sidecars/browser/Dockerfile" },
    @{ Name = "mcp-database"; Context = "mcp-sidecars"; Dockerfile = "mcp-sidecars/database/Dockerfile" },
    @{ Name = "mcp-git"; Context = "mcp-sidecars"; Dockerfile = "mcp-sidecars/git/Dockerfile" },
    @{ Name = "mcp-github-adapter"; Context = "mcp-sidecars"; Dockerfile = "mcp-sidecars/github-adapter/Dockerfile" },
    @{ Name = "mcp-kubernetes"; Context = "mcp-sidecars"; Dockerfile = "mcp-sidecars/kubernetes/Dockerfile" },
    @{ Name = "mcp-messaging"; Context = "mcp-sidecars"; Dockerfile = "mcp-sidecars/messaging/Dockerfile" },
    @{ Name = "mcp-rag"; Context = "mcp-sidecars"; Dockerfile = "mcp-sidecars/rag/Dockerfile" }
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

    $valuesPath = Join-Path $outputPath "kubesynapse-bundle-values.yaml"
    @"
# Fill in real secrets and ingress settings before deploying this bundle.
operator:
  image:
    repository: "$Registry/kubesynapse-operator"
    tag: "$Version"
  workerImage:
    repository: "$Registry/kubesynapse-operator"
    tag: "$Version"

opencodeRuntime:
  image:
    repository: "$Registry/kubesynapse-opencode-rt"
    tag: "$Version"

piRuntime:
  image:
    repository: "$Registry/kubesynapse-pi-rt"
    tag: "$Version"

mistralVibeRuntime:
  image:
    repository: "$Registry/kubesynapse-vibe-rt"
    tag: "$Version"

apiGateway:
  image:
    repository: "$Registry/kubesynapse-api-gateway"
    tag: "$Version"
  ingressHost: "agents.example.com"

webUi:
  image:
    repository: "$Registry/kubesynapse-web-ui"
    tag: "$Version"

litellm:
  image:
    repository: "$Registry/litellm"
    tag: "$Version"

mcpHub:
  servers:
    github:
      image: "$Registry/mcp-github-adapter:$Version"

mcpToolSidecars:
  codeExec:
    image: "$Registry/mcp-code-exec"
    tag: "$Version"
  webSearch:
    image: "$Registry/mcp-web-search"
    tag: "$Version"
  documents:
    image: "$Registry/mcp-documents"
    tag: "$Version"
  browser:
    image: "$Registry/mcp-browser"
    tag: "$Version"
  database:
    image: "$Registry/mcp-database"
    tag: "$Version"
  git:
    image: "$Registry/mcp-git"
    tag: "$Version"
  kubernetes:
    image: "$Registry/mcp-kubernetes"
    tag: "$Version"
  messaging:
    image: "$Registry/mcp-messaging"
    tag: "$Version"
  rag:
    image: "$Registry/mcp-rag"
    tag: "$Version"

platformSecrets:
  mode: native
  native:
    openaiApiKey: "replace-me"
    openrouterApiKey: "replace-me"
    anthropicApiKey: "replace-me"
    litellmMasterKey: "replace-me"
    apiGatewaySharedToken: "your-bearer-token-here"
"@ | Set-Content -Path $valuesPath -Encoding UTF8

    & helm lint (Join-Path $repoRoot "charts/kubesynapse") -f $valuesPath
    if ($LASTEXITCODE -ne 0) {
        throw "helm lint failed"
    }

    & helm package (Join-Path $repoRoot "charts/kubesynapse") -d $outputPath
    if ($LASTEXITCODE -ne 0) {
        throw "helm package failed"
    }

    Write-Host "Bundle ready in $outputPath"
}
finally {
    Pop-Location
}