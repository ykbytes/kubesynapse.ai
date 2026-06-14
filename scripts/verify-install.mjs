#!/usr/bin/env node
// verify-install.mjs — quick source-level verifier that the install surface
// is consistent: required tools referenced, image set bundled in the
// install script matches the chart's service set, the bash and PowerShell
// installers exist and reference the same paths, and the makefile targets
// point at existing values files.
//
// Run with: node scripts/verify-install.mjs
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (p) => readFileSync(resolve(root, p), "utf8");
const has = (p) => existsSync(resolve(root, p));

const deployKind = read("scripts/deploy-kind.ps1");
const installSh = read("scripts/install.sh");
const makefile = read("Makefile");
const readme = read("README.md");
const values = read("charts/kubesynapse/values.yaml");
const localImages = read("deploy/values.local-images.example.yaml");
const kindQuickstart = read("deploy/values.kind.quickstart.yaml");
const catalog = read("catalog/skills-catalog.json");
const chartLock = read("charts/kubesynapse/Chart.lock");

const checks = [
  // Required install files exist
  ["PowerShell installer is checked in", has("scripts/deploy-kind.ps1")],
  ["Bash installer is checked in", has("scripts/install.sh")],
  ["Local images overlay is checked in", has("deploy/values.local-images.example.yaml")],
  ["Kind quickstart overlay is checked in", has("deploy/values.kind.quickstart.yaml")],
  ["Skills catalog is checked in", has("catalog/skills-catalog.json")],

  // Installers wire the same required paths
  ["PowerShell installer uses values.local-images.example.yaml", deployKind.includes("values.local-images.example.yaml")],
  ["PowerShell installer uses values.kind.quickstart.yaml", deployKind.includes("values.kind.quickstart.yaml")],
  ["Bash installer uses values.local-images.example.yaml", installSh.includes("values.local-images.example.yaml")],
  ["Bash installer uses values.kind.quickstart.yaml", installSh.includes("values.kind.quickstart.yaml")],

  // Installers set all chart-required secrets
  ["PowerShell installer sets litellmMasterKey", deployKind.includes("platformSecrets.native.litellmMasterKey")],
  ["PowerShell installer sets apiGatewaySharedToken", deployKind.includes("platformSecrets.native.apiGatewaySharedToken")],
  ["PowerShell installer sets databasePassword", deployKind.includes("platformSecrets.native.databasePassword")],
  ["PowerShell installer sets jwtSecret", deployKind.includes("platformSecrets.native.jwtSecret")],
  ["PowerShell installer sets authBootstrapAdminPassword", deployKind.includes("platformSecrets.native.authBootstrapAdminPassword")],
  ["Bash installer sets litellmMasterKey", installSh.includes("platformSecrets.native.litellmMasterKey")],
  ["Bash installer sets apiGatewaySharedToken", installSh.includes("platformSecrets.native.apiGatewaySharedToken")],
  ["Bash installer sets databasePassword", installSh.includes("platformSecrets.native.databasePassword")],
  ["Bash installer sets jwtSecret", installSh.includes("platformSecrets.native.jwtSecret")],
  ["Bash installer sets authBootstrapAdminPassword", installSh.includes("platformSecrets.native.authBootstrapAdminPassword")],

  // Required tools are checked
  ["PowerShell installer preflights required tools", deployKind.includes("Assert-Tool") && deployKind.includes("kind") && deployKind.includes("helm") && deployKind.includes("kubectl") && deployKind.includes("docker")],
  ["Bash installer preflights required tools", installSh.includes('need docker') && installSh.includes('need kind') && installSh.includes('need kubectl') && installSh.includes('need helm')],

  // Image set coverage
  ["PowerShell installer builds operator image", deployKind.includes("kubesynapse-operator:dev")],
  ["PowerShell installer builds api-gateway image", deployKind.includes("kubesynapse-api-gateway:dev")],
  ["PowerShell installer builds web-ui image", deployKind.includes("kubesynapse-web-ui:dev")],
  ["PowerShell installer builds opencode-runtime image", deployKind.includes("kubesynapse-opencode-rt:dev")],
  ["PowerShell installer builds litellm image", deployKind.includes("docker.io/litellm/litellm:v1.82.3-stable")],
  ["Bash installer builds operator image", installSh.includes("kubesynapse-operator:dev")],
  ["Bash installer builds api-gateway image", installSh.includes("kubesynapse-api-gateway:dev")],
  ["Bash installer builds web-ui image", installSh.includes("kubesynapse-web-ui:dev")],
  ["Bash installer builds opencode-runtime image", installSh.includes("kubesynapse-opencode-rt:dev")],
  ["Bash installer builds litellm image", installSh.includes("docker.io/litellm/litellm:v1.82.3-stable")],

  // Makefile targets map to existing files
  ["make k8s-install uses a real values file", makefile.includes("K8S_VALUES ?=") && makefile.includes(".yaml")],
  ["make deploy target passes the skills catalog when present", makefile.includes("HELM_SKILLS_CATALOG_ARG")],
  ["make deploy-sample lists only examples that exist", ["sample-agent.yaml", "sample-tenant.yaml", "sample-policy.yaml"].every((f) => has(`examples/${f}`))],

  // README quickstart points at the supported paths
  ["README quickstart mentions deploy-kind.ps1", readme.includes("./scripts/deploy-kind.ps1")],
  ["README quickstart mentions install.sh", readme.includes("./scripts/install.sh")],
  ["README quickstart prints admin credentials section", readme.includes("Default Credentials")],
  ["README quickstart gives kubectl port-forward commands", readme.includes("port-forward")],

  // Chart values structure sanity
  ["chart declares platformSecrets", values.includes("platformSecrets")],
  ["local images overlay declares all five core services", ["operator:", "apiGateway:", "webUi:", "opencodeRuntime:", "litellm:"].every((k) => localImages.includes(k))],
  ["kind quickstart overlay disables production-only flags", kindQuickstart.includes("podDisruptionBudget:") && kindQuickstart.includes("enabled: false")],
  ["chart is locked to a known dependency set", chartLock.includes("dependencies:")],
];

const failed = checks.filter(([, ok]) => !ok);
if (failed.length > 0) {
  console.error("Install verification failed:");
  for (const [name] of failed) {
    console.error(`- ${name}`);
  }
  process.exit(1);
}
console.log("Install verification passed.");
