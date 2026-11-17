import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import { spawnSync } from "node:child_process";
await mkdir(".local", { recursive: true });
await build({
  entryPoints: ["client/state.test.ts"],
  outfile: ".local/client-tests.cjs",
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node24",
});
const result = spawnSync(
  process.execPath,
  ["--test", ".local/client-tests.cjs"],
  { stdio: "inherit" },
);
process.exitCode = result.status ?? 1;
