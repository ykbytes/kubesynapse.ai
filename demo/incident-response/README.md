# Incident Response Demo

This is the strongest demo for:

- SRE teams
- DevOps teams
- on-call responders
- platform operators who care about safe automation

## What It Proves

- Kubernetes-sidecar tooling for cluster inspection
- approval-gated remediation instead of blind automation
- signed webhook intake with HMAC and timestamp validation
- event-driven workflow launch
- traceable workflow execution for incident response

## Why This Demo Is Slightly Different

The architecture supports both CRDs and gateway-backed webhook and trigger flows.
For the live recording, the easiest reliable path is:

1. apply the agents, policy, workflow, and webhook secret from `bundle.yaml`
2. create the live webhook receiver and workflow trigger through the gateway API
3. send a signed webhook request with the helper script

This keeps the demo faithful to the current shipped gateway and operator behavior.

## Apply

```bash
kubectl apply -f demo/incident-response/bundle.yaml
```

## Bootstrap Receiver And Trigger

```bash
./demo/incident-response/bootstrap-webhook.sh
```

PowerShell:

```powershell
./demo/incident-response/bootstrap-webhook.ps1
```

## Trigger The Incident Workflow

```bash
./demo/incident-response/send-signed-webhook.sh
```

PowerShell:

```powershell
./demo/incident-response/send-signed-webhook.ps1
```

## What To Show On Camera

1. `kubectl get aiagents,agentworkflows -n default`
2. `kubectl get secret incident-webhook-secret -n default`
3. the bootstrap script creating the receiver and trigger
4. the signed webhook firing successfully
5. the workflow appearing and pausing at the remediation approval step
6. the approval being resolved live

## Strong Narration Angle

`This is not autonomous chaos. It is signed event intake, validated dispatch, evidence-first triage, and a human approval before the risky step runs.`
