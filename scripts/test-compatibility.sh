#!/usr/bin/env bash
# kubesynapse Compatibility Test Suite
# Tests Helm install + smoke tests across multiple K8s versions using Kind.
#
# Usage:
#   ./scripts/test-compatibility.sh              # Test all versions
#   ./scripts/test-compatibility.sh 1.31         # Test specific version
#   ./scripts/test-compatibility.sh --cleanup-only  # Cleanup leftover clusters
#
# Requirements:
#   - kind (https://kind.sigs.k8s.io)
#   - helm 3.12+
#   - kubectl
#   - docker or podman

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CHART_DIR="$REPO_ROOT/charts/kubesynapse"

# ── Configuration ──────────────────────────────────────────────────
CLUSTER_PREFIX="kubesynapse-compat"
TEST_NAMESPACE="kubesynapse"
TEST_TIMEOUT="600"  # 10 minutes
ALL_VERSIONS=("1.25" "1.27" "1.29" "1.31" "1.32")
KIND_IMAGES=(
  "kindest/node:v1.25.16"
  "kindest/node:v1.27.16"
  "kindest/node:v1.29.13"
  "kindest/node:v1.31.7"
  "kindest/node:v1.32.3"
)
RESULTS=()

# ── Colors ─────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_pass()  { echo -e "${GREEN}[PASS]${NC}  $*"; }
log_fail()  { echo -e "${RED}[FAIL]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }

# ── Cleanup ────────────────────────────────────────────────────────
cleanup_cluster() {
  local version="$1"
  local cluster_name="${CLUSTER_PREFIX}-${version//./-}"
  if kind get clusters 2>/dev/null | grep -q "^${cluster_name}$"; then
    log_info "Deleting cluster: $cluster_name"
    kind delete cluster --name "$cluster_name" || true
  fi
}

cleanup_all() {
  log_info "Cleaning up all compatibility test clusters..."
  for version in "${ALL_VERSIONS[@]}"; do
    cleanup_cluster "$version"
  done
}

# ── Health Check ───────────────────────────────────────────────────
wait_for_pods() {
  local cluster_name="$1"
  local timeout="$2"
  local start_time
  start_time=$(date +%s)

  log_info "Waiting for all pods to be Ready (timeout: ${timeout}s)..."
  while true; do
    local not_ready
    not_ready=$(kubectl get pods -n "$TEST_NAMESPACE" --no-headers 2>/dev/null | grep -v -c 'Running\|Completed' || echo "0")
    local total
    total=$(kubectl get pods -n "$TEST_NAMESPACE" --no-headers 2>/dev/null | wc -l || echo "0")

    if [ "$not_ready" -eq 0 ] && [ "$total" -gt 0 ]; then
      log_pass "All $total pods Ready"
      return 0
    fi

    local elapsed
    elapsed=$(($(date +%s) - start_time))
    if [ "$elapsed" -ge "$timeout" ]; then
      log_fail "Timeout waiting for pods. ${not_ready}/${total} not ready after ${timeout}s"
      kubectl get pods -n "$TEST_NAMESPACE" 2>/dev/null || true
      return 1
    fi

    sleep 10
  done
}

test_api_health() {
  local port=18080
  log_info "Port-forwarding API Gateway to :${port}..."

  kubectl port-forward -n "$TEST_NAMESPACE" svc/kubesynapse-api-gateway "${port}:8080" &>/dev/null &
  local pf_pid=$!
  sleep 5

  local result=0

  # Test /api/health
  log_info "Testing GET /api/health..."
  if curl -sf --max-time 10 "http://localhost:${port}/api/health" > /dev/null 2>&1; then
    log_pass "/api/health → 200 OK"
  else
    log_fail "/api/health failed"
    result=1
  fi

  # Test /api/ready
  log_info "Testing GET /api/ready..."
  if curl -sf --max-time 10 "http://localhost:${port}/api/ready" > /dev/null 2>&1; then
    log_pass "/api/ready → 200 OK"
  else
    log_fail "/api/ready failed"
    result=1
  fi

  kill $pf_pid 2>/dev/null || true
  return $result
}

test_agent_create() {
  log_info "Creating test AIAgent via kubectl..."

  cat <<'EOF' | kubectl apply -f - > /dev/null 2>&1
apiVersion: kubesynapse.ai/v1alpha1
kind: AIAgent
metadata:
  name: compat-test-agent
  namespace: kubesynapse
spec:
  displayName: "Compatibility Test Agent"
  model: gpt-4
  systemPrompt: "You are a test agent."
  runtime: opencode
EOF

  sleep 10

  # Check if the CRD was reconciled
  if kubectl get aiagent compat-test-agent -n "$TEST_NAMESPACE" &>/dev/null; then
    local status
    status=$(kubectl get aiagent compat-test-agent -n "$TEST_NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    log_pass "AIAgent created — status: $status"
    kubectl delete aiagent compat-test-agent -n "$TEST_NAMESPACE" --ignore-not-found > /dev/null 2>&1
    return 0
  else
    log_fail "AIAgent CRD not found or creation failed"
    return 1
  fi
}

# ── Test Single Version ────────────────────────────────────────────
test_version() {
  local version="$1"
  local index
  # Find index in ALL_VERSIONS
  for i in "${!ALL_VERSIONS[@]}"; do
    if [ "${ALL_VERSIONS[$i]}" = "$version" ]; then
      index=$i
      break
    fi
  done

  local cluster_name="${CLUSTER_PREFIX}-${version//./-}"
  local kind_image="${KIND_IMAGES[$index]}"

  echo ""
  echo "============================================================"
  log_info "Testing kubesynapse on Kubernetes v${version}"
  echo "============================================================"

  # Create cluster
  log_info "Creating Kind cluster: $cluster_name (image: $kind_image)"
  if ! kind create cluster --name "$cluster_name" --image "$kind_image" --wait 5m; then
    log_fail "Failed to create Kind cluster for v${version}"
    RESULTS+=("v${version}:FAIL(setup)")
    return 1
  fi

  # Install kubesynapse
  log_info "Installing kubesynapse via Helm..."
  if ! helm install kubesynapse "$CHART_DIR" \
    --namespace "$TEST_NAMESPACE" \
    --create-namespace \
    --set litellm.enabled=true \
    --set litellm.masterKey=compat-test-key \
    --set qdrant.enabled=false \
    --set nats.enabled=false \
    --set networkPolicy.enabled=false \
    --set podDisruptionBudget.enabled=false \
    --wait \
    --timeout "${TEST_TIMEOUT}s" 2>&1; then
    log_fail "Helm install failed for v${version}"
    helm status kubesynapse -n "$TEST_NAMESPACE" 2>/dev/null || true
    RESULTS+=("v${version}:FAIL(install)")
    cleanup_cluster "$version"
    return 1
  fi

  # Wait for pods
  if ! wait_for_pods "$cluster_name" "$TEST_TIMEOUT"; then
    RESULTS+=("v${version}:FAIL(pods)")
    cleanup_cluster "$version"
    return 1
  fi

  # API health check
  local all_pass=0
  if ! test_api_health; then
    all_pass=1
  fi

  # Agent creation test
  if ! test_agent_create; then
    all_pass=1
  fi

  # Report
  if [ "$all_pass" -eq 0 ]; then
    log_pass "v${version}: ALL TESTS PASSED"
    RESULTS+=("v${version}:PASS")
  else
    log_fail "v${version}: SOME TESTS FAILED"
    RESULTS+=("v${version}:FAIL(tests)")
  fi

  # Cleanup
  cleanup_cluster "$version"
  return $all_pass
}

# ── Main ───────────────────────────────────────────────────────────
main() {
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║     kubesynapse Compatibility Test Suite — v1.0.0              ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""

  # Check prerequisites
  for cmd in kind helm kubectl; do
    if ! command -v "$cmd" &>/dev/null; then
      log_fail "$cmd is required but not installed"
      exit 1
    fi
  done

  if ! helm lint "$CHART_DIR" > /dev/null 2>&1; then
    log_warn "Helm lint found issues — proceeding anyway"
  fi

  # Parse args
  local test_versions=()
  if [ $# -eq 0 ]; then
    test_versions=("${ALL_VERSIONS[@]}")
  elif [ "$1" = "--cleanup-only" ]; then
    cleanup_all
    exit 0
  else
    for v in "$@"; do
      if [[ " ${ALL_VERSIONS[*]} " =~ " ${v} " ]]; then
        test_versions+=("$v")
      else
        log_warn "Unknown version: $v (supported: ${ALL_VERSIONS[*]})"
      fi
    done
  fi

  if [ ${#test_versions[@]} -eq 0 ]; then
    log_fail "No valid versions to test"
    exit 1
  fi

  log_info "Testing versions: ${test_versions[*]}"
  log_warn "This will create and destroy Kind clusters. Press Ctrl+C to abort."
  sleep 3

  # Run tests
  local exit_code=0
  for version in "${test_versions[@]}"; do
    if ! test_version "$version"; then
      exit_code=1
    fi
  done

  # Summary
  echo ""
  echo "============================================================"
  echo "                    TEST SUMMARY"
  echo "============================================================"
  for result in "${RESULTS[@]}"; do
    if [[ "$result" == *":PASS" ]]; then
      log_pass "$result"
    else
      log_fail "$result"
    fi
  done
  echo ""

  local pass_count
  pass_count=$(printf '%s\n' "${RESULTS[@]}" | grep -c ":PASS" || echo "0")
  local total_count=${#RESULTS[@]}
  log_info "Passed: $pass_count / $total_count"

  if [ "$exit_code" -eq 0 ]; then
    log_pass "ALL COMPATIBILITY TESTS PASSED"
  else
    log_fail "SOME COMPATIBILITY TESTS FAILED"
  fi

  exit $exit_code
}

main "$@"
