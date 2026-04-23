#!/bin/bash
# Built-in: List Helm releases across all namespaces
set -e
echo "=== Helm Releases ==="
helm list --all-namespaces --output table 2>/dev/null || echo "helm not available or no releases"
echo ""
echo "=== Failed/Pending Helm Releases ==="
helm list --all-namespaces --failed --pending --output table 2>/dev/null || echo "none"
echo ""
echo "=== Recently Updated Releases ==="
helm list --all-namespaces --date --max 10 --output table 2>/dev/null || echo "helm not available"
