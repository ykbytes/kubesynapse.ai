# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in KubeSynth, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please send an email to the maintainers or use GitHub's private vulnerability reporting feature at:

https://github.com/ykbytes/kubemininions/security/advisories/new

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
