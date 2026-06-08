#!/usr/bin/env bash
# Shared helpers for KubeSynapse incident scripts.
# Source via:  . "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

set -euo pipefail

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BLUE=$'\033[0;34m'; CYAN=$'\033[0;36m'; NC=$'\033[0m'
info() { echo "${BLUE}[INFO]${NC}  $*"; }
ok()   { echo "${GREEN}[OK]${NC}    $*"; }
warn() { echo "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo "${RED}[ERROR]${NC} $*" >&2; }

# ── Resolve gateway URL & token ──────────────────────────────────────
# Args: $1 = local port (default 8080)
# Sets: GATEWAY_URL, KUBESYNAPSE_API_TOKEN
resolve_context() {
  local port="${1:-8080}"
  if [[ -z "${GATEWAY_URL:-}" ]]; then
    GATEWAY_URL="${KUBESYNAPSE_GATEWAY_URL:-}"
    if [[ -z "${GATEWAY_URL}" ]]; then
      if ! ss -lnt 2>/dev/null | grep -q ":${port} "; then
        info "No listener on port ${port} — starting port-forward to kubesynapse-api-gateway"
        kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway "${port}:8080" >/tmp/kubesynapse-pf-gateway.log 2>&1 &
        sleep 4
      fi
      GATEWAY_URL="http://127.0.0.1:${port}"
    fi
  fi

  if [[ -z "${KUBESYNAPSE_API_TOKEN:-}" ]]; then
    local token
    token="$(kubectl get secret kubesynapse-llm-api-keys -n kubesynapse -o jsonpath='{.data.API_GATEWAY_SHARED_TOKEN}' 2>/dev/null | base64 -d 2>/dev/null || true)"
    if [[ -n "${token}" ]]; then
      ok "Loaded gateway token from kubesynapse-llm-api-keys"
    else
      token="$(kubectl get secret kubesynapse-shared-auth -n kubesynapse -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || true)"
    fi
    if [[ -z "${token}" ]]; then
      err "Could not resolve KUBESYNAPSE_API_TOKEN. Set the env var or install the platform with a shared token secret."
      exit 1
    fi
    KUBESYNAPSE_API_TOKEN="${token}"
  fi
  export GATEWAY_URL KUBESYNAPSE_API_TOKEN
}
