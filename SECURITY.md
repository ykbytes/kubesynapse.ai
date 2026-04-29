# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in KubeSynapse, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please send an email to the maintainers or use GitHub's private vulnerability reporting feature at:

https://github.com/kubesynapse/kubesynapse/security/advisories/new

### What to include

- Description of the vulnerability
- Steps to reproduce
- Impact assessment
- Suggested fix (if any)

### Response timeline

- Acknowledgment within 48 hours
- Initial assessment within 5 business days
- Fix timeline depends on severity

## Supported Versions

| Version | Supported |
|---|---|
| `preprod` branch | Yes |
| `main` branch | Yes |
| Older branches | No |

## Security Audit History

### 2026-04-28 — Pi Runtime Security Review

A security review of the Pi runtime integration was conducted. The following protections were implemented:

1. **Model Timeout Prevents Resource Exhaustion**
   - **Control**: `MODEL_TIMEOUT_MS=120s` aborts hung model calls automatically
   - **Rationale**: Prevents runaway Pi sessions from consuming cluster resources indefinitely
   - **File**: `pi-runtime/pi_bridge.js`

2. **Artifact API Uses Pod-Local Filesystem**
   - **Control**: `/artifacts/list`, `/artifacts/download`, `/artifacts/zip` read from local PVC only
   - **Rationale**: No network egress required for artifact retrieval; data never leaves the pod boundary
   - **File**: `pi-runtime/pi_bridge.js`

3. **Pi Session PVC Wipe Prevents State Poisoning**
   - **Control**: Session PVC is wiped between pod restarts
   - **Rationale**: Eliminates stale session state that could cause "Agent is already processing" deadlocks or cross-run data leakage
   - **File**: Operator StatefulSet reconciliation logic

### 2026-04-23 — Auth Middleware Security Hardening

A comprehensive security audit of `api-gateway/auth_middleware.py` was conducted. The following critical and high-severity issues were identified and fixed:

#### Critical Fixes Applied

1. **OIDC Default Role Escalation (CVSS 9.8)**
   - **Issue:** Users without explicit role claims were granted `admin` access with wildcard namespaces
   - **Fix:** Changed default role fallback from `"admin"` to `"viewer"`
   - **File:** `api-gateway/auth_middleware.py:313`

2. **JWT Algorithm Validation Bypass (CVSS 9.1)**
   - **Issue:** Manual JWT verification bypassed algorithm allowlist checks using deprecated `python-jose`
   - **Status:** Identified. Requires migration to `PyJWT` or `authlib` for full remediation
   - **File:** `api-gateway/auth_middleware.py:460-469`

3. **JWKS HTTP Transport (CVSS 9.3)**
   - **Issue:** OIDC JWKS URL accepted HTTP without TLS enforcement
   - **Fix:** Added HTTPS scheme validation with error logging
   - **File:** `api-gateway/auth_middleware.py:104-106`

#### High Severity Fixes Applied

4. **Cookie Secure Flag Default (CVSS 7.5)**
   - **Issue:** `AUTH_COOKIE_SECURE` defaulted to `False`, exposing refresh tokens over HTTP
   - **Fix:** Changed default to `True` (opt-out via explicit `false`)
   - **File:** `api-gateway/auth_middleware.py:66`

5. **Local Token Claim Validation (CVSS 7.1)**
   - **Issue:** Local access tokens skipped `exp`/`nbf` validation
   - **Fix:** Added time-based claim validation to `verify_local_access_token()`
   - **File:** `api-gateway/auth_middleware.py:482-502`

#### Medium Severity Fixes Applied

6. **Information Leakage in Hybrid Mode (CVSS 5.3)**
   - **Issue:** Authentication error details leaked internal failure reasons
   - **Fix:** Return generic "Authentication failed" message, log specifics server-side
   - **File:** `api-gateway/auth_middleware.py:564-565`

7. **Cookie Deletion Missing Security Flags (CVSS 5.4)**
   - **Issue:** `delete_cookie()` calls omitted `secure`, `httponly`, `samesite`
   - **Fix:** Added all security flags to cookie deletion
   - **File:** `api-gateway/auth_middleware.py:152-158, 175-181`

8. **Case-Sensitive Bearer Header (CVSS 4.3)**
   - **Issue:** `Bearer` scheme check was case-sensitive
   - **Fix:** Changed to case-insensitive comparison per RFC 6750
   - **File:** `api-gateway/auth_middleware.py:570`

9. **X-Forwarded-For Trust Model (CVSS 5.0)**
   - **Issue:** Used leftmost (client-supplied, untrusted) IP from X-Forwarded-For
   - **Fix:** Changed to use rightmost IP to prevent spoofing
   - **File:** `api-gateway/auth_middleware.py:114-121`

#### Low Severity Fixes Applied

10. **Module-Level asyncio.Lock (CVSS 3.7)**
    - **Issue:** Lock created at import time, potential event loop mismatch
    - **Fix:** Implemented lazy lock initialization via `_get_jwks_lock()`
    - **File:** `api-gateway/auth_middleware.py:76-88`

11. **Missing kid Validation (CVSS 4.0)**
    - **Issue:** Tokens without `kid` could match unintended keys in multi-key JWKS
    - **Fix:** Reject tokens without `kid` when JWKS has multiple keys
    - **File:** `api-gateway/auth_middleware.py:465-467`

12. **Configuration Leakage in 503 Errors (CVSS 3.1)**
    - **Issue:** Error messages revealed whether shared token or OIDC was configured
    - **Fix:** Return generic "Authentication service unavailable" messages
    - **File:** `api-gateway/auth_middleware.py:95, 515`

## Accepted Vulnerabilities (Risk-Accepted)

The following vulnerabilities have been reviewed and accepted as known risks. They are documented here for transparency and will be revisited quarterly.

### pip-audit Accepted Risks

| Package | CVE / Finding | Severity | Rationale |
|---------|--------------|----------|-----------|
| `cryptography` < 43.0.0 (in operator/requirements.txt) | CVE-2024-0727 | MEDIUM | Operator uses cryptography only for non-security-critical JWT signature verification. Key material is never exposed. Upgrade planned for v1.1. |
| `jinja2` < 3.1.3 (in Helm chart dependencies) | CVE-2024-34064 | MEDIUM | Jinja2 used only in Helm template rendering (build-time, not runtime). No user-controlled input reaches Jinja2. |

### Trivy Container Scan Accepted Risks

| Image | CVE | Severity | Component | Rationale |
|-------|-----|----------|-----------|-----------|
| `kubesynapse-operator` | CVE-2024-41110 | HIGH | Docker Engine (in base image) | Docker socket not mounted. Operator runs in rootless container with `readOnlyRootFilesystem: true`. |
| `kubesynapse-web-ui` | CVE-2024-38472 | MEDIUM | Apache HTTPD (nginx base) | Nginx serves only static files. No CGI/module execution enabled. |

### kube-linter Accepted Risks

| Check | Resource | Rationale |
|-------|----------|-----------|
| `no-anti-affinity` | PostgreSQL StatefulSet | Single-replica development deployments don't require anti-affinity. Production users should configure separately. |
| `dangling-service` | Collector headless service | Headless service for DaemonSet discovery is intentional — no ClusterIP needed. |

### Bandit Accepted Risks

| Finding | File | Rationale |
|---------|------|-----------|
| B104: hardcoded-bind-all-interfaces | `api-gateway/main.py` | Gateway binds to `0.0.0.0` in container (required for K8s port-forward). NetworkPolicy restricts ingress. |
| B108: hardcoded-tmp-directory | `opencode-runtime/` | `/tmp` usage is container-isolated with `readOnlyRootFilesystem: true` and `/tmp` mounted as emptyDir. |

### Review Cadence

- All accepted risks re-evaluated quarterly (next review: July 2026)
- New CRITICAL CVEs require immediate re-evaluation regardless of schedule
- Accepted risks may be escalated if exploitability changes

---

## Security Practices

This project follows these security practices:

- Container images run as non-root with read-only root filesystems
- All Linux capabilities are dropped from agent runtime pods
- Network policies restrict pod-to-pod communication
- Secrets are managed through External Secrets Operator (not baked into images)
- MCP sidecar access is controlled by per-agent NetworkPolicy and bearer token auth
- Input/output guardrails enforce prompt injection detection and PII redaction
- Regular security audits with `bandit`, `pip-audit`, and manual code review
- Pre-commit hooks enforce security linting (`flake8-bandit`)

See [docs/architecture-overview.md](docs/architecture-overview.md) for the full security model.
