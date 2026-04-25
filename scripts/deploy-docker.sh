#!/usr/bin/env bash
# KubeSynth Docker deployment script
# 
# Usage:
#   ./scripts/deploy-docker.sh [up|down|build|logs|status]
#
# Environment variables:
#   COMPOSE_FILE    - Docker Compose file path (default: docker-compose.yml)
#   REGISTRY        - Docker registry prefix (default: docker.io/yakdhane)
#   VERSION         - Image tag (default: latest)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_ROOT/docker-compose.yml}"
REGISTRY="${REGISTRY:-docker.io/yakdhane}"
VERSION="${VERSION:-latest}"

cd "$PROJECT_ROOT"

case "${1:-up}" in
  up)
    echo "🚀 Starting KubeSynth stack..."
    docker compose -f "$COMPOSE_FILE" up -d
    echo ""
    echo "Services:"
    echo "  API Gateway:  http://localhost:8080"
    echo "  Web UI:       http://localhost:3000"
    echo "  LiteLLM:      http://localhost:4000"
    echo "  OpenCode RT:  http://localhost:8081"
    echo "  Postgres:     localhost:5432"
    echo "  Redis:        localhost:6379"
    echo "  NATS:         localhost:4222"
    echo "  Qdrant:       localhost:6333"
    ;;

  down)
    echo "🛑 Stopping KubeSynth stack..."
    docker compose -f "$COMPOSE_FILE" down
    ;;

  down-volumes)
    echo "🛑 Stopping KubeSynth stack and removing volumes..."
    docker compose -f "$COMPOSE_FILE" down -v
    ;;

  build)
    echo "🔨 Building all images..."
    docker compose -f "$COMPOSE_FILE" build --no-cache
    ;;

  pull)
    echo "⬇️ Pulling latest images..."
    docker compose -f "$COMPOSE_FILE" pull
    ;;

  logs)
    service="${2:-}"
    if [ -n "$service" ]; then
      docker compose -f "$COMPOSE_FILE" logs -f "$service"
    else
      docker compose -f "$COMPOSE_FILE" logs -f
    fi
    ;;

  status)
    docker compose -f "$COMPOSE_FILE" ps
    ;;

  health)
    echo "Checking service health..."
    docker compose -f "$COMPOSE_FILE" ps --format "table {{.Name}}\t{{.Status}}\t{{.Health}}"
    ;;

  push)
    echo "📤 Pushing images to $REGISTRY..."
    for image in kubesynth-api-gateway kubesynth-operator kubesynth-web-ui kubesynth-opencode-runtime; do
      docker tag "$image:$VERSION" "$REGISTRY/$image:$VERSION"
      docker push "$REGISTRY/$image:$VERSION"
    done
    ;;

  *)
    echo "Usage: $0 [up|down|down-volumes|build|pull|logs|status|health|push]"
    exit 1
    ;;
esac
