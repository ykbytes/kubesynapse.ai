#!/bin/bash
# Built-in: Inventory ConfigMaps & Secrets (names only, no data)
set -e
echo "=== ConfigMaps By Namespace ==="
kubectl get configmaps --all-namespaces --no-headers 2>/dev/null | awk '{ns[$1]++} END {for (n in ns) print n, ns[n], "configmaps"}' | sort
echo ""
echo "=== Secrets By Namespace ==="
kubectl get secrets --all-namespaces --no-headers 2>/dev/null | awk '{ns[$1]++} END {for (n in ns) print n, ns[n], "secrets"}' | sort
echo ""
echo "=== Large ConfigMaps (>100KB) ==="
kubectl get configmaps --all-namespaces -o json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
for cm in data.get('items', []):
    total = sum(len(v) for v in (cm.get('data') or {}).values())
    if total > 102400:
        print(f\"{cm['metadata']['namespace']}/{cm['metadata']['name']}: {total//1024}KB\")
" 2>/dev/null || echo "check skipped"
echo ""
echo "=== Expiring TLS Secrets (30 days) ==="
kubectl get secrets --all-namespaces --field-selector type=kubernetes.io/tls -o json 2>/dev/null | python3 -c "
import json, sys, base64
from datetime import datetime, timedelta, timezone
data = json.load(sys.stdin)
threshold = datetime.now(timezone.utc) + timedelta(days=30)
for s in data.get('items', []):
    try:
        import subprocess
        cert = base64.b64decode(s['data']['tls.crt'])
        result = subprocess.run(['openssl', 'x509', '-noout', '-enddate'], input=cert, capture_output=True)
        datestr = result.stdout.decode().strip().split('=')[1]
        expiry = datetime.strptime(datestr, '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
        if expiry < threshold:
            print(f\"{s['metadata']['namespace']}/{s['metadata']['name']}: expires {expiry.date()}\")
    except Exception:
        pass
" 2>/dev/null || echo "check skipped"
