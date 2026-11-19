/** Resolve the complete device-license snapshot before reconciling local files. */
export async function downloadLicensePages<T>(fetchPage: (path: string) => Promise<{ items: T[]; next_cursor: string | null }>): Promise<T[]> {
  const items: T[] = [], seen = new Set<string>();
  let cursor: string | null = null;
  for (let page = 0; page < 1000; page++) {
    const result = await fetchPage('/me/downloads' + (cursor ? '?cursor=' + encodeURIComponent(cursor) : ''));
    items.push(...result.items);
    if (result.next_cursor === null) return items;
    if (!result.next_cursor || seen.has(result.next_cursor)) throw new Error('download_failed');
    seen.add(result.next_cursor); cursor = result.next_cursor;
  }
  throw new Error('download_failed');
}
