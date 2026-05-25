#!/bin/bash
# Built-in: Gather storage configuration and PVC status
set -e
echo "=== Storage Classes ==="
kubectl get storageclass --no-headers 2>/dev/null || echo "no storage classes"
echo ""
echo "=== Persistent Volumes ==="
kubectl get pv --no-headers 2>/dev/null || echo "no PVs"
echo ""
echo "=== Persistent Volume Claims ==="
kubectl get pvc -A --no-headers 2>/dev/null || echo "no PVCs"
echo ""
echo "=== PVCs Not Bound ==="
kubectl get pvc -A --field-selector=status.phase!=Bound --no-headers 2>/dev/null || echo "all PVCs bound"
echo ""
echo "=== Disk Usage ==="
df -h 2>/dev/null | head -20
