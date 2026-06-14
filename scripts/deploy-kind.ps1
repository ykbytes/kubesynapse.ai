<#
.SYNOPSIS
  Build, load, and install KubeSynapse on a local kind cluster.

.DESCRIPTION
  Single entry point for a first-time local install. This script:

    1. Verifies required tools (docker, kind, helm, kubectl).
    2. Creates or reuses a kind cluster (default: kubesynapse-dev).
    3. Builds the five platform images + the pinned LiteLLM image.
    4. Loads them into the kind node.
    5. Reconciles the persisted PostgreSQL password on upgrade.
    6. Removes the immutable opencode/pi runtime ConfigMaps so Helm
       can replace them with the freshly generated values.
    7. Installs (or upgrades) the kubesynapse Helm release with the
       same overlays the docs recommend (local images + Kind quickstart
       overlay) and a fresh set of required secrets.
    8. Restarts the three core deployments so the new image content
       is picked up, then waits for them to roll out.
    9. Prints a final access summary: cluster, port-forward commands,
       admin URL, and the generated password (or, if you supplied one,
       the password you used).

  Every step exits non-zero with a clear message on failure, so a CI
  job (or a copy/paste in a terminal) can tell exactly where things
  broke. Use -WhatIf to print the actions it would take without
  actually running them.
#>
[CmdletBinding()]
param(
  [string]$ClusterName = "kubesynapse-dev",
  [string]$Namespace = "kubesynapse",
  [string]$ReleaseName = "kubesynapse",
  [string]$AdminUsername = "admin",
  [string]$AdminPassword = "",
  [string]$SharedToken = "",
  [string]$DatabasePassword = "",
  [string]$JwtSecret = "",
  [string]$LiteLlmMasterKey = "",
  [string]$ContainerCli = "docker",
  [int]$HelmTimeoutMinutes = 20,
  [int]$RolloutTimeoutMinutes = 10,
  [switch]$RecreateCluster,
  [switch]$SkipBuild,
  [switch]$SkipLoad,
  [switch]$SkipRestart,
  [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$clusterContext = "kind-$ClusterName"
$chartPath = (Join-Path $repoRoot "charts/kubesynapse") -replace "\\", "/"
$localImagesValuesPath = (Join-Path $repoRoot "deploy/values.local-images.example.yaml") -replace "\\", "/"
$kindQuickstartValuesPath = (Join-Path $repoRoot "deploy/values.kind.quickstart.yaml") -replace "\\", "/"
$skillsCatalogPath = (Join-Path $repoRoot "catalog/skills-catalog.json") -replace "\\", "/"
$installLogPath = Join-Path $env:TEMP "kubesynapse-install.log"
$useWhatIf = [bool]$WhatIf

function New-RandomSuffix {
  param([int]$Length = 32)

  $chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
  $builder = New-Object System.Text.StringBuilder
  for ($index = 0; $index -lt $Length; $index++) {
    [void]$builder.Append($chars[(Get-Random -Maximum $chars.Length)])
  }
  $builder.ToString()
}

function Ensure-SecretValue {
  param(
    [string]$CurrentValue,
    [string]$Prefix,
    [int]$RandomLength = 32
  )

  if ($CurrentValue) {
    return $CurrentValue
  }

  return "$Prefix$(New-RandomSuffix -Length $RandomLength)"
}

function Write-Banner {
  param([string]$Title, [string]$Color = "Cyan")

  Write-Host ""
  Write-Host ("=" * 78) -ForegroundColor $Color
  Write-Host ("  " + $Title) -ForegroundColor $Color
  Write-Host ("=" * 78) -ForegroundColor $Color
  Write-Host ""
}

function Write-Step {
  param([string]$Text)
  Write-Host "==> " -NoNewline -ForegroundColor Cyan
  Write-Host $Text
}

function Invoke-Checked {
  param(
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$Description
  )

  Write-Step "$Description"
  if ($useWhatIf) {
    Write-Host "    [whatif] $FilePath $($Arguments -join ' ')" -ForegroundColor DarkGray
    return
  }
  & $FilePath @Arguments 2>&1 | Tee-Object -FilePath $installLogPath -Append
  if ($LASTEXITCODE -ne 0) {
    throw "$Description failed with exit code $LASTEXITCODE. See $installLogPath for the full output."
  }
}

function Assert-Tool {
  param(
    [string]$Tool,
    [string]$MinVersion = "",
    [string]$VersionFlag = "--version"
  )

  $command = Get-Command -Name $Tool -ErrorAction SilentlyContinue
  if (-not $command) {
    throw "Required tool '$Tool' is not on PATH. Install it and retry."
  }

  # A few CLIs (kubectl, helm) reject --version and print to stderr; we just
  # need to know the tool runs. Capture output + exit code, but don't bail
  # purely on a non-zero exit: the tool may still be on PATH and functional.
  $output = & $command.Path $VersionFlag 2>&1
  $firstLine = ($output | Out-String).Trim().Split([Environment]::NewLine) | Where-Object { $_ } | Select-Object -First 1
  if (-not $firstLine) {
    throw "Required tool '$Tool' is not on PATH. Install it and retry."
  }
  if ($MinVersion -and $firstLine -notmatch $MinVersion) {
    Write-Host "    [warn] ${Tool} resolved to: $firstLine (looking for pattern '$MinVersion')" -ForegroundColor Yellow
  } else {
    Write-Host "    [ok]   ${Tool}: $firstLine" -ForegroundColor DarkGray
  }
}

function Sync-PostgresPassword {
  param(
    [string]$Namespace,
    [string]$ClusterContext,
    [string]$ReleaseName,
    [string]$DatabasePassword
  )

  $postgresPod = "$ReleaseName-postgresql-0"
  $existingPod = & kubectl get pod $postgresPod -n $Namespace --context $ClusterContext --ignore-not-found -o name
  if ($LASTEXITCODE -ne 0) {
    throw "Checking for existing PostgreSQL pod '$postgresPod' failed with exit code $LASTEXITCODE."
  }

  if ([string]::IsNullOrWhiteSpace((($existingPod | Out-String).Trim()))) {
    return
  }

  $escapedDatabasePassword = $DatabasePassword.Replace("'", "''")

  $psqlArgs = @(
    "exec",
    "-n",
    $Namespace,
    "--context",
    $ClusterContext,
    $postgresPod,
    "--",
    "psql",
    "-U",
    "kubesynapse",
    "-d",
    "postgres",
    "-v",
    "ON_ERROR_STOP=1",
    "-c",
    "ALTER ROLE CURRENT_USER WITH PASSWORD '$escapedDatabasePassword';"
  )

  Invoke-Checked -FilePath "kubectl" -Arguments $psqlArgs -Description "Synchronizing PostgreSQL password for existing release '$ReleaseName'"
}

function Reset-ImmutableRuntimeConfigMaps {
  param(
    [string]$Namespace,
    [string]$ClusterContext,
    [string]$ReleaseName
  )

  $configMaps = @(
    "$ReleaseName-opencode-safe-config",
    "$ReleaseName-pi-safe-config"
  )

  foreach ($configMap in $configMaps) {
    $existing = & kubectl get configmap $configMap -n $Namespace --context $ClusterContext --ignore-not-found -o name
    if ($LASTEXITCODE -ne 0) {
      throw "Checking for immutable runtime ConfigMap '$configMap' failed with exit code $LASTEXITCODE."
    }

    if (-not [string]::IsNullOrWhiteSpace((($existing | Out-String).Trim()))) {
      Invoke-Checked -FilePath "kubectl" -Arguments @(
        "delete",
        "configmap",
        $configMap,
        "-n",
        $Namespace,
        "--context",
        $clusterContext
      ) -Description "Deleting immutable runtime ConfigMap '$configMap' so Helm can recreate it"
    }
  }
}

function Reset-LegacyOperatorDeployment {
  param(
    [string]$Namespace,
    [string]$ClusterContext,
    [string]$ReleaseName
  )

  $deploymentName = "$ReleaseName-operator"
  $deploymentJson = & kubectl get deployment $deploymentName -n $Namespace --context $ClusterContext --ignore-not-found -o json
  if ($LASTEXITCODE -ne 0) {
    throw "Checking for existing operator deployment '$deploymentName' failed with exit code $LASTEXITCODE."
  }

  if ([string]::IsNullOrWhiteSpace((($deploymentJson | Out-String).Trim()))) {
    return
  }

  $deployment = $deploymentJson | ConvertFrom-Json
  $envItems = @($deployment.spec.template.spec.containers[0].env)
  $legacyNamespaceEnv = $envItems | Where-Object {
    $_.name -eq "OPERATOR_NAMESPACE" -and
    $_.PSObject.Properties.Match("value").Count -gt 0 -and
    -not [string]::IsNullOrWhiteSpace($_.value)
  }

  if ($legacyNamespaceEnv) {
    Invoke-Checked -FilePath "kubectl" -Arguments @(
      "delete",
      "deployment",
      $deploymentName,
      "-n",
      $Namespace,
      "--context",
      $ClusterContext,
      "--wait=true"
    ) -Description "Deleting legacy operator deployment '$deploymentName' so Helm can recreate the env schema"
  }
}

# ---------------------------------------------------------------------------
# Step 0 — preflight
# ---------------------------------------------------------------------------
Remove-Item $installLogPath -ErrorAction SilentlyContinue
Write-Banner "KubeSynapse local install  (cluster: $ClusterName)"

Write-Step "Preflight: required tools"
Assert-Tool -Tool "docker" -VersionFlag "--version" | Out-Null
Assert-Tool -Tool "kind" -MinVersion "kind v" | Out-Null
Assert-Tool -Tool "kubectl" | Out-Null
Assert-Tool -Tool "helm" -MinVersion "v" | Out-Null

if (-not (Test-Path $localImagesValuesPath)) {
  throw "Local images overlay not found at $localImagesValuesPath"
}
if (-not (Test-Path $kindQuickstartValuesPath)) {
  throw "Kind quickstart overlay not found at $kindQuickstartValuesPath"
}
if (-not (Test-Path $skillsCatalogPath)) {
  Write-Host "    [warn] Skills catalog not found at $skillsCatalogPath — the in-app Catalog tab will be empty." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Step 1 — secrets
# ---------------------------------------------------------------------------
Write-Step "Step 1/7 — Generate secrets"
$AdminPassword = Ensure-SecretValue -CurrentValue $AdminPassword -Prefix "KsAdmin!" -RandomLength 14
$SharedToken = Ensure-SecretValue -CurrentValue $SharedToken -Prefix "ks-shared-" -RandomLength 32
$DatabasePassword = Ensure-SecretValue -CurrentValue $DatabasePassword -Prefix "ks-db-" -RandomLength 32
$JwtSecret = Ensure-SecretValue -CurrentValue $JwtSecret -Prefix "ks-jwt-" -RandomLength 32
$LiteLlmMasterKey = Ensure-SecretValue -CurrentValue $LiteLlmMasterKey -Prefix "ks-litellm-" -RandomLength 32
Write-Host "    Admin password: $AdminPassword" -ForegroundColor DarkGray
Write-Host "    API shared token: $($SharedToken.Substring(0, 12))..." -ForegroundColor DarkGray
Write-Host "    Database password: $($DatabasePassword.Substring(0, 12))..." -ForegroundColor DarkGray
Write-Host "    JWT secret: $($JwtSecret.Substring(0, 12))..." -ForegroundColor DarkGray
Write-Host "    LiteLLM master key: $($LiteLlmMasterKey.Substring(0, 12))..." -ForegroundColor DarkGray

# ---------------------------------------------------------------------------
# Step 2 — kind cluster
# ---------------------------------------------------------------------------
Write-Step "Step 2/7 — Prepare kind cluster"
$kindClusters = @(& kind get clusters)
$clusterExists = $kindClusters -contains $ClusterName

if ($RecreateCluster -and $clusterExists) {
  Invoke-Checked -FilePath "kind" -Arguments @("delete", "cluster", "--name", $ClusterName) -Description "Deleting existing kind cluster '$ClusterName'"
  $clusterExists = $false
}

if (-not $clusterExists) {
  Invoke-Checked -FilePath "kind" -Arguments @("create", "cluster", "--name", $ClusterName, "--wait", "120s") -Description "Creating kind cluster '$ClusterName'"
}

Invoke-Checked -FilePath "kubectl" -Arguments @("config", "use-context", $clusterContext) -Description "Switching kubectl to '$clusterContext'"

# ---------------------------------------------------------------------------
# Step 3 — build images
# ---------------------------------------------------------------------------
$images = @(
  @{ Tag = "localhost/kubesynapse/kubesynapse-operator:dev"; Context = "operator" },
  @{ Tag = "localhost/kubesynapse/kubesynapse-api-gateway:dev"; Context = "api-gateway" },
  @{ Tag = "localhost/kubesynapse/kubesynapse-web-ui:dev"; Context = "web-ui" },
  @{ Tag = "localhost/kubesynapse/kubesynapse-opencode-rt:dev"; Context = "opencode-runtime" },
  @{ Tag = "docker.io/litellm/litellm:v1.82.3-stable"; Context = "deploy/litellm"; Dockerfile = "deploy/litellm/Dockerfile" }
)

if (-not $SkipBuild) {
  Write-Step "Step 3/7 — Build images (this can take a few minutes on a cold cache)"
  foreach ($image in $images) {
    $buildArgs = @("build")
    if ($image.ContainsKey("Dockerfile")) {
      $buildArgs += @("-f", (Join-Path $repoRoot $image.Dockerfile))
    }
    $buildArgs += @("-t", $image.Tag, (Join-Path $repoRoot $image.Context))
    Invoke-Checked -FilePath $ContainerCli -Arguments $buildArgs -Description "Building image '$($image.Tag)'"
  }
} else {
  Write-Step "Step 3/7 — Skipping image builds (SkipBuild)"
}

# ---------------------------------------------------------------------------
# Step 4 — load images
# ---------------------------------------------------------------------------
if (-not $SkipLoad) {
  Write-Step "Step 4/7 — Load images into kind"
  foreach ($image in $images) {
    Invoke-Checked -FilePath "kind" -Arguments @("load", "docker-image", $image.Tag, "--name", $ClusterName) -Description "Loading image '$($image.Tag)' into kind"
  }
} else {
  Write-Step "Step 4/7 — Skipping kind image load (SkipLoad)"
}

# ---------------------------------------------------------------------------
# Step 5 — state migrations
# ---------------------------------------------------------------------------
Write-Step "Step 5/7 — Reconcile state from previous installs"
Sync-PostgresPassword -Namespace $Namespace -ClusterContext $clusterContext -ReleaseName $ReleaseName -DatabasePassword $DatabasePassword
Reset-ImmutableRuntimeConfigMaps -Namespace $Namespace -ClusterContext $clusterContext -ReleaseName $ReleaseName
Reset-LegacyOperatorDeployment -Namespace $Namespace -ClusterContext $clusterContext -ReleaseName $ReleaseName

# ---------------------------------------------------------------------------
# Step 6 — helm install
# ---------------------------------------------------------------------------
Write-Step "Step 6/7 — Install (or upgrade) Helm release '$ReleaseName'"
$helmArgs = @(
  "upgrade",
  "--install",
  $ReleaseName,
  $chartPath,
  "--namespace",
  $Namespace,
  "--create-namespace",
  "--kube-context",
  $clusterContext,
  "--wait",
  "--timeout",
  ("$HelmTimeoutMinutes" + "m"),
  "--force-conflicts",
  "-f",
  $localImagesValuesPath,
  "-f",
  $kindQuickstartValuesPath,
  "--set-string",
  "platformSecrets.native.litellmMasterKey=$LiteLlmMasterKey",
  "--set-string",
  "platformSecrets.native.apiGatewaySharedToken=$SharedToken",
  "--set-string",
  "platformSecrets.native.databasePassword=$DatabasePassword",
  "--set-string",
  "platformSecrets.native.jwtSecret=$JwtSecret",
  "--set-string",
  "platformSecrets.native.authBootstrapAdminPassword=$AdminPassword",
  "--set-string",
  "apiGateway.auth.bootstrapAdminUsername=$AdminUsername"
)
if (Test-Path $skillsCatalogPath) {
  $helmArgs += @("--set-file", "skillsCatalog.catalogJson=$skillsCatalogPath")
}

Invoke-Checked -FilePath "helm" -Arguments $helmArgs -Description "Installing or upgrading Helm release '$ReleaseName'"

# ---------------------------------------------------------------------------
# Step 7 — restart + rollout
# ---------------------------------------------------------------------------
if (-not $SkipRestart) {
  Write-Step "Step 7/7 — Restart core deployments to pick up new local images, then wait"
  $coreDeployments = @(
    "$ReleaseName-operator",
    "$ReleaseName-api-gateway",
    "$ReleaseName-web-ui"
  )

  foreach ($deployment in $coreDeployments) {
    Invoke-Checked -FilePath "kubectl" -Arguments @(
      "rollout",
      "restart",
      "deployment/$deployment",
      "-n",
      $Namespace,
      "--context",
      $clusterContext
    ) -Description "Restarting deployment '$deployment' to pick up local dev images"

    Invoke-Checked -FilePath "kubectl" -Arguments @(
      "rollout",
      "status",
      "deployment/$deployment",
      "-n",
      $Namespace,
      "--context",
      $clusterContext,
      ("--timeout=$RolloutTimeoutMinutes" + "m")
    ) -Description "Waiting for deployment '$deployment' rollout"
  }
} else {
  Write-Step "Step 7/7 — Skipping rollout restart (SkipRestart)"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Banner "KubeSynapse local install is ready." "Green"

Write-Host "  Cluster context : $clusterContext" -ForegroundColor White
Write-Host "  Release name    : $ReleaseName" -ForegroundColor White
Write-Host "  Namespace       : $Namespace" -ForegroundColor White
Write-Host "  Image registry  : localhost/kubesynapse/*:dev (kind-loaded)" -ForegroundColor White
Write-Host "  Admin username  : $AdminUsername" -ForegroundColor White
Write-Host "  Admin password  : $AdminPassword" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Next: port-forward the platform." -ForegroundColor Cyan
Write-Host "    kubectl port-forward svc/$ReleaseName-api-gateway -n $Namespace 8080:8080" -ForegroundColor White
Write-Host "    kubectl port-forward svc/$ReleaseName-web-ui -n $Namespace 3000:80" -ForegroundColor White
Write-Host ""
Write-Host "  UI:    http://localhost:3000" -ForegroundColor White
Write-Host "  API:   http://localhost:8080/api/v1/health" -ForegroundColor White
Write-Host ""
Write-Host "  Important: configure an LLM API key before invoking agents." -ForegroundColor Cyan
Write-Host "    Option A: open the Web UI -> Settings -> Providers, add your key." -ForegroundColor White
Write-Host "    Option B: see scripts/install.sh (Option B/C) for kubectl patch commands." -ForegroundColor White
Write-Host ""
Write-Host "  Re-running the script with the same -ClusterName will upgrade in place" -ForegroundColor DarkGray
Write-Host "  and reuse the existing cluster and chart release. Use -RecreateCluster to" -ForegroundColor DarkGray
Write-Host "  start from a clean slate." -ForegroundColor DarkGray
Write-Host ""
