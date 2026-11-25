"""Printable worksheet and answer key for a learning track (classroom licence, revenue plan Step 4.2).

Built from the track's own lessons and current quiz questions; nothing is invented. Uses the
platform's embedded PDF fonts (billing.pdf_fonts), which shape Bengali correctly. Blank "Name" and
"Class" lines are printed for pupils to write on; no pupil data is collected.
"""
import io

from django.core.exceptions import ValidationError

from core.api import DomainError
from .models import Track

LETTERS = {'en': 'ABCDEFGH', 'bn': 'কখগঘঙচছজ'}
WORDS = {
    'en': {'worksheet': 'Worksheet', 'answers': 'Answer key', 'name': 'Name', 'class': 'Class', 'answer': 'Answer',
           'sponsored': 'Sponsored by {name}', 'footer': 'Earnalism classroom · theearnalism.com'},
    'bn': {'worksheet': 'অনুশীলনী', 'answers': 'উত্তরমালা', 'name': 'নাম', 'class': 'শ্রেণি', 'answer': 'উত্তর',
           'sponsored': 'সৌজন্যে {name}', 'footer': 'Earnalism classroom · theearnalism.com'},
}
TOP, BOTTOM, LEFT, WIDTH = 790, 60, 56, 483


def worksheet_content(track_id):
    try:
        track = Track.objects.get(pk=track_id, published=True)
    except (Track.DoesNotExist, ValueError, ValidationError):
        raise DomainError('not_found', 'Track not found.', 404)
    if track.access == 'deny':
        raise DomainError('access_denied', 'This track is not offered.', 403)
    lessons = []
    for lesson in track.lessons.select_related('quiz').order_by('ordinal'):
        questions = []
        if hasattr(lesson, 'quiz'):
            for q in lesson.quiz.questions.prefetch_related('options').order_by('ordinal'):
                options = list(q.options.order_by('id'))
                questions.append({'prompt': q.prompt, 'options': [o.text for o in options],
                                  'correct': [i for i, o in enumerate(options) if o.is_correct], 'explanation': q.explanation})
        lessons.append({'title': lesson.title, 'questions': questions})
    if not any(l['questions'] for l in lessons):
        raise DomainError('worksheet_unavailable', 'This track has no quiz questions to print.', 409)
    return track, lessons


def _wrap(text, size, width, text_width):
    lines, line = [], ''
    for word in str(text).split():
        trial = f'{line} {word}'.strip()
        if line and text_width(trial, size) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


def render(track_id, answers=False):
    """PDF bytes: the worksheet, or with answers=True the answer key with explanations."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from billing.pdf_fonts import draw_text, text_width

    track, lessons = worksheet_content(track_id)
    locale = track.locale if track.locale in WORDS else 'en'
    words, letters = WORDS[locale], LETTERS[locale]
    out = io.BytesIO()
    pdf = canvas.Canvas(out, pagesize=A4, invariant=1)
    pdf.setTitle(f"{track.title} — {words['answers' if answers else 'worksheet']}")
    y = TOP

    def line(text, size=11, indent=0, gap=None):
        nonlocal y
        for part in _wrap(text, size, WIDTH - indent, text_width) or ['']:
            if y < BOTTOM:
                draw_text(pdf, words['footer'], LEFT, 30, 8)
                pdf.showPage()
                y = TOP
            draw_text(pdf, part, LEFT + indent, y, size)
            y -= gap or size * 1.6

    line(track.title, 18)
    line(words['answers' if answers else 'worksheet'], 13)
    if track.sponsor_name:
        line(words['sponsored'].format(name=track.sponsor_name), 10)
    if not answers:
        line(f"{words['name']}: ______________________    {words['class']}: __________", 11)
    y -= 8
    number = 0
    for lesson in lessons:
        if not lesson['questions']:
            continue
        y -= 6
        line(lesson['title'], 14)
        for q in lesson['questions']:
            number += 1
            line(f'{number}. {q["prompt"]}', 11)
            if answers:
                chosen = ', '.join(f'{letters[i]}. {q["options"][i]}' for i in q['correct']) or '—'
                line(f"{words['answer']}: {chosen}", 11, indent=16)
                if q['explanation']:
                    line(q['explanation'], 10, indent=16)
            else:
                for i, option in enumerate(q['options'][:len(letters)]):
                    line(f'{letters[i]}. {option}', 11, indent=16)
            y -= 6
    draw_text(pdf, words['footer'], LEFT, 30, 8)
    pdf.save()
    return out.getvalue()
