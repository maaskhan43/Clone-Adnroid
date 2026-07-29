#!/usr/bin/env python3
"""CloneDub V11 Phase 4 preparation: timing/regeneration planner.

Reads the Phase 3 bake-off report (per-block spoken-vs-target timing per
candidate) plus the Phase 2 script blocks, and produces a rewrite
adjustment plan: which blocks end too early and need fuller text, which
overrun their window and need shorter text, which must not be stretched
further, and which candidate(s) are worth the next (paid) regeneration.

Analysis only: no TTS, no APIs, no audio processing. Does not modify
Phase 3 outputs.

See CLONEDUB_V11_PRO_DUB_MASTER_PLAN.md, Phase 4.
"""

import argparse
import json
import re
import sys
from pathlib import Path

TOOL_VERSION = "1.0.0"

UNDERFILL_RATIO = 0.85    # spoken below this fraction of window -> ends too early
OVERRUN_RATIO = 1.10      # spoken beyond this fraction of window -> too long
TEMPO_CEILING = 1.075     # tempo at/above this means the 1.08x limit was hit
OVERRUN_PENALTY_S = 2.0   # ranking penalty per overrun block
CEILING_PENALTY_S = 1.0   # ranking penalty per tempo-ceiling block
WPS_FALLBACK = 2.9        # words/second if a block has no measurable rate

BLOCK_RE = re.compile(r"^\s*- (b\d+): ([\d.]+)s into ([\d.]+)s window(?:\s+\[(.*)\])?\s*$")
TABLE_RE = re.compile(r"^\| (\w+) \| (PASS|FAIL) \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \| ([+-]?[\d.]+) \|")


def count_words(text):
    return len([t for t in text.split() if any(c.isalnum() for c in t)])


def parse_report(path):
    candidates, current = {}, None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = TABLE_RE.match(line)
        if m:
            candidates.setdefault(m.group(1), {"blocks": {}}).update({
                "verdict": m.group(2), "active_speech_s": float(m.group(3)),
                "coverage_vs_original": float(m.group(4)),
                "coverage_vs_reference": float(m.group(5)),
                "silent_while_original_speaks_s": float(m.group(6)),
                "rms_delta_db": float(m.group(7))})
            continue
        if line.startswith("## "):
            name = line[3:].strip()
            current = name if name in candidates else None
            continue
        m = BLOCK_RE.match(line)
        if m and current:
            flags = m.group(4) or ""
            tempos = [float(t) for t in re.findall(r"tempo=([\d.]+)", flags)]
            candidates[current]["blocks"][m.group(1)] = {
                "spoken_s": float(m.group(2)), "target_s": float(m.group(3)),
                "tempo": max(tempos) if tempos else 1.0,
                "overrun_flag": "OVERRUN" in flags}
    return {n: c for n, c in candidates.items() if c.get("blocks")}


def classify(entry):
    ratio = entry["spoken_s"] / entry["target_s"] if entry["target_s"] else 1.0
    if entry["overrun_flag"] or ratio > OVERRUN_RATIO:
        return "OVERRUN"
    if ratio < UNDERFILL_RATIO:
        return "UNDERFILLED"
    return "OK"


def word_delta(entry, current_words):
    """Words to add (+) or cut (-) so natural delivery fills the window."""
    spoken = entry["spoken_s"]
    natural = spoken * entry["tempo"]  # undo tempo fitting -> natural duration
    wps = current_words / natural if natural > 0 else WPS_FALLBACK
    return int(round(wps * entry["target_s"])) - current_words


def analyze(candidates, blocks_by_id):
    per_candidate = {}
    for name, cand in candidates.items():
        rows, dev, overruns, ceilings = [], 0.0, 0, 0
        for bid, entry in sorted(cand["blocks"].items()):
            status = classify(entry)
            words = count_words(blocks_by_id[bid]["target_text_hi"]) if bid in blocks_by_id else 0
            at_ceiling = entry["tempo"] >= TEMPO_CEILING
            dev += abs(entry["spoken_s"] - entry["target_s"])
            overruns += status == "OVERRUN"
            ceilings += at_ceiling
            rows.append({"id": bid, "status": status, "spoken_s": entry["spoken_s"],
                         "target_s": entry["target_s"], "tempo": entry["tempo"],
                         "at_tempo_ceiling": at_ceiling, "current_words": words,
                         "word_delta": word_delta(entry, words) if status != "OK" else 0})
        per_candidate[name] = {
            "metrics": {k: v for k, v in cand.items() if k != "blocks"},
            "blocks": rows,
            "timing_fitness_score_s": round(
                dev + OVERRUN_PENALTY_S * overruns + CEILING_PENALTY_S * ceilings, 2),
            "overrun_blocks": overruns, "tempo_ceiling_blocks": ceilings}
    return per_candidate


def consensus(per_candidate, blocks_by_id):
    names = list(per_candidate)
    out = []
    for bid in sorted(blocks_by_id):
        statuses = {n: next((r["status"] for r in per_candidate[n]["blocks"] if r["id"] == bid), "?")
                    for n in names}
        ceilings = [n for n in names
                    if next((r["at_tempo_ceiling"] for r in per_candidate[n]["blocks"]
                             if r["id"] == bid), False)]
        under = [n for n, s in statuses.items() if s == "UNDERFILLED"]
        over = [n for n, s in statuses.items() if s == "OVERRUN"]
        if len(over) >= 2:
            action = "SHORTEN_TEXT"
        elif len(under) > len(names) / 2:
            action = "FULLER_TEXT"
        elif over or under:
            action = "PER_CANDIDATE"
        else:
            action = "KEEP"
        out.append({"id": bid, "action": action, "underfilled_on": under,
                    "overrun_on": over, "no_stretch": bool(ceilings),
                    "tempo_ceiling_on": ceilings,
                    "current_words": count_words(blocks_by_id[bid]["target_text_hi"]),
                    "target_s": blocks_by_id[bid]["target_seconds"],
                    "current_text": blocks_by_id[bid]["target_text_hi"]})
    return out


def recommend(per_candidate, preferred):
    ranking = sorted(per_candidate,
                     key=lambda n: per_candidate[n]["timing_fitness_score_s"])
    recommended = [n for n in ranking if n in preferred][:2] or ranking[:2]
    return ranking, recommended


def write_md(path, args, per_candidate, block_plan, ranking, recommended):
    lines = ["# CloneDub V11 Phase 4 plan (timing/regeneration)", "",
             "Inputs: `%s`, `%s`" % (args.report, args.script), "",
             "## Provider ranking by timing fitness (lower score = better fit)", "",
             "| rank | candidate | score (s) | overruns | tempo-ceiling blocks | "
             "coverage vs orig | silent while orig speaks (s) |", "|---|---|---|---|---|---|---|"]
    for i, n in enumerate(ranking, 1):
        c = per_candidate[n]
        lines.append("| %d | %s | %.2f | %d | %d | %.2f | %.2f |" % (
            i, n, c["timing_fitness_score_s"], c["overrun_blocks"],
            c["tempo_ceiling_blocks"], c["metrics"]["coverage_vs_original"],
            c["metrics"]["silent_while_original_speaks_s"]))
    lines += ["", "**Recommended for next (paid) regeneration: %s**" % ", ".join(recommended),
              "", "## Block actions (consensus across candidates)", "",
              "| block | action | window (s) | words now | underfilled on | overrun on | stretch allowed? |",
              "|---|---|---|---|---|---|---|"]
    for b in block_plan:
        lines.append("| %s | %s | %.2f | %d | %s | %s | %s |" % (
            b["id"], b["action"], b["target_s"], b["current_words"],
            ", ".join(b["underfilled_on"]) or "-", ", ".join(b["overrun_on"]) or "-",
            "NO (at 1.08x ceiling on %s)" % ", ".join(b["tempo_ceiling_on"])
            if b["no_stretch"] else "mild only"))
    lines += ["", "## Per-candidate block adjustments", ""]
    for n in recommended:
        lines += ["### %s" % n, ""]
        for r in per_candidate[n]["blocks"]:
            if r["status"] == "OK":
                continue
            direction = "add ~%d words (fuller, acted)" % r["word_delta"] if r["word_delta"] > 0 \
                else "cut ~%d words (tighter)" % -r["word_delta"]
            lines.append("- %s %s: %.2fs into %.2fs window -> %s%s" % (
                r["id"], r["status"], r["spoken_s"], r["target_s"], direction,
                "; do NOT stretch further" if r["at_tempo_ceiling"] else ""))
        lines.append("")
    lines += ["## Rules carried into Phase 4", "",
              "- Time-stretch preferred range 0.92x-1.08x; emergency 0.88x-1.12x; never fake filler.",
              "- Regenerate text first, stretch last.",
              "- Blocks marked KEEP are not regenerated (no wasted paid calls).",
              "- Re-run the Phase 1 evaluator after each regeneration round.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description="CloneDub V11 Phase 4 planner: turn Phase 3 "
                                            "timing data into a rewrite/regeneration plan.")
    p.add_argument("--report", required=True, help="Phase 3 phase3_report.md")
    p.add_argument("--script", required=True, help="Phase 2 script_blocks.json")
    p.add_argument("--prefer", default="eleven_v2,fish_girl",
                   help="candidates preferred for regeneration (comma-separated)")
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    candidates = parse_report(args.report)
    if not candidates:
        sys.exit("error: no per-block candidate data parsed from %s" % args.report)
    doc = json.loads(Path(args.script).read_text(encoding="utf-8"))
    blocks_by_id = {b["id"]: b for b in doc["blocks"]}

    per_candidate = analyze(candidates, blocks_by_id)
    block_plan = consensus(per_candidate, blocks_by_id)
    preferred = [n.strip() for n in args.prefer.split(",") if n.strip()]
    ranking, recommended = recommend(per_candidate, preferred)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "phase4_plan.json").write_text(json.dumps({
        "tool": "clonedub_v11_phase4_plan", "version": TOOL_VERSION,
        "thresholds": {"underfill_ratio": UNDERFILL_RATIO, "overrun_ratio": OVERRUN_RATIO,
                       "tempo_ceiling": TEMPO_CEILING},
        "ranking": ranking, "recommended": recommended,
        "candidates": per_candidate, "block_plan": block_plan,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    write_md(outdir / "phase4_plan.md", args, per_candidate, block_plan, ranking, recommended)

    print("candidates: %s" % ", ".join(ranking))
    print("recommended: %s" % ", ".join(recommended))
    for b in block_plan:
        if b["action"] != "KEEP":
            print("  %s -> %s%s" % (b["id"], b["action"],
                                    " (no stretch)" if b["no_stretch"] else ""))
    print("plan: %s" % (outdir / "phase4_plan.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
