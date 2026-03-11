import subprocess
import sys


PYTHON = f'"{sys.executable}"'


def run(cmd):
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, shell=True)
    print(res.stdout)


print("FLAKE8:")
run(f"{PYTHON} -m flake8 api-gateway agent-runtime operator --max-line-length=120")

print("\nMYPY:")
run(
    f"{PYTHON} -m mypy "
    "api-gateway/main.py agent-runtime/agent_logic.py agent-runtime/guardrails.py "
    "agent-runtime/hitl.py operator/main.py operator/worker.py --ignore-missing-imports --explicit-package-bases"
)
