"""One-shot script to remove builder functions/constants from main.py and add builders imports.

This script is part of §2.1b (road-to-prod plan). It removes the function/constant
definitions that have been extracted into operators/builders/ and adds import statements.

Run from operator/ directory:  python _extract_builders.py
"""
import re
import sys

MAIN_PY = "main.py"

# Names of all top-level definitions to remove from main.py.
# These have been extracted into builders/helpers.py and builders/manifests.py.
REMOVE_NAMES: set[str] = {
    # Constants (helpers.py)
    "POD_TEMPLATE_REVISION_ANNOTATION",
    "KUBERNETES_RESOURCE_NAME_PATTERN",
    "STORAGE_QUANTITY_MULTIPLIERS",
    # Functions (helpers.py)
    "sandbox_name",
    "resolved_api_gateway_internal_url",
    "slugify_name",
    "hashed_resource_name",
    "worker_artifact_pvc_name",
    "artifact_file_path",
    "worker_passthrough_env",
    "build_artifact_ref",
    "build_journal_ref",
    "build_pvc_spec",
    "_parse_storage_quantity",
    "platform_namespace_selector",
    "agent_baseline_ingress_peers",
    "agent_baseline_egress_rules",
    # Constants (manifests.py)
    "PLATFORM_MANAGED_GOOSE_ENV",
    "PLATFORM_MANAGED_CODEX_ENV",
    "PLATFORM_MANAGED_OPENCODE_ENV",
    "PLATFORM_MANAGED_AGENT_ENV",
    # Functions (manifests.py)
    "_extract_skill_mcp_servers",
    "_auto_inject_mcp_sidecars",
    "runtime_extra_env_items",
    "goose_runtime_extra_env_items",
    "codex_runtime_extra_env_items",
    "opencode_runtime_extra_env_items",
    "agent_runtime_extra_env_items",
    "merged_goose_runtime_config_files",
    "merged_codex_runtime_config_files",
    "merged_opencode_runtime_config_files",
    "resolve_runtime_kind",
    "validate_runtime_configuration",
    "_build_pod_template_revision",
    "_extract_statefulset_storage_request",
    "_statefulset_template_signature",
    "_validate_mcp_sidecars",
    "create_worker_artifact_pvc_manifest",
    "create_mcp_auth_secret_manifest",
    "create_agent_service_manifest",
    "create_agent_statefulset_manifest",
    "create_mcp_network_policy_manifest",
    "create_a2a_egress_network_policy_manifest",
    "create_a2a_ingress_network_policy_manifest",
    "_worker_git_env",
    "create_worker_job_manifest",
}

# Regex to detect the start of a top-level definition.
# Matches: def name(, NAME =, NAME:, NAME {, or @decorator
_DEF_RE = re.compile(r"^(def\s+(\w+)\s*\(|([A-Za-z_]\w*)\s*[:={])")


def _extract_name(line: str) -> str | None:
    """Return the top-level name being defined on *line*, or None."""
    stripped = line.rstrip()
    if not stripped or stripped[0].isspace():
        return None
    m = _DEF_RE.match(stripped)
    if m:
        return m.group(2) or m.group(3)
    return None


def _is_new_toplevel(line: str) -> bool:
    """Return True if *line* starts a new top-level definition (not a continuation)."""
    stripped = line.strip()
    if not stripped:
        return False
    # Lines starting with ), }, ] at column 0 are continuations
    if line[0] in ")]}":
        return False
    if line[0].isspace():
        return False
    # Check for recognised top-level patterns
    if stripped.startswith("def "):
        return True
    if stripped.startswith("class "):
        return True
    if stripped.startswith("@"):
        return True
    if stripped.startswith("import ") or stripped.startswith("from "):
        return True
    if stripped.startswith("#"):
        return True
    # UPPER_NAME = ... or UPPER_NAME: ... or UPPER_NAME { ...
    if re.match(r"^[A-Za-z_]\w*\s*[:={]", stripped):
        return True
    # Bare variable assignment (lower case)
    if re.match(r"^[A-Za-z_]\w*\s*=", stripped):
        return True
    return False


def find_block_ranges(lines: list[str]) -> list[tuple[int, int, str]]:
    """Return (start, end_exclusive, name) for every top-level definition to remove."""
    ranges: list[tuple[int, int, str]] = []
    i = 0
    while i < len(lines):
        name = _extract_name(lines[i])
        if name and name in REMOVE_NAMES:
            start = i
            i += 1
            # Advance past the entire block: indented lines, blank lines,
            # and continuation lines (, }, ]) at column 0.
            while i < len(lines):
                stripped = lines[i].strip()
                if not stripped:
                    # Blank line — peek ahead to decide if we're still in the body
                    j = i
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j >= len(lines):
                        break  # EOF
                    # If the next non-blank line is indented or a continuation, keep going
                    if lines[j][0].isspace() or lines[j][0] in ")]}":
                        i = j
                        continue
                    break  # next non-blank is a new top-level item
                if lines[i][0].isspace():
                    # Indented — part of the body
                    i += 1
                    continue
                if lines[i][0] in ")]}":
                    # Continuation closer at column 0
                    i += 1
                    continue
                if _is_new_toplevel(lines[i]):
                    break  # new definition
                # Unknown non-indented line — treat as end
                break
            # Include trailing blank lines (up to 1) for clean separation
            end = i
            if end < len(lines) and not lines[end].strip():
                end += 1
            ranges.append((start, end, name))
            i = end
        else:
            i += 1
    return ranges


# The import block to insert (placed after existing imports)
BUILDERS_IMPORT = """\
from builders import (
    KUBERNETES_RESOURCE_NAME_PATTERN,
    PLATFORM_MANAGED_AGENT_ENV,
    PLATFORM_MANAGED_CODEX_ENV,
    PLATFORM_MANAGED_GOOSE_ENV,
    PLATFORM_MANAGED_OPENCODE_ENV,
    POD_TEMPLATE_REVISION_ANNOTATION,
    STORAGE_QUANTITY_MULTIPLIERS,
    _auto_inject_mcp_sidecars,
    _build_pod_template_revision,
    _extract_skill_mcp_servers,
    _extract_statefulset_storage_request,
    _parse_storage_quantity,
    _statefulset_template_signature,
    _validate_mcp_sidecars,
    _worker_git_env,
    agent_baseline_egress_rules,
    agent_baseline_ingress_peers,
    agent_runtime_extra_env_items,
    artifact_file_path,
    build_artifact_ref,
    build_journal_ref,
    build_pvc_spec,
    codex_runtime_extra_env_items,
    create_a2a_egress_network_policy_manifest,
    create_a2a_ingress_network_policy_manifest,
    create_agent_service_manifest,
    create_agent_statefulset_manifest,
    create_mcp_auth_secret_manifest,
    create_mcp_network_policy_manifest,
    create_worker_artifact_pvc_manifest,
    create_worker_job_manifest,
    goose_runtime_extra_env_items,
    hashed_resource_name,
    merged_codex_runtime_config_files,
    merged_goose_runtime_config_files,
    merged_opencode_runtime_config_files,
    opencode_runtime_extra_env_items,
    platform_namespace_selector,
    resolve_runtime_kind,
    resolved_api_gateway_internal_url,
    runtime_extra_env_items,
    sandbox_name,
    slugify_name,
    validate_runtime_configuration,
    worker_artifact_pvc_name,
    worker_passthrough_env,
)
"""


def main() -> None:
    with open(MAIN_PY, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 1. Find all blocks to remove
    ranges = find_block_ranges(lines)

    # Sanity check: verify we found all expected names
    found_names = {name for _, _, name in ranges}
    missing = REMOVE_NAMES - found_names
    if missing:
        print(f"ERROR: Could not locate definitions for: {sorted(missing)}", file=sys.stderr)
        sys.exit(1)

    extra = found_names - REMOVE_NAMES
    if extra:
        print(f"WARNING: Found unexpected names: {sorted(extra)}", file=sys.stderr)

    # Sort by start line (should already be sorted, but be safe)
    ranges.sort(key=lambda r: r[0])

    print(f"Found {len(ranges)} blocks to remove:")
    for start, end, name in ranges:
        print(f"  {name}: lines {start + 1}-{end} ({end - start} lines)")

    total_removed = sum(end - start for start, end, start_name in ranges)
    print(f"Total lines to remove: {total_removed}")

    # 2. Build the set of lines to delete
    delete_set: set[int] = set()
    for start, end, _ in ranges:
        for i in range(start, end):
            delete_set.add(i)

    # 3. Reconstruct the file
    new_lines: list[str] = []
    import_inserted = False
    i = 0
    while i < len(lines):
        if i in delete_set:
            # If this is the first deleted block, insert the builders import
            if not import_inserted:
                # Add a blank line before the import if needed
                if new_lines and new_lines[-1].strip():
                    new_lines.append("\n")
                for imp_line in BUILDERS_IMPORT.split("\n"):
                    new_lines.append(imp_line + "\n" if imp_line else "\n")
                import_inserted = True
            i += 1
            continue
        new_lines.append(lines[i])
        i += 1

    # Remove duplicate consecutive blank lines (more than 2)
    cleaned: list[str] = []
    blank_count = 0
    for line in new_lines:
        if not line.strip():
            blank_count += 1
            if blank_count <= 2:
                cleaned.append(line)
        else:
            blank_count = 0
            cleaned.append(line)

    # 4. Write the result
    with open(MAIN_PY, "w", encoding="utf-8") as f:
        f.writelines(cleaned)

    original_count = len(lines)
    new_count = len(cleaned)
    print(f"\nResult: {original_count} lines -> {new_count} lines (removed {original_count - new_count} net lines)")
    print("Done. Builders import inserted and definitions removed.")


if __name__ == "__main__":
    main()
