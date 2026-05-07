param(
    [string]$BaseUrl = "http://127.0.0.1:18080",
    [string]$Namespace = "ai-agent-sandbox",
    [string]$Token = "minikube-dev-shared-token"
)

$ErrorActionPreference = "Stop"

$headers = @{
    Authorization = "Bearer $Token"
}

$suffix = Get-Date -Format "HHmmss"
$connectorName = "smoke-connector-$suffix"
$policyName = "smoke-policy-$suffix"
$targetName = "smoke-target-$suffix"

function Invoke-JsonApi {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("GET", "POST", "PATCH", "DELETE")]
        [string]$Method,

        [Parameter(Mandatory = $true)]
        [string]$Url,

        $Body = $null
    )

    $params = @{
        Method  = $Method
        Uri     = $Url
        Headers = $headers
    }

    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = $Body | ConvertTo-Json -Depth 20
    }

    Invoke-RestMethod @params
}

function Test-IsNotFound {
    param($ErrorRecord)

    return $null -ne $ErrorRecord.Exception.Response -and [int]$ErrorRecord.Exception.Response.StatusCode -eq 404
}

function Wait-ForResourceDeletion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,

        [int]$Attempts = 15,

        [int]$DelaySeconds = 1
    )

    # Custom resources can remain visible briefly after DELETE while the API server
    # finishes removing them, so poll before asserting final overview counts.
    for ($attempt = 0; $attempt -lt $Attempts; $attempt += 1) {
        try {
            Invoke-JsonApi -Method "GET" -Url $Url | Out-Null
            Start-Sleep -Seconds $DelaySeconds
        }
        catch {
            if (Test-IsNotFound $_) {
                return
            }
            throw
        }
    }

    throw "Timed out waiting for resource deletion: $Url"
}

function Remove-TestResource {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Plural,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    try {
        Invoke-JsonApi -Method "DELETE" -Url "${BaseUrl}/api/observability/${Plural}/${Name}?namespace=${Namespace}" | Out-Null
        Wait-ForResourceDeletion -Url "${BaseUrl}/api/observability/${Plural}/${Name}?namespace=${Namespace}"
    }
    catch {
        if (Test-IsNotFound $_) {
            return
        }
        throw
    }
}

try {
    $initialOverview = Invoke-JsonApi -Method "GET" -Url "${BaseUrl}/api/v1/observability/overview?namespace=${Namespace}"

    $connector = Invoke-JsonApi -Method "POST" -Url "${BaseUrl}/api/v1/observability/connectors?namespace=${Namespace}" -Body @{
        name = $connectorName
        description = "Smoke-test connector proving that connector create, update, and delete flows work through the live gateway."
        image = "docker.io/kubesynapse/connector-kubernetes:smoke"
        protocol = "grpc"
        port = 9090
        capabilities = @("kubernetes-api")
        healthEndpoint = "/healthz"
        resources = @{
            requests = @{ cpu = "50m"; memory = "64Mi" }
            limits = @{ cpu = "200m"; memory = "256Mi" }
        }
    }

    $connectorPatched = Invoke-JsonApi -Method "PATCH" -Url "${BaseUrl}/api/v1/observability/connectors/${connectorName}?namespace=${Namespace}" -Body @{
        port = 9091
        healthEndpoint = "/readyz"
    }

    $policy = Invoke-JsonApi -Method "POST" -Url "${BaseUrl}/api/v1/observability/policies?namespace=${Namespace}" -Body @{
        name = $policyName
        description = "Smoke-test policy proving that retention, anomaly, and notification settings can be created, updated, and deleted through the live gateway."
        retention = @{ days = 30; downsampling = @{ after = "7d"; resolution = "5m" } }
        anomalyDetection = @{ enabled = $true; algorithm = "ensemble"; sensitivity = 0.7; windowSize = "1h"; evaluationInterval = "5m"; metrics = @("kube_node_status_condition") }
        alertRules = @(
            @{ name = "NodeNotReady"; expr = "kube_node_status_condition{condition='Ready',status='true'} == 0"; severity = "critical"; for = "2m" }
        )
        notifications = @{ natsSubject = "aiops.smoke" }
    }

    $policyPatched = Invoke-JsonApi -Method "PATCH" -Url "${BaseUrl}/api/v1/observability/policies/${policyName}?namespace=${Namespace}" -Body @{
        retention = @{ days = 14 }
        notifications = @{ natsSubject = "aiops.smoke.updated" }
    }

    $target = Invoke-JsonApi -Method "POST" -Url "${BaseUrl}/api/v1/observability/targets?namespace=${Namespace}" -Body @{
        name = $targetName
        description = "Smoke-test target proving that a real observed system can be connected to a connector and policy through the live gateway."
        targetType = "kubernetes-api"
        connectorRef = $connectorName
        policyRef = $policyName
        endpoint = "https://kubernetes.default.svc.cluster.local:443"
        scrapeInterval = "30s"
        labels = @{ smoke = "true"; environment = "dev" }
        tlsConfig = @{ insecureSkipVerify = $true }
    }

    $targetPatched = Invoke-JsonApi -Method "PATCH" -Url "${BaseUrl}/api/v1/observability/targets/${targetName}?namespace=${Namespace}" -Body @{
        scrapeInterval = "45s"
        labels = @{ smoke = "updated"; environment = "dev" }
    }

    $overview = Invoke-JsonApi -Method "GET" -Url "${BaseUrl}/api/v1/observability/overview?namespace=${Namespace}"
    $executions = Invoke-JsonApi -Method "GET" -Url "${BaseUrl}/api/v1/traces/executions?namespace=${Namespace}&limit=1"
    $runtimeEvents = Invoke-JsonApi -Method "GET" -Url "${BaseUrl}/api/v1/traces/runtime-events?namespace=${Namespace}&limit=1"
    $spend = Invoke-JsonApi -Method "GET" -Url "${BaseUrl}/api/v1/observability/spend?namespace=${Namespace}&window_hours=1"
    $agentGraph = Invoke-JsonApi -Method "GET" -Url "${BaseUrl}/api/v1/observability/agent-graph?namespace=${Namespace}&window_hours=1"

    if (($overview.connectors | Where-Object { $_.name -eq $connectorName }).Count -ne 1) {
        throw "Connector not present in overview after create"
    }
    if (($overview.policies | Where-Object { $_.name -eq $policyName }).Count -ne 1) {
        throw "Policy not present in overview after create"
    }
    if (($overview.targets | Where-Object { $_.name -eq $targetName }).Count -ne 1) {
        throw "Target not present in overview after create"
    }
    if ($connectorPatched.spec.port -ne 9091) {
        throw "Connector patch did not persist"
    }
    if ($policyPatched.spec.retention.days -ne 14) {
        throw "Policy patch did not persist"
    }
    if ($targetPatched.spec.scrapeInterval -ne "45s") {
        throw "Target patch did not persist"
    }
    if ($null -eq $executions.items) {
        throw "Execution list response does not expose an items envelope"
    }
    if ($runtimeEvents.limit -lt 1) {
        throw "Runtime events response did not return pagination metadata"
    }
    if ($null -eq $spend.items) {
        throw "Spend analytics response is missing items"
    }
    if ($null -eq $agentGraph.nodes -or $null -eq $agentGraph.edges) {
        throw "Agent graph response is missing nodes or edges"
    }

    Remove-TestResource -Plural "targets" -Name $targetName
    Remove-TestResource -Plural "policies" -Name $policyName
    Remove-TestResource -Plural "connectors" -Name $connectorName

    $finalOverview = Invoke-JsonApi -Method "GET" -Url "${BaseUrl}/api/v1/observability/overview?namespace=${Namespace}"

    if (($finalOverview.connectors | Where-Object { $_.name -eq $connectorName }).Count -ne 0) {
        throw "Connector delete did not persist"
    }
    if (($finalOverview.policies | Where-Object { $_.name -eq $policyName }).Count -ne 0) {
        throw "Policy delete did not persist"
    }
    if (($finalOverview.targets | Where-Object { $_.name -eq $targetName }).Count -ne 0) {
        throw "Target delete did not persist"
    }

    [pscustomobject]@{
        created = @{
            connector = $connector.metadata.name
            policy = $policy.metadata.name
            target = $target.metadata.name
        }
        patched = @{
            connectorPort = $connectorPatched.spec.port
            policyRetentionDays = $policyPatched.spec.retention.days
            targetScrapeInterval = $targetPatched.spec.scrapeInterval
        }
        overviewCountsDuringTest = @{
            connectors = $overview.summary.connectors.total
            policies = $overview.summary.policies.total
            targets = $overview.summary.targets.total
        }
        traceChecks = @{
            executionItems = $executions.items.Count
            runtimeEventItems = $runtimeEvents.items.Count
            spendItems = $spend.items.Count
            agentGraphNodes = $agentGraph.nodes.Count
            agentGraphEdges = $agentGraph.edges.Count
        }
        finalCounts = @{
            connectors = $finalOverview.summary.connectors.total
            policies = $finalOverview.summary.policies.total
            targets = $finalOverview.summary.targets.total
        }
        initialCounts = @{
            connectors = $initialOverview.summary.connectors.total
            policies = $initialOverview.summary.policies.total
            targets = $initialOverview.summary.targets.total
        }
    } | ConvertTo-Json -Depth 10
}
catch {
    Remove-TestResource -Plural "targets" -Name $targetName
    Remove-TestResource -Plural "policies" -Name $policyName
    Remove-TestResource -Plural "connectors" -Name $connectorName
    throw
}