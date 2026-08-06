# -*- coding: utf-8 -*-
"""Stage 6: TRANSLATION GATE.
If workdir/translations.json missing -> write translation_todo.json and exit(3)
(orchestrator pauses; Claude/user fills translations). If present -> merge into
lines_final.json.

translations.json format: {"<vid>": {"tiers": ["normal text", "short", "shorter"]}}
Rules for the translator: Urdu+English-in-Devanagari flavor; ~2.6 words/sec of slot;
non-lexical interjections (<0.9s scoffs/calls) -> {"original": true} to keep actor audio.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CFG, wpath

D = json.load(open(wpath("actors.json"), encoding="utf-8"))
lines = sorted(D["lines"], key=lambda L: L["abs_start"])
tp = wpath("translations.json")
if not os.path.exists(tp):
    todo = []
    for i, L in enumerate(lines):
        nxt = lines[i + 1]["abs_start"] if i + 1 < len(lines) else CFG["t1"]
        avail = round(min(nxt, CFG["t1"]) - L["abs_start"] - 0.15, 2)
        todo.append({"vid": L["vid"], "zh": L["zh"], "actor": L["actor"],
                     "gender": L["gender"], "slot": L["dur"], "avail": avail,
                     "word_budget": max(2, int(L["dur"] * 2.6)),
                     "suggest_original": bool(L["dur"] < 0.9 and len(L["zh"]) <= 3)})
    json.dump(todo, open(wpath("translation_todo.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    print("TRANSLATION GATE: fill %s using translation_todo.json (%d lines)" % (tp, len(todo)))
    sys.exit(3)

TR = json.load(open(tp, encoding="utf-8"))
final = []
for L in lines:
    t = TR.get(str(L["vid"]))
    if t is None:
        sys.exit("translations.json missing vid %s" % L["vid"])
    L2 = dict(L)
    L2["original_audio"] = bool(t.get("original"))
    L2["tiers"] = t.get("tiers", [])
    if not L2["original_audio"] and not L2["tiers"]:
        sys.exit("vid %s: need tiers or original:true" % L["vid"])
    final.append(L2)
json.dump({"t0": CFG["t0"], "t1": CFG["t1"], "lines": final},
          open(wpath("lines_final.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("lines_final: %d (%d original-audio)" % (len(final), sum(1 for L in final if L["original_audio"])))
