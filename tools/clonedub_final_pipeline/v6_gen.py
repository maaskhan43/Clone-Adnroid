# -*- coding: utf-8 -*-
# V6 generation: per-line candidates with new continuous refs.
# - V01/V10/V14 skipped (original-audio interjections, added at assembly)
# - flagged lines get 3 candidates; others 1 (failures get more later)
# - text tiers for slot-tight lines: if too long even at speed 1.10 -> shorter tier
# - energy-based START TRIM (kills F5's known 200-400ms onset garble)
import os, json, numpy as np, soundfile as sf, torch
from transformers import AutoModel

W = "/mnt/d/CloneDub/work/v12_3min_1470_1650"
D = json.load(open(W + "/lines_v5.json", encoding="utf-8"))
REF6 = W + "/orig_voice_refs_v6"
GEN = W + "/generated_wavs_v6"; os.makedirs(GEN, exist_ok=True)
T0, T1 = D["window"]; SR = 24000; MAX_SPEED = 1.10
SKIP = {1, 10, 14}                      # original-audio interjections
FLAGGED = {0, 3, 4, 7, 13, 20}          # 3 candidates each
TIERS = {
  7:  ["सॉरी से सब ठीक होता, तो पुलिस क्यों होती?",
       "सॉरी से सब ठीक होता तो पुलिस क्यों?"],
  13: ["ख़ुद को स्कूल की सबसे बड़ी हस्ती समझते हो? हर जगह अकड़ दिखाते हो। फ़ोन तोड़कर सॉरी तक नहीं — तुम पूरे बदतमीज़ हो!",
       "ख़ुद को स्कूल का सबसे ख़ास समझते हो? फ़ोन तोड़कर सॉरी भी नहीं — बदतमीज़!"],
  20: ["थाली कैसे मिली? ज़रूर उसी वजह से।",
       "थाली उसी वजह से मिली होगी।"],
  4:  ["तुम ठीक हो? मैं फ़ाइन हूँ। डरा ही दिया था, ज़रा केयरफुल! फ़ोन बच गया... पर केक गिर गया, कुछ हाथ न आया।",
       "तुम ठीक हो? मैं फ़ाइन। डरा दिया! फ़ोन बच गया, पर केक गिर गया — कुछ हाथ न आया।"],
}

def start_trim(a, sr_):
    # trim leading low-energy/garble: first frame of sustained speech, max 0.5s
    fl = int(0.03 * sr_)
    peak = np.max(np.abs(a)) + 1e-9
    thr = 0.10 * peak
    run = 0; onset = 0
    for i in range(0, min(len(a), int(0.6 * sr_)), fl):
        if np.max(np.abs(a[i:i+fl])) > thr:
            run += 1
            if run >= 3:
                onset = max(0, i - 2 * fl); break
        else:
            run = 0
    return a[onset:] if onset > 0 and onset < int(0.5 * sr_) else a

def speedup(a, f):
    if f <= 1.001: return a
    n = int(len(a) / f)
    return np.interp(np.linspace(0, len(a), n, endpoint=False), np.arange(len(a)), a).astype(np.float32)

dev = "cuda" if torch.cuda.is_available() else "cpu"
model = AutoModel.from_pretrained("ai4bharat/IndicF5", trust_remote_code=True).to(dev)
print("model on", dev, flush=True)

def refpath(actor):
    p = REF6 + "/ref_%s.wav" % actor
    if os.path.exists(p): return p, open(REF6 + "/ref_%s.txt" % actor, encoding="utf-8").read().strip()
    p5 = W + "/orig_voice_refs_v5/ref_%s.wav" % actor  # fallback to v5 ref
    return p5, open(W + "/orig_voice_refs_v5/ref_%s.txt" % actor, encoding="utf-8").read().strip()

lines = sorted(D["lines"], key=lambda L: L["abs_start"])
rep = []
for i, L in enumerate(lines):
    vid = L["vid"]
    if vid in SKIP: continue
    nxt = lines[i + 1]["abs_start"] if i + 1 < len(lines) else T1
    avail = min(nxt, T1) - L["abs_start"] - 0.15
    texts = TIERS.get(vid, [L["hindi"]])
    ncand = 3 if vid in FLAGGED else 1
    rw, rt = refpath(L["actor"])
    made = 0; tier_used = 0
    for c in range(ncand):
        hi = texts[min(tier_used, len(texts) - 1)]
        for attempt in range(len(texts) - tier_used):
            audio = model(hi, ref_audio_path=rw, ref_text=rt)
            a = np.array(audio, dtype=np.float32)
            if a.size < SR // 8:
                continue
            if np.max(np.abs(a)) > 1.5: a = a / 32768.0
            a = a / (np.max(np.abs(a)) + 1e-9) * 0.9
            a = start_trim(a, SR)
            gen = len(a) / SR
            if gen <= avail * MAX_SPEED or avail <= 0.4:
                f = max(1.0, min(MAX_SPEED, gen / avail)) if avail > 0.4 else 1.0
                a = speedup(a, f)
                fn = "%s/V%02d_c%d.wav" % (GEN, vid, c)
                sf.write(fn, a, SR)
                rep.append({"vid": vid, "cand": c, "text": hi, "final": round(len(a)/SR, 2),
                            "avail": round(avail, 2), "speed": round(f, 2)})
                made += 1
                print("  V%02d_c%d %s final=%.2f avail=%.2f sp=%.2f | %s" % (
                    vid, c, L["actor"], len(a)/SR, avail, f, hi[:22]), flush=True)
                break
            else:
                tier_used += 1
                hi = texts[min(tier_used, len(texts) - 1)]
                print("  V%02d too long (%.1f>%.1f) -> shorter tier" % (vid, gen, avail), flush=True)
    if made == 0:
        print("  V%02d NO CANDIDATE (all empty/long)" % vid, flush=True)
json.dump(rep, open(W + "/v6_gen_report.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("V6_GEN_DONE cands=%d" % len(rep), flush=True)
