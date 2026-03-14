# CI Observability, Manual Heal, and Auto-Heal Field Requirements

## Purpose

This document defines the minimum operational data that each Configuration Item (CI) type should expose to support:

- reliable observability
- fast manual remediation
- safe and effective auto-heal workflows

The goal is to standardize the payload expected from monitoring and event-management tools so downstream systems such as Grafana, Zabbix, Splunk, ITSI, ServiceNow, event brokers, and automation engines can act on alerts without missing key context.

## Outcome

For each CI type, the monitoring payload should make it possible to answer five questions immediately:

1. What failed?
2. Where did it fail?
3. How severe is it?
4. What data is required to diagnose or heal it?
5. Is the item safe to auto-remediate?

## Core Design Principles

### 1. Every alert must identify the target unambiguously

Each alert should include a stable CI identifier and the exact affected component instance, not only a human-readable message.

### 2. Observability data must be operational, not only descriptive

Fields must support action. A message such as "disk full" is not enough if the payload does not tell us which filesystem, which host, current usage, and the threshold crossed.

### 3. Auto-heal must be gated by explicit safety metadata

Automation should not infer whether an action is allowed. The alert payload or enrichment layer should declare whether auto-heal is permitted and what script or runbook can be used.

### 4. Manual heal and auto-heal require different levels of precision

Manual response can tolerate narrative context. Auto-heal requires structured fields with deterministic names and values.

## Standard Cross-CI Field Contract

The following fields should exist for all CI types, either in the original monitoring event or via enrichment before the alert reaches automation.

| Field | Why it matters |
| --- | --- |
| `ciType` | Identifies the CI category such as service, disk, VM, interface, database, or certificate. |
| `ciId` | Stable unique identifier used by CMDB, ITSM, or automation. |
| `ciName` | Human-readable CI name. |
| `host` | Hostname or node where the issue occurred. |
| `environment` | Dev, QA, prod, pilot, or other operational scope. |
| `region` | Geographic or logical region for routing and compliance. |
| `platform` | Windows, Linux, network appliance, VMware, Azure, AWS, Kubernetes, and so on. |
| `serviceOwner` | Owning team or resolver group. |
| `severity` | Priority or impact classification. |
| `eventState` | Problem, update, recovery, resolved, suppressed, maintenance. |
| `firstSeen` | First detection timestamp. |
| `lastSeen` | Last update timestamp. |
| `alertRuleId` | Monitoring rule or trigger identity. |
| `alertSource` | Zabbix, Grafana, Splunk, Azure Monitor, SNMP, and so on. |
| `metricName` | Name of the metric or signal that breached. |
| `metricValue` | Current observed value. |
| `threshold` | Trigger threshold or comparator. |
| `correlationId` | Event grouping key across tools. |
| `runbookId` | Linked manual recovery guide. |
| `autoHealEligible` | Explicit true or false flag for automation. |
| `autoHealPolicy` | Which automation policy or script family is allowed. |
| `maintenanceFlag` | Prevents action during approved maintenance windows. |
| `changeContext` | Current change ticket, rollout, or deployment context if applicable. |

## CI Requirements Matrix

The table below lists 20 common CI types and the most important fields needed for a fully working observability and healing model.

| # | CI Type | Key observability fields | Manual heal data required | Auto-heal script inputs |
| --- | --- | --- | --- | --- |
| 1 | Service | `serviceName`, `serviceStatus`, `startupType`, `host`, `processId`, `port`, `dependencyServices`, `lastRestartTime` | recent service logs, dependent service state, recent config changes, host health, maintenance status | `host`, `serviceName`, expected state, allowed restart method, retry count, timeout, dependency order |
| 2 | Disk / Filesystem | `filesystem`, `mountPoint`, `driveLetter`, `usedPercent`, `freeBytes`, `inodePercent`, `deviceName`, `host` | top directories, growth trend, recent cleanup jobs, file handle pressure, application owner | `host`, `filesystem`, cleanup profile, threshold breached, minimum free target, exclusion paths, safe-delete mode |
| 3 | Virtual Machine | `vmName`, `powerState`, `guestState`, `cpuPercent`, `memoryPercent`, `datastore`, `hypervisor`, `host` | console reachability, recent reboot history, patch state, VM tools status, attached disks, backup state | `vmName`, virtualization platform, action type, guest credentials reference, stop-start permission, health wait timeout |
| 4 | Network Interface | `interfaceName`, `adminState`, `operState`, `speed`, `duplex`, `errorRate`, `discardRate`, `deviceName` | link peers, VLAN, recent flaps, utilization trend, change window, config drift | `deviceName`, `interfaceName`, desired admin state, bounce permission, cooldown timer, escalation threshold |
| 5 | CPU Resource | `host`, `cpuPercent`, `loadAverage`, `runQueue`, `stealTime`, `topProcesses`, `coreCount` | process offenders, recent workload change, batch window, contention source, thermal or hypervisor context | `host`, remediation profile, process kill allowlist, scale trigger, CPU threshold, observation window |
| 6 | Memory Resource | `host`, `memoryUsedPercent`, `availableMemory`, `swapUsage`, `pagingRate`, `topConsumers`, `oomEvents` | memory leak indicators, process growth trend, recent deploys, swap pressure, restart candidates | `host`, target process or service, safe restart order, free-memory threshold, memory cleanup mode |
| 7 | Process | `processName`, `processId`, `host`, `state`, `cpuPercent`, `memoryPercent`, `startTime`, `commandLine` | parent process, log path, last exit code, ownership, dependency mapping, crash frequency | `host`, `processName`, start command, stop command, credential reference, expected instance count |
| 8 | Application Endpoint | `applicationName`, `url`, `httpStatus`, `latencyMs`, `errorRate`, `availability`, `backendPool`, `environment` | synthetic check history, backend dependency status, recent releases, certificate validity, DNS health | `applicationName`, `url`, health probe, restart target, rollback option, canary status, timeout |
| 9 | Database Instance | `dbName`, `dbType`, `instanceName`, `listenerStatus`, `connections`, `replicationLag`, `storageUsed`, `host` | blocking queries, failover status, backup freshness, transaction log growth, maintenance job state | `dbName`, instance identifier, service restart permission, failover target, credential secret ref, drain mode |
| 10 | Database Listener / Port | `listenerName`, `host`, `port`, `status`, `acceptRate`, `connectionFailures`, `tlsState` | port check history, firewall changes, process binding, certificate and cipher status | `host`, `listenerName`, `port`, restart action, validation probe, rollback condition |
| 11 | Kubernetes Pod | `cluster`, `namespace`, `podName`, `podPhase`, `containerRestarts`, `node`, `image`, `readinessState` | pod events, previous logs, deployment revision, HPA state, node pressure, recent rollout | `cluster`, `namespace`, `podName` or label selector, restart policy, rollout object, grace period |
| 12 | Kubernetes Node | `cluster`, `nodeName`, `readyState`, `cpuPercent`, `memoryPercent`, `diskPressure`, `networkUnavailable` | workload placement, taints, kubelet state, node events, draining status, infrastructure health | `cluster`, `nodeName`, cordon permission, drain policy, reboot method, rejoin validation |
| 13 | Container | `containerName`, `containerId`, `image`, `exitCode`, `restartCount`, `cpuPercent`, `memoryPercent`, `host` | container logs, orchestrator state, image version, secret mounts, volume health | `containerId` or workload name, restart command, image rollback tag, health probe, timeout |
| 14 | Load Balancer / VIP | `vip`, `poolName`, `memberStatus`, `healthProbeStatus`, `failedMembers`, `latency`, `deviceName` | affected pool members, probe configuration, change history, traffic drain status | `deviceName`, `poolName`, member identifiers, enable or disable action, probe path, validation check |
| 15 | Certificate / TLS Endpoint | `certificateName`, `subject`, `issuer`, `expiryDate`, `daysToExpire`, `bindingTarget`, `thumbprint` | bound services, renewal chain, ownership, key store path, change restrictions | `certificateName`, target endpoint, renewal source, import method, restart target list, validation URL |
| 16 | Scheduled Job / Batch | `jobName`, `jobStatus`, `lastRunTime`, `lastSuccessTime`, `duration`, `exitCode`, `scheduler`, `host` | job logs, upstream dependency status, business calendar, input file status, retry history | `jobName`, scheduler target, rerun mode, business-date parameter, dependency override flag, timeout |
| 17 | Message Queue / Topic | `queueName`, `depth`, `oldestMessageAge`, `consumerLag`, `deadLetterCount`, `broker`, `host` | producer and consumer state, poison message sample, throughput trend, maintenance window | `queueName`, broker endpoint, purge or replay mode, consumer restart target, max drain batch |
| 18 | Storage Share / NAS / Object Store | `shareName`, `bucketName`, `path`, `latency`, `availability`, `capacityUsed`, `iops`, `endpoint` | mount clients, permission issues, recent quota changes, backend health, network path | `storageTarget`, path or share, reconnect method, remount option, cleanup threshold, validation probe |
| 19 | DNS Record / Resolver | `recordName`, `recordType`, `resolvedValue`, `ttl`, `resolverStatus`, `lookupLatency`, `zoneName` | authoritative server state, propagation status, recent change, dependency map | `zoneName`, `recordName`, desired value, rollback value, DNS provider target, propagation wait |
| 20 | Firewall / Security Rule / ACL | `deviceName`, `ruleName`, `policyName`, `hitCount`, `adminState`, `lastChange`, `sourceZone`, `destinationZone` | blocked flow details, related ticket, recent policy push, affected services, compliance owner | `deviceName`, `policyName`, `ruleName`, temporary override flag, expiration time, approval reference |

## Recommended Data Model Per Alert

Every actionable alert should carry four layers of information.

### A. Identification

- CI type
- CI ID
- CI name
- exact affected subcomponent
- host, node, cluster, or device name

### B. Detection Context

- metric name and current value
- threshold and comparator
- alert rule or trigger expression
- severity and impact
- first seen, last seen, and event count

### C. Operational Context

- owning team
- business service or application
- environment and region
- maintenance state
- change or deployment context
- dependencies and parent service

### D. Healing Context

- manual runbook ID
- auto-heal eligibility flag
- approved automation policy
- required script parameters
- rollback or validation criteria
- escalation path if automation fails

## Minimum Auto-Heal Safety Controls

Auto-heal should only execute when the following metadata exists and is valid.

| Control | Requirement |
| --- | --- |
| Target validation | The script can identify exactly one intended target. |
| Action approval | The CI type and resolver policy explicitly allow the action. |
| Maintenance awareness | The item is not in an active maintenance window unless approved. |
| Dependency awareness | Required upstream or downstream dependencies are known. |
| Retry policy | Maximum attempts and cooldown are defined. |
| Validation check | Post-action health verification is available. |
| Rollback rule | Reversal or escalation path exists if healing fails. |
| Auditability | Correlation ID, actor, action, and result are logged. |

## Suggested Payload Structure

```json
{
  "ciType": "service",
  "ciId": "srv-win-ops-001:Spooler",
  "ciName": "Windows Print Spooler",
  "host": "server01.example.net",
  "environment": "prod",
  "severity": "high",
  "eventState": "problem",
  "alertSource": "grafana",
  "alertRuleId": "win-service-down",
  "metricName": "service_status",
  "metricValue": "down",
  "threshold": "expected=running",
  "observability": {
    "serviceName": "Spooler",
    "startupType": "Automatic",
    "dependencyServices": ["RPCSS"],
    "lastRestartTime": "2026-03-13T08:24:00Z"
  },
  "manualHeal": {
    "runbookId": "RB-WIN-SVC-001",
    "logLocation": "C:/Windows/System32/winevt/Logs/System.evtx",
    "ownerGroup": "IT_INFRA_CLS_UNIFIED-L1_OPS"
  },
  "autoHeal": {
    "autoHealEligible": true,
    "autoHealPolicy": "restart-windows-service",
    "inputs": {
      "host": "server01.example.net",
      "serviceName": "Spooler",
      "retryCount": 2,
      "timeoutSeconds": 90
    },
    "validation": {
      "expectedState": "running",
      "checkAfterSeconds": 30
    }
  },
  "correlationId": "evt-20260313-000145"
}
```

## Implementation Guidance

### Monitoring tools should provide

- raw metric and alert-rule details
- target-specific labels such as service name, filesystem name, interface name, pod name, or queue name
- timestamps and event lifecycle state

### Enrichment layers should provide

- CI identifiers from CMDB
- owner and assignment data
- environment, platform, and business service mapping
- runbook and auto-heal policy references

### Automation platforms should require

- structured inputs only
- an explicit `autoHealEligible` gate
- post-remediation validation result
- full audit logging

## Priority Recommendation

If the implementation must be phased, start with the CI types that usually provide the fastest operational value and safest remediation profile:

1. Service
2. Disk / Filesystem
3. Process
4. Virtual Machine
5. Application Endpoint
6. Scheduled Job
7. Kubernetes Pod
8. Certificate / TLS Endpoint

## Final Recommendation

The monitoring payload contract should be treated as an integration standard, not as a dashboard convenience. If a field is required by a runbook or a healing script, it must be present as a structured attribute in the event stream and not hidden only inside free-text descriptions.

That is the difference between alerts that are visible and alerts that are actionable.