# -*- coding: utf-8 -*-
# INVESTIGATION step 1: word-level ASR of the 1400-1800s window (original vocals).
# Gives exact per-word timestamps = ground truth of who says what when.
# Output: asr_words.json with abs-time per word. NO changes to pipeline files.
import json
from faster_whisper import WhisperModel

WAV = "/mnt/d/CloneDub/work/v12_3min_1470_1650/diar_7min/window_vocals.wav"  # 1400-1800 @16k
T0 = 1400.0
OUT = "/mnt/d/CloneDub/work/v12_3min_1470_1650/investigation"
import os; os.makedirs(OUT, exist_ok=True)

m = WhisperModel("small", device="cpu", compute_type="int8")
segs, info = m.transcribe(WAV, task="transcribe", beam_size=5,
                          word_timestamps=True, vad_filter=True)
out = []
for s in segs:
    seg = {"abs_start": round(s.start + T0, 2), "abs_end": round(s.end + T0, 2),
           "text": s.text.strip(), "words": []}
    for w in (s.words or []):
        seg["words"].append({"abs_start": round(w.start + T0, 2),
                             "abs_end": round(w.end + T0, 2), "word": w.word})
    out.append(seg)
    print("SEG %.1f-%.1f | %s" % (seg["abs_start"], seg["abs_end"], seg["text"][:40]), flush=True)
json.dump({"language": info.language, "segments": out},
          open(OUT + "/asr_words.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("ASR_WORDS_DONE segs=%d" % len(out), flush=True)
