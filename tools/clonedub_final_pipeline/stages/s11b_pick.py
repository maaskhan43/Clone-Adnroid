# -*- coding: utf-8 -*-
"""Stage 11b: UTMOS + ECAPA sim for pool; composite pick (-CER + 15*sim + 4*UTMOS)."""
import os, sys, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import wpath, to_sr
import numpy as np, soundfile as sf, torch
from speechbrain.inference.speaker import EncoderClassifier

D = json.load(open(wpath("lines_final.json"), encoding="utf-8"))
CERJ = json.load(open(wpath("judge_cer.json"), encoding="utf-8"))
cmap = {(c["pool"], c["vid"], c["cand"]): c["cer"] for c in CERJ}
lines = {L["vid"]: L for L in D["lines"]}

pred = torch.hub.load("tarepan/SpeechMOS:v1.2.0", "utmos22_strong", trust_repo=True)
sys.path.insert(0, "/mnt/d/CloneDub/voice_gender_clf")
from model import ECAPA_gender
_g = ECAPA_gender.from_pretrained("JaesungHuh/voice-gender-classifier"); _g.eval()
def gender_of(a, sr):
    x = to_sr(a if a.ndim == 1 else a.mean(1), sr, 16000)
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
    sf.write("/tmp/_jg.wav", x.astype(np.float32), 16000)
    with torch.no_grad():
        return _g.predict("/tmp/_jg.wav", device="cpu")
enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                     savedir="/mnt/d/CloneDub/hf_cache/ecapa_sb",
                                     run_opts={"device": "cpu"})

def emb(a, sr):
    x = to_sr(a if a.ndim == 1 else a.mean(1), sr, 16000)
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
    with torch.no_grad():
        e = enc.encode_batch(torch.tensor(x).unsqueeze(0)).squeeze().cpu().numpy()
    return e / (np.linalg.norm(e) + 1e-9)

refemb = {}
for L in D["lines"]:
    if L["actor"] not in refemb:
        a, sr = sf.read(wpath("refs", "ref_%s.wav" % L["actor"]))
        refemb[L["actor"]] = emb(np.asarray(a, dtype=np.float32), sr)

picks = {}
def consider(pool, vid, cand, fn):
    cerv = cmap.get((pool, vid, cand))
    if cerv is None:
        return
    a, sr = sf.read(fn)
    a = np.asarray(a, dtype=np.float32)
    if a.ndim > 1:
        a = a.mean(1)
    with torch.no_grad():
        u = float(pred(torch.from_numpy(a).unsqueeze(0), sr))
    sim = float(np.dot(emb(a, sr), refemb[lines[vid]["actor"]]))
    comp = -cerv + 15 * sim + 4 * u
    if len(a) / sr >= 1.2 and gender_of(a, sr) != lines[vid]["gender"]:
        comp -= 40   # wrong-gender clone: heavy penalty
    print("%s V%02d c%s cer=%.1f sim=%.2f utmos=%.2f comp=%.1f" % (pool, vid, cand, cerv, sim, u, comp), flush=True)
    if vid not in picks or comp > picks[vid]["comp"]:
        picks[vid] = {"pool": pool, "cand": cand, "file": fn, "cer": cerv,
                      "sim": round(sim, 2), "utmos": round(u, 2), "comp": round(comp, 1)}

for fn in sorted(glob.glob(wpath("gen_vc", "V*.wav"))):
    consider("vc", int(os.path.basename(fn)[1:3]), -1, fn)
for fn in sorted(glob.glob(wpath("gen_direct", "V*_c*.wav"))):
    b = os.path.basename(fn)[:-4]
    consider("direct", int(b[1:3]), int(b.split("_c")[1]), fn)
# tiny TTS lines that skipped VC may only exist in gen_clean -> include as fallback
for L in D["lines"]:
    if L["original_audio"] or L["vid"] in picks:
        continue
    cl = sorted(glob.glob(wpath("gen_clean", "V%02d_c*.wav" % L["vid"])))
    if cl:
        picks[L["vid"]] = {"pool": "clean", "cand": 0, "file": cl[0], "cer": -1,
                           "sim": 0, "utmos": 0, "comp": 0}
json.dump({str(k): v for k, v in picks.items()},
          open(wpath("picks.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
vals = [p["cer"] for p in picks.values() if p["cer"] >= 0]
print("picks=%d mean CER=%.1f" % (len(picks), sum(vals) / max(len(vals), 1)))
