export interface StreamGrant {
  asset_id: string;
  edition_revision_id: string;
  transport: string;
  content_type: string;
  url: string;
  expires_at: string;
}
/** Accept only a fresh grant for this exact revision and approved Stream delivery. */
export function approvedStreamURL(grant: StreamGrant, assetId: string, revisionId: string, now = Date.now()): string | undefined {
  try {
    const url = new URL(grant.url);
    const expiry = Date.parse(grant.expires_at);
    if (grant.asset_id !== assetId || grant.edition_revision_id !== revisionId || grant.transport !== "stream_signed" || !["video/mp4", "application/vnd.apple.mpegurl", "application/x-mpegURL"].includes(grant.content_type) || !Number.isFinite(expiry) || expiry <= now || expiry > now + 120000 || url.protocol !== "https:" || url.username || url.password || url.port || !(url.hostname === "iframe.videodelivery.net" || /^customer-[a-z0-9]+\.cloudflarestream\.com$/.test(url.hostname))) return undefined;
    return url.href;
  } catch { return undefined; }
}

export interface AudioGrant {
  asset_id: string; edition_revision_id: string; transport: string; content_type: string;
  url: string; expires_at: string; sha256: string; duration_ms: number; quality_kbps: number;
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
