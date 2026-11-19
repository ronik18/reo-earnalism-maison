"""PDF-only platform fonts with explicit Bengali shaping and readable text extraction."""
from functools import lru_cache
from pathlib import Path
from threading import RLock
from django.core.exceptions import ImproperlyConfigured
from core.api import DomainError

_LOCK=RLock()

@lru_cache(maxsize=1)
def _fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    root=Path(__file__).parent/'fonts'
    result={}
    for name,filename in [('MaisonSansLatin','MaisonSansLatin.ttf'),('MaisonSansBengali','MaisonSansBengali.ttf')]:
        path=root/filename
        if not path.is_file():raise ImproperlyConfigured('Retained licensed financial PDF fonts are missing')
        font=TTFont(name,str(path),shapable=True)
        pdfmetrics.registerFont(font);result[name]=font
    return result

def _runs(text):
    if not isinstance(text,str) or len(text)>4096:
        raise DomainError('financial_document_text_invalid','Financial document text exceeds its bounded rendering profile.',409)
    fonts=_fonts();runs=[]
    for char in text:
        cp=ord(char)
        if cp<32 or 0x7f<=cp<0xa0:
            raise DomainError('financial_document_text_invalid','Financial document text contains unsupported control characters.',409)
        if 0x980<=cp<=0x9ff:name='MaisonSansBengali'
        elif cp in (0x200c,0x200d):
            if not runs or runs[-1][0]!='MaisonSansBengali':
                raise DomainError('financial_document_text_invalid','Join controls require Bengali text.',409)
            name='MaisonSansBengali'
        elif char==' ' and runs:name=runs[-1][0]
        elif cp in fonts['MaisonSansLatin'].face.charToGlyph:name='MaisonSansLatin'
        elif cp in fonts['MaisonSansBengali'].face.charToGlyph:name='MaisonSansBengali'
        else:raise DomainError('financial_document_glyph_unavailable','This financial document needs a qualified font for its text.',409)
        if cp not in (0x200c,0x200d) and not fonts[name].face.charToGlyph.get(cp):
            raise DomainError('financial_document_glyph_unavailable','This financial document needs a qualified font for its text.',409)
        if runs and runs[-1][0]==name:runs[-1]=(name,runs[-1][1]+char)
        else:runs.append((name,char))
    return runs

def _shape(name,text,size):
    from reportlab.pdfbase import pdfmetrics
    if name=='MaisonSansBengali':
        from reportlab.pdfbase.ttfonts import shapeStr,ShapedStr
        shaped=shapeStr(text,name,size,force=True)
        if not isinstance(shaped,ShapedStr) or not shaped.__shapeData__:
            raise DomainError('financial_document_shaping_unavailable','Bengali document shaping is unavailable.',409)
        return shaped,sum(item.x_advance for item in shaped.__shapeData__)*size/1000
    return text,pdfmetrics.stringWidth(text,name,size)

def _size(font_size):
    if type(font_size) not in (int,float) or not 6<=font_size<=36:
        raise ValueError('Financial document font size must be6..36points')

def text_width(text,font_size=11):
    _size(font_size)
    with _LOCK:return sum(_shape(name,run,font_size)[1] for name,run in _runs(text))

def draw_text(canvas,text,x,y,font_size=11):
    """Draw literal text; return the exact shaped horizontal advance in points."""
    _size(font_size);width=0
    with _LOCK:
        canvas.saveState()
        try:
            for name,run in _runs(text):
                shaped,advance=_shape(name,run,font_size);canvas.setFont(name,font_size)
                # ActualText preserves original Unicode for copying/searching even
                # when a Bengali conjunct maps to a font-private shaped glyph.
                actual='FEFF'+run.encode('utf-16-be').hex().upper()
                canvas.addLiteral('/Span << /ActualText <'+actual+'> >> BDC')
                try:canvas.drawString(x+width,y,shaped)
                finally:canvas.addLiteral('EMC')
                width+=advance
        finally:canvas.restoreState()
    return width
