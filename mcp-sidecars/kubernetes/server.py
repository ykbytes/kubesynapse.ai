"""MCP Kubernetes sidecar — query and manage Kubernetes resources."""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

log = logging.getLogger("mcp-kubernetes")

server = create_mcp_server(
    "mcp-kubernetes",
    "Query Kubernetes resources — list pods, get logs, apply manifests, describe resources.",
)

MAX_OUTPUT_CHARS = 12000

# --- Security: Resource type and namespace allowlists ---
# Only these resource types may be queried via kubectl_get / kubectl_describe.
# Secrets, service-account tokens, RBAC objects, and cluster-level resources
# are explicitly excluded to prevent credential exfiltration.
ALLOWED_RESOURCE_TYPES = frozenset({
    "pods", "services", "deployments", "statefulsets", "daemonsets",
    "replicasets", "jobs", "cronjobs", "configmaps", "events",
    "ingresses", "endpoints", "persistentvolumeclaims", "nodes",
    "horizontalpodautoscalers", "networkpolicies",
})

# Blocked resource types — always rejected even if ALLOWED_RESOURCE_TYPES is
# overridden via env var in the future.
BLOCKED_RESOURCE_TYPES = frozenset({
    "secrets", "serviceaccounts", "roles", "rolebindings",
    "clusterroles", "clusterrolebindings", "tokenreviews",
    "certificatesigningrequests",
})

# Optional namespace allowlist from env var (comma-separated).
# Empty means all namespaces are allowed.
_ns_env = os.environ.get("ALLOWED_NAMESPACES", "").strip()
ALLOWED_NAMESPACES: frozenset[str] | None = (
    frozenset(n.strip() for n in _ns_env.split(",") if n.strip()) if _ns_env else None
)


def _validate_resource_type(resource_type: str) -> str | None:
    """Return an error message if the resource type is not allowed, else None."""
    rt = resource_type.lower().strip()
    if rt in BLOCKED_RESOURCE_TYPES:
        return f"Resource type '{resource_type}' is blocked for security reasons"
    if rt not in ALLOWED_RESOURCE_TYPES:
        return (
            f"Resource type '{resource_type}' is not in the allowlist. "
            f"Allowed: {', '.join(sorted(ALLOWED_RESOURCE_TYPES))}"
        )
    return None


def _validate_namespace(namespace: str) -> str | None:
    """Return an error message if the namespace is not allowed, else None."""
    if ALLOWED_NAMESPACES is not None and namespace not in ALLOWED_NAMESPACES:
        return f"Namespace '{namespace}' is not in the allowlist"
    return None


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
    ns_err = _validate_namespace(namespace)
    if ns_err:
        return f"BLOCKED: {ns_err}"
    try:
        v1 = _get_k8s_client()
        pods = v1.list_namespaced_pod(namespace)
        lines = []
        for pod in pods.items:
            status = pod.status.phase
            lines.append(f"{pod.metadata.name}\t{status}")
        return "\n".join(lines) if lines else "(no pods found)"
    except Exception as e:
        log.exception("list_pods failed")
        return "ERROR: Failed to list pods"


@server.tool()
def get_pod_logs(namespace: str, pod_name: str, tail_lines: int = 50) -> str:
    """Get recent logs from a pod."""
    ns_err = _validate_namespace(namespace)
    if ns_err:
        return f"BLOCKED: {ns_err}"
    try:
        v1 = _get_k8s_client()
        logs = v1.read_namespaced_pod_log(
            pod_name, namespace, tail_lines=min(tail_lines, 200),
        )
        return logs[:MAX_OUTPUT_CHARS] if logs else "(no logs)"
    except Exception as e:
        log.exception("get_pod_logs failed")
        return "ERROR: Failed to get pod logs"


@server.tool()
def kubectl_get(resource_type: str, namespace: str = "default", name: str = "") -> str:
    """Get Kubernetes resources (pods, services, deployments, etc.).

    Restricted to safe resource types only — secrets and RBAC objects are blocked.
    """
    import subprocess
    rt_err = _validate_resource_type(resource_type)
    if rt_err:
        return f"BLOCKED: {rt_err}"
    ns_err = _validate_namespace(namespace)
    if ns_err:
        return f"BLOCKED: {ns_err}"
    try:
        cmd = ["kubectl", "get", resource_type, "-n", namespace, "-o", "wide"]
        if name:
            cmd.insert(3, name)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        output = result.stdout + result.stderr
        return output[:MAX_OUTPUT_CHARS] if output.strip() else "(no output)"
    except Exception as e:
        log.exception("kubectl_get failed")
        return "ERROR: kubectl get failed"


@server.tool()
def kubectl_describe(resource_type: str, name: str, namespace: str = "default") -> str:
    """Describe a Kubernetes resource.

    Restricted to safe resource types only — secrets and RBAC objects are blocked.
    """
    import subprocess
    rt_err = _validate_resource_type(resource_type)
    if rt_err:
        return f"BLOCKED: {rt_err}"
    ns_err = _validate_namespace(namespace)
    if ns_err:
        return f"BLOCKED: {ns_err}"
    try:
        result = subprocess.run(
            ["kubectl", "describe", resource_type, name, "-n", namespace],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout + result.stderr
        return output[:MAX_OUTPUT_CHARS] if output.strip() else "(no output)"
    except Exception as e:
        log.exception("kubectl_describe failed")
        return "ERROR: kubectl describe failed"


if __name__ == "__main__":
    run_server(server)
