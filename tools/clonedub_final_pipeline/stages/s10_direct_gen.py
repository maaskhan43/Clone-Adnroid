# -*- coding: utf-8 -*-
"""Stage 10: direct actor-ref TTS candidates (v6-style) — hybrid pool ke liye.
2 candidates per line with the ACTOR's own ref (works well for some lines; judge decides)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CFG, wpath, start_trim, speedup
import numpy as np, soundfile as sf, torch
from transformers import AutoModel

D = json.load(open(wpath("lines_final.json"), encoding="utf-8"))
best = json.load(open(wpath("clean_best.json"), encoding="utf-8"))
GEN = wpath("gen_direct"); os.makedirs(GEN, exist_ok=True)
SR = 24000
dev = "cuda" if torch.cuda.is_available() else "cpu"
model = AutoModel.from_pretrained("ai4bharat/IndicF5", trust_remote_code=True).to(dev)
print("model on", dev, flush=True)
lines = sorted(D["lines"], key=lambda L: L["abs_start"])
rep = []
for i, L in enumerate(lines):
    if L["original_audio"]:
        continue
    nxt = lines[i + 1]["abs_start"] if i + 1 < len(lines) else D["t1"]
    avail = min(nxt, D["t1"]) - L["abs_start"] - 0.15
    b = best.get(str(L["vid"]))
    hi = b["text"] if b else L["tiers"][0]
    rw = wpath("refs", "ref_%s.wav" % L["actor"])
    rt = open(wpath("refs", "ref_%s.txt" % L["actor"]), encoding="utf-8").read().strip()
    for c in range(2):
        audio = model(hi, ref_audio_path=rw, ref_text=rt)
        a = np.array(audio, dtype=np.float32)
        if a.size < SR // 8:
            print("V%02d_c%d empty" % (L["vid"], c), flush=True)
            continue
        if np.max(np.abs(a)) > 1.5:
            a = a / 32768.0
        a = a / (np.max(np.abs(a)) + 1e-9) * 0.9
        a = start_trim(a, SR)
        gen = len(a) / SR
        if avail > 0.4 and gen > avail * 1.15 + 0.4:
            print("V%02d_c%d too long %.1f" % (L["vid"], c, gen), flush=True)
            continue
        f = max(1.0, min(1.15, gen / avail)) if avail > 0.4 else 1.0
        a = speedup(a, f)
        sf.write("%s/V%02d_c%d.wav" % (GEN, L["vid"], c), a, SR)
        rep.append({"vid": L["vid"], "cand": c, "text": hi, "final": round(len(a)/SR, 2)})
        print("V%02d_c%d final=%.2f" % (L["vid"], c, len(a)/SR), flush=True)
json.dump(rep, open(wpath("gen_direct_report.json"), "w", encoding="utf-8"),
          indent=1, ensure_ascii=False)
open(os.path.join(GEN, ".written"), "w").write("ok")
print("direct candidates=%d" % len(rep))
