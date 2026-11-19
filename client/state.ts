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
export function sleepDeadline(
  minutes: number,
  now: number,
): number | undefined {
  return Number.isFinite(minutes) && minutes > 0
    ? now + minutes * 60000
    : undefined;
}
export function timerExpired(
  deadline: number | undefined,
  now: number,
): boolean {
  return deadline !== undefined && now >= deadline;
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
