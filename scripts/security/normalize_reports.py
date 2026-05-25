#!/usr/bin/env python3
"""
normalize_reports.py

Reads raw scanner outputs from security-reports/raw/ and produces:
  - security-reports/normalized/remediation-report.json
  - security-reports/summary.md

Handles missing files gracefully and continues if a parser fails.

Supported scanners:
  bandit        → security-reports/raw/bandit.json
  semgrep       → security-reports/raw/semgrep.json
  gitleaks      → security-reports/raw/gitleaks.json
  trivy-fs      → security-reports/raw/trivy-fs.json
  trivy-config  → security-reports/raw/trivy-config.json
  pip-audit     → security-reports/raw/pip-audit.json
  osv-scanner   → security-reports/raw/osv-scanner.json
  kube-score    → security-reports/raw/kube-score.json
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "security-reports" / "raw"
NORMALIZED_DIR = REPO_ROOT / "security-reports" / "normalized"
SUMMARY_PATH = REPO_ROOT / "security-reports" / "summary.md"

# ---------------------------------------------------------------------------
# Component inference
# ---------------------------------------------------------------------------

KNOWN_COMPONENTS = [
    "api-gateway",
    "operator",
    "web-ui",
    "charts",
    "deploy",
    "collector-agent",
    "mcp-sidecars",
    "pi-runtime",
    "opencode-runtime",
    "vibe-runtime",
    "cli",
    "clients",
    "catalog",
    "tests",
]


def infer_component(file_path: str | None) -> str:
    """Return the top-level component name from a file path."""
    if not file_path:
        return "root"
    parts = Path(file_path.lstrip("/")).parts
    if parts:
        candidate = parts[0]
        if candidate in KNOWN_COMPONENTS:
            return candidate
    return "root"


# ---------------------------------------------------------------------------
# Severity normalisation
# ---------------------------------------------------------------------------

_SEVERITY_MAP = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "moderate": "MEDIUM",
    "low": "LOW",
    "informational": "INFO",
    "info": "INFO",
    "note": "INFO",
    "warning": "LOW",
    "warn": "LOW",
    "error": "HIGH",
}


def norm_severity(raw: str | None) -> str:
    if not raw:
        return "UNKNOWN"
    return _SEVERITY_MAP.get(str(raw).lower(), str(raw).upper())


# ---------------------------------------------------------------------------
# ai_fix_strategy heuristic
# ---------------------------------------------------------------------------

def ai_fix_strategy(severity: str, category: str, message: str) -> str:
    """Return a coarse AI-fix strategy label."""
    msg_lower = (message or "").lower()
    if category == "secret" or any(k in msg_lower for k in ("hardcoded", "secret", "password", "token", "credential")):
        return "rotate_and_remove"
    if category in ("dependency", "supply-chain"):
        return "bump_dependency"
    if severity in ("CRITICAL", "HIGH") and category == "code":
        return "targeted_code_fix"
    if category in ("kubernetes", "helm"):
        return "manifest_patch"
    return "review_and_fix"


# ---------------------------------------------------------------------------
# Confidence heuristic
# ---------------------------------------------------------------------------

def confidence_from_scanner(scanner: str, severity: str) -> str:
    high_conf_scanners = {"bandit", "codeql", "semgrep"}
    if scanner in high_conf_scanners and severity in ("CRITICAL", "HIGH"):
        return "HIGH"
    if scanner in high_conf_scanners:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Finding dataclass helper
# ---------------------------------------------------------------------------

def make_finding(
    scanner: str,
    rule_id: str,
    severity: str,
    title: str,
    message: str,
    file_path: str | None,
    line: int | None,
    component: str,
    category: str,
    recommendation: str,
    evidence: Any = None,
) -> dict:
    sev = norm_severity(severity)
    return {
        "scanner": scanner,
        "rule_id": rule_id or "",
        "severity": sev,
        "title": title or "",
        "message": message or "",
        "file": file_path or "",
        "line": line,
        "component": component,
        "category": category,
        "recommendation": recommendation or "",
        "ai_fix_strategy": ai_fix_strategy(sev, category, message or ""),
        "confidence": confidence_from_scanner(scanner, sev),
        "raw_evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Parser: Bandit
# ---------------------------------------------------------------------------

def parse_bandit(data: dict) -> list[dict]:
    findings = []
    for result in data.get("results", []):
        fp = result.get("filename", "")
        findings.append(
            make_finding(
                scanner="bandit",
                rule_id=result.get("test_id", ""),
                severity=result.get("issue_severity", ""),
                title=result.get("test_name", result.get("issue_text", "")),
                message=result.get("issue_text", ""),
                file_path=fp,
                line=result.get("line_number"),
                component=infer_component(fp),
                category="code",
                recommendation=result.get("more_info", "See Bandit docs for remediation"),
                evidence={
                    "code": result.get("code", ""),
                    "confidence": result.get("issue_confidence", ""),
                },
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Parser: Semgrep
# ---------------------------------------------------------------------------

def parse_semgrep(data: dict) -> list[dict]:
    findings = []
    for result in data.get("results", []):
        fp = result.get("path", "")
        extra = result.get("extra", {})
        meta = extra.get("metadata", {})
        findings.append(
            make_finding(
                scanner="semgrep",
                rule_id=result.get("check_id", ""),
                severity=extra.get("severity", ""),
                title=result.get("check_id", ""),
                message=extra.get("message", ""),
                file_path=fp,
                line=result.get("start", {}).get("line"),
                component=infer_component(fp),
                category=meta.get("category", "code"),
                recommendation=meta.get("fix", meta.get("references", [""])[0] if meta.get("references") else ""),
                evidence={"lines": extra.get("lines", "")},
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Parser: Gitleaks
# ---------------------------------------------------------------------------

def parse_gitleaks(data: list) -> list[dict]:
    findings = []
    if not isinstance(data, list):
        return findings
    for result in data:
        fp = result.get("File", "")
        findings.append(
            make_finding(
                scanner="gitleaks",
                rule_id=result.get("RuleID", ""),
                severity="HIGH",
                title=f"Secret detected: {result.get('Description', result.get('RuleID', ''))}",
                message=result.get("Description", ""),
                file_path=fp,
                line=result.get("StartLine"),
                component=infer_component(fp),
                category="secret",
                recommendation="Remove the secret from source, rotate it immediately, and use environment variables or a secrets manager.",
                evidence={
                    "match": result.get("Match", ""),
                    "commit": result.get("Commit", ""),
                    "author": result.get("Author", ""),
                    "date": result.get("Date", ""),
                },
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Parser: Trivy (filesystem or config)
# ---------------------------------------------------------------------------

def parse_trivy(data: dict, scanner_name: str = "trivy") -> list[dict]:
    findings = []

    def _category_from_class(vuln_type: str) -> str:
        mapping = {
            "os-pkgs": "dependency",
            "lang-pkgs": "dependency",
            "config": "kubernetes",
            "secret": "secret",
        }
        return mapping.get(vuln_type, "dependency")

    for result in data.get("Results", []):
        target = result.get("Target", "")
        vuln_type = result.get("Class", result.get("Type", ""))
        cat = _category_from_class(vuln_type)

        # Vulnerabilities (CVEs)
        for vuln in result.get("Vulnerabilities", []) or []:
            pkg = vuln.get("PkgName", "")
            cve_id = vuln.get("VulnerabilityID", "")
            findings.append(
                make_finding(
                    scanner=scanner_name,
                    rule_id=cve_id,
                    severity=vuln.get("Severity", ""),
                    title=f"{cve_id} in {pkg}",
                    message=vuln.get("Description", vuln.get("Title", "")),
                    file_path=target,
                    line=None,
                    component=infer_component(target),
                    category=cat,
                    recommendation=vuln.get("FixedVersion")
                    and f"Upgrade {pkg} to {vuln['FixedVersion']}"
                    or "No fix available yet; monitor for updates.",
                    evidence={
                        "package": pkg,
                        "installed_version": vuln.get("InstalledVersion", ""),
                        "fixed_version": vuln.get("FixedVersion", ""),
                        "cvss": vuln.get("CVSS", {}),
                        "references": vuln.get("References", [])[:3],
                    },
                )
            )

        # Misconfigurations
        for mis in result.get("Misconfigurations", []) or []:
            findings.append(
                make_finding(
                    scanner=scanner_name,
                    rule_id=mis.get("ID", ""),
                    severity=mis.get("Severity", ""),
                    title=mis.get("Title", mis.get("ID", "")),
                    message=mis.get("Description", ""),
                    file_path=target,
                    line=mis.get("CauseMetadata", {}).get("StartLine"),
                    component=infer_component(target),
                    category="kubernetes" if "kube" in vuln_type.lower() or "config" in vuln_type.lower() else "iac",
                    recommendation=mis.get("Resolution", ""),
                    evidence={
                        "message": mis.get("Message", ""),
                        "references": mis.get("References", [])[:3],
                    },
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Parser: pip-audit (wrapped format produced by the workflow)
# ---------------------------------------------------------------------------

def parse_pip_audit(data: dict) -> list[dict]:
    findings = []
    for entry in data.get("results", []):
        component = entry.get("component", "root")
        req_file = entry.get("requirement", "")
        inner = entry.get("findings", {})
        # pip-audit JSON format: list of dicts with "name", "version", "vulns"
        for pkg_info in inner if isinstance(inner, list) else []:
            pkg_name = pkg_info.get("name", "")
            pkg_ver = pkg_info.get("version", "")
            for vuln in pkg_info.get("vulns", []):
                vuln_id = vuln.get("id", "")
                fix_versions = vuln.get("fix_versions", [])
                findings.append(
                    make_finding(
                        scanner="pip-audit",
                        rule_id=vuln_id,
                        severity="HIGH",
                        title=f"{vuln_id} in {pkg_name}=={pkg_ver}",
                        message=vuln.get("description", ""),
                        file_path=req_file,
                        line=None,
                        component=component,
                        category="dependency",
                        recommendation=f"Upgrade {pkg_name} to {fix_versions[0]}" if fix_versions else "No fix available; consider an alternative.",
                        evidence={
                            "package": pkg_name,
                            "installed_version": pkg_ver,
                            "fix_versions": fix_versions,
                            "aliases": vuln.get("aliases", []),
                        },
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Parser: OSV-Scanner
# ---------------------------------------------------------------------------

def parse_osv_scanner(data: dict) -> list[dict]:
    findings = []
    for result in data.get("results", []):
        source = result.get("source", {})
        req_file = source.get("path", "")
        component = infer_component(req_file)
        for pkg in result.get("packages", []):
            pkg_info = pkg.get("package", {})
            pkg_name = pkg_info.get("name", "")
            pkg_ver = pkg_info.get("version", "")
            ecosystem = pkg_info.get("ecosystem", "")
            for vuln in pkg.get("vulnerabilities", []):
                vuln_id = vuln.get("id", "")
                aliases = vuln.get("aliases", [])
                severity_list = vuln.get("database_specific", {}).get("severity", "") or ""
                all_ids = ", ".join([vuln_id] + aliases[:3])
                findings.append(
                    make_finding(
                        scanner="osv-scanner",
                        rule_id=vuln_id,
                        severity=severity_list or "MEDIUM",
                        title=f"{vuln_id} in {pkg_name}@{pkg_ver} ({ecosystem})",
                        message=vuln.get("summary", vuln.get("details", "")),
                        file_path=req_file,
                        line=None,
                        component=component,
                        category="dependency",
                        recommendation=f"Check fix versions for {pkg_name} ({all_ids})",
                        evidence={
                            "package": pkg_name,
                            "version": pkg_ver,
                            "ecosystem": ecosystem,
                            "aliases": aliases[:5],
                        },
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Parser: kube-score
# ---------------------------------------------------------------------------

def parse_kube_score(data: list) -> list[dict]:
    findings = []
    if not isinstance(data, list):
        return findings
    for obj in data:
        obj_name = obj.get("object_name", "")
        obj_type = obj.get("type_meta", {}).get("kind", "")
        for check in obj.get("checks", []):
            if check.get("grade", 10) >= 5:
                continue  # Only collect failed/warning checks
            check_name = check.get("check", {}).get("name", "")
            check_id = check.get("check", {}).get("id", check_name)
            for comment in check.get("comments", []):
                summary = comment.get("summary", "")
                description = comment.get("description", "")
                findings.append(
                    make_finding(
                        scanner="kube-score",
                        rule_id=check_id,
                        severity="MEDIUM" if check.get("grade", 0) >= 3 else "HIGH",
                        title=f"{check_name} — {obj_type}/{obj_name}",
                        message=summary or description,
                        file_path=f"charts/kubesynapse (rendered/{obj_type}/{obj_name})",
                        line=None,
                        component="charts",
                        category="kubernetes",
                        recommendation=description or summary,
                        evidence={
                            "object": f"{obj_type}/{obj_name}",
                            "check": check_name,
                            "grade": check.get("grade"),
                        },
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Load JSON safely
# ---------------------------------------------------------------------------

def load_json(path: Path) -> Any | None:
    if not path.exists():
        print(f"[skip] {path.name} not found", file=sys.stderr)
        return None
    try:
        with path.open() as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Could not parse {path.name}: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Main aggregation
# ---------------------------------------------------------------------------

def collect_findings() -> list[dict]:
    all_findings: list[dict] = []

    def _try(parser, data, label: str) -> None:
        if data is None:
            return
        try:
            found = parser(data)
            print(f"[{label}] {len(found)} finding(s)", file=sys.stderr)
            all_findings.extend(found)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] Parser failed for {label}: {exc}", file=sys.stderr)

    _try(parse_bandit, load_json(RAW_DIR / "bandit.json"), "bandit")
    _try(parse_semgrep, load_json(RAW_DIR / "semgrep.json"), "semgrep")

    gitleaks_raw = load_json(RAW_DIR / "gitleaks.json")
    _try(parse_gitleaks, gitleaks_raw, "gitleaks")

    _try(lambda d: parse_trivy(d, "trivy-fs"), load_json(RAW_DIR / "trivy-fs.json"), "trivy-fs")
    _try(lambda d: parse_trivy(d, "trivy-config"), load_json(RAW_DIR / "trivy-config.json"), "trivy-config")
    _try(parse_pip_audit, load_json(RAW_DIR / "pip-audit.json"), "pip-audit")
    _try(parse_osv_scanner, load_json(RAW_DIR / "osv-scanner.json"), "osv-scanner")
    _try(parse_kube_score, load_json(RAW_DIR / "kube-score.json"), "kube-score")

    return all_findings


# ---------------------------------------------------------------------------
# Severity sort key
# ---------------------------------------------------------------------------

_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4, "UNKNOWN": 5}


def sev_key(finding: dict) -> int:
    return _SEV_ORDER.get(finding.get("severity", "UNKNOWN"), 5)


# ---------------------------------------------------------------------------
# Markdown summary generator
# ---------------------------------------------------------------------------

def generate_summary(findings: list[dict]) -> str:
    from collections import Counter

    total = len(findings)
    sev_counts: Counter = Counter(f["severity"] for f in findings)
    scanner_counts: Counter = Counter(f["scanner"] for f in findings)
    component_counts: Counter = Counter(f["component"] for f in findings)

    lines = [
        "# Security Scan Summary",
        "",
        f"_Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}_",
        "",
        f"**Total findings:** {total}",
        "",
        "## Findings by Severity",
        "",
        "| Severity | Count |",
        "|----------|-------|",
    ]
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "UNKNOWN"):
        count = sev_counts.get(sev, 0)
        if count:
            lines.append(f"| {sev} | {count} |")

    lines += [
        "",
        "## Findings by Scanner",
        "",
        "| Scanner | Count |",
        "|---------|-------|",
    ]
    for scanner, count in scanner_counts.most_common():
        lines.append(f"| {scanner} | {count} |")

    lines += [
        "",
        "## Findings by Component",
        "",
        "| Component | Count |",
        "|-----------|-------|",
    ]
    for component, count in component_counts.most_common(10):
        lines.append(f"| {component} | {count} |")

    # Top 20 critical/high findings
    top = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH")][:20]
    if top:
        lines += [
            "",
            "## Top Critical / High Findings",
            "",
            "| # | Scanner | Severity | Component | Title |",
            "|---|---------|----------|-----------|-------|",
        ]
        for i, f in enumerate(top, 1):
            title = (f["title"] or f["message"] or "")[:80]
            title = title.replace("|", "\\|")
            lines.append(
                f"| {i} | {f['scanner']} | {f['severity']} | {f['component']} | {title} |"
            )

    lines += [
        "",
        "## AI Remediation Strategy Distribution",
        "",
        "| Strategy | Count |",
        "|----------|-------|",
    ]
    strategy_counts: Counter = Counter(f.get("ai_fix_strategy", "review_and_fix") for f in findings)
    for strategy, count in strategy_counts.most_common():
        lines.append(f"| {strategy} | {count} |")

    lines += [
        "",
        "---",
        "_See `security-reports/normalized/remediation-report.json` for full machine-readable data._",
    ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)

    findings = collect_findings()
    findings.sort(key=sev_key)

    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_findings": len(findings),
        "findings": findings,
    }

    report_path = NORMALIZED_DIR / "remediation-report.json"
    with report_path.open("w") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"[ok] Wrote {report_path} ({len(findings)} findings)", file=sys.stderr)

    summary = generate_summary(findings)
    with SUMMARY_PATH.open("w") as fh:
        fh.write(summary)
    print(f"[ok] Wrote {SUMMARY_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
