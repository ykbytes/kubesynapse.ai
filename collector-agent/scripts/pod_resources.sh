#!/bin/bash
# Built-in: Gather pod resource usage and status across all namespaces
set -e
echo "=== Pod Resources ==="
kubectl top pods -A --no-headers 2>/dev/null || echo "metrics-server not available"
echo ""
echo "=== Pod Status Summary ==="
kubectl get pods -A -o wide --no-headers 2>/dev/null | awk '{
    ns=$1; status=$4; node=$8
    count[ns":"status]++
    total[ns]++
    nodes[ns]=node
}
END {
    printf "%-30s %-15s %-8s\n", "NAMESPACE", "STATUS", "COUNT"
    for (key in count) {
        split(key, parts, ":")
        printf "%-30s %-15s %-8d\n", parts[1], parts[2], count[key]
    }
}'
echo ""
echo "=== Pods Not Running ==="
kubectl get pods -A --field-selector=status.phase!=Running --no-headers 2>/dev/null || echo "all pods running"
