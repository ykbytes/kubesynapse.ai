#!/usr/bin/env bash
# Verify Docker images build correctly
# Usage: ./scripts/verify-docker-builds.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "========================================"
echo "kubesynapse Docker Build Verification"
echo "========================================"
echo ""

FAILED=0

build_image() {
  local name=$1
  local path=$2
  local dockerfile=${3:-Dockerfile}
  
  echo "🔨 Building $name from $path/$dockerfile ..."
  if docker build -f "$path/$dockerfile" -t "kubesynapse/$name:test" "$path" > "/tmp/build-$name.log" 2>&1; then
    echo "  ✅ $name built successfully"
    return 0
  else
    echo "  ❌ $name build FAILED"
    echo "  Logs: /tmp/build-$name.log"
    FAILED=1
    return 1
  fi
}

# Core images
build_image "api-gateway" "./api-gateway"
build_image "operator" "./operator"
build_image "web-ui" "./web-ui"
build_image "opencode-runtime" "./opencode-runtime"
build_image "collector-agent" "./collector-agent"

# MCP sidecars
for sidecar in code-exec web-search documents browser database git github-adapter kubernetes messaging rag; do
  if [ -f "./mcp-sidecars/$sidecar/Dockerfile" ]; then
    build_image "mcp-$sidecar" "./mcp-sidecars/$sidecar"
  fi
done

echo ""
if [ $FAILED -eq 0 ]; then
  echo "========================================"
  echo "✅ All images built successfully!"
  echo "========================================"
  exit 0
else
  echo "========================================"
  echo "❌ Some builds failed. Check logs above."
  echo "========================================"
  exit 1
fi
