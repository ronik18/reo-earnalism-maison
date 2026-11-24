"""Public-domain term screen for a candidate title across the active publication whitelist.

This is a research screen, not clearance. It computes, from an author's death year and the
work's first publication year, whether the copyright term has expired in each active
territory, using the rules already recorded in docs/evidence/publication-clearance-20261123.json.
A pass only says the title is worth sourcing; publication still needs the per-title evidence
record, a licensed text source, cover provenance and owner approval (BOOK_PUBLICATION_POLICY.md).

Not handled, so always flagged for human review: joint authorship (use the last surviving
author), anonymous/pseudonymous or posthumous works, government works, translations (a new
translation has its own term) and illustrations (each illustrator has their own term).
"""
import json
from pathlib import Path

POLICY = Path(__file__).resolve().parents[1] / 'contracts' / 'publication-policy.json'

# term: years after the year of death; the work is public domain from 1 January after
# (death year + term). US: years after first publication (works published 95+ years ago).
RULES = {
    'IN': {'basis': 'death', 'term': 60, 'rule': 'Copyright Act 1957 s.22: life + 60 years from the year following death',
           'source': 'https://copyright.gov.in/Copyright_Act_1957/chapter_v.html'},
    'US': {'basis': 'publication', 'term': 95, 'rule': '17 U.S.C. 304 / Circular 15a: works first published 95 or more years ago (before 1 January 1931 in 2026) are in the public domain',
           'source': 'https://www.copyright.gov/circs/circ15a.pdf'},
    'GB': {'basis': 'death', 'term': 70, 'rule': 'CDPA 1988 s.12: life + 70 years from the end of the calendar year of death',
           'source': 'https://www.legislation.gov.uk/ukpga/1988/48/section/12'},
    'BR': {'basis': 'death', 'term': 70, 'rule': 'Law 9610/1998 art.41: life + 70 years from 1 January following death',
           'source': 'https://www.planalto.gov.br/ccivil_03/leis/l9610.htm'},
    'SG': {'basis': 'death', 'term': 70, 'rule': 'Copyright Act 2021 s.114: life + 70; terms already expired under the earlier life + 50 rule (before the 2004 extension) are not revived',
           'source': 'https://sso.agc.gov.sg/Act/CA2021?ProvIds=P13-&ViewType=Advance&WiAl=1'},
    'MY': {'basis': 'death', 'term': 50, 'rule': 'Copyright Act 1987 s.17: life + 50 years from the year following death',
           'source': 'https://www.myipo.gov.my/faq/'},
    'ID': {'basis': 'death', 'term': 70, 'rule': 'Law 28/2014 art.58: life + 70 years from 1 January following death',
           'source': 'https://www.wipo.int/wipolex/en/legislation/details/15600'},
    'PH': {'basis': 'death', 'term': 50, 'rule': 'IP Code s.213.1: life + 50 years from the year following death',
           'source': 'https://ilaw.ipophil.gov.ph/pluginfile.php/146/mod_resource/content/2/Philippine%20IP%20Code.pdf'},
    'TH': {'basis': 'death', 'term': 50, 'rule': 'Copyright Act B.E. 2537 s.19: life + 50 years from the death of the author (screened conservatively to the end of that year)',
           'source': 'https://web2026.ipthailand.go.th/wp-content/uploads/2025/05/COPYRIGHT-ACT-B.E.-2537-1994.pdf'},
}


def active_territories():
    return list(json.loads(POLICY.read_text())['whitelist'])


def _year(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or not 1000 <= value <= 2200:
        raise ValueError(f'{name} must be a four-digit year')
    return value


def assess(author_died, first_published, year, territories=None):
    """Per-territory term screen. Raises ValueError for unknown territories or bad years."""
    author_died = None if author_died is None else _year(author_died, 'author_died')
    first_published = None if first_published is None else _year(first_published, 'first_published')
    year = _year(year, 'year')
    territories = territories or active_territories()
    unknown = sorted(set(territories) - set(RULES))
    if unknown:
        raise ValueError(f'No term rule recorded for {", ".join(unknown)}; add one before screening')
    result = {}
    for code in territories:
        rule = RULES[code]
        anchor = author_died if rule['basis'] == 'death' else first_published
        if anchor is None:
            result[code] = {'status': 'unknown', 'reason': f"{rule['basis']} year missing", 'rule': rule['rule'], 'source': rule['source']}
            continue
        expired_end_of = anchor + rule['term']
        result[code] = {'status': 'public_domain' if year > expired_end_of else 'in_copyright',
                        'expired_end_of': expired_end_of, 'public_domain_from': expired_end_of + 1,
                        'rule': rule['rule'], 'source': rule['source']}
    return result


def screen(candidate, year):
    """Screen one candidate dict; returns it with territory_terms, a verdict and review flags."""
    terms = assess(candidate.get('author_died'), candidate.get('first_published'), year)
    blocked = sorted(c for c, t in terms.items() if t['status'] != 'public_domain')
    flags = list(candidate.get('review_flags', []))
    if candidate.get('translation') or candidate.get('illustrated'):
        flags.append('translator/illustrator terms must be screened separately')
    verdict = 'hold' if blocked else ('review' if flags else 'screen_pass')
    return {**candidate, 'territory_terms': terms, 'blocked_in': blocked, 'review_flags': flags,
            'verdict': verdict, 'screened_for_year': year, 'is_clearance': False}
