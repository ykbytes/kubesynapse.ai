import subprocess
import sys


PYTHON = f'"{sys.executable}"'


def run(cmd):
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, shell=True)
    print(res.stdout)


print("FLAKE8:")
run(f"{PYTHON} -m flake8 api-gateway opencode-runtime operator --max-line-length=120")

print("\nMYPY:")
run(
    f"{PYTHON} -m mypy "
    "api-gateway/main.py opencode-runtime/main.py opencode-runtime/hitl.py "
    "operator/main.py operator/worker.py --ignore-missing-imports --explicit-package-bases"
)
