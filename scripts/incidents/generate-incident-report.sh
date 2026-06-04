#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# KubeSynapse — Generate incident report
# ────────────────────────────────────────────────────────────────────
# Fetches the named incident, its timeline, and the linked workflow
# run (if any) and writes a Markdown report. Optionally renders HTML.
#
# Usage:
#   ./scripts/incidents/generate-incident-report.sh
#   ./scripts/incidents/generate-incident-report.sh --incident-name "alert-..." --format html
#   ./scripts/incidents/generate-incident-report.sh --incident-name "alert-..." --output-dir ./reports
# ────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_common.sh
. "${SCRIPT_DIR}/_common.sh"

NAMESPACE="default"
INCIDENT_NAME=""
OUTPUT_DIR=""
FORMAT="md"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace)      NAMESPACE="$2"; shift 2 ;;
    --incident-name)  INCIDENT_NAME="$2"; shift 2 ;;
    --output-dir)     OUTPUT_DIR="$2"; shift 2 ;;
    --format)         FORMAT="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

resolve_context 8080
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
TOKEN="${KUBESYNAPSE_API_TOKEN:-}"

if [[ -z "${INCIDENT_NAME}" && -f /tmp/kubesynapse-last-incident.txt ]]; then
  INCIDENT_NAME="$(cat /tmp/kubesynapse-last-incident.txt | tr -d '[:space:]')"
  info "Reusing last-fired incident: ${INCIDENT_NAME}"
fi

if [[ -z "${INCIDENT_NAME}" ]]; then
  err "No --incident-name provided and no previous incident recorded. Run fire-alertmanager-alert.sh first."
  exit 1
fi

if [[ -z "${OUTPUT_DIR}" ]]; then OUTPUT_DIR="./reports"; fi
mkdir -p "${OUTPUT_DIR}"

SAFE_NAME=$(echo "${INCIDENT_NAME}" | tr -c '[:alnum:]._-' '_')
STAMP="$(date -u +%Y%m%d-%H%M%S)"
MD_PATH="${OUTPUT_DIR}/${SAFE_NAME}-${STAMP}.md"
HTML_PATH="${OUTPUT_DIR}/${SAFE_NAME}-${STAMP}.html"

# ── 1) Fetch incident ─────────────────────────────────────────────
echo ""
echo -e "${CYAN}═══ Fetching incident data ═══${NC}"
INCIDENT_JSON=$(curl -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  --max-time 15 \
  "${GATEWAY_URL}/api/v1/incidents/${INCIDENT_NAME}?namespace=${NAMESPACE}")
echo "${INCIDENT_JSON}" > /tmp/kubesynapse-incident.json

# ── 2) Fetch timeline ──────────────────────────────────────────────
TIMELINE_JSON=$(curl -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  --max-time 15 \
  "${GATEWAY_URL}/api/v1/incidents/${INCIDENT_NAME}/timeline?namespace=${NAMESPACE}" 2>/dev/null || echo '{"timeline":[]}')
echo "${TIMELINE_JSON}" > /tmp/kubesynapse-incident-timeline.json

# ── 3) Fetch workflow run data (if linked) ────────────────────────
RUN_ID=$(python3 -c "import json,sys
d=json.load(open('/tmp/kubesynapse-incident.json'))
print(d.get('workflow_run_id') or '')" 2>/dev/null || true)
WORKFLOW_NAME=$(python3 -c "import json,sys
d=json.load(open('/tmp/kubesynapse-incident.json'))
ref=d.get('workflow_ref') or {}
print(ref.get('name') or '')" 2>/dev/null || true)
RUN_TRACE=""
RUN_LOGS=""

if [[ -n "${RUN_ID}" ]]; then
  if [[ -z "${WORKFLOW_NAME}" ]]; then
    info "workflow_run_id present but workflow_ref name missing — searching workflows list"
    WORKFLOWS_JSON=$(curl -sS -H "Authorization: Bearer ${TOKEN}" --max-time 10 \
      "${GATEWAY_URL}/api/v1/workflows?namespace=${NAMESPACE}" 2>/dev/null || echo "[]")
    WORKFLOW_NAME=$(python3 -c "
import json
d=json.loads('''${WORKFLOWS_JSON}''')
for w in d:
    if w.get('run_id') == '${RUN_ID}':
        print(w.get('name',''))
        break
" 2>/dev/null || true)
  fi
  if [[ -n "${WORKFLOW_NAME}" ]]; then
    info "Linked workflow: ${WORKFLOW_NAME} (run ${RUN_ID})"
    RUN_TRACE=$(curl -sS -H "Authorization: Bearer ${TOKEN}" --max-time 15 \
      "${GATEWAY_URL}/api/v1/workflows/${WORKFLOW_NAME}/runs/${RUN_ID}/trace?namespace=${NAMESPACE}" 2>/dev/null || echo "")
    RUN_LOGS=$(curl -sS -H "Authorization: Bearer ${TOKEN}" --max-time 15 \
      "${GATEWAY_URL}/api/v1/workflows/${WORKFLOW_NAME}/logs?namespace=${NAMESPACE}&runId=${RUN_ID}" 2>/dev/null || echo "")
  else
    warn "workflow_run_id present but workflow name could not be resolved; run trace will be omitted."
  fi
fi

# ── 4) Render Markdown via Python (no external deps beyond stdlib) ─
python3 - <<PY > "${MD_PATH}"
import json
from pathlib import Path
from datetime import datetime, timezone

incident = json.loads(Path('/tmp/kubesynapse-incident.json').read_text())
timeline = (json.loads(Path('/tmp/kubesynapse-incident-timeline.json').read_text()).get('timeline') or [])
run_trace_str = """${RUN_TRACE}""".strip()
run_logs_str = """${RUN_LOGS}""".strip()
run_id = "${RUN_ID}"
workflow_name = "${WORKFLOW_NAME}"

def esc(s):
    if s is None: return ''
    return str(s).replace('|','\\|').replace('\\n',' ')

sev_emoji = {"critical":"🔴","warning":"🟡","info":"🔵"}.get(incident.get("severity"),"⚪")
st_emoji  = {"firing":"🔥","acknowledged":"👀","diagnosing":"🧪",
             "remediated":"🛠️","resolved":"✅","closed":"📦","escalated":"📈"}.get(incident.get("status"),"⚪")

lines = []
lines.append(f"# Incident Report — {incident.get('title','')}")
lines.append("")
lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
lines.append("Reporter: ${USER:-$(id -un)} @ $(hostname)")
lines.append("")
lines.append("## Summary")
lines.append("")
lines.append("| Field | Value |")
lines.append("| --- | --- |")
lines.append(f"| Status | {st_emoji} {incident.get('status','')} |")
lines.append(f"| Severity | {sev_emoji} {incident.get('severity','')} |")
lines.append(f"| Source | {incident.get('source','')} |")
lines.append(f"| Namespace | {incident.get('namespace','')} |")
lines.append(f"| Name | `{incident.get('name','')}` |")
lines.append(f"| Assigned agent | {incident.get('assigned_agent') or 'unassigned'} |")
lines.append(f"| Escalation timeout | {incident.get('escalation_timeout_minutes','?')} min |")
lines.append(f"| Auto-acknowledge | {incident.get('auto_acknowledge')} |")
lines.append(f"| Created | {incident.get('created_at','')} |")
lines.append(f"| Updated | {incident.get('updated_at','')} |")
if incident.get("acknowledged_at"): lines.append(f"| Acknowledged | {incident['acknowledged_at']} |")
if incident.get("resolved_at"):      lines.append(f"| Resolved | {incident['resolved_at']} |")
if incident.get("workflow_run_id"):  lines.append(f"| Workflow run | `{incident['workflow_run_id']}` |")
lines.append("")

if incident.get("description"):
    lines.append("## Description")
    lines.append("")
    lines.append(incident["description"])
    lines.append("")

if incident.get("labels"):
    lines.append("## Labels")
    lines.append("")
    lines.append("| Key | Value |")
    lines.append("| --- | --- |")
    for k,v in incident["labels"].items():
        lines.append(f"| {k} | `{v}` |")
    lines.append("")

if incident.get("annotations"):
    lines.append("## Annotations")
    lines.append("")
    for k,v in incident["annotations"].items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")

lines.append("## Timeline")
lines.append("")
if not timeline:
    lines.append("_No timeline events recorded._")
else:
    lines.append("| Time | Event | Message |")
    lines.append("| --- | --- | --- |")
    for e in timeline:
        lines.append(f"| {e.get('timestamp','')} | {e.get('event','')} | {esc(e.get('message',''))} |")
lines.append("")

if run_trace_str:
    lines.append(f"## Workflow Run Trace — {workflow_name}")
    lines.append("")
    try:
        rt = json.loads(run_trace_str)
        activities = rt.get("activities") or rt.get("steps") or []
        if activities:
            for a in activities:
                name = a.get("name") or a.get("stepName") or "unknown"
                status = a.get("status") or a.get("phase") or "unknown"
                lines.append(f"### Step: {name}")
                lines.append("")
                lines.append(f"- Status: {status}")
                if a.get("startedAt"):   lines.append(f"- Started: {a['startedAt']}")
                if a.get("completedAt"): lines.append(f"- Completed: {a['completedAt']}")
                if a.get("output"):
                    lines.append("")
                    lines.append("```json")
                    lines.append(json.dumps(a["output"], indent=2))
                    lines.append("```")
                if a.get("error"):
                    lines.append(f"- Error: `{a['error']}`")
                lines.append("")
        else:
            lines.append("```json")
            lines.append(json.dumps(rt, indent=2))
            lines.append("```")
            lines.append("")
    except json.JSONDecodeError:
        lines.append("```")
        lines.append(run_trace_str)
        lines.append("```")
        lines.append("")

if run_logs_str:
    lines.append("## Workflow Logs")
    lines.append("")
    lines.append("<details><summary>Click to expand</summary>")
    lines.append("")
    lines.append("```")
    lines.append(run_logs_str)
    lines.append("```")
    lines.append("")
    lines.append("</details>")
    lines.append("")

lines.append("---")
lines.append("_Generated by `scripts/incidents/generate-incident-report.sh`_")
print("\n".join(lines))
PY

ok "Wrote Markdown report:"
echo "       ${MD_PATH}"

# ── 5) Optionally render HTML ──────────────────────────────────────
if [[ "${FORMAT}" == "html" || "${FORMAT}" == "both" ]]; then
  python3 - <<PY > "${HTML_PATH}"
import re, html, sys
from pathlib import Path
md = Path("${MD_PATH}").read_text(encoding='utf-8')
title = re.search(r'^# (.+)$', md, re.MULTILINE)
title = title.group(1) if title else "Incident Report"

text = html.escape(md)
def codeblock(m):
    return '<pre><code>' + m.group(1) + '</code></pre>'
text = re.sub(r'(?ms)\n```\n(.*?)\n```', codeblock, text)
text = re.sub(r'^###### (.+)$', r'<h6>\1</h6>', text, flags=re.MULTILINE)
text = re.sub(r'^##### (.+)$',  r'<h5>\1</h5>', text, flags=re.MULTILINE)
text = re.sub(r'^#### (.+)$',   r'<h4>\1</h4>', text, flags=re.MULTILINE)
text = re.sub(r'^### (.+)$',    r'<h3>\1</h3>', text, flags=re.MULTILINE)
text = re.sub(r'^## (.+)$',     r'<h2>\1</h2>', text, flags=re.MULTILINE)
text = re.sub(r'^# (.+)$',      r'<h1>\1</h1>', text, flags=re.MULTILINE)
text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
text = re.sub(r'\*([^*]+)\*',     r'<em>\1</em>', text)
text = re.sub(r'\`([^\`]+)\`',    r'<code>\1</code>', text)
text = re.sub(r'(?m)^- (.+)$',    r'<li>\1</li>', text)
text = re.sub(r'(?ms)(<li>.*?</li>(?:\s*<li>.*?</li>)*)', r'<ul>\1</ul>', text)
text = re.sub(r'\n{2,}',          '</p><p>', text)
text = text.replace('\n', '<br>')
print(f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>")
print("<style>body{font:14px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:920px;margin:32px auto;padding:0 16px;color:#1f2937;background:#fff}h1,h2,h3{border-bottom:1px solid #e5e7eb;padding-bottom:4px}h1{font-size:1.8rem}h2{font-size:1.3rem}table{border-collapse:collapse;width:100%;margin:12px 0}th,td{border:1px solid #e5e7eb;padding:6px 10px;text-align:left}th{background:#f9fafb}code{background:#f3f4f6;padding:1px 4px;border-radius:3px}pre{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:6px;overflow-x:auto}pre code{background:transparent;color:inherit}details{background:#f8fafc;border:1px solid #e5e7eb;border-radius:6px;padding:8px 12px}</style>")
print("</head><body><p>")
print(text)
print("</p></body></html>")
PY
  ok "Wrote HTML report:"
  echo "       ${HTML_PATH}"
fi

echo ""
echo -e "${CYAN}Done. Share the Markdown file with responders or paste it into a ticket.${NC}"
