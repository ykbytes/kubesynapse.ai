# Observability Explained

This document explains what the observability feature is trying to do, how the current implementation behaves today, and how to use the demo config to make something visible in the UI.

## The Short Version

The observability model has four resource types:

1. `ConnectorPlugin`
   This answers: how do we collect data?
   Example: a Kubernetes connector, a Prometheus scraper, or an SNMP collector.

2. `ObservationTarget`
   This answers: what are we watching?
   Example: a namespace, a control-plane endpoint, or a set of pods selected by labels.

3. `ObservationPolicy`
   This answers: how do we judge whether what we collected is healthy or unhealthy?
   Example: retention rules, anomaly settings, alert rules, and notification routing.

4. `ObservationReport`
   This is the result.
   It tells you what the policy concluded after looking at the target through the connector.

If you want the mental model in one sentence:

`target` defines scope, `connector` defines collection, `policy` defines evaluation, and `report` carries the outcome.

## What Is Real Today

Today the product already lets you create, edit, and inspect all four resource types in the UI.

What was missing before this update was a visible end-to-end result. You could define targets and policies, but nothing obvious showed why they mattered.

To fix that, the observation controller now creates and updates an `ObservationReport` for each target. It also supports a demo mode so you can deliberately force a visible finding and see the whole flow in the dashboard.

This means:

1. You can create a healthy target and still get a report card that explains the path.
2. You can create a demo target that intentionally fires, so the UI shows a non-empty report with findings.
3. The report is visible through the same observability workspace you already have.

## The Demo That Fires

Use [examples/observability-demo-fire.yaml](../examples/observability-demo-fire.yaml).

It creates:

1. `demo-kubernetes-connector`
   This is the declared collection layer.

2. `demo-fire-policy`
   This is the declared evaluation layer.

3. `demo-fire-target`
   This is the watched thing.

The important part is this annotation on the target:

```yaml
metadata:
  annotations:
    observability.kubesynth.ai/demo-mode: firing
```

That annotation tells the current controller to synthesize a visible firing report so you can inspect something concrete in the UI.

## Apply The Demo

From the repo root:

```powershell
kubectl apply -f .\examples\observability-demo-fire.yaml
```

Then wait about 60 seconds for the controller timer to run.

## What You Should See

Open the Observability workspace in the UI and inspect these resources in namespace `ai-agent-sandbox`:

1. `demo-kubernetes-connector`
   You should see the connector explanation and a ready status.

2. `demo-fire-policy`
   You should see the policy explanation, anomaly settings, and active alert count.

3. `demo-fire-target`
   You should see the target explanation and a degraded state.

4. `demo-fire-target-report`
   You should see the actual result: health score, findings, summary, observed value, expected value, deviation, and a recommendation.

That report is the point of the whole feature. It is where the user-facing answer appears after the rest of the resources define the collection and evaluation pipeline.

## Reading The Demo Report

When the demo fires, the report is intentionally written to be read from top to bottom:

1. `Health score`
   This gives you a fast signal for whether the target is broadly healthy.

2. `Findings`
   This tells you how many concrete issues were surfaced.

3. `Summary`
   This explains, in plain language, what the report is trying to show.

4. `Finding cards`
   Each finding shows:
   - the metric that drifted
   - the severity
   - the observed value
   - the expected value
   - the deviation
   - the recommendation

## Example: Healthy vs Firing

### Healthy target

If the target is healthy, the report acts as a quiet status document.

Example meaning:

- the target is being watched
- the connector is available
- the policy is attached
- no findings are active right now

### Firing target

If the target is firing, the report acts like an incident summary.

Example meaning:

- the policy judged the observed behavior as abnormal
- one or more findings were generated
- the report tells the operator what changed and what to look at next

## Why The UI Now Shows Purpose Text Even When A Description Is Missing

Older resources may still exist without a hand-written `description` field.

Instead of showing a placeholder like "No description was provided yet", the UI now derives a purpose sentence from the actual spec.

Examples:

1. A target can explain which connector it uses and which policy evaluates it.
2. A policy can explain retention, algorithm choice, and notification destination.
3. A connector can explain protocol, image, port, and supported capabilities.

That makes the page readable even before every resource has been manually curated.

## Switching The Demo Off

If you want the same target to stop firing, change:

```yaml
observability.kubesynth.ai/demo-mode: firing
```

to:

```yaml
observability.kubesynth.ai/demo-mode: healthy
```

Then re-apply the target and wait for the next controller reconciliation.

## Practical Takeaway

If you are trying to understand the feature, look at it in this order:

1. Open the target and read what is being watched.
2. Open the connector and read how the data is supposed to be collected.
3. Open the policy and read how the data is judged.
4. Open the report and read the actual result.

That is the full purpose of this observability workflow.
