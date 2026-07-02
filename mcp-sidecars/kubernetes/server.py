"""MCP Kubernetes sidecar — query and manage Kubernetes resources."""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

log = logging.getLogger("mcp-kubernetes")

server = create_mcp_server(
    "mcp-kubernetes",
    "Query Kubernetes resources — list pods with restart counts, list events, "
    "get logs, describe resources, inspect deployment resource limits.",
)

MAX_OUTPUT_CHARS = 12000

# --- Security: Resource type and namespace allowlists ---
ALLOWED_RESOURCE_TYPES = frozenset({
    "pods", "services", "deployments", "statefulsets", "daemonsets",
    "replicasets", "jobs", "cronjobs", "configmaps", "events",
    "ingresses", "endpoints", "persistentvolumeclaims", "nodes",
    "horizontalpodautoscalers", "networkpolicies",
})

BLOCKED_RESOURCE_TYPES = frozenset({
    "secrets", "serviceaccounts", "roles", "rolebindings",
    "clusterroles", "clusterrolebindings", "tokenreviews",
    "certificatesigningrequests",
})

_ns_env = os.environ.get("ALLOWED_NAMESPACES", "").strip()
ALLOWED_NAMESPACES: frozenset[str] | None = (
    frozenset(n.strip() for n in _ns_env.split(",") if n.strip()) if _ns_env else None
)


def _validate_resource_type(resource_type: str) -> str | None:
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
    if ALLOWED_NAMESPACES is not None and namespace not in ALLOWED_NAMESPACES:
        return f"Namespace '{namespace}' is not in the allowlist"
    return None


def _redact_sensitive_output(text: str, resource_type: str) -> str:
    import re
    rt = resource_type.lower().strip()
    if rt == "secrets":
        return "[REDACTED: secret data withheld]"
    if rt == "configmaps":
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


def _format_age(timestamp_str):
    """Format a timestamp into a human-readable age string."""
    from datetime import datetime, timezone
    try:
        if not timestamp_str:
            return "unknown"
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - ts
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return "just now"
        if total_seconds < 60:
            return f"{total_seconds}s"
        minutes = total_seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        return f"{days}d"
    except Exception:
        return "unknown"


@server.tool()
def list_pods(namespace: str = "default", label_selector: str = "") -> str:
    """List pods in a namespace with full status: restarts, phase, age, and OOMKilled info.

    Use this to find crash-looping pods, OOMKilled pods, or pods with high restart counts.
    Output format: NAME  READY  STATUS  RESTARTS  AGE  LAST-TERMINATION
    """
    ns_err = _validate_namespace(namespace)
    if ns_err:
        return f"BLOCKED: {ns_err}"
    try:
        v1 = _get_k8s_client()
        kwargs = {"namespace": namespace}
        if label_selector:
            kwargs["label_selector"] = label_selector
        pods = v1.list_namespaced_pod(**kwargs)
        if not pods.items:
            return "(no pods found)"
        lines = ["NAME\tREADY\tSTATUS\tRESTARTS\tAGE\tLAST-TERMINATION"]
        for pod in pods.items:
            name = pod.metadata.name
            phase = pod.status.phase or "Unknown"
            age = _format_age(pod.metadata.creation_timestamp)

            ready = "?"
            restarts = 0
            last_term = ""
            statuses = pod.status.container_statuses or []
            for cs in statuses:
                restarts = max(restarts, cs.restart_count or 0)
                ready_count = sum(1 for c in statuses if c.ready)
                total = len(statuses)
                ready = f"{ready_count}/{total}"
                if cs.last_state and cs.last_state.terminated:
                    reason = cs.last_state.terminated.reason or "Unknown"
                    exit_code = cs.last_state.terminated.exit_code
                    last_term = f"{reason}(exit={exit_code})"
                elif cs.state and cs.state.waiting:
                    reason = cs.state.waiting.reason or ""
                    if reason and reason not in ("ContainerCreating", "Running", "PodInitializing"):
                        phase = reason
            lines.append(f"{name}\t{ready}\t{phase}\t{restarts}\t{age}\t{last_term}")
        return "\n".join(lines)
    except Exception as e:
        log.exception("list_pods failed")
        return f"ERROR: Failed to list pods: {e}"


@server.tool()
def list_events(namespace: str = "default", field_selector: str = "") -> str:
    """List Kubernetes events in a namespace, sorted by most recent first.

    Use this to find OOMKilled, CrashLoopBackOff, BackOff, Killing, or FailedScheduling events.
    Output format: LAST-SEEN  TYPE  REASON  OBJECT  COUNT  MESSAGE
    """
    ns_err = _validate_namespace(namespace)
    if ns_err:
        return f"BLOCKED: {ns_err}"
    try:
        v1 = _get_k8s_client()
        kwargs = {"namespace": namespace}
        if field_selector:
            kwargs["field_selector"] = field_selector
        events = v1.list_namespaced_event(**kwargs)
        if not events.items:
            return "(no events found)"
        sorted_events = sorted(
            events.items,
            key=lambda e: e.last_timestamp or e.metadata.creation_timestamp or "",
            reverse=True,
        )
        lines = ["LAST-SEEN\tTYPE\tREASON\tOBJECT\tCOUNT\tMESSAGE"]
        for ev in sorted_events[:50]:
            last_seen = _format_age(ev.last_timestamp)
            ev_type = ev.type or "Unknown"
            reason = ev.reason or ""
            obj = ""
            if ev.involved_object:
                obj = f"{ev.involved_object.kind}/{ev.involved_object.name}"
            count = ev.count or 1
            msg = (ev.message or "")[:120]
            lines.append(f"{last_seen}\t{ev_type}\t{reason}\t{obj}\t{count}\t{msg}")
        return "\n".join(lines)
    except Exception as e:
        log.exception("list_events failed")
        return f"ERROR: Failed to list events: {e}"


@server.tool()
def get_pod_logs(namespace: str, pod_name: str, tail_lines: int = 50) -> str:
    """Get recent logs from a pod. Use for troubleshooting, error investigation."""
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
        return f"ERROR: Failed to get pod logs: {e}"


@server.tool()
def describe_deployment(namespace: str, deployment_name: str) -> str:
    """Describe a Deployment including container resource requests and limits.

    Use this to inspect memory/CPU limits when diagnosing OOMKilled pods.
    """
    ns_err = _validate_namespace(namespace)
    if ns_err:
        return f"BLOCKED: {ns_err}"
    try:
        from kubernetes import client
        apps_v1 = client.AppsV1Api()
        dep = apps_v1.read_namespaced_deployment(deployment_name, namespace)
        lines = [
            f"Deployment: {dep.metadata.name}",
            f"Namespace: {dep.metadata.namespace}",
            f"Replicas: desired={dep.spec.replicas}, ready={dep.status.ready_replicas or 0}",
            f"Strategy: {dep.spec.strategy.type if dep.spec.strategy else 'RollingUpdate'}",
            "",
        ]
        for container in dep.spec.template.spec.containers:
            lines.append(f"Container: {container.name}")
            lines.append(f"  Image: {container.image}")
            res = container.resources or {}
            if res.get("requests"):
                lines.append(f"  Requests: {dict(res['requests'])}")
            else:
                lines.append("  Requests: (none)")
            if res.get("limits"):
                lines.append(f"  Limits: {dict(res['limits'])}")
            else:
                lines.append("  Limits: (none)")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        log.exception("describe_deployment failed")
        return f"ERROR: Failed to describe deployment: {e}"


@server.tool()
def kubectl_get(resource_type: str, namespace: str = "default", name: str = "") -> str:
    """Get Kubernetes resources (pods, services, deployments, events, etc.).

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
    """Describe a Kubernetes resource in detail — full spec, status, and metadata.

    Restricted to safe resource types only.
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

        lines = [f"Name: {obj.metadata.name}"]
        if obj.metadata.namespace:
            lines.append(f"Namespace: {obj.metadata.namespace}")
        if obj.metadata.labels:
            lines.append(f"Labels: {dict(obj.metadata.labels)}")
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
