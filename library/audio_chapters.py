"""One validator for chapter markers [{title, start_ms}] of a unit's audio, shared by every write path."""
from core.api import DomainError
from .validation import validate_schema


def validate_chapters(chapters, duration_ms):
    """Return a list of error strings (empty when valid): non-empty, AudioChapter shape, non-blank titles,
    strictly increasing start_ms, each inside [0, duration_ms)."""
    if not isinstance(chapters, list) or not chapters:
        return ["chapters must not be empty (a list of {title, start_ms})."]
    errors, previous = [], -1
    for i, chapter in enumerate(chapters):
        try:
            validate_schema(chapter, "AudioChapter")
            valid = bool(chapter["title"].strip()) and not isinstance(chapter["start_ms"], bool) and chapter["start_ms"] >= 0
        except DomainError:
            valid = False
        if not valid:
            errors.append(f"chapters[{i}] must be {{title: non-blank text, start_ms: integer >= 0}}.")
            continue
        start = chapter["start_ms"]
        if start <= previous:
            errors.append(f"chapters[{i}].start_ms {start} is not after the previous marker ({previous}).")
        elif start >= duration_ms:
            errors.append(f"chapters[{i}].start_ms {start} is not inside the measured duration {duration_ms} ms.")
        previous = max(previous, start)
    return errors
