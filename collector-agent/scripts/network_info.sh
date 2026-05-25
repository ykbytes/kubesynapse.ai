#!/bin/bash
# Built-in: Gather networking configuration
set -e
echo "=== Services ==="
kubectl get svc -A --no-headers 2>/dev/null | head -50
echo ""
echo "=== Ingresses ==="
kubectl get ingress -A --no-headers 2>/dev/null || echo "no ingresses found"
echo ""
echo "=== Network Policies ==="
kubectl get networkpolicies -A --no-headers 2>/dev/null || echo "no network policies found"
echo ""
echo "=== Endpoints (non-default) ==="
kubectl get endpoints -A --no-headers 2>/dev/null | grep -v "^kube-system" | head -30
echo ""
echo "=== DNS Config ==="
cat /etc/resolv.conf 2>/dev/null || echo "no resolv.conf"
