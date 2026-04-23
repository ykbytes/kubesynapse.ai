#!/bin/bash
# Built-in: CRD and custom resource inventory
set -e
echo "=== Custom Resource Definitions ==="
kubectl get crds --no-headers 2>/dev/null | awk '{print $1, $2}' || echo "none"
echo ""
echo "=== CRD Counts ==="
for crd in $(kubectl get crds -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
  group=$(kubectl get crd "$crd" -o jsonpath='{.spec.group}' 2>/dev/null)
  kind=$(kubectl get crd "$crd" -o jsonpath='{.spec.names.kind}' 2>/dev/null)
  count=$(kubectl get "$kind" --all-namespaces --no-headers 2>/dev/null | wc -l)
  if [ "$count" -gt 0 ]; then
    echo "$group/$kind: $count instances"
  fi
done 2>/dev/null
echo ""
echo "=== API Server Resources ==="
kubectl api-resources --verbs=list --no-headers 2>/dev/null | awk '{print $NF, $1}' | sort | head -40
