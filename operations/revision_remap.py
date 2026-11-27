"""Move readers' saved positions and annotations from a replaced revision to its text correction (K1, 27 Nov 2026).

The revise stage (publish_cleared_editions) records, in the new revision's validation_evidence.source_revision,
an old -> new map for every unit and paragraph anchor (`unit_map`, `anchor_map`), like clone_revision's in-memory
anchor_map. When that revision is published, remap_reader_state moves exactly the rows that still point at the
replaced revision: reader Progress locations and Annotation ranges (bookmarks, highlights, notes). Offsets follow
the text through the correction (difflib over the old and new paragraph text; a position at an insertion point
stays before the inserted text for a range end, after it for a start), then snap down to a grapheme boundary and
clamp to the new paragraph length. Rows already on the new revision, or whose anchors the map does not name,
are not touched, so a re-run moves nothing. Annotation quotes are re-read from the new text. Row versions are bumped
(so another device's stale write conflicts and refetches); updated_at is kept, so the Continue shelf order is unchanged.
"""
import difflib

from django.db.models import F

from core.api import DomainError


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


def remap_reader_state(old_revision_id, new_revision):
    """Move reader state of `old_revision_id` onto `new_revision`; returns counts. Call inside the publish transaction."""
    from library.models import Paragraph
    from reader.models import Annotation, Progress
    from reader.services import _range
    record = (new_revision.validation_evidence or {}).get("source_revision") or {}
    anchors, units = record.get("anchor_map") or {}, record.get("unit_map") or {}
    counts = {"progress": 0, "annotations": 0, "left_unmapped": 0}
    if record.get("replaces_revision_id") != str(old_revision_id) or not anchors or not units:
        return counts
    old_text = {str(a): t for a, t in Paragraph.objects.filter(unit__revision_id=old_revision_id).values_list("anchor_id", "text")}
    new_text = {str(a): t for a, t in Paragraph.objects.filter(unit__revision=new_revision).values_list("anchor_id", "text")}

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
        try:
            mapped, quote, truncated = _range(new_revision, mapped, row.kind)
        except DomainError:
            counts["left_unmapped"] += 1
            continue
        Annotation.objects.filter(pk=row.pk, revision_id=old_revision_id).update(
            revision=new_revision, range=mapped, quoted_text=quote, quoted_text_truncated=truncated, version=F("version") + 1)
        counts["annotations"] += 1
    return counts
