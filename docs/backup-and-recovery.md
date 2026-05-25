# Backup & Disaster Recovery

KubeSynapse provides automated PostgreSQL backups and integrates with Velero for cluster-wide disaster recovery.

## Table of Contents

- [Automated Backups (CronJob)](#automated-backups-cronjob)
- [Manual Backup](#manual-backup)
- [Restore Procedure](#restore-procedure)
- [Velero Integration](#velero-integration)
- [Disaster Recovery Runbook](#disaster-recovery-runbook)

---

## Automated Backups (CronJob)

KubeSynapse ships an optional CronJob that runs `pg_dump` on a configurable schedule.

### Enabling Backups

```yaml
# values.yaml
backup:
  enabled: true
  schedule: "0 2 * * *"      # Daily at 2am UTC
  retentionCount: 7           # Keep 7 most recent backups
  backend: "pvc"              # "pvc" or "s3"
```

### Backend Options

**PVC Backend (default, simplest):**
Backups are written to a PersistentVolumeClaim. Ensure the PVC has sufficient capacity.

```yaml
backup:
  enabled: true
  backend: "pvc"
  pvcName: "kubesynapse-postgresql-backup"  # Optional; defaults to <release-name>-postgresql-backup
```

**S3 Backend (recommended for production):**
Backups are uploaded to S3-compatible object storage.

```yaml
backup:
  enabled: true
  backend: "s3"
  s3:
    bucket: "KubeSynapse-backups"
    endpoint: "https://s3.us-east-1.amazonaws.com"
    credentialsSecretName: "KubeSynapse-backup-s3"
```

Create the S3 credentials secret:
```bash
kubectl create secret generic KubeSynapse-backup-s3 \
  -n kubesynapse \
  --from-literal=access-key-id=AKIA... \
  --from-literal=secret-access-key=...
```

### Monitoring Backup Jobs

```bash
# List recent backup jobs
kubectl get jobs -n kubesynapse -l app=postgresql-backup

# View backup job logs
kubectl logs -n kubesynapse job/kubesynapse-postgresql-backup-<suffix>

# Check CronJob status
kubectl get cronjob -n kubesynapse kubesynapse-postgresql-backup
```

---

## Manual Backup

To run an ad-hoc backup:

```bash
kubectl create job --from=cronjob/kubesynapse-postgresql-backup \
  -n kubesynapse \
  manual-backup-$(date +%Y%m%d%H%M%S)

# Monitor progress
kubectl wait --for=condition=complete job/manual-backup-* -n kubesynapse --timeout=300s
kubectl logs -n kubesynapse job/manual-backup-*
```

For direct `pg_dump`:

```bash
kubectl exec -n kubesynapse kubesynapse-postgresql-0 -- \
  pg_dump -U KubeSynapse -d kubesynapse --clean --if-exists \
  | gzip > KubeSynapse-backup-$(date +%Y%m%d).sql.gz
```

---

## Restore Procedure

### From PVC Backup

1. **Identify the backup file:**
   ```bash
   kubectl exec -n kubesynapse deploy/kubesynapse-postgresql-backup \
     -- ls -la /backup/
   ```

2. **Copy the backup to the PostgreSQL pod:**
   ```bash
   BACKUP_FILE="KubeSynapse-pg-backup-20260401T020000Z.sql.gz"
   kubectl cp -n kubesynapse \
     <backup-pod>:/backup/$BACKUP_FILE \
     /tmp/$BACKUP_FILE
   ```

3. **Restore:**
   ```bash
   # Stop the API gateway and operator to prevent writes
   kubectl scale deploy -n kubesynapse kubesynapse-api-gateway --replicas=0
   kubectl scale deploy -n kubesynapse kubesynapse-operator --replicas=0

   # Restore
   gunzip -c /tmp/$BACKUP_FILE | \
     kubectl exec -i -n kubesynapse kubesynapse-postgresql-0 -- \
       psql -U kubesynapse -d kubesynapse

   # Resume services
   kubectl scale deploy -n kubesynapse kubesynapse-api-gateway --replicas=2
   kubectl scale deploy -n kubesynapse kubesynapse-operator --replicas=2
   ```

### From S3 Backup

```bash
# Download from S3
aws s3 cp s3://KubeSynapse-backups/KubeSynapse/KubeSynapse-pg-backup-20260401T020000Z.sql.gz ./

# Restore (same as above)
gunzip -c KubeSynapse-pg-backup-20260401T020000Z.sql.gz | \
  kubectl exec -i -n kubesynapse kubesynapse-postgresql-0 -- \
    psql -U kubesynapse -d kubesynapse
```

---

## Velero Integration

KubeSynapse PVCs are annotated for Velero backup discovery.

### Installing Velero

```bash
velero install \
  --provider aws \
  --bucket KubeSynapse-velero \
  --secret-file ./credentials-velero \
  --backup-location-config region=us-east-1 \
  --snapshot-location-config region=us-east-1
```

### Backing Up with Velero

Velero automatically discovers PVCs with `backup.velero.io/backup-volumes` annotations.

```bash
# Create a full namespace backup
velero backup create KubeSynapse-full --include-namespaces KubeSynapse

# Schedule daily backups
velero schedule create KubeSynapse-daily \
  --schedule="0 3 * * *" \
  --include-namespaces KubeSynapse \
  --ttl 720h0m0s

# Check backup status
velero backup describe KubeSynapse-full
velero backup logs KubeSynapse-full
```

### Restoring with Velero

```bash
# Restore entire namespace
velero restore create --from-backup KubeSynapse-full

# Restore specific resources
velero restore create --from-backup KubeSynapse-full \
  --include-resources persistentvolumeclaims,statefulsets,deployments
```

---

## Disaster Recovery Runbook

### Scenario 1: Accidental Data Deletion

1. Stop writes: scale down API gateway and operator
2. Identify the most recent good backup
3. Restore following the [Restore Procedure](#restore-procedure)
4. Resume services
5. Validate: `kubectl exec -n kubesynapse kubesynapse-postgresql-0 -- psql -U kubesynapse -c "SELECT count(*) FROM ai_agents;"`

### Scenario 2: PostgreSQL Pod Failure

1. Check StatefulSet status: `kubectl describe statefulset -n kubesynapse kubesynapse-postgresql`
2. If PVC is intact, the pod should restart automatically
3. If PVC is corrupted, restore from backup (see Restore Procedure)

### Scenario 3: Full Cluster Loss

1. Provision a new Kubernetes cluster
2. Install Velero and configure the same backup location
3. Run: `velero restore create --from-backup <latest-backup>`
4. Re-apply any external secrets or certificates
5. Verify all pods are Running: `kubectl get pods -n kubesynapse`

### Scenario 4: Cross-Region DR

1. Enable S3 cross-region replication on your backup bucket
2. In the DR region:
   ```bash
   velero install \
     --provider aws \
     --bucket KubeSynapse-dr-backups \
     --backup-location-config region=us-west-2
   velero restore create --from-backup <replicated-backup>
   ```
3. Update DNS records to point to the new cluster
4. Verify end-to-end: `curl https://api.dr.KubeSynapse.example.com/api/v1/health`

---

## Backup Validation

Regularly verify backup integrity:

```bash
# Test a backup by restoring to a temporary database
kubectl exec -n kubesynapse kubesynapse-postgresql-0 -- \
  createdb -U KubeSynapse restore_test

gunzip -c /path/to/backup.sql.gz | \
  kubectl exec -i -n kubesynapse kubesynapse-postgresql-0 -- \
    psql -U kubesynapse -d restore_test

# Verify table counts
kubectl exec -n kubesynapse kubesynapse-postgresql-0 -- \
  psql -U kubesynapse -d restore_test -c "\dt+"

# Clean up
kubectl exec -n kubesynapse kubesynapse-postgresql-0 -- \
  dropdb -U KubeSynapse restore_test
```

Add this to your monitoring schedule (weekly recommended).

---

## Configuration Reference

| Helm Value | Default | Description |
|---|---|---|
| `backup.enabled` | `false` | Enable the backup CronJob |
| `backup.schedule` | `"0 2 * * *"` | Cron schedule for automated backups |
| `backup.retentionCount` | `7` | Number of recent backups to keep |
| `backup.backend` | `"pvc"` | Storage backend (`pvc` or `s3`) |
| `backup.pvcName` | `""` | Name of the backup PVC |
| `backup.s3.bucket` | `""` | S3 bucket name |
| `backup.s3.endpoint` | `""` | S3 endpoint URL (for non-AWS providers) |
| `backup.s3.credentialsSecretName` | `""` | Secret name for S3 credentials |
