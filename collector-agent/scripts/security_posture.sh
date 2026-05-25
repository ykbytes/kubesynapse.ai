#!/bin/bash
# Built-in: Security posture assessment (read-only)
set -e
echo "=== RBAC - ClusterRoles ==="
kubectl get clusterroles --no-headers 2>/dev/null | wc -l
echo "cluster roles total"
echo ""
echo "=== RBAC - ClusterRoleBindings ==="
kubectl get clusterrolebindings --no-headers 2>/dev/null | head -30
echo ""
echo "=== Service Accounts (non-default) ==="
kubectl get sa -A --no-headers 2>/dev/null | grep -v "^kube-system" | grep -v "default " | head -30
echo ""
echo "=== Secrets Summary ==="
kubectl get secrets -A --no-headers 2>/dev/null | awk '{ns=$1; type=$3; count[ns":"type]++} END {for (k in count) printf "%-40s %d\n", k, count[k]}'
echo ""
echo "=== Pods Running as Root ==="
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}: runAsNonRoot={.spec.securityContext.runAsNonRoot}, runAsUser={.spec.containers[0].securityContext.runAsUser}{"\n"}{end}' 2>/dev/null | head -30
echo ""
echo "=== Pod Security Standards ==="
kubectl get namespaces -o jsonpath='{range .items[*]}{.metadata.name}: {.metadata.labels.pod-security\.kubernetes\.io/enforce}{"\n"}{end}' 2>/dev/null
