/**
 * Structured JSON logger for pi-runtime.
 * Outputs one JSON object per line (Kubernetes-friendly).
 * Info/debug -> stdout, warn/error -> stderr.
 */
const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };

const LOG_LEVEL = LEVELS[process.env.RUNTIME_LOG_LEVEL] ?? LEVELS.info;

function fmt(level, component, message, extra = {}) {
  if (LEVELS[level] < LOG_LEVEL) return;
  const entry = {
    ts: new Date().toISOString(),
    level,
    component,
    msg: typeof message === "string" ? message : JSON.stringify(message),
    ...extra,
  };
  const line = JSON.stringify(entry);
  if (level === "error" || level === "warn") {
    process.stderr.write(line + "\n");
  } else {
    process.stdout.write(line + "\n");
  }
}

function logger(component) {
  return {
    debug: (msg, extra) => fmt("debug", component, msg, extra),
    info: (msg, extra) => fmt("info", component, msg, extra),
    warn: (msg, extra) => fmt("warn", component, msg, extra),
    error: (msg, extra) => fmt("error", component, msg, extra),
  };
}

module.exports = { logger };
