import re

path = r'C:\Users\ahmed\OneDrive\Desktop\repos\kubesynth\kubemininions\api-gateway\main.py'
with open(path, encoding='utf-8') as f:
    content = f.read()

# 1. logger.error(..., exc) -> logger.exception(...)
lines = content.splitlines()
new_lines = []
for line in lines:
    if 'logger.error(' in line and ', exc)' in line:
        line = line.replace('logger.error(', 'logger.exception(')
        line = re.sub(r',\s*exc\)', ')', line)
    new_lines.append(line)
content = '\n'.join(new_lines)

# 2. Silent except blocks
# list_agent_pods
content = content.replace(
    '    except Exception:\n        return []\n\n\ndef list_job_pods',
    '    except Exception as exc:\n        logger.warning("Failed to list agent pods: %s", exc, exc_info=True)\n        return []\n\n\ndef list_job_pods'
)

# list_job_pods
content = content.replace(
    '    except Exception:\n        return []\n\n\ndef get_agent_status',
    '    except Exception as exc:\n        logger.warning("Failed to list job pods: %s", exc, exc_info=True)\n        return []\n\n\ndef get_agent_status'
)

# workflow recommendation
content = content.replace(
    '    except Exception:\n        return {"action": "Create a workflow", "reason": "Workflow not found."}',
    '    except Exception as exc:\n        logger.warning("Workflow recommendation lookup failed: %s", exc, exc_info=True)\n        return {"action": "Create a workflow", "reason": "Workflow not found."}'
)

# observability dashboard
content = content.replace(
    '        except Exception:\n            data[label] = []',
    '        except Exception as exc:\n            logger.warning("Failed to list %s: %s", label, exc, exc_info=True)\n            data[label] = []'
)

# croniter
content = content.replace(
    '                except Exception:\n                    nxt = None',
    '                except Exception as exc:\n                    logger.warning("Failed to parse cron expression: %s", exc, exc_info=True)\n                    nxt = None'
)

# 3. Race condition: RLock + purge_expired_a2a_tasks lock
content = content.replace(
    'A2A_TASK_STORE_LOCK = threading.Lock()',
    'A2A_TASK_STORE_LOCK = threading.RLock()'
)

content = content.replace(
    'def purge_expired_a2a_tasks() -> None:\n    cutoff = time.time() - A2A_TASK_RETENTION_SECONDS\n    stale_keys = [key for key, record in A2A_TASK_STORE.items() if float(record.get("updatedAt", 0.0)) < cutoff]\n    for key in stale_keys:\n        A2A_TASK_STORE.pop(key, None)',
    'def purge_expired_a2a_tasks() -> None:\n    with A2A_TASK_STORE_LOCK:\n        cutoff = time.time() - A2A_TASK_RETENTION_SECONDS\n        stale_keys = [key for key, record in A2A_TASK_STORE.items() if float(record.get("updatedAt", 0.0)) < cutoff]\n        for key in stale_keys:\n            A2A_TASK_STORE.pop(key, None)'
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print('main.py updated')
