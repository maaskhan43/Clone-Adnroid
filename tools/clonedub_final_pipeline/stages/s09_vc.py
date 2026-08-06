# -*- coding: utf-8 -*-
"""Stage 9: Seed-VC — convert each best clean line to its actor's voice.
Skips lines <1.2s (Seed-VC mangles tiny clips — proven). Runs inference.py per line."""
import os, sys, json, glob, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CFG, wpath

SEEDVC = CFG.get("seedvc_dir", "/mnt/d/CloneDub/seed-vc")
D = json.load(open(wpath("lines_final.json"), encoding="utf-8"))
best = json.load(open(wpath("clean_best.json"), encoding="utf-8"))
OUT = wpath("gen_vc"); os.makedirs(OUT, exist_ok=True)
lines = {L["vid"]: L for L in D["lines"]}
for vid_s, b in sorted(best.items(), key=lambda x: int(x[0])):
    vid = int(vid_s)
    L = lines[vid]
    src = wpath("gen_clean", "V%02d_c%d.wav" % (vid, b["cand"]))
    if b.get("cer", 0) is not None and os.path.exists(src):
        import soundfile as sf
        if sf.info(src).frames / sf.info(src).samplerate < 1.2:
            print("V%02d skip VC (<1.2s)" % vid, flush=True)
            continue
    tgt = wpath("refs", "ref_%s.wav" % L["actor"])
    r = subprocess.run([sys.executable, "inference.py", "--source", src, "--target", tgt,
                        "--output", OUT, "--diffusion-steps", "30", "--length-adjust", "1.0",
                        "--inference-cfg-rate", "0.7", "--f0-condition", "False"],
                       cwd=SEEDVC, capture_output=True, text=True)
    produced = sorted(glob.glob(os.path.join(OUT, "vc_*.wav")), key=os.path.getmtime)
    if r.returncode != 0 or not produced:
        print("V%02d VC FAILED: %s" % (vid, r.stderr[-200:]), flush=True)
        continue
    os.replace(produced[-1], os.path.join(OUT, "V%02d.wav" % vid))
    print("V%02d converted -> %s" % (vid, L["actor"]), flush=True)
open(os.path.join(OUT, ".written"), "w").write("ok")
print("VC done")
