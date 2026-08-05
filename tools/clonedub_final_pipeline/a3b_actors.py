# -*- coding: utf-8 -*-
# Stage A3b: gender-aware actor clustering (fixes A3 over-split).
# - lines >=1.2s: average-linkage cosine clustering WITHIN gender, thr 0.5
# - lines <1.2s: nearest same-gender centroid; tie-break nearest-in-time
# - merge adjacent same-actor lines (gap<0.5s)
# - refs per actor from 7-min solo pool (sim>0.45, SNR-sorted); fallback = actor's own
#   line slices (boosted) if pool empty
import json, numpy as np, soundfile as sf, torch

W = "/mnt/d/CloneDub/work/v12_3min_1470_1650"
INV = W + "/investigation"
VOX = "/mnt/d/CloneDub/work/video1_meteor_video_clone/demucs/htdemucs/full/vocals.wav"
OUTREF = W + "/orig_voice_refs_v5"
import os; os.makedirs(OUTREF, exist_ok=True)

A1 = json.load(open(INV + "/wordlines_a1.json", encoding="utf-8"))
A2 = json.load(open(INV + "/wordlines_a2_recovered.json", encoding="utf-8"))
G = json.load(open(INV + "/wordlines_a4_gender.json", encoding="utf-8"))
gmap = {round(g["abs_start"], 2): g["gender"] for g in G}
t7 = json.load(open(W + "/diar_7min/turns.json"))["turns"]
lines = sorted(A1["lines"] + A2, key=lambda L: L["abs_start"])
for L in lines:
    L["gender"] = gmap.get(round(L["abs_start"], 2), "female")
    L["dur"] = round(L["abs_end"] - L["abs_start"], 2)

info = sf.info(VOX); sr = info.samplerate
from speechbrain.inference.speaker import EncoderClassifier
enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                     savedir="/mnt/d/CloneDub/hf_cache/ecapa_sb",
                                     run_opts={"device": "cpu"})
print("ECAPA loaded", flush=True)

def read16k(a0, a1):
    x, _ = sf.read(VOX, start=int(a0 * sr), stop=int(a1 * sr))
    if x.ndim > 1: x = x.mean(1)
    x = x.astype(np.float32)
    n = int(len(x) * 16000 / sr)
    return np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x).astype(np.float32)

def embed(x):
    t = torch.tensor(x / (np.max(np.abs(x)) + 1e-9) * 0.9).unsqueeze(0)
    with torch.no_grad():
        e = enc.encode_batch(t).squeeze().cpu().numpy()
    return e / (np.linalg.norm(e) + 1e-9)

def snr_db(x):
    fl = 1600
    fe = np.array([np.sqrt(np.mean(x[i:i+fl]**2)) for i in range(0, max(len(x)-fl, 1), fl)])
    if len(fe) < 3: return 0.0
    return float(20 * np.log10((np.percentile(fe, 90) + 1e-9) / (np.percentile(fe, 10) + 1e-9)))

for L in lines:
    L["emb"] = embed(read16k(L["abs_start"], L["abs_end"]))

# average-linkage clustering within gender for long lines
def cluster(idxs, thr=0.5):
    cl = [[i] for i in idxs]
    def adist(c1, c2):
        return float(np.mean([[np.dot(lines[i]["emb"], lines[j]["emb"]) for j in c2] for i in c1]))
    while True:
        best = None; bestv = thr
        for i in range(len(cl)):
            for j in range(i + 1, len(cl)):
                v = adist(cl[i], cl[j])
                if v > bestv: bestv = v; best = (i, j)
        if best is None: break
        i, j = best
        cl[i] += cl[j]; del cl[j]
    return cl

actor_id = 0
cents = {}
for gender in ("female", "male"):
    idxs = [i for i, L in enumerate(lines) if L["gender"] == gender and L["dur"] >= 1.2]
    for c in cluster(idxs):
        name = "%s_%d" % (gender.upper()[0], actor_id); actor_id += 1
        e = np.mean([lines[i]["emb"] for i in c], axis=0)
        cents[name] = {"emb": e / (np.linalg.norm(e) + 1e-9), "gender": gender}
        for i in c: lines[i]["actor"] = name

for i, L in enumerate(lines):
    if "actor" in L: continue
    best, bestv = None, -1
    for name, ct in cents.items():
        if ct["gender"] != L["gender"]: continue
        v = float(np.dot(L["emb"], ct["emb"]))
        # small time-proximity bonus: nearest same-gender long line within 8s
        near = min((abs(L["abs_start"] - lines[j]["abs_start"])
                    for j in range(len(lines)) if lines[j].get("actor") == name), default=99)
        v += 0.05 if near < 8 else 0
        if v > bestv: bestv = v; best = name
    if best is None:  # no long line of this gender at all -> new solo actor
        best = "%s_%d" % (L["gender"].upper()[0], actor_id); actor_id += 1
        cents[best] = {"emb": L["emb"], "gender": L["gender"]}
    L["actor"] = best; L["short_sim"] = round(bestv, 2)

def fmt(t):
    s = t - 1470.0
    return "%d:%04.1f" % (int(s // 60), s % 60)

merged = []
for L in lines:
    if merged and L["actor"] == merged[-1]["actor"] and L["abs_start"] - merged[-1]["abs_end"] < 0.5:
        merged[-1]["abs_end"] = L["abs_end"]; merged[-1]["zh"] += " " + L["zh"]
        merged[-1]["dur"] = round(merged[-1]["abs_end"] - merged[-1]["abs_start"], 2)
    else:
        merged.append({k: L[k] for k in ("abs_start", "abs_end", "zh", "actor", "gender", "dur")})
print("=== FINAL LINES (%d) ===" % len(merged))
for i, L in enumerate(merged):
    L["vid"] = i
    print("V%02d %s-%s %-4s %-6s | %s" % (i, fmt(L["abs_start"]), fmt(L["abs_end"]),
                                          L["actor"], L["gender"], L["zh"][:34]))

# solo pool for refs
solo = []
for i, s in enumerate(t7):
    a0, a1v = s["abs_start"], s["abs_end"]; d = a1v - a0
    if d < 1.2: continue
    ov = any(j != i and u["speaker"] != s["speaker"] and
             (min(a1v, u["abs_end"]) - max(a0, u["abs_start"])) > 0.15 for j, u in enumerate(t7))
    if ov: continue
    x = read16k(a0, a1v)
    solo.append({"a0": a0, "a1": a1v, "d": d, "snr": snr_db(x), "emb": embed(x)})
print("solo pool: %d" % len(solo), flush=True)

refs = {}
used_actors = sorted(set(L["actor"] for L in merged))
for name in used_actors:
    ct = cents[name]["emb"]
    cand = [c for c in solo if float(np.dot(c["emb"], ct)) > 0.45]
    cand.sort(key=lambda c: (-c["snr"], -c["d"]))
    parts = []; tot = 0.0; meta = []
    for c in cand:
        x, _ = sf.read(VOX, start=int(c["a0"] * sr), stop=int(c["a1"] * sr))
        if x.ndim > 1: x = x.mean(1)
        parts.append(x.astype(np.float32)); parts.append(np.zeros(int(0.15 * sr), dtype=np.float32))
        tot += c["d"]; meta.append((round(c["d"], 1), round(c["snr"], 1)))
        if tot >= 13: break
    src = "pool"
    if tot < 3.0:  # fallback: actor's own line slices (boosted)
        parts = []; tot = 0.0; meta = []; src = "own-lines"
        for L in sorted([L for L in merged if L["actor"] == name], key=lambda L: -L["dur"]):
            x, _ = sf.read(VOX, start=int(L["abs_start"] * sr), stop=int(L["abs_end"] * sr))
            if x.ndim > 1: x = x.mean(1)
            x = x.astype(np.float32); x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
            parts.append(x); parts.append(np.zeros(int(0.15 * sr), dtype=np.float32))
            tot += L["dur"]; meta.append((L["dur"], "own"))
            if tot >= 13: break
    if not parts: continue
    cc = np.concatenate(parts); cc = cc / (np.max(np.abs(cc)) + 1e-9) * 0.95
    fn = OUTREF + "/ref_%s.wav" % name
    sf.write(fn, cc, sr)
    c16 = read16k(0, 0.01)  # placeholder not used
    n16 = int(len(cc) * 16000 / sr)
    x16 = np.interp(np.linspace(0, len(cc), n16, endpoint=False), np.arange(len(cc)), cc).astype(np.float32)
    refs[name] = {"wav": fn, "dur": round(len(cc)/sr, 1), "snr": round(snr_db(x16), 1),
                  "source": src, "clips": meta[:6]}
    print("%s ref: %.1fs SNR=%.1f (%s) %s" % (name, len(cc)/sr, refs[name]["snr"], src, meta[:4]))

json.dump({"lines": merged, "refs": refs},
          open(INV + "/wordlines_a3b.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("A3B_DONE actors_used=%d" % len(used_actors))
