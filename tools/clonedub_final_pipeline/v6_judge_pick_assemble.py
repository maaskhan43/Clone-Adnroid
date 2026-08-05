# -*- coding: utf-8 -*-
# Judge part 2 (chatterbox venv): UTMOS + ECAPA sim for every candidate;
# combine with CER -> pick best candidate per line -> assemble v6 scene:
#   TTS best picks + ORIGINAL-audio interjections (V01,V10,V14) + bed 0.6x.
import json, os, glob, numpy as np, soundfile as sf, torch

W = "/mnt/d/CloneDub/work/v12_3min_1470_1650"
GEN = W + "/generated_wavs_v6"
VOX = "/mnt/d/CloneDub/work/video1_meteor_video_clone/demucs/htdemucs/full/vocals.wav"
D = json.load(open(W + "/lines_v5.json", encoding="utf-8"))
CER = {(c["vid"], c["cand"]): c for c in json.load(open(W + "/v6_judge_cer.json", encoding="utf-8"))}
REF6 = W + "/orig_voice_refs_v6"
T0, T1 = D["window"]; SCENE = T1 - T0; SR = 24000
ORIG_INTJ = {1, 10, 14}

pred = torch.hub.load("tarepan/SpeechMOS:v1.2.0", "utmos22_strong", trust_repo=True)
from speechbrain.inference.speaker import EncoderClassifier
enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                     savedir="/mnt/d/CloneDub/hf_cache/ecapa_sb",
                                     run_opts={"device": "cpu"})

def utmos(path):
    a, sr = sf.read(path)
    if a.ndim > 1: a = a.mean(1)
    with torch.no_grad():
        return float(pred(torch.from_numpy(a.astype(np.float32)).unsqueeze(0), sr))

def emb_wav(a, sr):
    if a.ndim > 1: a = a.mean(1)
    a = a.astype(np.float32)
    if sr != 16000:
        n = int(len(a) * 16000 / sr)
        a = np.interp(np.linspace(0, len(a), n, endpoint=False), np.arange(len(a)), a).astype(np.float32)
    with torch.no_grad():
        e = enc.encode_batch(torch.tensor(a).unsqueeze(0)).squeeze().cpu().numpy()
    return e / (np.linalg.norm(e) + 1e-9)

refemb = {}
for name in ("F_A", "F_B", "M"):
    a, sr = sf.read(REF6 + "/ref_%s.wav" % name)
    refemb[name] = emb_wav(a, sr)

lines = {L["vid"]: L for L in D["lines"]}
scores = []
for fn in sorted(glob.glob(GEN + "/V*_c*.wav")):
    b = os.path.basename(fn)[:-4]
    vid = int(b[1:3]); cand = int(b.split("_c")[1])
    if (vid, cand) not in CER: continue
    L = lines[vid]
    u = utmos(fn)
    a, sr = sf.read(fn)
    sim = float(np.dot(emb_wav(a, sr), refemb[L["actor"]]))
    cer = CER[(vid, cand)]["cer"]
    dur = len(a) / sr if a.ndim == 1 else len(a) / sr
    # composite: CER dominates (pronunciation), then UTMOS, then sim
    comp = -cer * 1.0 + u * 8 + sim * 15
    scores.append({"vid": vid, "cand": cand, "cer": cer, "utmos": round(u, 2),
                   "sim": round(sim, 2), "comp": round(comp, 1), "dur": round(dur, 2)})
    print("V%02d_c%d cer=%5.1f utmos=%.2f sim=%.2f comp=%6.1f" % (vid, cand, cer, u, sim, comp), flush=True)

best = {}
for s in scores:
    if s["vid"] not in best or s["comp"] > best[s["vid"]]["comp"]:
        best[s["vid"]] = s
json.dump({"scores": scores, "best": best}, open(W + "/v6_judge_final.json", "w"), indent=1)
print("=== BEST PICKS ===")
for vid, s in sorted(best.items()):
    print("V%02d -> c%d (cer=%.1f utmos=%.2f sim=%.2f)" % (vid, s["cand"], s["cer"], s["utmos"], s["sim"]), flush=True)

# assemble
info = sf.info(VOX); vsr = info.samplerate
tl = np.zeros(int(SCENE * SR) + SR)
for L in sorted(D["lines"], key=lambda x: x["abs_start"]):
    vid = L["vid"]
    if vid in ORIG_INTJ:
        x, _ = sf.read(VOX, start=int(L["abs_start"] * vsr), stop=int(L["abs_end"] * vsr))
        if x.ndim > 1: x = x.mean(1)
        x = x.astype(np.float32)
        x = x / (np.max(np.abs(x)) + 1e-9) * 0.75    # original interjection, normalized
        n = int(len(x) * SR / vsr)
        a = np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x)
    else:
        if vid not in best:
            print("V%02d has no pick - SKIP" % vid, flush=True); continue
        a, sr = sf.read("%s/V%02d_c%d.wav" % (GEN, vid, best[vid]["cand"]))
        if a.ndim > 1: a = a.mean(1)
    s = int(round((L["abs_start"] - T0) * SR)); e = s + len(a)
    if e > len(tl): a = a[:len(tl) - s]; e = len(tl)
    tl[s:e] += a
tl = tl[:int(SCENE * SR)]
voice = tl * (0.75 / (np.abs(tl).max() + 1e-9))
NOVOX = "/mnt/d/CloneDub/work/video1_meteor_video_clone/demucs/htdemucs/full/no_vocals.wav"
binfo = sf.info(NOVOX); bsr = binfo.samplerate
bed, _ = sf.read(NOVOX, start=int(T0 * bsr), stop=int(T1 * bsr))
if bed.ndim > 1: bed = bed.mean(1)
if bsr != SR:
    n = int(len(bed) * SR / bsr)
    bed = np.interp(np.linspace(0, len(bed), n, endpoint=False), np.arange(len(bed)), bed)
n = min(len(bed), len(voice)); mix = voice[:n] + bed[:n] * 0.6
mix = mix * (0.99 / max(np.abs(mix).max(), 0.99))
sf.write(W + "/scene_3min_v6.wav", mix.astype(np.float32), SR)
print("V6_ASSEMBLE_DONE")
