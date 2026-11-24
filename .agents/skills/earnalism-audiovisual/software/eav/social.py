"""Social kit: campaign-tagged links, YouTube film description with chapters, reel posts, quote cards.

Everything here is derived from the production record and the book's own text; nothing is
invented. Links follow docs/CAMPAIGN_LINKS.md so Maison attributes signups to the post.
Writing a kit publishes nothing: posting still needs the owner's destination instruction.
"""
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from PIL import Image, ImageDraw, ImageFont, features

SOURCES = ("youtube", "instagram", "facebook", "x", "whatsapp", "newsletter", "google_play",
           "podcast", "school", "partner")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
CARD = 1080
MIN_CHAPTERS, MIN_CHAPTER_S = 3, 10.0  # YouTube's own chapter rules
YOUTUBE_DESCRIPTION_LIMIT = 5000
QUOTE_MAX_CHARS = 220


def campaign_url(site: str, edition_id: str, campaign: str, source: str, content: str) -> str:
    parts = urlsplit(site)
    if parts.scheme != "https" or not parts.hostname or parts.path not in ("", "/") or parts.query:
        raise ValueError("site must be a bare https origin such as https://theearnalism.com")
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")
    for name, value in (("campaign", campaign), ("content", content)):
        if not SLUG.fullmatch(value):
            raise ValueError(f"{name} must be lowercase letters, digits and hyphens")
    if not re.fullmatch(r"[0-9a-f-]{36}", edition_id or ""):
        raise ValueError("edition_id must be the Maison edition UUID")
    query = urlencode({"utm_source": source, "utm_campaign": campaign, "utm_content": content})
    return f"https://{parts.netloc}/en/titles/{edition_id}/?{query}"


def stamp(seconds: float) -> str:
    s = int(seconds)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chapters(units: list, scenes: list, timing: list) -> list:
    """(start_seconds, unit title) per source chapter, or [] when YouTube would reject them.

    Titles are the book's own unit titles; a film with fewer than three chapters, or one shorter
    than ten seconds, gets no chapter list rather than invented ones.
    """
    scene_of = {a: sc["scene_id"] for sc in scenes for a in sc.get("anchor_ids", [])}
    marks = []
    for unit in units:
        anchors = [p["anchor_id"] for p in unit.get("paragraphs", []) if p["anchor_id"] in scene_of]
        title = (unit.get("title") or "").strip()
        if not anchors or not title:
            return []
        scene_id = scene_of[anchors[0]]
        start = next((t["start"] for t in timing if t["unit_key"].startswith(scene_id + "-")), None)
        if start is None:
            return []
        marks.append((0.0 if not marks else float(start), title))
    ends = [m[0] for m in marks[1:]] + [float(timing[-1]["end"])] if timing else []
    if len(marks) < MIN_CHAPTERS or any(e - s < MIN_CHAPTER_S for (s, _), e in zip(marks, ends)):
        return []
    return marks


def film_description(title: str, author: str, url: str, marks: list, credits: list, tags: list) -> str:
    lines = [f"{title} — {author}", "", f"Read it free on Earnalism: {url}"]
    if marks:
        lines += ["", "Chapters"] + [f"{stamp(s)} {t}" for s, t in marks]
    lines += ["", *credits, "", " ".join(tags)]
    text = "\n".join(lines).strip() + "\n"
    if len(text) > YOUTUBE_DESCRIPTION_LIMIT:
        raise ValueError("description exceeds YouTube's 5,000 character limit")
    return text


def reel_post(caption: str, url: str, clickable: bool) -> str:
    """Reel caption plus the tagged link (Instagram captions do not make links clickable)."""
    line = f"Read it free: {url}" if clickable else "Read it free on Earnalism (link in bio)"
    return caption.rstrip() + "\n\n" + line + "\n"


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def verify_quote(quote: str, units: list) -> str:
    """The quote must be the book's exact words (whitespace-insensitive) and card-sized."""
    q = _norm(quote)
    if not q or len(q) > QUOTE_MAX_CHARS:
        raise ValueError(f"a quote card holds 1 to {QUOTE_MAX_CHARS} characters")
    for unit in units:
        for p in unit.get("paragraphs", []):
            if q in _norm(p["text"]):
                return q
    raise ValueError("quote is not the book's exact words; copy it from the source text")


def _wrap(draw, text, font, width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def quote_card(quote: str, attribution: str, footer: str, font_path: Path, footer_font_path: Path,
               out: Path, background: Path = None, marks: bool = True) -> dict:
    """1080x1080 PNG: the quote centred over a darkened still (or a plain field), with credits.

    font_path sets the quote and attribution (the Bengali subset for Bengali titles);
    footer_font_path sets the Latin web address. marks=False omits curly quotation marks,
    which the Bengali-only font subset does not contain.
    """
    if not features.check("raqm"):
        raise RuntimeError("Pillow lacks libraqm; Bengali text would be mis-shaped")
    if background:
        img = Image.open(background).convert("RGB")
        side = min(img.size)
        img = img.crop(((img.width - side) // 2, (img.height - side) // 2,
                        (img.width + side) // 2, (img.height + side) // 2)).resize((CARD, CARD))
        img = Image.blend(img, Image.new("RGB", img.size, (12, 10, 8)), 0.62)
    else:
        img = Image.new("RGB", (CARD, CARD), (28, 22, 18))
    draw = ImageDraw.Draw(img)
    margin, size = 110, 64
    while size >= 34:
        font = ImageFont.truetype(str(font_path), size, layout_engine=ImageFont.Layout.RAQM)
        lines = _wrap(draw, f"“{quote}”" if marks else quote, font, CARD - 2 * margin)
        height = len(lines) * int(size * 1.45)
        if height <= CARD - 2 * margin - 160:
            break
        size -= 4
    else:
        raise ValueError("quote is too long to set legibly on one card")
    y = (CARD - height) // 2 - 40
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((CARD - w) / 2, y), line, font=font, fill=(246, 239, 226))
        y += int(size * 1.45)
    small = ImageFont.truetype(str(font_path), 34, layout_engine=ImageFont.Layout.RAQM)
    latin = ImageFont.truetype(str(footer_font_path), 30, layout_engine=ImageFont.Layout.RAQM)
    for text, face, ty, fill in ((attribution, small, y + 30, (214, 178, 108)),
                                 (footer, latin, CARD - 90, (200, 192, 180))):
        w = draw.textlength(text, font=face)
        draw.text(((CARD - w) / 2, ty), text, font=face, fill=fill)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return {"size": [CARD, CARD], "font_size": size, "lines": len(lines)}
