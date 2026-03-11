# Upstream Reference Repositories

This repository tracks the platform's first-party source code, Helm chart, deployment examples, and automation.

The following local clones are intentionally not part of the shared Git history:

- `tools-repos/goose`
- `tools-repos/OpenSandbox`
- `mcp-catalog`

They are useful for upstream research, API exploration, and design comparison, but they are not required to build or deploy this project because the platform integrates with published images and packages instead of importing source from those directories at runtime.

If you want the same local reference setup, recreate it after cloning this repository:

```bash
git clone git@github.com:block/goose.git tools-repos/goose
git clone git@github.com:alibaba/OpenSandbox.git tools-repos/OpenSandbox
git clone https://github.com/punkpeye/awesome-mcp-servers.git mcp-catalog
```

Notes:

- `goose-runtime/` builds from `ghcr.io/block/goose:latest`, not from a local Goose checkout.
- `agent-runtime/` integrates with the published `opensandbox` Python packages and OpenSandbox container images.
- The MCP catalog is documentation-only reference material.
