"""Private retimed Tides validation; new speech never inherits old AAC acceptance."""
from fractions import Fraction
from pathlib import Path
import json, math, subprocess
from .release import PLAIN_SCHEMA, require, sha, bound_record, audio_packet_signature

def file_record(item, root):
    require(isinstance(item,dict) and item.get('file') and item.get('sha256'), 'Missing bound private record')
    return bound_record({'path':item['file'],'sha256':item['sha256']},root)

def load_record(item, root):
    p=file_record(item,root)
    return json.loads(p.read_text())

def cache_frames_gate(cache_path, cache, name):
    # A frozen manifest alone does not detect pixels changed after capture QA.
    for frame in cache['formats'][name]['frames']:
        bound_record({'path':str(cache_path.parent/frame['file']),
                      'sha256':frame['sha256']},cache_path.parent)

def source_links_gate(records, root):
    plan=json.loads(records['render_plan'].read_text())
    timing=json.loads(records['timing'].read_text())
    require(timing.get('timing_status')=='actual_audio_aligned'
            and timing.get('audio_sha256')==sha(records['narration'])
            and timing.get('source_script_sha256')==sha(records['script']),
            'Timing belongs to another native voice/script')
    for name in ('landscape','portrait'):
        for key,record in (('narration','narration'),('transcript','script'),('timing','timing')):
            require(bound_record(plan['formats'][name][key],root)==records[record],
                    'Render plan uses another '+name+' '+key)
    for key,record in (('raw_asr','raw_ASR'),('owner_dry_voice_decision','owner_dry_voice_decision')):
        require(bound_record(timing[key],root)==records[record],
                'Timing uses another '+key)
    require(bound_record(plan['owner_dry_voice_decision'],root)==records['owner_dry_voice_decision'],
            'Render plan uses another dry-voice decision')
    # Match the existing subtitle writer exactly, including actual cue times.
    def stamp(ms):
        hh,rem=divmod(ms,3600000);mm,rem=divmod(rem,60000);ss,sub=divmod(rem,1000)
        return f'{hh:02}:{mm:02}:{ss:02},{sub:03}'
    expected=''.join(f'{i+1}\n{stamp(c["start_ms"])} --> {stamp(c["end_ms"])}\n{c["text"]}\n\n'
                     for i,c in enumerate(timing['cues']) if c['kind']=='narration')
    # The final blank cue separator is optional in an SRT; words, cue numbers,
    # intermediate separators and timestamps must still match exactly.
    require(bool(expected) and records['captions'].read_text().rstrip('\n')==expected.rstrip('\n'),
            'English SRT differs from actual timing cues')

def pixel_format_gate(d, pixels, name, r, body_frames, root):
    p=load_record(pixels['formats'][name],root)
    require(p.get('state')=='DELIVERY_PIXEL_PASS' and p.get('schema')=='earnalism.tides.plain-v4.delivery-pixel-check.v1' and p.get('issues')==[] and p.get('bound_inputs_unchanged') is True,'Final source/picture review incomplete')
    require(p['final_sha256']==r['sha256'] and p['body_receipt_sha256']==r['body_receipt']['sha256'] and p['assembly_receipt_sha256']==r['assembly_receipt']['sha256'] and p['checker_sha256']==sha(d/'check_delivery_pixels.py') and p['fresh_reference_source_sha256']==sha(d/'retime.py') and p['rendered_body_retime_source_sha256']==r['retime_source']['sha256'],'Final pixel review bound to another source/video')
    require(p['checks']==body_frames and p['body_indices']==[0,body_frames-1] and p['matching_final_indices']==[0,2*(body_frames-1)] and (p['thumbnail']['width'],p['thumbnail']['height'])==(96,54),'Final whole-picture temporal coverage incomplete')
    tolerance=p['fixed_predeclared_tolerance']
    require(tolerance['mae_at_most']==6 and tolerance['maximum_pixel_error_at_most']==64 and p['maximum_mae']['mae']<=6 and p['maximum_pixel_error']<=64 and len(p['controls'])>=2 and all(c.get('detected') is True for c in p['controls']),'Final split/tile sensitivity failed')
    for path,digest in p['input_hashes'].items():
        bound_record({'path':path,'sha256':digest},root)
    if name=='portrait':
        require(all(p['input_hashes'].get(str(d/f))==sha(d/f) for f in ('portrait-framing-cache/MANIFEST.json','PORTRAIT_FRAMING.json')),'Effective portrait camera/cache evidence missing')
    for path_key,hash_key in (('reference_thumbnail_file','source_reference_thumbnail_sha256'),('source_frame_times_file','source_frame_times_sha256')):
        bound_record({'path':p[path_key],'sha256':p[hash_key]},root)

def capture_gate(d, m, root):
    c=load_record(m.get('capture_check'),root)
    require(c.get('schema')=='earnalism.tides.plain-v4.capture-check.v1' and c.get('state')=='RETIMED_CAPTURE_PASS','Current retimed source-pixel capture PASS missing')
    require(c['checker_sha256']==sha(d/'check_capture.py') and c['clock_sha256']==sha(d/'HARBOR_CLOCK.json'),'Capture source/clock changed')
    refs=d/'capture-references/REFERENCES.json'
    require(c['references_sha256']==sha(refs),'Independent reference inventory changed')
    refs=json.loads(refs.read_text());clock=json.loads((d/'HARBOR_CLOCK.json').read_text())
    for name in ('landscape','portrait'):
        cache_path=file_record(m['harbor_caches'][name],root);cache=json.loads(cache_path.read_text())
        require(cache_path==d/('portrait-framing-cache' if name=='portrait' else 'harbor-cache')/'MANIFEST.json','Wrong effective cache path')
        require(cache['schema']=='earnalism.tides.retimed-harbor-cache.v1' and cache['clock_sha256']==c['clock_sha256'] and set(cache['overlaysExcluded'])>={'captions','brand','qualifier'},'Wrong clean source cache')
        cache_frames_gate(cache_path,cache,name)
        r=refs['formats'][name];v=c['formats'][name]
        require(Path(r['cache_manifest']).resolve()==cache_path and r['cache_manifest_sha256']==sha(cache_path),'Independent reference bound to another cache')
        require([f['index'] for f in cache['formats'][name]['frames']]==[f['index'] for f in clock['frames']] and v['frames_checked']==len(clock['frames']) and v['issues']==[],'Incomplete clean source-frame review')
        require(set(v['max_anchor_MAE'])=={'sky','roof'} and all(x<=.1 for x in v['max_anchor_MAE'].values()) and all(v['controls'].get(k) is True for k in ('split_tile_detected','valid_moving_water_excluded')),'Static-anchor or split/tile control failed')
        endpoints=v['independent_endpoint_checks']
        require(len(endpoints)==2 and {e['index'] for e in endpoints}=={0,m['duration']['body_frames']-1} and all(e['pass'] is True and e['MAE']<=.02 and e['max_channel_error']<=2 and e['changed_pixel_fraction']<=.001 for e in endpoints),'Independent whole-picture endpoints missing')
        for f in r['frames']:
            bound_record({'path':str(d/'capture-references'/f['file']),'sha256':f['sha256']},root)
    return c

def check_plain_private(d, root):
    manifest=d/'FINAL_MANIFEST.json';m=json.loads(manifest.read_text())
    require(m.get('schema')==PLAIN_SCHEMA and m.get('private') is True and m.get('publication_approved') is False,'Expected unapproved private retimed candidate')
    capture=capture_gate(d,m,root)
    records={k:file_record(m[k],root) for k in ('narration','owner_dry_voice_decision','script','raw_ASR','timing','render_plan','captions','portrait_framing')}
    source_links_gate(records,root)
    decision=json.loads(records['owner_dry_voice_decision'].read_text())
    require(decision.get('owner_answer')=='Acceptable throughout' and decision['audio_sha256']==sha(records['narration']) and decision['script_sha256']==sha(records['script']),'Dry acceptance belongs to another voice/script')
    clock=m['duration'];body_frames=clock['body_frames'];final_frames=body_frames*2+180
    require(clock['body_fps']==30 and clock['final_fps']==60 and clock['END_seconds']==3 and clock['final_frames']==final_frames and abs(clock['final_seconds']-final_frames/60)<1e-9,'Retimed body/END clock differs')
    native=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(records['narration'])]))['streams']
    require(len(native)==1 and native[0]['codec_type']=='audio','Expected actual native voice only')
    native_seconds=Fraction(native[0]['duration_ts'])*Fraction(native[0]['time_base'])
    require(math.ceil(native_seconds*30)==body_frames and abs(float(native_seconds)-clock['native_voice_seconds'])<1e-9,'Body clock not derived from complete native speech')
    master=file_record(m['music']['master'],root);body_master=file_record(m['music']['body_master'],root)
    mix=load_record(m['music']['timing_correction_provenance'],root);load_record(m['music']['arrangement_provenance'],root)
    require(mix['native_voice_sha256']==sha(records['narration']) and mix['voice_gain_db']==0 and mix['speech_rate_pitch_EQ_changes'] is False and mix['body_frames']==body_frames and mix['master_samples']==final_frames*800 and mix['exact_END_PCM24_once'] is True and mix['master_PCM24_is_body_plus_END_exact'] is True,'Accepted voice or corrected PCM clock differs')
    require(mix['outputs']['soundtrack-master-1169f.wav']['sha256']==sha(master) and mix['outputs']['body-master-1169f.wav']['sha256']==sha(body_master),'Corrected master binding differs')
    pixels=load_record(m.get('delivery_pixel_check'),root)
    require(pixels.get('schema')=='earnalism.tides.plain-v4.delivery-pixel-check.v1' and pixels.get('state')=='DELIVERY_PIXEL_PASS','Current final-pixel PASS missing')
    identities=[]
    for name,size in [('landscape',(1920,1080)),('portrait',(1080,1920))]:
        r=m['formats'][name];video=file_record(r,root);body=load_record(r['body_receipt'],root);source=file_record(r['retime_source'],root);assembly=load_record(r['assembly_receipt'],root)
        pixel_format_gate(d,pixels,name,r,body_frames,root)
        body_path=bound_record(body,root)
        # The executed wrapper records self.path (base cache); its portrait
        # loader additionally uses the separately bound camera override. The
        # full fresh-source/final test above verifies that effective override.
        require(video==d/'final'/f'{name}.mp4' and body['schema']=='earnalism.tides.plain-v4.silent-body.v1' and body['frames']==body_frames and body['retime_source_sha256']==sha(source) and body['approved_drawing_source_sha256']==sha(root/'video_studio/tides_cinematic/renderer.py') and body['plan_sha256']==sha(records['render_plan']) and body['harbor_cache_sha256']==m['harbor_caches']['landscape']['sha256'] and body['rendered_frames_checked_for_actual_glyph_bounds_brand_clearance_and_field_signs']==body_frames,'Actual body source/timing/layout evidence differs')
        if name=='portrait':
            require(body.get('portrait_framing_cache_sha256')==m['harbor_caches'][name]['sha256'],'Rendered effective portrait cache differs')
        require(assembly.get('schema')=='earnalism.tides.private-assembly.v1' and assembly.get('synthetic_fixture') is False and assembly.get('private') is True and assembly.get('publication_approved') is False and bound_record(assembly['output'],root)==video,'Actual private assembly binding differs')
        require(assembly['input_hashes'].get(str(body_path))==sha(body_path) and assembly['input_hashes'].get(str(master))==sha(master) and assembly['soundtrack']['source']==str(master) and assembly['soundtrack']['filters'] is None and assembly['soundtrack']['speed_change'] is False and assembly['soundtrack']['pitch_shift'] is False,'Assembly audio or body binding differs')
        validation=assembly['validation'];end=assembly['ending']
        require(all(validation.get(k) is True for k in ('video_full_decode','audio_full_decode','continuous_decoded_frame_timestamps','faststart_moov_before_mdat')),'Executed decode/cadence/faststart evidence missing')
        require(end.get('decoded_frame_md5_equal') is True and end.get('master_PCM24_tail_matches_approved_sound') is True and end['frames']==180 and len(end['reference_frame_md5'])==180 and end['reference_frame_md5']==end['final_frame_md5'] and end['source_sha256']==sha(root/f'video_studio/assets/standard-intro/v1/{name}.mp4') and end['approved_sound_sha256']==sha(root/'video_studio/assets/standard-intro/v1/source-sound.wav'),'Exact canonical END changed')
        streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))['streams']
        require(len(streams)==2,'Expected one video and one audio stream')
        v=next(s for s in streams if s['codec_type']=='video');a=next(s for s in streams if s['codec_type']=='audio')
        duration=Fraction(int(v['duration_ts']))*Fraction(v['time_base'])
        require((v['codec_name'],v['width'],v['height'],v['pix_fmt'])==('h264',*size,'yuv420p') and Fraction(v['r_frame_rate'])==Fraction(v['avg_frame_rate'])==60 and int(v['nb_frames'])==final_frames,'Wrong final picture format/cadence')
        require(a['codec_name']=='aac' and a['sample_rate']=='48000' and a['channels']==2 and duration==Fraction(int(a['duration_ts']))*Fraction(a['time_base'])==Fraction(final_frames,60),'Wrong final audio/video clock')
        identities.append(audio_packet_signature(video))
    require(len(set(identities))==1,'New soundtrack packets differ between formats')
    return {'state':'PRIVATE_REVIEW_REQUIRES_ACCEPTANCE','manifest_sha256':sha(manifest),'source_capture':capture['state'],'final_pixels':pixels['state'],'soundtrack_packet_identity':True,'dry_voice':'Owner accepted exact bound native recording','listening':'New scored mix pending; no old AAC acceptance inherited','full_AV':'PENDING_OWNER_REVIEW','publication_approved':False,'scope':'Hash-bound current voice, timing, source capture, final pixels, common assembly, exact END and identical new AAC; no native Instagram or publication claim'}
