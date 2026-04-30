---
title: "Workflow Composer: Visual DAG Builder for Multi-Agent Pipelines"
date: "2026-04-28"
author: "KubeSynapse Team"
tags: ["feature", "composer", "workflows"]
summary: "The Workflow Composer lets you visually build multi-agent DAG pipelines with drag-and-drop. Support for approval gates, parallel execution, retries, and real-time monitoring."
slug: "workflow-composer-v2"
published: true
---

Building multi-agent workflows shouldn't require hand-editing YAML dependency graphs. Today we are shipping the **Workflow Composer** — a visual DAG builder integrated directly into the KubeSynapse console.

## What Changed

The Composer provides a full React Flow canvas where you can:

- **Drag agent steps** onto the canvas from your deployed agent inventory
- **Draw dependency edges** between steps to define execution order
- **Add approval gates** for human-in-the-loop review before destructive actions
- **Toggle layout direction** between horizontal and vertical arrangements
- **Auto-layout** with a single click to organize complex graphs

## How It Works

Every workflow in KubeSynapse is an `AgentWorkflow` CRD. The Composer is a visual editor for that CRD — it reads the current spec, renders it as a graph, and writes changes back to the API.

```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: incident-response
spec:
  steps:
    - name: triage
      agentRef: incident-triage
      prompt: "Analyze the alert and correlate with pod events."
    - name: analyze-logs
      agentRef: log-analyzer
      dependsOn: [triage]
      prompt: "Deep-dive into logs for affected pods."
    - name: remediate
      agentRef: incident-triage
      dependsOn: [analyze-logs]
      requireApproval: true
      prompt: "Apply the recommended fix."
```

The Composer renders this as: **Trigger** → **triage** → **analyze-logs** → **remediate** (with approval gate).

## Real-Time Execution Monitoring

When a workflow is running, the Composer shows live status on each node:

- Green pulse for completed steps
- Amber for steps currently executing
- Gray for steps waiting on dependencies
- Red for failed steps with retry indicators

The **Run History Panel** in the sidebar shows all previous executions with timing, status, and log access.

## Edge Design

Connection edges use animated dashed paths with arrow markers. Edge colors reflect the relationship type — standard dependencies in teal, approval-gated dependencies in purple.

## What's Next

We are working on:

- **Conditional branching** — route execution based on step output
- **Loop steps** — retry patterns with configurable exit conditions
- **Artifact passing** — explicit data flow between steps
- **Template library** — pre-built workflow patterns for common operations
