"""A new full-picture Tides composition, retaining exact existing speech/timing.

This is original deterministic explanatory artwork, not a fluid simulation.
Only the existing tested point-Moon physics and shared brand validator are reused.
No voice synthesis, score modification, END assembly or publication occurs here.
"""
from pathlib import Path
from functools import lru_cache
import argparse
import hashlib
import json
import math
import re
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from ..tides.model import actual_lunar_acceleration, relative_tidal_acceleration, illustrative_envelope_axes

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'output/episodes/19-tides/rebuild-20261115'
COAST=OUT/'assets/coast-original.png'
FONT=Path('/System/Library/Fonts/Avenir Next.ttc')
FONT_INDEX=7
ASSETS=Path.home()/'.codex/skills/earnalism-video/software/assets/standard-intro/v1'
LOGO=ASSETS/'production-lockup.png'
LOGO_SHA='951d21e89cbcab58e0f9aed60778a8966d920e2fba464d1cade7bc37fb3ee919'
SIZES={'landscape':(1920,1080),'portrait':(1080,1920)}
KINDS=('opening','actual','relative','envelope','coast','recap')
TITLES={'opening':'Why can the far side rise?',
 'actual':'The Moon attracts every side',
 'relative':'Compare with Earth’s centre',
 'envelope':'Unequal attraction. Two broad bulges.',
 'coast':'At a real coast, the pattern changes',
 'recap':'One Moon. A two-sided response.'}
EXAMPLES={'opening':'So why can the far side rise too?',
 'actual':'Near the Moon, gravity is stronger.',
 'relative':'The far side lags behind.',
 'envelope':'This difference stretches our simple ocean model in two directions.',
 'coast':'Real oceans have continents, varying depths, and the Sun’s influence,',
 'recap':'One Moon. Unequal attraction. Two sides responding.'}
CYAN='#8AE8ED';GOLD='#FFD38A';WHITE='#F3FBF6';INK='#173C4A'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,data):Path(path).write_text(json.dumps(data,indent=2)+'\n')
def rect(b):return {'x':b[0],'y':b[1],'width':b[2]-b[0],'height':b[3]-b[1]}
def contains(b,a):return b[0]<=a[0]<=a[2]<=b[2] and b[1]<=a[1]<=a[3]<=b[3]
def smooth(x):x=max(0,min(1,x));return x*x*(3-2*x)

@lru_cache(maxsize=150)
def font(px,path=str(FONT),index=FONT_INDEX):return ImageFont.truetype(path,round(px),index=index)

@lru_cache(maxsize=300)
def _safe(serialized):
    r=subprocess.run(['node',str(HERE/'layout.mjs')],input=serialized.encode(),capture_output=True,check=True)
    return json.loads(r.stdout)

def layout(name,occupied=()):
    w,h=SIZES[name]
    return _safe(json.dumps({name:{'width':w,'height':h,'occupiedRects':list(occupied)}},sort_keys=True))[name]

def text(image,copy,bounds,px,minimum=None,*,color=WHITE,align='center',max_lines=2,font_path=FONT,font_index=FONT_INDEX):
    """Record actual rendered glyph boxes; never shrink below a declared floor."""
    d=ImageDraw.Draw(image);pad=4;minimum=round(px if minimum is None else minimum)
    for size in range(round(px),minimum-1,-1):
        face=font(size,str(font_path),font_index);lines=[]
        for para in copy.split('\n'):
            row=''
            for word in para.split():
                test=(row+' '+word).strip()
                if row and d.textlength(test,font=face)>bounds[2]-bounds[0]-pad*2:
                    lines.append(row);row=word
                else:row=test
            lines.append(row)
        step=math.ceil(size*1.30)
        if len(lines)<=max_lines and step*len(lines)<=bounds[3]-bounds[1] and all(d.textlength(l,font=face)<=bounds[2]-bounds[0]-pad*2 for l in lines):break
    else:raise ValueError('Reflow unreadable text: '+copy)
    top=bounds[1]+(bounds[3]-bounds[1]-step*len(lines))/2;inks=[]
    for i,line in enumerate(lines):
        x=bounds[0]+pad if align=='left' else (bounds[0]+bounds[2]-d.textlength(line,font=face))/2
        y=top+i*step;ink=d.textbbox((x,y),line,font=face,anchor='lt')
        if not contains(bounds,ink):raise ValueError('Glyph escaped its reading region')
        d.text((x,y),line,font=face,fill=color,anchor='lt');inks.append(ink)
    return {'text':copy,'font_px':size,'face':face.getname(),'ink':inks,'region':bounds}

@lru_cache(maxsize=8)
def atmosphere(size):
    w,h=size;y=np.linspace(0,1,h)[:,None,None]
    # Continuous sky wash keeps the original dark logo legible without a backing.
    top=np.array([235,244,234.]);mid=np.array([11,40,64.]);bottom=np.array([4,18,36.])
    stop=.205 if h>w else .145
    t=np.clip((y-stop)/.11,0,1);c=top*(1-smooth_array(t))+mid*smooth_array(t)
    u=np.clip((y-stop-.11)/(1-stop-.11),0,1);c=c*(1-u)+bottom*u
    arr=np.broadcast_to(c,(h,w,3)).astype(np.uint8).copy()
    im=Image.fromarray(arr,'RGB').convert('RGBA');d=ImageDraw.Draw(im)
    rng=np.random.default_rng(73)
    for x1,y1,rad in zip(rng.uniform(.02,.98,70)*w,rng.uniform(.30,.95,70)*h,rng.choice([1,1,2],70)):
        d.ellipse((x1-rad,y1-rad,x1+rad,y1+rad),fill=(112,172,192,150))
    return im

def smooth_array(x):return x*x*(3-2*x)

@lru_cache(maxsize=8)
def coastal_plate(size,path):
    if not Path(path).is_file():raise FileNotFoundError('Source-bound coast artwork required: '+str(path))
    with Image.open(path) as source:
        return ImageOps.fit(source.convert('RGBA'),size,Image.Resampling.LANCZOS,centering=(.5,.56))

def backdrop(name,kind,progress,coast_path):
    size=SIZES[name];im=atmosphere(size).copy()
    if kind in ('opening','coast','recap'):
        plate=coastal_plate(size,str(coast_path));w,h=size
        # Only decorative scenery extends under platform UI reservations.
        strength=.75 if kind=='coast' else .34
        alpha=np.zeros((h,1),dtype=np.float32)
        yy=np.linspace(0,1,h)[:,None];alpha=np.clip((yy-.31)/.16,0,1)*strength
        mask=Image.fromarray(np.broadcast_to((alpha*255).astype(np.uint8),(h,w)).copy(),'L')
        im=Image.composite(plate,im,mask)
        # A continuous blue atmosphere, not a card around the globe.
        if kind!='coast':
            veil=Image.new('RGBA',size,(2,18,36,90));im=Image.alpha_composite(im,veil)
            # Restore the continuous upper sky wash for canonical logo contrast.
            clear=atmosphere(size);m=np.clip((.42-yy)/.14,0,1)
            im=Image.composite(clear,im,Image.fromarray(np.broadcast_to((m*255).astype(np.uint8),(h,w)).copy(),'L'))
    return im

@lru_cache(maxsize=100)
def ocean_sphere(radius,rotation_step=0):
    """Original shaded ocean-only sphere; no invented geographic coastline."""
    r=int(radius);n=2*r+8
    yy,xx=np.mgrid[:n,:n].astype(float);x=(xx-n/2)/r;y=(yy-n/2)/r
    rr=x*x+y*y;z=np.sqrt(np.clip(1-rr,0,1));a=np.arctan2(x,z)+rotation_step*.001
    light=np.clip(-.34*x-.44*y+.8*z,0,1)
    texture=.5+.5*np.sin(35*a+7*y)*np.sin(23*y-3*a)
    fresnel=(1-z)**3
    rgb=np.stack([10+14*light+4*texture+17*fresnel,45+72*light+5*texture+58*fresnel,72+75*light+8*texture+64*fresnel],axis=-1)
    alpha=np.clip((1-rr)*r/1.4,0,1)*255
    rgba=np.concatenate([np.clip(rgb,0,255),alpha[...,None]],axis=-1).astype(np.uint8)
    im=Image.fromarray(rgba,'RGBA');d=ImageDraw.Draw(im)
    # Curved latitude cues use a translucent overlay, avoiding dark overwritten
    # alpha seams. No geographic boundaries or measured ocean parcels are shown.
    c=n/2;grid=Image.new('RGBA',im.size);d=ImageDraw.Draw(grid)
    for fraction in (-.6,-.3,0,.3,.6):
        y0=c+r*fraction;rx=r*math.sqrt(1-fraction*fraction)
        d.arc((c-rx,y0-r*.075,c+rx,y0+r*.075),0,180,fill=(120,210,215,32),width=1)
    return Image.alpha_composite(im,grid)

def sphere(im,cx,cy,r,rotation=0):
    glow=Image.new('RGBA',im.size);d=ImageDraw.Draw(glow)
    d.ellipse((cx-r-9,cy-r-9,cx+r+9,cy+r+9),outline=(70,222,233,130),width=7)
    glow=glow.filter(ImageFilter.GaussianBlur(10));im.alpha_composite(glow)
    art=ocean_sphere(round(r),round(rotation*1000));im.alpha_composite(art,(round(cx-art.width/2),round(cy-art.height/2)))

@lru_cache(maxsize=12)
def lunar_disc(radius):
    r=round(radius);n=r*2+4;yy,xx=np.mgrid[:n,:n].astype(float);x=(xx-n/2)/r;y=(yy-n/2)/r
    rr=x*x+y*y;z=np.sqrt(np.clip(1-rr,0,1));shade=np.clip(.4+.45*z-.20*x-.15*y,0,1)
    rgb=np.stack([150+90*shade,156+83*shade,150+64*shade],axis=-1)
    alpha=np.clip((1-rr)*r,0,1)*255
    im=Image.fromarray(np.concatenate([rgb,alpha[...,None]],axis=-1).astype(np.uint8),'RGBA');d=ImageDraw.Draw(im)
    for dx,dy,rad in [(-.35,-.28,.20),(.23,-.43,.11),(.25,.27,.19),(-.26,.38,.10),(.54,-.04,.08)]:
        x0,y0=n/2+dx*r,n/2+dy*r;q=rad*r
        d.ellipse((x0-q,y0-q,x0+q,y0+q),fill=(134,150,148,140),outline=(207,213,191,120),width=1)
    return im

def moon(im,cx,cy,r):
    plate=lunar_disc(r);im.alpha_composite(plate,(round(cx-plate.width/2),round(cy-plate.height/2)))

def arrow(d,start,end,color,width=8):
    if math.dist(start,end)<1:return
    d.line((start,end),fill=color,width=width)
    angle=math.atan2(end[1]-start[1],end[0]-start[0]);head=width*2.8
    d.polygon([end,(end[0]-head*math.cos(angle-.43),end[1]-head*math.sin(angle-.43)),(end[0]-head*math.cos(angle+.43),end[1]-head*math.sin(angle+.43))],fill=color)

def geometry(name):
    if name=='portrait':return {'cx':398.,'cy':820.,'r':235.,'mx':794.,'my':820.,'mr':49.}
    return {'cx':740.,'cy':505.,'r':238.,'mx':1515.,'my':505.,'mr':65.}

def arrow_geometry(kind,progress,name,actual_onsets=None):
    q=geometry(name);cx,cy,r=q['cx'],q['cy'],q['r'];records=[]
    centre=actual_lunar_acceleration((0,0))[0]
    # Preview fallback is specific to the controlled original recording. Actual
    # compiled rendering derives these from the source-bound measured words.
    onsets=actual_onsets or {'near':.2791095890410959,'centre':.511986301369863,'far':.7294520547945206}
    for i,x in enumerate((-1,0,1)):
        source=(x,0);origin=(cx+x*r,cy)
        if kind=='actual':
            vec=actual_lunar_acceleration(source);scale=r*.36/centre
            # One linear scale for the complete vector; differences are not stretched.
            onset=onsets[{1:'near',0:'centre',-1:'far'}[x]];fade=smooth((progress-onset)/.12)
            display=(vec[0]*scale*fade,vec[1]*scale*fade)
            records.append({'source_point':source,'physical_vector':vec,'display_origin':origin,'display_vector':display,'display_scale':scale,'frame':'actual_lunar_attraction','reveal':fade})
        elif kind=='relative':
            vec=relative_tidal_acceleration(source)
            # The frame changes first. Enlarging a separately labelled difference
            # field is distinct from exaggerating actual-force ratios.
            scale=r*.34/max(abs(relative_tidal_acceleration((-1,0))[0]),abs(relative_tidal_acceleration((1,0))[0]))
            onset=.22 if x>=0 else .41;fade=smooth((progress-onset)/.12)
            display=(vec[0]*scale*fade,vec[1]*scale*fade)
            records.append({'source_point':source,'physical_vector':vec,'display_origin':origin,'display_vector':display,'display_scale':scale,'frame':'difference_from_centre_enlarged','reveal':fade})
    return records

def ocean_envelope(im,q,progress):
    cx,cy,r=q['cx'],q['cy'],q['r'];stretch=.035+.13*smooth(progress)
    a,b=illustrative_envelope_axes(stretch,r);inner=.83*r
    if b<=inner:raise ValueError('Illustrated ocean layer detached or inverted')
    layer=Image.new('RGBA',im.size);d=ImageDraw.Draw(layer)
    d.ellipse((cx-a,cy-b,cx+a,cy+b),fill=(45,167,191,170),outline=(141,243,243,240),width=4)
    im.alpha_composite(layer);sphere(im,cx,cy,inner,progress*.35)
    d=ImageDraw.Draw(im)
    # Continuous attached water is the illustration; no detached particles.
    d.arc((cx-a,cy-b,cx+a,cy+b),195,345,fill=(202,255,249,240),width=4)
    return {'ellipse_axes':[a,b],'inner_radius':inner,'stretch':stretch,'meaning':'Exaggerated connected 2-D illustration, not fluid dynamics or forecast'}

def basin_geometry(panel,progress):
    pw=panel[2]-panel[0];ph=panel[3]-panel[1];left=panel[0]+30;right=panel[2]-30
    land=[(left,panel[1]+ph*.32),(left+pw*.18,panel[1]+ph*.34),(left+pw*.38,panel[1]+ph*.70),(right,panel[1]+ph*.81)]
    ywater=panel[1]+ph*.46+ph*.025*math.sin(progress*math.pi*2)
    # Solve the shore intersection at this actual illustrative water level.
    a,b=land[1],land[2]
    xwater=a[0]+(ywater-a[1])*(b[0]-a[0])/(b[1]-a[1])
    water=[(xwater,ywater),(right,ywater),land[3],land[2]]
    return {'land':land,'water':water,'surface_contact':(xwater,ywater),'shore_segment':(a,b)}

@lru_cache(maxsize=12)
def brand_layer(name,path):
    w,h=SIZES[name];q=layout(name)['brand']
    with Image.open(path) as src:
        sx,sy=src.width/q['width'],src.height/q['height']
        im=src.convert('RGBA').transform((w,h),Image.Transform.AFFINE,(sx,0,-q['left']*sx,0,sy,-q['top']*sy),resample=Image.Resampling.BICUBIC)
    im=im.filter(ImageFilter.GaussianBlur(q['blurPx']));im.putalpha(im.getchannel('A').point(lambda a:round(a*q['opacity'])))
    return im

def frame(kind,progress,name,*,caption='',preview=False,font_path=FONT,font_index=FONT_INDEX,logo_path=LOGO,coast_path=COAST,actual_onsets=None):
    if name not in SIZES or kind not in KINDS:raise ValueError('Unknown format or explanatory beat')
    progress=max(0,min(1,float(progress)));w,h=SIZES[name];portrait=name=='portrait'
    if sha(logo_path)!=LOGO_SHA:raise ValueError('Exact original transparent full lockup required')
    im=backdrop(name,kind,progress,coast_path);d=ImageDraw.Draw(im);glyphs=[];occupied=[]
    def label(copy,b,px,minimum=None,**kw):
        g=text(im,copy,b,px,minimum,font_path=font_path,font_index=font_index,**kw);glyphs.append(g);occupied.extend(rect(i) for i in g['ink']);return g
    # Primary reading regions are independently composed, not crop coordinates.
    header=(72,276,570,350) if portrait else (70,51,1435,145)
    title=(72,400,900,510) if portrait else (70,178,1850,258)
    caption_box=(72,1256,900,1500) if portrait else (70,860,1850,1032)
    label('DRAFT · NO AUDIO' if preview else 'EVERYDAY SCIENCE',header,31 if portrait else 29,color=INK,align='left')
    d.rounded_rectangle(title,18,fill=(6,29,49,235))
    occupied.append(rect(title))
    label(TITLES[kind],title,44 if portrait else 49,40,max_lines=2)
    q=geometry(name);cx,cy,r,mx,my,mr=[q[k] for k in ('cx','cy','r','mx','my','mr')]
    if kind=='coast':
        # A pictorial coastline remains visible behind a simple explanatory inset.
        panel=(72,640,900,1196) if portrait else (240,360,1680,813)
        sun_panel=(72,535,900,620) if portrait else (1100,275,1680,345)
        d.rounded_rectangle(sun_panel,18,fill=(4,30,49,220),outline=(175,158,109,140),width=2)
        occupied.append(rect(sun_panel))
        sunx=(sun_panel[0]+46);suny=(sun_panel[1]+sun_panel[3])/2
        d.ellipse((sunx-23,suny-23,sunx+23,suny+23),fill=GOLD)
        label('Sun also shapes tides',(sun_panel[0]+90,sun_panel[1]+3,sun_panel[2]-20,sun_panel[3]-3),35 if portrait else 32,30)
        d.rounded_rectangle(panel,28,fill=(4,30,49,220),outline=(93,171,186,160),width=2)
        occupied.append(rect(panel));pw=panel[2]-panel[0];ph=panel[3]-panel[1]
        left=panel[0]+30;right=panel[2]-30
        basin=basin_geometry(panel,progress);land=basin['land'];water=basin['water']
        d.polygon(land+[(right,panel[3]-40),(left,panel[3]-40)],fill='#486A67')
        d.line(land,fill='#D2C68C',width=7)
        d.polygon(water,fill=(49,167,194,160));d.line((water[0],water[1]),fill=CYAN,width=5)
        label('Coastline & ocean depth',(panel[0]+30,panel[1]+20,panel[2]-30,panel[1]+95),40,36)
        label('Schematic basin · not a tide forecast',(panel[0]+20,panel[3]-107,panel[2]-20,panel[3]-32),32,30)
        rec={'basin':basin,'basin_scope':'Qualitative original cross-section; no numerical local heights or forecast','geometry':q,'field_arrows':[]}
    else:
        # Neutral navy vignette in the useful space lets the 3-D sphere read clearly.
        shade=Image.new('RGBA',im.size);sd=ImageDraw.Draw(shade)
        ellipse=(cx-r*1.65,cy-r*1.33,cx+r*1.65,cy+r*1.33)
        sd.ellipse(ellipse,fill=(3,20,40,115));shade=shade.filter(ImageFilter.GaussianBlur(38));im.alpha_composite(shade)
        if kind in ('opening','envelope','recap'):env=ocean_envelope(im,q,.65 if kind=='opening' else progress)
        else:sphere(im,cx,cy,r,progress*.1);env=None
        moon(im,mx,my,mr);d=ImageDraw.Draw(im)
        occupied.append(rect((cx-r*1.20-12,cy-r-20,cx+r*1.20+12,cy+r+20)))
        occupied.append(rect((mx-mr-4,my-mr-4,mx+mr+4,my+mr+4)))
        label('Moon',(mx-80,my+mr+18,mx+80,my+mr+80),35,32)
        field=arrow_geometry(kind,progress,name,actual_onsets=actual_onsets)
        if kind in ('actual','relative'):
            for item in field:
                x0,y0=item['display_origin'];dx,dy=item['display_vector']
                d.ellipse((x0-6,y0-6,x0+6,y0+6),fill=WHITE)
                arrow(d,(x0,y0),(x0+dx,y0+dy),GOLD if kind=='actual' else CYAN,8)
                if abs(dx)>1:occupied.append(rect((min(x0,x0+dx)-4,y0-25,max(x0,x0+dx)+4,y0+25)))
            for x,copy in ((-1,'Far'),(0,'Centre'),(1,'Near')):
                xx=cx+x*r;label(copy,(xx-77,cy+46,xx+77,cy+110),35,32)
            if kind=='relative':
                d.ellipse((cx-15,cy-15,cx+15,cy+15),outline=CYAN,width=4)
            badge='ACTUAL ATTRACTION' if kind=='actual' else None
            subtitle='Sizes / distance exaggerated · one linear arrow scale' if kind=='actual' else ('First, use the centre as our reference' if progress<.22 else 'Arrows show differences · actual gravity stays Moonward')
        elif kind=='opening':
            badge=None;subtitle='Ocean model · sizes exaggerated'
        elif kind=='envelope':badge='A CONNECTED OCEAN RESPONSE';subtitle='Ideal ocean-covered Earth · bulges exaggerated'
        else:badge='ONE MOON · UNEQUAL ATTRACTION';subtitle='Two sides responding · local patterns vary'
        badge_box=(72,1090,900,1145) if portrait else (100,754,1820,800)
        sub_box=((72,1146,900,1220) if badge else (72,1100,900,1220)) if portrait else ((100,800,1820,849) if badge else (100,778,1820,849))
        if badge:label(badge,badge_box,31 if portrait else 28,28,color=GOLD,max_lines=1)
        label(subtitle,sub_box,30 if portrait else 29,27,max_lines=2)
        rec={'geometry':q,'field_arrows':field,'ocean_envelope':env}
    if caption:
        d=ImageDraw.Draw(im);d.rounded_rectangle(caption_box,26,fill=(4,25,43,235),outline=(81,151,166,130),width=2)
        occupied.append(rect(caption_box))
        label(caption,caption_box,50 if portrait else 46,44 if portrait else 42,max_lines=3)
    # Validate actual occupied ink, complete diagram/arrow extents and reading boxes.
    validated=layout(name,occupied);lock=brand_layer(name,str(logo_path));ink=lock.getbbox()
    safe=validated['safe'];sb=(safe['x'],safe['y'],safe['x']+safe['width'],safe['y']+safe['height'])
    if ink is None or not contains(sb,ink):raise ValueError('Actual transparent lockup escaped destination-safe region')
    im.alpha_composite(lock)
    rec.update(format=name,kind=kind,progress=progress,preview=preview,outer_glyphs=glyphs,occupied_rects=occupied,brand_ink=ink,layout=validated,
      artwork='New deterministic shaded ocean sphere, connected illustrative envelope, source-bound original coast plate; no human figures',
      scope='Representative frame geometry and glyph measurements; complete motion/hearing/platform review remains separate')
    return im.convert('RGB'),rec

def tokens(s):return re.findall(r"[\w]+(?:'[\w]+)*",s.lower().replace('’',"'"))

def measured_actual_onsets(timing):
    scene=next(s for s in timing['scenes'] if s['kind']=='actual')
    words=[(token,w['start_ms']) for w in timing['words'] for token in tokens(w['word']) if scene['start_ms']<=w['start_ms']<scene['end_ms']]
    phrases={'near':['near','the','moon'],'centre':['at',"earth's",'centre'],'far':['on','the','far','side']}
    result={}
    for key,phrase in phrases.items():
        matches=[i for i in range(len(words)-len(phrase)+1) if [w[0] for w in words[i:i+len(phrase)]]==phrase]
        if len(matches)!=1:raise ValueError('Actual-attraction beat needs one unambiguous measured phrase: '+key)
        result[key]=(words[matches[0]][1]-scene['start_ms'])/(scene['end_ms']-scene['start_ms'])
    if not 0<=result['near']<result['centre']<result['far']<1:raise ValueError('Actual gravity explanation order changed')
    return result

def bound(binding,base):
    p=Path(binding['path']);p=p if p.is_absolute() else base/p
    if not p.is_file() or sha(p)!=binding['sha256']:raise ValueError('Changed or missing source: '+str(p))
    return p

def compile_plan(path):
    path=Path(path).resolve();p=json.loads(path.read_text());base=path.parent
    if p.get('private') is not True or p.get('publication_approved') is not False or p.get('fps')!=30:raise ValueError('Private actual-audio30fps plan required')
    fnt=bound(p['font'],base);logo=bound(p['logo'],base);coast=bound(p['coast'],base)
    if sha(logo)!=LOGO_SHA:raise ValueError('Canonical logo mismatch')
    result={}
    for name in SIZES:
        v=p['formats'][name];audio=bound(v['narration'],base);transcript=bound(v['transcript'],base);tp=bound(v['timing'],base);t=json.loads(tp.read_text())
        probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(audio)]));ms=round(float(probe['format']['duration'])*1000)
        if t.get('timing_status')!='actual_audio_aligned' or t.get('audio_sha256')!=sha(audio) or t.get('duration_ms')!=ms or not t.get('method'):raise ValueError('Actual audio/timing lineage required')
        if tokens(transcript.read_text())!=tokens(' '.join(x['word'] for x in t['words'])):raise ValueError('Actual word transcript mismatch')
        if tokens(transcript.read_text())!=tokens(' '.join(x['text'] for x in t['cues'])):raise ValueError('Caption source mismatch')
        for key in ('scenes','cues'):
            cursor=0
            for item in t[key]:
                if item['start_ms']!=cursor or not cursor<item['end_ms']<=ms:raise ValueError('Incomplete actual timeline')
                cursor=item['end_ms']
            if cursor!=ms:raise ValueError('Incomplete actual timeline')
        if [s['kind'] for s in t['scenes']]!=list(KINDS):raise ValueError('Preserve all causal and real-coast beats')
        result[name]={'timing':t,'audio':audio,'duration_ms':ms,'actual_onsets':measured_actual_onsets(t)}
    return {'plan_path':path,'plan_sha256':sha(path),'font':fnt,'font_index':p['font'].get('index',FONT_INDEX),'logo':logo,'coast':coast,'formats':result}

def preview(output,plan=None):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True);records=[];compiled=compile_plan(plan) if plan else None
    for name in SIZES:
        for kind in KINDS:
            if compiled:
                t=compiled['formats'][name]['timing'];scene=next(s for s in t['scenes'] if s['kind']==kind);ms=scene['start_ms']+.7*(scene['end_ms']-scene['start_ms']);caption=next(c['text'] for c in t['cues'] if c['start_ms']<=ms<c['end_ms'])
            else:caption=EXAMPLES[kind]
            args={'font_path':compiled['font'],'font_index':compiled['font_index'],'logo_path':compiled['logo'],'coast_path':compiled['coast'],'actual_onsets':compiled['formats'][name]['actual_onsets']} if compiled else {}
            im,r=frame(kind,.70,name,caption=caption,preview=compiled is None,**args);file=output/f'{name}-{kind}.png';im.save(file)
            write(file.with_suffix('.json'),r);records.append({'path':str(file),'sha256':sha(file)})
    manifest={'status':'PRIVATE_PROOF_STILLS_NOT_COMPLETE_MOTION_REVIEW','renderer_sha256':sha(__file__),'coast_sha256':sha(compiled['coast'] if compiled else COAST),'plan_sha256':compiled['plan_sha256'] if compiled else None,'files':records,'new_audio':False,'publication_approved':False}
    write(output/'PROOF-MANIFEST.json',manifest);return manifest

def silent_body(plan,output):
    c=compile_plan(plan);output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True);outputs={}
    for name,f in c['formats'].items():
        w,h=SIZES[name];count=math.ceil(f['duration_ms']*.03);target=output/f'{name}-silent-body.mp4'
        cmd=['ffmpeg','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r','30','-i','-','-an','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-vf','scale=in_range=full:out_range=tv:out_color_matrix=bt709','-color_range','tv','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709','-movflags','+faststart',str(target)]
        child=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=subprocess.PIPE);si=ci=0;scenes=f['timing']['scenes'];cues=f['timing']['cues'];receipts=[]
        try:
            for i in range(count):
                ms=min(f['duration_ms']-1,i*1000/30)
                while ms>=scenes[si]['end_ms']:si+=1
                while ms>=cues[ci]['end_ms']:ci+=1
                s=scenes[si];p=(ms-s['start_ms'])/(s['end_ms']-s['start_ms'])
                im,r=frame(s['kind'],p,name,caption=cues[ci]['text'],font_path=c['font'],font_index=c['font_index'],logo_path=c['logo'],coast_path=c['coast'],actual_onsets=f['actual_onsets']);child.stdin.write(im.tobytes())
                if i%300==0:print(json.dumps({'format':name,'frame':i,'frames':count}),flush=True)
                if i==0 or i==count-1 or abs(ms-s['start_ms'])<1000/30:receipts.append({'frame':i,'receipt':r})
            child.stdin.close();err=child.stderr.read();code=child.wait()
            if code:raise RuntimeError(err.decode()[-2000:])
        except BaseException:
            child.kill();child.wait();raise
        outputs[name]={'path':str(target),'sha256':sha(target),'frames':count,'body_duration_seconds':count/30,'actual_audio_seconds':f['duration_ms']/1000,'frame_alignment_pad_seconds':count/30-f['duration_ms']/1000,'sample_receipts':receipts}
    m={'status':'PRIVATE_NEW_SILENT_BODY_FOR_COMPARISON','plan_sha256':c['plan_sha256'],'renderer_sha256':sha(__file__),'coast_sha256':sha(c['coast']),'outputs':outputs,'audio_appended':False,'END_appended':False,'publication_approved':False}
    write(output/'SILENT-BODY-MANIFEST.json',m);return m

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    a=s.add_parser('preview');a.add_argument('--output',required=True);a.add_argument('--plan')
    a=s.add_parser('validate');a.add_argument('plan')
    a=s.add_parser('silent-body');a.add_argument('plan');a.add_argument('--output',required=True)
    a=p.parse_args()
    if a.command=='preview':result=preview(a.output,a.plan)
    elif a.command=='validate':result={'status':'INPUTS_VALIDATED_NOT_RENDERED','plan_sha256':compile_plan(a.plan)['plan_sha256']}
    else:result=silent_body(a.plan,a.output)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
