# -*- coding: utf-8 -*-
# Stage A1: word-level line builder.
# words (asr_words.json) x diarization turns (diar_7min) ->
#   per-word speaker (max-overlap, turns padded +-0.25s)
#   -> majority-smoothing (window 3) to kill single-word flips
#   -> split lines at smoothed speaker change OR gap>0.8s, cap 12s
# Also: list diar turns in window with NO words inside (candidates for 2nd-pass ASR).
import json

W = "/mnt/d/CloneDub/work/v12_3min_1470_1650"
INV = W + "/investigation"
T0, T1 = 1470.0, 1650.0
A = json.load(open(INV + "/asr_words.json", encoding="utf-8"))
t7 = json.load(open(W + "/diar_7min/turns.json"))["turns"]
turns = [u for u in t7 if u["abs_end"] > T0 - 2 and u["abs_start"] < T1 + 2]

words = []
for seg in A["segments"]:
    for w in seg["words"]:
        if T0 - 0.5 <= w["abs_start"] <= T1 + 0.5:
            words.append(dict(w))
words.sort(key=lambda w: w["abs_start"])

def spk_of(w):
    mid = (w["abs_start"] + w["abs_end"]) / 2
    best, bestov = None, 0.0
    for u in turns:
        ov = min(w["abs_end"], u["abs_end"] + 0.25) - max(w["abs_start"], u["abs_start"] - 0.25)
        if ov > bestov:
            bestov = ov; best = u["speaker"]
    return best

for w in words:
    w["spk"] = spk_of(w)

# majority smoothing over 3 (only relabel middle if both neighbors agree and differ)
sm = [w["spk"] for w in words]
for i in range(1, len(words) - 1):
    a, b, c = words[i-1]["spk"], words[i]["spk"], words[i+1]["spk"]
    if a == c and b != a and a is not None:
        # only flip if word is short (<0.5s) - long words trust their own overlap
        if words[i]["abs_end"] - words[i]["abs_start"] < 0.5:
            sm[i] = a
for i, w in enumerate(words):
    w["spk_sm"] = sm[i]

# build lines
lines = []
cur = None
for w in words:
    if cur and (w["spk_sm"] != cur["spk"] or
                w["abs_start"] - cur["abs_end"] > 0.8 or
                w["abs_end"] - cur["abs_start"] > 12.0):
        lines.append(cur); cur = None
    if cur is None:
        cur = {"abs_start": w["abs_start"], "abs_end": w["abs_end"],
               "spk": w["spk_sm"], "zh": w["word"]}
    else:
        cur["abs_end"] = w["abs_end"]; cur["zh"] += w["word"]
if cur: lines.append(cur)

def fmt(t):
    s = t - T0
    return "%d:%04.1f" % (int(s // 60), s % 60)

print("=== WORD-LEVEL LINES (%d) ===" % len(lines))
for i, L in enumerate(lines):
    L["wid"] = i
    print("W%02d %s-%s %-11s | %s" % (i, fmt(L["abs_start"]), fmt(L["abs_end"]),
                                      str(L["spk"]), L["zh"][:38]))

# diar turns in scene window with NO words inside -> 2nd-pass candidates
empties = []
for u in turns:
    if u["abs_end"] < T0 or u["abs_start"] > T1: continue
    has = any(u["abs_start"] - 0.3 <= (w["abs_start"]+w["abs_end"])/2 <= u["abs_end"] + 0.3 for w in words)
    if not has:
        empties.append({"abs_start": u["abs_start"], "abs_end": u["abs_end"], "spk": u["speaker"]})
print("=== EMPTY TURNS (2nd-pass ASR candidates): %d ===" % len(empties))
for e in empties:
    print("  %s-%s %s (%.1fs)" % (fmt(e["abs_start"]), fmt(e["abs_end"]), e["spk"],
                                  e["abs_end"] - e["abs_start"]))
json.dump({"lines": lines, "empty_turns": empties},
          open(INV + "/wordlines_a1.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("A1_DONE")
