export interface OfflineAsset {
  asset_id: string;
  unit_id: string;
  sha256: string;
  bytes: number;
  content_type: string;
  url: string;
  url_expires_at: string;
  piece_manifest: null | { url: string; sha256: string; bytes: number };
}
export interface License {
  license_id: string;
  edition_revision_id: string;
  content_sha256: string;
  anchor_revision: number;
  device_id: string;
  format: "reader" | "audio";
  unit_ids: string[];
  status: string;
  valid_until: string;
  assets: OfflineAsset[];
  bytes_total: number;
}
export interface LocalBook {
  key: string;
  member: string;
  license: License;
  title: string;
  locale: string;
  state: "downloading" | "ready" | "failed";
  last_seen: number;
}
const NAME = "maison-private-v1";
export function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(NAME, 1);
    request.onupgradeneeded = () => {
      for (const name of ["books", "assets", "meta"])
        if (!request.result.objectStoreNames.contains(name))
          request.result.createObjectStore(name, { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
export async function store<T>(
  name: string,
  action: (object: IDBObjectStore) => IDBRequest<T>,
  mode: IDBTransactionMode = "readonly",
): Promise<T> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction(name, mode);
      const request = action(transaction.objectStore(name));
      transaction.oncomplete = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally {
    db.close();
  }
}
export const hash = async (data: ArrayBuffer) =>
  Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", data)))
    .map((c) => c.toString(16).padStart(2, "0"))
    .join("");
export async function activeMember() {
  return (
    await store<{ key: string; member: string; device_id: string }>(
      "meta",
      (s) => s.get("identity"),
    )
  )?.member;
}
export async function setIdentity(member: string, device_id: string) {
  const old = await activeMember();
  if (old && old !== member) await purge();
  await store(
    "meta",
    (s) => s.put({ key: "identity", member, device_id }),
    "readwrite",
  );
}
export async function books(member: string): Promise<LocalBook[]> {
  return (await store<LocalBook[]>("books", (s) => s.getAll())).filter(
    (b) => b.member === member,
  );
}
export async function removeBook(book: LocalBook) {
  const db = await database();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(["books", "assets"], "readwrite");
    tx.objectStore("books").delete(book.key);
    for (const asset of book.license.assets)
      tx.objectStore("assets").delete(book.key + ":" + asset.asset_id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}
export async function purge() {
  const db = await database();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(["books", "assets", "meta"], "readwrite");
    for (const name of ["books", "assets", "meta"])
      tx.objectStore(name).clear();
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}
async function boundedFetch(
  url: string,
  bytes: number,
  expectedHash: string,
  range?: string,
): Promise<Blob> {
  const parsed = new URL(url, location.origin);
  if (parsed.protocol !== "https:" && parsed.origin !== location.origin)
    throw new Error("download_failed");
  const response = await fetch(parsed, {
    headers: range ? { Range: range } : {},
    credentials: "same-origin",
    cache: "no-store",
    referrerPolicy: "no-referrer",
  });
  if (!response.ok || (range && response.status !== 206)) {
    await response.body?.cancel();
    throw new Error("download_failed");
  }
  if (bytes > 8 * 1024 * 1024) {
    await response.body?.cancel();
    throw new Error("download_failed");
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error("download_failed");
  const parts: Uint8Array<ArrayBuffer>[] = [];
  let total = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > bytes) {
      await reader.cancel();
      throw new Error("download_integrity");
    }
    parts.push(value as Uint8Array<ArrayBuffer>);
  }
  const blob = new Blob(parts);
  if (
    total !== bytes ||
    (await hash(await blob.arrayBuffer())) !== expectedHash
  )
    throw new Error("download_integrity");
  return blob;
}
export async function download(
  member: string,
  license: License,
  title: string,
  locale: string,
  onProgress: (done: number, total: number) => void,
) {
  if (
    license.status !== "active" ||
    Date.parse(license.valid_until) <= Date.now()
  )
    throw new Error("download_expired");
  const estimate = await navigator.storage?.estimate?.();
  if (
    estimate?.quota !== undefined &&
    estimate.usage !== undefined &&
    license.bytes_total > estimate.quota - estimate.usage
  )
    throw new Error("storage_unavailable");
  const key = member + ":" + license.license_id;
  const safe = structuredClone(license);
  for (const asset of safe.assets) {
    asset.url = "";
    asset.url_expires_at = "";
    asset.piece_manifest = null;
  }
  const record: LocalBook = {
    key,
    member,
    license: safe,
    title,
    locale,
    state: "downloading",
    last_seen: Date.now(),
  };
  await store("books", (s) => s.put(record), "readwrite");
  let done = 0;
  try {
    for (const asset of license.assets) {
      let blob: Blob;
      if (license.format === "audio") {
        const descriptor = asset.piece_manifest;
        if (!descriptor) throw new Error("download_failed");
        const data = await boundedFetch(
          descriptor.url,
          descriptor.bytes,
          descriptor.sha256,
        );
        const page = JSON.parse(await data.text()) as {
          asset_id: string;
          asset_sha256: string;
          pieces: {
            piece_index: number;
            offset_bytes: number;
            bytes: number;
            sha256: string;
          }[];
        };
        if (
          page.asset_id !== asset.asset_id ||
          page.asset_sha256 !== asset.sha256 ||
          page.pieces.length > 5000
        )
          throw new Error("download_integrity");
        const chunks: Blob[] = [];
        let offset = 0;
        for (const [index, piece] of page.pieces.entries()) {
          if (
            piece.piece_index !== index ||
            piece.offset_bytes !== offset ||
            piece.bytes < 1 ||
            piece.bytes > 1048576
          )
            throw new Error("download_integrity");
          chunks.push(
            await boundedFetch(
              asset.url,
              piece.bytes,
              piece.sha256,
              `bytes=${offset}-${offset + piece.bytes - 1}`,
            ),
          );
          offset += piece.bytes;
          done += piece.bytes;
          onProgress(done, license.bytes_total);
        }
        if (offset !== asset.bytes) throw new Error("download_integrity");
        blob = new Blob(chunks, { type: asset.content_type });
      } else {
        blob = await boundedFetch(asset.url, asset.bytes, asset.sha256);
        done += asset.bytes;
        onProgress(done, license.bytes_total);
      }
      await store(
        "assets",
        (s) =>
          s.put({
            key: key + ":" + asset.asset_id,
            blob,
            sha256: asset.sha256,
            bytes: asset.bytes,
            content_type: asset.content_type,
          }),
        "readwrite",
      );
    }
    record.state = "ready";
    record.last_seen = Date.now();
    await store("books", (s) => s.put(record), "readwrite");
    return record;
  } catch (error) {
    record.state = "failed";
    await store("books", (s) => s.put(record), "readwrite");
    throw error;
  }
}
export async function openReader(
  book: LocalBook,
): Promise<{ text: string; kind: string; anchor_id: string }[]> {
  if (
    (await activeMember()) !== book.member ||
    book.state !== "ready" ||
    book.license.status !== "active" ||
    Date.parse(book.license.valid_until) <= Date.now() ||
    Date.now() < book.last_seen - 60000
  )
    throw new Error("download_expired");
  const paragraphs: { text: string; kind: string; anchor_id: string }[] = [];
  for (const asset of book.license.assets) {
    const saved = await store<{ blob: Blob; sha256: string }>("assets", (s) =>
      s.get(book.key + ":" + asset.asset_id),
    );
    if (
      !saved ||
      saved.sha256 !== asset.sha256 ||
      (await hash(await saved.blob.arrayBuffer())) !== asset.sha256
    )
      throw new Error("download_integrity");
    const document = JSON.parse(await saved.blob.text());
    if (
      document.schema_version !== 1 ||
      document.chunk_id !== asset.asset_id ||
      document.edition_revision_id !== book.license.edition_revision_id ||
      document.anchor_revision !== book.license.anchor_revision ||
      document.unit_id !== asset.unit_id
    )
      throw new Error("download_integrity");
    paragraphs.push(...document.paragraphs);
  }
  book.last_seen = Date.now();
  await store("books", (s) => s.put(book), "readwrite");
  return paragraphs;
}

export async function audioURL(book: LocalBook, assetId: string) {
  if (
    (await activeMember()) !== book.member ||
    book.state !== "ready" ||
    book.license.status !== "active" ||
    Date.parse(book.license.valid_until) <= Date.now() ||
    Date.now() < book.last_seen - 60000
  )
    throw new Error("download_expired");
  if (
    !book.license.assets.some(
      (a) => a.asset_id === assetId && a.content_type.startsWith("audio/"),
    )
  )
    throw new Error("download_failed");
  return "/maison-offline-assets/" + book.license.license_id + "/" + assetId;
}
