#!/usr/bin/env python3
"""Fix _core.py: restore complete imports from main_old.py while keeping routes removed."""

from pathlib import Path

WORKSPACE = Path(r"C:\Users\ahmed\OneDrive\Desktop\repos\kubesynapse\kubemininions")
CORE_PY = WORKSPACE / "api-gateway" / "_core.py"
OLD_MAIN = WORKSPACE / "api-gateway" / "main_old.py"

old_lines = OLD_MAIN.read_text(encoding="utf-8").split("\n")

# Read current _core.py (which has correct non-route code but broken imports)
core_lines = CORE_PY.read_text(encoding="utf-8").split("\n")

# Find where the "code" section starts in old main (after all imports)
# The imports end around line 170. The code section starts with helper functions.
# We want to replace the broken import section in _core.py with the full imports from old main.

# Find the first non-import, non-constant line in old main
# This is approximately where def _configure_logging() starts
code_start = 0
for i, line in enumerate(old_lines):
    if line.startswith("def _configure_logging"):
        code_start = i
        break

print(f"Old main: code starts at line {code_start + 1}")

# In _core.py, find where the imports end and code begins
core_code_start = 0
for i, line in enumerate(core_lines):
    if line.startswith("def _configure_logging"):
        core_code_start = i
        break

print(f"_core.py: code starts at line {core_code_start + 1}")

# Get the import section from old main (lines 0 to code_start - 1)
import_section = old_lines[:code_start]

# Get the code section from _core.py (lines core_code_start to end)
code_section = core_lines[core_code_start:]

# But we need to adjust: the constants after imports in old main should be kept
# Actually, let me check what _core.py has at line core_code_start
print(f"_core.py line {core_code_start}: {core_lines[core_code_start][:80]}")

# Let me also include constants defined between imports and code in old main
# Lines 144-170 have config constants and some imports
# These should already be in _core.py if the split worked correctly

# Let me look at what's in the first 200 lines of _core.py
print("\nFirst 40 lines of _core.py:")
for i in range(min(40, len(core_lines))):
    print(f"  {i+1}: {core_lines[i][:100]}")

# The problem: _core.py lines 38-51 have truncated imports
# The correct imports are in old_main.py lines 38-142
# The code at old_main line 160+ is _configure_logging

# Solution: Replace _core.py lines from after the initial imports up to _configure_logging
# with the full import block from old_main
# Actually, simpler: create _core.py as:
# 1. Initial imports (lines 1-37 of old_main are same as _core lines 1-37)
# 2. Full import block from old_main (lines 38-170)
# 3. Rest of _core.py starting from _configure_logging (line core_code_start+)

# But _core.py might have duplicate code. Let's just replace the broken import section.

# Find where _core.py's broken auth_middleware import starts and where code begins
import_start = None
import_end = None
for i, line in enumerate(core_lines):
    if "from auth_middleware import" in line and import_start is None:
        import_start = i
    if import_start is not None and line.startswith("def "):
        import_end = i
        break

print(f"\nBroken import section: lines {import_start+1} to {import_end}")

# Combine: lines 0 to import_start + full old_main imports (lines 38-170) + code from core_lines[import_end:]
new_core = (
    core_lines[:import_start] +
    old_lines[37:170] +  # lines 38-170 (0-indexed: 37-169)
    ["", ""] +  # spacing
    core_lines[import_end:]
)

new_text = "\n".join(new_core)
CORE_PY.write_text(new_text, encoding="utf-8")
print(f"\nFixed _core.py: {len(new_text)} chars, {len(new_text.split(chr(10)))} lines")
print("Done!")
