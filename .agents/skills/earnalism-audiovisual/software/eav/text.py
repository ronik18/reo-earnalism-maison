"""Text helpers: sentence splitting, word counts and narration-time estimates."""
import re

_SPLIT = re.compile(r'(?<=[.?!।])\s+|(?<=[.?!।]["\'”’)])\s+')


def sentences(text: str, language: str = "en") -> list:
    """Split after . ? ! and the Bengali danda, keeping the punctuation."""
    text = " ".join((text or "").split())
    if not text:
        return []
    return [s for s in _SPLIT.split(text) if s]


def words(text: str) -> int:
    return len((text or "").split())


def estimate_seconds(text: str, language: str = "en", wpm: float = 120) -> float:
    return words(text) / wpm * 60.0
