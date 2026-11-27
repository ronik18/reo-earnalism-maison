export interface Position {
  format: "reader";
  unit_id: string;
  anchor_id: string;
  offset_chars: number;
}
export function codePointOffset(text: string, utf16Offset: number): number {
  return Array.from(text.slice(0, utf16Offset)).length;
}
export function samePosition(a: Position | undefined, b: Position): boolean {
  return (
    !!a &&
    a.unit_id === b.unit_id &&
    a.anchor_id === b.anchor_id &&
    a.offset_chars === b.offset_chars
  );
}
export function pageCount(
  scrollWidth: number,
  width: number,
  gap = 50,
): number {
  return width > 0
    ? Math.max(1, Math.ceil((scrollWidth + gap) / (width + gap)))
    : 1;
}
/** The sleep timer's fade-out length. */
export const FADE_MS = 15000;
/** Listening time left on a timer set after `setAtPlayedMs` of playback; only time spent playing moves it. */
export function sleepRemaining(playedMs: number, setAtPlayedMs: number, durationMs: number): number {
  if (!Number.isFinite(durationMs)) return Infinity;
  return Math.max(0, durationMs - Math.max(0, playedMs - setAtPlayedMs));
}
/** Volume multiplier: 1 until the last 15 s, then a straight ramp down to 0. */
export function fadeGain(remainingMs: number): number {
  if (Number.isNaN(remainingMs)) return 1;
  return Math.min(1, Math.max(0, remainingMs / FADE_MS));
}
/** What playback does when a part ends: "end of part" and the last part both stop; nothing jumps to another title. */
export function afterPartEnds(index: number, count: number, endOfPart: boolean): "stop" | "advance" {
  return !endOfPart && index + 1 < count ? "advance" : "stop";
}
/** mm:ss for a position in milliseconds (minutes grow past 59 rather than wrapping). */
export function clockLabel(ms: number): string {
  const total = Number.isFinite(ms) ? Math.max(0, Math.floor(ms / 1000)) : 0;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`;
}
/** "Chapter title, mm:ss" (just the time when the title is unknown). */
export function positionLabel(title: string, ms: number): string {
  return title ? `${title}, ${clockLabel(ms)}` : clockLabel(ms);
}
export interface TimingSegment {
  unit_id: string;
  anchor_id: string;
  start_ms: number;
  end_ms: number;
}
export function measuredSeek(
  segments: TimingSegment[],
  anchor: string,
  duration: number,
): number | undefined {
  if (!Number.isFinite(duration) || duration <= 0 || !segments.length) return;
  let end = 0;
  for (const s of segments) {
    if (
      !Number.isFinite(s.start_ms) ||
      !Number.isFinite(s.end_ms) ||
      s.start_ms < end ||
      s.end_ms < s.start_ms ||
      s.end_ms > duration
    )
      return;
    end = s.end_ms;
  }
  return segments.find((s) => s.anchor_id === anchor)?.start_ms;
}
export function validReturnPath(path: string, _locale = "en"): string {
  try {
    const u = new URL(path, "https://maison.invalid");
    return u.origin === "https://maison.invalid" &&
      /^\/(en|bn)\//.test(u.pathname) &&
      !/[\\\r\n]/.test(path)
      ? u.pathname.replace(/^\/bn(?=\/)/,"/en") + u.search + u.hash
      : "/en/";
  } catch {
    return "/en/";
  }
}

export function meaningfulSelection(text: string): boolean {
  return /[^\s\u200b-\u200d\ufeff]/u.test(text);
}

export interface ProgressSnapshot {
  version: number;
  location?: Position;
  last_operation_id?: string | null;
}
export function newestProgress<T extends ProgressSnapshot>(
  current: T | undefined,
  incoming: T,
): T {
  return !current || incoming.version >= current.version ? incoming : current;
}
export function progressConflictDecision(
  latest: ProgressSnapshot,
  attempted: Position | undefined,
  ownOperationIds: ReadonlySet<string>,
): "already_saved" | "retry_own" | "conflict" {
  if (attempted && samePosition(latest.location, attempted))
    return "already_saved";
  return latest.last_operation_id &&
    ownOperationIds.has(latest.last_operation_id)
    ? "retry_own"
    : "conflict";
}

const RATE_KEY = "maison.player.rate";
const clampRate = (rate: number) => (Number.isFinite(rate) ? Math.min(2, Math.max(0.75, rate)) : 1);
/** Remember the listener's playback speed on this device (0.75 to 2). */
export function rememberSpeed(rate: number): void {
  try { localStorage.setItem(RATE_KEY, String(clampRate(rate))); } catch { /* storage may be blocked */ }
}
export function recallSpeed(): number {
  try {
    const raw = localStorage.getItem(RATE_KEY);
    return raw === null ? 1 : clampRate(Number(raw));
  } catch { return 1; }
}
/** Position in seconds after skipping by `delta`, kept inside 0..duration (duration ignored when unknown). */
export function seekTarget(current: number, delta: number, duration: number): number {
  const next = Math.max(0, current + delta);
  return Number.isFinite(duration) ? Math.min(duration, next) : next;
}
export interface MediaMetadataSource { title: string; author?: string; cover_url?: string; cover_width?: number; cover_height?: number }
/** A unit with the listener's chosen rendition: same unit and title, that rendition's asset, hash, quality and length. */
export function withRendition<T extends { asset_id: string }, R extends { asset_id: string }>(unit: T, rendition: R | undefined): T & Partial<R> {
  return rendition ? { ...unit, ...rendition } : (unit as T & Partial<R>);
}
export function mediaMetadataFor(
  boot: MediaMetadataSource,
  part: { title: string },
): { title: string; artist?: string; album: string; artwork: { src: string; sizes?: string }[] } {
  const sized = Number.isInteger(boot.cover_width) && Number.isInteger(boot.cover_height) && boot.cover_width! > 0 && boot.cover_height! > 0;
  return {
    title: part.title || boot.title,
    ...(boot.author ? { artist: boot.author } : {}),
    album: boot.title,
    artwork: boot.cover_url ? [{ src: boot.cover_url, ...(sized ? { sizes: `${boot.cover_width}x${boot.cover_height}` } : {}) }] : [],
  };
}
