# Secrets Management — KubeSynapse

This guide covers three production-grade approaches for managing secrets in KubeSynapse deployments. Choose the approach that best fits your infrastructure and security requirements.

---

## Quick Comparison

| Feature | External Secrets Operator | Vault CSI Provider | Sealed Secrets |
|---------|--------------------------|-------------------|----------------|
| **How it works** | Syncs secrets from external secret manager (AWS/GCP/Azure) into K8s Secrets | Mounts secrets from HashiCorp Vault directly into pod filesystem | Encrypts secrets with cluster-specific key; safe to commit to git |
| **Secret storage** | External (cloud provider) | External (HashiCorp Vault) | Git (encrypted) |
| **Secret rotation** | Automatic (syncs from source) | Automatic (Vault lease renewal) | Manual (re-seal with new key) |
| **K8s Secret created?** | Yes (mirrors into K8s) | No (mounted as volume) | Yes (decrypted at deploy time) |
| **Complexity** | Medium | High | Low |
| **Best for** | Teams already on AWS/GCP/Azure with existing Secret Manager | Enterprises with HashiCorp Vault already deployed | Small teams, GitOps workflows, edge/air-gapped clusters |
| **KubeSynapse integration** | Reference ExternalSecret in Helm values | Reference Vault path in Helm values | Commit SealedSecret YAML to repo; decrypt with Helm |

---

## Approach 1: External Secrets Operator (ESO)

**Best for**: AWS/GCP/Azure users who already use their cloud's Secret Manager.

### Prerequisites

- Kubernetes 1.25+
- Helm 3.12+
- AWS Secrets Manager / GCP Secret Manager / Azure Key Vault (one of these)
- IAM permissions for ESO to read secrets from your cloud provider

### Step 1: Install External Secrets Operator

```bash
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets \
  --namespace external-secrets-system \
  --create-namespace
```

### Step 2: Configure Secret Store

Create a `ClusterSecretStore` that tells ESO how to access your cloud provider's secret manager.

#### AWS Secrets Manager

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: aws-secrets-manager
spec:
  provider:
    aws:
      service: SecretsManager
      region: us-east-1
      auth:
        jwt:
          serviceAccountRef:
            name: eso-reader
            namespace: external-secrets-system
```

#### GCP Secret Manager

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: gcp-secrets-manager
spec:
  provider:
    gcpsm:
      projectID: my-gcp-project
      auth:
        workloadIdentity:
          serviceAccountRef:
            name: eso-reader
            namespace: external-secrets-system
```

#### Azure Key Vault

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: azure-key-vault
spec:
  provider:
    azurekv:
      vaultUrl: "https://my-keyvault.vault.azure.net"
      authSecretRef:
        clientId:
          name: azure-secret
          key: client-id
        clientSecret:
          name: azure-secret
          key: client-secret
```

### Step 3: Create ExternalSecret for KubeSynapse

Define an `ExternalSecret` that maps cloud secrets to K8s Secrets KubeSynapse can consume.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: KubeSynapse-secrets
  namespace: KubeSynapse
spec:
  refreshInterval: "1h"  # Sync from cloud every hour
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets-manager  # or gcp-secrets-manager, azure-key-vault
  target:
    name: KubeSynapse-platform-secrets
    creationPolicy: Owner
  data:
    # Map cloud secret names → K8s secret keys
    - secretKey: OPENAI_API_KEY
      remoteRef:
        key: "/KubeSynapse/production/openai-api-key"
    - secretKey: ANTHROPIC_API_KEY
      remoteRef:
        key: "/KubeSynapse/production/anthropic-api-key"
    - secretKey: LITELLM_MASTER_KEY
      remoteRef:
        key: "/KubeSynapse/production/litellm-master-key"
    - secretKey: DATABASE_URL
      remoteRef:
        key: "/KubeSynapse/production/database-url"
```

### Step 4: Reference in Helm Values

```yaml
# deploy/values.production.yaml
platformSecrets:
  existingSecret: "KubeSynapse-platform-secrets"  # Created by ESO
```

### Verify

```bash
# Check ExternalSecret status
kubectl get externalsecret kubesynapse-secrets -n kubesynapse

# Check the generated K8s Secret
kubectl get secret kubesynapse-platform-secrets -n kubesynapse -o jsonpath='{.data}' | jq 'keys'

# Verify KubeSynapse pods are using the secret
kubectl describe pod -l app.kubernetes.io/name=kubesynapse-api-gateway -n kubesynapse | grep OPENAI_API_KEY
```

---

## Approach 2: HashiCorp Vault CSI Provider

**Best for**: Organizations with an existing HashiCorp Vault deployment.

### Prerequisites

- HashiCorp Vault cluster (v1.12+)
- Vault Kubernetes auth method configured
- Helm 3.12+

### Step 1: Install Vault CSI Provider

```bash
helm repo add hashicorp https://helm.releases.hashicorp.com
helm install vault hashicorp/vault \
  --namespace vault \
  --create-namespace \
  --set "server.enabled=false" \
  --set "injector.enabled=false" \
  --set "csi.enabled=true"
```

### Step 2: Configure Vault Kubernetes Auth

```bash
# Enable Kubernetes auth in Vault
vault auth enable kubernetes

# Configure the auth method
vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc" \
  token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"

# Create a policy for KubeSynapse
vault policy write KubeSynapse - <<EOF
path "secret/data/KubeSynapse/*" {
  capabilities = ["read"]
}
EOF

# Create a role
vault write auth/kubernetes/role/KubeSynapse \
  bound_service_account_names=kubesynapse-api-gateway-sa \
  bound_service_account_namespaces=KubeSynapse \
  policies=KubeSynapse \
  ttl=1h
```

### Step 3: Store Secrets in Vault

```bash
vault kv put secret/KubeSynapse/production \
  OPENAI_API_KEY="sk-..." \
  ANTHROPIC_API_KEY="sk-ant-..." \
  LITELLM_MASTER_KEY="secure-master-key" \
  DATABASE_URL="postgresql://..."
```

### Step 4: Create SecretProviderClass

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: KubeSynapse-vault
  namespace: KubeSynapse
spec:
  provider: vault
  parameters:
    vaultAddress: "https://vault.vault.svc:8200"
    roleName: "KubeSynapse"
    objects: |
      - secretPath: "secret/data/KubeSynapse/production"
        objectName: "openai-api-key"
        secretKey: "OPENAI_API_KEY"
      - secretPath: "secret/data/KubeSynapse/production"
        objectName: "anthropic-api-key"
        secretKey: "ANTHROPIC_API_KEY"
      - secretPath: "secret/data/KubeSynapse/production"
        objectName: "litellm-master-key"
        secretKey: "LITELLM_MASTER_KEY"
  secretObjects:
    - secretName: KubeSynapse-platform-secrets
      type: Opaque
      data:
        - objectName: openai-api-key
          key: OPENAI_API_KEY
        - objectName: anthropic-api-key
          key: ANTHROPIC_API_KEY
        - objectName: litellm-master-key
          key: LITELLM_MASTER_KEY
```

### Step 5: Reference in Pod Spec

The Vault CSI driver automatically mounts the secrets. KubeSynapse's Helm chart will detect `platformSecrets.existingSecret` and inject the environment variables from the K8s Secret.

```yaml
# deploy/values.production.yaml
platformSecrets:
  existingSecret: "KubeSynapse-platform-secrets"  # Created by Vault CSI
```

### Verify

```bash
# Check SecretProviderClass status
kubectl get secretproviderclass kubesynapse-vault -n kubesynapse

# Check the generated K8s Secret
kubectl get secret kubesynapse-platform-secrets -n kubesynapse

# Verify Vault CSI driver is running
kubectl get pods -l app=vault-csi-provider -n vault

# Test secret access from a pod
kubectl exec -it deploy/kubesynapse-api-gateway -n kubesynapse -- env | grep OPENAI_API_KEY
```

---

## Approach 3: Sealed Secrets

**Best for**: GitOps workflows, small teams, edge deployments without external secret managers.

### Prerequisites

- Helm 3.12+
- `kubeseal` CLI installed locally

### Step 1: Install Sealed Secrets Controller

```bash
helm repo add sealed-secrets https://bitnami-labs.github.io/sealed-secrets
helm install sealed-secrets sealed-secrets/sealed-secrets \
  --namespace kube-system \
  --set fullnameOverride=sealed-secrets-controller
```

### Step 2: Create a K8s Secret Locally

```bash
# Create a regular K8s Secret (do NOT commit this file)
kubectl create secret generic KubeSynapse-platform-secrets \
  --namespace kubesynapse \
  --from-literal=OPENAI_API_KEY="sk-..." \
  --from-literal=ANTHROPIC_API_KEY="sk-ant-..." \
  --from-literal=LITELLM_MASTER_KEY="secure-master-key" \
  --dry-run=client -o yaml > secret.yaml
```

### Step 3: Seal the Secret

```bash
# Seal it using the cluster's public key (safe to commit)
kubeseal --controller-name=sealed-secrets-controller \
  --controller-namespace=kube-system \
  --format yaml \
  < secret.yaml > sealed-secret.yaml

# Delete the unencrypted secret file
rm secret.yaml
```

The resulting `sealed-secret.yaml` looks like:

```yaml
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: KubeSynapse-platform-secrets
  namespace: KubeSynapse
spec:
  encryptedData:
    OPENAI_API_KEY: AgB4x...encrypted...base64...==
    ANTHROPIC_API_KEY: AgB5y...encrypted...base64...==
    LITELLM_MASTER_KEY: AgC6z...encrypted...base64...==
  template:
    metadata:
      name: KubeSynapse-platform-secrets
      namespace: KubeSynapse
```

### Step 4: Commit and Deploy

```bash
# Safe to commit — only the cluster can decrypt
git add sealed-secret.yaml
git commit -m "Add KubeSynapse platform secrets (sealed)"

# Deploy — Sealed Secrets controller automatically decrypts
kubectl apply -f sealed-secret.yaml
```

### Step 5: Reference in Helm Values

```yaml
# deploy/values.production.yaml
platformSecrets:
  existingSecret: "KubeSynapse-platform-secrets"  # Decrypted from SealedSecret
```

### Verify

```bash
# Check SealedSecret status
kubectl get sealedsecret kubesynapse-platform-secrets -n kubesynapse

# Check the decrypted K8s Secret (requires cluster access)
kubectl get secret kubesynapse-platform-secrets -n kubesynapse

# Verify KubeSynapse pods see the secret
kubectl exec -it deploy/kubesynapse-api-gateway -n kubesynapse -- env | grep OPENAI_API_KEY
```

### Rotating Secrets with Sealed Secrets

```bash
# 1. Re-create the secret with new values
kubectl create secret generic KubeSynapse-platform-secrets \
  --namespace kubesynapse \
  --from-literal=OPENAI_API_KEY="sk-new-..." \
  --dry-run=client -o yaml > secret.yaml

# 2. Re-seal
kubeseal --controller-name=sealed-secrets-controller \
  --controller-namespace=kube-system \
  --format yaml \
  < secret.yaml > sealed-secret.yaml

# 3. Apply
kubectl apply -f sealed-secret.yaml

# 4. Restart pods to pick up new values
kubectl rollout restart deployment -n kubesynapse
```

---

## KubeSynapse-Specific Secret Reference

All secrets consumed by KubeSynapse components:

| Secret Key | Component | Required | Description |
|-----------|-----------|----------|-------------|
| `OPENAI_API_KEY` | LiteLLM, Operator | If using OpenAI models | OpenAI API key for GPT models |
| `ANTHROPIC_API_KEY` | LiteLLM, Operator | If using Anthropic models | Anthropic API key for Claude models |
| `OPENROUTER_API_KEY` | LiteLLM, Operator | If using OpenRouter | OpenRouter API key for multi-provider access |
| `LITELLM_MASTER_KEY` | LiteLLM | Yes | Master key for LiteLLM admin API |
| `DATABASE_URL` | LiteLLM | Yes (if DB-backed) | PostgreSQL connection string for LiteLLM |
| `MCP_AUTH_TOKEN` | Gateway → Agent pods | If MCP auth enabled | Bearer token for MCP server authentication |
| `POSTGRES_PASSWORD` | PostgreSQL | Yes | PostgreSQL superuser password |
| `REDIS_PASSWORD` | Redis | If Redis auth enabled | Redis authentication password |

---

## Security Best Practices

1. **Never commit plaintext secrets to git.** Use Sealed Secrets or reference an external manager.
2. **Use separate secrets per environment.** Production secrets should never be accessible from dev clusters.
3. **Rotate secrets regularly.** ESO and Vault CSI support automatic rotation.
4. **Restrict secret access.** KubeSynapse's RBAC limits which SAs can read secrets (see [RBAC Matrix](rbac-matrix.md)).
5. **Audit secret access.** Enable Kubernetes audit logging for Secret reads.
6. **Use namespace isolation.** Place KubeSynapse in its own namespace and use NetworkPolicies.
