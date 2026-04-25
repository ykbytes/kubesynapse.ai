import os

# Files to fix: test files with S106/S108
files_to_fix = [
    ('tests/test_auth_store.py', ['S106']),
    ('tests/test_main.py', ['S108']),
    ('../operator/tests/test_approval_controller.py', ['S108']),
    ('../operator/tests/test_state_store.py', ['S108']),
    ('../operator/tests/test_workflow_controller.py', ['S108']),
]

for filepath, rules in files_to_fix:
    if not os.path.exists(filepath):
        print(f'Skip {filepath}: not found')
        continue
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    modified = False
    for i, line in enumerate(lines):
        # Skip lines that already have noqa
        if 'noqa' in line:
            continue
        # Add noqa for hardcoded /tmp in strings
        if 'S108' in rules and '/tmp' in line and ('"' in line or "'" in line):
            lines[i] = line.rstrip('\n').rstrip() + '  # noqa: S108\n'
            modified = True
        # Add noqa for hardcoded password args in test files
        if 'S106' in rules and 'password=' in line.lower():
            lines[i] = line.rstrip('\n').rstrip() + '  # noqa: S106 — test fixture\n'
            modified = True
    
    if modified:
        with open(filepath, 'w') as f:
            f.writelines(lines)
        print(f'Fixed {filepath}')
    else:
        print(f'No changes needed for {filepath}')
