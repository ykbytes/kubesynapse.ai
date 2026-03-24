# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Kubeminionagents, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please send an email to the maintainers or use GitHub's private vulnerability reporting feature at:

https://github.com/kubeminionagents/kubemininions/security/advisories/new

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
| `robustness-hardening` branch | Yes |
| `main` branch | Yes |
| Older branches | No |

## Security Practices

This project follows these security practices:

- Container images run as non-root with read-only root filesystems
- All Linux capabilities are dropped from agent runtime pods
- Network policies restrict pod-to-pod communication
- Secrets are managed through External Secrets Operator (not baked into images)
- MCP sidecar access is controlled by per-agent NetworkPolicy and bearer token auth
- Input/output guardrails enforce prompt injection detection and PII redaction

See [docs/architecture-overview.md](docs/architecture-overview.md) Section 11 for the full security model.
