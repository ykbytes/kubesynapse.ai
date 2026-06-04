# ────────────────────────────────────────────────────────────────────
# KubeSynapse — Generate incident report
# ────────────────────────────────────────────────────────────────────
# Fetches the named incident, its timeline, and the linked workflow
# run (if any) and writes a Markdown report. Optionally renders HTML.
#
# Usage:
#   .\scripts\incidents\generate-incident-report.ps1
#   .\scripts\incidents\generate-incident-report.ps1 -IncidentName "alert-..." -Format html
#   .\scripts\incidents\generate-incident-report.ps1 -IncidentName "alert-..." -OutputDir ".\reports"
# ────────────────────────────────────────────────────────────────────
[CmdletBinding()]
param(
  [string]$Namespace = "default",
  [string]$IncidentName = "",
  [string]$OutputDir = "",
  [ValidateSet("md", "html", "both")]
  [string]$Format = "md"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
. (Join-Path $ScriptDir "_common.ps1")
$Ctx = Resolve-KubeSynapseContext -Port 8080
$Token = $Ctx.Token
$GatewayUrl = $Ctx.GatewayUrl

# ── Resolve incident name ──────────────────────────────────────────
if (-not $IncidentName) {
  $LastFile = Join-Path $env:TEMP "kubesynapse-last-incident.txt"
  if (Test-Path $LastFile) {
    $IncidentName = (Get-Content $LastFile -Raw).Trim()
    Write-Host "[INFO] Reusing last-fired incident: $IncidentName" -ForegroundColor Blue
  } else {
    throw "No -IncidentName provided and no previous incident recorded. Run fire-alertmanager-alert.ps1 first."
  }
}

$Headers = @{ Authorization = "Bearer $Token" }

# ── 1) Fetch incident ─────────────────────────────────────────────
Write-Host ""
Write-Host "═══ Fetching incident data ═══" -ForegroundColor Cyan
$IncidentUri = "${GatewayUrl}/api/v1/incidents/${IncidentName}?namespace=$Namespace"
$Incident = Invoke-RestMethod -Uri $IncidentUri -Method Get -Headers $Headers -TimeoutSec 15

# ── 2) Fetch timeline ──────────────────────────────────────────────
$TimelineUri = "${GatewayUrl}/api/v1/incidents/${IncidentName}/timeline?namespace=$Namespace"
try {
  $TimelineResp = Invoke-RestMethod -Uri $TimelineUri -Method Get -Headers $Headers -TimeoutSec 15
  $Timeline = $TimelineResp.timeline
} catch {
  $Timeline = @()
  Write-Host "[WARN] Could not fetch timeline: $($_.Exception.Message)" -ForegroundColor Yellow
}

# ── 3) Fetch workflow run data (if linked) ────────────────────────
$RunTrace = $null
$RunLogs = $null
$WorkflowName = $null
$RunId = $Incident.workflow_run_id
if ($RunId) {
  $WorkflowName = $Incident.workflow_ref_name ?? $null
  if (-not $WorkflowName) {
    # Try to derive workflow name from runId prefix if present, otherwise ask the API
    try {
      $StatusUri = "${GatewayUrl}/api/v1/workflows?namespace=$Namespace"
      $Workflows = Invoke-RestMethod -Uri $StatusUri -Method Get -Headers $Headers -TimeoutSec 10
      foreach ($w in $Workflows) {
        if ($w.run_id -eq $RunId) { $WorkflowName = $w.name; break }
      }
    } catch {}
  }
  if ($WorkflowName) {
    Write-Host "[INFO] Linked workflow: $WorkflowName (run $RunId)" -ForegroundColor Blue
    $TraceUri = "${GatewayUrl}/api/v1/workflows/${WorkflowName}/runs/${RunId}/trace?namespace=$Namespace"
    try {
      $RunTrace = Invoke-RestMethod -Uri $TraceUri -Method Get -Headers $Headers -TimeoutSec 15
    } catch {
      Write-Host "[WARN] Could not fetch workflow run trace: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    $LogsUri = "${GatewayUrl}/api/v1/workflows/${WorkflowName}/logs?namespace=$Namespace&runId=${RunId}"
    try {
      $RunLogs = (Invoke-WebRequest -Uri $LogsUri -Method Get -Headers $Headers -TimeoutSec 15).Content
    } catch {
      Write-Host "[WARN] Could not fetch workflow logs: $($_.Exception.Message)" -ForegroundColor Yellow
    }
  } else {
    Write-Host "[WARN] workflow_run_id present but workflow name could not be resolved; run trace will be omitted." -ForegroundColor Yellow
  }
}

# ── 4) Output paths ────────────────────────────────────────────────
if (-not $OutputDir) { $OutputDir = Join-Path (Get-Location) "reports" }
if (-not (Test-Path $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null }

$SafeName = ($IncidentName -replace '[^\w\.\-]', '_')
$Stamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
$MdPath = Join-Path $OutputDir "${SafeName}-${Stamp}.md"
$HtmlPath = Join-Path $OutputDir "${SafeName}-${Stamp}.html"

# ── Helper: tiny Markdown→HTML (no external deps) ─────────────────
function Convert-MarkdownToHtml {
  param([string]$Markdown, [string]$Title = "Incident Report")
  $esc = [System.Web.HttpUtility]::HtmlEncode($Markdown)
  $html = $esc
  $html = $html -replace '^###### (.+)$',           '<h6>$1</h6>'
  $html = $html -replace '^##### (.+)$',            '<h5>$1</h5>'
  $html = $html -replace '^#### (.+)$',             '<h4>$1</h4>'
  $html = $html -replace '^### (.+)$',              '<h3>$1</h3>'
  $html = $html -replace '^## (.+)$',               '<h2>$1</h2>'
  $html = $html -replace '^# (.+)$',                '<h1>$1</h1>'
  $html = $html -replace '\*\*([^*]+)\*\*',         '<strong>$1</strong>'
  $html = $html -replace '\*([^*]+)\*',             '<em>$1</em>'
  $html = $html -replace '`([^`]+)`',               '<code>$1</code>'
  $html = $html -replace '(?ms)\n```\n(.*?)\n```',  '<pre><code>$1</code></pre>'
  $html = $html -replace '(?m)^- (.+)$',            '<li>$1</li>'
  $html = $html -replace '(?ms)(<li>.*?</li>(?:\s*<li>.*?</li>)*)', '<ul>$1</ul>'
  $html = $html -replace '\n{2,}',                  '</p><p>'
  $html = "<!doctype html><html><head><meta charset='utf-8'><title>$Title</title><style>body{font:14px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:920px;margin:32px auto;padding:0 16px;color:#1f2937}h1,h2,h3{border-bottom:1px solid #e5e7eb;padding-bottom:4px}h1{font-size:1.8rem}h2{font-size:1.3rem}table{border-collapse:collapse;width:100%;margin:12px 0}th,td{border:1px solid #e5e7eb;padding:6px 10px;text-align:left}th{background:#f9fafb}code{background:#f3f4f6;padding:1px 4px;border-radius:3px}pre{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:6px;overflow-x:auto}pre code{background:transparent;color:inherit}details{background:#f8fafc;border:1px solid #e5e7eb;border-radius:6px;padding:8px 12px}</style></head><body><p>$html</p></body></html>"
  return $html
}

# ── 5) Render Markdown ─────────────────────────────────────────────
$SeverityEmoji = @{ critical = "🔴"; warning = "🟡"; info = "🔵" }
$StatusEmoji   = @{ firing = "🔥"; acknowledged = "👀"; diagnosing = "🧪"; remediated = "🛠️"; resolved = "✅"; closed = "📦"; escalated = "📈" }

$SevEmoji = $SeverityEmoji[$Incident.severity] ?? "⚪"
$StEmoji  = $StatusEmoji[$Incident.status] ?? "⚪"

# Pre-bind values to avoid PowerShell object-string conflicts in template
$iTitle   = [string]$Incident.title
$iStatus  = [string]$Incident.status
$iSev     = [string]$Incident.severity
$iSource  = [string]$Incident.source
$iNs      = [string]$Incident.namespace
$iName    = [string]$Incident.name
$iAgent   = if ($Incident.assigned_agent) { [string]$Incident.assigned_agent } else { 'unassigned' }
$iTimeout = [string]$Incident.escalation_timeout_minutes
$iAutoA   = [string]$Incident.auto_acknowledge
$iCreated = [string]$Incident.created_at
$iUpdated = [string]$Incident.updated_at
$iAckAt   = if ($Incident.acknowledged_at) { [string]$Incident.acknowledged_at } else { $null }
$iResAt   = if ($Incident.resolved_at)      { [string]$Incident.resolved_at } else { $null }
$iWfRunId = if ($Incident.workflow_run_id)  { [string]$Incident.workflow_run_id } else { $null }

$Md = New-Object System.Text.StringBuilder
[void]$Md.AppendLine("# Incident Report — $iTitle")
[void]$Md.AppendLine("")
[void]$Md.AppendLine("Generated: $(Get-Date -Format 'u')")
[void]$Md.AppendLine("Reporter: $(whoami) @ $env:COMPUTERNAME")
[void]$Md.AppendLine("")
[void]$Md.AppendLine("## Summary")
[void]$Md.AppendLine("")
[void]$Md.AppendLine("| Field | Value |")
[void]$Md.AppendLine("| --- | --- |")
[void]$Md.AppendLine("| Status | $StEmoji $iStatus |")
[void]$Md.AppendLine("| Severity | $SevEmoji $iSev |")
[void]$Md.AppendLine("| Source | $iSource |")
[void]$Md.AppendLine("| Namespace | $iNs |")
[void]$Md.AppendLine("| Name | $iName |")
[void]$Md.AppendLine("| Assigned agent | $iAgent |")
[void]$Md.AppendLine("| Escalation timeout | $iTimeout min |")
[void]$Md.AppendLine("| Auto-acknowledge | $iAutoA |")
[void]$Md.AppendLine("| Created | $iCreated |")
[void]$Md.AppendLine("| Updated | $iUpdated |")
if ($iAckAt) { [void]$Md.AppendLine("| Acknowledged | $iAckAt |") }
if ($iResAt) { [void]$Md.AppendLine("| Resolved | $iResAt |") }
if ($iWfRunId) { [void]$Md.AppendLine("| Workflow run | $iWfRunId |") }
[void]$Md.AppendLine("")

if ($Incident.description) {
  [void]$Md.AppendLine("## Description")
  [void]$Md.AppendLine("")
  [void]$Md.AppendLine($Incident.description)
  [void]$Md.AppendLine("")
}

if ($Incident.labels.PSObject.Properties.Count -gt 0 -or $Incident.labels.Count -gt 0) {
  [void]$Md.AppendLine("## Labels")
  [void]$Md.AppendLine("")
  [void]$Md.AppendLine("| Key | Value |")
  [void]$Md.AppendLine("| --- | --- |")
  foreach ($p in $Incident.labels.PSObject.Properties) {
    $pN = [string]$p.Name; $pV = [string]$p.Value; [void]$Md.AppendLine("| $pN | ``$pV`` |")
  }
  [void]$Md.AppendLine("")
}

if ($Incident.annotations.PSObject.Properties.Count -gt 0 -or $Incident.annotations.Count -gt 0) {
  [void]$Md.AppendLine("## Annotations")
  [void]$Md.AppendLine("")
  foreach ($p in $Incident.annotations.PSObject.Properties) {
    [void]$Md.AppendLine("- **$($p.Name)**: $($p.Value)")
  }
  [void]$Md.AppendLine("")
}

[void]$Md.AppendLine("## Timeline")
[void]$Md.AppendLine("")
if (-not $Timeline -or $Timeline.Count -eq 0) {
  [void]$Md.AppendLine("_No timeline events recorded._")
} else {
  [void]$Md.AppendLine("| Time | Event | Message |")
  [void]$Md.AppendLine("| --- | --- | --- |")
  foreach ($e in $Timeline) {
    $msg = ($e.message -replace '\|', '\|' -replace "`r`n", ' ')
    [void]$Md.AppendLine("| $($e.timestamp) | $($e.event) | $msg |")
  }
}
[void]$Md.AppendLine("")

if ($RunTrace) {
  [void]$Md.AppendLine("## Workflow Run Trace")
  [void]$Md.AppendLine("")
  [void]$Md.AppendLine("Workflow: **$WorkflowName**")
  [void]$Md.AppendLine("")
  if ($RunTrace.activities) {
    foreach ($a in $RunTrace.activities) {
      $stepName = if ($a.PSObject.Properties['name']) { $a.name } elseif ($a.PSObject.Properties['stepName']) { $a.stepName } else { 'unknown' }
      [void]$Md.AppendLine("### Step: $stepName")
      [void]$Md.AppendLine("")
      $stepStatus = if ($a.PSObject.Properties['status']) { $a.status } elseif ($a.PSObject.Properties['phase']) { $a.phase } else { 'unknown' }
      [void]$Md.AppendLine("Status: $stepStatus")
      if ($a.startedAt)   { [void]$Md.AppendLine("Started: $($a.startedAt)") }
      if ($a.completedAt) { [void]$Md.AppendLine("Completed: $($a.completedAt)") }
      if ($a.output)      { [void]$Md.AppendLine(""); [void]$Md.AppendLine("``````json"); [void]$Md.AppendLine((($a.output | ConvertTo-Json -Depth 6))); [void]$Md.AppendLine("``````") }
      $errVal = $null
      if ($a.PSObject.Properties.Match('error').Count -gt 0) { $errVal = $a.PSObject.Properties['error'].Value }
      if ($errVal) { $msg = 'Error: ' + $errVal; [void]$Md.AppendLine($msg) }
      [void]$Md.AppendLine("")
    }
  } else {
    [void]$Md.AppendLine("``````json")
    [void]$Md.AppendLine(($RunTrace | ConvertTo-Json -Depth 8))
    [void]$Md.AppendLine("``````")
    [void]$Md.AppendLine("")
  }
}

if ($RunLogs) {
  [void]$Md.AppendLine("## Workflow Logs")
  [void]$Md.AppendLine("")
  [void]$Md.AppendLine('<details><summary>Click to expand</summary>')
  [void]$Md.AppendLine("")
  [void]$Md.AppendLine('```')
  [void]$Md.AppendLine($RunLogs)
  [void]$Md.AppendLine('```')
  [void]$Md.AppendLine("")
  [void]$Md.AppendLine('</details>')
  [void]$Md.AppendLine("")
}

[void]$Md.AppendLine("---")
[void]$Md.AppendLine("_Generated by ``scripts/incidents/generate-incident-report.ps1``_")

$MdText = $Md.ToString()
$MdText | Out-File -FilePath $MdPath -Encoding utf8

Write-Host ""
Write-Host "[OK]   Wrote Markdown report:" -ForegroundColor Green
Write-Host "       $MdPath"

# ── 6) Optionally render HTML ──────────────────────────────────────
if ($Format -in "html", "both") {
  $Html = Convert-MarkdownToHtml -Markdown $MdText -Title $Incident.title
  $Html | Out-File -FilePath $HtmlPath -Encoding utf8
  Write-Host "[OK]   Wrote HTML report:" -ForegroundColor Green
  Write-Host "       $HtmlPath"
}

Write-Host ""
Write-Host "Done. Share the Markdown file with responders or paste it into a ticket." -ForegroundColor Cyan


