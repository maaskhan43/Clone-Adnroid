# -*- coding: utf-8 -*-
"""Global Speaker Map — stage B (chatterbox venv):
Build registry v2 from global turns:
- solo turns only, SPEECH-EVIDENCE filter (full-movie word timestamps), SNR>=18, dur>=1.5
- per global speaker: MULTI-FINGERPRINT set (up to 10 diverse ECAPA embeddings),
  best continuous clean ref (score=2*min(dur,11)+SNR), gender (JaesungHuh),
- link old registry actors (F_A/F_B/M) to global speakers (keep proven names+refs)
Output: work/video1_actors/registry.json (v2: "centroids" list; s05 uses max-sim)
"""
import os, sys, json
import numpy as np, soundfile as sf, torch
from speechbrain.inference.speaker import EncoderClassifier
sys.path.insert(0, "/mnt/d/CloneDub/voice_gender_clf")
from model import ECAPA_gender

REG = "/mnt/d/CloneDub/work/video1_actors"
VOX = "/mnt/d/CloneDub/work/video1_meteor_video_clone/demucs/htdemucs/full/vocals.wav"
SEG = "/mnt/d/CloneDub/work/video1_meteor_video_clone/segments_diarized.json"
turns = json.load(open(REG + "/global_turns.json"))["turns"]
words = [(w["start"], w["end"]) for s in json.load(open(SEG))["segments"] for w in s.get("words", [])]

info = sf.info(VOX); sr = info.samplerate
enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                     savedir="/mnt/d/CloneDub/hf_cache/ecapa_sb",
                                     run_opts={"device": "cpu"})
gcl = ECAPA_gender.from_pretrained("JaesungHuh/voice-gender-classifier"); gcl.eval()

def read(a0, a1):
    x, _ = sf.read(VOX, start=int(a0 * sr), stop=int(a1 * sr))
    if x.ndim > 1:
        x = x.mean(1)
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
    y = to16k(x); fl = 1600
    fe = np.array([np.sqrt(np.mean(y[i:i+fl]**2)) for i in range(0, max(len(y)-fl, 1), fl)])
    if len(fe) < 3:
        return 0.0
    return float(20 * np.log10((np.percentile(fe, 90) + 1e-9) / (np.percentile(fe, 10) + 1e-9)))

def has_speech(a0, a1):
    return any(a0 - 0.2 <= (ws + we) / 2 <= a1 + 0.2 for ws, we in words)

# clean solo turns per global speaker
solo = {}
for i, t in enumerate(turns):
    d = t["abs_end"] - t["abs_start"]
    if d < 1.5:
        continue
    ov = any(j != i and u["speaker"] != t["speaker"] and
             (min(t["abs_end"], u["abs_end"]) - max(t["abs_start"], u["abs_start"])) > 0.15
             for j, u in enumerate(turns))
    if ov or not has_speech(t["abs_start"], t["abs_end"]):
        continue
    x = read(t["abs_start"], t["abs_end"])
    s = snr_db(x)
    if s < 18:
        continue
    solo.setdefault(t["speaker"], []).append(
        {"a0": t["abs_start"], "a1": t["abs_end"], "d": d, "snr": s})
print("speakers with clean solo material: %d" % len(solo), flush=True)

reg2 = {}
os.makedirs("/tmp/gsm", exist_ok=True)
for spk, clips in sorted(solo.items(), key=lambda kv: -sum(c["d"] for c in kv[1])):
    total = sum(c["d"] for c in clips)
    if total < 4.0:      # too little material to be a real recurring character
        continue
    # multi-fingerprint: up to 10, spread across the movie (diverse moods)
    clips_sorted = sorted(clips, key=lambda c: c["a0"])
    step = max(1, len(clips_sorted) // 10)
    fps = []
    for c in clips_sorted[::step][:10]:
        fps.append([float(v) for v in embed(read(c["a0"], min(c["a1"], c["a0"] + 8)))])
    # best continuous ref
    best = max(clips, key=lambda c: 2 * min(c["d"], 11) + c["snr"])
    a0, a1 = best["a0"], min(best["a1"], best["a0"] + 11)
    x = read(a0, a1)
    # gender from the ref clip
    sf.write("/tmp/gsm/g.wav", to16k(x / (np.max(np.abs(x)) + 1e-9) * 0.9), 16000)
    with torch.no_grad():
        gender = gcl.predict("/tmp/gsm/g.wav", device="cpu")
    xr = x / (np.max(np.abs(x)) + 1e-9) * 0.85
    xr = np.concatenate([xr, np.zeros(int(0.35 * sr), dtype=np.float32)])
    wavp = REG + "/ref_%s.wav" % spk
    sf.write(wavp, xr, sr)
    # transcript from full-movie words in ref span
    seg = json.load(open(SEG))
    ws = [w["word"] for s in seg["segments"] for w in s.get("words", [])
          if a0 - 0.2 <= w["start"] <= a1 + 0.2]
    open(REG + "/ref_%s.txt" % spk, "w", encoding="utf-8").write("".join(ws).strip())
    reg2[spk] = {"gender": gender, "centroids": fps, "total_s": round(total, 1),
                 "ref_wav": wavp, "ref_txt": REG + "/ref_%s.txt" % spk,
                 "ref_span": [a0, a1], "ref_snr": round(best["snr"], 1)}
    print("%s %s total=%.0fs fingerprints=%d ref=%.1f-%.1f snr=%.1f" % (
        spk, gender, total, len(fps), a0, a1, best["snr"]), flush=True)

# link old proven actors (F_A/F_B/M) to global ids — keep old names as aliases
old = json.load(open(REG + "/registry.json")) if os.path.exists(REG + "/registry.json") else {}
alias = {}
for oname, o in old.items():
    if not o.get("centroid"):
        continue
    oe = np.array(o["centroid"])
    bestg, bestv = None, 0.5
    for gname, g in reg2.items():
        v = max(float(np.dot(oe, np.array(c))) for c in g["centroids"])
        if v > bestv and g["gender"] == o["gender"]:
            bestv, bestg = v, gname
    if bestg:
        alias[oname] = bestg
        print("ALIAS %s -> %s (%.2f)" % (oname, bestg, bestv), flush=True)
        # keep the PROVEN old ref for continuity (scenes 1-8 used it)
        reg2[bestg]["ref_wav"] = o["ref_wav"]
        reg2[bestg]["ref_txt"] = o["ref_txt"]
        reg2[bestg]["alias"] = oname
json.dump({"version": 2, "actors": reg2, "aliases": alias},
          open(REG + "/registry_v2.json", "w"), indent=1)
print("GSM_B_DONE actors=%d aliases=%d" % (len(reg2), len(alias)))
