# -*- coding: utf-8 -*-
"""Stage 1: pyannote diarization of scene window + margin -> diar/turns.json (abs times)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CFG, WD, wpath, read_slice, to_sr
import numpy as np, soundfile as sf, torch
from pyannote.audio import Pipeline

os.makedirs(wpath("diar"), exist_ok=True)
m = CFG.get("diar_margin", 210)
w0 = max(0.0, CFG["t0"] - m)
w1 = CFG["t1"] + m
a, sr = read_slice(CFG["vocals"], w0, w1)
a16 = to_sr(a, sr, 16000)
sf.write(wpath("diar", "window_vocals.wav"), a16, 16000)
print("window %.1f-%.1f (%.0fs)" % (w0, w1, len(a16) / 16000), flush=True)

pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1",
                                use_auth_token=os.environ.get("HF_TOKEN"))
pipe.to(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
diar = pipe(wpath("diar", "window_vocals.wav"))
turns = []
for turn, _, spk in diar.itertracks(yield_label=True):
    turns.append({"abs_start": round(turn.start + w0, 2),
                  "abs_end": round(turn.end + w0, 2), "speaker": spk})
json.dump({"window": [w0, w1], "turns": turns}, open(wpath("diar", "turns.json"), "w"), indent=1)
print("turns=%d speakers=%d" % (len(turns), len(set(t["speaker"] for t in turns))))
