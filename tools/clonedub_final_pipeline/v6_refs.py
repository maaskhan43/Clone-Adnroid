# -*- coding: utf-8 -*-
# V6 refs: single CONTINUOUS 8-12s clip per actor (no concatenation), end-silence,
# plus full-movie embedding scan for better M and F_B material.
import json, numpy as np, soundfile as sf, torch, os

W = "/mnt/d/CloneDub/work/v12_3min_1470_1650"
VOX = "/mnt/d/CloneDub/work/video1_meteor_video_clone/demucs/htdemucs/full/vocals.wav"
OUT = W + "/orig_voice_refs_v6"; os.makedirs(OUT, exist_ok=True)
t7 = json.load(open(W + "/diar_7min/turns.json"))["turns"]
D = json.load(open(W + "/lines_v5.json", encoding="utf-8"))

info = sf.info(VOX); sr = info.samplerate; TOTAL = info.frames / sr
from speechbrain.inference.speaker import EncoderClassifier
enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                     savedir="/mnt/d/CloneDub/hf_cache/ecapa_sb",
                                     run_opts={"device": "cpu"})
print("ECAPA loaded, movie=%.0fs" % TOTAL, flush=True)

def read(a0, a1):
    x, _ = sf.read(VOX, start=int(a0 * sr), stop=int(a1 * sr))
    if x.ndim > 1: x = x.mean(1)
    return x.astype(np.float32)

def to16k(x):
    n = int(len(x) * 16000 / sr)
    return np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x).astype(np.float32)

def embed(x):
    t = torch.tensor(to16k(x) / (np.max(np.abs(x)) + 1e-9) * 0.9).unsqueeze(0)
    with torch.no_grad():
        e = enc.encode_batch(t).squeeze().cpu().numpy()
    return e / (np.linalg.norm(e) + 1e-9)

def snr_db(x):
    x = to16k(x); fl = 1600
    fe = np.array([np.sqrt(np.mean(x[i:i+fl]**2)) for i in range(0, max(len(x)-fl, 1), fl)])
    if len(fe) < 3: return 0.0
    return float(20 * np.log10((np.percentile(fe, 90) + 1e-9) / (np.percentile(fe, 10) + 1e-9)))

def save_ref(name, a0, a1):
    x = read(a0, a1)
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.85
    x = np.concatenate([x, np.zeros(int(0.35 * sr), dtype=np.float32)])  # end silence
    fn = OUT + "/ref_%s.wav" % name
    sf.write(fn, x, sr)
    print("%s ref saved: abs %.1f-%.1f (%.1fs) SNR=%.1f" % (name, a0, a1, a1-a0, snr_db(read(a0, a1))), flush=True)
    return {"abs_start": a0, "abs_end": a1, "wav": fn}

meta = {}
# F_A: longest continuous solo SPEAKER_00 turn (had a 13.5s one) -> trim to 11s
best = max((u for u in t7 if u["speaker"] == "SPEAKER_00" and u["abs_end"]-u["abs_start"] >= 8),
           key=lambda u: u["abs_end"]-u["abs_start"], default=None)
if best:
    a0 = best["abs_start"]; a1 = min(best["abs_end"], a0 + 11.0)
    meta["F_A"] = save_ref("F_A", a0, a1)

# centroids for M and F_B from their ORIGINAL line slices (>=0.8s)
cents = {}
for actor in ("M", "F_B"):
    slices = [read(L["abs_start"], L["abs_end"]) for L in D["lines"]
              if L["actor"] == actor and L["dur"] >= 0.8]
    es = [embed(x) for x in slices if len(x) > sr // 2]
    e = np.mean(es, axis=0); cents[actor] = e / (np.linalg.norm(e) + 1e-9)
print("centroids ready", flush=True)

# full-movie scan: 2.5s windows, 1.25s hop, RMS-gated
WIN, HOP = 2.5, 1.25
hits = {"M": [], "F_B": []}
t = 0.0
while t + WIN < TOTAL:
    x = read(t, t + WIN)
    rms = float(np.sqrt(np.mean(x**2)))
    if rms > 0.0015:
        e = embed(x)
        for actor in ("M", "F_B"):
            s = float(np.dot(e, cents[actor]))
            if s >= 0.55:
                hits[actor].append((t, t + WIN, s))
    t += HOP
print("scan done: M hits=%d F_B hits=%d" % (len(hits["M"]), len(hits["F_B"])), flush=True)

for actor in ("M", "F_B"):
    runs = []
    for h in sorted(hits[actor]):
        if runs and h[0] <= runs[-1][1] + 0.1:
            runs[-1] = (runs[-1][0], h[1], max(runs[-1][2], h[2]))
        else:
            runs.append(list(h))
    runs = [r for r in runs if r[1] - r[0] >= 5.0]
    runs.sort(key=lambda r: -(min(r[1]-r[0], 12) * 2 + snr_db(read(r[0], min(r[1], r[0]+11)))))
    print("%s continuous runs >=5s: %d" % (actor, len(runs)), flush=True)
    for r in runs[:5]:
        print("   %.1f-%.1f (%.1fs) sim=%.2f snr=%.1f" % (r[0], r[1], r[1]-r[0], r[2], snr_db(read(r[0], min(r[1], r[0]+11)))), flush=True)
    if runs:
        r = runs[0]
        a0 = r[0]; a1 = min(r[1], a0 + 11.0)
        meta[actor] = save_ref(actor, a0, a1)
    else:
        print("%s: NO run found - keep v5 ref" % actor, flush=True)

json.dump(meta, open(OUT + "/refs_meta.json", "w"), indent=1)
print("V6_REFS_DONE")
