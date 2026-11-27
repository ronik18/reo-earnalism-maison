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

/** The UTF-16 range to highlight inside `text`; the whole text when the highlight is a paragraph or its offsets do not fit. */
export function highlightSpan(text: string, range: [number, number] | null): [number, number] {
  if (!range) return [0, text.length];
  const start = utf16Index(text, range[0]);
  const end = utf16Index(text, range[1]);
  return start < end ? [start, end] : [0, text.length];
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
