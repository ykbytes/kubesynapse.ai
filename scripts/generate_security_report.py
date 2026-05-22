#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def read_json(path: Path):
    with path.open() as f:
        return json.load(f)


def read_statuses(results_dir: Path) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for path in sorted(results_dir.glob("*.status")):
        statuses[path.stem] = path.read_text().strip()
    return statuses


def escape(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def table(headers: list[str], rows: list[list[object]]) -> list[str]:
    if not rows:
        return ["No findings.\n"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(escape(cell) for cell in row) + " |")
    lines.append("")
    return lines


def add_section(lines: list[str], title: str, count: int, rows: list[list[object]], headers: list[str]) -> None:
    lines.append(f"## {title} ({count})\n")
    lines.extend(table(headers, rows))


def find_first(results_dir: Path, *names: str) -> Path | None:
    for name in names:
        path = results_dir / name
        if path.exists():
            return path
    return None


def bandit_findings(results_dir: Path):
    path = find_first(results_dir, "bandit.json")
    if not path:
        return [], "not found"
    data = read_json(path)
    rows = []
    for item in data.get("results", []):
        rows.append(
            [
                item.get("issue_severity"),
                item.get("test_id"),
                f"{item.get('filename')}:{item.get('line_number')}",
                item.get("issue_text"),
            ]
        )
    return rows, "ok"


def pip_audit_findings(results_dir: Path):
    rows: list[list[object]] = []
    for path in sorted(results_dir.glob("pip-audit-*.json")):
        project = path.stem.removeprefix("pip-audit-")
        data = read_json(path)
        dependencies = data.get("dependencies", data if isinstance(data, list) else [])
        for dep in dependencies:
            for vuln in dep.get("vulns", []):
                rows.append(
                    [
                        project,
                        dep.get("name"),
                        dep.get("version"),
                        vuln.get("id"),
                        ", ".join(vuln.get("fix_versions", [])) or "none",
                    ]
                )
    return rows, "ok"


def npm_audit_findings(results_dir: Path):
    rows: list[list[object]] = []
    for name in ("web-ui", "typescript"):
        path = results_dir / f"npm-audit-{name}.json"
        if not path.exists():
            continue
        data = read_json(path)
        vulnerabilities = data.get("vulnerabilities", {})
        for package_name, vuln in sorted(vulnerabilities.items()):
            via = vuln.get("via", [])
            advisory_rows = [entry for entry in via if isinstance(entry, dict)]
            if advisory_rows:
                for advisory in advisory_rows:
                    rows.append(
                        [
                            name,
                            package_name,
                            advisory.get("severity", vuln.get("severity")),
                            advisory.get("title"),
                            advisory.get("url"),
                            vuln.get("fixAvailable"),
                        ]
                    )
            else:
                rows.append([name, package_name, vuln.get("severity"), "transitive advisory", "", vuln.get("fixAvailable")])
    return rows, "ok"


def trivy_findings(results_dir: Path, name: str):
    path = find_first(results_dir, f"{name}-fixed.json", f"{name}.json")
    if not path:
        return [], "not found"
    data = read_json(path)
    rows = []
    for result in data.get("Results", []):
        for vuln in result.get("Vulnerabilities") or []:
            severity = vuln.get("Severity")
            if severity not in {"HIGH", "CRITICAL"}:
                continue
            rows.append(
                [
                    result.get("Target"),
                    vuln.get("PkgName"),
                    vuln.get("InstalledVersion"),
                    vuln.get("VulnerabilityID"),
                    severity,
                    vuln.get("FixedVersion") or "none",
                ]
            )
    return rows, "ok"


def kube_linter_findings(results_dir: Path):
    path = find_first(results_dir, "kube-linter-fixed.json", "kube-linter.json")
    if not path:
        return [], "not found"
    data = read_json(path)
    rows = []
    for report in data.get("Reports", []):
        obj = report.get("Object", {}).get("K8sObject", {})
        rows.append(
            [
                report.get("Check"),
                obj.get("GroupVersionKind", {}).get("Kind"),
                obj.get("Name"),
                report.get("Diagnostic", {}).get("Message"),
            ]
        )
    return rows, "ok"


def checkov_findings(results_dir: Path, name: str):
    path = find_first(results_dir, f"{name}.json")
    if not path:
        return [], "not found"
    data = read_json(path)
    rows = []
    for check in data.get("results", {}).get("failed_checks", []):
        rows.append(
            [
                check.get("check_id"),
                check.get("resource"),
                check.get("check_name"),
                check.get("file_path"),
            ]
        )
    return rows, "ok"


def trufflehog_findings(results_dir: Path):
    path = find_first(results_dir, "trufflehog.json")
    if not path:
        return [], "not found"
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            item = json.loads(line)
            source = item.get("SourceMetadata", {}).get("Data", {}).get("Filesystem", {}).get("file", "")
            if "DetectorName" in item:
                rows.append(
                    [
                        item.get("DetectorName"),
                        source,
                        item.get("Verified"),
                        item.get("Raw"),
                    ]
                )
    return rows, "ok"


def execution_notes(statuses: dict[str, str]) -> list[list[object]]:
    rows: list[list[object]] = []
    for name, status in sorted(statuses.items()):
        if status in {"0", "skipped"}:
            continue
        rows.append([name, status])
    return rows


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: generate_security_report.py <results_dir> <output_md>", file=sys.stderr)
        return 2

    results_dir = Path(sys.argv[1]).resolve()
    output_path = Path(sys.argv[2]).resolve()
    statuses = read_statuses(results_dir)

    sections = [
        ("Bandit", ["Severity", "Rule", "Location", "Issue"], *bandit_findings(results_dir)),
        ("pip-audit", ["Project", "Package", "Version", "Advisory", "Fixed Version"], *pip_audit_findings(results_dir)),
        ("npm audit", ["Project", "Package", "Severity", "Advisory", "URL", "Fix Available"], *npm_audit_findings(results_dir)),
        ("Trivy filesystem", ["Target", "Package", "Version", "Advisory", "Severity", "Fixed Version"], *trivy_findings(results_dir, "trivy-fs")),
        ("Trivy image api-gateway", ["Target", "Package", "Version", "Advisory", "Severity", "Fixed Version"], *trivy_findings(results_dir, "trivy-image-api-gateway")),
        ("Trivy image operator", ["Target", "Package", "Version", "Advisory", "Severity", "Fixed Version"], *trivy_findings(results_dir, "trivy-image-operator")),
        ("Trivy image web-ui", ["Target", "Package", "Version", "Advisory", "Severity", "Fixed Version"], *trivy_findings(results_dir, "trivy-image-web-ui")),
        ("kube-linter", ["Check", "Kind", "Object", "Message"], *kube_linter_findings(results_dir)),
        ("checkov Helm", ["Check", "Resource", "Message", "File"], *checkov_findings(results_dir, "checkov-helm-kind")),
        ("checkov Kubernetes", ["Check", "Resource", "Message", "File"], *checkov_findings(results_dir, "checkov-k8s-fixed3")),
        ("TruffleHog", ["Detector", "Location", "Verified", "Raw"], *trufflehog_findings(results_dir)),
    ]

    lines = [
        "# Security Report\n",
        f"- Generated: {datetime.now(UTC).isoformat()}\n",
        f"- Results directory: `{results_dir}`\n",
        "- Scope: local equivalent run of the repository security workflow tools\n",
        "\n## Summary\n",
    ]

    summary_rows = []
    for title, _headers, rows, state in sections:
        summary_rows.append([title, len(rows), state])
    lines.extend(table(["Tool", "Findings", "State"], summary_rows))

    non_zero_status_rows = execution_notes(statuses)
    if non_zero_status_rows:
        lines.append("## Execution Notes\n")
        lines.extend(table(["Command", "Status"], non_zero_status_rows))

    for title, headers, rows, _state in sections:
        add_section(lines, title, len(rows), rows, headers)

    bandit_rows, _ = bandit_findings(results_dir)
    if bandit_rows:
        severity_counts = Counter(row[0] for row in bandit_rows)
        lines.append("## Bandit Severity Totals\n")
        lines.extend(table(["Severity", "Count"], [[k, v] for k, v in sorted(severity_counts.items())]))

    output_path.write_text("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
