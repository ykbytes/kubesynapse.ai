# Deployment & Production Readiness Guide

Welcome to the Kubemininions deployment suite. This directory contains comprehensive resources for preparing and deploying the AI Agent Sandbox to production.

## 📋 Documentation Files

### 1. **[production-deployment-guide.md](production-deployment-guide.md)**
Comprehensive guide covering:
- Pre-deployment verification checklist
- Step-by-step deployment instructions  
- Production readiness matrix
- Scaling and high availability guidance
- Monitoring and observability recommendations
- Troubleshooting procedures
- Maintenance and update procedures

**When to use:** During initial deployment planning and execution

### 2. **[deployment-checklist.yaml](deployment-checklist.yaml)**
Interactive YAML-based checklist with:
- Pre-deployment phase checks
- Deployment phase operations
- Post-deployment verification steps
- Functionality validation
- Security verification
- Performance and monitoring checks
- Disaster recovery procedures
- Final approval sign-off

**When to use:** During actual deployment to track progress and ensure nothing is missed

### 3. **[tests/test_production_readiness.py](../tests/test_production_readiness.py)**
Automated validation script that checks:
- Image tags and versioning
- Dockerfile security practices
- Helm chart configuration
- Values file security (no hardcoded secrets)
- Web UI TypeScript compilation
- API gateway setup
- Database persistence
- RBAC configuration
- Pod security contexts
- Test suite availability

**When to use:** Before deployment to automatically validate the platform is ready

## 🚀 Quick Start

### Prerequisites
```bash
# Ensure you have:
- Kubernetes 1.24+ cluster
- kubectl configured
- Helm 3.10+
- Docker (for image validation)
```

### Step 1: Run Automated Validation
```bash
# Full validation with detailed output
python test_production_readiness.py --verbose

# Generate JSON report for documentation
python test_production_readiness.py --report deployment_report.json

# Run only critical checks
python test_production_readiness.py 2>&1 | grep FAIL
```

### Step 2: Review Production Deployment Guide
```bash
# Read through production-deployment-guide.md
# Pay special attention to:
# - Security & Hardening section
# - Credentials setup
# - Production values configuration
```

### Step 3: Execute Using Checklist
```bash
# Use deployment-checklist.yaml as your deployment guide
# Work through each phase:
# 1. Pre-deployment phase
# 2. Deployment phase (Helm install)
# 3. Post-deployment verification
# 4. Security verification
# 5. Final approval
```

### Step 4: Deploy
```bash
# Prepare your environment
export ADMIN_PASSWORD="your-secure-password"
export JWT_SECRET="your-32-char-secret"

# Update values file with your configuration
vim deploy/values.dockerhub.local.yaml

# Deploy using Helm
helm install ai-agent-sandbox ./charts/ai-agent-sandbox \
  -f deploy/values.dockerhub.local.yaml \
  -n ai-platform

# Monitor deployment
kubectl get pods -n ai-platform -w
```

## 🔍 Workflow by Scenario

### Scenario 1: First-time Production Deployment
1. Run `python test_production_readiness.py --verbose`
2. Review any warnings or critical issues
3. Read **production-deployment-guide.md** completely
4. Work through **deployment-checklist.yaml** systematically
5. Deploy using Helm commands from the guide

### Scenario 2: Upgrading Existing Deployment
1. Run validation script to check new version readiness
2. Review the "Updates and Rollbacks" section in deployment guide
3. Use `helm upgrade` command with new values file
4. Work through post-deployment verification section of checklist
5. Have rollback command ready

### Scenario 3: Emergency Rollback
1. Reference rollback commands in deployment guide
2. Execute: `helm rollback ai-agent-sandbox -n ai-platform`
3. Verify cluster health using monitoring commands
4. Post-mortem and root cause analysis

### Scenario 4: Multi-Cluster Deployment
1. Validate each cluster independently
2. Use cluster-specific values files in `deploy/` directory
3. Maintain separate checklist entries for each cluster
4. Follow "Scaling for Production" section for multi-cluster setup

## 📊 Readiness Matrix

| Component | Status | Verified |
|-----------|--------|----------|
| **Images** | ✅ Versioned tags | [production-deployment-guide.md](production-deployment-guide.md#-image-versions) |
| **Config** | ✅ External secrets | [production-deployment-guide.md](production-deployment-guide.md#-deployment-configuration) |
| **Web UI** | ✅ Layout fixed, React errors resolved | [production-deployment-guide.md](production-deployment-guide.md#-web-ui--frontend) |
| **Features** | ✅ All core features working | [production-deployment-guide.md](production-deployment-guide.md#-core-features-verified) |
| **Security** | ✅ Pod security contexts, RBAC ready | [production-deployment-guide.md](production-deployment-guide.md#-security--hardening) |
| **Persistence** | ✅ Database ready | [production-deployment-guide.md](production-deployment-guide.md#-persistent-state) |

## 🔐 Security Checklist

Before deploying to production, verify:

- [ ] Admin password meets complexity requirements (min 16 chars, mixed case + numbers + symbols)
- [ ] JWT secret is securely generated (32+ characters)
- [ ] No hardcoded secrets in configuration files
- [ ] Image registry credentials are secure
- [ ] Pod security contexts are non-root
- [ ] RBAC roles are properly scoped
- [ ] Network policies restrict traffic appropriately
- [ ] TLS/SSL certificates are valid
- [ ] Database backups are configured
- [ ] Secrets are encrypted at rest in etcd

## 📈 Scaling Recommendations

### Small Deployment (Development/Testing)
```yaml
operator.replicaCount: 1
apiGateway.replicas: 1
webUi.replicas: 1
resources:
  limits:
    cpu: "500m"
    memory: "512Mi"
```

### Medium Deployment (Production - Single Cluster)
```yaml
operator.replicaCount: 3
apiGateway.replicas: 3
webUi.replicas: 2
resources:
  limits:
    cpu: "1000m"
    memory: "2Gi"
```

### Large Deployment (Multi-Cluster/High Availability)
```yaml
operator.replicaCount: 5
apiGateway.replicas: 5
webUi.replicas: 3
resources:
  limits:
    cpu: "2000m"
    memory: "4Gi"
# Add HPA and pod disruption budgets
```

## 🆘 Getting Help

### Troubleshooting Resources
- See "Support & Troubleshooting" section in [production-deployment-guide.md](production-deployment-guide.md)
- See "Troubleshooting Guide" section at end of [deployment-checklist.yaml](deployment-checklist.yaml)

### Common Issues

**Issue:** Pods stuck in Pending  
**Solution:** Check node resources and pod requests in [production-deployment-guide.md](production-deployment-guide.md#scaling-for-production)

**Issue:** API returning 401 Unauthorized  
**Solution:** Verify JWT secret in [production-deployment-guide.md](production-deployment-guide.md#-security--hardening)

**Issue:** Web UI not loading  
**Solution:** Follow "Chat interface not loading" troubleshooting steps in guide

## 📞 Support Contacts

For deployment issues, escalation, or questions:
- Platform Team: platform-team@example.com
- On-Call SRE: oncall@example.com
- Escalation: platform-leads@example.com

## 📄 Document Versions

| Document | Version | Last Updated |
|----------|---------|--------------|
| production-deployment-guide.md | 1.0.0 | 2026-03-19 |
| deployment-checklist.yaml | 1.0.0 | 2026-03-19 |
| test_production_readiness.py | 1.0.0 | 2026-03-19 |
| This README | 1.0.0 | 2026-03-19 |

---

## 🎯 Next Steps

1. **Before Deployment:**
   - [ ] Run `python test_production_readiness.py`
   - [ ] Review `production-deployment-guide.md`
   - [ ] Prepare credentials and secrets
   - [ ] Get stakeholder sign-off

2. **During Deployment:**
   - [ ] Use `deployment-checklist.yaml` as your guide
   - [ ] Document all steps taken
   - [ ] Keep rollback procedures handy
   - [ ] Monitor logs and pod status

3. **After Deployment:**
   - [ ] Verify all smoke tests pass
   - [ ] Create database backup
   - [ ] Configure monitoring and alerting
   - [ ] Document any customizations
   - [ ] Schedule post-deployment review

---

**Status:** ✅ Platform Ready for Production Deployment

**Chart Version:** 0.1.0  
**Platform Version:** 1.0.0  
**Last Updated:** March 19, 2026
