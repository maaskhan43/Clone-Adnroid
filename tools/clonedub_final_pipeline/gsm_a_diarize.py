# -*- coding: utf-8 -*-
"""Global Speaker Map — stage A (pyannote venv):
ONE diarization pass over the FULL movie -> globally consistent speaker labels.
Output: work/video1_actors/global_turns.json
Research basis: pyannote 3.1 clusters across the entire recording (CAM++ embeddings
internally, DER ~11%); per-window diar was the cause of label inconsistency.
"""
import os, json
import numpy as np, soundfile as sf, torch
from pyannote.audio import Pipeline

VOX = "/mnt/d/CloneDub/work/video1_meteor_video_clone/demucs/htdemucs/full/vocals.wav"
OUT = "/mnt/d/CloneDub/work/video1_actors"
os.makedirs(OUT, exist_ok=True)
W16 = OUT + "/full_vocals_16k.wav"

if not os.path.exists(W16):
    info = sf.info(VOX); sr = info.samplerate
    a, _ = sf.read(VOX)
    if a.ndim > 1:
        a = a.mean(1)
    a = a.astype(np.float32)
    n = int(len(a) * 16000 / sr)
    a16 = np.interp(np.linspace(0, len(a), n, endpoint=False), np.arange(len(a)), a).astype(np.float32)
    sf.write(W16, a16, 16000)
    print("full 16k wav: %.0fs" % (len(a16) / 16000), flush=True)

pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1",
                                use_auth_token=os.environ.get("HF_TOKEN"))
pipe.to(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
print("pipeline loaded, diarizing FULL movie (~30-40 min)...", flush=True)
diar = pipe(W16)
turns = []
per = {}
for turn, _, spk in diar.itertracks(yield_label=True):
    turns.append({"abs_start": round(turn.start, 2), "abs_end": round(turn.end, 2),
                  "speaker": spk})
    per[spk] = per.get(spk, 0) + (turn.end - turn.start)
json.dump({"turns": turns}, open(OUT + "/global_turns.json", "w"), indent=1)
print("global speakers=%d turns=%d" % (len(per), len(turns)), flush=True)
for spk, tot in sorted(per.items(), key=lambda x: -x[1])[:12]:
    print("  %s: %.1fs" % (spk, tot), flush=True)
print("GSM_A_DONE")
