# -*- coding: utf-8 -*-
"""Stage 11a: CER for the hybrid pool (gen_vc/V*.wav + gen_direct/V*_c*.wav)."""
import os, sys, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import wpath, cer
from faster_whisper import WhisperModel

best = json.load(open(wpath("clean_best.json"), encoding="utf-8"))
drep = json.load(open(wpath("gen_direct_report.json"), encoding="utf-8"))
dtxt = {(r["vid"], r["cand"]): r["text"] for r in drep}
m = WhisperModel("small", device="cpu", compute_type="int8")
out = []

def judge(fn, vid, cand, target, pool):
    segs, _ = m.transcribe(fn, task="transcribe", beam_size=5, language="hi")
    hyp = " ".join(s.text.strip() for s in segs).strip()
    c = round(cer(target, hyp), 1)
    out.append({"pool": pool, "vid": vid, "cand": cand, "cer": c})
    print("%s V%02d c%s CER=%.1f" % (pool, vid, cand, c), flush=True)

for fn in sorted(glob.glob(wpath("gen_vc", "V*.wav"))):
    vid = int(os.path.basename(fn)[1:3])
    b = best.get(str(vid))
    if b:
        judge(fn, vid, -1, b["text"], "vc")
for fn in sorted(glob.glob(wpath("gen_direct", "V*_c*.wav"))):
    b = os.path.basename(fn)[:-4]
    vid = int(b[1:3]); cand = int(b.split("_c")[1])
    t = dtxt.get((vid, cand))
    if t:
        judge(fn, vid, cand, t, "direct")
json.dump(out, open(wpath("judge_cer.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("judged=%d" % len(out))
