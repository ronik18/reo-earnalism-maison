import json
import struct
import uuid
import zlib
from pathlib import Path
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.utils import timezone
from library.models import Work,Edition,Revision,Unit,Paragraph,Asset,Rights
from library.services import canonical_bytes,digest,asset_path,write_reader_package,revision_hash,paragraph_dto
from learning.models import Track,Lesson,Quiz,Question,QuestionOption,InterviewQuestion

def uid(prefix,suffix):
    return uuid.UUID(f'{prefix}000000-0000-4000-8000-000000000{suffix}')

def original_cover():
    """An original simple raster test cover, generated without external media."""
    width,height=600,900
    rows=[]
    for y in range(height):
        row=bytearray()
        for x in range(width):
            border=x<20 or x>=580 or y<20 or y>=880
            river=y>450 and x>100+(y-450)//3
            row.extend((185,154,87) if border else ((35,81,82) if river else (39+y//22,27+y//45,46+y//30)))
        rows.append(b'\x00'+bytes(row))
    def chunk(kind,data): return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows),9))+chunk(b'IEND',b'')

class Command(BaseCommand):
    help='Seed original English/Bengali local-only Reader and learning acceptance fixtures. No import or provider call.'

    @transaction.atomic
    def handle(self,*args,**options):
        if not getattr(settings,'LOCAL',False) or not getattr(settings,'MAISON_LOCAL_FIXTURES',False):
            raise CommandError('Local fixtures are forbidden outside the explicit local profile.')
        packet=json.loads((Path(__file__).parents[2]/'fixtures/local_original.json').read_text())
        work,_=Work.objects.get_or_create(id=uid('10','001'),defaults={'slug':'river-notebook','title':'The River Notebook',
            'creators':['Maison local fixture authors'],'house':'golpo','topic':'observation','level':'beginner'})
        if work.level=='foundation':
            work.level='beginner';work.save(update_fields=['level'])
        for row in packet['editions']:
            suffix=row['suffix'];eid=uid('20',suffix);rid=uid('30',suffix);unid=uid('40',suffix)
            edition,_=Edition.objects.get_or_create(id=eid,defaults={'work':work,'slug':row['slug'],'locale':row['locale']})
            if Revision.objects.filter(id=rid).exists():
                self.stdout.write(f'PRESERVED existing local fixture edition={eid} revision={rid}')
                continue
            revision=Revision.objects.create(id=rid,edition=edition,title=row['title'],description=row['description'],
                access_policy={'reader':'free','audio':'deny','video':'deny'},download_policy={'reader':True,'audio':False,'video':False})
            unit=Unit.objects.create(id=unid,revision=revision,title=row['unit_title'],ordinal=1)
            for index,text in enumerate(row['paragraphs'],1):
                Paragraph.objects.create(unit=unit,ordinal=index,text=text)
            paragraphs=list(unit.paragraphs.all())
            bounded=paragraph_dto(paragraphs[0]);bounded['text']=bounded['text'][:130]
            revision.preview=[bounded]
            cover=original_cover();aid=uuid.uuid4();key=f'revisions/{rid}/{aid}.png'
            path=asset_path(key);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(cover)
            Asset.objects.create(id=aid,revision=revision,kind='cover',state='ready',storage_key=key,
                sha256=digest(cover),bytes=len(cover),content_type='image/png')
            write_reader_package(unit)
            now=timezone.now()
            for action in ('read','preview','download'):
                Rights.objects.create(revision=revision,format='reader',action=action,territories=['IN'],
                    starts_at=now-timedelta(days=1),ends_at=now+timedelta(days=365),approved=True,test_only=True,
                    evidence=packet['notice'])
            revision.content_sha256=revision_hash(revision)
            revision.validation_evidence={'browser':{'status':'pending','sha256':revision.content_sha256,'scope':'local_test_only'},
                'seed_notice':'Locally live test-only fixture, not a commercial publication or browser approval.'}
            revision.state='live';revision.published_at=now;revision.save()
            edition.live_revision=revision;edition.save()
            self.stdout.write(f'LOCAL TEST ONLY edition={eid} revision={rid} unit={unid} locale={row["locale"]}')
        self.seed_learning()
        self.stdout.write(self.style.SUCCESS('Original local fixtures ready. Commercial release, provider and browser gates remain separate.'))

    def seed_learning(self):
        for suffix,locale in [('001','en'),('002','bn')]:
            track,_=Track.objects.get_or_create(id=uid('80',suffix),defaults={
                'title':'SDE Foundations — 7 days' if locale=='en' else 'এসডিই ভিত্তি — ৭ দিন',
                'locale':locale,'kind':'sde_interview','description':'Original local practice material. No employer affiliation or hiring prediction.',
                'duration_days':7,'access':'free','published':True})
            lesson,_=Lesson.objects.get_or_create(id=uid('81',suffix),defaults={'track':track,'ordinal':1,
                'title':'Explain a queue' if locale=='en' else 'একটি কিউ ব্যাখ্যা করুন',
                'body':[{'anchor_id':str(uuid.uuid4()),'kind':'paragraph','ordinal':1,
                    'text':'A queue removes the oldest item first. Explain its invariant, operations, failure cases and complexity.' if locale=='en' else 'কিউতে আগে ঢোকা উপাদান আগে বের হয়। এর নিয়ম, কাজ, ব্যতিক্রম আর সময়ের জটিলতা ব্যাখ্যা করুন।'}]})
            InterviewQuestion.objects.get_or_create(id=uid('83',suffix),defaults={'track':track,'topic':'data_structures','difficulty':'foundation',
                'prompt':'Design a bounded FIFO queue. What happens when it is full?' if locale=='en' else 'সীমিত আকারের একটি ফিফো কিউ তৈরি করুন। পূর্ণ হলে কী হবে?',
                'model_answer':'Use a circular buffer with head, tail and count. Reject an enqueue when count equals capacity. Remove at head, advance modulo capacity, and preserve FIFO. Both operations are O(1); storage is O(capacity).' if locale=='en' else 'হেড, টেল আর গণনা সহ একটি বৃত্তাকার বাফার ব্যবহার করুন। গণনা ধারণক্ষমতার সমান হলে নতুন উপাদান প্রত্যাখ্যান করুন। হেড থেকে সরিয়ে সূচক ঘুরিয়ে দিন। কাজ দুটির সময় O(1), স্থান O(capacity)।',
                'rubric':[{'criterion':'Invariant','guidance':'State the count bounds and FIFO ordering.'},{'criterion':'Edge cases','guidance':'Handle empty and full without data loss.'},{'criterion':'Complexity','guidance':'Justify O(1) operations and bounded storage.'}]})
            quiz,_=Quiz.objects.get_or_create(id=uid('82',suffix),defaults={'lesson':lesson,'max_attempts':None})
            question,_=Question.objects.get_or_create(id=uid('84',suffix),defaults={'quiz':quiz,'ordinal':1,
                'prompt':'Which item leaves a FIFO queue first?' if locale=='en' else 'ফিফো কিউ থেকে কোন উপাদানটি আগে বের হয়?',
                'explanation':'FIFO means first in, first out.' if locale=='en' else 'ফিফো মানে আগে প্রবেশ, আগে প্রস্থান।'})
            QuestionOption.objects.get_or_create(id=uid('85',suffix),defaults={'question':question,'text':'The oldest item' if locale=='en' else 'সবচেয়ে আগে আসা উপাদান','is_correct':True})
            QuestionOption.objects.get_or_create(id=uid('86',suffix),defaults={'question':question,'text':'The newest item' if locale=='en' else 'সবচেয়ে পরে আসা উপাদান','is_correct':False})

        from library.collections import seed_local_collection
        seed_local_collection()
