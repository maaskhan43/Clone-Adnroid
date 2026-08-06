#!/usr/bin/env python3
"""CloneDub V11 Phase 4b: round review / listening pack builder.

Builds a no-cost diagnostic pack for one regeneration round: audio
extracts for A/B listening, an objective comparison table read from
EXISTING evaluator outputs (no re-evaluation, no TTS, no APIs), and a
list of diagnostic windows where the original/reference is marked
active but every reviewed candidate is silent — annotated with the
source ASR words overlapping each window so a human can judge whether
the gap is real missed speech or a music-bridged VAD false positive.

See CLONEDUB_V11_PRO_DUB_MASTER_PLAN.md, Phase 4.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

TOOL_VERSION = "1.0.0"

GRID_S = 0.01          # activity resample grid
MIN_GAP_WINDOW_S = 0.3  # ignore shorter both-silent slivers
ASR_REAL_SPEECH_CHARS = 2  # >= this many source chars overlapping -> likely real speech


def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("command failed (%d): %s\n%s"
                           % (proc.returncode, " ".join(map(str, cmd)), proc.stderr[-1200:]))


def extract_wav(src, dst, start, duration, sr=16000):
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start > 0:
        cmd += ["-ss", "%.3f" % start]
    cmd += ["-i", str(src), "-t", "%.3f" % duration,
            "-vn", "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(dst)]
    run(cmd)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def windows_to_grid(windows, duration):
    n = int(round(duration / GRID_S))
    grid = [False] * n
    for w in windows:
        a, b = max(0, int(w[0] / GRID_S)), min(n, int(w[1] / GRID_S))
        for i in range(a, b):
            grid[i] = True
    return grid


def grid_to_intervals(grid):
    out, start = [], None
    for i, v in enumerate(grid):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start * GRID_S, i * GRID_S))
            start = None
    if start is not None:
        out.append((start * GRID_S, len(grid) * GRID_S))
    return [(s, e) for s, e in out if e - s >= MIN_GAP_WINDOW_S]


def overlapping_words(words, abs_start, abs_end):
    hit = [w for w in words
           if abs_start <= (w["start"] + w["end"]) / 2.0 < abs_end]
    return "".join(w["word"] for w in hit)


def eval_row(name, eval_json):
    ev = load_json(eval_json)
    c, comp = ev["tracks"]["candidate"], ev["comparisons"]
    return {"name": name, "verdict": ev["verdict"],
            "active_s": c["active_speech_seconds"],
            "cov_orig": comp["coverage_vs_original"],
            "cov_ref": comp["coverage_vs_reference"],
            "silent_while_orig_s": comp["candidate_silent_while_original_speaking_s"],
            "rms_delta_db": comp["candidate_rms_delta_vs_reference_db"]}


def main():
    p = argparse.ArgumentParser(description="CloneDub V11 Phase 4b review/listening pack "
                                            "(no TTS, no APIs, reads existing evaluator outputs).")
    p.add_argument("--original", required=True)
    p.add_argument("--reference", required=True)
    p.add_argument("--oldv1", required=True)
    p.add_argument("--oldv1-start", type=float, default=900.0)
    p.add_argument("--candidate", action="append", default=[], metavar="NAME=PREVIEW.mp4",
                   help="repeatable: reviewed candidate preview (start assumed 0)")
    p.add_argument("--eval-dir", action="append", default=[], metavar="NAME=EVAL_DIR",
                   help="repeatable: existing evaluator outdir for NAME (has eval.json + "
                        "activity_windows.json); include one for oldv1")
    p.add_argument("--segments", required=True, help="old pipeline segments.json (source words)")
    p.add_argument("--window-start", type=float, default=900.0)
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    cands = dict(kv.split("=", 1) for kv in args.candidate)
    evals = dict(kv.split("=", 1) for kv in args.eval_dir)
    outdir = Path(args.outdir)
    extracts = outdir / "audio_extracts"
    extracts.mkdir(parents=True, exist_ok=True)

    # 1. audio extracts for listening
    plan = [("original", args.original, 0.0), ("reference", args.reference, 0.0),
            ("oldv1", args.oldv1, args.oldv1_start)]
    plan += [(n, path, 0.0) for n, path in cands.items()]
    for name, src, start in plan:
        extract_wav(src, extracts / ("%s.wav" % name), start, args.duration)
        print("[extract] %s.wav" % name)

    # 2. objective table from existing evaluator outputs
    rows = [eval_row(n, Path(d) / "eval.json") for n, d in sorted(evals.items())]

    # 3. diagnostic both-silent windows
    first_eval = Path(next(iter(evals.values())))
    activity = load_json(first_eval / "activity_windows.json")
    orig_grid = windows_to_grid(activity["original"], args.duration)
    ref_grid = windows_to_grid(activity["reference"], args.duration)
    cand_grids = {}
    for n, d in evals.items():
        if n == "oldv1":
            continue
        cand_grids[n] = windows_to_grid(
            load_json(Path(d) / "activity_windows.json")["candidate"], args.duration)
    both_silent = [o and all(not g[i] for g in cand_grids.values())
                   for i, o in enumerate(orig_grid)]
    words = []
    for seg in load_json(args.segments)["segments"]:
        words += [w for w in seg.get("words", []) if "start" in w and "end" in w]
    diags = []
    for s, e in grid_to_intervals(both_silent):
        src_text = overlapping_words(words, args.window_start + s, args.window_start + e)
        diags.append({
            "rel_start": round(s, 2), "rel_end": round(e, 2), "dur_s": round(e - s, 2),
            "abs_start": round(args.window_start + s, 2),
            "reference_also_active": any(
                ref_grid[i] for i in range(int(s / GRID_S), min(len(ref_grid), int(e / GRID_S)))),
            "source_words": src_text,
            "hint": "likely real speech" if len(src_text) >= ASR_REAL_SPEECH_CHARS
                    else "likely music/false-positive"})

    (outdir / "diagnostic_windows.json").write_text(
        json.dumps({"tool": "clonedub_v11_round_review", "version": TOOL_VERSION,
                    "candidates": sorted(cand_grids), "windows": diags},
                   indent=2, ensure_ascii=False), encoding="utf-8")

    # 4. report + listening index
    lines = ["# CloneDub V11 round review pack (%.0f-%.0fs)" % (
                 args.window_start, args.window_start + args.duration), "",
             "No-cost diagnostic pack: no TTS, no APIs. Metrics read from existing evaluator runs.", "",
             "## Objective comparison (existing evaluator metrics)", "",
             "| candidate | verdict | active (s) | cov vs orig | cov vs Rask | "
             "silent while orig speaks (s) | RMS vs Rask (dB) |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %.2f | %.2f | %.2f | %.2f | %+.1f |" % (
            r["name"], r["verdict"], r["active_s"], r["cov_orig"], r["cov_ref"],
            r["silent_while_orig_s"], r["rms_delta_db"]))
    real = [d for d in diags if d["hint"] == "likely real speech"]
    fake = [d for d in diags if d["hint"] != "likely real speech"]
    lines += ["", "## Diagnostic: original active but ALL reviewed candidates silent", "",
              "total %d windows, %.2fs | likely real speech: %d (%.2fs) | "
              "likely music-bridged false positives: %d (%.2fs)" % (
                  len(diags), sum(d["dur_s"] for d in diags),
                  len(real), sum(d["dur_s"] for d in real),
                  len(fake), sum(d["dur_s"] for d in fake)), "",
              "| window (rel s) | dur | ref also active | source words | hint |",
              "|---|---|---|---|---|"]
    for d in diags:
        lines.append("| %.2f - %.2f | %.2f | %s | %s | %s |" % (
            d["rel_start"], d["rel_end"], d["dur_s"],
            "yes" if d["reference_also_active"] else "no",
            d["source_words"] or "(none)", d["hint"]))
    lines += ["", "## Listening index (A/B in this order)", ""]
    order = [("original (source acting)", args.original, "0:00"),
             ("Rask benchmark", args.reference, "0:00"),
             ("old V1 (start 15:00)", args.oldv1, "15:00")]
    order += [("%s round1" % n, path, "0:00") for n, path in sorted(cands.items())]
    for i, (label, path, seek) in enumerate(order, 1):
        lines.append("%d. **%s** — `%s` (seek %s)" % (i, label, path, seek))
    lines += ["", "WAV-only versions for quick scrubbing: `%s`" % extracts,
              "", "Judge: robotic feel, stretched words, early cut-offs, "
              "external-narration feel, and whether the diagnostic windows above "
              "actually contain missed dialogue.", ""]
    (outdir / "review_pack_report.md").write_text("\n".join(lines), encoding="utf-8")

    print("windows: %d both-silent (%d likely real speech, %d likely false-positive)"
          % (len(diags), len(real), len(fake)))
    print("report: %s" % (outdir / "review_pack_report.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
