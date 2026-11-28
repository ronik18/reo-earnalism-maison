Scene 14 v5 sounds. Licence record per file in licences.json (sha256 of every file and, for new synthesis, of
the generating script).

- wheels.wav, breeze.wav, broom.wav, murmur.wav: byte copies from ../../v4/sfx (see its README): original
  synthesis by ../../v4/tools/synth_sfx.py, no third-party recording, dedicated to the public domain (CC0 1.0)
  by the project. broom.wav (timed to the old v2 sweeping take) is kept for the record and is not placed.
- night2.wav, pot-drop.wav: byte copies from ../../sfx (see its README): original synthesis, no third-party
  recording, CC0 1.0.
- New on 28 Nov 2026 (owner decision 28 Nov: synthesize hooves and morning birds ourselves), made by
  ../../v4/tools/synth_sfx_v5.py (numpy/OpenCV, reusing synth_sfx.py's helpers; no input recording),
  dedicated to the public domain (CC0 1.0) by the project:
  - hooves.wav (6.4 s): one horse trotting on a brick lane at night, diagonal hoof pairs, lane reflections,
    light room tone. Shot 1.
  - crows.wav (14.5 s): sparse morning chorus, nine house-crow caws in four series plus small chirps, with a
    faint open-air bed. Caw spans in crows.caws.json. Shots 9-10.
  - broom-13s.wav (9.6 s): synth_sfx.py's broom strokes re-timed to the 13s sweeping take of the door re-take
    (clips-f01s014-door-r3); stroke times measured from the take's frame difference, in broom-13s.times.json.
    Shot 10.
- fx-f01s014.json: the cue's ambience and foley placement for scene 14 (scene seconds).
- No Wikimedia Commons or other third-party file is used. motion-pilot4's sfx-*.raw are excluded: their records
  say only "Public domain" with no author-release basis (and the "broom" files are tooth-brushing, "birds-2" is
  a Wiktionary pronunciation).
