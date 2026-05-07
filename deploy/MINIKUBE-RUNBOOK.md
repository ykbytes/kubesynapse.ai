# KubeSynapse Minikube Runbook

This is the validated local install path for the current chart on Windows using PowerShell, Podman, and Minikube with the VMware driver.

Validated environment:

- Minikube profile: `minikube`
- Driver: `vmware`
- Kubernetes: `v1.34.0`
- Cluster sizing: `16384Mi` memory and `28` CPUs
- Container build tool: `podman`
- Chart: `charts/kubesynapse`

This runbook intentionally uses the chart-default image references and preloads those exact tags into Minikube. Do not layer `deploy/values.minikube.local.yaml` on top of this path unless you are switching to the separate `localhost/*:dev` registry workflow.

## 1. Recreate the Minikube cluster

Run from the repository root.

```powershell
minikube delete --profile=minikube
minikube start --profile=minikube --driver=vmware --kubernetes-version=v1.34.0 --memory=16384 --cpus=28
minikube addons enable default-storageclass --profile=minikube
minikube addons enable storage-provisioner --profile=minikube
minikube addons enable ingress --profile=minikube
kubectl get pods -n ingress-nginx -o wide
```

## 2. Build the chart-default images with Podman

```powershell
podman build --format docker -f operator/Dockerfile -t docker.io/kubesynapse/kubesynapse-operator:v2.1.0-run-intelligence operator
podman build --format docker -f api-gateway/Dockerfile -t docker.io/kubesynapse/kubesynapse-api-gateway:v2.1.0-run-intelligence api-gateway
podman build --format docker -f web-ui/Dockerfile -t docker.io/kubesynapse/kubesynapse-web-ui:v2.1.0-run-intelligence web-ui
podman build --format docker -f opencode-runtime/Dockerfile -t docker.io/kubesynapse/kubesynapse-opencode-rt:v2.1.0-run-intelligence opencode-runtime
podman build --format docker -f pi-runtime/Dockerfile -t docker.io/kubesynapse/kubesynapse-pi-rt:v2.1.0-run-intelligence pi-runtime
podman build --format docker -f vibe-runtime/Dockerfile -t docker.io/kubesynapse/kubesynapse-vibe-rt:v2.1.0-run-intelligence vibe-runtime
podman build --format docker -f mcp-sidecars/github-adapter/Dockerfile -t docker.io/kubesynapse/mcp-github-adapter:deploy-20260401-212102 mcp-sidecars
podman build --format docker -f deploy/litellm/Dockerfile -t docker.io/litellm/litellm:v1.82.3-stable deploy/litellm
```

## 3. Pull the dependency images

```powershell
$dependencyImages = @(
  'postgres:16-alpine',
  'redis:7-alpine',
  'qdrant/qdrant:v1.7.4',
  'nats:2.10-alpine',
  'ghcr.io/github/github-mcp-server:latest'
)

foreach ($image in $dependencyImages) {
  podman pull $image
}
```

## 4. Load all images into Minikube

On Windows with Podman and the VMware driver, the most reliable path is saving each image to a tar archive and loading it with `minikube image load`.

```powershell
$cache = Join-Path $env:TEMP 'kubesynapse-image-cache'
New-Item -ItemType Directory -Force -Path $cache | Out-Null

$images = @(
  'docker.io/kubesynapse/kubesynapse-operator:v2.1.0-run-intelligence',
  'docker.io/kubesynapse/kubesynapse-api-gateway:v2.1.0-run-intelligence',
  'docker.io/kubesynapse/kubesynapse-web-ui:v2.1.0-run-intelligence',
  'docker.io/kubesynapse/kubesynapse-opencode-rt:v2.1.0-run-intelligence',
  'docker.io/kubesynapse/kubesynapse-pi-rt:v2.1.0-run-intelligence',
  'docker.io/kubesynapse/kubesynapse-vibe-rt:v2.1.0-run-intelligence',
  'docker.io/kubesynapse/mcp-github-adapter:deploy-20260401-212102',
  'docker.io/litellm/litellm:v1.82.3-stable',
  'postgres:16-alpine',
  'redis:7-alpine',
  'qdrant/qdrant:v1.7.4',
  'nats:2.10-alpine',
  'ghcr.io/github/github-mcp-server:latest'
)

foreach ($image in $images) {
  $safe = (($image -replace '[/:]', '_') + '.tar')
  $tar = Join-Path $cache $safe
  podman save -o $tar $image
  minikube image load $tar --profile=minikube
}
```

## 5. Lint and package the chart

```powershell
New-Item -ItemType Directory -Force -Path .\dist | Out-Null
helm lint .\charts\kubesynapse
helm package .\charts\kubesynapse -d .\dist
Get-ChildItem .\dist\kubesynapse-*.tgz
```

## 6. Generate install secrets

```powershell
function New-HexSecret([int]$Length) {
  -join (1..$Length | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
}

$databasePassword = New-HexSecret 32
$jwtSecret = New-HexSecret 64
$apiGatewaySharedToken = New-HexSecret 32
$litellmMasterKey = New-HexSecret 32
$authBootstrapAdminPassword = New-HexSecret 64
$mcpBearerToken = New-HexSecret 32
```

## 7. Install the chart

```powershell
helm upgrade --install kubesynapse .\charts\kubesynapse `
  --namespace kubesynapse `
  --create-namespace `
  --set operator.replicaCount=1 `
  --set-string platformSecrets.native.databasePassword=$databasePassword `
  --set-string platformSecrets.native.jwtSecret=$jwtSecret `
  --set-string platformSecrets.native.apiGatewaySharedToken=$apiGatewaySharedToken `
  --set-string platformSecrets.native.litellmMasterKey=$litellmMasterKey `
  --set-string platformSecrets.native.authBootstrapAdminPassword=$authBootstrapAdminPassword `
  --set-string mcpHub.auth.bearerToken=$mcpBearerToken `
  --set-file skillsCatalog.catalogJson=catalog/skills-catalog.json `
  --wait --timeout 20m
```

## 8. Verify the deployment

```powershell
helm status kubesynapse -n kubesynapse
kubectl get pods -n kubesynapse -o wide
kubectl get aiagents -n kubesynapse-system -o wide
```

All core pods should become `Running`, Helm should report `STATUS: deployed`, and the `kubesynapse-system` namespace should contain these system agents:

- `ks-run-inspector`
- `ks-signal-summarizer`
- `ks-spend-reviewer`

## 9. Get the Web UI URL

```powershell
$ip = minikube ip --profile=minikube
$nodePort = kubectl get svc kubesynapse-web-ui -n kubesynapse -o jsonpath='{.spec.ports[0].nodePort}'
Write-Host "Web UI: http://$ip:$nodePort"
```

The same pattern works for the API gateway service:

```powershell
$apiPort = kubectl get svc kubesynapse-api-gateway -n kubesynapse -o jsonpath='{.spec.ports[0].nodePort}'
Write-Host "API Gateway: http://$ip:$apiPort"
```

## 10. Cleanup

```powershell
helm uninstall kubesynapse -n kubesynapse
kubectl delete namespace kubesynapse kubesynapse-system mcp-hub --ignore-not-found=true
```