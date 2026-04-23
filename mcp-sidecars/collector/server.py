"""
KubeSynth Collector MCP Sidecar

MCP tool interface that lets AI agents gather intelligence from
collector agents deployed on Kubernetes clusters and VMs.

Tools:
  - gather_info: Run a read-only collection script on target collectors
  - list_collectors: List registered collector agents and their status
  - list_builtin_scripts: Show available built-in collection scripts
  - get_system_info: Get system info from a specific collector
  - query_cluster: Run a built-in script on all collectors in a cluster
"""

import json
import logging
import os
from typing import Optional

import httpx
from mcp_base import create_mcp_server, run_server

log = logging.getLogger("mcp-collector")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Collector agents register via env or K8s service discovery
# Format: "name=http://host:port,name2=http://host2:port2"
COLLECTOR_ENDPOINTS = os.environ.get("COLLECTOR_ENDPOINTS", "")
COLLECTOR_TOKEN = os.environ.get("COLLECTOR_TOKEN", "collector-dev-token")
COLLECTOR_TIMEOUT = int(os.environ.get("COLLECTOR_TIMEOUT", "45"))

# Gateway URL for dynamic collector discovery
GATEWAY_URL = os.environ.get("GATEWAY_URL", "")
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "")


def _parse_endpoints() -> dict[str, str]:
    """Parse COLLECTOR_ENDPOINTS env var into a dict."""
    endpoints = {}
    if not COLLECTOR_ENDPOINTS:
        return endpoints
    for entry in COLLECTOR_ENDPOINTS.split(","):
        entry = entry.strip()
        if "=" in entry:
            name, url = entry.split("=", 1)
            endpoints[name.strip()] = url.strip()
    return endpoints


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {COLLECTOR_TOKEN}"}


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
server = create_mcp_server(
    name="collector-tools",
    description=(
        "Intelligence gathering tools for KubeSynth. "
        "Use these tools to collect information from Kubernetes clusters "
        "and VMs by running read-only scripts on deployed collector agents."
    ),
)


@server.tool()
async def list_collectors() -> str:
    """
    List all registered collector agents and their status.
    Returns each collector's name, URL, status, cluster, node, and capabilities.
    """
    endpoints = _parse_endpoints()
    if not endpoints:
        return json.dumps({"collectors": [], "message": "No collectors configured"})

    results = []
    async with httpx.AsyncClient(timeout=10) as client:
        for name, url in endpoints.items():
            try:
                resp = await client.get(f"{url}/info", headers=_headers())
                resp.raise_for_status()
                info = resp.json()
                info["name"] = name
                info["url"] = url
                info["status"] = "online"
                results.append(info)
            except Exception as e:
                results.append({
                    "name": name,
                    "url": url,
                    "status": "offline",
                    "error": str(e),
                })

    return json.dumps({"collectors": results, "total": len(results)}, indent=2)


@server.tool()
async def list_builtin_scripts(collector_name: Optional[str] = None) -> str:
    """
    List available built-in collection scripts from a collector.
    These are pre-packaged scripts for common intelligence gathering tasks
    like pod_resources, node_health, network_info, storage_info, security_posture, cluster_overview.

    Args:
        collector_name: Name of the collector to query. If not specified, queries the first available collector.
    """
    endpoints = _parse_endpoints()
    if not endpoints:
        return "No collectors configured"

    name = collector_name or next(iter(endpoints))
    url = endpoints.get(name)
    if not url:
        return f"Collector '{name}' not found. Available: {list(endpoints.keys())}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{url}/info", headers=_headers())
            resp.raise_for_status()
            info = resp.json()
            return json.dumps({
                "collector": name,
                "builtin_scripts": info.get("builtin_scripts", []),
                "capabilities": info.get("capabilities", []),
            }, indent=2)
    except Exception as e:
        return f"Error querying collector '{name}': {e}"


@server.tool()
async def gather_info(
    script: str,
    script_type: str = "bash",
    collector_name: Optional[str] = None,
    timeout: int = 30,
) -> str:
    """
    Run a read-only collection script on a collector agent to gather intelligence.
    The script is executed in a sandboxed environment — write operations are blocked.

    Use this to gather configuration, status, metrics, or any other read-only data
    from a Kubernetes cluster or VM.

    Args:
        script: The bash or python script to execute. Must be read-only (no writes, deletes, or mutations).
                Example: 'kubectl get pods -A -o wide' or 'cat /etc/os-release'
        script_type: Type of script - 'bash' or 'python'. Default: 'bash'
        collector_name: Name of the collector to use. If not specified, uses the first available collector.
        timeout: Maximum execution time in seconds (max 60). Default: 30
    """
    endpoints = _parse_endpoints()
    if not endpoints:
        return "No collectors configured. Deploy a collector agent first."

    name = collector_name or next(iter(endpoints))
    url = endpoints.get(name)
    if not url:
        return f"Collector '{name}' not found. Available: {list(endpoints.keys())}"

    try:
        async with httpx.AsyncClient(timeout=COLLECTOR_TIMEOUT) as client:
            resp = await client.post(
                f"{url}/collect",
                headers=_headers(),
                json={
                    "script": script,
                    "type": script_type,
                    "timeout": min(timeout, 60),
                },
            )
            resp.raise_for_status()
            result = resp.json()
            return json.dumps(result, indent=2)
    except httpx.TimeoutException:
        return f"Timeout: collector '{name}' did not respond within {COLLECTOR_TIMEOUT}s"
    except Exception as e:
        return f"Error: {e}"


@server.tool()
async def run_builtin_script(
    script_name: str,
    collector_name: Optional[str] = None,
    timeout: int = 30,
) -> str:
    """
    Run a built-in collection script on a collector agent.
    Built-in scripts are pre-packaged for common intelligence gathering tasks.

    Available built-in scripts:
    - cluster_overview: Cluster version, namespaces, resource counts, warning events
    - pod_resources: Pod resource usage, status summary, non-running pods
    - node_health: Node status, resources, conditions, pressure
    - network_info: Services, ingresses, network policies, DNS config
    - storage_info: Storage classes, PVs, PVCs, disk usage
    - security_posture: RBAC, service accounts, secrets, pod security

    Args:
        script_name: Name of the built-in script to run
        collector_name: Name of the collector to use. If not specified, uses the first available collector.
        timeout: Maximum execution time in seconds (max 60). Default: 30
    """
    endpoints = _parse_endpoints()
    if not endpoints:
        return "No collectors configured. Deploy a collector agent first."

    name = collector_name or next(iter(endpoints))
    url = endpoints.get(name)
    if not url:
        return f"Collector '{name}' not found. Available: {list(endpoints.keys())}"

    try:
        async with httpx.AsyncClient(timeout=COLLECTOR_TIMEOUT) as client:
            resp = await client.post(
                f"{url}/collect",
                headers=_headers(),
                json={
                    "builtin": script_name,
                    "timeout": min(timeout, 60),
                },
            )
            resp.raise_for_status()
            result = resp.json()
            return json.dumps(result, indent=2)
    except httpx.TimeoutException:
        return f"Timeout: collector '{name}' did not respond within {COLLECTOR_TIMEOUT}s"
    except Exception as e:
        return f"Error: {e}"


@server.tool()
async def get_system_info(collector_name: Optional[str] = None) -> str:
    """
    Get system-level information from a collector agent's host.
    Returns CPU, memory, disk usage, uptime, and platform info.

    Args:
        collector_name: Name of the collector to query. If not specified, queries the first available collector.
    """
    endpoints = _parse_endpoints()
    if not endpoints:
        return "No collectors configured"

    name = collector_name or next(iter(endpoints))
    url = endpoints.get(name)
    if not url:
        return f"Collector '{name}' not found. Available: {list(endpoints.keys())}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{url}/system-info", headers=_headers())
            resp.raise_for_status()
            return json.dumps(resp.json(), indent=2)
    except Exception as e:
        return f"Error: {e}"


@server.tool()
async def fan_out_collect(
    script: str,
    script_type: str = "bash",
    timeout: int = 30,
) -> str:
    """
    Run a collection script on ALL registered collectors simultaneously.
    Use this to gather the same information across all nodes/clusters at once.
    Results are returned as a list with each collector's response.

    Args:
        script: The bash or python script to execute on all collectors
        script_type: Type of script - 'bash' or 'python'. Default: 'bash'
        timeout: Maximum execution time per collector in seconds (max 60). Default: 30
    """
    endpoints = _parse_endpoints()
    if not endpoints:
        return "No collectors configured"

    results = {}
    async with httpx.AsyncClient(timeout=COLLECTOR_TIMEOUT) as client:
        for name, url in endpoints.items():
            try:
                resp = await client.post(
                    f"{url}/collect",
                    headers=_headers(),
                    json={
                        "script": script,
                        "type": script_type,
                        "timeout": min(timeout, 60),
                    },
                )
                resp.raise_for_status()
                results[name] = resp.json()
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}

    return json.dumps({
        "fan_out_results": results,
        "total_collectors": len(endpoints),
        "successful": sum(1 for r in results.values() if r.get("status") == "completed"),
    }, indent=2)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info("Starting collector MCP sidecar")
    run_server(server)
