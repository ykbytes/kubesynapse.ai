#!/bin/bash
set -euo pipefail

echo "[kubesynapse-pi-runtime] Starting pi in RPC mode..."
echo "[kubesynapse-pi-runtime] Agent: ${KUBESYNAPSE_AGENT_NAME:-unknown}"
echo "[kubesynapse-pi-runtime] Provider: ${PI_PROVIDER:-auto}"
echo "[kubesynapse-pi-runtime] Model: ${PI_MODEL:-auto}"
echo "[kubesynapse-pi-runtime] Working directory: ${OPENCODE_WORKDIR:-/workspace}"

WORKDIR="${OPENCODE_WORKDIR:-/workspace}"
SESSION_DIR="${PI_CODING_AGENT_DIR}/sessions"
READY_FILE="${PI_CODING_AGENT_DIR}/.ready"

mkdir -p "$SESSION_DIR" 2>/dev/null || true

# Build auth.json from environment variables or PI_AUTH_JSON
AUTH_DIR="${PI_CODING_AGENT_DIR}"
mkdir -p "$AUTH_DIR" 2>/dev/null || true

if [ -n "${PI_AUTH_JSON:-}" ]; then
    echo "$PI_AUTH_JSON" > "$AUTH_DIR/auth.json" 2>/dev/null || true
    echo "[kubesynapse-pi-runtime] Written auth.json from PI_AUTH_JSON"
else
    # Auto-generate auth.json from kubesynapse-injected provider API keys
    node -e "
      const auth = {};
      const env = process.env;
      if (env.ANTHROPIC_API_KEY) auth.anthropic = { type: 'api_key', key: env.ANTHROPIC_API_KEY };
      if (env.AZURE_OPENAI_API_KEY) auth['azure-openai-responses'] = { type: 'api_key', key: env.AZURE_OPENAI_API_KEY };
      if (env.OPENAI_API_KEY) auth.openai = { type: 'api_key', key: env.OPENAI_API_KEY };
      if (env.DEEPSEEK_API_KEY) auth.deepseek = { type: 'api_key', key: env.DEEPSEEK_API_KEY };
      if (env.GEMINI_API_KEY) auth.google = { type: 'api_key', key: env.GEMINI_API_KEY };
      else if (env.GOOGLE_API_KEY) auth.google = { type: 'api_key', key: env.GOOGLE_API_KEY };
      if (env.MISTRAL_API_KEY) auth.mistral = { type: 'api_key', key: env.MISTRAL_API_KEY };
      if (env.GROQ_API_KEY) auth.groq = { type: 'api_key', key: env.GROQ_API_KEY };
      if (env.CEREBRAS_API_KEY) auth.cerebras = { type: 'api_key', key: env.CEREBRAS_API_KEY };
      if (env.CLOUDFLARE_API_KEY) auth['cloudflare-workers-ai'] = { type: 'api_key', key: env.CLOUDFLARE_API_KEY };
      if (env.XAI_API_KEY) auth.xai = { type: 'api_key', key: env.XAI_API_KEY };
      if (env.OPENROUTER_API_KEY) auth.openrouter = { type: 'api_key', key: env.OPENROUTER_API_KEY };
      if (env.AI_GATEWAY_API_KEY) auth['vercel-ai-gateway'] = { type: 'api_key', key: env.AI_GATEWAY_API_KEY };
      if (env.OPENCODE_API_KEY) auth.opencode = { type: 'api_key', key: env.OPENCODE_API_KEY };
      if (env.OPENCODE_GO_API_KEY) auth['opencode-go'] = { type: 'api_key', key: env.OPENCODE_GO_API_KEY };
      if (env.HF_TOKEN) auth.huggingface = { type: 'api_key', key: env.HF_TOKEN };
      if (env.FIREWORKS_API_KEY) auth.fireworks = { type: 'api_key', key: env.FIREWORKS_API_KEY };
      if (env.KIMI_API_KEY) auth['kimi-coding'] = { type: 'api_key', key: env.KIMI_API_KEY };
      if (env.MINIMAX_API_KEY) auth.minimax = { type: 'api_key', key: env.MINIMAX_API_KEY };
      if (env.MINIMAX_CN_API_KEY) auth['minimax-cn'] = { type: 'api_key', key: env.MINIMAX_CN_API_KEY };
      if (env.COHERE_API_KEY) auth.cohere = { type: 'api_key', key: env.COHERE_API_KEY };
      if (Object.keys(auth).length > 0) {
        const fs = require('fs');
        fs.writeFileSync('$AUTH_DIR/auth.json', JSON.stringify(auth, null, 2));
        console.log('[kubesynapse-pi-runtime] Written auth.json from environment variables');
      }
    " 2>/dev/null || true
fi

# Write models.json to override provider base URLs when using LiteLLM proxy
if [ -n "${OPENAI_BASE_URL:-}" ]; then
    node -e "
      const fs = require('fs');
      const path = '$AUTH_DIR/models.json';
      let config = {};
      try { config = JSON.parse(fs.readFileSync(path, 'utf8')); } catch(e) {}
      config.providers = config.providers || {};
      config.providers.openai = config.providers.openai || {};
      config.providers.openai.baseUrl = process.env.OPENAI_BASE_URL;
      fs.writeFileSync(path, JSON.stringify(config, null, 2));
      console.log('[kubesynapse-pi-runtime] Written models.json with OPENAI_BASE_URL');
    " 2>/dev/null || true
fi

if [ -n "${ANTHROPIC_BASE_URL:-}" ]; then
    node -e "
      const fs = require('fs');
      const path = '$AUTH_DIR/models.json';
      let config = {};
      try { config = JSON.parse(fs.readFileSync(path, 'utf8')); } catch(e) {}
      config.providers = config.providers || {};
      config.providers.anthropic = config.providers.anthropic || {};
      config.providers.anthropic.baseUrl = process.env.ANTHROPIC_BASE_URL;
      fs.writeFileSync(path, JSON.stringify(config, null, 2));
      console.log('[kubesynapse-pi-runtime] Written models.json with ANTHROPIC_BASE_URL');
    " 2>/dev/null || true
fi

# Write SYSTEM.md if PI_SYSTEM_PROMPT is set
if [ -n "${PI_SYSTEM_PROMPT:-}" ]; then
    echo "$PI_SYSTEM_PROMPT" > "${PI_CODING_AGENT_DIR}/SYSTEM.md" 2>/dev/null || true
    echo "[kubesynapse-pi-runtime] Written SYSTEM.md" 2>/dev/null || true
fi

# Write AGENTS.md with kubesynapse context
cat > "${PI_CODING_AGENT_DIR}/AGENTS.md" 2>/dev/null << 'AGENTSEOF' || true
# kubesynapse Agent Context

You are an AI agent running inside the kubesynapse Kubernetes AI platform.

## Platform
- You are deployed as a Kubernetes pod with resource limits and security policies.
- Your workspace is at /workspace (persistent or ephemeral depending on configuration).
- You have access to MCP (Model Context Protocol) tools configured by the platform admin.
- You may communicate with other kubesynapse agents via the KUBESYNAPSE_a2a_send tool.

## Behavior
1. Always verify your changes — read files back after writing.
2. Report full error messages, not summaries.
3. Use MCP tools for external integrations instead of curl/bash hacks when available.
4. Respect the permission level configured for this agent (check KS_PERMISSION_LEVEL).
5. Clean up temporary files and be efficient with resources.
6. Save important results to /artifacts when running in workflow context.
AGENTSEOF
echo "[kubesynapse-pi-runtime] Written AGENTS.md"

# Build the pi command
PI_CMD="pi --mode rpc"

# Session handling
if [ "${PI_NO_SESSION:-false}" = "true" ]; then
    PI_CMD="$PI_CMD --no-session"
else
    PI_CMD="$PI_CMD --session-dir $SESSION_DIR"
fi

# Provider & model
if [ -n "${PI_PROVIDER:-}" ]; then
    PI_CMD="$PI_CMD --provider ${PI_PROVIDER}"
fi

if [ -n "${PI_MODEL:-}" ]; then
    PI_CMD="$PI_CMD --model ${PI_MODEL}"
fi

# Thinking level
if [ -n "${PI_THINKING_LEVEL:-}" ]; then
    PI_CMD="$PI_CMD --thinking ${PI_THINKING_LEVEL}"
fi

# Tools configuration
if [ "${PI_NO_TOOLS:-false}" = "true" ]; then
    PI_CMD="$PI_CMD --no-tools"
elif [ -n "${PI_TOOLS:-}" ]; then
    PI_CMD="$PI_CMD --tools ${PI_TOOLS}"
fi

# Extensions
if [ -n "${PI_EXTENSIONS:-}" ]; then
    for ext in ${PI_EXTENSIONS}; do
        PI_CMD="$PI_CMD -e ${ext}"
    done
fi

# System prompt
if [ -n "${PI_SYSTEM_PROMPT:-}" ]; then
    PI_CMD="$PI_CMD --system-prompt \"${PI_SYSTEM_PROMPT}\""
fi

echo "[kubesynapse-pi-runtime] Command: $PI_CMD"

# Write ready marker for Kubernetes readiness probe
echo "ready" > "$READY_FILE" 2>/dev/null || true

# Create FIFOs for pi stdin/stdout BEFORE starting the bridge
# so the bridge can open them for reading.
PI_STDIN_FIFO="/tmp/pi-stdin"
PI_STDOUT_FIFO="/tmp/pi-stdout"
rm -f "$PI_STDIN_FIFO" "$PI_STDOUT_FIFO"
mkfifo "$PI_STDIN_FIFO"
mkfifo "$PI_STDOUT_FIFO"

# Background writer keeps the stdin FIFO open so pi's read never gets EOF
sleep infinity > "$PI_STDIN_FIFO" &
FIFO_WRITER_PID=$!

# Start pi-bridge HTTP server in background (Node.js, no extra deps)
# The bridge will read pi's stdout from /tmp/pi-stdout
echo "[kubesynapse-pi-runtime] Starting HTTP bridge on port 8080..."
node /pi_bridge.js &
BRIDGE_PID=$!
echo "[kubesynapse-pi-runtime] Bridge PID: $BRIDGE_PID"

# Give the bridge a moment to open the stdout FIFO for reading
sleep 0.5

# Trap SIGTERM for graceful shutdown
cleanup() {
    echo "[kubesynapse-pi-runtime] Received shutdown signal"
    rm -f "$READY_FILE"
    kill $BRIDGE_PID 2>/dev/null || true
    kill $FIFO_WRITER_PID 2>/dev/null || true
    wait
}

trap cleanup SIGTERM SIGINT

# Execute pi reading from stdin FIFO, writing stdout to stdout FIFO
# This avoids competition with Docker's container stdout reader
exec $PI_CMD < "$PI_STDIN_FIFO" > "$PI_STDOUT_FIFO"
