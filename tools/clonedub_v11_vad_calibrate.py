#!/usr/bin/env python3
"""CloneDub V11 Phase 4c: evaluator VAD calibration diagnostic.

Tests whether the Phase 1 evaluator's energy VAD inflates original/
reference "active speech" by counting music/SFX energy. Runs several
no-cost VAD variants over the same five tracks and reports how the
speech-coverage gates would judge each candidate under each variant.

Diagnostic only: does NOT change the official evaluator and does not
overwrite any existing eval output. No TTS, no APIs.

Variants:
    baseline         current evaluator parameters (0.42xRMS, merge 0.15s, min 0.10s)
    bandpass         speech band 300-3400 Hz (FFT brick-wall) before the envelope
    strict           merge-gap 0.05s + min-window 0.25s + threshold 0.50xRMS
    bandpass_strict  bandpass + strict combined

Reference-aware sanity per variant: how well original-active aligns
with Rask-reference-active (IoU and orig-active-but-ref-silent seconds).
Original and a professional dub should have similar speech envelopes,
so poor alignment flags music-bridged false activity.

See CLONEDUB_V11_PRO_DUB_MASTER_PLAN.md, Phases 1/4.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

TOOL_VERSION = "1.0.0"

SR = 16000
FRAME_S = 0.025
HOP_S = 0.010
VAD_ABS_FLOOR = 10 ** (-55.0 / 20.0)

# evaluator speech gates (mix/RMS gates unchanged by VAD, not re-tested here)
MIN_COVERAGE = 0.85
MAX_MISSING_SPEECH_S = 5.0

VARIANTS = {
    "baseline":        {"band": None,        "ratio": 0.42, "merge": 0.15, "minwin": 0.10},
    "bandpass":        {"band": (300, 3400), "ratio": 0.42, "merge": 0.15, "minwin": 0.10},
    "strict":          {"band": None,        "ratio": 0.50, "merge": 0.05, "minwin": 0.25},
    "bandpass_strict": {"band": (300, 3400), "ratio": 0.50, "merge": 0.05, "minwin": 0.25},
}


def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("command failed (%d): %s\n%s"
                           % (proc.returncode, " ".join(map(str, cmd)), proc.stderr[-1200:]))


def extract_wav(src, dst, start, duration):
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start > 0:
        cmd += ["-ss", "%.3f" % start]
    cmd += ["-i", str(src), "-t", "%.3f" % duration,
            "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)]
    run(cmd)


def bandpass_fft(np, x, lo, hi, sr):
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    spec[(freqs < lo) | (freqs > hi)] = 0.0
    return np.fft.irfft(spec, n=len(x))


def envelope(np, x):
    frame = int(round(FRAME_S * SR))
    hop = int(round(HOP_S * SR))
    n = 1 + (len(x) - frame) // hop
    csum = np.concatenate(([0.0], np.cumsum(x.astype(np.float64) ** 2)))
    starts = np.arange(n) * hop
    return np.sqrt((csum[starts + frame] - csum[starts]) / frame)


def activity(np, x, spec):
    """Boolean per-hop activity grid + merged windows for one variant."""
    sig = bandpass_fft(np, x, *spec["band"], SR) if spec["band"] else x
    env = envelope(np, sig)
    rms = float(np.sqrt(np.mean(sig ** 2)))
    thr = max(VAD_ABS_FLOOR, spec["ratio"] * rms)
    active = env >= thr
    # frames -> windows with merge/minwin
    wins, start = [], None
    for i, a in enumerate(active):
        if a and start is None:
            start = i
        elif not a and start is not None:
            wins.append([start * HOP_S, i * HOP_S])
            start = None
    if start is not None:
        wins.append([start * HOP_S, len(active) * HOP_S])
    merged = []
    for w in wins:
        if merged and w[0] - merged[-1][1] < spec["merge"]:
            merged[-1][1] = w[1]
        else:
            merged.append(list(w))
    merged = [w for w in merged if w[1] - w[0] >= spec["minwin"]]
    grid = np.zeros(len(active), dtype=bool)
    for s, e in merged:
        grid[int(s / HOP_S):int(e / HOP_S)] = True
    return grid, merged


def seconds(np, grid):
    return float(np.sum(grid)) * HOP_S


def main():
    p = argparse.ArgumentParser(description="CloneDub V11 Phase 4c VAD calibration "
                                            "diagnostic (no TTS, no APIs).")
    p.add_argument("--original", required=True)
    p.add_argument("--reference", required=True)
    p.add_argument("--oldv1", required=True)
    p.add_argument("--oldv1-start", type=float, default=900.0)
    p.add_argument("--eleven", required=True)
    p.add_argument("--fish", required=True)
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--outdir", required=True)
    p.add_argument("--no-plot", action="store_true")
    args = p.parse_args()

    import numpy as np
    import soundfile as sf

    outdir = Path(args.outdir)
    extracts = outdir / "audio_extracts"
    extracts.mkdir(parents=True, exist_ok=True)

    tracks = {}
    for name, src, start in [("original", args.original, 0.0),
                             ("reference", args.reference, 0.0),
                             ("oldv1", args.oldv1, args.oldv1_start),
                             ("eleven", args.eleven, 0.0),
                             ("fish", args.fish, 0.0)]:
        wav = extracts / ("%s.wav" % name)
        extract_wav(src, wav, start, args.duration)
        x, _ = sf.read(str(wav), dtype="float64")
        tracks[name] = x.mean(axis=1) if x.ndim > 1 else x
        print("[extract] %s" % name)

    results = {}
    for vname, spec in VARIANTS.items():
        grids, windows = {}, {}
        for tname, x in tracks.items():
            grids[tname], windows[tname] = activity(np, x, spec)
        n = min(len(g) for g in grids.values())
        orig, ref = grids["original"][:n], grids["reference"][:n]
        inter = float(np.sum(orig & ref)) * HOP_S
        union = float(np.sum(orig | ref)) * HOP_S
        sanity = {"orig_ref_iou": round(inter / union, 3) if union else 0.0,
                  "orig_active_ref_silent_s": round(float(np.sum(orig & ~ref)) * HOP_S, 2),
                  "ref_active_orig_silent_s": round(float(np.sum(ref & ~orig)) * HOP_S, 2)}
        cands = {}
        for cname in ("oldv1", "eleven", "fish"):
            g = grids[cname][:n]
            act = seconds(np, g)
            cov_o = act / seconds(np, orig) if seconds(np, orig) else 0.0
            cov_r = act / seconds(np, ref) if seconds(np, ref) else 0.0
            missing = float(np.sum(orig & ~g)) * HOP_S
            checks = {"coverage_vs_original": cov_o >= MIN_COVERAGE,
                      "coverage_vs_reference": cov_r >= MIN_COVERAGE,
                      "silence_while_original_speaking": missing <= MAX_MISSING_SPEECH_S}
            cands[cname] = {"active_s": round(act, 2), "coverage_vs_original": round(cov_o, 3),
                            "coverage_vs_reference": round(cov_r, 3),
                            "silent_while_original_speaks_s": round(missing, 2),
                            "speech_gates_pass": all(checks.values()),
                            "failed_gates": [k for k, v in checks.items() if not v]}
        results[vname] = {"params": {k: v for k, v in spec.items()},
                          "original_active_s": round(seconds(np, orig), 2),
                          "reference_active_s": round(seconds(np, ref), 2),
                          "reference_sanity": sanity, "candidates": cands}
        print("[variant] %-16s orig=%.2fs ref=%.2fs IoU=%.2f"
              % (vname, results[vname]["original_active_s"],
                 results[vname]["reference_active_s"], sanity["orig_ref_iou"]))

    (outdir / "vad_calibration.json").write_text(json.dumps(
        {"tool": "clonedub_v11_vad_calibrate", "version": TOOL_VERSION,
         "gates": {"min_coverage": MIN_COVERAGE, "max_missing_speech_s": MAX_MISSING_SPEECH_S},
         "variants": results}, indent=2), encoding="utf-8")

    lines = ["# CloneDub V11 VAD calibration (900-960s)", "",
             "Diagnostic only — official evaluator unchanged. No TTS, no APIs.", "",
             "| variant | orig active (s) | ref active (s) | orig/ref IoU | orig-act ref-silent (s) |",
             "|---|---|---|---|---|"]
    for vname, r in results.items():
        s = r["reference_sanity"]
        lines.append("| %s | %.2f | %.2f | %.2f | %.2f |" % (
            vname, r["original_active_s"], r["reference_active_s"],
            s["orig_ref_iou"], s["orig_active_ref_silent_s"]))
    lines += ["", "## Candidates under each variant (speech gates only: coverage >= %.2f, "
              "missing <= %.1fs)" % (MIN_COVERAGE, MAX_MISSING_SPEECH_S), ""]
    for vname, r in results.items():
        lines += ["### %s" % vname, "",
                  "| candidate | active (s) | cov orig | cov ref | silent-while-orig (s) | speech gates |",
                  "|---|---|---|---|---|---|"]
        for cname, c in r["candidates"].items():
            lines.append("| %s | %.2f | %.2f | %.2f | %.2f | %s |" % (
                cname, c["active_s"], c["coverage_vs_original"], c["coverage_vs_reference"],
                c["silent_while_original_speaks_s"],
                "PASS" if c["speech_gates_pass"] else "FAIL: " + ", ".join(c["failed_gates"])))
        lines.append("")
    (outdir / "vad_calibration_report.md").write_text("\n".join(lines), encoding="utf-8")

    if not args.no_plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, axes = plt.subplots(len(VARIANTS), 1, figsize=(14, 2.6 * len(VARIANTS)), sharex=True)
            x = tracks["original"]
            for ax, (vname, spec) in zip(axes, VARIANTS.items()):
                sig = bandpass_fft(np, x, *spec["band"], SR) if spec["band"] else x
                env = envelope(np, sig)
                ts = np.arange(len(env)) * HOP_S
                ax.plot(ts, env, linewidth=0.5)
                _, wins = activity(np, x, spec)
                for s, e in wins:
                    ax.axvspan(s, e, color="green", alpha=0.18)
                ax.set_title("original | %s | active %.2fs" % (vname, results[vname]["original_active_s"]))
            axes[-1].set_xlabel("seconds")
            fig.tight_layout()
            fig.savefig(str(outdir / "envelope_variants.png"), dpi=110)
        except ImportError:
            print("[warn] matplotlib unavailable, plot skipped")

    print("report: %s" % (outdir / "vad_calibration_report.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
