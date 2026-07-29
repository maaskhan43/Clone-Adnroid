#!/usr/bin/env python3
"""CloneDub V11 Phase 2: dialogue rewrite engine (block builder + validator).

Turns the old pipeline's long literal narration segments into short,
timed script blocks aligned to the ORIGINAL speech windows measured by
the Phase 1 evaluator, then attaches acted Hindi/Hinglish lines from a
reviewable lines file and validates them against each block's time
budget.

See CLONEDUB_V11_PRO_DUB_MASTER_PLAN.md, Phase 2.

Inputs:
    --segments   old pipeline segments.json (source text + word timings + speakers)
    --gender     old pipeline gender.json (speaker -> gender)
    --activity   Phase 1 activity_windows.json (speech windows, window-relative)
    --lines      optional JSON {block_id: "hindi/hinglish line"} with the rewrite
    --benchmark-asr  optional Rask ASR json for per-block style comparison

Outputs (under --outdir):
    script_blocks.json   plan-schema blocks (empty target_text_hi until --lines given)
    script_blocks.srt    subtitle preview of the rewrite
    rewrite_report.md    per-block review table + validation flags

This tool is deterministic, offline, stdlib-only. It does not generate
TTS and does not modify any input.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

TOOL_VERSION = "1.0.0"

MERGE_GAP_S = 0.5      # activity windows closer than this become one block
MIN_BLOCK_S = 0.8      # smaller blocks are merged into the previous/next block
MAX_BLOCK_S = 8.0      # longer runs are split at the most suitable internal pause
SPLIT_GAP_WEIGHT = 2.0  # how strongly splitting prefers wider pauses over centered ones
WORDS_PER_SECOND = 2.9  # conversational Hindi/Hinglish narration rate estimate
MAX_FIT_RATIO = 1.08   # est. speech may exceed block length by at most this
MIN_FILL_RATIO = 0.60  # est. speech under this fraction of block length is too thin
MUST_NOT = ["literal textbook explanation", "fake filler", "word stretching"]
DEFAULT_STYLE = "energetic recap narration, conversational Hinglish"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def collect_words(segments_doc, t0, t1):
    words = []
    for seg in segments_doc["segments"]:
        if float(seg["end"]) <= t0 or float(seg["start"]) >= t1:
            continue
        for w in seg.get("words", []):
            if "start" not in w or "end" not in w:
                continue
            if w["end"] > t0 and w["start"] < t1:
                words.append(w)
    return sorted(words, key=lambda w: w["start"])


def split_long(group):
    """Split a group of sub-windows at internal pauses until <= MAX_BLOCK_S."""
    dur = group[-1][1] - group[0][0]
    if dur <= MAX_BLOCK_S or len(group) < 2:
        return [group]
    mid = group[0][0] + dur / 2.0
    def score(i):
        gap = group[i][0] - group[i - 1][1]
        center = (group[i - 1][1] + group[i][0]) / 2.0
        return abs(center - mid) - SPLIT_GAP_WEIGHT * gap
    best = min(range(1, len(group)), key=score)
    return split_long(group[:best]) + split_long(group[best:])


def merge_windows(rel_windows, t0):
    """Window-relative [start, end, dur] -> merged absolute [start, end] blocks."""
    spans = [[t0 + w[0], t0 + w[1]] for w in sorted(rel_windows)]
    groups = []
    for s, e in spans:
        if groups and s - groups[-1][-1][1] < MERGE_GAP_S:
            groups[-1].append([s, e])
        else:
            groups.append([[s, e]])
    # fold too-short groups into the previous group (first folds forward)
    folded = []
    for g in groups:
        if folded and g[-1][1] - g[0][0] < MIN_BLOCK_S:
            folded[-1].extend(g)
        else:
            folded.append(g)
    if len(folded) > 1 and folded[0][-1][1] - folded[0][0][0] < MIN_BLOCK_S:
        folded[1][0:0] = folded[0]
        folded.pop(0)
    out = []
    for g in folded:
        out.extend(split_long(g))
    return [[g[0][0], g[-1][1]] for g in out]


def split_by_word_gaps(span, words, min_gap=0.3):
    """Fallback for blocks with no activity pause: split at ASR word gaps.

    Music/SFX can bridge the VAD window across a real speech pause, so a
    single continuous activity window may still contain sentence breaks
    visible in the word timings.
    """
    s, e = span
    if e - s <= MAX_BLOCK_S:
        return [span]
    inner = [w for w in words if w["start"] >= s and w["end"] <= e]
    mid = s + (e - s) / 2.0
    candidates = []
    for a, b in zip(inner, inner[1:]):
        gap = b["start"] - a["end"]
        if gap >= min_gap:
            center = (a["end"] + b["start"]) / 2.0
            candidates.append((abs(center - mid) - SPLIT_GAP_WEIGHT * gap, center))
    if not candidates:
        return [span]
    cut = min(candidates)[1]
    return split_by_word_gaps([s, cut], words) + split_by_word_gaps([cut, e], words)


def majority_speaker(words):
    weight = defaultdict(float)
    for w in words:
        if w.get("speaker"):
            weight[w["speaker"]] += float(w["end"]) - float(w["start"])
    return max(weight, key=weight.get) if weight else "UNKNOWN"


def overlapping_text(entries, s, e, t0, key="text"):
    """Entries with window-relative start/end -> joined text overlapping [s, e]."""
    hits = [x for x in entries
            if t0 + float(x["end"]) > s and t0 + float(x["start"]) < e]
    return " ".join(x[key].strip() for x in hits)


def srt_time(t):
    ms = int(round(t * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def build_blocks(args, segments_doc, gender_map, rel_windows, lines):
    t0, t1 = args.window_start, args.window_start + args.duration
    all_words = collect_words(segments_doc, t0, t1)
    spans = []
    for span in merge_windows(rel_windows, t0):
        spans.extend(split_by_word_gaps(span, all_words))
    blocks = []
    for i, (s, e) in enumerate(spans):
        # assign each word to exactly one block, by its midpoint
        words = [w for w in all_words if s <= (w["start"] + w["end"]) / 2.0 < e]
        speaker = majority_speaker(words)
        target_seconds = round(e - s, 2)
        bid = "b%03d" % i
        text = lines.get(bid, "")
        blocks.append({
            "id": bid,
            "start": round(s, 2),
            "end": round(e, 2),
            "speaker": speaker,
            "gender": gender_map.get(speaker, "unknown"),
            "source_text": "".join(w["word"] for w in words),
            "target_text_hi": text,
            "style": args.style,
            "target_seconds": target_seconds,
            "max_words": max(3, int(round(target_seconds * WORDS_PER_SECOND))),
            "must_not": MUST_NOT,
        })
    return blocks


def count_words(text):
    # punctuation-only tokens (em-dashes etc.) are not spoken words
    return len([t for t in text.split() if any(c.isalnum() for c in t)])


def validate_block(b):
    flags = []
    if not b["target_text_hi"]:
        flags.append("NO_LINE: target_text_hi not authored yet")
        return flags, 0.0
    n_words = count_words(b["target_text_hi"])
    est = n_words / WORDS_PER_SECOND
    if n_words > b["max_words"]:
        flags.append("TOO_MANY_WORDS: %d > max %d" % (n_words, b["max_words"]))
    if est > b["target_seconds"] * MAX_FIT_RATIO:
        flags.append("EST_TOO_LONG: ~%.1fs vs window %.1fs" % (est, b["target_seconds"]))
    if est < b["target_seconds"] * MIN_FILL_RATIO:
        flags.append("EST_TOO_THIN: ~%.1fs vs window %.1fs" % (est, b["target_seconds"]))
    return flags, est


def write_outputs(args, blocks, old_segments, bench_asr, outdir):
    t0 = args.window_start
    (outdir / "script_blocks.json").write_text(
        json.dumps({"tool": "clonedub_v11_rewrite", "version": TOOL_VERSION,
                    "window": [t0, t0 + args.duration], "blocks": blocks},
                   indent=2, ensure_ascii=False), encoding="utf-8")

    srt = []
    for i, b in enumerate(blocks, 1):
        srt += [str(i), "%s --> %s" % (srt_time(b["start"] - t0), srt_time(b["end"] - t0)),
                b["target_text_hi"] or "[NOT AUTHORED]", ""]
    (outdir / "script_blocks.srt").write_text("\n".join(srt), encoding="utf-8")

    total_target = sum(b["target_seconds"] for b in blocks)
    total_est = 0.0
    lines = ["# CloneDub V11 rewrite report (%.0f-%.0fs)" % (t0, t0 + args.duration), "",
             "Style: %s" % args.style, "",
             "blocks: %d | speech budget: %.2fs of %.0fs window" % (len(blocks), total_target, args.duration), ""]
    all_flags = []
    for b in blocks:
        flags, est = validate_block(b)
        total_est += est
        all_flags += ["%s: %s" % (b["id"], f) for f in flags]
        old_hi = overlapping_text(
            [{"start": s["start"] - t0, "end": s["end"] - t0, "text": s.get("text_hi", "")}
             for s in old_segments], b["start"], b["end"], t0)
        lines += [
            "## %s  |  %.2f - %.2f  (%.2fs)  |  %s (%s)" % (
                b["id"], b["start"], b["end"], b["target_seconds"], b["speaker"], b["gender"]),
            "",
            "- source (zh): %s" % (b["source_text"] or "(no ASR words in window)"),
            "- old V1 line: %s" % ((old_hi[:220] + "...") if len(old_hi) > 220 else (old_hi or "(none)")),
        ]
        if bench_asr:
            bench = overlapping_text(bench_asr, b["start"], b["end"], t0)
            lines.append("- benchmark (Rask ASR): %s" % (bench or "(none)"))
        lines += [
            "- NEW line: **%s**" % (b["target_text_hi"] or "[NOT AUTHORED]"),
            "- budget: %d/%d words, est ~%.1fs for %.2fs window%s" % (
                count_words(b["target_text_hi"]), b["max_words"], est, b["target_seconds"],
                "  FLAGS: " + "; ".join(flags) if flags else "  OK"),
            "",
        ]
    lines += ["## Summary", "",
              "- estimated spoken time: %.1fs vs window speech budget %.2fs" % (total_est, total_target),
              "- flags: %d" % len(all_flags)]
    lines += ["  - %s" % f for f in all_flags]
    lines.append("")
    (outdir / "rewrite_report.md").write_text("\n".join(lines), encoding="utf-8")
    return all_flags


def main():
    p = argparse.ArgumentParser(
        description="CloneDub V11 Phase 2: build timed script blocks from original "
                    "speech windows and validate acted Hindi/Hinglish rewrite lines.")
    p.add_argument("--segments", required=True, help="old pipeline segments.json")
    p.add_argument("--gender", required=True, help="old pipeline gender.json")
    p.add_argument("--activity", required=True, help="Phase 1 activity_windows.json")
    p.add_argument("--activity-track", default="original", help="which track's windows to use")
    p.add_argument("--window-start", type=float, required=True, help="absolute start seconds (e.g. 900)")
    p.add_argument("--duration", type=float, required=True, help="window length in seconds")
    p.add_argument("--lines", help="JSON {block_id: line} with the authored rewrite")
    p.add_argument("--benchmark-asr", help="optional benchmark ASR json (window-relative)")
    p.add_argument("--style", default=DEFAULT_STYLE)
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    segments_doc = load_json(args.segments)
    gender_map = load_json(args.gender).get("gender", {})
    activity = load_json(args.activity)
    if args.activity_track not in activity:
        sys.exit("error: track %r not in %s" % (args.activity_track, args.activity))
    lines = load_json(args.lines) if args.lines else {}
    bench_asr = load_json(args.benchmark_asr) if args.benchmark_asr else None

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    t0 = args.window_start
    old_segments = [s for s in segments_doc["segments"]
                    if s["start"] < t0 + args.duration and s["end"] > t0]
    blocks = build_blocks(args, segments_doc, gender_map, activity[args.activity_track], lines)
    flags = write_outputs(args, blocks, old_segments, bench_asr, outdir)

    unknown = set(lines) - {b["id"] for b in blocks}
    if unknown:
        print("[warn] lines file has ids not matching any block: %s" % sorted(unknown))
    print("blocks: %d | authored: %d | flags: %d | outdir: %s"
          % (len(blocks), sum(1 for b in blocks if b["target_text_hi"]), len(flags), outdir))
    for f in flags:
        print("  - %s" % f)
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
