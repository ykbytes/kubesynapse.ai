# Creative Production Demo

This is the best closer for the video because it proves the platform is useful
outside a pure ops firefight.

It is still aimed at engineers. The point is not generic content generation. The
point is that KubeSynapse can stage work, enforce approvals, and produce reviewable
artifacts for launch and production workflows too.

## What It Proves

- the same CRD and workflow model supports production-launch work
- artifact handoff across multiple specialist roles
- final packaging behind an approval gate
- grounded messaging that does not overclaim what the product does

## Apply

```bash
kubectl apply -f demo/creative-production/bundle.yaml
```

## Trigger

```bash
agentctl --gateway http://localhost:8080 workflows trigger conference-launch-pack
```

## What To Show On Camera

1. the workflow producing the hook, run-of-show, and social pack
2. the final approval gate before the launch pack is finalized
3. generated artifacts that can actually be reused for the video and launch

## Strong Narration Angle

`The same platform primitives that help SRE and platform teams can also drive disciplined creative production, as long as the work still benefits from staged execution, clear artifacts, and human approval.`
