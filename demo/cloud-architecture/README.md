# Cloud Architecture Demo

This is the strongest demo for:

- cloud architects
- platform leads
- security reviewers
- FinOps and infrastructure leadership

## What It Proves

- multi-agent decision support without pretending architecture should auto-ship
- explicit separation of architecture, security, and cost review roles
- use of workflow review stages and final approval
- artifact handoff that feels like an ADR pipeline, not a chat transcript

## Apply

```bash
kubectl apply -f demo/cloud-architecture/bundle.yaml
```

## Trigger

```bash
agentctl --gateway-url http://localhost:8080 workflows trigger multi-cluster-platform-decision
```

## What To Show On Camera

1. the workflow DAG and named review roles
2. the security review stage
3. the final approval pause before the decision memo is finalized
4. the generated ADR-style artifacts

## Strong Narration Angle

`AI should not magically decide your platform shape. It should help surface the tradeoffs faster, force role separation, and package a decision memo a real architect can challenge.`
