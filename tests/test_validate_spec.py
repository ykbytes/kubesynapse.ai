import yaml, sys, json

with open('opencode-runtime/openapi.yaml', encoding='utf-8') as f:
    spec = yaml.safe_load(f)

assert spec['openapi'] == '3.1.0', 'Bad openapi version'
assert 'paths' in spec, 'Missing paths'
assert 'components' in spec, 'Missing components'

paths = list(spec['paths'].keys())
schemas = list(spec['components']['schemas'].keys())

ov = spec['openapi']
title = spec['info']['title']
print(f'OpenAPI version: {ov}')
print(f'Title: {title}')
print(f'Paths ({len(paths)}): {json.dumps(paths, indent=2)}')
print(f'Schemas ({len(schemas)}): {json.dumps(schemas, indent=2)}')

def find_refs(obj, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == '$ref' and isinstance(v, str):
                yield (path, v)
            else:
                yield from find_refs(v, f'{path}/{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from find_refs(v, f'{path}[{i}]')

broken = []
for location, ref in find_refs(spec):
    parts = ref.lstrip('#/').split('/')
    target = spec
    for part in parts:
        if isinstance(target, dict) and part in target:
            target = target[part]
        else:
            broken.append((location, ref))
            break

if broken:
    print('BROKEN REFS:')
    for loc, ref in broken:
        print(f'  {loc} -> {ref}')
    sys.exit(1)
else:
    print('All $ref targets resolve correctly')

print('VALIDATION PASSED')
