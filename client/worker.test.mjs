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
  ];
  const requests = [],
    stored = [];
  const handlers = {};
  const source = readFileSync("static/maison/offline-worker.js", "utf8")
    .replaceAll("__VERSION__", "test")
    .replace("__ASSETS__", JSON.stringify(assets))
    .replace("__ASSET_BASE__", JSON.stringify(prefix));
  const context = {
    URL,
    Set,
    Request,
    Response,
    Blob,
    Promise,
    self: {
      location: { origin: "https://app.example.test" },
      addEventListener(name, handler) { handlers[name] = handler; },
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
  return { context, prefix, assets, requests, stored, handlers };
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

for (const legacy of [false, true]) {
  test(`Private offline bytes and ranges survive ${legacy ? "legacy Blob" : "ArrayBuffer"} storage`, async () => {
    const { context } = worker();
    const payload = new TextEncoder().encode("offline-audio");
    const descriptor = { asset_id: "asset", sha256: "verified", bytes: payload.byteLength };
    context.database = async () => ({ close() {} });
    context.get = async (_, store) => store === "meta"
      ? { member: "member", device_id: "device" }
      : store === "books" ? {
        member: "member", state: "ready", last_seen: Date.now(),
        license: { device_id: "device", status: "active", valid_until: new Date(Date.now()+60000).toISOString(), assets: [descriptor] },
      } : { ...descriptor, content_type: "audio/mpeg", ...(legacy ? { blob: new Blob([payload]) } : { data: payload.buffer }) };
    const url = new URL("https://app.example.test/maison-offline-assets/license/asset");
    const full = await context.privateAsset(new Request(url), url);
    assert.equal(full.status, 200);
    assert.equal(await full.text(), "offline-audio");
    const partial = await context.privateAsset(new Request(url, { headers: { Range: "bytes=2-5" } }), url);
    assert.equal(partial.status, 206);
    assert.equal(partial.headers.get("Content-Range"), "bytes 2-5/13");
    assert.equal(await partial.text(), "flin");
    const invalid = await context.privateAsset(new Request(url, { headers: { Range: "bytes=99-" } }), url);
    assert.equal(invalid.status, 416);
  });
}


test("Legacy and current offline navigation use the same English shell", async()=>{
 for (const path of ["/en/read/book/","/bn/read/book/"]) {
  const {context,handlers}=worker();let cachedPath;let pending;
  context.fetch=async()=>{throw new Error("offline fixture")};
  context.caches.match=async value=>{cachedPath=value;return new Response("English offline shell")};
  handlers.fetch({request:{url:"https://app.example.test"+path,mode:"navigate"},respondWith(value){pending=value}});
  assert.equal(await (await pending).text(),"English offline shell");
  assert.equal(cachedPath,"/en/offline/");
 }
});
