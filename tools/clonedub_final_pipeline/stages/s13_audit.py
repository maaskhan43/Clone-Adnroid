# -*- coding: utf-8 -*-
"""Stage 13: ACCEPTANCE AUDIT of assembled scene.wav — FAIL exits nonzero (no mux).
Tests: per-line gender probe in output, overlap=0, word coverage>=95%, CER gate<=40."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/mnt/d/CloneDub/voice_gender_clf")
from common import CFG, wpath, to_sr
import numpy as np, soundfile as sf, torch
from model import ECAPA_gender

D = json.load(open(wpath("lines_final.json"), encoding="utf-8"))
picks = json.load(open(wpath("picks.json"), encoding="utf-8"))
A = json.load(open(wpath("asr_words.json"), encoding="utf-8"))
T0, T1 = D["t0"], D["t1"]
a, sr = sf.read(wpath("scene.wav"))
if a.ndim > 1:
    a = a.mean(1)
dev = "cuda" if torch.cuda.is_available() else "cpu"
g = ECAPA_gender.from_pretrained("JaesungHuh/voice-gender-classifier"); g.eval(); g.to(dev)
fails = []

# 1) gender probe per line (>=1.2s lines only — classifier unreliable below)
for L in D["lines"]:
    if L["dur"] < 1.2 or L.get("original_audio"):   # original slices are verbatim source
        continue
    s0 = L["abs_start"] - T0
    s1 = min(L["abs_end"] - T0 + 0.2, T1 - T0)
    seg = a[int(s0 * sr):int(s1 * sr)]
    if len(seg) < sr // 4:      # line at/beyond scene edge — unverifiable
        continue
    rms = float(np.sqrt(np.mean(seg**2)))
    if rms < 0.02:
        fails.append("V%02d SILENT (rms=%.3f)" % (L["vid"], rms))
        continue
    x = seg / (np.max(np.abs(seg)) + 1e-9) * 0.9
    sf.write("/tmp/_aud.wav", to_sr(x.astype(np.float32), sr, 16000), 16000)
    with torch.no_grad():
        got = g.predict("/tmp/_aud.wav", device=dev)
    if got != L["gender"]:
        fails.append("V%02d gender got=%s want=%s" % (L["vid"], got, L["gender"]))

# 2) overlaps: pick durations vs next onset
lines = sorted(D["lines"], key=lambda x: x["abs_start"])
for i, L in enumerate(lines[:-1]):
    p = picks.get(str(L["vid"]))
    if not p or L["original_audio"]:
        continue
    info = sf.info(p["file"])
    end = L["abs_start"] + info.frames / info.samplerate
    if end > lines[i + 1]["abs_start"] + 0.05:
        fails.append("V%02d overlaps next by %.2fs" % (L["vid"], end - lines[i+1]["abs_start"]))

# 3) word coverage
words = [w for seg in A["segments"] for w in seg["words"] if T0 <= w["abs_start"] <= T1]
cov = sum(1 for w in words if any(L["abs_start"] - 0.4 <= (w["abs_start"] + w["abs_end"]) / 2
                                  <= L["abs_end"] + 0.4 for L in lines))
pct = 100.0 * cov / max(len(words), 1)
if pct < 95:
    fails.append("word coverage %.1f%% < 95%%" % pct)

# 4) CER gate — only for lines >=1.2s (whisper CER unreliable on tiny clips)
durs = {L["vid"]: L["dur"] for L in D["lines"]}
badcer = [(int(v), p["cer"]) for v, p in picks.items()
          if p["cer"] is not None and p["cer"] > 40 and durs.get(int(v), 0) >= 1.2]
for vid, c in badcer:
    fails.append("V%02d CER %.1f > 40" % (vid, c))

summary = "coverage=%.1f%% fails=%d" % (pct, len(fails))
json.dump({"summary": summary, "fails": fails, "coverage": pct},
          open(wpath("audit.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(summary)
for f in fails:
    print("FAIL:", f)
if fails:
    sys.exit(1)
print("AUDIT PASS")
