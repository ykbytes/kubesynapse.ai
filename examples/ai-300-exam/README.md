# AI-300 Practice Exam Generator

Generate a Udemy-ready **60-question** practice exam for the **Microsoft AI-300:
Operationalizing Machine Learning and Generative AI Solutions** certification
using a 3-agent pipeline with web-search grounding.

## Exam Details

| Field | Value |
|---|---|
| Exam Code | AI-300 |
| Certification | Microsoft Certified: Machine Learning Operations (MLOps) Engineer Associate |
| Passing Score | 700 |
| Status | Beta |
| Study Guide | [learn.microsoft.com/.../ai-300](https://learn.microsoft.com/en-us/credentials/certifications/resources/study-guides/ai-300) |

## Architecture

**3 Specialized Agents** on `claude-haiku-4-5` with web-search MCP sidecar + SerpAPI:

| Agent | Role | Permissions |
|---|---|---|
| `ai300-researcher` | Discovers exam objectives, collects reference material via web search | Read-only |
| `ai300-exam-writer` | Generates original questions with per-question fact verification | Read/Write |
| `ai300-qa-reviewer` | Validates every answer against Microsoft Learn documentation | Read-only |

**8-Step Workflow Pipeline** (`ai300-exam-generation`):

1. **research-exam-scope** — Researcher discovers AI-300 objectives from Microsoft Learn
2. **deep-dive-references** — Researcher collects detailed technical facts per domain
3. **generate-questions-part1** — Writer creates Qs 1–27 (Domains 1–2: MLOps + ML Lifecycle)
4. **generate-questions-part2** — Writer creates Qs 28–60 (Domains 3–5: GenAIOps + QA + Optimize)
5. **validate-all-questions** — Reviewer fact-checks all 60 questions via SerpAPI
6. **compile-udemy-html** — Writer compiles validated questions into interactive HTML
7. **final-quality-check** — Reviewer performs final QA on the HTML output
8. **publish-gate** — Conditional gate: passes only if `ready_for_publish: true`

## AI-300 Exam Domains (5 domains)

| # | Domain | Weight | Questions |
|---|---|---|---|
| 1 | Design and implement an MLOps infrastructure | 15–20% | 11 |
| 2 | Implement machine learning model lifecycle and operations | 25–30% | 16 |
| 3 | Design and implement a GenAIOps infrastructure | 20–25% | 14 |
| 4 | Implement generative AI quality assurance and observability | 10–15% | 10 |
| 5 | Optimize generative AI systems and model performance | 10–15% | 9 |

## Files

| File | Description |
|---|---|
| `agent.yaml` | 3 AIAgent definitions (researcher, writer, reviewer) |
| `workflow.yaml` | 8-step AgentWorkflow pipeline |
| `project-context.yaml` | ConfigMap with full AI-300 study guide objectives |
| `deploy.ps1` | Fail-fast PowerShell deployment script |

## Quick Deploy

```powershell
# Deploy everything (validates, applies, waits for sandboxes)
.\examples\ai-300-exam\deploy.ps1
```

## Manual Deploy

```powershell
kubectl apply -f examples/ai-300-exam/project-context.yaml
kubectl apply -f examples/ai-300-exam/agent.yaml
kubectl apply -f examples/ai-300-exam/workflow.yaml
```

## Trigger the Workflow

```powershell
# Via API gateway
curl -X POST http://localhost:18080/workflows/ai300-exam-generation/trigger
```

## Retrieve Output

```powershell
# Find the writer sandbox pod
kubectl get pods -l agent-name=ai300-exam-writer -n default
kubectl -n default cp <pod>:/workspace/ai300_practice_exam.html ./ai300_practice_exam.html
```

## Question Types

- **Multiple Choice** (~30 questions) — single correct answer from A/B/C/D
- **Multiple Select** (~10 questions) — choose N correct answers
- **Scenario/Case Study** (~10 questions) — realistic MLOps/GenAIOps business scenarios
- **Ordering/Sequence** (~5 questions) — arrange steps in correct order
- **Yes/No Series** (~5 questions) — evaluate multiple statements as true/false

## Notes & Ethics

- All questions are **synthesized from public Microsoft documentation** — no proprietary exam dumps.
- Every question explanation cites at least one Microsoft Learn URL.
- SerpAPI is used for Google search grounding during research and verification.
- Review the generated questions for accuracy before publishing on Udemy.
