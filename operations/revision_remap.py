"""Move readers' saved positions and annotations from a replaced revision to its text correction (K1, 27 Nov 2026).

The revise stage (publish_cleared_editions) records, in the new revision's validation_evidence.source_revision,
an old -> new map for every unit and paragraph anchor (`unit_map`, `anchor_map`), like clone_revision's in-memory
anchor_map. When that revision is published (library.services.move_reader_state, called by transition_revision on
every publish path, in the publish transaction and once more after commit), remap_reader_state moves exactly the rows that still point at the
replaced revision: reader Progress locations and Annotation ranges (bookmarks, highlights, notes). Offsets follow
the text through the correction (difflib over the old and new paragraph text; a position at an insertion point
stays before the inserted text for a range end, after it for a start), then snap down to a grapheme boundary and
clamp to the new paragraph length. Rows already on the new revision, or whose anchors the map does not name,
are not touched, so a re-run moves nothing. Annotation quotes are re-read from the new text, loaded once (quote_from mirrors reader.services._range). Row versions are bumped
(so another device's stale write conflicts and refetches); updated_at is kept, so the Continue shelf order is unchanged.
"""
import difflib

from django.db.models import F



def map_offset(old, new, offset, side="start"):
    """`offset` in `old` mapped into `new`; side 'end' keeps a position at an insertion point before the insertion."""
    if old == new:
        return min(offset, len(new))
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag != "equal":
            continue
        inside = (i1 <= offset < i2) if side == "start" else (i1 < offset <= i2)
        if inside:
            return j1 + (offset - i1)
    if side == "start":  # an offset inside replaced/deleted text, or at the very end
        return len(new) if offset >= len(old) else min(offset, len(new))
    return min(offset, len(new))


def snap(text, offset):
    from reader.services import _boundary
    offset = max(0, min(offset, len(text)))
    while offset > 0 and not _boundary(text, offset):
        offset -= 1
    return offset


def quote_from(rows, by_unit, value, kind):
    """reader.services._range over preloaded paragraphs: (quote, truncated), or None where _range would refuse."""
    from reader.services import _boundary
    start, end = rows.get(value["start_anchor_id"]), rows.get(value["end_anchor_id"])
    so, eo = value["start_offset_chars"], value["end_offset_chars"]
    if (not start or not end or start[0] != value["unit_id"] or end[0] != value["unit_id"] or not _boundary(start[2], so)
            or not _boundary(end[2], eo) or (start[1], so) > (end[1], eo)):
        return None
    collapsed = value["start_anchor_id"] == value["end_anchor_id"] and so == eo
    if (kind == "bookmark") != collapsed:
        return None
    texts = by_unit[value["unit_id"]]
    parts = [texts[n][so if n == start[1] else 0:eo if n == end[1] else len(texts[n])] for n in range(start[1], end[1] + 1)]
    quote = "\n".join(parts)
    bounded = quote[:2048]
    while len(bounded.encode()) > 8192:
        bounded = bounded[:-1]
    return bounded, bounded != quote


def remap_reader_state(old_revision_id, new_revision):
    """Move reader state of `old_revision_id` onto `new_revision`; returns counts. Call inside the publish transaction."""
    from library.models import Paragraph
    from reader.models import Annotation, Progress
    record = (new_revision.validation_evidence or {}).get("source_revision") or {}
    anchors, units = record.get("anchor_map") or {}, record.get("unit_map") or {}
    counts = {"progress": 0, "annotations": 0, "left_unmapped": 0}
    if record.get("replaces_revision_id") != str(old_revision_id) or not anchors or not units:
        return counts
    old_text = {str(a): t for a, t in Paragraph.objects.filter(unit__revision_id=old_revision_id).values_list("anchor_id", "text")}
    # One read of the new text serves every quote (no per-annotation queries in the publish transaction).
    new_rows = {str(a): (str(u), n, t) for a, u, n, t in
                Paragraph.objects.filter(unit__revision=new_revision).values_list("anchor_id", "unit_id", "ordinal", "text")}
    new_text = {a: row[2] for a, row in new_rows.items()}
    by_unit = {}
    for anchor, (unit, ordinal, text) in new_rows.items():
        by_unit.setdefault(unit, {})[ordinal] = text

    def moved(anchor, offset, side):
        target = anchors[anchor]
        return target, snap(new_text[target], map_offset(old_text[anchor], new_text[target], offset, side))

    for row in Progress.objects.select_for_update().filter(revision_id=old_revision_id, format="reader"):
        loc = row.location or {}
        if (loc.get("unit_id") not in units or loc.get("anchor_id") not in anchors or type(loc.get("offset_chars")) is not int
                or loc["anchor_id"] not in old_text):
            counts["left_unmapped"] += 1
            continue
        anchor, offset = moved(loc["anchor_id"], loc["offset_chars"], "start")
        Progress.objects.filter(pk=row.pk, revision_id=old_revision_id).update(
            revision=new_revision, version=F("version") + 1,
            location={**loc, "unit_id": units[loc["unit_id"]], "anchor_id": anchor, "offset_chars": offset})
        counts["progress"] += 1
    for row in Annotation.objects.select_for_update().filter(revision_id=old_revision_id, deleted_at=None):
        value = row.range if isinstance(row.range, dict) else {}
        if (value.get("unit_id") not in units or value.get("start_anchor_id") not in old_text
                or value.get("end_anchor_id") not in old_text):
            counts["left_unmapped"] += 1
            continue
        collapsed = value["start_anchor_id"] == value["end_anchor_id"] and value["start_offset_chars"] == value["end_offset_chars"]
        start_anchor, start = moved(value["start_anchor_id"], value["start_offset_chars"], "start")
        end_anchor, end = (start_anchor, start) if collapsed else moved(value["end_anchor_id"], value["end_offset_chars"], "end")
        mapped = {**value, "unit_id": units[value["unit_id"]], "start_anchor_id": start_anchor, "start_offset_chars": start,
                  "end_anchor_id": end_anchor, "end_offset_chars": end}
        quoted = quote_from(new_rows, by_unit, mapped, row.kind)
        if quoted is None:
            counts["left_unmapped"] += 1
            continue
        quote, truncated = quoted
        Annotation.objects.filter(pk=row.pk, revision_id=old_revision_id).update(
            revision=new_revision, range=mapped, quoted_text=quote, quoted_text_truncated=truncated, version=F("version") + 1)
        counts["annotations"] += 1
    return counts
