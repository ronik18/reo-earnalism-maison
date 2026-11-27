"""Small deterministic Bengali -> Latin scheme for search matching only.

Not a transliteration standard: it only needs to map a Latin query a reader
would plausibly type ("bicharak", "bicharok") onto a Bengali title. The
inherent vowel of a consonant is written 'a' or 'o' in common Banglish, so two
uniform variants are produced (all 'a', all 'o'); a word-final inherent vowel
is dropped. Output is lower-case ASCII with no spaces or hyphens.

Variant cap: at most MAX_VARIANTS (2) per title, independent of title length,
and at most MAX_CHARS (200) Bengali characters are read, so a long title can
never multiply combinatorially.
"""
import unicodedata

MAX_CHARS = 200
MAX_VARIANTS = 2
_INHERENT = '\0'  # placeholder replaced by 'a' / 'o' (or dropped word-finally)

CONSONANTS = {
    'ক': 'k', 'খ': 'kh', 'গ': 'g', 'ঘ': 'gh', 'ঙ': 'ng', 'চ': 'ch', 'ছ': 'chh', 'জ': 'j',
    'ঝ': 'jh', 'ঞ': 'n', 'ট': 't', 'ঠ': 'th', 'ড': 'd', 'ঢ': 'dh', 'ণ': 'n', 'ত': 't',
    'থ': 'th', 'দ': 'd', 'ধ': 'dh', 'ন': 'n', 'প': 'p', 'ফ': 'ph', 'ব': 'b', 'ভ': 'bh',
    'ম': 'm', 'য': 'j', 'র': 'r', 'ল': 'l', 'শ': 'sh', 'ষ': 'sh', 'স': 's', 'হ': 'h',
    'ৎ': 't',
}
NUKTA = '়'
NUKTA_FORMS = {'ড': 'r', 'ঢ': 'rh', 'য': 'y'}  # ড় ঢ় য়
HASANTA = '্'
VOWEL_SIGNS = {
    'া': 'a', 'ি': 'i', 'ী': 'i', 'ু': 'u', 'ূ': 'u', 'ৃ': 'ri',
    'ে': 'e', 'ৈ': 'oi', 'ো': 'o', 'ৌ': 'ou',
}
INDEPENDENT_VOWELS = {
    'আ': 'a', 'ই': 'i', 'ঈ': 'i', 'উ': 'u', 'ঊ': 'u', 'ঋ': 'ri',
    'এ': 'e', 'ঐ': 'oi', 'ও': 'o', 'ঔ': 'ou',
}
MARKS = {'ঁ': 'n', 'ং': 'ng', 'ঃ': 'h'}
DIGITS = {chr(0x09e6 + i): str(i) for i in range(10)}
# Common conjuncts whose spoken form is not the plain concatenation.
CONJUNCTS = {'ক্ষ': 'kkh', 'জ্ঞ': 'gg'}


def _is_bengali(char):
    return 'ঀ' <= char <= '৿'


def _tokens(text):
    """Return a list of strings/_INHERENT markers; None marks a word break."""
    out = []
    i, n = 0, len(text)
    while i < n:
        char = text[i]
        if text[i:i + 3] in CONJUNCTS:
            out.append(CONJUNCTS[text[i:i + 3]]); i += 3; follow = True
        elif char in CONSONANTS:
            if text[i + 1:i + 2] == NUKTA and char in NUKTA_FORMS:
                out.append(NUKTA_FORMS[char]); i += 2
            else:
                out.append(CONSONANTS[char]); i += 1
            follow = True
        elif char == 'অ':
            out.append(_INHERENT); i += 1; continue
        elif char in INDEPENDENT_VOWELS:
            out.append(INDEPENDENT_VOWELS[char]); i += 1; continue
        elif char in MARKS:
            out.append(MARKS[char]); i += 1; continue
        elif char in DIGITS:
            out.append(DIGITS[char]); i += 1; continue
        elif char.isascii() and char.isalnum():
            out.append(char.lower()); i += 1; continue
        else:
            # Spaces, punctuation, joiners, stray signs: a word break.
            out.append(None); i += 1; continue
        # After a consonant: vowel sign, hasanta (conjunct), or inherent vowel.
        nxt = text[i:i + 1]
        if nxt in VOWEL_SIGNS:
            out.append(VOWEL_SIGNS[nxt]); i += 1
        elif nxt == HASANTA:
            i += 1
        else:
            out.append(_INHERENT)
    return out


def romanize_bn(text):
    """Return the set of Latin spellings (<= MAX_VARIANTS) of a Bengali text."""
    if not isinstance(text, str):
        return set()
    text = unicodedata.normalize('NFC', text)[:MAX_CHARS]
    if not any(_is_bengali(char) for char in text):
        return set()
    tokens = _tokens(text)
    # A word-final inherent vowel is not pronounced: drop it before a break/end.
    for index, token in enumerate(tokens):
        if token == _INHERENT and (index + 1 == len(tokens) or tokens[index + 1] is None):
            tokens[index] = ''
    variants = set()
    for vowel in ('a', 'o'):
        spelled = ''.join(vowel if t == _INHERENT else (t or '') for t in tokens)
        if spelled:
            variants.add(spelled)
    return variants


def normalize_latin_query(value):
    """Lower-case and drop spaces/hyphens; '' unless the query is plain ASCII letters."""
    squashed = ''.join(char for char in value.casefold() if not char.isspace() and char != '-')
    return squashed if squashed.isascii() and squashed.isalnum() else ''
