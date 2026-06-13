import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const dialog = readFileSync(resolve(root, "src/components/auth/ConnectionDialog.tsx"), "utf8");

const signedInBranch = /currentUser\s*\?\s*\(/.test(dialog);
const tokenInputGuarded = /!\s*currentUser[\s\S]{0,1200}id="token"/.test(dialog);

const checks = [
  ["signed-in dialog branch exists", signedInBranch],
  ["signed-in account dialog does not label a token field as API Token", !dialog.includes("API Token")],
  ["token input is only rendered from the unauthenticated connection branch", tokenInputGuarded],
  ["account trigger sanitizes shared-token identities", dialog.includes("accountDisplayLabel")],
  ["signed-in dialog exposes account and access UI", dialog.includes("Account & Access")],
];

const failed = checks.filter(([, ok]) => !ok);
if (failed.length > 0) {
  console.error("Account dialog verification failed:");
  for (const [name] of failed) {
    console.error(`- ${name}`);
  }
  process.exit(1);
}

console.log("Account dialog verification passed.");
