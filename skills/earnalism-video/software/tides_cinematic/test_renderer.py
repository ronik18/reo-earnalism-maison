"""Regressions for the performed motion and explanatory frame separation."""
from pathlib import Path
import unittest

import numpy as np

from . import renderer as r


class CinematicMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plan=r.DEFAULT_OUTPUT/'render-plan.json'
        if not plan.is_file():raise unittest.SkipTest('Private source plan not supplied')
        cls.c=r.compile_plan(plan)

    def test_water_rises_while_the_piling_pixels_stay_fixed(self):
        for name in r.SIZES:
            first,a=r.cinematic_coast(name,0,self.c['coast']);last,b=r.cinematic_coast(name,1,self.c['coast'])
            self.assertEqual(a['fixed_piling_bounds'],b['fixed_piling_bounds'])
            self.assertEqual(a['fixed_gauge_bounds'],b['fixed_gauge_bounds'])
            self.assertLess(b['water_level_y'],a['water_level_y'])
            x0,y0,x1,y1=a['fixed_piling_bounds'];crop=(x0+3,y0+15,x1-3,round(b['water_level_y'])-20)
            self.assertTrue(np.array_equal(np.asarray(first.crop(crop)),np.asarray(last.crop(crop))))
            wet=(x0+3,round(b['water_level_y'])+22,x1-3,round(a['water_level_y'])-22)
            self.assertFalse(np.array_equal(np.asarray(first.crop(wet)),np.asarray(last.crop(wet))))

    def test_original_shore_and_pier_anchor_pixels_never_move(self):
        for name in r.SIZES:
            w,h=r.SIZES[name]
            if name=='landscape':
                anchors=[(0,.48,.14,.96),(.88,.34,.99,.61),(.72,.90,.99,.99)]
            else:
                anchors=[(.90,.34,.99,.59),(0,.93,.99,.99)]
            images=[r.cinematic_coast(name,p,self.c['coast'])[0] for p in (0,.25,.5,.75,1)]
            for anchor in anchors:
                box=tuple(round(v*(w if i%2==0 else h)) for i,v in enumerate(anchor))
                reference=np.asarray(images[0].crop(box))
                for image in images[1:]:self.assertTrue(np.array_equal(reference,np.asarray(image.crop(box))))

    def test_common_linear_actual_arrows_and_separate_relative_frame(self):
        for name in r.SIZES:
            q=r.composition(name);onsets=self.c['formats'][name]['actual_onsets']
            actual=r.field_records(q,'actual',1,onsets)
            self.assertEqual(len({a['scale'] for a in actual}),1)
            for a in actual:
                self.assertGreater(a['vector'][0],0)
                self.assertAlmostEqual(a['physical'][0]*a['scale'],a['vector'][0])
            early=r.field_records(q,'relative',.21,onsets)
            self.assertTrue(all(a['vector']==(0.0,0) for a in early))
            relative=r.field_records(q,'relative',1,onsets)
            self.assertLess(relative[0]['vector'][0],0)
            self.assertEqual(relative[1]['vector'],(0.0,0))
            self.assertGreater(relative[2]['vector'][0],0)

    def test_every_actual_caption_and_transition_is_measured_and_safe(self):
        for name,data in self.c['formats'].items():
            times=[(c['start_ms']+c['end_ms'])/2 for c in data['timing']['cues']]
            times.extend((0,2600,2700,3000,4200,5200,5780,17460,41880,50500,55359))
            for ms in times:
                with self.subTest(format=name,ms=ms):
                    im,receipt=r.frame_at(ms,name,self.c)
                    self.assertEqual(im.size,r.SIZES[name])
                    for glyph in receipt['glyphs']:
                        for ink in glyph['ink']:self.assertTrue(r.common.contains(glyph['region'],ink))
                    self.assertTrue(receipt['brand_ink'])


if __name__=='__main__':unittest.main()
