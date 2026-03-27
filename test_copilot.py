#!/usr/bin/env python3
"""Quick test: fetch Copilot models from inside the pod."""
import base64
import os
import httpx

from kubernetes import client as k8s_client, config

config.load_incluster_config()

ns = os.getenv("POD_NAMESPACE", "ai-agent-sandbox")
sn = os.getenv("LLM_SECRET_NAME", "ai-sandbox-ai-agent-sandbox-llm-api-keys")
secret = k8s_client.CoreV1Api().read_namespaced_secret(name=sn, namespace=ns)
raw = (getattr(secret, "data", None) or {}).get("GITHUB_COPILOT_TOKEN", "")
token = base64.b64decode(raw).decode("utf-8").strip() if raw else ""

if not token:
    print("NO TOKEN FOUND")
    raise SystemExit(1)

print(f"Token prefix: {token[:10]}...")

# 1) Try token exchange
print("\n--- Token Exchange ---")
try:
    resp = httpx.get(
        "https://api.github.com/copilot_internal/v2/token",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/json",
            "User-Agent": "GitHubCopilotChat/0.25.2024",
        },
        timeout=15.0,
    )
    print(f"Status: {resp.status_code}")
    print(f"Body:   {resp.text[:500]}")
except Exception as exc:
    print(f"Error: {exc}")

# 2) Try direct model fetch with OAuth token
print("\n--- Direct Model Fetch (OAuth token) ---")
try:
    resp = httpx.get(
        "https://api.githubcopilot.com/models",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "GitHubCopilotChat/0.25.2024",
            "Editor-Version": "vscode/1.96.2",
            "Editor-Plugin-Version": "copilot-chat/0.25.2024",
            "Copilot-Integration-Id": "vscode-chat",
            "Openai-Intent": "conversation-edits",
        },
        timeout=15.0,
    )
    print(f"Status: {resp.status_code}")
    print(f"Body:   {resp.text[:1000]}")
except Exception as exc:
    print(f"Error: {exc}")
