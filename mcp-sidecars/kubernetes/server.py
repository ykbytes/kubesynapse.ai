"""MCP Kubernetes sidecar — query and manage Kubernetes resources."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

server = create_mcp_server(
    "mcp-kubernetes",
    "Query Kubernetes resources — list pods, get logs, apply manifests, describe resources.",
)

MAX_OUTPUT_CHARS = 12000


def _get_k8s_client():
    """Load Kubernetes config and return CoreV1Api."""
    from kubernetes import client, config
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


@server.tool()
def list_pods(namespace: str = "default") -> str:
    """List pods in a namespace."""
    try:
        v1 = _get_k8s_client()
        pods = v1.list_namespaced_pod(namespace)
        lines = []
        for pod in pods.items:
            status = pod.status.phase
            lines.append(f"{pod.metadata.name}\t{status}")
        return "\n".join(lines) if lines else "(no pods found)"
    except Exception as e:
        return f"ERROR: {e}"


@server.tool()
def get_pod_logs(namespace: str, pod_name: str, tail_lines: int = 50) -> str:
    """Get recent logs from a pod."""
    try:
        v1 = _get_k8s_client()
        logs = v1.read_namespaced_pod_log(
            pod_name, namespace, tail_lines=min(tail_lines, 200),
        )
        return logs[:MAX_OUTPUT_CHARS] if logs else "(no logs)"
    except Exception as e:
        return f"ERROR: {e}"


@server.tool()
def kubectl_get(resource_type: str, namespace: str = "default", name: str = "") -> str:
    """Get Kubernetes resources (pods, services, deployments, etc.)."""
    import subprocess
    try:
        cmd = ["kubectl", "get", resource_type, "-n", namespace, "-o", "wide"]
        if name:
            cmd.insert(3, name)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        output = result.stdout + result.stderr
        return output[:MAX_OUTPUT_CHARS] if output.strip() else "(no output)"
    except Exception as e:
        return f"ERROR: {e}"


@server.tool()
def kubectl_describe(resource_type: str, name: str, namespace: str = "default") -> str:
    """Describe a Kubernetes resource."""
    import subprocess
    try:
        result = subprocess.run(
            ["kubectl", "describe", resource_type, name, "-n", namespace],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout + result.stderr
        return output[:MAX_OUTPUT_CHARS] if output.strip() else "(no output)"
    except Exception as e:
        return f"ERROR: {e}"


if __name__ == "__main__":
    run_server(server)
