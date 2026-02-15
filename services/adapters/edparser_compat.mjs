#!/usr/bin/env node
// Compatibility wrapper for legacy edparser Node entrypoint.
// Keeps old "run edparser.mjs" workflows while delegating to vNext adapter.

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { spawn } from "child_process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..", "..");

const pythonBin =
  process.env.WKV_EDPARSER_PYTHON ||
  process.env.PYTHON ||
  "python";

const vnextScript =
  process.env.WKV_EDPARSER_VNEXT_SCRIPT ||
  path.resolve(__dirname, "edparser_vnext.py");

function mapLegacyEnv(env) {
  const out = { ...env };

  // Allow older variable names where they exist in legacy tooling.
  if (out.STATUS_PATH && !out.WKV_ED_STATUS_PATH) {
    out.WKV_ED_STATUS_PATH = out.STATUS_PATH;
  }
  if (out.JOURNAL_DIR && !out.WKV_ED_JOURNAL_DIR) {
    out.WKV_ED_JOURNAL_DIR = out.JOURNAL_DIR;
  }
  if (out.ED_TELEMETRY_JSON && !out.WKV_ED_TELEMETRY_OUT) {
    out.WKV_ED_TELEMETRY_OUT = out.ED_TELEMETRY_JSON;
  }
  if (out.ED_PROCESS_NAMES && !out.WKV_ED_PROCESS_NAMES) {
    out.WKV_ED_PROCESS_NAMES = out.ED_PROCESS_NAMES;
  }

  return out;
}

function log(msg) {
  process.stdout.write(`[edparser_compat] ${msg}\n`);
}

if (!fs.existsSync(vnextScript)) {
  process.stderr.write(
    `[edparser_compat] vNext script not found: ${vnextScript}\n`
  );
  process.exit(2);
}

const args = process.argv.slice(2);
const childEnv = mapLegacyEnv(process.env);

log(`Delegating to vNext adapter: ${vnextScript}`);
log(`Python: ${pythonBin}`);

const child = spawn(
  pythonBin,
  [vnextScript, ...args],
  {
    cwd: rootDir,
    stdio: "inherit",
    env: childEnv,
    windowsHide: true
  }
);

let shuttingDown = false;

function forwardSignal(signalName) {
  if (shuttingDown) return;
  shuttingDown = true;
  if (child && child.pid) {
    try {
      child.kill(signalName);
    } catch {
      // no-op
    }
  }
}

process.on("SIGINT", () => forwardSignal("SIGINT"));
process.on("SIGTERM", () => forwardSignal("SIGTERM"));

child.on("error", (err) => {
  process.stderr.write(`[edparser_compat] spawn failed: ${err.message}\n`);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.stderr.write(`[edparser_compat] exited by signal: ${signal}\n`);
    process.exit(1);
  }
  process.exit(code ?? 0);
});
