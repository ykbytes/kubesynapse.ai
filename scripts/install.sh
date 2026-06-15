#!/usr/bin/env bash
# install.sh — build, load, and install KubeSynapse on a local kind cluster
# (or any cluster you can push images to).
#
# This is the bash equivalent of scripts/deploy-kind.ps1. Both scripts wrap
# the same set of operations so a first-time user on any platform can do
# a clean install with one command.
#
# Usage:
#   ./scripts/install.sh                           # kind, default values
#   ADMIN_PASSWORD="YourPwd1!" ./scripts/install.sh # set admin password
#   SKIP_BUILD=1 SKIP_LOAD=1 ./scripts/install.sh  # reuse already-loaded images
#   RECREATE_CLUSTER=1 ./scripts/install.sh         # destroy + recreate cluster
#   WHATIF=1 ./scripts/install.sh                   # dry-run, print actions only
#
# Required tools: bash, docker, kind, kubectl, helm, base64, openssl.
# `openssl` is the only one Linux/macOS usually have out of the box.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CLUSTER_NAME="${CLUSTER_NAME:-kubesynapse-dev}"
NAMESPACE="${NAMESPACE:-kubesynapse}"
RELEASE_NAME="${RELEASE_NAME:-kubesynapse}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
SHARED_TOKEN="${SHARED_TOKEN:-}"
DATABASE_PASSWORD="${DATABASE_PASSWORD:-}"
JWT_SECRET="${JWT_SECRET:-}"
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-}"
CONTAINER_CLI="${CONTAINER_CLI:-docker}"
HELM_TIMEOUT_MINUTES="${HELM_TIMEOUT_MINUTES:-20}"
ROLLOUT_TIMEOUT_MINUTES="${ROLLOUT_TIMEOUT_MINUTES:-10}"
RECREATE_CLUSTER="${RECREATE_CLUSTER:-}"
SKIP_BUILD="${SKIP_BUILD:-}"
SKIP_LOAD="${SKIP_LOAD:-}"
SKIP_RESTART="${SKIP_RESTART:-}"
WHATIF="${WHATIF:-}"
VERBOSE="${VERBOSE:-}"

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
REPO_ROOT="$( cd -- "${SCRIPT_DIR}/.." &> /dev/null && pwd )"
CLUSTER_CONTEXT="kind-${CLUSTER_NAME}"
CHART_PATH="${REPO_ROOT}/charts/kubesynapse"
LOCAL_IMAGES_VALUES_PATH="${REPO_ROOT}/deploy/values.local-images.example.yaml"
KIND_QUICKSTART_VALUES_PATH="${REPO_ROOT}/deploy/values.kind.quickstart.yaml"
SKILLS_CATALOG_PATH="${REPO_ROOT}/catalog/skills-catalog.json"
LOG_FILE="${KUBESYNAPSE_INSTALL_LOG:-/tmp/kubesynapse-install.log}"

# ---------------------------------------------------------------------------
# Pretty output
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_GREY=$'\033[90m'
  C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_RST=$'\033[0m'
else
  C_CYAN=""; C_GREEN=""; C_GREY=""
  C_YELLOW=""; C_RED=""; C_RST=""
fi

step()  { printf "%s==>%s %s\n" "${C_CYAN}" "${C_RST}" "$*"; }
ok()    { printf "%s[ ok]%s %s\n" "${C_GREEN}" "${C_RST}" "$*"; }
warn()  { printf "%s[warn]%s %s\n" "${C_YELLOW}" "${C_RST}" "$*" >&2; }
fail()  { printf "%s[fail]%s %s\n" "${C_RED}" "${C_RST}" "$*" >&2; exit 1; }
banner(){ printf "\n%s%s%s\n\n" "${C_CYAN}" "$(printf '=%.0s' {1..78})" "${C_RST}"; printf "%s  %s%s\n" "${C_CYAN}" "$*" "${C_RST}"; printf "%s%s%s\n\n" "${C_CYAN}" "$(printf '=%.0s' {1..78})" "${C_RST}"; }
run() {
  if [[ -n "${WHATIF}" ]]; then
    printf "    %s[whatif]%s %s\n" "${C_GREY}" "${C_RST}" "$*"
    return 0
  fi
  "$@" 2>&1 | tee -a "$LOG_FILE"
}
need() {
  command -v "$1" >/dev/null 2>&1 || fail "Required tool '$1' is not on PATH"
  # A few CLIs (kubectl, helm) reject --version; we just need a non-empty
  # version line. Print whatever they emit on their first stdout/stderr line.
  local line
  line="$($1 --version 2>&1 | head -n1 || true)"
  if [[ -z "$line" ]]; then
    line="$($1 version 2>&1 | head -n1 || true)"
  fi
  [[ -n "$line" ]] || fail "Required tool '$1' did not report a version"
  ok "$1: $line"
}

random_suffix() {
  # Generate a cryptographically-random alphanumeric suffix of exactly $len
  # characters. We use openssl rand as the primary source (universally
  # available, returns the requested number of bytes, no SIGPIPE race) and
  # fall back to /dev/urandom if openssl is missing. We do NOT pipe the
  # output through a SIGPIPE-prone `tr | head` chain with an `awk` fallback,
  # because that combination misbehaves under `set -o pipefail`: `tr` exits
  # with 128+SIGPIPE the moment `head` closes the pipe, the pipeline returns
  # non-zero, the awk fallback runs, and the resulting password balloons
  # from 14 to 80+ characters.
  local len="${1:-32}"
  local out
  if command -v openssl >/dev/null 2>&1; then
    # Request 2x bytes to survive the alphanumeric filter cleanly.
    out="$(openssl rand -base64 "$((len * 2))" 2>/dev/null | tr -dc 'A-Za-z0-9' | head -c "$len")" || true
  fi
  if [[ -z "$out" || "${#out}" -lt "$len" ]]; then
    out="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c "$len")" || true
  fi
  # Last-resort fill (should never be hit): deterministic chars.
  if [[ -z "$out" || "${#out}" -lt "$len" ]]; then
    out="$(printf '%s' "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" | head -c "$len")"
  fi
  printf "%s" "${out:0:$len}"
}

ensure_secret() {
  local current="$1" prefix="$2" len="${3:-32}"
  if [[ -n "$current" ]]; then
    printf "%s" "$current"
  else
    printf "%s%s" "$prefix" "$(random_suffix "$len")"
  fi
}

# ---------------------------------------------------------------------------
# Step 0 — preflight
# ---------------------------------------------------------------------------
# WSL/Windows PATH bridge: when running from WSL, Windows binaries (kind.exe,
# helm.exe) may not be on PATH.  Create symlinks in a temp dir and prepend it.
if [[ "$(uname -s 2>/dev/null)" == *MINGW* || "$(uname -s 2>/dev/null)" == *MSYS* || -d "/mnt/c/Users" ]]; then
  _KSbin="/tmp/ksbin"
  mkdir -p "$_KSbin"
  _needs_link() { command -v "$1" &>/dev/null || [[ -x "$_KSbin/$1" ]]; }
  # kind — check WinGet, C:\bin, and Program Files
  if ! _needs_link kind; then
    for p in \
      "/mnt/c/bin/kind.exe" \
      "/mnt/c/Program Files/kind/kind.exe" \
      "$(find /mnt/c/Users/*/AppData/Local/Microsoft/WinGet/Packages -name 'kind.exe' 2>/dev/null | head -1)"; do
      if [[ -n "$p" && -f "$p" ]]; then
        ln -sf "$p" "$_KSbin/kind" 2>/dev/null || true
        break
      fi
    done
  fi
  # helm — check WinGet and choco
  if ! _needs_link helm; then
    for p in \
      "/mnt/c/ProgramData/chocolatey/bin/helm.exe" \
      "$(find /mnt/c/Users/*/AppData/Local/Microsoft/WinGet/Packages -name 'helm.exe' 2>/dev/null | head -1)"; do
      if [[ -n "$p" && -f "$p" ]]; then
        ln -sf "$p" "$_KSbin/helm" 2>/dev/null || true
        break
      fi
    done
  fi
  # kubectl — check WinGet (usually also available natively in WSL)
  if ! command -v kubectl &>/dev/null; then
    for p in \
      "/mnt/c/Users/*/AppData/Local/Microsoft/WinGet/Packages/kubectl.exe" \
      "/mnt/c/ProgramData/chocolatey/bin/kubectl.exe"; do
      if [[ -n "$p" && -f "$p" ]]; then
        ln -sf "$p" "$_KSbin/kubectl" 2>/dev/null || true
        break
      fi
    done
  fi
  export PATH="$_KSbin:$PATH"
  unset _needs_link _KSbin
fi

: > "$LOG_FILE"
banner "KubeSynapse local install  (cluster: ${CLUSTER_NAME})"

step "Preflight: required tools"
need docker
need kind
need kubectl
need helm
need openssl
need base64

[[ -f "$LOCAL_IMAGES_VALUES_PATH" ]]   || fail "Local images overlay not found at $LOCAL_IMAGES_VALUES_PATH"
[[ -f "$KIND_QUICKSTART_VALUES_PATH" ]] || fail "Kind quickstart overlay not found at $KIND_QUICKSTART_VALUES_PATH"
if [[ ! -f "$SKILLS_CATALOG_PATH" ]]; then
  warn "Skills catalog not found at $SKILLS_CATALOG_PATH — the in-app Catalog tab will be empty."
fi

# ---------------------------------------------------------------------------
# WSL ↔ Windows kubeconfig bridge
# ---------------------------------------------------------------------------
# When kind.exe (Windows binary) runs from WSL bash, it writes kubeconfig to
# the Windows HOME (C:\Users\<user>\.kube\config).  WSL's kubectl reads from
# /home/<user>/.kube/config — a different file.  We detect this mismatch and
# set KUBECONFIG to merge both files so kubectl can see kind contexts.
WINDOWS_KUBECONFIG=""
if [[ "$(uname -s 2>/dev/null)" == *MINGW* || "$(uname -s 2>/dev/null)" == *MSYS* || -d "/mnt/c/Users" ]]; then
  # Running under WSL or Git Bash — find the Windows kubeconfig
  WIN_USER="$(cmd.exe /C "echo %USERNAME%" 2>/dev/null | tr -d '\r' || true)"
  if [[ -n "$WIN_USER" && -f "/mnt/c/Users/${WIN_USER}/.kube/config" ]]; then
    WINDOWS_KUBECONFIG="/mnt/c/Users/${WIN_USER}/.kube/config"
    # Prepend Windows config so kubectl sees kind contexts created by kind.exe
    if [[ -z "${KUBECONFIG:-}" ]]; then
      export KUBECONFIG="${HOME}/.kube/config:${WINDOWS_KUBECONFIG}"
    else
      export KUBECONFIG="${KUBECONFIG}:${WINDOWS_KUBECONFIG}"
    fi
    ok "Detected WSL/Git Bash — bridging Windows kubeconfig (${WINDOWS_KUBECONFIG})"
  fi
fi

# ---------------------------------------------------------------------------
# Step 1 — secrets
# ---------------------------------------------------------------------------
step "Step 1/7 — Generate secrets"
ADMIN_PASSWORD="$(ensure_secret "${ADMIN_PASSWORD}" "KsAdmin!" 14)"
SHARED_TOKEN="$(ensure_secret "${SHARED_TOKEN}" "ks-shared-" 32)"
DATABASE_PASSWORD="$(ensure_secret "${DATABASE_PASSWORD}" "ks-db-" 32)"
JWT_SECRET="$(ensure_secret "${JWT_SECRET}" "ks-jwt-" 32)"
LITELLM_MASTER_KEY="$(ensure_secret "${LITELLM_MASTER_KEY}" "ks-litellm-" 32)"
printf "    %sAdmin password:%s %s\n" "${C_GREY}" "${C_RST}" "${ADMIN_PASSWORD}"
printf "    %sAPI shared token:%s %s...\n" "${C_GREY}" "${C_RST}" "${SHARED_TOKEN:0:12}"
printf "    %sDatabase password:%s %s...\n" "${C_GREY}" "${C_RST}" "${DATABASE_PASSWORD:0:12}"
printf "    %sJWT secret:%s %s...\n" "${C_GREY}" "${C_RST}" "${JWT_SECRET:0:12}"
printf "    %sLiteLLM master key:%s %s...\n" "${C_GREY}" "${C_RST}" "${LITELLM_MASTER_KEY:0:12}"

# ---------------------------------------------------------------------------
# Step 2 — kind cluster
# ---------------------------------------------------------------------------
step "Step 2/7 — Prepare kind cluster"
if kind get clusters 2>/dev/null | grep -qxF "${CLUSTER_NAME}"; then
  CLUSTER_EXISTS="1"
else
  CLUSTER_EXISTS=""
fi

if [[ -n "${RECREATE_CLUSTER}" && -n "${CLUSTER_EXISTS}" ]]; then
  step "Deleting existing kind cluster '${CLUSTER_NAME}'"
  run kind delete cluster --name "${CLUSTER_NAME}"
  CLUSTER_EXISTS=""
fi

if [[ -z "${CLUSTER_EXISTS}" ]]; then
  step "Creating kind cluster '${CLUSTER_NAME}'"
  KIND_ARGS=(--name "${CLUSTER_NAME}" --wait 120s)
  # When kind is a Windows binary (kind.exe) running in WSL, it writes
  # kubeconfig to the Windows HOME.  Pass --kubeconfig with a Windows-style
  # path so the context lands in the file we merged into KUBECONFIG above.
  if [[ -n "$WINDOWS_KUBECONFIG" ]]; then
    WIN_PATH="C:\\Users\\${WIN_USER}\\.kube\\config"
    KIND_ARGS+=(--kubeconfig "$WIN_PATH")
  fi
  run kind create cluster "${KIND_ARGS[@]}"
fi

step "Switching kubectl to '${CLUSTER_CONTEXT}'"
run kubectl config use-context "${CLUSTER_CONTEXT}"

# ---------------------------------------------------------------------------
# Step 3 — build images
# ---------------------------------------------------------------------------
IMAGES=(
  "localhost/kubesynapse/kubesynapse-operator:dev|operator"
  "localhost/kubesynapse/kubesynapse-api-gateway:dev|api-gateway"
  "localhost/kubesynapse/kubesynapse-web-ui:dev|web-ui"
  "localhost/kubesynapse/kubesynapse-opencode-rt:dev|opencode-runtime"
  "docker.io/litellm/litellm:v1.82.3-stable|deploy/litellm|deploy/litellm/Dockerfile"
)

if [[ -z "${SKIP_BUILD}" ]]; then
  step "Step 3/7 — Build images (a few minutes on a cold cache)"
  IFS='|' read -r -a PARTS <<< "${IMAGES[0]}"
  for entry in "${IMAGES[@]}"; do
    IFS='|' read -r -a parts <<< "${entry}"
    tag="${parts[0]}"; ctx="${parts[1]}"; dockerfile="${parts[2]:-}"
    if [[ -n "${dockerfile}" ]]; then
      step "Building image '${tag}'"
      run ${CONTAINER_CLI} build -f "${REPO_ROOT}/${dockerfile}" -t "${tag}" "${REPO_ROOT}/${ctx}"
    else
      step "Building image '${tag}'"
      run ${CONTAINER_CLI} build -t "${tag}" "${REPO_ROOT}/${ctx}"
    fi
  done
else
  step "Step 3/7 — Skipping image builds (SKIP_BUILD set)"
fi

# ---------------------------------------------------------------------------
# Step 4 — load images
# ---------------------------------------------------------------------------
if [[ -z "${SKIP_LOAD}" ]]; then
  step "Step 4/7 — Load images into kind"
  for entry in "${IMAGES[@]}"; do
    IFS='|' read -r -a parts <<< "${entry}"
    tag="${parts[0]}"
    step "Loading image '${tag}' into kind"
    run kind load docker-image "${tag}" --name "${CLUSTER_NAME}"
  done
else
  step "Step 4/7 — Skipping kind image load (SKIP_LOAD set)"
fi

# ---------------------------------------------------------------------------
# Step 5 — state migrations
# ---------------------------------------------------------------------------
step "Step 5/7 — Reconcile state from previous installs"

POSTGRES_POD="${RELEASE_NAME}-postgresql-0"
if kubectl get pod "${POSTGRES_POD}" -n "${NAMESPACE}" --context "${CLUSTER_CONTEXT}" --ignore-not-found -o name >/dev/null 2>&1; then
  if [[ -n "$(kubectl get pod "${POSTGRES_POD}" -n "${NAMESPACE}" --context "${CLUSTER_CONTEXT}" --ignore-not-found -o name 2>/dev/null | tr -d '[:space:]')" ]]; then
    step "Synchronizing PostgreSQL password for existing release '${RELEASE_NAME}'"
    run kubectl exec -n "${NAMESPACE}" --context "${CLUSTER_CONTEXT}" "${POSTGRES_POD}" -- \
      psql -U kubesynapse -d postgres -v ON_ERROR_STOP=1 \
      -c "ALTER ROLE CURRENT_USER WITH PASSWORD '${DATABASE_PASSWORD}';"
  fi
fi

for cm in "${RELEASE_NAME}-opencode-safe-config" "${RELEASE_NAME}-pi-safe-config"; do
  if [[ -n "$(kubectl get configmap "${cm}" -n "${NAMESPACE}" --context "${CLUSTER_CONTEXT}" --ignore-not-found -o name 2>/dev/null | tr -d '[:space:]')" ]]; then
    step "Deleting immutable runtime ConfigMap '${cm}' so Helm can recreate it"
    run kubectl delete configmap "${cm}" -n "${NAMESPACE}" --context "${CLUSTER_CONTEXT}"
  fi
done

if [[ -n "$(kubectl get deployment "${RELEASE_NAME}-operator" -n "${NAMESPACE}" --context "${CLUSTER_CONTEXT}" --ignore-not-found -o jsonpath='{.spec.template.spec.containers[0].env}' 2>/dev/null)" ]]; then
  if kubectl get deployment "${RELEASE_NAME}-operator" -n "${NAMESPACE}" --context "${CLUSTER_CONTEXT}" -o json 2>/dev/null | \
       python3 -c "import json,sys; d=json.load(sys.stdin); env=d['spec']['template']['spec']['containers'][0].get('env',[]); sys.exit(0 if any(e.get('name')=='OPERATOR_NAMESPACE' and 'value' in e and e['value'] for e in env) else 1)" 2>/dev/null; then
    step "Deleting legacy operator deployment with literal OPERATOR_NAMESPACE"
    run kubectl delete deployment "${RELEASE_NAME}-operator" -n "${NAMESPACE}" --context "${CLUSTER_CONTEXT}" --wait=true
  fi
fi

# ---------------------------------------------------------------------------
# Step 6 — helm install
# ---------------------------------------------------------------------------
step "Step 6/7 — Install (or upgrade) Helm release '${RELEASE_NAME}'"
step "Building chart dependencies"
HELM_CHART_PATH="${CHART_PATH}"
HELM_LOCAL_IMAGES_VALUES="${LOCAL_IMAGES_VALUES_PATH}"
HELM_KIND_QUICKSTART_VALUES="${KIND_QUICKSTART_VALUES_PATH}"
HELM_SKILLS_CATALOG="${SKILLS_CATALOG_PATH}"
if [[ -n "$WINDOWS_KUBECONFIG" ]]; then
  # Windows helm.exe can't read /mnt/c paths; convert to Windows style
  HELM_CHART_PATH="$(wslpath -w "${CHART_PATH}" 2>/dev/null || echo "${CHART_PATH}")"
  HELM_LOCAL_IMAGES_VALUES="$(wslpath -w "${LOCAL_IMAGES_VALUES_PATH}" 2>/dev/null || echo "${LOCAL_IMAGES_VALUES_PATH}")"
  HELM_KIND_QUICKSTART_VALUES="$(wslpath -w "${KIND_QUICKSTART_VALUES_PATH}" 2>/dev/null || echo "${KIND_QUICKSTART_VALUES_PATH}")"
  HELM_SKILLS_CATALOG="$(wslpath -w "${SKILLS_CATALOG_PATH}" 2>/dev/null || echo "${SKILLS_CATALOG_PATH}")"
fi
run helm dependency build "${HELM_CHART_PATH}"
HELM_ARGS=(
  upgrade --install "${RELEASE_NAME}" "${HELM_CHART_PATH}"
  --namespace "${NAMESPACE}"
  --create-namespace
  --kube-context "${CLUSTER_CONTEXT}"
  --wait
  --timeout "${HELM_TIMEOUT_MINUTES}m"
  --force-conflicts
  -f "${HELM_LOCAL_IMAGES_VALUES}"
  -f "${HELM_KIND_QUICKSTART_VALUES}"
  --set-string "platformSecrets.native.litellmMasterKey=${LITELLM_MASTER_KEY}"
  --set-string "platformSecrets.native.apiGatewaySharedToken=${SHARED_TOKEN}"
  --set-string "platformSecrets.native.databasePassword=${DATABASE_PASSWORD}"
  --set-string "platformSecrets.native.jwtSecret=${JWT_SECRET}"
  --set-string "platformSecrets.native.authBootstrapAdminPassword=${ADMIN_PASSWORD}"
  --set-string "apiGateway.auth.bootstrapAdminUsername=${ADMIN_USERNAME}"
)
if [[ -f "$SKILLS_CATALOG_PATH" ]]; then
  HELM_ARGS+=("--set-file" "skillsCatalog.catalogJson=${HELM_SKILLS_CATALOG}")
fi

run helm "${HELM_ARGS[@]}"

# ---------------------------------------------------------------------------
# Step 7 — restart + rollout
# ---------------------------------------------------------------------------
if [[ -z "${SKIP_RESTART}" ]]; then
  step "Step 7/7 — Restart core deployments to pick up new local images, then wait"
  for deployment in "${RELEASE_NAME}-operator" "${RELEASE_NAME}-api-gateway" "${RELEASE_NAME}-web-ui"; do
    step "Restarting deployment '${deployment}' to pick up local dev images"
    run kubectl rollout restart "deployment/${deployment}" -n "${NAMESPACE}" --context "${CLUSTER_CONTEXT}"

    step "Waiting for deployment '${deployment}' rollout"
    run kubectl rollout status "deployment/${deployment}" -n "${NAMESPACE}" --context "${CLUSTER_CONTEXT}" --timeout="${ROLLOUT_TIMEOUT_MINUTES}m"
  done
else
  step "Step 7/7 — Skipping rollout restart (SKIP_RESTART set)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\n%s%s%s\n" "${C_GREEN}" "$(printf '=%.0s' {1..78})" "${C_RST}"
printf "%s  KubeSynapse local install is ready.%s\n" "${C_GREEN}" "${C_RST}"
printf "%s%s%s\n\n" "${C_GREEN}" "$(printf '=%.0s' {1..78})" "${C_RST}"

printf "  %sCluster context:%s %s\n" "${C_GREY}" "${C_RST}" "${CLUSTER_CONTEXT}"
printf "  %sRelease name:%s    %s\n" "${C_GREY}" "${C_RST}" "${RELEASE_NAME}"
printf "  %sNamespace:%s       %s\n" "${C_GREY}" "${C_RST}" "${NAMESPACE}"
printf "  %sImage registry:%s  localhost/kubesynapse/*:dev (kind-loaded)\n" "${C_GREY}" "${C_RST}"
printf "  %sAdmin username:%s  %s\n" "${C_GREY}" "${C_RST}" "${ADMIN_USERNAME}"
printf "  %sAdmin password:%s  %s\n" "${C_YELLOW}" "${C_RST}" "${ADMIN_PASSWORD}"
echo
printf "  %sNext: port-forward the platform.%s\n" "${C_CYAN}" "${C_RST}"
printf "    kubectl port-forward svc/${RELEASE_NAME}-api-gateway -n ${NAMESPACE} 8080:8080\n"
printf "    kubectl port-forward svc/${RELEASE_NAME}-web-ui -n ${NAMESPACE} 3000:80\n"
echo
printf "  %sUI:%s   http://localhost:3000\n" "${C_GREY}" "${C_RST}"
printf "  %sAPI:%s  http://localhost:8080/api/v1/health\n" "${C_GREY}" "${C_RST}"
echo
printf "  %sImportant:%s configure an LLM API key before invoking agents.\n" "${C_CYAN}" "${C_RST}"
printf "    Option A: open the Web UI -> Settings -> Providers, add your key.\n"
cat <<PATCH_HELP

    Option B (bash):
      kubectl patch secret ${RELEASE_NAME}-llm-api-keys -n ${NAMESPACE} \\
        -p '{"data":{"OPENAI_API_KEY":"'"\$(printf 'sk-your-key' | base64)"'"}}'

    Option C (PowerShell):
      \$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('sk-your-key'))
      kubectl patch secret ${RELEASE_NAME}-llm-api-keys -n ${NAMESPACE} \\
        --patch "{`"data`":{`"OPENAI_API_KEY`":`"\$b64`"}}"
PATCH_HELP
echo
printf "  %sRe-running with the same CLUSTER_NAME will upgrade in place; use RECREATE_CLUSTER=1 to start over.%s\n" "${C_GREY}" "${C_RST}"
