#!/usr/bin/env python3
"""Build a JSON skills catalog index from a skills repository.

Scans a directory of skill folders, parses each SKILL.md for YAML frontmatter,
and writes a catalog/skills-catalog.json file suitable for mounting as a ConfigMap.

Usage:
    python scripts/build-catalog-index.py [--skills-dir DIR] [--output FILE]
"""

import argparse
import json
import os
import re
import sys

CATEGORY_MAP: dict[str, str] = {
    "pdf": "document",
    "docx": "document",
    "xlsx": "document",
    "pptx": "document",
    "doc-coauthoring": "document",
    "canvas-design": "design",
    "frontend-design": "design",
    "theme-factory": "design",
    "brand-guidelines": "design",
    "web-artifacts-builder": "design",
    "algorithmic-art": "design",
    "mcp-builder": "development",
    "claude-api": "development",
    "webapp-testing": "development",
    "internal-comms": "communication",
    "slack-gif-creator": "communication",
    "skill-creator": "productivity",
}


def infer_category(skill_id: str, description: str) -> str:
    if skill_id in CATEGORY_MAP:
        return CATEGORY_MAP[skill_id]
    text = f"{skill_id} {description}".lower()
    if any(k in text for k in ("pdf", "doc", "xlsx", "pptx", "spreadsheet", "office")):
        return "document"
    if any(k in text for k in ("design", "theme", "brand", "art", "canvas")):
        return "design"
    if any(k in text for k in ("code", "build", "test", "api", "mcp")):
        return "development"
    if any(k in text for k in ("slack", "email", "comms", "messaging")):
        return "communication"
    return "general"


def split_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from Markdown content."""
    try:
        import yaml as _yaml
    except ImportError:
        _yaml = None

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
    if not match:
        return {}, content

    raw_fm = match.group(1)
    body = match.group(2)

    if _yaml is not None:
        try:
            metadata = _yaml.safe_load(raw_fm) or {}
        except Exception:
            metadata = {}
    else:
        metadata = {}
        for line in raw_fm.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                metadata[key.strip()] = value.strip().strip('"').strip("'")

    return metadata if isinstance(metadata, dict) else {}, body


def scan_bundled_assets(skill_dir: str) -> list[str]:
    """List non-SKILL.md files in a skill directory (relative paths)."""
    assets: list[str] = []
    for root, _dirs, files in os.walk(skill_dir):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), skill_dir).replace("\\", "/")
            if rel.upper() not in ("SKILL.MD", "LICENSE.TXT"):
                assets.append(rel)
    return sorted(assets)


def build_catalog(skills_dir: str) -> list[dict]:
    catalog: list[dict] = []
    if not os.path.isdir(skills_dir):
        print(f"ERROR: skills directory not found: {skills_dir}", file=sys.stderr)
        sys.exit(1)

    for entry in sorted(os.listdir(skills_dir)):
        skill_path = os.path.join(skills_dir, entry)
        if not os.path.isdir(skill_path):
            continue

        skill_md = os.path.join(skill_path, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue

        with open(skill_md, encoding="utf-8") as fh:
            content = fh.read()

        metadata, body = split_frontmatter(content)
        name = metadata.get("name", entry)
        description = metadata.get("description", "")
        license_info = metadata.get("license", "")

        preview = body.strip()[:300].strip()
        if len(body.strip()) > 300:
            preview += "..."

        assets = scan_bundled_assets(skill_path)

        skill_files: dict[str, str] = {}
        skill_files[f"catalog/{entry}/SKILL.md"] = content

        catalog.append({
            "id": entry,
            "name": str(name),
            "description": str(description),
            "license": str(license_info),
            "category": infer_category(entry, str(description)),
            "source": "anthropics/skills",
            "instructions_preview": preview,
            "bundled_assets": assets,
            "files": skill_files,
            "allowed_mcp_servers": metadata.get("allowedMcpServers", []) or [],
            "allowed_sandbox_tools": metadata.get("allowedSandboxTools", []) or [],
        })

    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Build skills catalog index")
    parser.add_argument(
        "--skills-dir",
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "..", "external-examples-and-tools", "skills", "skills",
        ),
        help="Path to the skills directory",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "catalog", "skills-catalog.json"),
        help="Output JSON file path",
    )
    args = parser.parse_args()

    catalog = build_catalog(args.skills_dir)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=2, ensure_ascii=False)

    print(f"Generated catalog with {len(catalog)} skills -> {args.output}")


if __name__ == "__main__":
    main()
