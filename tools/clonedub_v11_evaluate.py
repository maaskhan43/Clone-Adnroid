#!/usr/bin/env python3
"""CloneDub V11 Phase 1: evaluator-first system.

Compares a candidate dub clip against the original source clip and a
professional benchmark reference clip, and produces an objective
PASS/FAIL scorecard.

See CLONEDUB_V11_PRO_DUB_MASTER_PLAN.md, Phase 1.

Outputs (under --outdir):
    eval.json               full machine-readable report
    scorecard.md            human-readable scorecard
    envelope.png            envelope + speech-activity plot (needs matplotlib)
    activity_windows.json   per-track speech windows
    audio_extracts/original.wav / reference.wav / candidate.wav

This tool only reads the input videos; it never modifies them.
No TTS, no paid APIs, no full-video processing.
"""

import argparse
import json
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

TOOL_VERSION = "1.0.0"

# --- verdict thresholds (all documented in eval.json) ---
DURATION_TOLERANCE_S = 0.75      # extract may differ from requested duration by this much
MIN_COVERAGE_VS_ORIGINAL = 0.85  # candidate active speech / original active speech
MIN_COVERAGE_VS_REFERENCE = 0.85
MAX_MISSING_SPEECH_S = 5.0       # candidate silent while original is speaking
RMS_DELTA_MAX_DB = 3.0           # candidate louder than reference by more -> over-hot
RMS_DELTA_MIN_DB = -6.0          # candidate quieter than reference by more -> too low
MAX_CONTINUOUS_WINDOW_S = 25.0   # single narration block longer than this is a red flag

# --- experimental gate modes (defaults preserve original behavior) ---
SPEECHBAND_HZ = (300.0, 3400.0)  # --vad-mode speechband: filter before activity

# --- VAD parameters (calibrated against D:\CloneDub\work\rask_analysis) ---
DEFAULT_SR = 16000
FRAME_S = 0.025
HOP_S = 0.010
VAD_RMS_RATIO = 0.42             # activity threshold = ratio * global RMS
VAD_ABS_FLOOR = 10 ** (-55.0 / 20.0)
MERGE_GAP_S = 0.15               # merge windows separated by less than this
MIN_WINDOW_S = 0.10              # drop windows shorter than this


def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "command failed (%d): %s\n%s" % (proc.returncode, " ".join(cmd), proc.stderr[-2000:])
        )
    return proc.stdout


def ffprobe_streams(path):
    out = run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
        "-of", "json", str(path),
    ])
    info = json.loads(out)
    streams = info.get("streams", [])
    fmt = info.get("format", {})
    return {
        "path": str(path),
        "container_duration": float(fmt.get("duration", 0.0)),
        "format_name": fmt.get("format_name"),
        "size_bytes": int(fmt.get("size", 0)),
        "video_streams": [s for s in streams if s.get("codec_type") == "video"],
        "audio_streams": [s for s in streams if s.get("codec_type") == "audio"],
    }


def extract_wav(src, dst, start, duration, sr):
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start > 0:
        cmd += ["-ss", "%.3f" % start]
    cmd += ["-i", str(src), "-t", "%.3f" % duration,
            "-vn", "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(dst)]
    run(cmd)


def rms_envelope(x, sr, np):
    frame = int(round(FRAME_S * sr))
    hop = int(round(HOP_S * sr))
    if len(x) < frame:
        return np.zeros(0), hop / sr
    n_frames = 1 + (len(x) - frame) // hop
    csum = np.concatenate(([0.0], np.cumsum(x.astype(np.float64) ** 2)))
    starts = np.arange(n_frames) * hop
    energy = csum[starts + frame] - csum[starts]
    return np.sqrt(energy / frame), hop / sr


def active_frames_to_windows(active, hop_s):
    windows = []
    start = None
    for i, a in enumerate(active):
        if a and start is None:
            start = i
        elif not a and start is not None:
            windows.append([start * hop_s, i * hop_s])
            start = None
    if start is not None:
        windows.append([start * hop_s, len(active) * hop_s])
    merged = []
    for w in windows:
        if merged and w[0] - merged[-1][1] < MERGE_GAP_S:
            merged[-1][1] = w[1]
        else:
            merged.append(w)
    return [[s, e, e - s] for s, e in merged if e - s >= MIN_WINDOW_S]


def bandpass_fft(np, x, lo, hi, sr):
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    spec[(freqs < lo) | (freqs > hi)] = 0.0
    return np.fft.irfft(spec, n=len(x))


def analyze_track(name, wav_path, np, sf, vad_mode="baseline"):
    x, sr = sf.read(str(wav_path), dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    duration = len(x) / sr
    rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    # RMS/peak (mix checks) always measure the unfiltered audio; only the
    # activity measurement switches signal in speechband mode.
    x_vad = bandpass_fft(np, x, *SPEECHBAND_HZ, sr) if vad_mode == "speechband" else x
    vad_rms = float(np.sqrt(np.mean(x_vad ** 2))) if len(x_vad) else 0.0
    env, hop_s = rms_envelope(x_vad, sr, np)
    thr = max(VAD_ABS_FLOOR, VAD_RMS_RATIO * vad_rms)
    active = env >= thr
    windows = active_frames_to_windows(active, hop_s)
    speech_dur = sum(w[2] for w in windows)
    gaps = [windows[i + 1][0] - windows[i][1] for i in range(len(windows) - 1)]
    to_db = lambda v: 20.0 * (np.log10(v) if v > 0 else -6.0)
    return {
        "name": name,
        "duration": duration,
        "sample_rate": sr,
        "rms": rms,
        "rms_dbfs": float(to_db(rms)),
        "peak": peak,
        "peak_dbfs": float(to_db(peak)),
        "vad_threshold": thr,
        "active_speech_seconds": speech_dur,
        "active_ratio": speech_dur / duration if duration else 0.0,
        "window_count": len(windows),
        "median_window_s": statistics.median(w[2] for w in windows) if windows else 0.0,
        "longest_window_s": max((w[2] for w in windows), default=0.0),
        "median_gap_s": statistics.median(gaps) if gaps else 0.0,
        "windows": windows,
        "_active": active,
        "_hop_s": hop_s,
    }


def overlap_seconds(a_active, b_active, hop_s, np):
    n = min(len(a_active), len(b_active))
    return {
        "a_speaking_b_silent_s": float(np.sum(a_active[:n] & ~b_active[:n])) * hop_s,
        "b_speaking_a_silent_s": float(np.sum(b_active[:n] & ~a_active[:n])) * hop_s,
    }


def plot_envelopes(tracks, out_png, np):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, axes = plt.subplots(len(tracks), 1, figsize=(14, 3 * len(tracks)), sharex=True)
    for ax, t in zip(axes, tracks):
        env, hop_s = t["_env"], t["_hop_s"]
        ts = np.arange(len(env)) * hop_s
        ax.plot(ts, env, linewidth=0.6, color="#1f77b4")
        ax.axhline(t["vad_threshold"], color="red", linewidth=0.8, linestyle="--",
                   label="VAD thr %.4f" % t["vad_threshold"])
        for s, e, _ in t["windows"]:
            ax.axvspan(s, e, color="green", alpha=0.15)
        ax.set_title("%s  |  active %.2fs (%.0f%%)  |  RMS %.1f dBFS  peak %.1f dBFS"
                     % (t["name"], t["active_speech_seconds"], 100 * t["active_ratio"],
                        t["rms_dbfs"], t["peak_dbfs"]))
        ax.set_ylabel("RMS env")
        ax.legend(loc="upper right", fontsize=8)
    axes[-1].set_xlabel("seconds")
    fig.tight_layout()
    fig.savefig(str(out_png), dpi=110)
    plt.close(fig)
    return True


def build_checks(dur_req, tracks, probes, comps, gate):
    orig, ref, cand = tracks["original"], tracks["reference"], tracks["candidate"]
    checks = []

    def check(cid, ok, detail):
        checks.append({"id": cid, "pass": bool(ok), "detail": detail})

    for t in (orig, ref, cand):
        ok = abs(t["duration"] - dur_req) <= DURATION_TOLERANCE_S
        check("duration_contract_%s" % t["name"], ok,
              "%s extract %.2fs vs requested %.2fs (tolerance %.2fs)"
              % (t["name"], t["duration"], dur_req, DURATION_TOLERANCE_S))
    cand_probe = probes["candidate"]
    check("stream_contract_candidate",
          len(cand_probe["audio_streams"]) >= 1 and len(cand_probe["video_streams"]) >= 1,
          "candidate has %d video / %d audio streams"
          % (len(cand_probe["video_streams"]), len(cand_probe["audio_streams"])))

    cov_o = comps["coverage_vs_original"]
    check("coverage_vs_original", cov_o >= MIN_COVERAGE_VS_ORIGINAL,
          "candidate active %.2fs vs original %.2fs -> coverage %.2f (min %.2f)"
          % (cand["active_speech_seconds"], orig["active_speech_seconds"],
             cov_o, MIN_COVERAGE_VS_ORIGINAL))
    cov_r = comps["coverage_vs_reference"]
    check("coverage_vs_reference", cov_r >= MIN_COVERAGE_VS_REFERENCE,
          "candidate active %.2fs vs benchmark %.2fs -> coverage %.2f (min %.2f)"
          % (cand["active_speech_seconds"], ref["active_speech_seconds"],
             cov_r, MIN_COVERAGE_VS_REFERENCE))

    missing = comps["candidate_silent_while_original_speaking_s"]
    if gate["missing_gate"] == "benchmark-relative":
        limit = gate["reference_missing_s"] + gate["missing_margin_s"]
        check("silence_while_original_speaking", missing <= limit,
              "candidate silent for %.2fs while original speaks "
              "(benchmark-relative max %.2fs = reference %.2fs + margin %.2fs)"
              % (missing, limit, gate["reference_missing_s"], gate["missing_margin_s"]))
    else:
        check("silence_while_original_speaking", missing <= MAX_MISSING_SPEECH_S,
              "candidate silent for %.2fs while original speaks (max %.2fs)"
              % (missing, MAX_MISSING_SPEECH_S))

    delta = comps["candidate_rms_delta_vs_reference_db"]
    check("mix_not_over_hot", delta <= RMS_DELTA_MAX_DB,
          "candidate RMS %.1f dB vs benchmark (max +%.1f dB)" % (delta, RMS_DELTA_MAX_DB))
    check("mix_not_too_low", delta >= RMS_DELTA_MIN_DB,
          "candidate RMS %.1f dB vs benchmark (min %.1f dB)" % (delta, RMS_DELTA_MIN_DB))

    check("no_extreme_narration_block", cand["longest_window_s"] <= MAX_CONTINUOUS_WINDOW_S,
          "candidate longest continuous block %.2fs (max %.2fs)"
          % (cand["longest_window_s"], MAX_CONTINUOUS_WINDOW_S))
    return checks


def write_scorecard(path, args, tracks, comps, checks, verdict, reasons):
    orig, ref, cand = tracks["original"], tracks["reference"], tracks["candidate"]
    lines = [
        "# CloneDub V11 evaluation scorecard",
        "",
        "Verdict: **%s**" % verdict,
        "",
        "Gate mode: vad=%s, missing-gate=%s%s" % (
            args.vad_mode, args.missing_gate,
            " (margin %.1fs)" % args.missing_margin_s
            if args.missing_gate == "benchmark-relative" else ""),
        "",
        "- original: `%s`" % args.original,
        "- benchmark reference: `%s`" % args.reference,
        "- candidate: `%s` (start %.1fs, duration %.1fs)" % (args.candidate, args.candidate_start, args.duration),
        "",
        "## Track metrics",
        "",
        "| metric | original | benchmark | candidate |",
        "|---|---|---|---|",
    ]
    rows = [
        ("duration (s)", "duration", "%.2f"),
        ("RMS (dBFS)", "rms_dbfs", "%.1f"),
        ("peak (dBFS)", "peak_dbfs", "%.1f"),
        ("active speech (s)", "active_speech_seconds", "%.2f"),
        ("active ratio", "active_ratio", "%.2f"),
        ("speech windows", "window_count", "%d"),
        ("median window (s)", "median_window_s", "%.2f"),
        ("median gap (s)", "median_gap_s", "%.2f"),
        ("longest window (s)", "longest_window_s", "%.2f"),
    ]
    for label, key, fmt in rows:
        lines.append("| %s | %s | %s | %s |" % (label, fmt % orig[key], fmt % ref[key], fmt % cand[key]))
    lines += [
        "",
        "## Comparisons",
        "",
        "- speech coverage vs original: **%.2f**" % comps["coverage_vs_original"],
        "- speech coverage vs benchmark: **%.2f**" % comps["coverage_vs_reference"],
        "- candidate silent while original speaking: **%.2fs**" % comps["candidate_silent_while_original_speaking_s"],
        "- candidate speaking while original silent: %.2fs" % comps["candidate_speaking_while_original_silent_s"],
        "- candidate RMS vs benchmark: **%+.1f dB**" % comps["candidate_rms_delta_vs_reference_db"],
        "- candidate peak vs benchmark: %+.1f dB" % comps["candidate_peak_delta_vs_reference_db"],
        "",
        "## Checks",
        "",
        "| check | result | detail |",
        "|---|---|---|",
    ]
    for c in checks:
        lines.append("| %s | %s | %s |" % (c["id"], "PASS" if c["pass"] else "FAIL", c["detail"]))
    lines += ["", "## Verdict reasons", ""]
    lines += ["- %s" % r for r in reasons] if reasons else ["- all checks passed"]
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(
        description="CloneDub V11 Phase 1 evaluator: compare a candidate dub clip "
                    "against the original clip and a professional benchmark, and "
                    "emit an objective PASS/FAIL report.")
    p.add_argument("--original", required=True, help="original source clip (already trimmed to the test window)")
    p.add_argument("--reference", required=True, help="professional benchmark dub clip (already trimmed)")
    p.add_argument("--candidate", required=True, help="candidate dub video (may be full-length)")
    p.add_argument("--candidate-start", type=float, default=0.0,
                   help="seconds into the candidate where the test window starts (default 0)")
    p.add_argument("--duration", type=float, required=True, help="test window length in seconds")
    p.add_argument("--outdir", required=True, help="output directory (created if missing)")
    p.add_argument("--sr", type=int, default=DEFAULT_SR, help="analysis sample rate (default %d)" % DEFAULT_SR)
    p.add_argument("--vad-mode", choices=["baseline", "speechband"], default="baseline",
                   help="experimental: 'speechband' filters %d-%d Hz before activity "
                        "measurement (default baseline = current behavior)"
                        % (SPEECHBAND_HZ[0], SPEECHBAND_HZ[1]))
    p.add_argument("--missing-gate", choices=["absolute", "benchmark-relative"], default="absolute",
                   help="experimental: 'benchmark-relative' allows candidate missing-speech "
                        "up to reference missing + --missing-margin-s (default absolute = "
                        "current fixed %.1fs limit)" % MAX_MISSING_SPEECH_S)
    p.add_argument("--missing-margin-s", type=float, default=2.0,
                   help="margin for --missing-gate benchmark-relative (default 2.0)")
    args = p.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            sys.exit("error: %s not found on PATH" % tool)
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as e:
        sys.exit("error: missing python dependency: %s" % e)

    inputs = {"original": Path(args.original), "reference": Path(args.reference), "candidate": Path(args.candidate)}
    for name, path in inputs.items():
        if not path.is_file():
            sys.exit("error: %s input not found: %s" % (name, path))

    outdir = Path(args.outdir)
    extracts = outdir / "audio_extracts"
    extracts.mkdir(parents=True, exist_ok=True)

    probes, tracks = {}, {}
    for name, path in inputs.items():
        probes[name] = ffprobe_streams(path)
        wav = extracts / ("%s.wav" % name)
        start = args.candidate_start if name == "candidate" else 0.0
        extract_wav(path, wav, start, args.duration, args.sr)
        tracks[name] = analyze_track(name, wav, np, sf, args.vad_mode)
        print("[analyze] %-9s active=%.2fs/%ss rms=%.1fdBFS windows=%d"
              % (name, tracks[name]["active_speech_seconds"], "%g" % args.duration,
                 tracks[name]["rms_dbfs"], tracks[name]["window_count"]))

    orig, ref, cand = tracks["original"], tracks["reference"], tracks["candidate"]
    ov_o = overlap_seconds(orig["_active"], cand["_active"], orig["_hop_s"], np)
    ov_ref = overlap_seconds(orig["_active"], ref["_active"], orig["_hop_s"], np)
    db = lambda a, b: 20.0 * float(np.log10(a / b)) if a > 0 and b > 0 else 0.0
    comps = {
        "coverage_vs_original": cand["active_speech_seconds"] / orig["active_speech_seconds"]
            if orig["active_speech_seconds"] else 0.0,
        "coverage_vs_reference": cand["active_speech_seconds"] / ref["active_speech_seconds"]
            if ref["active_speech_seconds"] else 0.0,
        "candidate_silent_while_original_speaking_s": ov_o["a_speaking_b_silent_s"],
        "candidate_speaking_while_original_silent_s": ov_o["b_speaking_a_silent_s"],
        "reference_silent_while_original_speaking_s": ov_ref["a_speaking_b_silent_s"],
        "candidate_rms_delta_vs_reference_db": db(cand["rms"], ref["rms"]),
        "candidate_rms_delta_vs_original_db": db(cand["rms"], orig["rms"]),
        "candidate_peak_delta_vs_reference_db": db(cand["peak"], ref["peak"]),
    }

    gate = {"vad_mode": args.vad_mode, "missing_gate": args.missing_gate,
            "missing_margin_s": args.missing_margin_s,
            "reference_missing_s": ov_ref["a_speaking_b_silent_s"]}
    checks = build_checks(args.duration, tracks, probes, comps, gate)
    reasons = [c["detail"] for c in checks if not c["pass"]]
    verdict = "PASS" if not reasons else "FAIL"

    for t in tracks.values():
        x_plot = sf.read(str(extracts / ("%s.wav" % t["name"])), dtype="float64")[0]
        if args.vad_mode == "speechband":
            x_plot = bandpass_fft(np, x_plot, *SPEECHBAND_HZ, args.sr)
        env, _ = rms_envelope(x_plot, args.sr, np)
        t["_env"] = env
    plotted = plot_envelopes([orig, ref, cand], outdir / "envelope.png", np)
    if not plotted:
        print("[warn] matplotlib unavailable, envelope.png skipped")

    public = {n: {k: v for k, v in t.items() if not k.startswith("_")} for n, t in tracks.items()}
    (outdir / "activity_windows.json").write_text(
        json.dumps({n: t["windows"] for n, t in public.items()}, indent=2), encoding="utf-8")
    thresholds = {
        "duration_tolerance_s": DURATION_TOLERANCE_S,
        "min_coverage_vs_original": MIN_COVERAGE_VS_ORIGINAL,
        "min_coverage_vs_reference": MIN_COVERAGE_VS_REFERENCE,
        "max_missing_speech_s": MAX_MISSING_SPEECH_S,
        "rms_delta_vs_reference_db_range": [RMS_DELTA_MIN_DB, RMS_DELTA_MAX_DB],
        "max_continuous_window_s": MAX_CONTINUOUS_WINDOW_S,
        "vad_rms_ratio": VAD_RMS_RATIO,
        "vad_frame_s": FRAME_S,
        "vad_hop_s": HOP_S,
        "merge_gap_s": MERGE_GAP_S,
        "min_window_s": MIN_WINDOW_S,
    }
    eval_doc = {
        "tool": "clonedub_v11_evaluate", "version": TOOL_VERSION,
        "args": {k: str(v) for k, v in vars(args).items()},
        "gate_config": dict(gate, candidate_missing_s=comps[
            "candidate_silent_while_original_speaking_s"]),
        "thresholds": thresholds,
        "streams": probes,
        "tracks": public,
        "comparisons": comps,
        "checks": checks,
        "verdict": verdict,
        "verdict_reasons": reasons,
    }
    (outdir / "eval.json").write_text(json.dumps(eval_doc, indent=2), encoding="utf-8")
    write_scorecard(outdir / "scorecard.md", args, tracks, comps, checks, verdict, reasons)

    print("\n=== VERDICT: %s ===" % verdict)
    for r in reasons:
        print("  - %s" % r)
    print("reports written to %s" % outdir)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
