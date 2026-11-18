/* Public shell only. API/account/checkout/grant responses are never shared-cached. */
const CACHE = "maison-shell-__VERSION__";
const ASSETS = __ASSETS__;
const ASSET_BASE = new URL(__ASSET_BASE__, self.location.origin);
const ASSET_URLS = new Set(
  ASSETS.map((value) => new URL(value, self.location.origin).href),
);
function publicAsset(url) {
  return (
    url.origin === ASSET_BASE.origin &&
    url.pathname.startsWith(ASSET_BASE.pathname) &&
    ASSET_URLS.has(url.href)
  );
}
async function precache() {
  const cache = await caches.open(CACHE);
  await Promise.all(
    ASSETS.map(async (value) => {
      const request = new Request(new URL(value, self.location.origin), {
        credentials: "omit",
        mode: "cors",
        cache: "reload",
      });
      const response = await fetch(request);
      if (!response.ok || response.type === "opaque")
        throw new Error("Public offline shell could not be verified");
      await cache.put(request, response);
    }),
  );
}
self.addEventListener("install", (event) => event.waitUntil(precache()));
self.addEventListener("activate", (event) =>
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith("maison-shell-") && k !== CACHE)
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  ),
);
function database() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("maison-private-v1", 1);
    request.onupgradeneeded = () => {
      for (const name of ["books", "assets", "meta"])
        if (!request.result.objectStoreNames.contains(name))
          request.result.createObjectStore(name, { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function get(db, store, key) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store),
      request = tx.objectStore(store).get(key);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function privateAsset(request, url) {
  const parts = url.pathname.split("/"),
    licenseId = parts[2],
    assetId = parts[3];
  let db;
  try {
    db = await database();
    const identity = await get(db, "meta", "identity");
    if (!identity) return new Response("", { status: 401 });
    const key = identity.member + ":" + licenseId,
      book = await get(db, "books", key);
    if (
      !book ||
      book.member !== identity.member ||
      book.state !== "ready" ||
      book.license.device_id !== identity.device_id ||
      book.license.status !== "active" ||
      Date.parse(book.license.valid_until) <= Date.now() ||
      Date.now() < book.last_seen - 60000
    )
      return new Response("", { status: 403 });
    const descriptor = book.license.assets.find((a) => a.asset_id === assetId),
      saved = await get(db, "assets", key + ":" + assetId);
    if (
      !descriptor ||
      !saved ||
      saved.sha256 !== descriptor.sha256 ||
      saved.bytes !== descriptor.bytes
    )
      return new Response("", { status: 404 });
    const blob = saved.blob,
      headers = {
        "Content-Type": saved.content_type,
        "Cache-Control": "private, no-store",
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
      };
    const raw = request.headers.get("Range");
    if (!raw) {
      headers["Content-Length"] = String(blob.size);
      return new Response(blob, { headers });
    }
    const match = /^bytes=(\d*)-(\d*)$/.exec(raw);
    if (!match || (!match[1] && !match[2]))
      return new Response("", {
        status: 416,
        headers: { "Content-Range": "bytes */" + blob.size },
      });
    let start, end;
    if (!match[1]) {
      const count = Number(match[2]);
      start = Math.max(0, blob.size - count);
      end = blob.size - 1;
    } else {
      start = Number(match[1]);
      end = match[2]
        ? Math.min(Number(match[2]), blob.size - 1)
        : blob.size - 1;
    }
    if (start >= blob.size || end < start)
      return new Response("", {
        status: 416,
        headers: { "Content-Range": "bytes */" + blob.size },
      });
    headers["Content-Range"] = `bytes ${start}-${end}/${blob.size}`;
    headers["Content-Length"] = String(end - start + 1);
    return new Response(blob.slice(start, end + 1), { status: 206, headers });
  } catch {
    return new Response("", { status: 503 });
  } finally {
    db?.close();
  }
}
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (publicAsset(url)) {
    event.respondWith(
      caches
        .open(CACHE)
        .then((cache) =>
          cache
            .match(url.href, { ignoreVary: true })
            .then(
              (response) =>
                response ||
                fetch(
                  new Request(event.request, {
                    credentials: "omit",
                    mode: "cors",
                  }),
                ),
            ),
        ),
    );
    return;
  }
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/maison-offline-assets/")) {
    event.respondWith(privateAsset(event.request, url));
    return;
  }
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(
        async () =>
          (await caches.match(
            url.pathname.startsWith("/bn/") ? "/bn/offline/" : "/en/offline/",
          )) || new Response("Offline", { status: 503 }),
      ),
    );
    return;
  }
});
