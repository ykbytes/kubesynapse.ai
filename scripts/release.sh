#!/usr/bin/env bash
set -euo pipefail

# kubesynapse Release Script
# Usage: ./scripts/release.sh <version>
# Example: ./scripts/release.sh v1.0.0

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    echo "Usage: $0 <version>"
    echo "Example: $0 v1.0.0"
    exit 1
fi

# Validate semver
if ! echo "$VERSION" | grep -qE '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "ERROR: Version must be semver with v prefix (e.g., v1.0.0)"
    exit 1
fi

REGISTRY="${REGISTRY:-docker.io/yakdhane}"
CHART_REGISTRY="${CHART_REGISTRY:-oci://ghcr.io/yakdhane/charts}"

echo "=== kubesynapse Release $VERSION ==="

# ---------------------------------------------------------------------------
# 1. Update version references
# ---------------------------------------------------------------------------
echo "[1/8] Updating version references..."
sed -i.bak "s/version = \"[0-9.]*\"/version = \"${VERSION#v}\"/" pyproject.toml
rm -f pyproject.toml.bak

# ---------------------------------------------------------------------------
# 2. Generate changelog
# ---------------------------------------------------------------------------
echo "[2/8] Generating changelog..."
if command -v git-cliff &> /dev/null; then
    git-cliff --tag "$VERSION" > CHANGELOG.md
else
    echo "WARNING: git-cliff not installed. Skipping changelog generation."
    echo "Install: cargo install git-cliff"
fi

# ---------------------------------------------------------------------------
# 3. Git tag
# ---------------------------------------------------------------------------
echo "[3/8] Creating git tag..."
git add -A
git commit -m "release: $VERSION" || true
git tag -a "$VERSION" -m "Release $VERSION"

# ---------------------------------------------------------------------------
# 4. Build container images
# ---------------------------------------------------------------------------
echo "[4/8] Building container images..."
make docker-build VERSION="$VERSION"

# ---------------------------------------------------------------------------
# 5. Push container images
# ---------------------------------------------------------------------------
echo "[5/8] Pushing container images..."
make docker-push VERSION="$VERSION"

# ---------------------------------------------------------------------------
# 6. Sign images with cosign
# ---------------------------------------------------------------------------
echo "[6/8] Signing images with cosign..."
if command -v cosign &> /dev/null; then
    for image in \
        "kubesynapse-operator" \
        "kubesynapse-api-gateway" \
        "kubesynapse-web-ui" \
        "kubesynapse-opencode-rt"; do
        cosign sign --yes "$REGISTRY/$image:$VERSION"
    done
else
    echo "WARNING: cosign not installed. Skipping image signing."
fi

# ---------------------------------------------------------------------------
# 7. Generate SBOMs
# ---------------------------------------------------------------------------
echo "[7/8] Generating SBOMs..."
if command -v syft &> /dev/null; then
    for image in \
        "kubesynapse-operator" \
        "kubesynapse-api-gateway" \
        "kubesynapse-web-ui" \
        "kubesynapse-opencode-rt"; do
        syft "$REGISTRY/$image:$VERSION" -o spdx-json > "dist/sbom-$image-$VERSION.json"
    done
else
    echo "WARNING: syft not installed. Skipping SBOM generation."
fi

# ---------------------------------------------------------------------------
# 8. Package and publish Helm chart
# ---------------------------------------------------------------------------
echo "[8/8] Packaging Helm chart..."
helm package ./charts/kubesynapse --version "${VERSION#v}" --app-version "$VERSION" -d ./dist/

if command -v helm &> /dev/null; then
    helm push "./dist/kubesynapse-${VERSION#v}.tgz" "$CHART_REGISTRY"
else
    echo "WARNING: helm not available for OCI push."
fi

# ---------------------------------------------------------------------------
# 9. GitHub release
# ---------------------------------------------------------------------------
echo "Creating GitHub release..."
if command -v gh &> /dev/null; then
    gh release create "$VERSION" \
        --title "kubesynapse $VERSION" \
        --notes-file CHANGELOG.md \
        ./dist/*
else
    echo "WARNING: gh CLI not installed. Skipping GitHub release."
    echo "Create release manually at: https://github.com/ykbytes/kubemininions/releases/new"
fi

echo "=== Release $VERSION complete ==="
echo "Artifacts in ./dist/"
