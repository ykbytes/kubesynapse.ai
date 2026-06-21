import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const detailPath = resolve(here, "../src/components/mcp/McpServerDetail.tsx");
const registryPath = resolve(here, "../src/components/mcp/McpRegistryTab.tsx");
const detailSource = readFileSync(detailPath, "utf8");
const registrySource = readFileSync(registryPath, "utf8");

const checks = [
  {
    name: "MCP server detail uses centered dialog primitives",
    pass:
      detailSource.includes("from \"@/components/ui/dialog\"") &&
      detailSource.includes("DialogContent") &&
      detailSource.includes("<Dialog open={!!server}"),
  },
  {
    name: "MCP server detail no longer renders a right-side sheet",
    pass:
      !detailSource.includes("from \"@/components/ui/sheet\"") &&
      !detailSource.includes("<Sheet") &&
      !detailSource.includes("SheetContent"),
  },
  {
    name: "MCP registry documents the detail modal contract",
    pass: registrySource.includes("Detail modal"),
  },
];

const failures = checks.filter((check) => !check.pass);
if (failures.length > 0) {
  console.error("MCP UI contract checks failed:");
  for (const failure of failures) {
    console.error(`- ${failure.name}`);
  }
  process.exit(1);
}

console.log("MCP UI contract checks passed.");
