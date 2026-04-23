#!/bin/bash
# Built-in: Cluster overview and configuration
set -e
echo "=== Cluster Version ==="
kubectl version --short 2>/dev/null || kubectl version 2>/dev/null
echo ""
echo "=== Cluster Info ==="
kubectl cluster-info 2>/dev/null | head -5
echo ""
echo "=== Namespaces ==="
kubectl get namespaces --no-headers 2>/dev/null
echo ""
echo "=== API Resources ==="
kubectl api-resources --verbs=list --no-headers 2>/dev/null | awk '{print $NF}' | sort -u
echo ""
echo "=== Resource Counts ==="
for kind in pods deployments services configmaps secrets statefulsets daemonsets jobs cronjobs; do
    count=$(kubectl get $kind -A --no-headers 2>/dev/null | wc -l)
    printf "%-20s %d\n" "$kind" "$count"
done
echo ""
echo "=== Events (Warning) ==="
kubectl get events -A --field-selector=type=Warning --sort-by='.lastTimestamp' 2>/dev/null | tail -20
