/**
 * Follow-along helpers: the sentence rule shared with library/sentences.py, and the pure decisions the reader makes
 * while the audiobook narrates. No DOM here; client/follow-dom.ts applies the result.
 */

/** Same rule as library/sentences.py `split_sentences` (pinned by contracts/sentence-split-golden.json).
 * Returns [start, end) UTF-16 string indices, a partition of the text; [] for blank text.
 * The Python side counts code points; the two agree for text without astral characters (all of Bengali). */
const SPLIT = /(?<=[.?!।])\s+|(?<=[.?!।]["'”’)])\s+/gu;
export function splitSentences(text: string): Array<[number, number]> {
  const visibleEnd = text.trimEnd().length;
  if (visibleEnd === 0) return [];
  const starts = [0];
  for (const match of text.matchAll(SPLIT)) {
    const end = match.index + match[0].length;
    if (end < visibleEnd) starts.push(end);
  }
  return starts.map((start, i): [number, number] => [start, i + 1 < starts.length ? starts[i + 1] : text.length]);
}

/** A code-point offset (what the API and the database store) as a UTF-16 index into `text`. Clamped to the text. */
export function utf16Index(text: string, codePoints: number): number {
  let index = 0;
  for (let seen = 0; seen < codePoints && index < text.length; seen++) {
    index += (text.codePointAt(index) ?? 0) > 0xffff ? 2 : 1;
  }
  return index;
}

export interface FollowSegment {
  anchor_id: string;
  start_ms: number;
  end_ms: number;
  start_offset_chars: number;
  end_offset_chars: number;
  sentence_index?: number;
}
export interface FollowMap {
  asset_id?: string;
  segments: FollowSegment[];
}
export interface Highlight {
  anchorId: string | null;
  /** [start, end) in code points of the paragraph text, or null when the whole paragraph is the unit. */
  range: [number, number] | null;
}

/**
 * What the narration is on at `ms`. A sentence segment (it carries `sentence_index`) gives its range; a paragraph
 * segment, in a paragraph map or in the unmeasured anchors of a sentence map, gives range null and the whole
 * paragraph is highlighted. `anchorId` is the paragraph already highlighted: its segments are tried first so a
 * boundary does not flicker. Returns anchorId null when no segment holds `ms` (before the first, a silent gap).
 */
export function currentHighlight(maps: readonly FollowMap[], anchorId: string | null, ms: number): Highlight {
  const holds = (s: FollowSegment) => s.start_ms <= ms && ms < s.end_ms;
  const found =
    (anchorId ? maps.flatMap((m) => m.segments).find((s) => s.anchor_id === anchorId && holds(s)) : undefined) ??
    maps.flatMap((m) => m.segments).find(holds);
  if (!found) return { anchorId: null, range: null };
  const sentence = found.sentence_index !== undefined && found.end_offset_chars > found.start_offset_chars;
  return { anchorId: found.anchor_id, range: sentence ? [found.start_offset_chars, found.end_offset_chars] : null };
}

/**
 * A stored-text offset (code points, as library/sentences.py counts with Python len) as a code-point offset into the
 * text the HTML parser left in the page. The parser turns each CRLF into one LF (a lone CR into one LF too, same
 * length), so every CRLF before the offset counts one less. `crlf` holds the stored code-point index of each CR that
 * starts a CRLF (the reader bootstrap's `crlf[anchor]`); an offset between that CR and its LF lands on the LF.
 */
export function domOffset(codePoints: number, crlf: readonly number[] = []): number {
  let before = 0;
  for (const cr of crlf) if (cr < codePoints) before++;
  return codePoints - before;
}

/**
 * The UTF-16 range to highlight inside `text` (the page text); the whole text when the highlight is a paragraph or
 * its offsets do not fit. `range` is in stored-text code points; `crlf` maps them past the parser's CRLF folding.
 */
export function highlightSpan(text: string, range: [number, number] | null, crlf: readonly number[] = []): [number, number] {
  if (!range) return [0, text.length];
  const start = utf16Index(text, domOffset(range[0], crlf));
  const end = utf16Index(text, domOffset(range[1], crlf));
  return start < end ? [start, end] : [0, text.length];
}

/** Stored code-point index of each CR that starts a CRLF in `text` (the server-side rule, for tests and fixtures). */
export function crlfIndexes(text: string): number[] {
  const found: number[] = [];
  const chars = Array.from(text);
  chars.forEach((c, i) => { if (c === "\r" && chars[i + 1] === "\n") found.push(i); });
  return found;
}

/**
 * Follow-along scrolling: how far (px, positive is down) to scroll so the highlighted `box` sits in the middle of the
 * visible band `view` (viewport y from below the toolbar to above a docked player); 0 when it is already inside.
 * A box taller than the band is brought to the band's top.
 */
export function followScrollDelta(box: { top: number; bottom: number }, view: { top: number; bottom: number }): number {
  if (box.top >= view.top && box.bottom <= view.bottom) return 0;
  if (box.bottom - box.top >= view.bottom - view.top) return Math.round(box.top - view.top);
  return Math.round((box.top + box.bottom) / 2 - (view.top + view.bottom) / 2);
}

const SCROLL_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "PageUp", "PageDown", "Home", "End", " "]);
/** The reader's own scrolling raises `scroll` events for this long (ms) after it scrolls. */
export const OWN_SCROLL_MS = 400;
/**
 * Is this event the reader scrolling by hand? Wheel, touch, scroll keys and the page-turn buttons are; a `scroll`
 * event is too (scrollbar drag, keyboard, find-in-page) unless it falls inside the window after the reader's own
 * scroll (`ownScrollUntil`, a timestamp). Other keys and events are not.
 */
export function isUserScroll(type: string, key: string | undefined, now: number, ownScrollUntil: number): boolean {
  if (type === "wheel" || type === "touchmove" || type === "page-button") return true;
  if (type === "keydown") return key !== undefined && SCROLL_KEYS.has(key);
  if (type === "scroll") return now > ownScrollUntil;
  return false;
}

export const MAP_RETRY_MS = 30_000;
export const MAP_RETRY_MAX_MS = 300_000;
/** A mappings fetch that failed: when, and how many times in a row. */
export interface MapFailure { failedAt: number; failures: number }
export type MapEntry = "loading" | MapFailure | { maps: unknown[] | null };
const isFailure = (e: MapEntry): e is MapFailure => typeof e === "object" && "failures" in e;
export function mapFailed(previous: MapEntry | undefined, now: number): MapFailure {
  return { failedAt: now, failures: previous && isFailure(previous) ? previous.failures + 1 : 1 };
}
/** What to do on a playback event: fetch, wait (loading, or backing off after a failure: 30 s doubling to 5 min), or use the maps. */
export function mapFetchPlan(entry: MapEntry | undefined, now: number): "fetch" | "wait" | "use" {
  if (entry === undefined) return "fetch";
  if (entry === "loading") return "wait";
  if (!isFailure(entry)) return "use";
  const wait = Math.min(MAP_RETRY_MS * 2 ** (entry.failures - 1), MAP_RETRY_MAX_MS);
  return now - entry.failedAt >= wait ? "fetch" : "wait";
}

export const AUTOSCROLL_PAUSE_MS = 5000;
/** Follow with scrolling only when the reader has not scrolled by hand in the last 5 seconds. */
export function autoscrollAllowed(now: number, lastUserScrollAt: number | undefined): boolean {
  return lastUserScrollAt === undefined || now - lastUserScrollAt >= AUTOSCROLL_PAUSE_MS;
}

/** The persistent player announces where it is; the reader and any other island listens. */
export const PLAYBACK_EVENT = "maison:playback";
export const PLAYBACK_REQUEST_EVENT = "maison:playback-request";
export interface PlaybackDetail {
  edition_id: string;
  unit_id: string;
  asset_id: string;
  ms: number;
  playing: boolean;
  /** True when the player was closed: nothing is being followed. */
  closed?: boolean;
}
