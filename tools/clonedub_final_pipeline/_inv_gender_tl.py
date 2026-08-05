# -*- coding: utf-8 -*-
# INVESTIGATION step 2: ground-truth speech+gender timeline of ORIGINAL vocals.
# Sliding 1.6s window, 0.4s hop over the whole scene (1470-1650). For each hop:
# RMS -> speech/silence; if speech -> JaesungHuh male/female. Output timeline JSON.
# Pure analysis - no pipeline changes.
import os, sys, json, numpy as np, soundfile as sf, torch
sys.path.insert(0, "/mnt/d/CloneDub/voice_gender_clf")
from model import ECAPA_gender

VOX = "/mnt/d/CloneDub/work/video1_meteor_video_clone/demucs/htdemucs/full/vocals.wav"
T0, T1 = 1470.0, 1650.0
OUT = "/mnt/d/CloneDub/work/v12_3min_1470_1650/investigation"
os.makedirs(OUT, exist_ok=True)
TMP = "/tmp/gt"; os.makedirs(TMP, exist_ok=True)

info = sf.info(VOX); sr = info.samplerate
a, _ = sf.read(VOX, start=int(T0 * sr), stop=int(T1 * sr))
if a.ndim > 1: a = a.mean(1)
a = a.astype(np.float32)
# resample once to 16k
n16 = int(len(a) * 16000 / sr)
a16 = np.interp(np.linspace(0, len(a), n16, endpoint=False), np.arange(len(a)), a).astype(np.float32)

dev = "cuda" if torch.cuda.is_available() else "cpu"
g = ECAPA_gender.from_pretrained("JaesungHuh/voice-gender-classifier"); g.eval(); g.to(dev)
print("classifier on", dev, flush=True)

WIN, HOP = 1.6, 0.4
# global RMS stats for threshold
fl = int(0.4 * 16000)
frames = [a16[i:i+fl] for i in range(0, len(a16)-fl, fl)]
fe = np.array([np.sqrt(np.mean(f**2)) for f in frames])
thr = 0.0015  # fixed: this vocals track speech RMS is 0.002-0.005   # below this = silence
print("rms thr=%.4f" % thr, flush=True)

timeline = []
t = 0.0
while t + WIN <= (T1 - T0):
    s = int(t * 16000); e = int((t + WIN) * 16000)
    seg = a16[s:e]
    rms = float(np.sqrt(np.mean(seg**2)))
    if rms < thr:
        lab = "silence"; conf = 0.0
    else:
        sf.write(TMP + "/w.wav", seg, 16000)
        with torch.no_grad():
            lab = g.predict(TMP + "/w.wav", device=dev)
        conf = 1.0
    timeline.append({"scene_t": round(t + WIN/2, 1), "abs_t": round(T0 + t + WIN/2, 1),
                     "label": lab, "rms": round(rms, 4)})
    t += HOP
json.dump(timeline, open(OUT + "/gender_timeline.json", "w"), indent=0)

# compact print: merge consecutive same labels
merged = []
for x in timeline:
    if merged and merged[-1]["label"] == x["label"]:
        merged[-1]["end"] = x["scene_t"]
    else:
        merged.append({"start": x["scene_t"], "end": x["scene_t"], "label": x["label"]})
for m in merged:
    ss = m["start"]; ee = m["end"]
    print("%d:%04.1f - %d:%04.1f  %s" % (int(ss//60), ss % 60, int(ee//60), ee % 60, m["label"]), flush=True)
print("GENDER_TIMELINE_DONE hops=%d" % len(timeline), flush=True)
