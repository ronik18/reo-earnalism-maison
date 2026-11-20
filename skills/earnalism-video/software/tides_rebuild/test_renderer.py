"""Focused regressions for the actual explanatory differences in the rebuild."""
import json
import math
from pathlib import Path
import subprocess
import unittest

from . import renderer as r


class ExplanatoryGeometryTests(unittest.TestCase):
    def test_actual_attraction_uses_one_linear_scale(self):
        for name in r.SIZES:
            arrows=r.arrow_geometry('actual',1,name)
            self.assertEqual(len({a['display_scale'] for a in arrows}),1)
            for a in arrows:
                self.assertGreater(a['physical_vector'][0],0)
                self.assertGreater(a['display_vector'][0],0)
                self.assertAlmostEqual(a['display_vector'][0],a['physical_vector'][0]*a['display_scale'])
            # Ratios must survive display. A min-max arrow transform fails this.
            self.assertAlmostEqual(arrows[0]['display_vector'][0]/arrows[2]['display_vector'][0],arrows[0]['physical_vector'][0]/arrows[2]['physical_vector'][0])

    def test_reference_frame_changes_before_outward_arrows(self):
        for name in r.SIZES:
            early=r.arrow_geometry('relative',.21,name)
            self.assertTrue(all(a['display_vector']==(0.0,0.0) for a in early))
            final=r.arrow_geometry('relative',1,name)
            self.assertLess(final[0]['display_vector'][0],0)
            self.assertEqual(final[1]['display_vector'],(0.0,0.0))
            self.assertGreater(final[2]['display_vector'][0],0)
            self.assertTrue(all(a['frame']=='difference_from_centre_enlarged' for a in final))

    def test_illustrative_ocean_remains_connected(self):
        for name in r.SIZES:
            q=r.geometry(name)
            for progress in (0,.25,.5,.75,1):
                stretch=.035+.13*r.smooth(progress)
                a,b=r.illustrative_envelope_axes(stretch,q['r'])
                self.assertGreater(b,q['r']*.83)
                self.assertAlmostEqual(a*b,q['r']**2)

    def test_shared_validator_rejects_logo_collision(self):
        for name in r.SIZES:
            brand=r.layout(name)['brand']['protectedRect']
            with self.assertRaises(subprocess.CalledProcessError):r.layout(name,[brand])

    def test_changing_water_level_meets_the_sloping_shore(self):
        for panel in ((72,640,900,1196),(240,360,1680,813)):
            for step in range(101):
                g=r.basin_geometry(panel,step/100);a,b=g['shore_segment'];p=g['surface_contact']
                cross=(p[0]-a[0])*(b[1]-a[1])-(p[1]-a[1])*(b[0]-a[0])
                self.assertAlmostEqual(cross,0,places=7)
                self.assertLess(a[0],p[0]);self.assertLess(p[0],b[0])
                self.assertEqual(g['water'][0],p)
                self.assertEqual(g['water'][-1],g['land'][2])


class ActualCandidateReadabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=Path('/private/tmp/earnalism-tides-private-20261115/render-plan.json')
        if not cls.path.is_file():raise unittest.SkipTest('Actual private plan not supplied; no visual acceptance inferred')
        cls.c=r.compile_plan(cls.path)

    def render(self,name,kind,progress,caption):
        im,receipt=r.frame(kind,progress,name,caption=caption,font_path=self.c['font'],font_index=self.c['font_index'],logo_path=self.c['logo'],coast_path=self.c['coast'],actual_onsets=self.c['formats'][name]['actual_onsets'])
        self.assertEqual(im.size,r.SIZES[name])
        self.assertTrue(receipt['brand_ink'])
        for g in receipt['outer_glyphs']:
            for ink in g['ink']:self.assertTrue(r.contains(g['region'],ink))

    def test_actual_arrow_reveals_follow_measured_phrase_onsets(self):
        for name,data in self.c['formats'].items():
            onset=data['actual_onsets'];scene=next(s for s in data['timing']['scenes'] if s['kind']=='actual')
            for label,expected_ms,index in [('near',9040,2),('centre',11760,1),('far',14300,0)]:
                ms=scene['start_ms']+onset[label]*(scene['end_ms']-scene['start_ms'])
                self.assertAlmostEqual(ms,expected_ms)
                self.assertEqual(r.arrow_geometry('actual',onset[label]-.0001,name,onset)[index]['display_vector'],(0.0,0.0))
                self.assertGreater(r.arrow_geometry('actual',onset[label]+.01,name,onset)[index]['display_vector'][0],0)

    def test_every_actual_caption_and_scene_boundary(self):
        for name,data in self.c['formats'].items():
            t=data['timing']
            for cue in t['cues']:
                ms=(cue['start_ms']+cue['end_ms'])/2
                scene=next(s for s in t['scenes'] if s['start_ms']<=ms<s['end_ms'])
                progress=(ms-scene['start_ms'])/(scene['end_ms']-scene['start_ms'])
                with self.subTest(format=name,caption=cue['text']):self.render(name,scene['kind'],progress,cue['text'])
            for scene in t['scenes']:
                for progress in (0,.21,.52,.999):
                    ms=scene['start_ms']+progress*(scene['end_ms']-scene['start_ms'])
                    cue=next(c for c in t['cues'] if c['start_ms']<=ms<c['end_ms'])
                    with self.subTest(format=name,scene=scene['kind'],progress=progress):self.render(name,scene['kind'],progress,cue['text'])


if __name__=='__main__':unittest.main()
