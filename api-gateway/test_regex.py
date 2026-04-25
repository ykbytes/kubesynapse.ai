import re

tests = [
    '        logger.exception("Failed to list %s: %s", plural)',
    '        logger.exception("Failed to delete %s %s: %s", label, name)',
    '        logger.exception("Failed to list policies: %s")',
    '        logger.exception("Agent invocation failed (%s): %s", agent_name)',
]

for line in tests:
    line = re.sub(r'logger\.exception\("([^"]*): %s"\)', r'logger.exception("\1")', line)
    line = re.sub(r'logger\.exception\("([^"]*): %s",\s*([^)]+)\)', r'logger.exception("\1", \2)', line)
    print(line)
