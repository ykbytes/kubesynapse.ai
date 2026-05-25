FROM node:22-slim

LABEL org.kubesynapse.runtime="pi"
LABEL org.kubesynapse.version="0.1.0"

# System dependencies for pi extensions + procps for health probes
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    procps \
    zip \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --uid 2000 --create-home piuser || useradd --uid 2000 --create-home --non-unique piuser

# Install pi-coding-agent globally (typebox is included as a dependency)
RUN npm install -g @mariozechner/pi-coding-agent@0.70.5 && \
    npm cache clean --force

# Verify installation
RUN pi --version && echo "pi installed successfully"

# Set up pi config directory
# Set up pi config directory with pre-created paths for readOnlyRootFilesystem compatibility
RUN mkdir -p /home/piuser/.pi/agent/{extensions,skills,prompts,themes,sessions} && \
    mkdir -p /workspace && \
    mkdir -p /tmp && \
    chown -R piuser:piuser /home/piuser/.pi /workspace /tmp

# Copy kubesynapse extensions
COPY --chown=piuser:piuser extensions/ /home/piuser/.pi/agent/extensions/

# Copy agent settings
COPY --chown=piuser:piuser settings.json /home/piuser/.pi/agent/settings.json

# Copy entrypoint and bridge
COPY --chown=piuser:piuser entrypoint.sh /entrypoint.sh
COPY --chown=piuser:piuser pi_bridge.js /pi_bridge.js
COPY --chown=piuser:piuser runtime_events.js /runtime_events.js
RUN chmod +x /entrypoint.sh /pi_bridge.js

WORKDIR /workspace
USER piuser

# Default environment
ENV NODE_ENV=production
ENV PI_CODING_AGENT_DIR=/home/piuser/.pi/agent
ENV PI_TELEMETRY=0

ENTRYPOINT ["/entrypoint.sh"]
