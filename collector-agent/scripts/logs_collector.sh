#!/bin/bash
# Built-in: Collect recent warning/error logs from all pods
set -e
echo "=== Pods with Restart Count > 0 ==="
kubectl get pods --all-namespaces --no-headers 2>/dev/null | awk '$5 > 0 {print $1, $2, "restarts="$5}'
echo ""
echo "=== Recent Warning Events ==="
kubectl get events --all-namespaces --field-selector type=Warning --sort-by='.lastTimestamp' 2>/dev/null | tail -30
echo ""
echo "=== CrashLoopBackOff Pods ==="
kubectl get pods --all-namespaces --no-headers 2>/dev/null | grep -i "crashloop\|error\|imagepull" || echo "none"
echo ""
echo "=== OOMKilled Containers (last 50 events) ==="
kubectl get events --all-namespaces --no-headers 2>/dev/null | grep -i "oomkill\|oom" | tail -10 || echo "none"
echo ""
echo "=== Failed Pods ==="
kubectl get pods --all-namespaces --field-selector status.phase=Failed --no-headers 2>/dev/null || echo "none"
