# GDPR Compliance Auditor

Three AI agents scan a codebase for PII exposure, classify findings by
GDPR article and risk level, and produce a compliance report.

## Architecture

```
gdpr-scanner ──► gdpr-classifier ──► gdpr-report-writer
  (Step 1)         (Step 2)             (Step 3)
                                       │
                                  ┌────▼─────┐
                                  │  VERIFY:  │
                                  │  report-  │
                                  │  writer   │ (Step 4 — self-verify)
                                  └──────────┘
```

| Agent | Role | MCP |
|-------|------|-----|
| `gdpr-scanner` | Scans code for PII patterns (emails, SSNs, credit cards, IPs, phone numbers) | code-exec |
| `gdpr-classifier` | Classifies each finding by GDPR article + risk level | code-exec |
| `gdpr-report-writer` | Generates compliance report + self-verifies completeness | code-exec |

## Workflow

```
1. scan-codebase     →  findings.json
2. classify-findings →  classified-findings.json
3. generate-report   →  compliance-report.md
4. verify-report     →  compliance-report.md (verified + signed)
```

## Sample Data (Built-In)

The `project-context.yaml` includes 4 fake source files containing PII:
- `src/auth/users.py` — hardcoded admin credentials, exposed emails
- `src/api/customer_export.py` — CSV export with unmasked credit cards
- `src/logging/request_logger.py` — logs full IP addresses and user agents
- `src/analytics/tracker.py` — sends PII to third-party analytics without consent

No real data. All files are synthetic examples of common GDPR violations.

## Quick Deploy

```powershell
Set-Location ./examples/gdpr-compliance-auditor
pwsh ./deploy.ps1
```

## Trigger

```bash
agentctl workflows trigger gdpr-compliance-audit
```

## Output

`compliance-report.md` in the `gdpr-report-writer` workspace includes:
- Executive summary with risk score
- Per-file findings table (PII type, count, GDPR article, severity)
- Remediation recommendations
- Verification signature
