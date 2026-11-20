"""Pictorial coast-to-Earth-to-coast Tides film, with source-bound timing.

No slide panels, banner headings or grid globe. Texture maps are actual NASA
editorial source material, credited in the private rights receipt and film credit.
The tide model remains an explicitly exaggerated illustration, not a forecast.
"""
from pathlib import Path
from functools import lru_cache
import argparse
import json
import math
import subprocess

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from ..tides.model import actual_lunar_acceleration, relative_tidal_acceleration, illustrative_envelope_axes
from ..tides_rebuild import renderer as common

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
DEFAULT_OUTPUT=ROOT/'output/episodes/19-tides/rebuild-20261115/cinematic-v2'
SIZES=common.SIZES
CYAN='#99F3F2';GOLD='#FFDB92';WHITE='#F8FBF6'

def smooth(x):x=np.clip(x,0,1);return x*x*(3-2*x)
def rect(b):return common.rect(b)

@lru_cache(maxsize=8)
def texture(path):
    with Image.open(path) as im:return np.asarray(im.convert('RGB'),dtype=np.float32)/255

def sample(tex,u,v):
    """Continuous bilinear longitude/latitude sampling with a wrapped seam."""
    h,w=tex.shape[:2];x=np.mod(u,1)*(w-1);y=np.clip(v,0,1)*(h-1)
    x0=x.astype(np.int32);y0=y.astype(np.int32);x1=(x0+1)%w;y1=np.minimum(y0+1,h-1)
    fx=(x-x0)[...,None];fy=(y-y0)[...,None]
    return (tex[y0,x0]*(1-fx)+tex[y0,x1]*fx)*(1-fy)+(tex[y1,x0]*(1-fx)+tex[y1,x1]*fx)*fy

@lru_cache(maxsize=8)
def space(size):
    w,h=size;yy,xx=np.mgrid[:h,:w].astype(np.float32);x=xx/w;y=yy/h
    # Broad atmospheric/nebular light is part of the full picture, not a backing
    # rectangle. It preserves the canonical dark-lettered logo's readability.
    glow=np.exp(-((x-.80)/.42)**2-((y-.14)/.21)**2)
    blue=np.exp(-((x-.27)/.64)**2-((y-.70)/.55)**2)
    base=np.stack([4+178*glow+1*blue,9+182*glow+10*blue,22+171*glow+20*blue],axis=-1)
    im=Image.fromarray(np.clip(base,0,255).astype(np.uint8),'RGB').convert('RGBA');d=ImageDraw.Draw(im)
    rng=np.random.default_rng(304)
    for a,b,r,light in zip(rng.uniform(0,w,170),rng.uniform(0,h,170),rng.choice([.6,.8,1,1.3],170),rng.integers(75,170,170)):
        d.ellipse((a-r,b-r,a+r,b+r),fill=(int(light),int(light+25),int(light+35),200))
    return im

@lru_cache(maxsize=8)
def coast_plate(path,size):
    with Image.open(path) as im:
        # Portrait independently favors the pier side; it is not a crop of the
        # finished landscape composition or any of its text/animation layers.
        return ImageOps.fit(im.convert('RGBA'),size,Image.Resampling.LANCZOS,centering=(.86 if size[1]>size[0] else .5,.50))

@lru_cache(maxsize=8)
def open_water_mask(path,size):
    """Manually traced conservative water-only region of the actual coast art.

    The left rock bank, bottom foreground rocks and entire original pier/post
    region are excluded. Feathering is multiplied by the original hard mask,
    so animated samples cannot leak into an excluded shore or pier pixel.
    """
    with Image.open(path) as source:
        w,h=source.size;mask=Image.new('L',(w,h),0);d=ImageDraw.Draw(mask)
        polygon=[(.22,.46),(.43,.42),(.70,.43),(.85,.43),(.85,.69),(.91,.75),(.80,.80),(.63,.86),(.36,.81),(.28,.71),(.22,.66)]
        d.polygon([(round(x*w),round(y*h)) for x,y in polygon],fill=255)
        inside=mask.filter(ImageFilter.MinFilter(21)).filter(ImageFilter.GaussianBlur(12))
        mask=ImageChops.multiply(mask,inside)
        return np.asarray(ImageOps.fit(mask,size,Image.Resampling.LANCZOS,centering=(.86 if size[1]>size[0] else .5,.50)),dtype=np.float32)/255

@lru_cache(maxsize=8)
def clean_water_texture(path,size):
    with Image.open(path) as source:
        w,h=source.size
        # This source patch contains only central open sea, never pier/rock
        # pixels that could be dragged into a different image location.
        patch=source.convert('RGB').crop((round(w*.38),round(h*.48),round(w*.72),round(h*.76)))
        return np.asarray(ImageOps.fit(patch,size,Image.Resampling.LANCZOS),dtype=np.float32)

def cinematic_coast(name,progress,coast_path):
    """Fixed original coastline and pilings, with a moving foreground sea level.

    This shot illustrates time-compressed water-level change. Its unnumbered
    gauge, level amplitude and timing are not a real site's tidal observation.
    """
    w,h=SIZES[name];portrait=h>w;im=coast_plate(str(coast_path),(w,h)).copy()
    yy,xx=np.mgrid[:h,:w].astype(np.float32)
    haze=np.exp(-((xx/w-.80)/.55)**2-((yy/h-.14)/.20)**2)*88
    sky=Image.new('RGBA',(w,h),(210,225,216,0));sky.putalpha(Image.fromarray(haze.astype(np.uint8),'L'));im.alpha_composite(sky)
    # Independent fixed foreground timber piling and unnumbered tide gauge.
    cx=.31*w if portrait else .29*w;top=.31*h if portrait else .24*h
    bottom=(.68 if portrait else .80)*h;radius=.036*w if portrait else .025*w
    draw=ImageDraw.Draw(im)
    postbox=(round(cx-radius),round(top),round(cx+radius),round(bottom))
    pw=postbox[2]-postbox[0];ph=postbox[3]-postbox[1]
    yy,xx=np.mgrid[:ph,:pw].astype(np.float32);t=(xx-pw/2)/(pw/2)
    cyl=np.sqrt(np.clip(1-t*t,0,1));grain=np.sin(xx*.31+np.sin(yy*.019)*3)+.4*np.sin(xx*.99+yy*.015)
    weather=5*np.sin(xx*1.7+np.sin(yy*.031)*2)+4*np.sin(xx*.11+yy*.067)
    rgb=np.stack([59+66*cyl+6*grain+weather,43+50*cyl+4*grain+weather*.8,26+29*cyl+3*grain+weather*.6],axis=-1)
    alpha=(np.abs(t)<=1)*255
    post=Image.fromarray(np.dstack([np.clip(rgb,0,255),alpha]).astype(np.uint8),'RGBA')
    im.alpha_composite(post,(postbox[0],postbox[1]));draw=ImageDraw.Draw(im)
    draw.ellipse((cx-radius,top-radius*.24,cx+radius,top+radius*.24),fill='#A18B5D',outline='#4B3C27',width=2)
    gauge=(cx+radius*.13,top+ph*.18,cx+radius*.65,top+ph*.89)
    draw.rounded_rectangle(gauge,3,fill='#E9E5CE',outline='#555545',width=2)
    for i in range(15):
        y0=gauge[1]+(gauge[3]-gauge[1])*(i+1)/16
        draw.line((gauge[0],y0,gauge[0]+(gauge[2]-gauge[0])*(.95 if i%4==0 else .58),y0),fill='#17383B',width=3)
    # Rise is monotonic in the opening, much gentler in the closing shore shot.
    level=((.64 if portrait else .69)-.115*float(smooth(progress)))*h
    # Photograph-derived water patch blends into the same sea, with no moving
    # piling/shore pixels. Only a local foreground surface changes position.
    source=clean_water_texture(str(coast_path),(w,h))
    row0=max(0,min(h-2,round(level)));rows=h-row0
    yy,xx=np.mgrid[:rows,:w].astype(np.float32)
    normalized_y=yy/max(1,rows-1)
    sy=np.clip(h*.53+normalized_y*h*.17+2*np.sin(xx*.016+progress*6),0,h-1).astype(np.int32)
    sx=np.clip(xx+4*np.sin(yy*.07+progress*9),0,w-1).astype(np.int32)
    sea=source[sy,sx]*np.array([.76,.94,1.03])+np.array([0,3,6])
    # Smooth elliptical extent leaves the original far shore and rock edges fixed.
    mask=np.exp(-((xx-cx)/(w*.29))**4)*np.clip(yy/18,0,1)*.94
    mask*=open_water_mask(str(coast_path),(w,h))[row0:]
    sea_layer=Image.fromarray(np.dstack([np.clip(sea,0,255),mask*255]).astype(np.uint8),'RGBA')
    im.alpha_composite(sea_layer,(0,row0));draw=ImageDraw.Draw(im)
    # An attached reflected ripple/wet edge makes the rise visible at a fixed post.
    for j in range(4):
        rad=radius*(1.5+j*.62)+float(progress)*radius*.12
        draw.arc((cx-rad,level-6-j*4,cx+rad,level+8+j*4),0,180,fill=(169,214,215,190-j*24),width=2)
    return im,{'fixed_piling_bounds':postbox,'fixed_gauge_bounds':gauge,'water_level_y':level,'water_mask':'Conservative manually traced actual-art water polygon; feathered only inside; excludes original shore, rocks and pier','time_compressed':True,'actual_site_forecast':False}

def planet(im,cx,cy,r,path,longitude=0,*,ideal=0,moon=False,opacity=1):
    """Texture an orthographic 3-D sphere with continuous lighting and atmosphere."""
    w,h=im.size;pad=20 if not moon else 5
    x0=max(0,int(cx-r-pad));x1=min(w,int(cx+r+pad+1));y0=max(0,int(cy-r-pad));y1=min(h,int(cy+r+pad+1))
    if x0>=x1 or y0>=y1:return None
    yy,xx=np.mgrid[y0:y1,x0:x1].astype(np.float32);x=(xx-cx)/r;y=(yy-cy)/r
    rho2=x*x+y*y;rho=np.sqrt(rho2);z=np.sqrt(np.clip(1-rho2,0,1));inside=rho2<=1
    lon=np.arctan2(x,z)+longitude;lat=np.arcsin(np.clip(-y,-1,1))
    u=(lon+math.pi)/(2*math.pi);v=.5-lat/math.pi
    albedo=sample(texture(str(path)),u,v)
    if ideal:
        # Geography disappears only in the visibly labelled ideal-ocean model.
        # Cloud/detail luminance provides depth; no real coastline is submerged.
        lum=albedo.mean(axis=-1)
        ocean=np.stack([.025+.05*lum,.18+.14*lum,.30+.18*lum],axis=-1)
        cloud=np.clip((lum-.67)/.25,0,1)[...,None]
        ocean=ocean*(1-cloud*.65)+np.ones_like(ocean)*cloud*.65
        albedo=albedo*(1-ideal)+ocean*ideal
    dot=np.clip(-.33*x-.28*y+.90*z,0,1)
    light=.18+.95*dot
    linear=np.power(albedo,2.2)*light[...,None]
    if not moon:
        # Ocean reflection and a blue atmospheric rim are qualitative lighting.
        water=(albedo[...,2]>albedo[...,0]*1.35)&(albedo[...,2]>albedo[...,1]*1.08)
        spec=np.maximum(0,-.16*x-.14*y+.977*z)**80*water*.12
        linear+=spec[...,None]*np.array([.74,.88,1.0])
        rim=np.power(1-z,3.5)*.25
        linear+=rim[...,None]*np.array([.05,.28,.62])
    rgb=np.power(np.clip(linear,0,1),1/2.2)*255
    edge=np.clip((1-rho)*r+1,0,1)
    if not moon:
        outer=np.exp(-np.maximum(0,rho-1)*r/5)*.5
        atmosphere=(rho>1)&(rho<1+pad/r)
        rgb=np.where(atmosphere[...,None],np.array([71,137,191]),rgb)
        edge=np.where(atmosphere,outer,edge)
    a=edge*255*opacity
    tile=Image.fromarray(np.dstack([np.clip(rgb,0,255),a]).astype(np.uint8),'RGBA')
    im.alpha_composite(tile,(x0,y0))
    return (cx-r-pad,cy-r-pad,cx+r+pad,cy+r+pad)

def composition(name):
    if name=='portrait':return {'cx':410.,'cy':800.,'r':250.,'mx':815.,'my':800.,'mr':55.}
    return {'cx':740.,'cy':490.,'r':310.,'mx':1510.,'my':490.,'mr':92.}

def arrow(draw,a,b,color,width=8):return common.arrow(draw,a,b,color,width)

def model_envelope(im,q,progress):
    """A connected luminous ellipsoid around an explicitly ideal ocean Earth."""
    cx,cy,r=q['cx'],q['cy'],q['r'];stretch=.035+.13*float(smooth(progress));a,b=illustrative_envelope_axes(stretch,r)
    layer=Image.new('RGBA',im.size);d=ImageDraw.Draw(layer)
    # Nested translucent contours shade an attached, continuous water layer.
    for j in range(22,0,-1):
        f=j/22;aa=r*.84+(a-r*.84)*f;bb=r*.84+(b-r*.84)*f
        d.ellipse((cx-aa,cy-bb,cx+aa,cy+bb),fill=(28+int(12*(1-f)),126+int(40*(1-f)),162+int(35*(1-f)),int(35+75*(1-f))))
    im.alpha_composite(layer);d=ImageDraw.Draw(im)
    d.ellipse((cx-a,cy-b,cx+a,cy+b),outline=(75,174,210,165),width=2)
    d.arc((cx-a,cy-b,cx+a,cy+b),185,352,fill=(157,242,241,220),width=3)
    d.arc((cx-a,cy-b,cx+a,cy+b),3,170,fill=(75,174,210,170),width=2)
    return {'outer_axes':[a,b],'inner_radius':r*.84,'continuous':b>r*.84,'physical_fluid_prediction':False}

def field_records(q,kind,progress,onsets):
    centre=actual_lunar_acceleration((0,0))[0];r=q['r'];out=[]
    rel=max(abs(relative_tidal_acceleration((-1,0))[0]),abs(relative_tidal_acceleration((1,0))[0]))
    for x,label in ((-1,'Far'),(0,'Centre'),(1,'Near')):
        origin=(q['cx']+x*r,q['cy'])
        if kind=='actual':
            physical=actual_lunar_acceleration((x,0));scale=.30*r/centre;key={-1:'far',0:'centre',1:'near'}[x]
            reveal=float(smooth((progress-onsets[key])/.12));vector=(physical[0]*scale*reveal,0)
        else:
            physical=relative_tidal_acceleration((x,0));scale=.30*r/rel
            reveal=float(smooth((progress-(.22 if x>=0 else .41))/.12));vector=(physical[0]*scale*reveal,0)
        out.append({'label':label,'origin':origin,'physical':physical,'scale':scale,'vector':vector,'reveal':reveal,'frame':'actual_Moonward' if kind=='actual' else 'centre_relative_enlarged'})
    return out

def shadow_text(im,copy,bounds,px,minimum=None,**kwargs):
    # Only a soft glyph shadow, no reading card or coloured headline banner.
    shadow=Image.new('RGBA',im.size)
    common.text(shadow,copy,tuple(v+2 if i in (0,2) else v+3 for i,v in enumerate(bounds)),px,minimum,color=(0,8,17,230),**kwargs)
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(3)))
    return common.text(im,copy,bounds,px,minimum,**kwargs)

def frame_at(ms,name,compiled):
    w,h=SIZES[name];portrait=h>w;f=compiled['formats'][name];t=f['timing'];ms=min(t['duration_ms']-1,max(0,float(ms)))
    scene=next(s for s in t['scenes'] if s['start_ms']<=ms<s['end_ms']);kind=scene['kind'];p=(ms-scene['start_ms'])/(scene['end_ms']-scene['start_ms']);cue=next(c for c in t['cues'] if c['start_ms']<=ms<c['end_ms']);caption=cue['text']
    q=composition(name);occupied=[];glyphs=[];record={'scene':kind,'progress':p,'ms':ms,'source_caption':caption}
    font_args={'font_path':compiled['font'],'font_index':compiled['font_index']}
    def label(copy,bounds,size,minimum=None,**kw):
        g=shadow_text(im,copy,bounds,size,minimum,**font_args,**kw);glyphs.append(g);occupied.extend(rect(b) for b in g['ink']);return g
    if kind=='opening' and ms<2700:
        im,coast=cinematic_coast(name,ms/2700,compiled['coast']);record['coast_action']=coast
        occupied.append(rect(coast['fixed_gauge_bounds']))
        qualifier='Time compressed · illustrative shore'
    elif kind=='coast':
        im,coast=cinematic_coast(name,.25+.45*p,compiled['coast']);record['coast_action']=coast
        occupied.append(rect(coast['fixed_gauge_bounds']))
        # One transient relevant label at a time; no extra text card.
        qualifier='Coastline & depth' if p<.43 else ('The Sun contributes' if p<.80 else 'Local tide patterns vary')
    else:
        im=space((w,h)).copy();longitude=.35+ms/1000*.010
        if kind=='opening':
            z=float(smooth((ms-2700)/2500));r0=max(w,h)*1.35
            rr=r0*(1-z)+q['r']*z
            top=h*.45*(1-z)+(q['cy']-q['r'])*z
            dynamic={**q,'r':rr,'cx':w*.52*(1-z)+q['cx']*z,'cy':rr+top}
            if ms<3600:
                coast,_=cinematic_coast(name,1,compiled['coast']);im=Image.blend(coast,im,float(smooth((ms-2700)/900)))
            planet(im,dynamic['cx'],dynamic['cy'],dynamic['r'],compiled['earth'],longitude,opacity=float(smooth((ms-2700)/600)))
            if z>.72:planet(im,q['mx'],q['my'],q['mr'],compiled['moon'],0,moon=True,opacity=float(smooth((z-.72)/.28)))
            record['camera_pullback']={'zoom':z,'earth_radius':dynamic['r']};qualifier='Sizes / distance exaggerated'
        elif kind in ('envelope','recap'):
            record['envelope']=model_envelope(im,q,p if kind=='envelope' else .9)
            planet(im,q['cx'],q['cy'],q['r']*.84,compiled['earth'],longitude,ideal=1)
            planet(im,q['mx'],q['my'],q['mr'],compiled['moon'],0,moon=True)
            qualifier='Ideal ocean model · bulges exaggerated'
            occupied.append(rect((q['cx']-q['r']*1.17-6,q['cy']-q['r']-10,q['cx']+q['r']*1.17+6,q['cy']+q['r']+10)))
        else:
            planet(im,q['cx'],q['cy'],q['r'],compiled['earth'],longitude)
            planet(im,q['mx'],q['my'],q['mr'],compiled['moon'],0,moon=True)
            arrows=field_records(q,kind,p,f['actual_onsets']);draw=ImageDraw.Draw(im)
            for a in arrows:
                x,y=a['origin'];dx,dy=a['vector'];draw.ellipse((x-5,y-5,x+5,y+5),fill=WHITE)
                arrow(draw,(x,y),(x+dx,y+dy),GOLD if kind=='actual' else CYAN,8)
                if abs(dx)>1:occupied.append(rect((min(x,x+dx)-3,y-24,max(x,x+dx)+3,y+24)))
                if a['reveal']>.01 or a['label']=='Centre':
                    label(a['label'],(x-72,y+37,x+72,y+102),35,32)
            record['field']=arrows
            if kind=='relative':
                draw.ellipse((q['cx']-14,q['cy']-14,q['cx']+14,q['cy']+14),outline=CYAN,width=4)
                qualifier='Relative to Earth’s centre · actual gravity is Moonward'
                if p<.22:label('Change the reference',(72,450,900,530) if portrait else (190,190,1300,280),43,39)
            else:qualifier='Actual attraction · sizes / distance exaggerated'
            occupied.append(rect((q['cx']-q['r']-12,q['cy']-q['r']-12,q['cx']+q['r']+12,q['cy']+q['r']+12)))
        if kind!='opening' or ms>=5200:
            label('Moon',(q['mx']-80,q['my']+q['mr']+18,q['mx']+80,q['my']+q['mr']+81),35,32)
            occupied.append(rect((q['mx']-q['mr']-5,q['my']-q['mr']-5,q['mx']+q['mr']+5,q['my']+q['mr']+5)))
    # A natural full-width bottom luminance falloff supports speech captions.
    yy=np.arange(h)[:,None];fade=np.clip((yy-(h*.59 if portrait else h*.69))/(h*.20),0,1)*145
    shadow=Image.new('RGBA',(w,h),(0,7,17,0));shadow.putalpha(Image.fromarray(np.broadcast_to(fade.astype(np.uint8),(h,w)).copy(),'L'));im.alpha_composite(shadow)
    # Transient scientific qualifications remain readable but subordinate.
    if qualifier:
        on_coast=(kind=='coast' or (kind=='opening' and ms<2700))
        bounds=((72,400,900,496) if portrait else (90,200,1380,290)) if on_coast else ((72,1120,900,1216) if portrait else (90,778,1830,846))
        label(qualifier,bounds,31 if portrait else 30,28,max_lines=2)
    if caption:label(caption,(72,1256,900,1500) if portrait else (70,860,1850,1032),50 if portrait else 46,44 if portrait else 42,max_lines=3)
    # Suppress bright source-sky noise behind the canonical full lockup with the
    # scene's existing atmospheric light, not an asset-specific backing shape.
    brand=common.brand_layer(name,str(compiled['logo']));im.alpha_composite(brand)
    safe=common.layout(name,occupied)
    record.update(format=name,glyphs=glyphs,occupied=occupied,layout=safe,brand_ink=brand.getbbox(),picture_treatment='Pictorial 3-D texture projection and time-compressed shore action; no slide/card composition',caption_timing_sha256=common.sha(f['timing_path']) if f.get('timing_path') else None)
    return im.convert('RGB'),record

def compile_plan(path):
    c=common.compile_plan(path);p=json.loads(Path(path).read_text());base=Path(path).parent
    c['earth']=common.bound(p['earth_texture'],base);c['moon']=common.bound(p['moon_texture'],base);c['rights']=common.bound(p['texture_rights'],base)
    for name in SIZES:
        b=p['formats'][name]['timing'];c['formats'][name]['timing_path']=common.bound(b,base)
    return c

def proofs(plan,output):
    c=compile_plan(plan);output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True);files=[]
    for name in SIZES:
        for tag,ms in [('shore-rise',1600),('pullback',4200),('actual',15800),('reference-change',19000),('ideal-response',36600),('real-coast',46300)]:
            im,receipt=frame_at(ms,name,c);p=output/f'{name}-{tag}.png';im.save(p);common.write(p.with_suffix('.json'),receipt)
            files.append({'path':str(p),'sha256':common.sha(p),'source_ms':ms})
    record={'state':'PRIVATE_CINEMATIC_PROOF_STILLS_NOT_ACCEPTED','source_plan_sha256':c['plan_sha256'],'renderer_sha256':common.sha(__file__),'files':files,'original_audio_unchanged':True,'no_model_training_or_inference':True,'publication_approved':False}
    common.write(output/'PROOFS.json',record);return record

def render_segment(plan,output,name,start_ms,end_ms,max_width=1080):
    c=compile_plan(plan);output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True);w,h=SIZES[name];ratio=min(1,max_width/w);ow=round(w*ratio)//2*2;oh=round(h*ratio)//2*2
    frames=math.ceil((end_ms-start_ms)*.03)
    command=['ffmpeg','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{ow}x{oh}','-r','30','-i','-','-an','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(output)]
    child=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for i in range(frames):
            ms=start_ms+i*1000/30;im,_=frame_at(ms,name,c)
            if im.size!=(ow,oh):im=im.resize((ow,oh),Image.Resampling.LANCZOS)
            child.stdin.write(im.tobytes())
            if i%60==0:print(json.dumps({'proof_format':name,'frame':i,'frames':frames}),flush=True)
        child.stdin.close();err=child.stderr.read();code=child.wait()
        if code:raise RuntimeError(err.decode()[-2000:])
    except BaseException:child.kill();child.wait();raise
    result={'status':'PRIVATE_SILENT_MOTION_PROOF_NOT_COMPLETE_AV_REVIEW','path':str(output),'sha256':common.sha(output),'source_plan_sha256':c['plan_sha256'],'renderer_sha256':common.sha(__file__),'format':name,'width':ow,'height':oh,'frames':frames,'fps':30,'source_start_ms':start_ms,'source_end_ms':end_ms,'audio_appended':False,'END_appended':False,'publication_approved':False}
    common.write(output.with_suffix('.json'),result);return result

def silent_body(plan,output):
    """Thin full-duration/native-size wrapper; still no audio, END or release."""
    c=compile_plan(plan);output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True);outputs={}
    for name,data in c['formats'].items():
        target=output/f'{name}-silent-body.mp4'
        result=render_segment(plan,target,name,0,data['duration_ms'],max_width=SIZES[name][0])
        seconds=result['frames']/30;actual=data['duration_ms']/1000
        outputs[name]={'file':target.name,'path':str(target),'sha256':result['sha256'],'frames':result['frames'],
          'body_duration_seconds':seconds,'actual_audio_seconds':actual,
          'frame_alignment_pad_seconds':seconds-actual,'width':result['width'],'height':result['height'],'fps':30}
    result={'schema':'earnalism.tides.cinematic.silent-body.v1','status':'PRIVATE_SILENT_BODY_FOR_ROOT_ASSEMBLY',
      'private':True,'publication_approved':False,'plan_sha256':c['plan_sha256'],'renderer_sha256':common.sha(__file__),
      'outputs':outputs,'audio_appended':False,'END_appended':False,
      'qualification':'Full-duration silent picture export only; full AV/listening and destination review remain separate'}
    common.write(output/'SILENT-BODY-MANIFEST.json',result);return result

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    a=s.add_parser('proofs');a.add_argument('plan');a.add_argument('--output',required=True)
    a=s.add_parser('motion-proof');a.add_argument('plan');a.add_argument('--output',required=True);a.add_argument('--format',choices=list(SIZES),default='landscape');a.add_argument('--start-ms',type=int,default=0);a.add_argument('--end-ms',type=int,default=10000);a.add_argument('--max-width',type=int,default=1080)
    a=s.add_parser('silent-body');a.add_argument('plan');a.add_argument('--output',required=True)
    a=p.parse_args()
    if a.command=='proofs':result=proofs(a.plan,a.output)
    elif a.command=='silent-body':result=silent_body(a.plan,a.output)
    else:result=render_segment(a.plan,a.output,a.format,a.start_ms,a.end_ms,a.max_width)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
