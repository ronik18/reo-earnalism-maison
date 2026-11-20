import json, tempfile, unittest
from pathlib import Path
from .plain_release import capture_gate, file_record, cache_frames_gate, source_links_gate
from .release import sha

class RetimedCandidateTests(unittest.TestCase):
    def source_records(self, root):
        paths={k:root/n for k,n in {
            'narration':'voice.wav','script':'script.txt','raw_ASR':'ASR.json',
            'owner_dry_voice_decision':'decision.json','timing':'timing.json',
            'render_plan':'plan.json','captions':'English.srt'}.items()}
        paths['narration'].write_bytes(b'unit-test native source binding; not generated speech')
        paths['script'].write_text('A boat rises.')
        for k in ('raw_ASR','owner_dry_voice_decision'):paths[k].write_text('{}')
        ref=lambda p:{'path':str(p),'sha256':sha(p)}
        timing={'timing_status':'actual_audio_aligned',
                'audio_sha256':sha(paths['narration']),
                'source_script_sha256':sha(paths['script']),
                'raw_asr':ref(paths['raw_ASR']),
                'owner_dry_voice_decision':ref(paths['owner_dry_voice_decision']),
                'cues':[{'kind':'narration','start_ms':0,'end_ms':1500,'text':'A boat rises.'}]}
        paths['timing'].write_text(json.dumps(timing))
        plan={'owner_dry_voice_decision':ref(paths['owner_dry_voice_decision']),
              'formats':{name:{key:ref(paths[record]) for key,record in
                         [('narration','narration'),('transcript','script'),('timing','timing')]}
                         for name in ('landscape','portrait')}}
        paths['render_plan'].write_text(json.dumps(plan))
        paths['captions'].write_text('1\n00:00:00,000 --> 00:00:01,500\nA boat rises.\n\n')
        return paths

    def test_in_progress_or_unbound_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for item in (None, {}, {'file':tmp,'sha256':None}):
                with self.assertRaisesRegex(ValueError,'Missing bound'):
                    file_record(item,Path(tmp))

    def test_capture_hold_is_not_inherited_from_previous_edition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();report=root/'capture.json'
            report.write_text(json.dumps({'schema':'earnalism.tides.plain-v4.capture-check.v1','state':'CAPTURE_HOLD'}))
            m={'capture_check':{'file':str(report),'sha256':sha(report)}}
            with self.assertRaisesRegex(ValueError,'source-pixel capture PASS'):
                capture_gate(root,m,root)

    def test_changed_capture_report_is_rejected_before_using_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();report=root/'capture.json';report.write_text('{}')
            m={'capture_check':{'file':str(report),'sha256':sha(report)}}
            report.write_text('{"state":"RETIMED_CAPTURE_PASS"}')
            with self.assertRaisesRegex(ValueError,'Changed or escaping'):
                capture_gate(root,m,root)

    def test_current_checker_hash_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'check_capture.py').write_text('new checker')
            report=root/'capture.json'
            report.write_text(json.dumps({'schema':'earnalism.tides.plain-v4.capture-check.v1','state':'RETIMED_CAPTURE_PASS','checker_sha256':'stale'}))
            m={'capture_check':{'file':str(report),'sha256':sha(report)}}
            with self.assertRaisesRegex(ValueError,'source/clock changed'):
                capture_gate(root,m,root)

    def test_changed_nonfirst_cache_frame_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();frames=[]
            for i in range(2):
                p=root/f'{i}.png';p.write_bytes(f'frame binding {i}'.encode())
                frames.append({'file':p.name,'sha256':sha(p)})
            cache={'formats':{'portrait':{'frames':frames}}}
            cache_frames_gate(root/'MANIFEST.json',cache,'portrait')
            (root/'1.png').write_bytes(b'pixels changed after capture review')
            with self.assertRaisesRegex(ValueError,'Changed or escaping'):
                cache_frames_gate(root/'MANIFEST.json',cache,'portrait')

    def test_timing_for_another_native_voice_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();paths=self.source_records(root)
            source_links_gate(paths,root)
            timing=json.loads(paths['timing'].read_text());timing['audio_sha256']='another voice'
            paths['timing'].write_text(json.dumps(timing))
            with self.assertRaisesRegex(ValueError,'Timing belongs to another'):
                source_links_gate(paths,root)

    def test_rebound_portrait_timing_cannot_diverge_from_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();paths=self.source_records(root)
            alternate=root/'another-timing.json';alternate.write_text(paths['timing'].read_text())
            plan=json.loads(paths['render_plan'].read_text())
            plan['formats']['portrait']['timing']={'path':str(alternate),'sha256':sha(alternate)}
            paths['render_plan'].write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError,'another portrait timing'):
                source_links_gate(paths,root)

    def test_rebound_ASR_record_cannot_diverge_from_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();paths=self.source_records(root)
            alternate=root/'another-ASR.json';alternate.write_text('{}')
            paths['raw_ASR']=alternate
            with self.assertRaisesRegex(ValueError,'another raw_asr'):
                source_links_gate(paths,root)

    def test_rebound_SRT_words_or_times_must_match_actual_cues(self):
        for changed in ('1\n00:00:00,000 --> 00:00:01,500\nAnother boat rises.\n\n',
                        '1\n00:00:00,000 --> 00:00:01,600\nA boat rises.\n\n'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();paths=self.source_records(root)
                source_links_gate(paths,root)
                paths['captions'].write_text(changed)
                with self.assertRaisesRegex(ValueError,'SRT differs from actual timing cues'):
                    source_links_gate(paths,root)

    def test_optional_final_SRT_separator_does_not_change_cues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();paths=self.source_records(root)
            paths['captions'].write_text(paths['captions'].read_text().rstrip('\n')+'\n')
            source_links_gate(paths,root)

if __name__=='__main__':unittest.main()
