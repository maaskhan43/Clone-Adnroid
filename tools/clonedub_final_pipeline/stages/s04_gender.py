# -*- coding: utf-8 -*-
"""Stage 4: acoustic gender per line (JaesungHuh classifier, indicf5 venv)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/mnt/d/CloneDub/voice_gender_clf")
from common import CFG, wpath, read_slice, to_sr
import numpy as np, soundfile as sf, torch
from model import ECAPA_gender

L = json.load(open(wpath("wordlines.json"), encoding="utf-8"))["lines"]
dev = "cuda" if torch.cuda.is_available() else "cpu"
g = ECAPA_gender.from_pretrained("JaesungHuh/voice-gender-classifier"); g.eval(); g.to(dev)
out = []
for x in L:
    d = x["abs_end"] - x["abs_start"]
    pad = max(0.0, (0.9 - d) / 2)
    a, sr = read_slice(CFG["vocals"], x["abs_start"] - pad, x["abs_end"] + pad)
    a = a / (np.max(np.abs(a)) + 1e-9) * 0.9
    sf.write("/tmp/_g.wav", to_sr(a, sr, 16000), 16000)
    with torch.no_grad():
        pred = g.predict("/tmp/_g.wav", device=dev)
    out.append({"abs_start": x["abs_start"], "gender": pred})
    print("%.1f %s | %s" % (x["abs_start"], pred, x["zh"][:24]), flush=True)
json.dump(out, open(wpath("gender.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("gender done n=%d" % len(out))
