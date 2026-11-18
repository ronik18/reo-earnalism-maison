import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
import test from "node:test";
function worker() {
  const prefix = "https://assets.example.test/static/release/";
  const assets = [
    prefix + "maison/reader-ABC.js",
    prefix + "maison/app.css?v=123",
    "/en/offline/",
    "/bn/offline/",
  ];
  const requests = [],
    stored = [];
  const source = readFileSync("static/maison/offline-worker.js", "utf8")
    .replaceAll("__VERSION__", "test")
    .replace("__ASSETS__", JSON.stringify(assets))
    .replace("__ASSET_BASE__", JSON.stringify(prefix));
  const context = {
    URL,
    Set,
    Request,
    Response,
    Promise,
    self: {
      location: { origin: "https://app.example.test" },
      addEventListener() {},
    },
    caches: {
      open: async () => ({ put: async (request) => stored.push(request.url) }),
    },
    fetch: async (request) => {
      requests.push(request);
      return new Response("public fixture");
    },
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, prefix, assets, requests, stored };
}
test("Worker caches only exact configured public CDN objects, never private capabilities", () => {
  const { context, prefix } = worker();
  assert.equal(
    context.publicAsset(new URL(prefix + "maison/reader-ABC.js")),
    true,
  );
  assert.equal(
    context.publicAsset(new URL(prefix + "maison/app.css?v=123")),
    true,
  );
  for (const url of [
    prefix + "maison/app.css?v=other",
    prefix + "private.json",
    "https://evil.test/static/release/maison/reader-ABC.js",
    "https://account.r2.cloudflarestorage.com/private/book.mp3?signature=secret",
    "https://app.example.test/api/v1/media/grants",
    "https://app.example.test/en/read/book/",
  ]) {
    assert.equal(context.publicAsset(new URL(url)), false);
  }
});
test("Worker precache omits credentials and requires readable CORS responses", async () => {
  const { context, assets, requests, stored } = worker();
  await context.precache();
  assert.equal(requests.length, assets.length);
  assert.equal(stored.length, assets.length);
  for (const request of requests) {
    assert.equal(request.credentials, "omit");
    assert.equal(request.mode, "cors");
  }
  context.fetch = async () => ({ ok: true, type: "opaque" });
  await assert.rejects(() => context.precache(), /could not be verified/);
});
