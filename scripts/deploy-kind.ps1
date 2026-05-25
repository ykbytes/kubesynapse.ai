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
  [switch]$RecreateCluster,
  [switch]$SkipBuild,
  [switch]$SkipLoad
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$clusterContext = "kind-$ClusterName"
$chartPath = (Join-Path $repoRoot "charts/kubesynapse") -replace "\\", "/"
$localImagesValuesPath = (Join-Path $repoRoot "deploy/values.local-images.example.yaml") -replace "\\", "/"
$kindQuickstartValuesPath = (Join-Path $repoRoot "deploy/values.kind.quickstart.yaml") -replace "\\", "/"
$skillsCatalogPath = (Join-Path $repoRoot "catalog/skills-catalog.json") -replace "\\", "/"

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

function Invoke-Checked {
  param(
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$Description
  )

  Write-Host $Description
  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$Description failed with exit code $LASTEXITCODE."
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

$AdminPassword = Ensure-SecretValue -CurrentValue $AdminPassword -Prefix "KsAdmin!" -RandomLength 14
$SharedToken = Ensure-SecretValue -CurrentValue $SharedToken -Prefix "ks-shared-" -RandomLength 32
$DatabasePassword = Ensure-SecretValue -CurrentValue $DatabasePassword -Prefix "ks-db-" -RandomLength 32
$JwtSecret = Ensure-SecretValue -CurrentValue $JwtSecret -Prefix "ks-jwt-" -RandomLength 32
$LiteLlmMasterKey = Ensure-SecretValue -CurrentValue $LiteLlmMasterKey -Prefix "ks-litellm-" -RandomLength 32

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

$images = @(
  @{ Tag = "localhost/kubesynapse/kubesynapse-operator:dev"; Context = "operator" },
  @{ Tag = "localhost/kubesynapse/kubesynapse-api-gateway:dev"; Context = "api-gateway" },
  @{ Tag = "localhost/kubesynapse/kubesynapse-web-ui:dev"; Context = "web-ui" },
  @{ Tag = "localhost/kubesynapse/kubesynapse-opencode-rt:dev"; Context = "opencode-runtime" },
  @{ Tag = "docker.io/litellm/litellm:v1.82.3-stable"; Context = "deploy/litellm"; Dockerfile = "deploy/litellm/Dockerfile" }
)

if (-not $SkipBuild) {
  foreach ($image in $images) {
    $buildArgs = @("build")
    if ($image.ContainsKey("Dockerfile")) {
      $buildArgs += @("-f", (Join-Path $repoRoot $image.Dockerfile))
    }
    $buildArgs += @("-t", $image.Tag, (Join-Path $repoRoot $image.Context))
    Invoke-Checked -FilePath $ContainerCli -Arguments $buildArgs -Description "Building image '$($image.Tag)'"
  }
}

if (-not $SkipLoad) {
  foreach ($image in $images) {
    Invoke-Checked -FilePath "kind" -Arguments @("load", "docker-image", $image.Tag, "--name", $ClusterName) -Description "Loading image '$($image.Tag)' into kind"
  }
}

Sync-PostgresPassword -Namespace $Namespace -ClusterContext $clusterContext -ReleaseName $ReleaseName -DatabasePassword $DatabasePassword

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
  "20m",
  "--force-conflicts",
  "-f",
  $localImagesValuesPath,
  "-f",
  $kindQuickstartValuesPath,
  "--set-file",
  "skillsCatalog.catalogJson=$skillsCatalogPath",
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

Invoke-Checked -FilePath "helm" -Arguments $helmArgs -Description "Installing or upgrading Helm release '$ReleaseName'"

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
    "--timeout=10m"
  ) -Description "Waiting for deployment '$deployment' rollout"
}

Invoke-Checked -FilePath "kubectl" -Arguments @("get", "pods", "-n", $Namespace) -Description "Listing pods in namespace '$Namespace'"
Invoke-Checked -FilePath "kubectl" -Arguments @("get", "svc", "-n", $Namespace) -Description "Listing services in namespace '$Namespace'"

Write-Host ""
Write-Host "KubeSynapse local Kind install is ready."
Write-Host "Admin username: $AdminUsername"
Write-Host "Admin password: $AdminPassword"
Write-Host "API port-forward: kubectl port-forward svc/$ReleaseName-api-gateway -n $Namespace 8080:8080"
Write-Host "Web UI port-forward: kubectl port-forward svc/$ReleaseName-web-ui -n $Namespace 3000:80"
Write-Host ""
Write-Host "Next: configure an LLM API key or agents cannot invoke models."
Write-Host "  Option A: Open the Web UI, go to Settings > Providers, add your key."
Write-Host "  Option B: kubectl patch secret kubesynapse-llm-api-keys -n $Namespace --patch '{\"data\":{\"OPENAI_API_KEY\":\"'+(echo -n 'sk-your-key' | base64)'\"}}'"