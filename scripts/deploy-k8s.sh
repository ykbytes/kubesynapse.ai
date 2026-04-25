#!/usr/bin/env bash
# KubeSynth Kubernetes deployment script
#
# Usage:
#   ./scripts/deploy-k8s.sh [install|upgrade|uninstall|status|logs]
#
# Environment variables:
#   NAMESPACE       - Kubernetes namespace (default: kubesynth)
#   RELEASE_NAME    - Helm release name (default: kubesynth)
#   VALUES_FILE     - Helm values file (default: deploy/values.production.yaml)
#   REGISTRY        - Container registry (default: docker.io/yakdhane)
#   VERSION         - Image tag (default: latest)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
NAMESPACE="${NAMESPACE:-kubesynth}"
RELEASE_NAME="${RELEASE_NAME:-kubesynth}"
VALUES_FILE="${VALUES_FILE:-$PROJECT_ROOT/deploy/values.production.yaml}"
REGISTRY="${REGISTRY:-docker.io/yakdhane}"
VERSION="${VERSION:-latest}"

cd "$PROJECT_ROOT"

ensure_namespace() {
  if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
    echo "Creating namespace: $NAMESPACE"
    kubectl create namespace "$NAMESPACE"
  fi
}

case "${1:-install}" in
  install)
    ensure_namespace
    echo "📦 Installing KubeSynth via Helm..."
    helm upgrade --install "$RELEASE_NAME" ./charts/kubesynth \
      --namespace "$NAMESPACE" \
      --values "$VALUES_FILE" \
      --set image.tag="$VERSION" \
      --set image.registry="$REGISTRY" \
      --wait \
      --timeout 10m
    echo ""
    echo "✅ Installation complete!"
    echo ""
    echo "Get started:"
    echo "  kubectl get pods -n $NAMESPACE"
    echo "  kubectl port-forward svc/$RELEASE_NAME-api-gateway 8080:8080 -n $NAMESPACE"
    ;;

  upgrade)
    ensure_namespace
    echo "⬆️ Upgrading KubeSynth..."
    helm upgrade "$RELEASE_NAME" ./charts/kubesynth \
      --namespace "$NAMESPACE" \
      --values "$VALUES_FILE" \
      --set image.tag="$VERSION" \
      --set image.registry="$REGISTRY" \
      --wait \
      --timeout 10m
    echo ""
    echo "✅ Upgrade complete!"
    ;;

  uninstall)
    echo "🗑️ Uninstalling KubeSynth..."
    helm uninstall "$RELEASE_NAME" --namespace "$NAMESPACE" || true
    echo ""
    echo "To delete namespace and all data:"
    echo "  kubectl delete namespace $NAMESPACE"
    ;;

  status)
    echo "📊 KubeSynth status in namespace: $NAMESPACE"
    echo ""
    echo "Pods:"
    kubectl get pods -n "$NAMESPACE"
    echo ""
    echo "Services:"
    kubectl get svc -n "$NAMESPACE"
    echo ""
    echo "Ingresses:"
    kubectl get ingress -n "$NAMESPACE" 2>/dev/null || echo "  (no ingresses)"
    ;;

  logs)
    service="${2:-api-gateway}"
    pod=$(kubectl get pods -n "$NAMESPACE" -l "app=$service" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [ -z "$pod" ]; then
      echo "No pods found for service: $service"
      exit 1
    fi
    echo "Tailing logs for $pod..."
    kubectl logs -n "$NAMESPACE" -f "$pod"
    ;;

  port-forward)
    echo "🔌 Port forwarding services..."
    echo "  API Gateway -> http://localhost:8080"
    echo "  Web UI      -> http://localhost:3000"
    kubectl port-forward svc/$RELEASE_NAME-api-gateway 8080:8080 -n "$NAMESPACE" &
    kubectl port-forward svc/$RELEASE_NAME-web-ui 3000:8080 -n "$NAMESPACE" &
    wait
    ;;

  *)
    echo "Usage: $0 [install|upgrade|uninstall|status|logs|port-forward]"
    exit 1
    ;;
esac
