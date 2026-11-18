import { build } from "esbuild";
import { mkdir, writeFile } from "node:fs/promises";
const outdir = "static/maison/dist";
await mkdir(outdir, { recursive: true });
const result = await build({
  entryPoints: {
    reader: "client/reader.tsx",
    quiz: "client/quiz.tsx",
    player: "client/player.tsx",
    downloads: "client/downloads.tsx",
    account: "client/account.tsx",
    shell: "client/shell.ts",
    commerce: "client/commerce.tsx",
  },
  outdir,
  bundle: true,
  splitting: true,
  format: "esm",
  target: ["es2022"],
  minify: true,
  entryNames: "[name]-[hash]",
  chunkNames: "shared-[hash]",
  metafile: true,
  define: { "process.env.NODE_ENV": '"production"' },
  legalComments: "linked",
});
const manifest = {};
for (const [file, details] of Object.entries(result.metafile.outputs))
  if (details.entryPoint) {
    const name = details.entryPoint
      .split("/")
      .pop()
      .replace(/\.tsx?$/, "");
    manifest[name] = file.replace(/^static\//, "");
  }
manifest.__assets = Object.keys(result.metafile.outputs)
  .filter((path) => path.endsWith(".js"))
  .map((path) => path.replace(/^static\//, ""));
await writeFile(
  outdir + "/manifest.json",
  JSON.stringify(manifest, null, 2) + "\n",
);
console.log(
  Object.entries(result.metafile.outputs)
    .map(([name, data]) => `${name}: ${data.bytes} bytes`)
    .join("\n"),
);
