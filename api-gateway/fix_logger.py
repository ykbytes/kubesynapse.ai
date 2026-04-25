import re

path = r'C:\Users\ahmed\OneDrive\Desktop\repos\kubesynth\kubemininions\api-gateway\main.py'
with open(path, encoding='utf-8') as f:
    content = f.read()

lines = content.splitlines()
new_lines = []
for line in lines:
    if 'logger.exception(' in line and ': %s' in line:
        line = re.sub(r'logger\.exception\("([^"]*): %s"\)', r'logger.exception("\1")', line)
        line = re.sub(r'logger\.exception\("([^"]*): %s",\s*([^)]+)\)', r'logger.exception("\1", \2)', line)
    new_lines.append(line)
content = '\n'.join(new_lines)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed logger.exception format strings')
