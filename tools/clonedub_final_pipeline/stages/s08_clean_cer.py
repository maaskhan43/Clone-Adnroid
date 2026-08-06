# -*- coding: utf-8 -*-
"""Stage 8: CER-judge clean candidates -> clean_best.json (best cand per line)."""
import os, sys, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import wpath, cer
from faster_whisper import WhisperModel

rep = json.load(open(wpath("gen_clean_report.json"), encoding="utf-8"))
txt = {(r["vid"], r["cand"]): r["text"] for r in rep}
m = WhisperModel("small", device="cpu", compute_type="int8")
best = {}
for fn in sorted(glob.glob(wpath("gen_clean", "V*_c*.wav"))):
    b = os.path.basename(fn)[:-4]
    vid = int(b[1:3]); cand = int(b.split("_c")[1])
    target = txt.get((vid, cand))
    if not target:
        continue
    segs, _ = m.transcribe(fn, task="transcribe", beam_size=5, language="hi")
    hyp = " ".join(s.text.strip() for s in segs).strip()
    c = round(cer(target, hyp), 1)
    print("V%02d_c%d CER=%.1f" % (vid, cand, c), flush=True)
    if vid not in best or c < best[vid]["cer"]:
        best[vid] = {"cand": cand, "cer": c, "text": target}
json.dump({str(k): v for k, v in best.items()},
          open(wpath("clean_best.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
import statistics
print("MEAN best CER=%.1f" % statistics.mean([v["cer"] for v in best.values()]))
