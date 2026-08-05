# -*- coding: utf-8 -*-
"""Stage 5: actor identity + refs (proven a3b/b_finalize/v6_refs logic).
- ECAPA embed lines; cluster within gender (avg-linkage 0.5); K=2 female cap
- short lines -> nearest same-gender centroid (+time bonus); merge adjacents;
  fold <0.5s zero-gap sentence tails
- refs: single CONTINUOUS clip per actor, score=2*min(dur,11)+SNR, dur>=5 (fallback
  own-lines boosted); exact transcript from asr_words; +0.35s end silence
- actor registry: match clusters to registry (sim>0.6) for cross-scene consistency
Output: actors.json (lines with actor+gender) + refs/ref_<actor>.{wav,txt}
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CFG, wpath, read_slice, to_sr, snr_db
import numpy as np, soundfile as sf, torch
from speechbrain.inference.speaker import EncoderClassifier

os.makedirs(wpath("refs"), exist_ok=True)
lines = json.load(open(wpath("wordlines.json"), encoding="utf-8"))["lines"]
gmap = {g["abs_start"]: g["gender"] for g in json.load(open(wpath("gender.json"), encoding="utf-8"))}
for L in lines:
    L["gender"] = gmap.get(L["abs_start"], "female")
turns = json.load(open(wpath("diar", "turns.json")))["turns"]
A = json.load(open(wpath("asr_words.json"), encoding="utf-8"))

enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                     savedir="/mnt/d/CloneDub/hf_cache/ecapa_sb",
                                     run_opts={"device": "cpu"})

def embed(a, sr):
    x = to_sr(a, sr, 16000)
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
    with torch.no_grad():
        e = enc.encode_batch(torch.tensor(x).unsqueeze(0)).squeeze().cpu().numpy()
    return e / (np.linalg.norm(e) + 1e-9)

for L in lines:
    a, sr = read_slice(CFG["vocals"], L["abs_start"], L["abs_end"])
    L["emb"] = embed(a, sr)

def cluster(idxs, thr=0.5):
    cl = [[i] for i in idxs]
    def ad(c1, c2):
        return float(np.mean([[np.dot(lines[i]["emb"], lines[j]["emb"]) for j in c2] for i in c1]))
    while True:
        best, bestv = None, thr
        for i in range(len(cl)):
            for j in range(i + 1, len(cl)):
                v = ad(cl[i], cl[j])
                if v > bestv:
                    bestv, best = v, (i, j)
        if best is None:
            return cl
        i, j = best
        cl[i] += cl[j]; del cl[j]

cents = {}
for gender in ("female", "male"):
    idxs = [i for i, L in enumerate(lines) if L["gender"] == gender and L["dur"] >= 1.2]
    cl = cluster(idxs)
    if gender == "female" and len(cl) > 2:   # K=2 female cap: keep 2 biggest, others fold below
        cl.sort(key=lambda c: -sum(lines[i]["dur"] for i in c))
        main, rest = cl[:2], cl[2:]
        for r in rest:
            sims = [np.mean([np.dot(lines[i]["emb"], lines[j]["emb"]) for i in r for j in mc])
                    for mc in main]
            main[int(np.argmax(sims))] += r
        cl = main
    for c in cl:
        name = "%s%d" % (gender[0].upper(), len(cents))
        e = np.mean([lines[i]["emb"] for i in c], axis=0)
        cents[name] = {"emb": e / (np.linalg.norm(e) + 1e-9), "gender": gender}
        for i in c:
            lines[i]["actor"] = name

for i, L in enumerate(lines):     # short lines
    if "actor" in L:
        continue
    best, bestv = None, -1
    for name, ct in cents.items():
        if ct["gender"] != L["gender"]:
            continue
        v = float(np.dot(L["emb"], ct["emb"]))
        near = min((abs(L["abs_start"] - lines[j]["abs_start"])
                    for j in range(len(lines)) if lines[j].get("actor") == name), default=99)
        v += 0.05 if near < 8 else 0
        if v > bestv:
            bestv, best = v, name
    if best is None:
        best = "%s%d" % (L["gender"][0].upper(), len(cents))
        cents[best] = {"emb": L["emb"], "gender": L["gender"]}
    L["actor"] = best

# conversation continuity + folds + merges
for i in range(1, len(lines)):
    if (lines[i]["gender"] == lines[i-1]["gender"]
            and lines[i]["abs_start"] - lines[i-1]["abs_end"] <= 0.3
            and lines[i]["actor"] != lines[i-1]["actor"]):
        lines[i]["actor"] = lines[i-1]["actor"]
folded = []
for L in lines:
    if folded and L["dur"] < 0.5 and L["abs_start"] - folded[-1]["abs_end"] <= 0.05:
        folded[-1]["abs_end"] = L["abs_end"]; folded[-1]["zh"] += L["zh"]
        folded[-1]["dur"] = round(folded[-1]["abs_end"] - folded[-1]["abs_start"], 2)
        continue
    folded.append(L)
merged = []
for L in folded:
    if merged and L["actor"] == merged[-1]["actor"] and L["abs_start"] - merged[-1]["abs_end"] < 0.5:
        merged[-1]["abs_end"] = L["abs_end"]; merged[-1]["zh"] += " " + L["zh"]
        merged[-1]["dur"] = round(merged[-1]["abs_end"] - merged[-1]["abs_start"], 2)
    else:
        merged.append({k: L[k] for k in ("abs_start", "abs_end", "zh", "actor", "gender", "dur")})
for i, L in enumerate(merged):
    L["vid"] = i

# actor registry match (cross-scene voice consistency)
reg_dir = CFG.get("actor_registry")
reg = {}
if reg_dir:
    os.makedirs(reg_dir, exist_ok=True)
    rp = os.path.join(reg_dir, "registry.json")
    if os.path.exists(rp):
        reg = json.load(open(rp))
rename = {}
for name, ct in cents.items():
    bestn, bestv = None, 0.6
    for rname, r in reg.items():
        if r["gender"] != ct["gender"]:
            continue
        v = float(np.dot(np.array(r["centroid"]), ct["emb"]))
        if v > bestv:
            bestv, bestn = v, rname
    if bestn:
        rename[name] = bestn
        print("registry match: %s -> %s (%.2f)" % (name, bestn, bestv), flush=True)
for L in merged:
    L["actor"] = rename.get(L["actor"], L["actor"])

# refs: continuous solo clip per used actor
used = sorted(set(L["actor"] for L in merged))
def solo_turns():
    out = []
    for i, s in enumerate(turns):
        d = s["abs_end"] - s["abs_start"]
        if d < 5:
            continue
        ov = any(j != i and u["speaker"] != s["speaker"] and
                 (min(s["abs_end"], u["abs_end"]) - max(s["abs_start"], u["abs_start"])) > 0.15
                 for j, u in enumerate(turns))
        if not ov:
            out.append(s)
    return out

refs_meta = {}
solos = solo_turns()
for name in used:
    # registry actor with existing ref? reuse it.
    if reg_dir and name in reg and os.path.exists(reg[name].get("ref_wav", "")):
        import shutil
        shutil.copy(reg[name]["ref_wav"], wpath("refs", "ref_%s.wav" % name))
        shutil.copy(reg[name]["ref_txt"], wpath("refs", "ref_%s.txt" % name))
        refs_meta[name] = {"source": "registry"}
        continue
    ct = cents.get(name) or {"emb": np.mean([L["emb"] for L in lines if L.get("actor") == name
                                             or True][:1], axis=0)}
    best, bestsc = None, -1
    for s in solos:
        a, sr = read_slice(CFG["vocals"], s["abs_start"], min(s["abs_end"], s["abs_start"] + 11))
        sim = float(np.dot(embed(a, sr), cents[name]["emb"])) if name in cents else 0
        if sim < 0.5:
            continue
        sc = 2 * min(s["abs_end"] - s["abs_start"], 11) + snr_db(a, sr)
        if sc > bestsc:
            bestsc, best = sc, s
    if best:
        a0 = best["abs_start"]; a1 = min(best["abs_end"], a0 + 11)
        a, sr = read_slice(CFG["vocals"], a0, a1)
        src = "solo-clip %.1f-%.1f" % (a0, a1)
        ws = [w["word"] for seg in A["segments"] for w in seg["words"]
              if a0 - 0.2 <= w["abs_start"] <= a1 + 0.2]
        txt = "".join(ws).strip()
    else:   # fallback: own lines boosted (male-scarce case)
        parts = []
        tot = 0.0
        for L in sorted([L for L in merged if L["actor"] == name], key=lambda L: -L["dur"]):
            x, sr = read_slice(CFG["vocals"], L["abs_start"], L["abs_end"])
            x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
            parts.append(x); parts.append(np.zeros(int(0.15 * sr), dtype=np.float32))
            tot += L["dur"]
            if tot >= 11:
                break
        a = np.concatenate(parts)
        src = "own-lines %.1fs" % tot
        txt = ""   # transcribed later by clean_cer stage if empty? keep zh join:
        txt = " ".join(L["zh"] for L in merged if L["actor"] == name)[:80]
    a = a / (np.max(np.abs(a)) + 1e-9) * 0.85
    a = np.concatenate([a, np.zeros(int(0.35 * sr), dtype=np.float32)])
    sf.write(wpath("refs", "ref_%s.wav" % name), a, sr)
    open(wpath("refs", "ref_%s.txt" % name), "w", encoding="utf-8").write(txt)
    refs_meta[name] = {"source": src, "snr": round(snr_db(a, sr), 1), "dur": round(len(a)/sr, 1)}
    print("ref %s: %s SNR=%.1f" % (name, src, refs_meta[name]["snr"]), flush=True)
    # save to registry
    if reg_dir:
        reg[name] = {"gender": cents[name]["gender"] if name in cents else merged[0]["gender"],
                     "centroid": [float(v) for v in cents[name]["emb"]] if name in cents else [],
                     "ref_wav": wpath("refs", "ref_%s.wav" % name),
                     "ref_txt": wpath("refs", "ref_%s.txt" % name)}
if reg_dir:
    json.dump(reg, open(os.path.join(reg_dir, "registry.json"), "w"), indent=1)

json.dump({"lines": merged, "refs": refs_meta},
          open(wpath("actors.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("actors=%s lines=%d" % (used, len(merged)))
