# -*- coding: utf-8 -*-
"""Stage 3: word-level line building (proven a1) + 2nd-pass ASR on empty turns (a2).
Runs in SoniTranslate venv (needs faster_whisper). Output: wordlines.json"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CFG, wpath, read_slice, to_sr
import numpy as np, soundfile as sf
from faster_whisper import WhisperModel

T0, T1 = CFG["t0"], CFG["t1"]
A = json.load(open(wpath("asr_words.json"), encoding="utf-8"))
turns = [u for u in json.load(open(wpath("diar", "turns.json")))["turns"]
         if u["abs_end"] > T0 - 2 and u["abs_start"] < T1 + 2]

words = []
for seg in A["segments"]:
    for w in seg["words"]:
        if T0 - 0.5 <= w["abs_start"] <= T1 + 0.5:
            words.append(dict(w))
words.sort(key=lambda w: w["abs_start"])

def spk_of(w):
    best, bestov = None, 0.0
    for u in turns:
        ov = min(w["abs_end"], u["abs_end"] + 0.25) - max(w["abs_start"], u["abs_start"] - 0.25)
        if ov > bestov:
            bestov, best = ov, u["speaker"]
    return best

for w in words:
    w["spk"] = spk_of(w)
# majority smoothing (window 3, only flip short words)
for i in range(1, len(words) - 1):
    a, b, c = words[i-1]["spk"], words[i]["spk"], words[i+1]["spk"]
    if a == c and b != a and a is not None and words[i]["abs_end"] - words[i]["abs_start"] < 0.5:
        words[i]["spk"] = a

lines, cur = [], None
for w in words:
    if cur and (w["spk"] != cur["spk"] or w["abs_start"] - cur["abs_end"] > 0.8
                or w["abs_end"] - cur["abs_start"] > 12.0):
        lines.append(cur); cur = None
    if cur is None:
        cur = {"abs_start": w["abs_start"], "abs_end": w["abs_end"], "spk": w["spk"], "zh": w["word"]}
    else:
        cur["abs_end"] = w["abs_end"]; cur["zh"] += w["word"]
if cur:
    lines.append(cur)

# 2nd-pass ASR on empty diar turns (recovers quiet lines)
m = WhisperModel("small", device="cpu", compute_type="int8")
for u in turns:
    if u["abs_end"] < T0 or u["abs_start"] > T1:
        continue
    dur = u["abs_end"] - u["abs_start"]
    if dur < 0.25:
        continue
    has = any(u["abs_start"] - 0.3 <= (w["abs_start"] + w["abs_end"]) / 2 <= u["abs_end"] + 0.3
              for w in words)
    if has:
        continue
    x, sr = read_slice(CFG["vocals"], u["abs_start"] - 0.3, u["abs_end"] + 0.3)
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
    sf.write("/tmp/_2p.wav", to_sr(x, sr, 16000), 16000)
    segs, _ = m.transcribe("/tmp/_2p.wav", task="transcribe", beam_size=5, language="zh")
    txt = " ".join(s.text.strip() for s in segs).strip()
    if txt:
        lines.append({"abs_start": u["abs_start"], "abs_end": u["abs_end"],
                      "spk": u["speaker"], "zh": txt, "recovered": True})
        print("RECOVERED %.1f %s" % (u["abs_start"], txt[:24]), flush=True)

lines.sort(key=lambda L: L["abs_start"])
for L in lines:
    L["dur"] = round(L["abs_end"] - L["abs_start"], 2)
lines = [L for L in lines if L["dur"] >= 0.2]   # whisper jitter: zero-length words
json.dump({"lines": lines}, open(wpath("wordlines.json"), "w", encoding="utf-8"),
          indent=1, ensure_ascii=False)
print("lines=%d" % len(lines))
