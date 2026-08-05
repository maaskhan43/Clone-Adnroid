# -*- coding: utf-8 -*-
# Stage B: finalize lines_v5.
# - females forced to K=2 actors (F_A, F_B) via centroid sim + time-proximity
# - tiny (<0.5s) fragment that continues prev sentence with 0 gap -> folded into prev
# - exclusive ref clips: each pool clip goes to its best actor only, SNR-sorted
# - translations (Urdu+Eng Devanagari, slot-sized) attached by abs_start key
import json, numpy as np, soundfile as sf, torch

W = "/mnt/d/CloneDub/work/v12_3min_1470_1650"
INV = W + "/investigation"
VOX = "/mnt/d/CloneDub/work/video1_meteor_video_clone/demucs/htdemucs/full/vocals.wav"
OUTREF = W + "/orig_voice_refs_v5"
import os; os.makedirs(OUTREF, exist_ok=True)

A3B = json.load(open(INV + "/wordlines_a3b.json", encoding="utf-8"))
t7 = json.load(open(W + "/diar_7min/turns.json"))["turns"]
lines = A3B["lines"]

info = sf.info(VOX); sr = info.samplerate
from speechbrain.inference.speaker import EncoderClassifier
enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                     savedir="/mnt/d/CloneDub/hf_cache/ecapa_sb",
                                     run_opts={"device": "cpu"})

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

# female anchors = the two biggest female clusters from a3b (F_0-group, F_2-group)
groups = {}
for L in lines:
    if L["gender"] == "female":
        groups.setdefault(L["actor"], []).append(L)
big2 = sorted(groups, key=lambda k: -sum(x["dur"] for x in groups[k]))[:2]
anchors = {}
for name in big2:
    e = np.mean([x["emb"] for x in groups[name]], axis=0)
    anchors[name] = e / (np.linalg.norm(e) + 1e-9)
ren = {big2[0]: "F_A", big2[1]: "F_B"}
print("female anchors:", big2, "->", list(ren.values()))

for L in lines:
    if L["gender"] == "male":
        L["actor2"] = "M"
    else:
        sims = {n: float(np.dot(L["emb"], a)) for n, a in anchors.items()}
        # time proximity bonus toward temporally adjacent same-anchor lines
        best = max(sims, key=sims.get)
        L["actor2"] = ren[best]; L["a2sim"] = round(sims[best], 2)

# force rant continuity: a line fully inside 0.3s of previous line end, same gender ->
# same actor as previous (conversation continuity for adjacent same-gender splits)
for i in range(1, len(lines)):
    if (lines[i]["gender"] == lines[i-1]["gender"] and
            lines[i]["abs_start"] - lines[i-1]["abs_end"] <= 0.3 and
            lines[i]["actor2"] != lines[i-1]["actor2"]):
        lines[i]["actor2"] = lines[i-1]["actor2"]

# fold tiny (<0.5s) zero-gap sentence-tail fragments into previous line
folded = []
for L in lines:
    if (folded and L["dur"] < 0.5 and L["abs_start"] - folded[-1]["abs_end"] <= 0.05):
        folded[-1]["abs_end"] = L["abs_end"]; folded[-1]["zh"] += L["zh"]
        folded[-1]["dur"] = round(folded[-1]["abs_end"] - folded[-1]["abs_start"], 2)
        continue
    folded.append(L)
# merge adjacent same-actor
merged = []
for L in folded:
    if merged and L["actor2"] == merged[-1]["actor2"] and L["abs_start"] - merged[-1]["abs_end"] < 0.5:
        merged[-1]["abs_end"] = L["abs_end"]; merged[-1]["zh"] += " " + L["zh"]
        merged[-1]["dur"] = round(merged[-1]["abs_end"] - merged[-1]["abs_start"], 2)
    else:
        merged.append(L)

TR = {  # abs_start(round1) -> Urdu+Eng Devanagari, sized to slot
  1472.7: "यहाँ ठीक रहेगा? चलो यहीं शूट करें।",
  1479.3: "जी हाँ!",
  1482.4: "तुम वहाँ जाओ, मैं सोलो फ़ोटो लेती हूँ।",
  1488.0: "ज़रा इधर आओ... ऐसे? केक फ़्रेम में नहीं आ रहा, थोड़ा और क़रीब आओ।",
  1499.6: "तुम ठीक हो? मैं फ़ाइन हूँ। डरा ही दिया था, ज़रा केयरफुल! फ़ोन बच गया... पर केक गिर गया, कुछ हाथ न आया।",
  1511.3: "फिर से तुम लोग?",
  1513.1: "सॉरी, सॉरी! मैंने जान-बूझकर नहीं किया।",
  1519.4: "सॉरी से सब ठीक होता, तो पुलिस क्यों होती?",
  1524.4: "दाओमिंग-सी सीनियर, मैं साफ़ कर देती हूँ।",
  1529.3: "हट जाओ!",
  1530.9: "अरे!",
  1534.1: "ठीक हो? हाँ, फ़ाइन। ...ऐ, वहीं रुको!",
  1540.1: "उसने जान-बूझकर नहीं किया, माफ़ी भी माँगी, इतना ग़ुस्सा ज़रूरी है?",
  1549.8: "तुम्हें लगता है तुम बहुत ख़ास हो? ख़ुद को स्कूल की सबसे बड़ी हस्ती समझते हो, जहाँ जाते हो अकड़ दिखाते हो। किसी का फ़ोन तोड़कर सॉरी तक नहीं — तुम सच में पूरे बदतमीज़ हो!",
  1562.3: "हुँह!",
  1565.6: "तुम...",
  1570.7: "हिम्मत है!",
  1607.7: "शानचाई, फ़ाइट क्यों हुई? ...पता नहीं, मैं इतनी इम्पल्सिव कैसे हो गई।",
  1620.9: "बस, आगे से ऐसा नहीं करूँगी।",
  1645.0: "झेगेर की थाली? शानचाई, तुम...",
  1647.2: "थाली कैसे मिली? ज़रूर दाओमिंग-सी की वजह से।",
}
def fmt(t):
    s = t - 1470.0
    return "%d:%04.1f" % (int(s // 60), s % 60)
final = []
for L in merged:
    key = round(L["abs_start"], 1)
    hi = TR.get(key)
    if hi is None:
        near = [k for k in TR if abs(k - key) <= 0.3]
        hi = TR[near[0]] if near else ""
    final.append({"vid": len(final), "abs_start": L["abs_start"], "abs_end": L["abs_end"],
                  "dur": L["dur"], "actor": L["actor2"], "gender": L["gender"],
                  "zh": L["zh"], "hindi": hi})
print("=== FINAL v5 LINES (%d) ===" % len(final))
for L in final:
    tag = "MISSING-TR" if not L["hindi"] else ""
    print("V%02d %s-%s %-3s %-6s %s | %s" % (L["vid"], fmt(L["abs_start"]), fmt(L["abs_end"]),
          L["actor"], L["gender"], tag, L["hindi"][:40]))

# exclusive refs: each solo clip -> best actor only (sim>=0.45), SNR-sorted, 13s cap
cents = {}
for name in ("F_A", "F_B", "M"):
    mem = [L for L in final if L["actor"] == name and L["dur"] >= 1.0]
    if not mem: continue
    es = [embed(read16k(L["abs_start"], L["abs_end"])) for L in mem]
    e = np.mean(es, axis=0); cents[name] = e / (np.linalg.norm(e) + 1e-9)
solo = []
for i, s in enumerate(t7):
    a0, a1v = s["abs_start"], s["abs_end"]; d = a1v - a0
    if d < 1.2: continue
    ov = any(j != i and u["speaker"] != s["speaker"] and
             (min(a1v, u["abs_end"]) - max(a0, u["abs_start"])) > 0.15 for j, u in enumerate(t7))
    if ov: continue
    x = read16k(a0, a1v)
    solo.append({"a0": a0, "a1": a1v, "d": d, "snr": snr_db(x), "emb": embed(x)})
buckets = {n: [] for n in cents}
for c in solo:
    sims = {n: float(np.dot(c["emb"], e)) for n, e in cents.items()}
    best = max(sims, key=sims.get)
    if sims[best] >= 0.45: buckets[best].append((c, sims[best]))
refs = {}
for name, bl in buckets.items():
    bl.sort(key=lambda t: (-t[0]["snr"], -t[0]["d"]))
    parts = []; tot = 0.0; meta = []
    for c, sim in bl:
        x, _ = sf.read(VOX, start=int(c["a0"] * sr), stop=int(c["a1"] * sr))
        if x.ndim > 1: x = x.mean(1)
        parts.append(x.astype(np.float32)); parts.append(np.zeros(int(0.15 * sr), dtype=np.float32))
        tot += c["d"]; meta.append((round(c["d"], 1), round(c["snr"], 1), round(sim, 2)))
        if tot >= 13: break
    if tot < 3.0:  # fallback to own lines (boosted)
        parts = []; tot = 0.0; meta = [("own", 0, 0)]
        for L in sorted([L for L in final if L["actor"] == name], key=lambda L: -L["dur"]):
            x, _ = sf.read(VOX, start=int(L["abs_start"] * sr), stop=int(L["abs_end"] * sr))
            if x.ndim > 1: x = x.mean(1)
            x = x.astype(np.float32); x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
            parts.append(x); parts.append(np.zeros(int(0.15 * sr), dtype=np.float32))
            tot += L["dur"]
            if tot >= 13: break
    cc = np.concatenate(parts); cc = cc / (np.max(np.abs(cc)) + 1e-9) * 0.95
    fn = OUTREF + "/ref_%s.wav" % name
    sf.write(fn, cc, sr)
    n16 = int(len(cc) * 16000 / sr)
    x16 = np.interp(np.linspace(0, len(cc), n16, endpoint=False), np.arange(len(cc)), cc).astype(np.float32)
    refs[name] = {"wav": fn, "dur": round(len(cc)/sr, 1), "snr": round(snr_db(x16), 1), "clips": meta[:5]}
    print("%s ref: %.1fs SNR=%.1f %s" % (name, len(cc)/sr, refs[name]["snr"], meta[:4]))

json.dump({"window": [1470.0, 1650.0], "lines": final, "refs": refs},
          open(W + "/lines_v5.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("B_DONE lines=%d" % len(final))
