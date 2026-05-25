#!/bin/bash
# Built-in: Gather node health information
set -e
echo "=== Node Status ==="
kubectl get nodes -o wide --no-headers 2>/dev/null
echo ""
echo "=== Node Resources ==="
kubectl top nodes --no-headers 2>/dev/null || echo "metrics-server not available"
echo ""
echo "=== Node Conditions ==="
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.conditions[*]}{.type}={.status}{" "}{end}{"\n"}{end}' 2>/dev/null
echo ""
echo "=== Disk & Memory Pressure ==="
kubectl describe nodes 2>/dev/null | grep -A5 "Conditions:" | grep -E "(MemoryPressure|DiskPressure|PIDPressure)" || echo "no pressure conditions"
