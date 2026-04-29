#!/usr/bin/env bash
# validate-crd-yaml.sh — Validates all CRD example YAML files and rendered templates
# §S6-2: camelCase Standardization
#
# Usage:
#   bash scripts/validate-crd-yaml.sh [--strict]
#
# Options:
#   --strict  Also validate that no snake_case keys exist in CRD examples

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STRICT_MODE=false

for arg in "$@"; do
    case "$arg" in
        --strict) STRICT_MODE=true ;;
    esac
done

PASSED=0
FAILED=0
WARNINGS=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "============================================"
echo "kubesynapse CRD YAML Validator"
echo "============================================"
echo ""

# ---------------------------------------------------------------------------
# 1. Validate individual CRD YAML files via kubectl --dry-run
# ---------------------------------------------------------------------------
validate_yaml_file() {
    local file="$1"
    if kubectl --dry-run=client apply -f "$file" >/dev/null 2>&1; then
        echo -e "  ${GREEN}PASS${NC}  $file"
        PASSED=$((PASSED + 1))
    else
        echo -e "  ${RED}FAIL${NC}  $file"
        kubectl --dry-run=client apply -f "$file" 2>&1 | head -5
        FAILED=$((FAILED + 1))
    fi
}

echo "--- Validating CRD example YAML files ---"
for file in "$REPO_ROOT"/examples/*.yaml "$REPO_ROOT"/examples/*.yml; do
    [ -f "$file" ] || continue
    validate_yaml_file "$file"
done
echo ""

# ---------------------------------------------------------------------------
# 2. Validate rendered Helm chart templates
# ---------------------------------------------------------------------------
echo "--- Validating Helm chart templates ---"
VALUES_FILE="$REPO_ROOT/deploy/values.kind.yaml"
if [ ! -f "$VALUES_FILE" ]; then
    echo -e "  ${YELLOW}WARN${NC}  No values.kind.yaml found at $VALUES_FILE — skipping Helmtemplate validation."
    WARNINGS=$((WARNINGS + 1))
else
    if helm template kubesynapse "$REPO_ROOT/charts/kubesynapse" -f "$VALUES_FILE" > /tmp/kubesynapse-rendered.yaml 2>/tmp/kubesynapse-helm-err.txt; then
        RENDERED_LINES=$(wc -l < /tmp/kubesynapse-rendered.yaml)
        echo -e "  ${GREEN}PASS${NC}  helm template rendered ${RENDERED_LINES} lines"
        PASSED=$((PASSED + 1))

        # Validate rendered YAML via kubectl dry-run
        if kubectl --dry-run=client apply -f /tmp/kubesynapse-rendered.yaml >/dev/null 2>&1; then
            echo -e "  ${GREEN}PASS${NC}  kubectl dry-run validates rendered templates"
            PASSED=$((PASSED + 1))
        else
            echo -e "  ${RED}FAIL${NC}  kubectl dry-run failed on rendered templates"
            kubectl --dry-run=client apply -f /tmp/kubesynapse-rendered.yaml 2>&1 | head -10
            FAILED=$((FAILED + 1))
        fi
    else
        echo -e "  ${RED}FAIL${NC}  helm template failed:"
        cat /tmp/kubesynapse-helm-err.txt
        FAILED=$((FAILED + 1))
    fi
fi
echo ""

# ---------------------------------------------------------------------------
# 3. Strict mode: check for snake_case in CRD spec fields
# ---------------------------------------------------------------------------
if [ "$STRICT_MODE" = true ]; then
    echo "--- Strict mode: checking for snake_case in CRD YAML files ---"
    SNAKE_PATTERNS=(
        "system_prompt"
        "runtime_kind"
        "storage_size"
        "enable_gvisor"
        "repo_url"
        "default_branch"
        "push_policy"
        "auth_method"
        "credential_secret_ref"
        "mcp_connections"
        "mcp_servers"
        "mcp_sidecars"
        "allowed_namespaces"
        "allowed_callers"
        "config_map_ref"
        "resource_quota"
    )

    SNAKE_FOUND=false
    for pattern in "${SNAKE_PATTERNS[@]}"; do
        for file in "$REPO_ROOT"/examples/*.yaml "$REPO_ROOT"/examples/*.yml "$REPO_ROOT"/deploy/*.yaml "$REPO_ROOT"/deploy/*.yml; do
            [ -f "$file" ] || continue
            if grep -q "$pattern" "$file" 2>/dev/null; then
                if [ "$SNAKE_FOUND" = false ]; then
                    echo ""
                    SNAKE_FOUND=true
                fi
                echo -e "  ${YELLOW}WARN${NC}  Found '$pattern' in $file"
                WARNINGS=$((WARNINGS + 1))
            fi
        done
    done

    if [ "$SNAKE_FOUND" = false ]; then
        echo -e "  ${GREEN}PASS${NC}  No snake_case keys found in CRD examples"
        PASSED=$((PASSED + 1))
    fi
    echo ""
fi

# ---------------------------------------------------------------------------
# 4. Check Helm lint
# ---------------------------------------------------------------------------
echo "--- Helm lint ---"
if helm lint "$REPO_ROOT/charts/kubesynapse" --strict 2>&1 | tee /tmp/kubesynapse-lint.txt | grep -q "ERROR"; then
    echo -e "  ${RED}FAIL${NC}  helm lint --strict found errors"
    cat /tmp/kubesynapse-lint.txt
    FAILED=$((FAILED + 1))
else
    echo -e "  ${GREEN}PASS${NC}  helm lint --strict passed"
    PASSED=$((PASSED + 1))
fi
echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "============================================"
echo "Validation Summary"
echo "============================================"
echo -e "  Passed:  ${GREEN}${PASSED}${NC}"
echo -e "  Failed:  ${RED}${FAILED}${NC}"
echo -e "  Warnings: ${YELLOW}${WARNINGS}${NC}"
echo ""

if [ "$FAILED" -gt 0 ]; then
    echo -e "${RED}Validation failed with ${FAILED} error(s).${NC}"
    exit 1
else
    echo -e "${GREEN}All validations passed!${NC}"
    exit 0
fi
