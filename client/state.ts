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
export function sleepRemaining(
  playedMs: number,
  setAtPlayedMs: number,
  durationMs: number,
): number {
  if (!Number.isFinite(durationMs)) return Infinity;
  return Math.max(0, durationMs - Math.max(0, playedMs - setAtPlayedMs));
}
/** Volume multiplier: 1 until the last 15 s, then a straight ramp down to 0. */
export function fadeGain(remainingMs: number): number {
  if (Number.isNaN(remainingMs)) return 1;
  return Math.min(1, Math.max(0, remainingMs / FADE_MS));
}
export interface SleepTickInput {
  paused: boolean;
  ended: boolean;
  elapsedMs: number;
  playedMs: number;
  timer: { setAt: number; ms: number } | undefined;
  endOfPart: boolean;
  unitMs: number;
  currentMs: number;
  rate: number;
}
/** Longest gap one tick may add, so a system sleep or frozen tab cannot use up the timer at once. */
export const MAX_TICK_MS = 2000;
/**
 * One sleep-timer tick: listening time counts only while playing (capped per tick); a minutes timer runs on
 * that time, "end of part" on the real time left in the part (media ms / rate). "stop" returns gain 1 so the
 * caller pauses and restores the listener's volume.
 */
export function sleepTick(i: SleepTickInput): {
  playedMs: number;
  action: "none" | "fade" | "stop";
  gain: number;
} {
  const playing = !i.paused && !i.ended;
  const playedMs =
    i.playedMs +
    (playing ? Math.min(Math.max(i.elapsedMs, 0), MAX_TICK_MS) : 0);
  if (!i.endOfPart && !i.timer) return { playedMs, action: "none", gain: 1 };
  const rate = Number.isFinite(i.rate) && i.rate > 0 ? i.rate : 1;
  const left = i.endOfPart
    ? (i.unitMs - i.currentMs) / rate
    : sleepRemaining(playedMs, i.timer!.setAt, i.timer!.ms);
  if (playing && left <= 0) return { playedMs, action: "stop", gain: 1 };
  const gain = fadeGain(left);
  return { playedMs, action: gain < 1 ? "fade" : "none", gain };
}
/** Index of the marker playing at `positionMs` (the last one starting at or before it), or -1. */
export function activeMarkerIndex(
  markers: { start_ms: number }[] | undefined,
  positionMs: number,
): number {
  let found = -1;
  markers?.forEach((m, k) => {
    if (m.start_ms <= positionMs) found = k;
  });
  return found;
}
/** Where the listener is, by name: the playing marker's title when the part has markers, else the part's title. */
export function placeTitle(
  unit:
    | { title: string; markers?: { title: string; start_ms: number }[] }
    | undefined,
  positionMs: number,
): string {
  if (!unit) return "";
  const k = activeMarkerIndex(unit.markers, positionMs);
  return k >= 0 ? unit.markers![k].title : unit.title;
}
/** What playback does when a part ends: "end of part" and the last part both stop; nothing jumps to another title. */
export function afterPartEnds(
  index: number,
  count: number,
  endOfPart: boolean,
): "stop" | "advance" {
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
      ? u.pathname.replace(/^\/bn(?=\/)/, "/en") + u.search + u.hash
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
const clampRate = (rate: number) =>
  Number.isFinite(rate) ? Math.min(2, Math.max(0.75, rate)) : 1;
/** Remember the listener's playback speed on this device (0.75 to 2). */
export function rememberSpeed(rate: number): void {
  try {
    localStorage.setItem(RATE_KEY, String(clampRate(rate)));
  } catch {
    /* storage may be blocked */
  }
}
export function recallSpeed(): number {
  try {
    const raw = localStorage.getItem(RATE_KEY);
    return raw === null ? 1 : clampRate(Number(raw));
  } catch {
    return 1;
  }
}
/** Position in seconds after skipping by `delta`, kept inside 0..duration (duration ignored when unknown). */
export function seekTarget(
  current: number,
  delta: number,
  duration: number,
): number {
  const next = Math.max(0, current + delta);
  return Number.isFinite(duration) ? Math.min(duration, next) : next;
}
export interface MediaMetadataSource {
  title: string;
  author?: string;
  cover_url?: string;
  cover_width?: number;
  cover_height?: number;
}
/** A unit with the listener's chosen rendition: same unit and title, that rendition's asset, hash, quality and length. */
export function withRendition<
  T extends { asset_id: string },
  R extends { asset_id: string },
>(unit: T, rendition: R | undefined): T & Partial<R> {
  return rendition ? { ...unit, ...rendition } : (unit as T & Partial<R>);
}
export function mediaMetadataFor(
  boot: MediaMetadataSource,
  part: { title: string },
): {
  title: string;
  artist?: string;
  album: string;
  artwork: { src: string; sizes?: string }[];
} {
  const sized =
    Number.isInteger(boot.cover_width) &&
    Number.isInteger(boot.cover_height) &&
    boot.cover_width! > 0 &&
    boot.cover_height! > 0;
  return {
    title: part.title || boot.title,
    ...(boot.author ? { artist: boot.author } : {}),
    album: boot.title,
    artwork: boot.cover_url
      ? [
          {
            src: boot.cover_url,
            ...(sized
              ? { sizes: `${boot.cover_width}x${boot.cover_height}` }
              : {}),
          },
        ]
      : [],
  };
}

export type ReaderTheme = "light" | "sepia" | "dark" | "true_black";
const READER_THEMES: readonly string[] = [
  "light",
  "sepia",
  "dark",
  "true_black",
];
/** Night first: a saved theme always wins; the device's dark setting only picks the start when nothing is saved. */
export function initialReaderTheme(
  saved: string | null | undefined,
  prefersDark: boolean,
): ReaderTheme {
  if (saved && READER_THEMES.includes(saved)) return saved as ReaderTheme;
  return prefersDark ? "dark" : "light";
}

/** Share of the page scrolled, 0..1; 0 when the page does not scroll. */
export function progressFraction(
  scrollTop: number,
  scrollHeight: number,
  viewport: number,
): number {
  const range = scrollHeight - viewport;
  if (!(range > 0)) return 0;
  return Math.min(1, Math.max(0, scrollTop / range));
}

/** Whole minutes left to read, rounded up (900 characters a minute unless told otherwise). */
export function minutesRemaining(
  charsLeft: number,
  charsPerMinute = 900,
): number {
  if (!(charsLeft > 0) || !(charsPerMinute > 0)) return 0;
  return Math.ceil(charsLeft / charsPerMinute);
}

const ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  "#39": "'",
  "#x27": "'",
  nbsp: " ",
};
/** The rendered `<h2>` chapter (পরিচ্ছেদ) headings of a unit, in order, with the element id a jump targets. */
export function headingsFor(unitHtml: string): Array<{ id: string; text: string }> {
  const found: Array<{ id: string; text: string }> = [];
  for (const m of unitHtml.matchAll(/<h2\b([^>]*)>([\s\S]*?)<\/h2>/gi)) {
    const id = /\bid="([^"]*)"/.exec(m[1])?.[1];
    const text = m[2]
      .replace(/<[^>]*>/g, "")
      .replace(/&(#?\w+);/g, (all, name: string) => ENTITIES[name] ?? all)
      .replace(/\s+/g, " ")
      .trim();
    if (id && text) found.push({ id, text });
  }
  return found;
}

export const TOOLBAR_TOP_PX = 80;
export const TOOLBAR_JITTER_PX = 4;
/**
 * Should the reader toolbar be hidden after the page moved from `from` to `to`? Down past the top band hides it, up
 * shows it, a tiny move changes nothing, and it is never hidden while focus or a screen reader is inside (`pinned`).
 */
export function toolbarHidden(
  hidden: boolean,
  from: number,
  to: number,
  pinned: boolean,
): boolean {
  if (pinned || to <= TOOLBAR_TOP_PX) return false;
  const delta = to - from;
  if (delta > TOOLBAR_JITTER_PX) return true;
  if (delta < -TOOLBAR_JITTER_PX) return false;
  return hidden;
}

/** Pinned open only by keyboard focus inside the toolbar; a tap's leftover focus does not hold it. */
export function toolbarPinned(focusInside: boolean, focusVisible: boolean): boolean {
  return focusInside && focusVisible;
}

/** The reading sizes the server accepts (accounts/models.py reader_font_size constraint). */
export const READER_FONT_SIZES = [16, 20, 23, 26, 30] as const;
export type ReaderFontSize = (typeof READER_FONT_SIZES)[number];
/** One step up (+1) or down (-1) the allowed sizes, clamped at both ends; an off-list size snaps to the nearest first. */
export function stepFont(current: number, delta: number): ReaderFontSize {
  const sizes = READER_FONT_SIZES;
  const from = Number.isFinite(current) ? current : 20;
  const last = sizes.length - 1;
  let index: number;
  if (delta > 0) index = sizes.findIndex((size) => size > from);
  else index = sizes.length - 1 - [...sizes].reverse().findIndex((size) => size < from);
  if (delta > 0 && index < 0) index = last;
  if (delta < 0 && index > last) index = 0;
  if (delta === 0) index = sizes.indexOf(from as ReaderFontSize);
  return sizes[Math.min(Math.max(index, 0), last)];
}

/** Justified Bengali breaks conjuncts badly, so the choice is not offered for it. */
export function alignmentOptions(locale: string): Array<"start" | "justify"> {
  return locale === "bn" ? ["start"] : ["start", "justify"];
}
export function effectiveAlignment(value: string | undefined, locale: string): string {
  return value === "justify" && locale === "bn" ? "start" : value || "start";
}

/** Narrow / Medium / Wide are the stored compact / comfortable / wide values. */
export const READER_WIDTHS = [
  { value: "compact", label: "narrow", measure: "55ch" },
  { value: "comfortable", label: "medium", measure: "65ch" },
  { value: "wide", label: "wide", measure: "72ch" },
] as const;
export function widthMeasure(value: string | undefined): string {
  return READER_WIDTHS.find((w) => w.value === value)?.measure ?? "65ch";
}

export const PREFERENCE_SAVE_MS = 500;
/** Trailing-edge debounce that remembers only the latest value. Timer functions are injected so it can be tested. */
export function createDebouncedSaver<T>(
  save: (value: T) => void,
  ms: number,
  setTimer: (fn: () => void, ms: number) => unknown = (fn, wait) => setTimeout(fn, wait),
  clearTimer: (id: unknown) => void = (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
) {
  let timer: unknown;
  let has = false;
  return {
    schedule(value: T) {
      if (has) clearTimer(timer);
      has = true;
      timer = setTimer(() => { has = false; save(value); }, ms);
    },
    cancel() { if (has) clearTimer(timer); has = false; },
    pending: () => has,
  };
}
