"""OpenCode Runtime Worker — executes AgentWorkflow steps via runtime API."""
from __future__ import annotations

import json
import logging
import os
import random
import signal
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import kubernetes.client
import kubernetes.config

logger = logging.getLogger("runtime-worker")
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.basicConfig(level=os.getenv("WORKER_LOG_LEVEL", "INFO").upper(), handlers=[_handler], force=True)

_shutting_down = threading.Event()

def is_shutting_down():
    return _shutting_down.is_set()

def _sigterm_handler(signum, _frame):
    _shutting_down.set()
    logger.info("Received signal %s — worker shutting down.", signum)

signal.signal(signal.SIGTERM, _sigterm_handler)

GROUP = "kubesynapse.ai"
VERSION = "v1alpha1"
WORKER_KIND = os.getenv("WORKER_KIND", "").strip().lower()
TARGET_NAMESPACE = os.getenv("TARGET_NAMESPACE", "")
TARGET_NAME = os.getenv("TARGET_NAME", "")
OPERATOR_NS = os.getenv("OPERATOR_NAMESPACE", "default")
WORKER_JOB_NAME = os.getenv("WORKER_JOB_NAME", "")
ARTIFACT_PATH = os.getenv("ARTIFACT_PATH", "/artifacts/run.json")
ARTIFACT_JOURNAL_PATH = os.getenv("ARTIFACT_JOURNAL_PATH", "")
WORKFLOW_RUN_ID = os.getenv("WORKFLOW_RUN_ID", "")
TARGET_UID = os.getenv("TARGET_UID", "")


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def load_k8s_config():
    try:
        kubernetes.config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config.")
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()
        logger.info("Loaded local kubeconfig.")


def get_resource(plural: str) -> dict[str, Any]:
    api = kubernetes.client.CustomObjectsApi()
    return api.get_namespaced_custom_object(GROUP, VERSION, TARGET_NAMESPACE, plural, TARGET_NAME)


def patch_status(plural: str, status: dict[str, Any]):
    api = kubernetes.client.CustomObjectsApi()
    for attempt in range(3):
        try:
            api.patch_namespaced_custom_object_status(GROUP, VERSION, TARGET_NAMESPACE, plural, TARGET_NAME, {"status": status})
            return
        except kubernetes.client.ApiException as exc:
            if exc.status == 409 and attempt < 2:
                time.sleep((2 ** attempt) + random.random())
                continue
            logger.error("Failed to patch status: %s", exc)
            raise


def runtime_url(agent_name: str, namespace: str, port: int = 8080) -> str:
    return f"http://{agent_name}-sandbox.{namespace}.svc.cluster.local:{port}"


def wait_for_runtime_ready(agent_name: str, namespace: str, timeout: float = 180):
    deadline = time.time() + timeout
    url = f"{runtime_url(agent_name, namespace)}/ready"
    while time.time() < deadline:
        if is_shutting_down():
            raise RuntimeError("Shutdown during runtime wait")
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code == 200:
                logger.info("Runtime %s/%s is ready.", agent_name, namespace)
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f"Runtime {agent_name}/{namespace} not ready within {timeout}s")


def invoke_agent(agent_name: str, namespace: str, prompt: str, step_name: str, run_id: str) -> dict[str, Any]:
    url = f"{runtime_url(agent_name, namespace)}/invoke"
    body = {
        "prompt": prompt,
        "thread_id": f"wf-{run_id}-{step_name}"[:128],
        "autonomous": True,
    }
    logger.info("Invoking agent %s/%s (step=%s)", agent_name, namespace, step_name)
    with httpx.Client(timeout=300) as client:
        r = client.post(url, json=body, timeout=300)
        r.raise_for_status()
        return r.json()


def write_artifact(payload: dict[str, Any]):
    path = Path(ARTIFACT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def append_journal(event_type: str, payload: dict[str, Any]):
    jpath = Path(ARTIFACT_JOURNAL_PATH) if ARTIFACT_JOURNAL_PATH else Path(str(ARTIFACT_PATH).replace(".json", ".journal.ndjson"))
    jpath.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": now_iso(), "event": event_type, "kind": WORKER_KIND, "payload": payload}
    with jpath.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def execute_workflow(workflow: dict[str, Any]):
    spec = workflow.get("spec", {})
    steps = spec.get("steps", [])
    generation = workflow.get("status", {}).get("observedGeneration", 1)
    run_id = WORKFLOW_RUN_ID or f"{TARGET_NAMESPACE}-{TARGET_NAME}-gen-{generation}"

    logger.info("Starting workflow %s/%s gen=%s run=%s steps=%d", TARGET_NAMESPACE, TARGET_NAME, generation, run_id, len(steps))

    step_states: dict[str, dict[str, Any]] = {}
    step_results: dict[str, dict[str, Any]] = {}

    patch_status("agentworkflows", {
        "phase": "running",
        "runId": run_id,
        "currentStep": "",
        "observedGeneration": generation,
    })

    completed = set()
    failed_steps = []
    current_step_name = ""

    # compute execution waves based on depends_on
    step_map = {s["name"]: s for s in steps}
    executed: set[str] = set()

    while len(executed) < len(steps):
        ready = []
        for s in steps:
            name = s["name"]
            if name in executed:
                continue
            deps = s.get("dependsOn", [])
            if all(d in executed for d in deps):
                ready.append(s)

        if not ready:
            logger.error("No steps are ready to execute — possible circular dependency or deadlock.")
            break

        for step in ready:
            if is_shutting_down():
                logger.warning("Shutdown during step execution.")
                break
            name = step["name"]
            current_step_name = name
            agent_ref = step.get("agentRef", "")
            prompt = step.get("prompt", "")

            # Build dependency context
            deps = step.get("dependsOn", [])
            if deps:
                dep_context = []
                for dep in deps:
                    if dep in step_results:
                        resp = step_results[dep].get("response", "")
                        dep_context.append(f"[Output from {dep}]\n{resp[:4000]}")
                if dep_context:
                    prompt = "\n\n".join(dep_context) + "\n\n" + prompt

            step_start = now_iso()
            step_start_ts = time.monotonic()
            step_states[name] = {
                "stepName": name,
                "agentRef": agent_ref,
                "status": "running",
                "attempts": 1,
                "startedAt": step_start,
                "workerJob": {"name": WORKER_JOB_NAME, "namespace": OPERATOR_NS},
            }
            patch_status("agentworkflows", {
                "phase": "running",
                "currentStep": name,
                "stepStates": step_states,
            })
            append_journal("step_started", {"step": name, "agentRef": agent_ref})

            try:
                result = invoke_agent(agent_ref, TARGET_NAMESPACE, prompt, name, run_id)
                latency_ms = int((time.monotonic() - step_start_ts) * 1000)
                step_states[name].update({
                    "status": "completed",
                    "completedAt": now_iso(),
                    "latencyMs": latency_ms,
                    "responsePreview": (result.get("response") or "")[:500],
                })
                step_results[name] = result
                completed.add(name)
                executed.add(name)
                append_journal("step_completed", {"step": name, "latencyMs": latency_ms})
            except Exception as exc:
                latency_ms = int((time.monotonic() - step_start_ts) * 1000)
                error_text = str(exc)[:2000]
                step_states[name].update({
                    "status": "failed",
                    "completedAt": now_iso(),
                    "latencyMs": latency_ms,
                    "error": error_text,
                })
                executed.add(name)
                failed_steps.append(name)
                append_journal("step_failed", {"step": name, "error": error_text})
                logger.error("Step '%s' failed: %s", name, error_text)

        if is_shutting_down():
            break

    # Write final artifact
    phase = "completed" if not failed_steps else "failed"
    artifact = {
        "kind": "workflow",
        "generation": generation,
        "runId": run_id,
        "updatedAt": now_iso(),
        "startedAt": step_start,
        "currentStep": current_step_name,
        "stepResults": step_results,
        "stepStates": step_states,
    }
    write_artifact(artifact)
    append_journal("workflow_completed", {"phase": phase, "failedSteps": failed_steps})

    total = len(steps)
    summary = {
        "completedSteps": len(completed),
        "failedSteps": len(failed_steps),
        "totalSteps": total,
        "runId": run_id,
        "startedAt": step_start,
        "updatedAt": now_iso(),
    }

    patch_status("agentworkflows", {
        "phase": phase,
        "currentStep": current_step_name,
        "observedGeneration": generation,
        "runId": run_id,
        "stepStates": step_states,
        "summary": summary,
    })
    logger.info("Workflow %s/%s %s (%d/%d steps completed)", TARGET_NAMESPACE, TARGET_NAME, phase, len(completed), total)


def main():
    load_k8s_config()
    plural_map = {"workflow": "agentworkflows"}
    plural = plural_map.get(WORKER_KIND)
    if not plural:
        logger.error("Unsupported WORKER_KIND=%s", WORKER_KIND)
        sys.exit(1)

    logger.info("Processing %s %s/%s", plural, TARGET_NAMESPACE, TARGET_NAME)
    resource = get_resource(plural)

    if WORKER_KIND == "workflow":
        execute_workflow(resource)
    else:
        logger.error("Unsupported kind: %s", WORKER_KIND)
        sys.exit(1)


if __name__ == "__main__":
    main()
