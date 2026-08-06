# -*- coding: utf-8 -*-
"""Stage 2: word-level ASR of the diar window -> asr_words.json (abs times)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CFG, wpath
from faster_whisper import WhisperModel

w0 = json.load(open(wpath("diar", "turns.json")))["window"][0]
m = WhisperModel("small", device="cpu", compute_type="int8")
segs, info = m.transcribe(wpath("diar", "window_vocals.wav"), task="transcribe",
                          beam_size=5, word_timestamps=True, vad_filter=True)
out = []
for s in segs:
    seg = {"abs_start": round(s.start + w0, 2), "abs_end": round(s.end + w0, 2),
           "text": s.text.strip(), "words": []}
    for w in (s.words or []):
        seg["words"].append({"abs_start": round(w.start + w0, 2),
                             "abs_end": round(w.end + w0, 2), "word": w.word})
    out.append(seg)
    print("SEG %.1f-%.1f | %s" % (seg["abs_start"], seg["abs_end"], seg["text"][:40]), flush=True)
json.dump({"language": info.language, "segments": out},
          open(wpath("asr_words.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("ASR segs=%d" % len(out))
