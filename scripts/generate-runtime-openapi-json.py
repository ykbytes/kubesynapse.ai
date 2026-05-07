from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SPEC = ROOT / "docs" / "runtime-api-spec.yaml"
TARGETS = [
    ROOT / "opencode-runtime" / "openapi.json",
    ROOT / "pi-runtime" / "openapi.json",
    ROOT / "vibe-runtime" / "openapi.json",
]
YAML_MIRRORS = [
    ROOT / "opencode-runtime" / "openapi.yaml",
]


def main() -> None:
    source_yaml = SOURCE_SPEC.read_text(encoding="utf-8")
    spec = yaml.safe_load(source_yaml)
    rendered = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    for target in TARGETS:
        target.write_text(rendered, encoding="utf-8")
        print(f"Wrote {target.relative_to(ROOT)}")
    mirrored_yaml = source_yaml.rstrip() + "\n"
    for target in YAML_MIRRORS:
        target.write_text(mirrored_yaml, encoding="utf-8")
        print(f"Wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()