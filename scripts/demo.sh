#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# kubesynapse 5-Minute Demo
# ────────────────────────────────────────────────────────────────────
# One-command demo: curl -sL https://get.kubesynapse.ai/demo.sh | bash
#
# Spins up a local Kind cluster, installs kubesynapse via Helm,
# deploys a sample AI agent, and demonstrates invocation.
# Total wall-clock target: < 3 minutes.
# ────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }
step()  { echo -e "\n${CYAN}${BOLD}═══ $* ═══${NC}\n"; }

# ── Prerequisites check ────────────────────────────────────────────
step "Step 1/6: Checking prerequisites"

MISSING=()

for cmd in docker kubectl kind helm; do
  if ! command -v "$cmd" &>/dev/null; then
    MISSING+=("$cmd")
  fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
  err "Missing required tools: ${MISSING[*]}"
  echo ""
  echo "Install them before running this demo:"
  echo "  Docker:  https://docs.docker.com/get-docker/"
  echo "  kubectl: https://kubernetes.io/docs/tasks/tools/"
  echo "  kind:    https://kind.sigs.k8s.io/docs/user/quick-start/"
  echo "  Helm:    https://helm.sh/docs/intro/install/"
  exit 1
fi

ok "All prerequisites found (docker, kubectl, kind, helm)"

# ── Create Kind cluster ────────────────────────────────────────────
step "Step 2/6: Creating local Kubernetes cluster (Kind)"

CLUSTER_NAME="kubesynapse-demo"

if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  info "Cluster '${CLUSTER_NAME}' already exists, reusing it"
else
  info "Creating Kind cluster '${CLUSTER_NAME}'..."
  kind create cluster --name "${CLUSTER_NAME}" --wait 2m
  ok "Kind cluster '${CLUSTER_NAME}' is ready"
fi

# Set kubectl context
kubectl config use-context "kind-${CLUSTER_NAME}" &>/dev/null || true

# ── Install cert-manager (required for webhook TLS) ─────────────────
step "Step 3/6: Installing cert-manager"

if kubectl get namespace cert-manager &>/dev/null; then
  info "cert-manager already installed"
else
  info "Installing cert-manager (required for CRD webhooks)..."
  kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.5/cert-manager.yaml
  kubectl wait --for=condition=Available deployment/cert-manager -n cert-manager --timeout=120s
  kubectl wait --for=condition=Available deployment/cert-manager-webhook -n cert-manager --timeout=120s
  ok "cert-manager ready"
fi

# ── Install kubesynapse via Helm ─────────────────────────────────────
step "Step 4/6: Installing kubesynapse with Helm"

# Use local chart if available, otherwise fetch from repo
CHART_PATH=""
if [ -f "./charts/kubesynapse/Chart.yaml" ]; then
  CHART_PATH="./charts/kubesynapse"
  info "Using local chart at ${CHART_PATH}"
elif [ -d "../charts/kubesynapse" ]; then
  CHART_PATH="../charts/kubesynapse"
  info "Using local chart at ${CHART_PATH}"
else
  info "Fetching kubesynapse chart from repository..."
  helm repo add kubesynapse https://charts.kubesynapse.ai 2>/dev/null || true
  helm repo update
  CHART_PATH="kubesynapse/kubesynapse"
fi

# Install with demo values (minimal resource footprint)
helm upgrade --install kubesynapse "${CHART_PATH}" \
  --namespace kubesynapse \
  --create-namespace \
  --wait \
  --timeout 5m \
  --set operator.replicas=1 \
  --set apiGateway.replicas=1 \
  --set opencodeRuntime.enabled=false \
  --set webUi.enabled=false \
  --set postgresql.enabled=false \
  --set litellm.enabled=false \
  --set resources.requests.cpu=100m \
  --set resources.requests.memory=128Mi \
  --set resources.limits.cpu=500m \
  --set resources.limits.memory=512Mi

ok "kubesynapse installed successfully"

# Wait for pods
info "Waiting for all pods to be ready..."
kubectl wait --for=condition=Ready pods --all -n kubesynapse --timeout=120s
kubectl get pods -n kubesynapse

# ── Deploy a sample AIAgent ────────────────────────────────────────
step "Step 5/6: Deploying a sample AI Agent"

AGENT_NAME="code-reviewer"
AGENT_NAMESPACE="default"

cat <<EOF | kubectl apply -f -
apiVersion: kubesynapse.ai/v1alpha1
kind: AIAgent
metadata:
  name: ${AGENT_NAME}
  namespace: ${AGENT_NAMESPACE}
spec:
  description: "Reviews code for bugs, security issues, and style violations"
  runtime: opencode
  runtimeConfig:
    systemPrompt: |
      You are an expert code reviewer. Analyze code for:
      1. Security vulnerabilities (OWASP Top 10)
      2. Performance issues
      3. Code style and best practices
      4. Potential bugs and edge cases

      Provide specific, actionable feedback with line references.
  tools:
    - read_file
    - search_code
    - web_search
  mcpSidecars:
    - name: web-search
      image: ghcr.io/kubesynapse/mcp-web-search:latest
      env:
        - name: SEARCH_PROVIDER
          value: duckduckgo
  guardrails:
    promptInjectionDetection: true
    piiRedaction: true
    maxOutputTokens: 4096
  approvals:
    requireApproval: false
  git:
    pushPolicy: never
EOF

ok "AIAgent '${AGENT_NAME}' created"

# Wait for agent to be reconciled
info "Waiting for agent reconciliation..."
for i in $(seq 1 30); do
  PHASE=$(kubectl get aiagent "${AGENT_NAME}" -n "${AGENT_NAMESPACE}" -o jsonpath='{.status.phase}' 2>/dev/null || echo "pending")
  if [ "$PHASE" = "ready" ]; then
    ok "Agent '${AGENT_NAME}' is ready (phase: ${PHASE})"
    break
  fi
  sleep 2
done

# ── Port-forward and invoke ────────────────────────────────────────
step "Step 6/6: Invoking the agent"

info "Setting up port-forward to API gateway..."
kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway 8080:80 &
PF_PID=$!
sleep 3

# Ensure cleanup on exit
trap 'kill ${PF_PID} 2>/dev/null; kind delete cluster --name ${CLUSTER_NAME} 2>/dev/null || true' EXIT

info "Invoking agent '${AGENT_NAME}' to review a sample code snippet..."

INVOKE_RESPONSE=$(curl -s -X POST "http://localhost:8080/api/v1/agents/${AGENT_NAME}/invoke" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer demo-token" \
  -d '{
    "input": "Review this Python function for security issues:\n\n```python\ndef process_user_input(data):\n    query = \"SELECT * FROM users WHERE name = '\" + data + \"'\"\n    result = db.execute(query)\n    return eval(result)\n```",
    "mode": "ask"
  }')

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}${BOLD}Agent Response:${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "${INVOKE_RESPONSE}" | python3 -m json.tool 2>/dev/null || echo "${INVOKE_RESPONSE}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}${BOLD}  Demo complete!${NC}"
echo ""
echo "  Next steps:"
echo "    • Open the Web UI:    kubectl port-forward -n kubesynapse svc/kubesynapse-web-ui 5173:80"
echo "    • View agent status:   kubectl get aiagent ${AGENT_NAME} -n ${AGENT_NAMESPACE} -o yaml"
echo "    • Read the docs:       https://docs.kubesynapse.ai"
echo "    • Join the community:  https://github.com/ykbytes/kubemininions/discussions"
echo ""
echo "  Cleanup: kind delete cluster --name ${CLUSTER_NAME}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Keep port-forward running for a moment to show results
sleep 2
