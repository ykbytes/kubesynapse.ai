#!/usr/bin/env bash
# build-mcp-images.sh — build lightweight, secure MCP sidecar images.
#
# Usage:
#   ./scripts/build-mcp-images.sh                  # build all, tag localhost/...
#   REGISTRY=quay.io/yakdhane ./scripts/build-mcp-images.sh  # also push
#   SERVERS="code-exec git database" ./scripts/build-mcp-images.sh
#   PUSH=1 ./scripts/build-mcp-images.sh           # push after build
#   PLATFORMS="linux/amd64,linux/arm64" ./scripts/build-mcp-images.sh
#   STAGE_DIR=/tmp/ksbuild-mcp ./scripts/build-mcp-images.sh
#
# The script builds a shared mcp-base image first, then layers each
# server-specific image on top.  All images are tagged locally as
# localhost/kubesynapse/mcp-<server>:dev.  When REGISTRY is set, an
# additional remote tag is applied (and pushed if PUSH=1).
#
# On Windows/WSL builds from OneDrive can fail with xattr/permission errors.
# The default STAGE_DIR is under /tmp (WSL ext4) to avoid those issues.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
MCP_DIR="${REPO_ROOT}/mcp-sidecars"

REGISTRY="${REGISTRY:-}"
PUSH="${PUSH:-}"
PLATFORMS="${PLATFORMS:-}"
SERVERS="${SERVERS:-code-exec collector git web-search documents browser kubernetes messaging rag database github-adapter}"
BASE_TAG="${BASE_TAG:-localhost/kubesynapse/mcp-base:dev}"
REMOTE_BASE_TAG="${REGISTRY:+${REGISTRY}/kubesynapse:mcp-base-dev}"
DEBIAN_BASE_TAG="${DEBIAN_BASE_TAG:-localhost/kubesynapse/mcp-base-debian:dev}"
REMOTE_DEBIAN_BASE_TAG="${REGISTRY:+${REGISTRY}/kubesynapse:mcp-base-debian-dev}"
STAGE_DIR="${STAGE_DIR:-/tmp/ksbuild-mcp-$$}"
CLEAN_STAGE="${CLEAN_STAGE:-1}"

if [[ -n "${PLATFORMS}" ]]; then
  BUILDER="docker buildx build --platform ${PLATFORMS}"
  OUTPUT_FLAG="--push"
else
  BUILDER="docker build"
  OUTPUT_FLAG=""
fi

step() { printf "==> %s\n" "$*"; }
ok()   { printf "[ok] %s\n" "$*"; }
fail() { printf "[fail] %s\n" "$*" >&2; exit 1; }

cleanup() {
  if [[ "${CLEAN_STAGE}" == "1" && -d "${STAGE_DIR}" ]]; then
    rm -rf "${STAGE_DIR}"
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Stage files on a WSL-native filesystem to avoid OneDrive xattr issues.
# ---------------------------------------------------------------------------
step "Staging mcp-sidecars into ${STAGE_DIR}"
rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}"
cp -r "${MCP_DIR}"/* "${STAGE_DIR}/"
# Write a minimal .dockerignore so hidden cache dirs are skipped even if the
# staging driver reads xattrs.
cat > "${STAGE_DIR}/.dockerignore" <<'EOF'
**/.git
**/.pytest_cache
**/__pycache__
**/*.pyc
**/*.pyo
**/.mypy_cache
**/.ruff_cache
EOF
ok "mcp-sidecars staged"

# ---------------------------------------------------------------------------
# Stage 1 — shared base image
# ---------------------------------------------------------------------------
step "Building mcp-base image (${BASE_TAG})"
${BUILDER} \
  -f "${STAGE_DIR}/base/Dockerfile" \
  -t "${BASE_TAG}" \
  ${OUTPUT_FLAG} \
  "${STAGE_DIR}"
ok "mcp-base built"

if [[ -n "${REMOTE_BASE_TAG}" ]]; then
  docker tag "${BASE_TAG}" "${REMOTE_BASE_TAG}"
  if [[ -n "${PUSH}" ]]; then
    docker push "${REMOTE_BASE_TAG}"
    ok "mcp-base pushed to ${REMOTE_BASE_TAG}"
  fi
fi

# ---------------------------------------------------------------------------
# Stage 1b — Debian-based shared base for sidecars that need glibc
# ---------------------------------------------------------------------------
step "Building mcp-base-debian image (${DEBIAN_BASE_TAG})"
${BUILDER} \
  -f "${STAGE_DIR}/base/Dockerfile.debian" \
  -t "${DEBIAN_BASE_TAG}" \
  ${OUTPUT_FLAG} \
  "${STAGE_DIR}"
ok "mcp-base-debian built"

if [[ -n "${REMOTE_DEBIAN_BASE_TAG}" ]]; then
  docker tag "${DEBIAN_BASE_TAG}" "${REMOTE_DEBIAN_BASE_TAG}"
  if [[ -n "${PUSH}" ]]; then
    docker push "${REMOTE_DEBIAN_BASE_TAG}"
    ok "mcp-base-debian pushed to ${REMOTE_DEBIAN_BASE_TAG}"
  fi
fi

# ---------------------------------------------------------------------------
# Stage 2 — per-server images
# ---------------------------------------------------------------------------
for server in ${SERVERS}; do
  server_dir="${STAGE_DIR}/${server}"
  [[ -d "${server_dir}" ]] || fail "Server directory not found: ${server_dir}"
  [[ -f "${server_dir}/Dockerfile" ]] || fail "Dockerfile missing for server: ${server}"

  local_tag="localhost/kubesynapse/mcp-${server}:dev"
  remote_tag="${REGISTRY:+${REGISTRY}/kubesynapse:mcp-${server}-dev}"

  # Browser and RAG need the Debian-based base because Playwright and
  # onnxruntime do not provide musllinux wheels.
  if [[ "${server}" == "browser" || "${server}" == "rag" ]]; then
    base_arg="${DEBIAN_BASE_TAG}"
  else
    base_arg="${BASE_TAG}"
  fi

  step "Building mcp-${server} image (${local_tag})"
  ${BUILDER} \
    -f "${server_dir}/Dockerfile" \
    --build-arg MCP_BASE_TAG="${base_arg}" \
    -t "${local_tag}" \
    ${OUTPUT_FLAG} \
    "${STAGE_DIR}"
  ok "mcp-${server} built"

  if [[ -n "${remote_tag}" ]]; then
    docker tag "${local_tag}" "${remote_tag}"
    if [[ -n "${PUSH}" ]]; then
      docker push "${remote_tag}"
      ok "mcp-${server} pushed to ${remote_tag}"
    fi
  fi
done

step "All MCP images built successfully"
echo
printf "Local tags:\n"
for server in ${SERVERS}; do
  printf "  localhost/kubesynapse/mcp-%s:dev\n" "${server}"
done
if [[ -n "${REGISTRY}" ]]; then
  printf "\nRemote tags (quay.io/yakdhane/kubesynapse):\n"
  for server in ${SERVERS}; do
    printf "  :mcp-%s-dev\n" "${server}"
  done
fi
