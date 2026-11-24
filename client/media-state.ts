export interface StreamGrant {
  asset_id: string;
  edition_revision_id: string;
  transport: string;
  content_type: string;
  url: string;
  expires_at: string;
  duration_ms?: number;
}
/** Accept only a fresh grant for this exact revision and approved Stream delivery. */
export function approvedStreamURL(grant: StreamGrant, assetId: string, revisionId: string, now = Date.now(), expectedHost?: string): string | undefined {
  try {
    const url = new URL(grant.url);
    const expiry = Date.parse(grant.expires_at);
    if (expectedHost !== undefined && (!/^customer-[a-z0-9]+\.cloudflarestream\.com$/.test(expectedHost) || url.hostname !== expectedHost)) return undefined;
    if (grant.asset_id !== assetId || grant.edition_revision_id !== revisionId || grant.transport !== "stream_signed" || !["video/mp4", "application/vnd.apple.mpegurl", "application/x-mpegURL"].includes(grant.content_type) || !Number.isFinite(expiry) || expiry <= now || expiry > now + 120000 || url.protocol !== "https:" || url.username || url.password || url.port || !(url.hostname === "iframe.videodelivery.net" || /^customer-[a-z0-9]+\.cloudflarestream\.com$/.test(url.hostname))) return undefined;
    return url.href;
  } catch { return undefined; }
}

export interface AudioGrant {
  asset_id: string; edition_revision_id: string; transport: string; content_type: string;
  url: string; expires_at: string; sha256: string; duration_ms: number; quality_kbps: number;
}

export interface AudioPreviewDescriptor {
  asset_id: string; edition_revision_id: string; unit_id: string; url: string;
  sha256: string; bytes: number; content_type: string; duration_ms: number; quality_kbps: number;
}
/** A public sample is a separate bounded clip, never a protected chapter URL. */
export function approvedAudioPreviewURL(preview: AudioPreviewDescriptor, revisionId: string, origin: string): string | undefined {
  try {
    const url = new URL(preview.url, origin);
    if (preview.edition_revision_id !== revisionId || !preview.asset_id || !preview.unit_id ||
        url.origin !== new URL(origin).origin || url.username || url.password || url.hash ||
        url.pathname !== `/api/v1/content/audio-previews/${preview.asset_id}` ||
        preview.content_type !== "audio/mpeg" || !/^[a-f0-9]{64}$/.test(preview.sha256) ||
        !Number.isInteger(preview.bytes) || preview.bytes < 1 || preview.bytes > 2 * 1024 * 1024 ||
        !Number.isInteger(preview.duration_ms) || preview.duration_ms < 1 || preview.duration_ms > 120000 ||
        ![48, 96].includes(preview.quality_kbps)) return undefined;
    return url.href;
  } catch { return undefined; }
}
export function approvedAudioURL(grant: AudioGrant, expected: {asset_id:string;sha256:string;duration_ms:number;quality_kbps:number}, revisionId: string, origin: string, now = Date.now()): string | undefined {
  try {
    const url = new URL(grant.url, origin), page = new URL(origin);
    const expiry = Date.parse(grant.expires_at);
    const local = grant.transport === "local_signed" && ["localhost", "127.0.0.1", "[::1]"].includes(page.hostname) && url.origin === page.origin;
    if (grant.asset_id !== expected.asset_id || grant.edition_revision_id !== revisionId || grant.sha256 !== expected.sha256 || grant.duration_ms !== expected.duration_ms || grant.quality_kbps !== expected.quality_kbps || ![48,96].includes(grant.quality_kbps) || grant.content_type !== "audio/mpeg" || !Number.isFinite(expiry) || expiry <= now || expiry > now + 120000 || url.username || url.password || !(local || (grant.transport === "r2_s3_presigned" && url.protocol === "https:"))) return undefined;
    return url.href;
  } catch { return undefined; }
}

export interface FilmGrant {
  asset_id: string; edition_revision_id: string; transport: string; content_type: string;
  url: string; expires_at: string; sha256: string; duration_ms: number;
}
/** Mirrors approvedAudioURL: exact asset/revision/bytes, at most 120 s ahead, private R2 over https or same-origin local dev. */
export function approvedFilmURL(grant: FilmGrant, expected: {asset_id:string;sha256:string;duration_ms:number}, revisionId: string, origin: string, now = Date.now()): string | undefined {
  try {
    const url = new URL(grant.url, origin), page = new URL(origin);
    const expiry = Date.parse(grant.expires_at);
    const local = grant.transport === "local_signed" && ["localhost", "127.0.0.1", "[::1]"].includes(page.hostname) && url.origin === page.origin;
    if (grant.asset_id !== expected.asset_id || grant.edition_revision_id !== revisionId || !/^[a-f0-9]{64}$/.test(grant.sha256) || grant.sha256 !== expected.sha256 || !Number.isInteger(grant.duration_ms) || grant.duration_ms <= 0 || grant.duration_ms !== expected.duration_ms || grant.content_type !== "video/mp4" || !Number.isFinite(expiry) || expiry <= now || expiry > now + 120000 || url.username || url.password || !(local || (grant.transport === "r2_s3_presigned" && url.protocol === "https:"))) return undefined;
    return url.href;
  } catch { return undefined; }
}
/** An element error renews only an expired grant, and only once at a time. */
export function shouldRenewFilm(expiresAt: string, now: number, renewing: boolean): boolean {
  const expiry = Date.parse(expiresAt);
  return !renewing && Number.isFinite(expiry) && expiry <= now;
}
export interface FilmRenewalIO {
  grant(): FilmGrant | undefined;
  renewing: {current: boolean};
  now(): number;
  request(): Promise<FilmGrant>;
  approve(grant: FilmGrant): string | undefined;
  /** Element position in seconds. */
  currentTime(): number;
  playing(): boolean;
  /** Swap the element source, seek to `at` seconds and resume when it was playing. */
  apply(url: string, grant: FilmGrant, at: number, resume: boolean): void | Promise<void>;
}
/** Replace an expired film grant and resume at the same position; false means show media_retry. */
export async function renewExpiredFilm(io: FilmRenewalIO): Promise<boolean> {
  const current = io.grant();
  if (!current || !shouldRenewFilm(current.expires_at, io.now(), io.renewing.current)) return false;
  io.renewing.current = true;
  try {
    const at = io.currentTime(), resume = io.playing();
    const next = await io.request();
    const url = io.approve(next);
    if (!url) throw new Error("media_changed");
    await io.apply(url, next, Number.isFinite(at) && at > 0 ? at : 0, resume);
    return true;
  } finally { io.renewing.current = false; }
}
