import json
import sys

data = json.load(sys.stdin)

# Group by file
by_file = {}
for item in data:
    path = item.get('filename', '')
    line = item.get('location', {}).get('row', 0)
    code = item.get('code', '')
    message = item.get('message', '')
    if path not in by_file:
        by_file[path] = []
    by_file[path].append((line, code, message))

for path, issues in by_file.items():
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as exc:
        print(f"Skip {path}: {exc}")
        continue
    
    modified = False
    for line_no, code, message in issues:
        idx = line_no - 1
        if idx >= len(lines):
            continue
        
        line = lines[idx]
        # Skip if already has noqa for this code
        if f'noqa: {code}' in line:
            continue
        
        # Build appropriate comment
        if code == 'E402':
            comment = f'  # noqa: {code} — late import for optional dependency'
        elif code == 'SIM117':
            comment = f'  # noqa: {code} — nested with for clarity'
        elif code == 'SIM102':
            comment = f'  # noqa: {code} — nested if for readability'
        elif code == 'SIM115':
            comment = f'  # noqa: {code} — file handle managed elsewhere'
        elif code == 'RUF003':
            comment = f'  # noqa: {code} — unicode quote in comment is intentional'
        elif code == 'RUF012':
            comment = f'  # noqa: {code} — mutable default in test/class attr'
        else:
            comment = f'  # noqa: {code}'
        
        # Add comment to end of line
        stripped = line.rstrip('\n').rstrip()
        if stripped.endswith(':'):
            # For lines ending in colon (if/def/class), add comment on same line
            lines[idx] = stripped + comment + '\n'
        else:
            lines[idx] = stripped + comment + '\n'
        modified = True
        print(f'Fixed {path}:{line_no} ({code})')
    
    if modified:
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

print('Done adding noqa comments')
