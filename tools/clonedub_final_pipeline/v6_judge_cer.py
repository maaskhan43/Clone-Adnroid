# -*- coding: utf-8 -*-
# Judge part 1 (SoniTranslate venv): CER for every v6 candidate wav.
import json, os, re, glob, unicodedata
from faster_whisper import WhisperModel

W = "/mnt/d/CloneDub/work/v12_3min_1470_1650"
GEN = W + "/generated_wavs_v6"
rep = json.load(open(W + "/v6_gen_report.json", encoding="utf-8"))
txt = {(r["vid"], r["cand"]): r["text"] for r in rep}

def norm(s):
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[^ऀ-ॿ ]", "", s)
    return re.sub(r"\s+", "", s)

def lev(a, b):
    if not a: return len(b)
    if not b: return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        cur = [i + 1]
        for j, cb in enumerate(b):
            cur.append(min(prev[j + 1] + 1, cur[j] + 1, prev[j] + (ca != cb)))
        prev = cur
    return prev[-1]

m = WhisperModel("small", device="cpu", compute_type="int8")
out = []
for fn in sorted(glob.glob(GEN + "/V*_c*.wav")):
    b = os.path.basename(fn)[:-4]
    vid = int(b[1:3]); cand = int(b.split("_c")[1])
    target = txt.get((vid, cand))
    if target is None: continue
    segs, _ = m.transcribe(fn, task="transcribe", beam_size=5, language="hi")
    hyp = " ".join(s.text.strip() for s in segs).strip()
    ref = norm(target); h = norm(hyp)
    cer = 100.0 * lev(ref, h) / max(len(ref), 1)
    out.append({"vid": vid, "cand": cand, "cer": round(cer, 1), "heard": hyp})
    print("V%02d_c%d CER=%5.1f | heard: %s" % (vid, cand, cer, hyp[:40]), flush=True)
json.dump(out, open(W + "/v6_judge_cer.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("V6_CER_DONE n=%d" % len(out))
