"""Sentence boundaries of a paragraph, the one rule shared by the importer, the server and the client.

Mirrors skills/earnalism-audiovisual/software/eav/text.py `sentences`: a sentence ends after `.`, `?`, `!` or the
Bengali danda, optionally followed by ONE closing mark (a quote, apostrophe, curly quote or `)`), and only when
whitespace follows; the mark stays with its sentence. eav collapses whitespace first and returns strings; this
returns character offsets into the untouched paragraph text. contracts/sentence-split-golden.json pins both.

Offsets are a partition of the paragraph (the same contiguity library.timing.validated_segments demands):
the first sentence starts at 0 (leading whitespace included), each later one starts at its first visible
character, and a sentence runs up to the next one's start, so trailing whitespace belongs to the sentence it
follows; the last ends at len(text). A blank text has no sentences.
"""
import re

_SPLIT = re.compile(r'(?<=[.?!।])\s+|(?<=[.?!।]["\'”’)])\s+')


def split_sentences(text):
    """Return [(start, end), ...] character offsets, a partition of text; [] for blank text."""
    text = text or ""
    visible_end = len(text.rstrip())
    if visible_end == 0:
        return []
    starts = [0]
    for match in _SPLIT.finditer(text):
        if match.end() < visible_end:
            starts.append(match.end())
    ends = starts[1:] + [len(text)]
    return list(zip(starts, ends))
