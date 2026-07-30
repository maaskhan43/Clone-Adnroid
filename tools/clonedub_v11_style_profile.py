#!/usr/bin/env python3
"""CloneDub V11 Phase 5A: Rask-style audio/timing profile extraction.

Human listening rejected all TTS voices; the gap is dubbing-system STYLE
(line shape, cadence, mix forwardness, ducking, compression), not the
voice. This tool measures those traits from waveform/VAD/envelope for
original vs Rask vs V1 on the same 60s window and emits a concrete
target profile to guide future V1 improvement.

Measurement only: no TTS, no APIs, no video generation. ASR transcript
text is deliberately NOT used as authoritative evidence (the existing
Rask/V1 ASR is noisy/mojibake); everything here is audio-derived.

See CLONEDUB_V11_PRO_DUB_MASTER_PLAN.md, Phase 5 (mix/room integration).
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
VAD_RMS_RATIO = 0.42          # activity threshold = ratio * global RMS (matches evaluator)
VAD_ABS_FLOOR = 10 ** (-55.0 / 20.0)
MERGE_GAP_S = 0.15
MIN_WINDOW_S = 0.10
SPEECHBAND = (300.0, 3400.0)  # dialogue band for forwardness/ducking proxies
TAIL_DROP_DB = 12.0           # envelope fall from window peak that marks the tail start
LONG_BLOCK_S = 8.0            # continuous speech longer than this = narration-like


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("cmd failed (%d): %s\n%s" % (p.returncode, " ".join(map(str, cmd)), p.stderr[-1500:]))
    return p.stdout


def ffprobe(path):
    out = run(["ffprobe", "-v", "error", "-show_entries",
               "format=duration:stream=codec_type,codec_name,sample_rate,channels,width,height,r_frame_rate",
               "-of", "json", str(path)])
    info = json.loads(out)
    streams = info.get("streams", [])
    return {
        "duration": float(info.get("format", {}).get("duration", 0.0)),
        "video_streams": sum(1 for s in streams if s.get("codec_type") == "video"),
        "audio_streams": sum(1 for s in streams if s.get("codec_type") == "audio"),
        "audio": next(({"codec": s.get("codec_name"), "sr": s.get("sample_rate"),
                        "ch": s.get("channels")} for s in streams
                       if s.get("codec_type") == "audio"), {}),
    }


def extract(src, dst, start, dur):
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start > 0:
        cmd += ["-ss", "%.3f" % start]
    cmd += ["-i", str(src), "-t", "%.3f" % dur, "-vn", "-ac", "1", "-ar", str(SR),
            "-c:a", "pcm_s16le", str(dst)]
    run(cmd)


def bandpass(np, x, lo, hi):
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    spec[(freqs < lo) | (freqs > hi)] = 0.0
    return np.fft.irfft(spec, n=len(x))


def envelope(np, x):
    frame = int(round(FRAME_S * SR))
    hop = int(round(HOP_S * SR))
    if len(x) < frame:
        return np.zeros(0)
    n = 1 + (len(x) - frame) // hop
    csum = np.concatenate(([0.0], np.cumsum(x.astype(np.float64) ** 2)))
    s = np.arange(n) * hop
    return np.sqrt((csum[s + frame] - csum[s]) / frame)


def windows_from_env(np, env, rms):
    thr = max(VAD_ABS_FLOOR, VAD_RMS_RATIO * rms)
    active = env >= thr
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
        if merged and w[0] - merged[-1][1] < MERGE_GAP_S:
            merged[-1][1] = w[1]
        else:
            merged.append(list(w))
    merged = [w for w in merged if w[1] - w[0] >= MIN_WINDOW_S]
    return merged, active, thr


def db(v):
    import math
    return 20.0 * math.log10(v) if v > 0 else -120.0


def median(xs):
    import statistics
    return statistics.median(xs) if xs else 0.0


def analyze(np, sf, name, wav):
    x, _ = sf.read(str(wav), dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    dur = len(x) / SR
    rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    env = envelope(np, x)
    wins, active, thr = windows_from_env(np, env, rms)
    win_lens = [w[1] - w[0] for w in wins]
    gaps = [wins[i + 1][0] - wins[i][1] for i in range(len(wins) - 1)]
    speech_s = sum(win_lens)

    # per-window RMS + crest for compression/consistency
    win_rms, win_crest, tail_lens = [], [], []
    for s, e in wins:
        seg = x[int(s * SR):int(e * SR)]
        if len(seg) < 10:
            continue
        r = float(np.sqrt(np.mean(seg ** 2)))
        pk = float(np.max(np.abs(seg)))
        win_rms.append(r)
        win_crest.append(db(pk) - db(r))
        # tail: time from last peak-{TAIL_DROP} crossing to window end
        senv = envelope(np, seg)
        if len(senv):
            pk_db = db(senv.max())
            below = np.where(db_arr(np, senv) < pk_db - TAIL_DROP_DB)[0]
            if len(below):
                tail_lens.append((len(senv) - below[0]) * HOP_S)

    speechband = bandpass(np, x, *SPEECHBAND)
    sb_env = envelope(np, speechband)
    speech_mask = active[:len(sb_env)]
    sb_speech = sb_env[speech_mask]
    sb_nonspeech = sb_env[~speech_mask] if (~speech_mask).any() else np.array([0.0])
    fullband_nonspeech = env[~active] if (~active).any() else np.array([0.0])
    forwardness_db = db(float(np.mean(sb_speech)) if len(sb_speech) else 0.0) - \
        db(float(np.mean(sb_nonspeech)) if len(sb_nonspeech) else 0.0)
    # ducking proxy: full-band floor during speech vs between speech
    floor_speech = db(float(np.median(env[active])) if active.any() else 0.0)
    floor_between = db(float(np.median(fullband_nonspeech)))
    ducking_db = floor_between - floor_speech  # positive => between-speech louder (no ducking)

    return {
        "name": name, "duration": round(dur, 3),
        "rms_dbfs": round(db(rms), 2), "peak_dbfs": round(db(peak), 2),
        "crest_db": round(db(peak) - db(rms), 2),
        "dynamic_range_db": round(db(float(np.percentile(env, 95))) -
                                  db(float(np.percentile(env, 20))), 2) if len(env) else 0.0,
        "vad_threshold": round(thr, 5),
        "active_speech_s": round(speech_s, 2),
        "active_ratio": round(speech_s / dur, 3) if dur else 0.0,
        "window_count": len(wins),
        "median_window_s": round(median(win_lens), 2),
        "longest_window_s": round(max(win_lens) if win_lens else 0.0, 2),
        "median_gap_s": round(median(gaps), 2),
        "pause_density_per_min": round(len(gaps) / (dur / 60.0), 2) if dur else 0.0,
        "long_narration_blocks": sum(1 for L in win_lens if L >= LONG_BLOCK_S),
        "longest_narration_s": round(max(win_lens) if win_lens else 0.0, 2),
        "median_window_rms_dbfs": round(db(median(win_rms)), 2),
        "window_rms_spread_db": round((db(max(win_rms)) - db(min(win_rms))) if win_rms else 0.0, 2),
        "median_crest_db": round(median(win_crest), 2),
        "median_tail_s": round(median(tail_lens), 2),
        "abrupt_endings": sum(1 for t in tail_lens if t < 0.12),
        "speechband_forwardness_db": round(forwardness_db, 2),
        "ducking_db": round(ducking_db, 2),
        "_env": env, "_active": active, "_windows": wins,
    }


def db_arr(np, a):
    return 20.0 * np.log10(np.maximum(a, 1e-9))


def onset_offset_drift(orig, cand):
    """Median absolute onset/offset drift of candidate windows vs nearest original window."""
    ow = orig["_windows"]
    if not ow or not cand["_windows"]:
        return {"median_onset_drift_s": 0.0, "median_offset_drift_s": 0.0}
    onset, offset = [], []
    for s, e in cand["_windows"]:
        onset.append(min(abs(s - o[0]) for o in ow))
        offset.append(min(abs(e - o[1]) for o in ow))
    return {"median_onset_drift_s": round(median(onset), 2),
            "median_offset_drift_s": round(median(offset), 2)}


def overlap(np, a_active, b_active):
    n = min(len(a_active), len(b_active))
    a, b = a_active[:n], b_active[:n]
    return {"a_speaking_b_silent_s": round(float(np.sum(a & ~b)) * HOP_S, 2),
            "b_speaking_a_silent_s": round(float(np.sum(b & ~a)) * HOP_S, 2)}


def target_profile(rask):
    """Concrete target ranges for future V1 improvement, derived from Rask."""
    def rng(v, lo, hi):
        return [round(v * lo, 2), round(v * hi, 2)]
    return {
        "target_median_window_s": rng(rask["median_window_s"], 0.85, 1.15),
        "target_median_gap_s": rng(rask["median_gap_s"], 0.7, 1.3),
        "target_active_ratio": rng(rask["active_ratio"], 0.92, 1.05),
        "target_speechband_forwardness_db": [round(rask["speechband_forwardness_db"] - 2, 1),
                                             round(rask["speechband_forwardness_db"] + 2, 1)],
        "target_median_crest_db": [round(rask["median_crest_db"] - 1.5, 1),
                                   round(rask["median_crest_db"] + 1.5, 1)],
        "target_window_rms_spread_max_db": round(rask["window_rms_spread_db"] + 1.5, 1),
        "max_long_narration_s": max(LONG_BLOCK_S, rask["longest_narration_s"]),
        "target_median_tail_s": [round(rask["median_tail_s"] * 0.8, 2),
                                 round(rask["median_tail_s"] * 1.2, 2)],
    }


def style_gaps(rask, v1):
    """Top style differences V1 must close to sound like Rask (audio-only)."""
    checks = [
        ("dialogue forwardness (speech vs floor)", "speechband_forwardness_db", "dB", 2.0),
        ("mix loudness (RMS)", "rms_dbfs", "dBFS", 2.0),
        ("compression (crest)", "median_crest_db", "dB", 1.5),
        ("level consistency (window RMS spread)", "window_rms_spread_db", "dB", 2.0),
        ("speech window length", "median_window_s", "s", 0.3),
        ("gap length", "median_gap_s", "s", 0.15),
        ("active speech ratio", "active_ratio", "", 0.05),
        ("line-ending tail", "median_tail_s", "s", 0.15),
        ("ducking (floor between vs under speech)", "ducking_db", "dB", 2.0),
        ("longest continuous narration", "longest_narration_s", "s", 3.0),
    ]
    gaps = []
    for label, key, unit, thr in checks:
        d = v1[key] - rask[key]
        if abs(d) >= thr:
            gaps.append({"metric": label, "rask": rask[key], "v1": v1[key],
                         "delta": round(d, 2), "unit": unit, "abs": abs(d)})
    return sorted(gaps, key=lambda g: g["abs"], reverse=True)


def plot(np, tracks, outdir):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    (outdir / "plots").mkdir(parents=True, exist_ok=True)
    # envelope compare
    fig, axes = plt.subplots(3, 1, figsize=(14, 8), sharex=True)
    for ax, t in zip(axes, tracks):
        env = t["_env"]
        ts = np.arange(len(env)) * HOP_S
        ax.plot(ts, db_arr(np, env), linewidth=0.5)
        for s, e in t["_windows"]:
            ax.axvspan(s, e, color="green", alpha=0.15)
        ax.set_title("%s | active %.1fs, %d win, med win %.2fs, fwd %.1fdB, crest %.1fdB"
                     % (t["name"], t["active_speech_s"], t["window_count"],
                        t["median_window_s"], t["speechband_forwardness_db"], t["median_crest_db"]))
        ax.set_ylabel("dB"); ax.set_ylim(-80, 0)
    axes[-1].set_xlabel("seconds")
    fig.tight_layout(); fig.savefig(str(outdir / "plots" / "envelope_compare.png"), dpi=110)
    plt.close(fig)
    # speech windows compare (timeline bars)
    fig, ax = plt.subplots(figsize=(14, 3))
    for i, t in enumerate(tracks):
        for s, e in t["_windows"]:
            ax.barh(i, e - s, left=s, height=0.6, color="C%d" % i)
        ax.text(-2, i, t["name"], ha="right", va="center")
    ax.set_yticks([]); ax.set_xlabel("seconds"); ax.set_title("Speech windows: original / Rask / V1")
    fig.tight_layout(); fig.savefig(str(outdir / "plots" / "speech_windows_compare.png"), dpi=110)
    plt.close(fig)
    return True


def write_md(path, probes, tracks, drifts, overlaps, profile, gaps):
    orig, rask, v1 = tracks
    L = ["# CloneDub V11 — Rask-style audio/timing profile (900-960s)", "",
         "Measurement only. **ASR transcript text is NOT used** (existing ASR is noisy/mojibake); "
         "all evidence below is waveform/VAD/envelope-derived.", "",
         "## Stream contract", "",
         "| clip | duration | video | audio | codec |", "|---|---|---|---|---|"]
    for nm, pr in probes.items():
        L.append("| %s | %.2fs | %d | %d | %s |" % (nm, pr["duration"], pr["video_streams"],
                  pr["audio_streams"], pr["audio"].get("codec", "?")))
    L += ["", "## Core metrics (original / Rask / V1)", "",
          "| metric | original | Rask | V1 |", "|---|---|---|---|"]
    rows = [("active speech (s)", "active_speech_s"), ("active ratio", "active_ratio"),
            ("windows", "window_count"), ("median window (s)", "median_window_s"),
            ("longest window (s)", "longest_window_s"), ("median gap (s)", "median_gap_s"),
            ("pause density /min", "pause_density_per_min"),
            ("long narration blocks", "long_narration_blocks"),
            ("RMS (dBFS)", "rms_dbfs"), ("peak (dBFS)", "peak_dbfs"),
            ("crest (dB)", "crest_db"), ("median window crest (dB)", "median_crest_db"),
            ("window RMS spread (dB)", "window_rms_spread_db"),
            ("dynamic range (dB)", "dynamic_range_db"),
            ("speechband forwardness (dB)", "speechband_forwardness_db"),
            ("ducking (dB, +=no duck)", "ducking_db"),
            ("median tail (s)", "median_tail_s"), ("abrupt endings", "abrupt_endings")]
    for label, key in rows:
        L.append("| %s | %s | %s | %s |" % (label, orig[key], rask[key], v1[key]))
    L += ["", "## Timing alignment vs original", "",
          "- Rask onset/offset drift: %.2fs / %.2fs; V1: %.2fs / %.2fs" % (
              drifts["rask"]["median_onset_drift_s"], drifts["rask"]["median_offset_drift_s"],
              drifts["v1"]["median_onset_drift_s"], drifts["v1"]["median_offset_drift_s"]),
          "- Rask silent-while-original-speaks: %.2fs; V1: %.2fs" % (
              overlaps["rask"]["a_speaking_b_silent_s"], overlaps["v1"]["a_speaking_b_silent_s"]),
          "- Rask speaking-while-original-silent: %.2fs; V1: %.2fs" % (
              overlaps["rask"]["b_speaking_a_silent_s"], overlaps["v1"]["b_speaking_a_silent_s"]),
          "", "## Top style gaps — what V1 must change to sound like Rask", ""]
    if gaps:
        L.append("| # | trait | Rask | V1 | delta |")
        L.append("|---|---|---|---|---|")
        for i, g in enumerate(gaps[:8], 1):
            L.append("| %d | %s | %s%s | %s%s | %+.2f%s |" % (
                i, g["metric"], g["rask"], g["unit"], g["v1"], g["unit"], g["delta"], g["unit"]))
    else:
        L.append("(no gaps above thresholds)")
    L += ["", "## Target profile for future V1 improvement", "",
          "```json", json.dumps(profile, indent=2), "```", "",
          "## Direction (audio-derived, for the style-application step — NOT done here)", "",
          "- Match Rask's median window / gap: reshape lines toward that length, add the pauses it uses.",
          "- Raise dialogue forwardness toward the target band (speech-band level over music floor).",
          "- Apply compression so per-window crest and RMS spread fall into the target ranges "
          "(consistent, forward delivery instead of uneven narration).",
          "- Duck music under speech to match Rask's floor difference.",
          "- Keep line-ending tails near Rask's median (avoid abrupt cut-offs and avoid long trailing narration).", ""]
    path.write_text("\n".join(L), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description="CloneDub V11 Phase 5A: extract a Rask-style "
                                            "audio/timing profile (measurement only, no TTS).")
    p.add_argument("--original", required=True)
    p.add_argument("--rask", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--candidate-start", type=float, default=900.0)
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    import numpy as np
    import soundfile as sf

    outdir = Path(args.outdir)
    ex = outdir / "audio_extracts"
    ex.mkdir(parents=True, exist_ok=True)

    plan = [("original", args.original, 0.0), ("rask", args.rask, 0.0),
            ("v1", args.candidate, args.candidate_start)]
    probes, wavs = {}, {}
    for nm, src, start in plan:
        probes[nm] = ffprobe(src)
        wavs[nm] = ex / ("%s.wav" % nm)
        extract(src, wavs[nm], start, args.duration)

    orig = analyze(np, sf, "original", wavs["original"])
    rask = analyze(np, sf, "rask", wavs["rask"])
    v1 = analyze(np, sf, "v1", wavs["v1"])
    tracks = [orig, rask, v1]

    drifts = {"rask": onset_offset_drift(orig, rask), "v1": onset_offset_drift(orig, v1)}
    overlaps = {"rask": overlap(np, orig["_active"], rask["_active"]),
                "v1": overlap(np, orig["_active"], v1["_active"])}
    profile = target_profile(rask)
    gaps = style_gaps(rask, v1)
    plotted = plot(np, tracks, outdir)

    pub = lambda t: {k: v for k, v in t.items() if not k.startswith("_")}
    doc = {"tool": "clonedub_v11_style_profile", "version": TOOL_VERSION,
           "asr_text_used": False, "asr_note": "existing ASR is noisy/mojibake; not used",
           "window": [args.candidate_start, args.candidate_start + args.duration],
           "stream_contract": probes,
           "tracks": {"original": pub(orig), "rask": pub(rask), "v1": pub(v1)},
           "timing_drift_vs_original": drifts, "speech_overlap_vs_original": overlaps,
           "target_profile": profile, "top_style_gaps": gaps, "plots_written": plotted}
    (outdir / "rask_style_profile.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    write_md(outdir / "rask_style_profile.md", probes, tracks, drifts, overlaps, profile, gaps)

    print("Rask : active=%.1fs win=%d medwin=%.2f medgap=%.2f rms=%.1f crest=%.1f fwd=%.1f"
          % (rask["active_speech_s"], rask["window_count"], rask["median_window_s"],
             rask["median_gap_s"], rask["rms_dbfs"], rask["median_crest_db"],
             rask["speechband_forwardness_db"]))
    print("V1   : active=%.1fs win=%d medwin=%.2f medgap=%.2f rms=%.1f crest=%.1f fwd=%.1f"
          % (v1["active_speech_s"], v1["window_count"], v1["median_window_s"],
             v1["median_gap_s"], v1["rms_dbfs"], v1["median_crest_db"],
             v1["speechband_forwardness_db"]))
    print("top style gaps:")
    for g in gaps[:5]:
        print("  %s: Rask %s%s vs V1 %s%s (%+.2f)" % (g["metric"], g["rask"], g["unit"],
              g["v1"], g["unit"], g["delta"]))
    print("outdir: %s | plots: %s" % (outdir, plotted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
