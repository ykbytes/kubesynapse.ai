# AI-300 Practice Exam Generator

This folder contains a scaffolded agent and workflow that can generate a
60-question Azure-style practice exam for the (new) AI-300 certification by
scanning authoritative web resources.

Files:
- `agent.yaml` — `AIAgent` definition with a `web-scan` skill.
- `workflow.yaml` — `AgentWorkflow` that runs the agent to produce the exam HTML.
- `project-context.yaml` — ConfigMap with exam format, breakdown and rules.

Usage (cluster must have operator and agent sandbox running):

1. Apply the project context and agent, then wait for the agent pod to be ready:

```powershell
kubectl apply -f examples/ai-300-exam/project-context.yaml
kubectl apply -f examples/ai-300-exam/agent.yaml
kubectl wait --for=condition=ready pod -l agent-name=ai300-exam-agent -n default --timeout=180s
```

2. Start the workflow to generate the exam:

```powershell
kubectl apply -f examples/ai-300-exam/workflow.yaml
kubectl get agentworkflow ai300-exam-generation -o yaml
```

3. When the workflow completes, the single HTML file will be written into the
   worker workspace (typically an artifacts PVC). To retrieve it you can exec
   into the sandbox pod or copy from the artifacts PVC. Example (if agent writes
   directly to `/workspace` inside the sandbox pod):

```powershell
# find the sandbox pod (agent-name=ai300-exam-agent)
kubectl get pods -l agent-name=ai300-exam-agent -n default
kubectl -n default exec -it <pod> -- cat /workspace/ai300_practice_exam.html > ./ai300_practice_exam.html
```

Notes & ethics:
- The agent is instructed to avoid reproducing paid exam dumps or
  copyrighted exam content verbatim. Use the generated exam for study and
  practice only.
- Review the generated questions and answers for accuracy before use.
