# Security Report

- Generated: 2026-05-22T10:30:11.108936+00:00

- Results directory: `/tmp/kubesynapse-security/results`

- Scope: local equivalent run of the repository security workflow tools


## Summary

| Tool | Findings | State |
| --- | --- | --- |
| Bandit | 48 | ok |
| pip-audit | 11 | ok |
| npm audit | 19 | ok |
| Trivy filesystem | 1 | ok |
| Trivy image api-gateway | 39 | ok |
| Trivy image operator | 7 | ok |
| Trivy image web-ui | 29 | ok |
| kube-linter | 55 | ok |
| checkov Helm | 16 | ok |
| checkov Kubernetes | 88 | ok |
| TruffleHog | 3 | ok |

## Execution Notes

| Command | Status |
| --- | --- |
| bandit | 1 |
| docker-build-opencode-runtime | 1 |
| kube-linter | 1 |
| npm-audit-web-ui | 1 |
| pip-audit-api-gateway | 1 |
| pip-audit-opencode-runtime | 1 |
| trivy-fs | 1 |
| trivy-image-api-gateway | 1 |
| trivy-image-operator | 1 |
| trivy-image-web-ui | 1 |

## Bandit (48)

| Severity | Rule | Location | Issue |
| --- | --- | --- | --- |
| LOW | B105 | api-gateway/_core.py:2458 | Possible hardcoded password: 'client_secret_post' |
| LOW | B105 | api-gateway/_core.py:2556 | Possible hardcoded password: 'client_secret_basic' |
| LOW | B105 | api-gateway/_core.py:2563 | Possible hardcoded password: 'client_secret_post' |
| LOW | B110 | api-gateway/_core.py:5090 | Try, Except, Pass detected. |
| LOW | B105 | api-gateway/auth_middleware.py:406 | Possible hardcoded password: 'bearer' |
| LOW | B105 | api-gateway/jwt_utils.py:125 | Possible hardcoded password: 'access' |
| LOW | B105 | api-gateway/routers/admin.py:1022 | Possible hardcoded password: '***' |
| LOW | B105 | api-gateway/routers/admin.py:1129 | Possible hardcoded password: '***' |
| LOW | B105 | api-gateway/routers/auth.py:949 | Possible hardcoded password: 'https://api.notion.com/v1/oauth/token' |
| LOW | B105 | api-gateway/routers/auth.py:950 | Possible hardcoded password: 'client_secret_basic' |
| LOW | B105 | api-gateway/routers/auth.py:1160 | Possible hardcoded password: 'https://oauth2.googleapis.com/token' |
| LOW | B105 | api-gateway/routers/chat.py:439 | Possible hardcoded password: 'OPENCODE_API_KEY' |
| LOW | B105 | api-gateway/routers/chat.py:447 | Possible hardcoded password: 'OPENCODE_GO_API_KEY' |
| LOW | B105 | api-gateway/routers/chat.py:455 | Possible hardcoded password: 'GITHUB_COPILOT_TOKEN' |
| LOW | B110 | api-gateway/routers/llm.py:49 | Try, Except, Pass detected. |
| LOW | B105 | api-gateway/routers/llm.py:605 | Possible hardcoded password: 'https://github.com/login/oauth/access_token' |
| LOW | B105 | api-gateway/routers/observability.py:1093 | Possible hardcoded password: 'Collector token is unavailable in the gateway. Re-register this collector with a valid token.' |
| LOW | B110 | api-gateway/routers/webhooks.py:389 | Try, Except, Pass detected. |
| LOW | B110 | api-gateway/routers/workflows.py:697 | Try, Except, Pass detected. |
| LOW | B105 | opencode-runtime/config.py:302 | Possible hardcoded password: 'API_GATEWAY_SHARED_TOKEN' |
| LOW | B404 | opencode-runtime/main.py:13 | Consider possible security implications associated with the subprocess module. |
| HIGH | B324 | opencode-runtime/main.py:776 | Use of weak MD5 hash for security. Consider usedforsecurity=False |
| LOW | B110 | opencode-runtime/pi_client.py:172 | Try, Except, Pass detected. |
| LOW | B110 | opencode-runtime/pi_client.py:183 | Try, Except, Pass detected. |
| LOW | B404 | opencode-runtime/skills.py:9 | Consider possible security implications associated with the subprocess module. |
| LOW | B112 | opencode-runtime/skills.py:232 | Try, Except, Continue detected. |
| LOW | B607 | opencode-runtime/skills.py:608 | Starting a process with a partial executable path |
| LOW | B603 | opencode-runtime/skills.py:608 | subprocess call - check for execution of untrusted input. |
| LOW | B607 | opencode-runtime/skills.py:613 | Starting a process with a partial executable path |
| LOW | B603 | opencode-runtime/skills.py:613 | subprocess call - check for execution of untrusted input. |
| LOW | B607 | opencode-runtime/skills.py:626 | Starting a process with a partial executable path |
| LOW | B603 | opencode-runtime/skills.py:626 | subprocess call - check for execution of untrusted input. |
| LOW | B607 | opencode-runtime/skills.py:648 | Starting a process with a partial executable path |
| LOW | B603 | opencode-runtime/skills.py:648 | subprocess call - check for execution of untrusted input. |
| LOW | B607 | opencode-runtime/skills.py:667 | Starting a process with a partial executable path |
| LOW | B603 | opencode-runtime/skills.py:667 | subprocess call - check for execution of untrusted input. |
| LOW | B404 | opencode-runtime/supervisor.py:9 | Consider possible security implications associated with the subprocess module. |
| LOW | B603 | opencode-runtime/supervisor.py:158 | subprocess call - check for execution of untrusted input. |
| LOW | B404 | opencode-runtime/workspace.py:10 | Consider possible security implications associated with the subprocess module. |
| LOW | B607 | opencode-runtime/workspace.py:290 | Starting a process with a partial executable path |
| LOW | B603 | opencode-runtime/workspace.py:290 | subprocess call - check for execution of untrusted input. |
| LOW | B607 | opencode-runtime/workspace.py:302 | Starting a process with a partial executable path |
| LOW | B603 | opencode-runtime/workspace.py:302 | subprocess call - check for execution of untrusted input. |
| MEDIUM | B113 | operator/builders/manifests.py:533 | Call to requests without timeout |
| LOW | B311 | operator/services/k8s.py:76 | Standard pseudo-random generators are not suitable for security/cryptographic purposes. |
| LOW | B105 | operator/services/k8s.py:437 | Possible hardcoded password: 'external-secrets' |
| LOW | B311 | operator/services/k8s.py:654 | Standard pseudo-random generators are not suitable for security/cryptographic purposes. |
| LOW | B311 | operator/worker.py:446 | Standard pseudo-random generators are not suitable for security/cryptographic purposes. |

## pip-audit (11)

| Project | Package | Version | Advisory | Fixed Version |
| --- | --- | --- | --- | --- |
| api-gateway | fastapi | 0.109.0 | PYSEC-2024-38 | 0.109.1 |
| api-gateway | python-jose | 3.3.0 | PYSEC-2024-233 | 3.4.0 |
| api-gateway | python-jose | 3.3.0 | PYSEC-2024-232 | 3.4.0 |
| api-gateway | python-jose | 3.3.0 | PYSEC-2024-232 | 3.4.0 |
| api-gateway | python-jose | 3.3.0 | PYSEC-2024-233 | 3.4.0 |
| api-gateway | python-jose | 3.3.0 | PYSEC-2025-185 | none |
| api-gateway | starlette | 0.35.1 | CVE-2024-47874 | 0.40.0 |
| api-gateway | starlette | 0.35.1 | CVE-2025-54121 | 0.47.2 |
| opencode-runtime | fastapi | 0.109.0 | PYSEC-2024-38 | 0.109.1 |
| opencode-runtime | starlette | 0.35.1 | CVE-2024-47874 | 0.40.0 |
| opencode-runtime | starlette | 0.35.1 | CVE-2025-54121 | 0.47.2 |

## npm audit (19)

| Project | Package | Severity | Advisory | URL | Fix Available |
| --- | --- | --- | --- | --- | --- |
| web-ui | dompurify | moderate | DOMPurify contains a Cross-site Scripting vulnerability | https://github.com/advisories/GHSA-v2wj-7wpq-c8vv | {'name': 'monaco-editor', 'version': '0.53.0', 'isSemVerMajor': True} |
| web-ui | dompurify | moderate | DOMPurify ADD_ATTR predicate skips URI validation | https://github.com/advisories/GHSA-cjmm-f4jc-qw8r | {'name': 'monaco-editor', 'version': '0.53.0', 'isSemVerMajor': True} |
| web-ui | dompurify | moderate | DOMPurify USE_PROFILES prototype pollution allows event handlers | https://github.com/advisories/GHSA-cj63-jhhr-wcxv | {'name': 'monaco-editor', 'version': '0.53.0', 'isSemVerMajor': True} |
| web-ui | dompurify | moderate | DOMPurify's ADD_TAGS function form bypasses FORBID_TAGS due to short-circuit evaluation | https://github.com/advisories/GHSA-39q2-94rc-95cp | {'name': 'monaco-editor', 'version': '0.53.0', 'isSemVerMajor': True} |
| web-ui | dompurify | moderate | DOMPurify: FORBID_TAGS bypassed by function-based ADD_TAGS predicate (asymmetry with FORBID_ATTR fix) | https://github.com/advisories/GHSA-h7mw-gpvr-xq4m | {'name': 'monaco-editor', 'version': '0.53.0', 'isSemVerMajor': True} |
| web-ui | dompurify | moderate | DOMPurify has a SAFE_FOR_TEMPLATES bypass in RETURN_DOM mode | https://github.com/advisories/GHSA-crv5-9vww-q3g8 | {'name': 'monaco-editor', 'version': '0.53.0', 'isSemVerMajor': True} |
| web-ui | dompurify | moderate | DOMPurify: Prototype Pollution to XSS Bypass via CUSTOM_ELEMENT_HANDLING Fallback | https://github.com/advisories/GHSA-v9jr-rg53-9pgp | {'name': 'monaco-editor', 'version': '0.53.0', 'isSemVerMajor': True} |
| web-ui | dompurify | moderate | DOMPurify is vulnerable to mutation-XSS via Re-Contextualization  | https://github.com/advisories/GHSA-h8r8-wccr-v5f2 | {'name': 'monaco-editor', 'version': '0.53.0', 'isSemVerMajor': True} |
| web-ui | mermaid | moderate | Mermaid Gantt Charts are vulnerable to an Infinite Loop DoS | https://github.com/advisories/GHSA-6m6c-36f7-fhxh | True |
| web-ui | mermaid | moderate | Mermaid: Improper sanitization of `classDefs` in diagrams leads to CSS injection | https://github.com/advisories/GHSA-xcj9-5m2h-648r | True |
| web-ui | mermaid | moderate | Mermaid: Improper sanitization of configuration leads to CSS injection | https://github.com/advisories/GHSA-87f9-hvmw-gh4p | True |
| web-ui | mermaid | moderate | Mermaid: Improper sanitization of `classDef` in state diagrams leads to HTML injection | https://github.com/advisories/GHSA-ghcm-xqfw-q4vr | True |
| web-ui | monaco-editor | moderate | transitive advisory |  | {'name': 'monaco-editor', 'version': '0.53.0', 'isSemVerMajor': True} |
| web-ui | picomatch | moderate | Picomatch: Method Injection in POSIX Character Classes causes incorrect Glob Matching | https://github.com/advisories/GHSA-3v7f-55p6-f55p | True |
| web-ui | picomatch | high | Picomatch has a ReDoS vulnerability via extglob quantifiers | https://github.com/advisories/GHSA-c2c7-rcm5-vvqj | True |
| web-ui | postcss | moderate | PostCSS has XSS via Unescaped </style> in its CSS Stringify Output | https://github.com/advisories/GHSA-qx2v-qp2m-jg93 | True |
| web-ui | uuid | moderate | uuid: Missing buffer bounds check in v3/v5/v6 when buf is provided | https://github.com/advisories/GHSA-w5hq-g745-h8pq | True |
| web-ui | vite | moderate | Vite Vulnerable to Path Traversal in Optimized Deps `.map` Handling | https://github.com/advisories/GHSA-4w7w-66w2-5vf9 | True |
| web-ui | vite | high | Vite Vulnerable to Arbitrary File Read via Vite Dev Server WebSocket | https://github.com/advisories/GHSA-p9ff-h696-f583 | True |

## Trivy filesystem (1)

| Target | Package | Version | Advisory | Severity | Fixed Version |
| --- | --- | --- | --- | --- | --- |
| api-gateway/requirements.txt | python-jose | 3.3.0 | CVE-2024-33663 | CRITICAL | 3.4.0 |

## Trivy image api-gateway (39)

| Target | Package | Version | Advisory | Severity | Fixed Version |
| --- | --- | --- | --- | --- | --- |
| /results/api-gateway.tar (debian 13.5) | libncursesw6 | 6.5+20250216-2 | CVE-2025-69720 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | libtinfo6 | 6.5+20250216-2 | CVE-2025-69720 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2013-7445 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2019-19449 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2019-19814 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2021-3847 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2021-3864 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2024-21803 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2024-58015 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2024-58093 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2025-22104 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2025-38137 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2025-38187 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2025-38204 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2025-38206 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2025-38421 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2025-38636 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2025-39859 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2025-39862 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2025-39958 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2026-23102 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2026-23171 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2026-23208 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2026-23327 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2026-31493 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2026-31568 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2026-31663 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2026-31688 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2026-43198 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2026-43494 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | linux-libc-dev | 6.12.88-1 | CVE-2026-46300 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | ncurses-base | 6.5+20250216-2 | CVE-2025-69720 | HIGH | none |
| /results/api-gateway.tar (debian 13.5) | ncurses-bin | 6.5+20250216-2 | CVE-2025-69720 | HIGH | none |
| Python | ecdsa | 0.19.2 | CVE-2024-23342 | HIGH | none |
| Python | jaraco.context | 5.3.0 | CVE-2026-23949 | HIGH | 6.1.0 |
| Python | python-jose | 3.3.0 | CVE-2024-33663 | CRITICAL | 3.4.0 |
| Python | starlette | 0.35.1 | CVE-2024-47874 | HIGH | 0.40.0 |
| Python | wheel | 0.45.1 | CVE-2026-24049 | HIGH | 0.46.2 |
| Python | wheel | 0.45.1 | CVE-2026-24049 | HIGH | 0.46.2 |

## Trivy image operator (7)

| Target | Package | Version | Advisory | Severity | Fixed Version |
| --- | --- | --- | --- | --- | --- |
| /results/operator.tar (debian 13.5) | libncursesw6 | 6.5+20250216-2 | CVE-2025-69720 | HIGH | none |
| /results/operator.tar (debian 13.5) | libtinfo6 | 6.5+20250216-2 | CVE-2025-69720 | HIGH | none |
| /results/operator.tar (debian 13.5) | ncurses-base | 6.5+20250216-2 | CVE-2025-69720 | HIGH | none |
| /results/operator.tar (debian 13.5) | ncurses-bin | 6.5+20250216-2 | CVE-2025-69720 | HIGH | none |
| Python | jaraco.context | 5.3.0 | CVE-2026-23949 | HIGH | 6.1.0 |
| Python | wheel | 0.45.1 | CVE-2026-24049 | HIGH | 0.46.2 |
| Python | wheel | 0.45.1 | CVE-2026-24049 | HIGH | 0.46.2 |

## Trivy image web-ui (29)

| Target | Package | Version | Advisory | Severity | Fixed Version |
| --- | --- | --- | --- | --- | --- |
| /results/web-ui.tar (alpine 3.21.3) | libcrypto3 | 3.3.3-r0 | CVE-2026-31789 | CRITICAL | 3.3.7-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libcrypto3 | 3.3.3-r0 | CVE-2025-15467 | HIGH | 3.3.6-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libcrypto3 | 3.3.3-r0 | CVE-2025-69421 | HIGH | 3.3.6-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libcrypto3 | 3.3.3-r0 | CVE-2026-28387 | HIGH | 3.3.7-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libcrypto3 | 3.3.3-r0 | CVE-2026-28388 | HIGH | 3.3.7-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libcrypto3 | 3.3.3-r0 | CVE-2026-28389 | HIGH | 3.3.7-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libcrypto3 | 3.3.3-r0 | CVE-2026-28390 | HIGH | 3.3.7-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libexpat | 2.7.0-r0 | CVE-2025-59375 | HIGH | 2.7.2-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libexpat | 2.7.0-r0 | CVE-2026-25210 | HIGH | 2.7.4-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libpng | 1.6.47-r0 | CVE-2025-64720 | HIGH | 1.6.53-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libpng | 1.6.47-r0 | CVE-2025-65018 | HIGH | 1.6.53-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libpng | 1.6.47-r0 | CVE-2025-66293 | HIGH | 1.6.53-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libpng | 1.6.47-r0 | CVE-2026-22695 | HIGH | 1.6.54-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libpng | 1.6.47-r0 | CVE-2026-22801 | HIGH | 1.6.54-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libpng | 1.6.47-r0 | CVE-2026-25646 | HIGH | 1.6.55-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libssl3 | 3.3.3-r0 | CVE-2026-31789 | CRITICAL | 3.3.7-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libssl3 | 3.3.3-r0 | CVE-2025-15467 | HIGH | 3.3.6-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libssl3 | 3.3.3-r0 | CVE-2025-69421 | HIGH | 3.3.6-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libssl3 | 3.3.3-r0 | CVE-2026-28387 | HIGH | 3.3.7-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libssl3 | 3.3.3-r0 | CVE-2026-28388 | HIGH | 3.3.7-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libssl3 | 3.3.3-r0 | CVE-2026-28389 | HIGH | 3.3.7-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libssl3 | 3.3.3-r0 | CVE-2026-28390 | HIGH | 3.3.7-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libxml2 | 2.13.4-r6 | CVE-2025-49794 | HIGH | 2.13.9-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libxml2 | 2.13.4-r6 | CVE-2025-49795 | HIGH | 2.13.9-r0 |
| /results/web-ui.tar (alpine 3.21.3) | libxml2 | 2.13.4-r6 | CVE-2025-49796 | HIGH | 2.13.9-r0 |
| /results/web-ui.tar (alpine 3.21.3) | musl | 1.2.5-r9 | CVE-2026-40200 | HIGH | 1.2.5-r11 |
| /results/web-ui.tar (alpine 3.21.3) | musl-utils | 1.2.5-r9 | CVE-2026-40200 | HIGH | 1.2.5-r11 |
| /results/web-ui.tar (alpine 3.21.3) | nghttp2-libs | 1.64.0-r0 | CVE-2026-27135 | HIGH | 1.68.1 |
| /results/web-ui.tar (alpine 3.21.3) | zlib | 1.3.1-r2 | CVE-2026-22184 | HIGH | 1.3.2-r0 |

## kube-linter (55)

| Check | Kind | Object | Message |
| --- | --- | --- | --- |
| pdb-unhealthy-pod-eviction-policy | PodDisruptionBudget | kubesynapse-api-gateway | unhealthyPodEvictionPolicy is not explicitly set |
| pdb-unhealthy-pod-eviction-policy | PodDisruptionBudget | kubesynapse-operator | unhealthyPodEvictionPolicy is not explicitly set |
| pdb-unhealthy-pod-eviction-policy | PodDisruptionBudget | kubesynapse-litellm | unhealthyPodEvictionPolicy is not explicitly set |
| pdb-min-available | PodDisruptionBudget | kubesynapse-postgresql | The current number of replicas for deployment kubesynapse-postgresql is equal to or lower than the minimum number of replicas specified by its PDB. |
| pdb-unhealthy-pod-eviction-policy | PodDisruptionBudget | kubesynapse-postgresql | unhealthyPodEvictionPolicy is not explicitly set |
| access-to-secrets | ClusterRoleBinding | kubesynapse-operator-rolebinding | binding to "kubesynapse-operator-role" clusterrole that has [get list watch] access to [secrets] |
| access-to-secrets | RoleBinding | kubesynapse-operator-local-binding | binding to "kubesynapse-operator-local" role that has [create delete get list patch update] access to [secrets] |
| access-to-secrets | RoleBinding | kubesynapse-api-gateway-secrets-binding | binding to "kubesynapse-api-gateway-secrets" role that has [get list create update] access to [secrets] |
| env-var-secret | Deployment | kubesynapse-api-gateway | environment variable REQUIRE_JWT_SECRET in container "api-gateway" found |
| env-var-secret | Deployment | kubesynapse-api-gateway | environment variable LLM_SECRET_NAME in container "api-gateway" found |
| env-var-secret | Deployment | kubesynapse-api-gateway | environment variable PROVIDER_AUTH_SECRET_NAME in container "api-gateway" found |
| read-secret-from-env-var | Deployment | kubesynapse-api-gateway | environment variable "API_GATEWAY_SHARED_TOKEN" in container "api-gateway" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-api-gateway | environment variable "JWT_SECRET" in container "api-gateway" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-api-gateway | environment variable "INTELLIGENCE_COLLECTOR_TOKEN_KEY" in container "api-gateway" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-api-gateway | environment variable "AUTH_BOOTSTRAP_ADMIN_PASSWORD" in container "api-gateway" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-api-gateway | environment variable "LDAP_BIND_PASSWORD" in container "api-gateway" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-api-gateway | environment variable "OIDC_PROVIDERS_JSON" in container "api-gateway" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-api-gateway | environment variable "SAML_PROVIDERS_JSON" in container "api-gateway" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-api-gateway | environment variable "DATABASE_PASSWORD" in container "api-gateway" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-api-gateway | environment variable "NATS_TOKEN" in container "api-gateway" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-api-gateway | environment variable "REDIS_PASSWORD" in container "api-gateway" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-api-gateway | environment variable "LITELLM_MASTER_KEY" in container "api-gateway" uses SecretKeyRef |
| no-anti-affinity | Deployment | kubesynapse-litellm | object has 2 replicas but does not specify inter pod anti-affinity |
| no-read-only-root-fs | Deployment | kubesynapse-litellm | container "litellm-schema-sync" does not have a read-only root file system |
| no-read-only-root-fs | Deployment | kubesynapse-litellm | container "litellm-db-init" does not have a read-only root file system |
| read-secret-from-env-var | Deployment | kubesynapse-litellm | environment variable "DATABASE_URL" in container "litellm-db-init" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-litellm | environment variable "DATABASE_URL" in container "litellm" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-litellm | environment variable "LITELLM_MASTER_KEY" in container "litellm" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-litellm | environment variable "OPENAI_API_KEY" in container "litellm" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-litellm | environment variable "OPENROUTER_API_KEY" in container "litellm" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-litellm | environment variable "ANTHROPIC_API_KEY" in container "litellm" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-litellm | environment variable "REDIS_PASSWORD" in container "litellm" uses SecretKeyRef |
| unset-cpu-requirements | Deployment | kubesynapse-litellm | container "litellm-schema-sync" has cpu request 0 |
| unset-cpu-requirements | Deployment | kubesynapse-litellm | container "litellm-db-init" has cpu request 0 |
| unset-memory-requirements | Deployment | kubesynapse-litellm | container "litellm-schema-sync" has memory limit 0 |
| unset-memory-requirements | Deployment | kubesynapse-litellm | container "litellm-db-init" has memory limit 0 |
| latest-tag | Deployment | kubesynapse-mcp-github | The container "github-upstream" is using an invalid container image, "ghcr.io/github/github-mcp-server:latest". Please use images that are not blocked by the `BlockList` criteria : [".*:(latest)$" "^[^:]*$" "(.*/[^:]+)$"] |
| read-secret-from-env-var | Deployment | kubesynapse-mcp-github | environment variable "MCP_BEARER_TOKEN" in container "mcp-server" uses SecretKeyRef |
| env-var-secret | Deployment | kubesynapse-operator | environment variable LLM_SECRET_NAME in container "operator" found |
| env-var-secret | Deployment | kubesynapse-operator | environment variable CLUSTER_SECRET_STORE in container "operator" found |
| env-var-secret | Deployment | kubesynapse-operator | environment variable SECRET_PROVISIONING_MODE in container "operator" found |
| env-var-secret | Deployment | kubesynapse-operator | environment variable MCP_AUTH_SECRET_NAME in container "operator" found |
| read-secret-from-env-var | Deployment | kubesynapse-operator | environment variable "DATABASE_PASSWORD" in container "operator" uses SecretKeyRef |
| read-secret-from-env-var | Deployment | kubesynapse-operator | environment variable "DEFAULT_LITELLM_MASTER_KEY" in container "operator" uses SecretKeyRef |
| no-read-only-root-fs | Deployment | kubesynapse-qdrant | container "qdrant" does not have a read-only root file system |
| no-anti-affinity | Deployment | kubesynapse-web-ui | object has 2 replicas but does not specify inter pod anti-affinity |
| no-read-only-root-fs | StatefulSet | kubesynapse-postgresql | container "fix-permissions" does not have a read-only root file system |
| no-read-only-root-fs | StatefulSet | kubesynapse-postgresql | container "postgresql" does not have a read-only root file system |
| read-secret-from-env-var | StatefulSet | kubesynapse-postgresql | environment variable "POSTGRES_PASSWORD" in container "postgresql" uses SecretKeyRef |
| run-as-non-root | StatefulSet | kubesynapse-postgresql | container "fix-permissions" is not set to runAsNonRoot |
| unset-cpu-requirements | StatefulSet | kubesynapse-postgresql | container "fix-permissions" has cpu request 0 |
| unset-memory-requirements | StatefulSet | kubesynapse-postgresql | container "fix-permissions" has memory limit 0 |
| latest-tag | Job | kubesynapse-pvc-retention-migration | The container "migrate" is using an invalid container image, "bitnami/kubectl:latest". Please use images that are not blocked by the `BlockList` criteria : [".*:(latest)$" "^[^:]*$" "(.*/[^:]+)$"] |
| unset-cpu-requirements | Job | kubesynapse-pvc-retention-migration | container "migrate" has cpu request 0 |
| unset-memory-requirements | Job | kubesynapse-pvc-retention-migration | container "migrate" has memory limit 0 |

## checkov Helm (16)

| Check | Resource | Message | File |
| --- | --- | --- | --- |
| CKV_K8S_21 | ConfigMap.default.release-name-kubesynapse-skills-catalog | The default namespace should not be used | /kubesynapse/templates/skills-catalog-configmap.yaml |
| CKV_K8S_21 | ConfigMap.default.release-name-kubesynapse-web-ui-nginx | The default namespace should not be used | /kubesynapse/templates/web-ui.yaml |
| CKV_K8S_21 | Secret.default.release-name-kubesynapse-llm-api-keys | The default namespace should not be used | /kubesynapse/templates/external-secrets.yaml |
| CKV_K8S_21 | ConfigMap.default.release-name-kubesynapse-postgresql-initdb | The default namespace should not be used | /kubesynapse/templates/postgresql-initdb-configmap.yaml |
| CKV_K8S_21 | ConfigMap.default.release-name-kubesynapse-provider-registry | The default namespace should not be used | /kubesynapse/templates/provider-registry-configmap.yaml |
| CKV_K8S_21 | ConfigMap.default.release-name-kubesynapse-pi-safe-config | The default namespace should not be used | /kubesynapse/templates/pi-safe-config.yaml |
| CKV_K8S_21 | ConfigMap.default.release-name-kubesynapse-litellm-config | The default namespace should not be used | /kubesynapse/templates/litellm-configmap.yaml |
| CKV_K8S_21 | ServiceAccount.default.release-name-kubesynapse-operator-sa | The default namespace should not be used | /kubesynapse/templates/operator-rbac.yaml |
| CKV_K8S_21 | ServiceAccount.default.release-name-kubesynapse-api-gateway-sa | The default namespace should not be used | /kubesynapse/templates/operator-rbac.yaml |
| CKV_K8S_21 | ServiceAccount.default.release-name-kubesynapse-worker-sa | The default namespace should not be used | /kubesynapse/templates/operator-rbac.yaml |
| CKV_K8S_21 | ServiceAccount.default.kubesynapse-agent-runtime | The default namespace should not be used | /kubesynapse/templates/operator-rbac.yaml |
| CKV_K8S_21 | Role.default.release-name-kubesynapse-operator-local | The default namespace should not be used | /kubesynapse/templates/operator-rbac.yaml |
| CKV_K8S_21 | Role.default.release-name-kubesynapse-api-gateway-secrets | The default namespace should not be used | /kubesynapse/templates/operator-rbac.yaml |
| CKV_K8S_21 | RoleBinding.default.release-name-kubesynapse-operator-local-binding | The default namespace should not be used | /kubesynapse/templates/operator-rbac.yaml |
| CKV_K8S_21 | RoleBinding.default.release-name-kubesynapse-api-gateway-secrets-binding | The default namespace should not be used | /kubesynapse/templates/operator-rbac.yaml |
| CKV_K8S_21 | ConfigMap.default.release-name-kubesynapse-opencode-safe-config | The default namespace should not be used | /kubesynapse/templates/opencode-safe-config.yaml |

## checkov Kubernetes (88)

| Check | Resource | Message | File |
| --- | --- | --- | --- |
| CKV_K8S_21 | ServiceAccount.default.kubesynapse-operator-sa | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | ServiceAccount.default.kubesynapse-api-gateway-sa | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | ServiceAccount.default.kubesynapse-worker-sa | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | ServiceAccount.default.kubesynapse-agent-runtime | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Secret.default.kubesynapse-llm-api-keys | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | ConfigMap.default.kubesynapse-litellm-config | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | ConfigMap.default.kubesynapse-opencode-safe-config | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | ConfigMap.default.kubesynapse-pi-safe-config | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | ConfigMap.default.kubesynapse-postgresql-initdb | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | ConfigMap.default.kubesynapse-provider-registry | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | ConfigMap.default.kubesynapse-skills-catalog | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | ConfigMap.default.kubesynapse-web-ui-nginx | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Service.default.kubesynapse-api-gateway | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Service.default.kubesynapse-litellm | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Service.default.kubesynapse-nats | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Service.default.kubesynapse-postgresql | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Service.default.kubesynapse-qdrant | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Service.default.kubesynapse-redis | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Service.default.kubesynapse-web-ui | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_15 | Deployment.default.kubesynapse-api-gateway | Image Pull Policy should be Always | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_40 | Deployment.default.kubesynapse-api-gateway | Containers should run as a high UID to avoid host conflict | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_35 | Deployment.default.kubesynapse-api-gateway | Prefer using secrets as files over secrets as environment variables | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_38 | Deployment.default.kubesynapse-api-gateway | Ensure that Service Account Tokens are only mounted where necessary | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_43 | Deployment.default.kubesynapse-api-gateway | Image should use digest | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Deployment.default.kubesynapse-api-gateway | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_15 | Deployment.default.kubesynapse-litellm | Image Pull Policy should be Always | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_40 | Deployment.default.kubesynapse-litellm | Containers should run as a high UID to avoid host conflict | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_35 | Deployment.default.kubesynapse-litellm | Prefer using secrets as files over secrets as environment variables | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_10 | Deployment.default.kubesynapse-litellm | CPU requests should be set | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_12 | Deployment.default.kubesynapse-litellm | Memory requests should be set | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_22 | Deployment.default.kubesynapse-litellm | Use read-only filesystem for containers where possible | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_43 | Deployment.default.kubesynapse-litellm | Image should use digest | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_11 | Deployment.default.kubesynapse-litellm | CPU limits should be set | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_13 | Deployment.default.kubesynapse-litellm | Memory limits should be set | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Deployment.default.kubesynapse-litellm | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_15 | Deployment.mcp-hub.kubesynapse-mcp-github | Image Pull Policy should be Always | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_40 | Deployment.mcp-hub.kubesynapse-mcp-github | Containers should run as a high UID to avoid host conflict | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_35 | Deployment.mcp-hub.kubesynapse-mcp-github | Prefer using secrets as files over secrets as environment variables | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_9 | Deployment.mcp-hub.kubesynapse-mcp-github | Readiness Probe Should be Configured | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_8 | Deployment.mcp-hub.kubesynapse-mcp-github | Liveness Probe Should be Configured | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_43 | Deployment.mcp-hub.kubesynapse-mcp-github | Image should use digest | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_14 | Deployment.mcp-hub.kubesynapse-mcp-github | Image Tag should be fixed - not latest or blank | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_15 | Deployment.default.kubesynapse-nats | Image Pull Policy should be Always | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_40 | Deployment.default.kubesynapse-nats | Containers should run as a high UID to avoid host conflict | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_43 | Deployment.default.kubesynapse-nats | Image should use digest | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Deployment.default.kubesynapse-nats | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_15 | Deployment.default.kubesynapse-operator | Image Pull Policy should be Always | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_40 | Deployment.default.kubesynapse-operator | Containers should run as a high UID to avoid host conflict | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_35 | Deployment.default.kubesynapse-operator | Prefer using secrets as files over secrets as environment variables | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_38 | Deployment.default.kubesynapse-operator | Ensure that Service Account Tokens are only mounted where necessary | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_43 | Deployment.default.kubesynapse-operator | Image should use digest | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Deployment.default.kubesynapse-operator | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_15 | Deployment.default.kubesynapse-qdrant | Image Pull Policy should be Always | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_40 | Deployment.default.kubesynapse-qdrant | Containers should run as a high UID to avoid host conflict | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_22 | Deployment.default.kubesynapse-qdrant | Use read-only filesystem for containers where possible | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_43 | Deployment.default.kubesynapse-qdrant | Image should use digest | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Deployment.default.kubesynapse-qdrant | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_15 | Deployment.default.kubesynapse-redis | Image Pull Policy should be Always | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_40 | Deployment.default.kubesynapse-redis | Containers should run as a high UID to avoid host conflict | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_43 | Deployment.default.kubesynapse-redis | Image should use digest | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Deployment.default.kubesynapse-redis | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_15 | Deployment.default.kubesynapse-web-ui | Image Pull Policy should be Always | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_40 | Deployment.default.kubesynapse-web-ui | Containers should run as a high UID to avoid host conflict | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_43 | Deployment.default.kubesynapse-web-ui | Image should use digest | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Deployment.default.kubesynapse-web-ui | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_15 | StatefulSet.default.kubesynapse-postgresql | Image Pull Policy should be Always | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_40 | StatefulSet.default.kubesynapse-postgresql | Containers should run as a high UID to avoid host conflict | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_35 | StatefulSet.default.kubesynapse-postgresql | Prefer using secrets as files over secrets as environment variables | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_10 | StatefulSet.default.kubesynapse-postgresql | CPU requests should be set | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_12 | StatefulSet.default.kubesynapse-postgresql | Memory requests should be set | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_22 | StatefulSet.default.kubesynapse-postgresql | Use read-only filesystem for containers where possible | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_20 | StatefulSet.default.kubesynapse-postgresql | Containers should not run with allowPrivilegeEscalation | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_28 | StatefulSet.default.kubesynapse-postgresql | Minimize the admission of containers with the NET_RAW capability | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_43 | StatefulSet.default.kubesynapse-postgresql | Image should use digest | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_11 | StatefulSet.default.kubesynapse-postgresql | CPU limits should be set | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_13 | StatefulSet.default.kubesynapse-postgresql | Memory limits should be set | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_37 | StatefulSet.default.kubesynapse-postgresql | Minimize the admission of containers with capabilities assigned | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | StatefulSet.default.kubesynapse-postgresql | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_15 | Job.default.kubesynapse-pvc-retention-migration | Image Pull Policy should be Always | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_40 | Job.default.kubesynapse-pvc-retention-migration | Containers should run as a high UID to avoid host conflict | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_10 | Job.default.kubesynapse-pvc-retention-migration | CPU requests should be set | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_12 | Job.default.kubesynapse-pvc-retention-migration | Memory requests should be set | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_38 | Job.default.kubesynapse-pvc-retention-migration | Ensure that Service Account Tokens are only mounted where necessary | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_43 | Job.default.kubesynapse-pvc-retention-migration | Image should use digest | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_11 | Job.default.kubesynapse-pvc-retention-migration | CPU limits should be set | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_13 | Job.default.kubesynapse-pvc-retention-migration | Memory limits should be set | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_14 | Job.default.kubesynapse-pvc-retention-migration | Image Tag should be fixed - not latest or blank | /results/kubesynapse-manifests-fixed.yaml |
| CKV_K8S_21 | Job.default.kubesynapse-pvc-retention-migration | The default namespace should not be used | /results/kubesynapse-manifests-fixed.yaml |

## TruffleHog (3)

| Detector | Location | Verified | Raw |
| --- | --- | --- | --- |
| Github | /repo/.git/config | False | ghs_1143301_eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9 |
| Postgres | /repo/api-gateway/routers/auth.py | False | postgresql://user:pass@host:5432 |
| Postgres | /repo/api-gateway/routers/auth.py | False | postgresql://user:pass@host:5432 |

## Bandit Severity Totals

| Severity | Count |
| --- | --- |
| HIGH | 1 |
| LOW | 46 |
| MEDIUM | 1 |
