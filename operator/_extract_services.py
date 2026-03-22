"""One-shot script to remove config definitions + service functions from main.py.

§2.1a-fixup + §2.1c: Complete the config.py migration by removing inline config
definitions, and remove service functions now in services/.

Run from operator/ directory:  python _extract_services.py
"""
import re
import sys

MAIN_PY = "main.py"


def find_func_end(lines: list[str], start: int) -> int:
    """Given a 'def ...' at *start*, return the first line AFTER the function body."""
    i = start + 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # blank lines inside a function — peek ahead
        if not stripped:
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines):
                return j
            # If next non-blank line is indented or a closing bracket, still inside function
            if lines[j][0].isspace() or lines[j][0] in ")]}":
                i = j
                continue
            return i  # reached a top-level construct
        if line[0].isspace() or line[0] in ")]}":
            i += 1
            continue
        return i  # new top-level construct
    return i


def main() -> None:
    with open(MAIN_PY, "r", encoding="utf-8") as f:
        lines = f.readlines()

    total = len(lines)
    print(f"Original file: {total} lines")

    # -- Locate key line numbers (0-indexed) --
    markers: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = re.match(r"^def\s+(\w+)", line)
        if m:
            markers[m.group(1)] = i
        m2 = re.match(r"^([A-Z_][A-Z0-9_]*)\s*[=:{]", line)
        if m2 and m2.group(1) not in markers:
            markers[m2.group(1)] = i
        if line.strip() == "_load_mcp_sidecar_catalog()":
            markers["_load_call"] = i
        if line.startswith("@kopf.on.startup"):
            markers["_kopf_startup"] = i

    # -- Block 1: describe_api_exception (one function) --
    b1_start = markers["describe_api_exception"]
    b1_end = find_func_end(lines, b1_start)
    print(f"Block 1 (describe_api_exception): lines {b1_start+1}-{b1_end}")

    # -- Block 2: config helpers + constants (get_string_env .. _load_mcp_sidecar_catalog() call) --
    b2_start = markers["get_string_env"]
    # The standalone _load_mcp_sidecar_catalog() call is followed by blank lines then @kopf.on.startup
    b2_end = markers["_kopf_startup"]  # stop just before @kopf.on.startup
    print(f"Block 2 (config definitions): lines {b2_start+1}-{b2_end}")

    # -- Block 3: service functions (ensure_runtime_access .. ensure_network_policy) --
    b3_start = markers["ensure_runtime_access"]
    b3_end = markers["create_agent_resources"]  # stop just before create_agent_resources
    print(f"Block 3 (ensure_* service functions): lines {b3_start+1}-{b3_end}")

    # -- Block 4: worker service functions (patch_custom_status .. cancel_worker_job) --
    b4_start = markers["patch_custom_status"]
    b4_end = markers["enqueue_eval_job"]  # stop just before enqueue_eval_job
    print(f"Block 4 (worker service functions): lines {b4_start+1}-{b4_end}")

    # -- Build removal set --
    remove = set()
    for s, e in [(b1_start, b1_end), (b2_start, b2_end), (b3_start, b3_end), (b4_start, b4_end)]:
        for i in range(s, e):
            remove.add(i)

    # -- Build new file --
    CONFIG_IMPORT = (
        "from config import (\n"
        "    EVAL_SCHEDULE_POLL_SECONDS,\n"
        "    OPERATOR_NAMESPACE,\n"
        "    OPERATOR_PEERING_NAME,\n"
        "    PROTECTED_NAMESPACES,\n"
        "    SCHEDULED_EVAL_QUEUE_STALE_SECONDS,\n"
        "    SECRET_PROVISIONING_MODE,\n"
        "    WORKER_IMAGE,\n"
        "    WORKFLOW_POLL_SECONDS,\n"
        "    WORKFLOW_QUEUE_STALE_SECONDS,\n"
        "    WORKFLOW_RUNNING_STALE_SECONDS,\n"
        ")\n"
    )

    SERVICES_IMPORT = (
        "from services import (\n"
        "    cancel_worker_job,\n"
        "    describe_api_exception,\n"
        "    ensure_network_policy,\n"
        "    ensure_runtime_access,\n"
        "    ensure_runtime_namespace_secret,\n"
        "    ensure_secret,\n"
        "    ensure_service,\n"
        "    ensure_statefulset,\n"
        "    ensure_worker_artifact_storage,\n"
        "    enqueue_worker_job,\n"
        "    patch_custom_status,\n"
        "    read_job_state,\n"
        ")\n"
    )

    new_lines: list[str] = []
    config_inserted = False
    services_inserted = False
    i = 0
    while i < total:
        if i in remove:
            # Insert config import at start of block 2
            if i == b2_start and not config_inserted:
                new_lines.append("\n")
                new_lines.append(CONFIG_IMPORT)
                new_lines.append("\n")
                config_inserted = True
            # Insert services import at start of block 3
            if i == b3_start and not services_inserted:
                new_lines.append(SERVICES_IMPORT)
                new_lines.append("\n")
                services_inserted = True
            i += 1
            continue
        new_lines.append(lines[i])
        i += 1

    # Collapse runs of >2 blank lines
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

    with open(MAIN_PY, "w", encoding="utf-8") as f:
        f.writelines(cleaned)

    print(f"\nResult: {total} lines -> {len(cleaned)} lines (removed {total - len(cleaned)} net lines)")
    print("Done. Config + services imports inserted; definitions removed.")


if __name__ == "__main__":
    main()
