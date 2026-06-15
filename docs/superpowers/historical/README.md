# Historical Documents

This folder preserves older design and installation documents that have been
superseded by the current docs tree. They are kept for archaeology and
historical context, not as install or operations references.

## Files

| File | What it covered | Why it was archived |
| --- | --- | --- |
| `DEPLOYMENT.md` | Phase-1 "Operator Reliability Deployment Guide" — ConfigMap hash drift, status condition projection, runtime health monitoring. | All of those behaviors are now documented under `docs/operator-guide.md` (Run Intelligence Layer, status conditions, runtime monitoring) and implemented by the current operator. The guide also pointed at a stale Windows path and a `kubesynapse-operator:latest` image tag. |
| `INSTALL.md` | A 60 KB installation walkthrough. | Largely duplicated by `docs/getting-started.md` + `docs/architecture-overview.md` + `deploy/README.md` + the `scripts/deploy-kind.ps1` and `scripts/install.sh` helpers. The current install path for a fresh cluster is `scripts/install.sh` (macOS/Linux) or `scripts/deploy-kind.ps1` (Windows). The verified entry point on any cluster is `deploy/README.md`. |

## Current Canonical Paths

| Concern | Read this |
| --- | --- |
| Local install (Kind) | [`../../scripts/install.sh`](../../scripts/install.sh) or [`../../scripts/deploy-kind.ps1`](../../scripts/deploy-kind.ps1), with [`../../deploy/README.md`](../../deploy/README.md) |
| First-time walkthrough | [`../../docs/getting-started.md`](../../docs/getting-started.md) |
| Architecture | [`../../docs/architecture-overview.md`](../../docs/architecture-overview.md) and [`../../docs/architecture.md`](../../docs/architecture.md) |
| Operations runbook | [`../../docs/operator-guide.md`](../../docs/operator-guide.md) and [`../../docs/troubleshooting.md`](../../docs/troubleshooting.md) |
| Configuration | [`../../docs/configuration-reference.md`](../../docs/configuration-reference.md) and [`../../charts/kubesynapse/README.md`](../../charts/kubesynapse/README.md) |
| Install verification | [`../../scripts/verify-install.mjs`](../../scripts/verify-install.mjs) |

> Do not link to anything in this folder from new docs. The current docs tree
> is the only source of truth.
