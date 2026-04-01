# OpenCode Invoke Examples
#
# This file shows agentctl CLI commands that exercise OpenCode's native
# tool capabilities for document creation, code generation, and
# structured JSON output.
#
# Prerequisites:
#   1. An OpenCode agent deployed:
#        agentctl apply -f examples/sample-opencode-agent.yaml
#   2. A running cluster with kubesynth installed.
#
# ─── 1. Create a document ───────────────────────────────────────────

# Write a project plan Markdown document.  The agent uses the native
# `write` tool to create the file and returns the artifact path.
agentctl invoke opencode-builder \
  "Create a project plan document at /workspace/docs/plan.md that includes a title, objectives, milestones (Q1-Q4), and a risks section."

# Same request but with a persistent thread so you can ask follow-ups.
agentctl invoke opencode-builder \
  --thread-id plan-thread \
  "Create a project plan document at /workspace/docs/plan.md covering objectives, milestones, and risks."

# ─── 2. Generate code ──────────────────────────────────────────────

# Write a Python CLI application.  The agent uses `write` to create
# the files and `bash` to verify syntax.
agentctl invoke opencode-builder \
  "Create a Python CLI tool at /workspace/converter/main.py that converts CSV files to JSON.  Include argument parsing with argparse, proper error handling, and a requirements.txt."

# Generate and test: the agent writes code, runs tests with bash,
# and fixes any failures automatically (autonomous mode is on by
# default).
agentctl invoke opencode-builder \
  "Write a Go HTTP server in /workspace/server/ with endpoints GET /health and POST /echo.  Include a Dockerfile, unit tests, and run 'go test ./...' to verify."

# Request code output directly (no file creation).
agentctl invoke opencode-builder \
  --output-format code \
  "Write a JavaScript function that debounces an input callback by a given delay in milliseconds."

# ─── 3. Structured JSON output ─────────────────────────────────────

# Return a JSON analysis using OpenCode's native StructuredOutput tool.
agentctl invoke opencode-builder \
  --output-format json \
  "Analyze the /workspace directory and return a JSON object with keys: file_count (int), languages (list of strings), and has_tests (bool)."

# Return JSON conforming to a specific schema.
#   First create the schema file:
#     cat > /tmp/project-schema.json <<'EOF'
#     {
#       "type": "object",
#       "properties": {
#         "name":     { "type": "string" },
#         "version":  { "type": "string" },
#         "language": { "type": "string" },
#         "dependencies": {
#           "type": "array",
#           "items": { "type": "string" }
#         }
#       },
#       "required": ["name", "version", "language"]
#     }
#     EOF
agentctl invoke opencode-builder \
  --output-format json \
  --output-schema-file /tmp/project-schema.json \
  "Inspect the workspace and return project metadata matching the provided schema."

# ─── 4. Control autonomous behaviour ───────────────────────────────

# Limit retries and turns for cost control.
agentctl invoke opencode-builder \
  --max-retries 1 \
  --max-turns 3 \
  "Refactor /workspace/server/main.go to extract handler functions."

# Disable the autonomous retry/continuation loop entirely.
agentctl invoke opencode-builder \
  --no-autonomous \
  "List all TODO comments in the workspace."

# ─── 5. Markdown and plain-text output ─────────────────────────────

agentctl invoke opencode-builder \
  --output-format markdown \
  "Summarize the architecture of the code in /workspace/ as a Markdown document with headings, bullet points, and a mermaid diagram."

agentctl invoke opencode-builder \
  --output-format text \
  "Count the lines of code per language in the workspace."

# ─── 6. Debug and session control ──────────────────────────────────

# One-shot invocation (ephemeral session, no thread persistence).
agentctl invoke opencode-builder \
  --no-session \
  --debug \
  "Ping the OpenCode server and report the response time."

# Resume a previous thread to iterate.
agentctl invoke opencode-builder \
  --thread-id plan-thread \
  "Add a 'Budget Estimate' section to the project plan you created earlier."
