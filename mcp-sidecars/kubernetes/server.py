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


def _redact_sensitive_output(text: str, resource_type: str) -> str:
    """Redact secret data and ConfigMap values from kubectl output."""
    import re
    rt = resource_type.lower().strip()
    if rt == "secrets":
        return "[REDACTED: secret data withheld]"
    if rt == "configmaps":
        # Defensively redact lines that look like key: value pairs in data sections
        text = re.sub(r"(?m)^(\s+[^:]+:\s).*", r"\1[REDACTED]", text)
    return text


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
    from kubernetes import client, config, dynamic
    from kubernetes.client import api_client

    rt_err = _validate_resource_type(resource_type)
    if rt_err:
        return f"BLOCKED: {rt_err}"
    ns_err = _validate_namespace(namespace)
    if ns_err:
        return f"BLOCKED: {ns_err}"
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        api = api_client.ApiClient()
        dyn = dynamic.DynamicClient(api)

        # Map common plural names to API groups
        _RESOURCE_API_MAP = {
            "pods": ("", "v1"), "services": ("", "v1"), "nodes": ("", "v1"),
            "events": ("", "v1"), "configmaps": ("", "v1"), "endpoints": ("", "v1"),
            "persistentvolumeclaims": ("", "v1"), "namespaces": ("", "v1"),
            "resourcequotas": ("", "v1"), "limitranges": ("", "v1"),
            "deployments": ("apps", "v1"), "statefulsets": ("apps", "v1"),
            "daemonsets": ("apps", "v1"), "replicasets": ("apps", "v1"),
            "jobs": ("batch", "v1"), "cronjobs": ("batch", "v1"),
            "ingresses": ("networking.k8s.io", "v1"),
            "networkpolicies": ("networking.k8s.io", "v1"),
            "horizontalpodautoscalers": ("autoscaling", "v2"),
        }

        rt = resource_type.lower().strip()
        group, version = _RESOURCE_API_MAP.get(rt, ("", "v1"))
        api_version = f"{group}/{version}" if group else version

        resource = None
        for r in dyn.resources.search(api_version=api_version):
            if r.name.lower() == rt:
                resource = r
                break
        if resource is None:
            return f"ERROR: Unknown resource type '{resource_type}'"

        cluster_scoped = rt in ("nodes", "namespaces")
        if name:
            if cluster_scoped:
                obj = resource.get(name=name)
            else:
                obj = resource.get(name=name, namespace=namespace)
            lines = [f"NAME: {obj.metadata.name}"]
            if hasattr(obj, 'status') and hasattr(obj.status, 'phase'):
                lines.append(f"STATUS: {obj.status.phase}")
            return _redact_sensitive_output("\n".join(lines), resource_type)
        else:
            if cluster_scoped:
                items = resource.get()
            else:
                items = resource.get(namespace=namespace)
            lines = []
            for item in items.items:
                meta = item.metadata
                parts = [meta.name]
                if hasattr(item, 'status'):
                    if hasattr(item.status, 'phase'):
                        parts.append(item.status.phase)
                    elif hasattr(item.status, 'readyReplicas'):
                        parts.append(f"ready={item.status.readyReplicas or 0}")
                lines.append("\t".join(str(p) for p in parts))
            return _redact_sensitive_output("\n".join(lines) if lines else "(no resources found)", resource_type)
    except Exception as e:
        log.exception("kubectl_get failed")
        return f"ERROR: kubectl get failed: {e}"


@server.tool()
def kubectl_describe(resource_type: str, name: str, namespace: str = "default") -> str:
    """Describe a Kubernetes resource.

    Restricted to safe resource types only — secrets and RBAC objects are blocked.
    """
    from kubernetes import client, config, dynamic
    from kubernetes.client import api_client

    rt_err = _validate_resource_type(resource_type)
    if rt_err:
        return f"BLOCKED: {rt_err}"
    ns_err = _validate_namespace(namespace)
    if ns_err:
        return f"BLOCKED: {ns_err}"
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        api = api_client.ApiClient()
        dyn = dynamic.DynamicClient(api)

        _RESOURCE_API_MAP = {
            "pods": ("", "v1"), "services": ("", "v1"), "nodes": ("", "v1"),
            "events": ("", "v1"), "configmaps": ("", "v1"), "endpoints": ("", "v1"),
            "persistentvolumeclaims": ("", "v1"), "namespaces": ("", "v1"),
            "deployments": ("apps", "v1"), "statefulsets": ("apps", "v1"),
            "daemonsets": ("apps", "v1"), "replicasets": ("apps", "v1"),
            "jobs": ("batch", "v1"), "cronjobs": ("batch", "v1"),
            "ingresses": ("networking.k8s.io", "v1"),
            "networkpolicies": ("networking.k8s.io", "v1"),
            "horizontalpodautoscalers": ("autoscaling", "v2"),
        }

        rt = resource_type.lower().strip()
        group, version = _RESOURCE_API_MAP.get(rt, ("", "v1"))
        api_version = f"{group}/{version}" if group else version

        resource = None
        for r in dyn.resources.search(api_version=api_version):
            if r.name.lower() == rt:
                resource = r
                break
        if resource is None:
            return f"ERROR: Unknown resource type '{resource_type}'"

        cluster_scoped = rt in ("nodes", "namespaces")
        if cluster_scoped:
            obj = resource.get(name=name)
        else:
            obj = resource.get(name=name, namespace=namespace)

        # Format a human-readable description
        lines = [f"Name: {obj.metadata.name}"]
        if obj.metadata.namespace:
            lines.append(f"Namespace: {obj.metadata.namespace}")
        if obj.metadata.labels:
            lines.append(f"Labels: {dict(obj.metadata.labels)}")
        if obj.metadata.annotations:
            ann = dict(obj.metadata.annotations)
            lines.append(f"Annotations: {ann}")
        if hasattr(obj, 'status'):
            import json
            status_dict = obj.status.to_dict() if hasattr(obj.status, 'to_dict') else str(obj.status)
            status_str = json.dumps(status_dict, indent=2, default=str) if isinstance(status_dict, dict) else str(status_dict)
            lines.append(f"Status:\n{status_str}")
        if hasattr(obj, 'spec'):
            import json
            spec_dict = obj.spec.to_dict() if hasattr(obj.spec, 'to_dict') else str(obj.spec)
            spec_str = json.dumps(spec_dict, indent=2, default=str) if isinstance(spec_dict, dict) else str(spec_dict)
            lines.append(f"Spec:\n{spec_str}")

        output = "\n".join(lines)
        return _redact_sensitive_output(output[:MAX_OUTPUT_CHARS] if output else "(no output)", resource_type)
    except Exception as e:
        log.exception("kubectl_describe failed")
        return f"ERROR: kubectl describe failed: {e}"


if __name__ == "__main__":
    run_server(server)
