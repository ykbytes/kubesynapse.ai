---
title: "Introducing KubeSynapse: A Kubernetes-Native AI Agent Platform"
date: "2026-04-30"
author: "KubeSynapse Team"
tags: ["announcement", "release", "kubernetes"]
summary: "KubeSynapse is an open-source, self-hosted AI operations platform built from the ground up for Kubernetes. Deploy governed AI agents, compose multi-agent workflows, and automate incident response — all managed by CRDs."
slug: "introducing-kubesynapse"
published: true
---

Today we are making KubeSynapse available as an open-source project under the Apache 2.0 license.

## What is KubeSynapse?

KubeSynapse is a **Kubernetes-native AI operations platform**. It lets you deploy, govern, and orchestrate AI agents directly inside your cluster using Custom Resource Definitions (CRDs).

Every agent is a first-class Kubernetes resource — a StatefulSet with its own PersistentVolumeClaim, Service, ConfigMap, and network policy. You declare agents with YAML, manage them with `kubectl`, and deploy them with Helm.

## Why We Built It

Modern Kubernetes environments generate enormous operational complexity. Alert fatigue is real. On-call engineers spend hours correlating logs, checking pod status, and guessing at root causes at 3 AM.

We wanted an AI layer that:

- Lives **inside** the cluster, not in an external SaaS
- Is **governed** with token budgets, approval gates, and audit trails
- Supports **multi-agent workflows** with dependency graphs and retries
- Provides **full observability** — execution traces, LLM call inspection, and live activity streaming

## Core Architecture

```
Control Plane          Execution Plane         Shared Services
├─ Kubernetes API      ├─ OpenCode Runtime     ├─ LiteLLM (Model Router)
├─ Operator (Kopf)     ├─ Pi Runtime           ├─ PostgreSQL
├─ API Gateway         ├─ MCP Sidecars (10)    ├─ Redis
└─ CRDs (12 types)    └─ Worker Jobs          └─ Qdrant
```

The operator watches CRD events and reconciles the desired state — provisioning StatefulSets, attaching MCP sidecars, enforcing policies, and managing lifecycle.

## Key Features

### CRD-Driven Governance

The current chart installs 12 custom resource types. The core agent control plane includes:

- **AIAgent** — Define runtime, model, system prompt, MCP tools, and storage
- **AgentWorkflow** — Multi-step DAG pipelines with approval gates
- **AgentPolicy** — Token budgets, allowed models, PII masking, tool whitelists
- **AgentTenant** — Namespace-scoped multi-tenancy
- **AgentApproval** — Human-in-the-loop control points
- **McpConnection** — Saved MCP connection definitions

Additional shipped CRDs cover webhook receivers, workflow triggers, and observability resources.

### Visual Workflow Composer

Build multi-agent pipelines with a drag-and-drop canvas. Trigger → Agent Step → Approval Gate → Agent Step. The composer supports horizontal and vertical layouts, auto-arrangement, and real-time execution monitoring.

### MCP Tool Ecosystem

Bundled MCP sidecars cover code execution, web search, browser automation, database access, Git, GitHub, Kubernetes operations, messaging, RAG, and document parsing. Saved `McpConnection` resources extend that with remote, hub, and sidecar transport patterns.

### Execution Observatory

Distributed traces for every agent invocation and workflow run. Inspect individual LLM calls, measure step timing, track token usage, and compare executions side-by-side.

## Getting Started

```bash
helm install kubesynapse \
  oci://quay.io/yakdhane/charts/kubesynapse \
  --namespace kubesynapse --create-namespace \
  --set platformSecrets.native.openaiApiKey="sk-..."
```

Then define your first agent:

```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AIAgent
metadata:
  name: incident-triage
  namespace: production
spec:
  runtime:
    kind: opencode
  model: claude-sonnet-4
  systemPrompt: |
    You are an SRE agent. When an alert fires,
    correlate logs, check pod status, and suggest
    remediation. Ask before destructive commands.
  mcpSidecars:
    - name: kubernetes
    - name: web-search
```

## What's Next

We are actively working on:

- **Runtime hardening** with defense-in-depth security controls
- **Enhanced A2A protocol** for cross-cluster agent communication
- **Helm chart hardening** for production enterprise deployments
- **Expanded MCP sidecar catalog** with database and cloud provider tools

Self-hosted, open source, and built for the engineers who keep the infrastructure running.
