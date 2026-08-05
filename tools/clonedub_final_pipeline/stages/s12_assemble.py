# -*- coding: utf-8 -*-
"""Stage 12: assemble scene.wav — picks at onsets + original-audio interjections + bed 0.6x."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CFG, wpath, read_slice, to_sr
import numpy as np, soundfile as sf

D = json.load(open(wpath("lines_final.json"), encoding="utf-8"))
picks = json.load(open(wpath("picks.json"), encoding="utf-8"))
T0, T1 = D["t0"], D["t1"]
SCENE = T1 - T0
SR = 24000
tl = np.zeros(int(SCENE * SR) + SR)
for L in sorted(D["lines"], key=lambda x: x["abs_start"]):
    if L["original_audio"]:
        x, sr = read_slice(CFG["vocals"], L["abs_start"], L["abs_end"])
        x = x / (np.max(np.abs(x)) + 1e-9) * 0.75
        a = to_sr(x, sr, SR)
    else:
        p = picks.get(str(L["vid"]))
        if not p:
            print("V%02d NO PICK - skipped" % L["vid"], flush=True)
            continue
        a, sr = sf.read(p["file"])
        a = np.asarray(a, dtype=np.float32)
        if a.ndim > 1:
            a = a.mean(1)
        a = to_sr(a, sr, SR)
    s = int(round((L["abs_start"] - T0) * SR))
    e = s + len(a)
    if e > len(tl):
        a = a[:len(tl) - s]; e = len(tl)
    tl[s:e] += a
tl = tl[:int(SCENE * SR)]
voice = tl * (0.75 / (np.abs(tl).max() + 1e-9))
bed, bsr = read_slice(CFG["no_vocals"], T0, T1)
bed = to_sr(bed, bsr, SR)
n = min(len(bed), len(voice))
mix = voice[:n] + bed[:n] * CFG.get("bed_gain", 0.6)
mix = mix * (0.99 / max(np.abs(mix).max(), 0.99))
sf.write(wpath("scene.wav"), mix.astype(np.float32), SR)
print("assembled %.0fs" % (len(mix) / SR))
