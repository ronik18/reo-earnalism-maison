"""Exact private Tides preflight; never supplies listening or release consent."""
from pathlib import Path
from fractions import Fraction
import hashlib,json,subprocess

SCHEMA='earnalism.tides-rebuild-private-kit.v1'
HARBOR_SCHEMA='earnalism.tides.harbor-v3.corrected-pair.v1'
PLAIN_SCHEMA='earnalism.tides.plain-language-v4.private-delivery.v1'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(test,message):
 if not test:raise ValueError(message)
def bound_files(folder,files):
 for name,digest in files.items():
  p=(folder/name).resolve()
  require(p.is_relative_to(folder) and p.is_file() and sha(p)==digest,'Changed or escaping bound file: '+name)

def bound_record(item,root):
 p=Path(item['path']).resolve()
 require(p.is_relative_to(root) and p.is_file() and sha(p)==item['sha256'],'Changed or escaping bound receipt/media: '+str(p))
 return p

def packet_hash(video,kind):
 return subprocess.check_output(['ffmpeg','-v','error','-nostdin','-i',str(video),'-map','0:'+kind+':0','-c','copy','-f','hash','-hash','sha256','-']).decode().strip().split('=',1)[-1]

def audio_packet_signature(video):
 packets=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','a:0','-show_packets','-show_data_hash','sha256','-show_entries','packet=pts,dts,duration,size,data_hash','-of','json',str(video)]))['packets']
 return len(packets),hashlib.sha256(json.dumps(packets,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def check_harbor_private(d,root):
 """Read the actual harbor receipts; retain the single existing private gate."""
 manifest=d/'FINAL_MANIFEST.json';m=json.loads(manifest.read_text())
 require(m.get('schema')==HARBOR_SCHEMA and m.get('publication_approved') is False and m.get('uploads_or_publications')==0,'Expected an unapproved private corrected harbor pair')
 cache_path=bound_record(m['clean_cache'],root);cache=json.loads(cache_path.read_text())
 require(cache.get('schema')=='earnalism.tides.harbor-clean-cache.v1' and set(cache.get('overlaysExcluded',[]))>={'captions','brand','qualifier'},'Expected actual clean harbor cache')
 capture_path=bound_record(m['independent_clean_cache_capture_review'],root);capture=json.loads(capture_path.read_text())
 require(capture.get('state')=='BOUNDED_CAPTURE_REGRESSION_PASS' and capture.get('cache_manifest_sha256')==sha(cache_path) and Path(capture['cache_manifest']).resolve()==cache_path,'Current source-pixel capture PASS missing or bound to another cache')
 bound_record({'path':capture['independent_references'],'sha256':capture['references_sha256']},root)
 require(capture['checker_sha256']==sha(root/'video_studio/tides_harbor/capture_check.py'),'Capture checker changed')
 require(set(cache['sourceHashes'])=={'scene.mjs','index.jsx','render.mjs','package-lock.json'},'Unexpected harbor source inventory')
 bound_files(root/'video_studio/tides_harbor',cache['sourceHashes'])
 bridge=bound_record({'path':cache['bridgePlan'],'sha256':cache['bridgePlanSha256']},root)
 plan=json.loads(bridge.read_text());bound_record({'path':plan['render_plan'],'sha256':plan['render_plan_sha256']},root)
 require(m['source_renderer_sha256']==sha(root/'video_studio/tides_cinematic/renderer.py') and m['bridge_sha256']==sha(root/'video_studio/tides_harbor/integrate.py') and m['assembly_wrapper_sha256']==sha(d/'assemble_one.py'),'Frozen renderer/bridge/assembly source changed')
 identities=[]
 for name,size in [('landscape',(1920,1080)),('portrait',(1080,1920))]:
  c=capture['formats'][name];endpoints=c['whole_endpoint_checks']
  require(c['frames_checked']==366 and c['issues']==[] and set(c['max_anchor_mae'])=={'sky','roof'} and all(x==0 for x in c['max_anchor_mae'].values()) and len(endpoints)==2 and all(x.get('pass') is True and x['mean_absolute_channel_error']==0 and x['max_channel_error']==0 and x['changed_pixel_fraction']==0 for x in endpoints),'Bounded clean-cache pixel checks are incomplete')
  r=m['outputs'][name];video=bound_record(r,root)
  require(video==d/f'{name}.mp4' and json.loads((d/f'{name}.delivery.json').read_text())==r,'Final delivery receipt differs from pair manifest')
  require(r.get('schema')=='earnalism.tides.harbor-v3.private-delivery.v1' and r.get('publication_approved') is False and r.get('uploaded_or_published') is False,'Expected actual private harbor delivery receipt')
  body_receipt=bound_record(r['body_source_receipt'],root);body=json.loads(body_receipt.read_text());body_path=bound_record(body,root)
  require(body_path==d/f'{name}-silent-body.mp4' and body['cache_manifest_sha256']==sha(cache_path) and body['plan_sha256']==plan['render_plan_sha256'] and body['frozen_renderer_sha256']==m['source_renderer_sha256'] and body['bridge_sha256']==m['bridge_sha256'] and body['baseline_body_sha256']==plan['baseline_body_hashes'][name],'Body is not bound to this source/cache/baseline')
  require(body.get('changed_frames')==366 and body.get('unchanged_decoded_YUV_frames_verified')==1295 and len(body['unchanged_frame_hashes'])==1295,'Executed unchanged-source picture evidence missing')
  assembly_path=bound_record(r['common_assembly_receipt'],root);assembly=json.loads(assembly_path.read_text());assembled=bound_record(assembly['output'],root)
  require(assembly.get('schema')=='earnalism.tides.private-assembly.v1' and assembly.get('synthetic_fixture') is False and assembly.get('private') is True and assembly.get('publication_approved') is False,'Expected actual private common assembly receipt')
  require(assembly['input_hashes'].get(str(body_path))==body['sha256'] and assembly['assembler_sha256']==r['common_assembler_sha256'],'Common assembly source binding differs')
  master=bound_record({'path':assembly['soundtrack']['source'],'sha256':r['accepted_soundtrack_master_sha256']},root)
  require(assembly['input_hashes'].get(str(master))==sha(master),'Accepted master binding differs')
  validation=assembly['validation'];ending=assembly['ending']
  require(all(validation.get(k) is True for k in ['video_full_decode','audio_full_decode','continuous_decoded_frame_timestamps','faststart_moov_before_mdat']),'Missing executed full decode/cadence/faststart evidence')
  require(ending.get('decoded_frame_md5_equal') is True and ending.get('master_PCM24_tail_matches_approved_sound') is True and ending.get('frames')==180 and len(ending['reference_frame_md5'])==180 and ending['reference_frame_md5']==ending['final_frame_md5'],'Exact approved END evidence missing')
  require(ending['source_sha256']==sha(root/f'video_studio/assets/standard-intro/v1/{name}.mp4') and ending['approved_sound_sha256']==sha(root/'video_studio/assets/standard-intro/v1/source-sound.wav'),'Canonical END changed')
  require(packet_hash(video,'v')==packet_hash(assembled,'v'),'Final video packets differ from checked common assembly')
  require(all(r.get(k) is True for k in ['video_full_decode','audio_full_decode','continuous_decoded_PTS','exact_180_END_decoded_frames','faststart']),'Missing final remux execution evidence')
  streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))['streams']
  require(len(streams)==2,'Expected exactly one video and one audio stream')
  v=next(s for s in streams if s['codec_type']=='video');a=next(s for s in streams if s['codec_type']=='audio')
  require((v['codec_name'],v['width'],v['height'],v['pix_fmt'])==('h264',*size,'yuv420p') and Fraction(v['avg_frame_rate'])==60 and Fraction(v['r_frame_rate'])==60,'Wrong video delivery format/cadence')
  duration=Fraction(int(v['duration_ts']))*Fraction(v['time_base'])
  require(a['codec_name']=='aac' and a['sample_rate']=='48000' and a['channels']==2 and duration==Fraction(int(a['duration_ts']))*Fraction(a['time_base']) and abs(float(duration)-m['duration_seconds'])<1e-6 and int(v['nb_frames'])==r['frames']==3502,'Wrong final clock/audio metadata')
  prior=bound_record(r['accepted_V2_source'],root);payload=packet_hash(video,'a');identity=audio_packet_signature(video)
  require(payload==packet_hash(prior,'a')==r['AAC_packet_payload_sha256']==m['accepted_V2_AAC_payload_sha256'] and identity==audio_packet_signature(prior)==(r['AAC_packet_count'],r['AAC_packet_signature_sha256']),'Accepted AAC packets/timing differ')
  identities.append((payload,identity))
 require(len(set(identities))==1,'Soundtrack differs between formats')
 return {'state':'PRIVATE_REVIEW_REQUIRES_ACCEPTANCE','manifest_sha256':sha(manifest),'soundtrack_packet_identity':True,'source_capture':capture['state'],'publication_approved':False,'listening':'No new listening or acceptance inferred; exact unchanged bound prior AAC','full_AV':m.get('owner_new_shore_acceptance','PENDING'),'scope':'Actual hash-bound assembly/capture evidence, stream metadata and packet identity; no invented listening, owner visual acceptance, native Instagram verification or publication approval'}

def check_private(folder,project_root):
 d=Path(folder).resolve();root=Path(project_root).resolve()
 require(d.is_relative_to(root),'Candidate outside project')
 if (d/'FINAL_MANIFEST.json').is_file() and json.loads((d/'FINAL_MANIFEST.json').read_text()).get('schema')==PLAIN_SCHEMA:
  from .plain_release import check_plain_private
  return check_plain_private(d,root)
 if (d/'FINAL_MANIFEST.json').is_file() and json.loads((d/'FINAL_MANIFEST.json').read_text()).get('schema')==HARBOR_SCHEMA:
  return check_harbor_private(d,root)
 m=json.loads((d/'delivery-manifest.json').read_text())
 require(m.get('schema')==SCHEMA and m.get('private') is True and m.get('publication_approved') is False,'Expected an unapproved private Tides candidate')
 bound_files(d,m['files'])
 payloads=[]
 for name,size in [('landscape',(1920,1080)),('portrait',(1080,1920))]:
  video=d/'final'/f'tides-{name}.mp4';receipt=json.loads((d/'final'/f'tides-{name}.assembly.json').read_text())
  require(receipt.get('synthetic_fixture') is False and receipt.get('output',{}).get('sha256')==sha(video),'Actual assembly binding differs')
  p=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))
  v=next(s for s in p['streams'] if s['codec_type']=='video');a=next(s for s in p['streams'] if s['codec_type']=='audio')
  require((v['codec_name'],v['width'],v['height'],v['pix_fmt'])==('h264',*size,'yuv420p'),'Wrong video delivery format')
  require(Fraction(v['avg_frame_rate'])==60 and a['codec_name']=='aac' and a['sample_rate']=='48000','Wrong cadence/audio format')
  require(abs(float(v['duration'])-float(a['duration']))<.001,'Audio/video duration mismatch')
  validation=receipt['validation'];end=receipt['ending']
  require(all(validation.get(k) is True for k in ['video_full_decode','audio_full_decode','continuous_decoded_frame_timestamps','faststart_moov_before_mdat']),'Missing executed full decode/cadence/faststart evidence')
  require(end.get('decoded_frame_md5_equal') is True and end.get('master_PCM24_tail_matches_approved_sound') is True and end.get('frames')==180,'Exact approved END evidence missing')
  payloads.append(subprocess.check_output(['ffmpeg','-v','error','-i',str(video),'-map','0:a:0','-c','copy','-f','hash','-hash','sha256','-']).decode().strip())
 require(len(set(payloads))==1,'Soundtrack differs between formats')
 for item in m['protected_originals']:
  p=Path(item['path']).resolve();require(p.is_relative_to(root) and sha(p)==item['sha256'],'Protected original changed')
 return {'state':'PRIVATE_REVIEW_REQUIRES_ACCEPTANCE','manifest_sha256':sha(d/'delivery-manifest.json'),
  'soundtrack_packet_identity':True,'publication_approved':False,
  'listening':m['listening'],'full_AV':m['full_AV'],
  'scope':'Exact file/receipt, stream and soundtrack checks; no invented listening, complete visual acceptance, native Instagram verification or publication approval'}
