# -*- coding: utf-8 -*-
# Stage A2: 2nd-pass ASR on diar turns that got no words in the full pass.
# Slice vocals (pad +-0.3s), amplify, transcribe WITHOUT vad filter.
import json, numpy as np, soundfile as sf
from faster_whisper import WhisperModel

W = "/mnt/d/CloneDub/work/v12_3min_1470_1650"
INV = W + "/investigation"
VOX = "/mnt/d/CloneDub/work/video1_meteor_video_clone/demucs/htdemucs/full/vocals.wav"
A1 = json.load(open(INV + "/wordlines_a1.json", encoding="utf-8"))
T0 = 1470.0

info = sf.info(VOX); sr = info.samplerate
m = WhisperModel("small", device="cpu", compute_type="int8")
recovered = []
for e in A1["empty_turns"]:
    dur = e["abs_end"] - e["abs_start"]
    if dur < 0.25: continue
    a0, a1 = e["abs_start"] - 0.3, e["abs_end"] + 0.3
    x, _ = sf.read(VOX, start=int(a0 * sr), stop=int(a1 * sr))
    if x.ndim > 1: x = x.mean(1)
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
    n = int(len(x) * 16000 / sr)
    x16 = np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x).astype(np.float32)
    sf.write("/tmp/a2.wav", x16, 16000)
    segs, _ = m.transcribe("/tmp/a2.wav", task="transcribe", beam_size=5, language="zh")
    txt = " ".join(s.text.strip() for s in segs).strip()
    st = e["abs_start"] - T0
    print("turn %d:%04.1f (%s %.1fs) -> %r" % (int(st//60), st % 60, e["spk"], dur, txt), flush=True)
    if txt:
        recovered.append({"abs_start": e["abs_start"], "abs_end": e["abs_end"],
                          "spk": e["spk"], "zh": txt, "recovered": True})
json.dump(recovered, open(INV + "/wordlines_a2_recovered.json", "w", encoding="utf-8"),
          indent=1, ensure_ascii=False)
print("A2_DONE recovered=%d" % len(recovered))
