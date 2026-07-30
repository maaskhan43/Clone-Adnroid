#!/usr/bin/env python3
"""CloneDub V11 Phase 5B: no-new-voice style application (900-960s).

Applies the measured Rask style profile to EXISTING V1 audio, as a
mix/level/dynamics experiment only. NO TTS, no new voice, no APIs.

Approach: V1's pipeline provides separated stems (final_dialogue.wav,
music_fx.wav). We rebuild the 60s mix by:
  - lowering V1 dialogue toward Rask's overall loudness,
  - gently compressing dialogue (reduce crest/forwardness, even it less
    aggressively than a limiter so some acting dynamics survive),
  - keeping the music/room bed present under speech (avoid the -42 dB
    collapse) by mixing dialogue OVER the bed at a Rask-like level.

Produces soft + stronger variants (and an optional timing-light variant),
muxes each over the original V1 video window, and measures every variant
against the Rask targets via the Phase 5A profiler.

See CLONEDUB_V11_PRO_DUB_MASTER_PLAN.md, Phase 5.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

TOOL_VERSION = "1.0.0"
SR = 48000


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("cmd failed (%d): %s\n%s" % (p.returncode, " ".join(map(str, cmd)), p.stderr[-1500:]))
    return p.stdout


def slice_wav(np, sf, src, start, dur):
    """Load a [start, start+dur] mono slice at SR from any audio/video source."""
    tmp = src if str(src).endswith(".wav") else None
    if tmp is None:
        raise ValueError("slice_wav expects wav")
    x, sr = sf.read(str(src), dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    a, b = int(start * sr), int((start + dur) * sr)
    seg = x[a:b]
    if sr != SR:
        # linear resample (adequate for level/analysis mixing)
        n = int(round(len(seg) * SR / sr))
        seg = np.interp(np.linspace(0, len(seg), n, endpoint=False), np.arange(len(seg)), seg)
    return seg


def rms_db(np, x):
    import math
    r = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    return 20.0 * math.log10(r) if r > 0 else -120.0


def set_rms(np, x, target_db):
    cur = rms_db(np, x)
    if cur <= -119:
        return x
    return x * (10 ** ((target_db - cur) / 20.0))


def soft_compress(np, x, threshold_db=-30.0, ratio=3.0, makeup_db=0.0):
    """Simple envelope-following soft-knee compressor to reduce crest/forwardness.

    Lowers peaks above threshold by `ratio`, evens dynamics without killing all
    acting variation. Deterministic; operates on the analytic-ish RMS envelope.
    """
    win = int(0.02 * SR)
    pad = np.pad(x ** 2, (win, win), mode="edge")
    env = np.sqrt(np.convolve(pad, np.ones(win) / win, mode="same")[win:-win] + 1e-12)
    env_db = 20.0 * np.log10(env + 1e-12)
    over = np.maximum(0.0, env_db - threshold_db)
    gain_db = -over * (1.0 - 1.0 / ratio) + makeup_db
    return x * (10.0 ** (gain_db / 20.0))


def build_variant(np, sf, name, dialogue, bed, dlg_rms_db, comp, bed_gain_db, outdir):
    d = set_rms(np, dialogue, dlg_rms_db)
    if comp:
        d = soft_compress(np, d, **comp)
        d = set_rms(np, d, dlg_rms_db)  # re-normalize after compression
    b = bed * (10.0 ** (bed_gain_db / 20.0))
    n = min(len(d), len(b))
    mix = d[:n] + b[:n]
    peak = np.abs(mix).max()
    if peak > 0.99:
        mix *= 0.99 / peak
    wav = outdir / ("%s.wav" % name)
    sf.write(str(wav), mix, SR)
    return wav


def mux(video, start, dur, mix_wav, out_mp4):
    run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % start, "-i", str(video),
         "-i", str(mix_wav), "-t", "%.3f" % dur, "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_mp4)])


def profile_metrics(np, sf, wav):
    """Reuse the Phase 5A analyzer for consistent metrics on a bare wav."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sp", str(Path(__file__).parent / "clonedub_v11_style_profile.py"))
    sp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sp)
    # analyze expects a 16k wav; resample via ffmpeg to a temp then analyze
    tmp = wav.with_suffix(".16k.wav")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(tmp)])
    t = sp.analyze(np, sf, wav.stem, tmp)
    return {k: v for k, v in t.items() if not k.startswith("_")}


def main():
    p = argparse.ArgumentParser(description="CloneDub V11 Phase 5B: apply Rask style "
                                            "profile to existing V1 audio (no TTS).")
    p.add_argument("--video", required=True, help="V1 full candidate video")
    p.add_argument("--dialogue", required=True, help="V1 separated dialogue stem wav")
    p.add_argument("--bed", required=True, help="V1 separated music/FX stem wav")
    p.add_argument("--rask", required=True, help="Rask benchmark 60s clip")
    p.add_argument("--original", required=True, help="original 60s clip")
    p.add_argument("--profile", required=True, help="rask_style_profile.json")
    p.add_argument("--window-start", type=float, default=900.0)
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    import numpy as np
    import soundfile as sf

    prof = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    rask = prof["tracks"]["rask"]
    v1p = prof["tracks"]["v1"]
    rask_rms = rask["rms_dbfs"]

    outdir = Path(args.outdir)
    ex = outdir / "audio_extracts"
    ex.mkdir(parents=True, exist_ok=True)

    dlg = slice_wav(np, sf, args.dialogue, args.window_start, args.duration)
    bed = slice_wav(np, sf, args.bed, args.window_start, args.duration)
    bed_rms_db = rms_db(np, bed)
    print("[stems] dialogue %.1f dBFS, bed %.1f dBFS (window %.0f-%.0f)"
          % (rms_db(np, dlg), bed_rms_db, args.window_start, args.window_start + args.duration))

    # variants: dialogue toward Rask RMS; soft = gentle, stronger = more compression +
    # more bed presence. Bed is boosted so it survives under speech (limited by how
    # quiet the source bed is - documented).
    variants = [
        ("v1_style_mix_soft", rask_rms + 1.0,
         {"threshold_db": -32.0, "ratio": 2.5}, +6.0),
        ("v1_style_mix_stronger", rask_rms,
         {"threshold_db": -34.0, "ratio": 4.0}, +12.0),
    ]

    results = []
    for name, dlg_rms, comp, bed_gain in variants:
        wav = build_variant(np, sf, name, dlg, bed, dlg_rms, comp, bed_gain, ex)
        mp4 = outdir / ("%s_900_960.mp4" % name)
        mux(args.video, args.window_start, args.duration, wav, mp4)
        m = profile_metrics(np, sf, wav)
        results.append({"name": name, "mp4": str(mp4), "dlg_target_rms_db": dlg_rms,
                        "bed_gain_db": bed_gain, "metrics": m})
        print("[variant] %-22s rms=%.1f fwd=%.1f bed=%.1f active=%.1f"
              % (name, m["rms_dbfs"], m["speechband_forwardness_db"],
                 m["bed_floor_under_speech_delta_db"], m["active_speech_s"]))

    # timing-light: not attempted (would need re-segmentation/stretch on mixed audio,
    # which risks artifacts on the combined stem). Documented as skipped.
    timing_note = ("timing_light SKIPPED: safe timing re-spacing needs per-line "
                   "boundaries on a clean dialogue stem and re-fitting; doing it on the "
                   "already-mixed 60s bed risks audible artifacts. Deferred to the "
                   "dialogue-generation stage where per-block timing is available.")

    # baseline + rask extracts for the listening pack
    for nm, src, start in [("rask_benchmark", args.rask, 0.0),
                           ("v1_baseline", args.video, args.window_start),
                           ("original", args.original, 0.0)]:
        run(["ffmpeg", "-y", "-v", "error"] +
            (["-ss", "%.3f" % start] if start else []) +
            ["-i", str(src), "-t", "%.3f" % args.duration, "-vn", "-ac", "1",
             "-ar", str(SR), "-c:a", "pcm_s16le", str(ex / ("%s.wav" % nm))])

    def dir_ok(v, r, cur):
        """did the variant move from V1 baseline toward Rask?"""
        return abs(v - r) < abs(cur - r)

    doc = {"tool": "clonedub_v11_style_apply", "version": TOOL_VERSION,
           "window": [args.window_start, args.window_start + args.duration],
           "no_tts": True, "targets": {"rms_dbfs": rask_rms,
           "speechband_forwardness_db": rask["speechband_forwardness_db"],
           "bed_floor_under_speech_delta_db": rask["bed_floor_under_speech_delta_db"]},
           "v1_baseline": {k: v1p[k] for k in ("rms_dbfs", "speechband_forwardness_db",
                           "bed_floor_under_speech_delta_db", "active_speech_s")},
           "source_bed_rms_dbfs": round(bed_rms_db, 1),
           "variants": results, "timing_light": timing_note}
    (outdir / "style_apply_metrics.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")

    # report
    L = ["# CloneDub V11 Phase 5B - style application (900-960s)", "",
         "No TTS, no new voice. Rebuilt V1 mix from separated stems "
         "(dialogue + music/FX bed) toward the Rask style profile.", "",
         "Targets (Rask): RMS %.1f dBFS, forwardness %.1f dB, bed-floor delta %.1f dB."
         % (rask_rms, rask["speechband_forwardness_db"], rask["bed_floor_under_speech_delta_db"]),
         "V1 baseline: RMS %.1f, forwardness %.1f, bed-floor %.1f."
         % (v1p["rms_dbfs"], v1p["speechband_forwardness_db"], v1p["bed_floor_under_speech_delta_db"]),
         "",
         "**Source limitation:** the V1 music/FX bed in this window is only %.1f dBFS "
         "(very quiet), so 'keep bed alive under speech' can only go as far as the source bed "
         "allows. Bed boost is applied but cannot fully reach Rask's -10.5 dB delta from this "
         "material. Documented, not hidden." % bed_rms_db, "",
         "## Variant metrics (did each move V1 toward Rask?)", "",
         "| variant | RMS dBFS | fwd dB | bed-floor dB | active s | moved toward Rask? |",
         "|---|---|---|---|---|---|"]
    for r in results:
        m = r["metrics"]
        moved = []
        moved.append("RMS" if dir_ok(m["rms_dbfs"], rask_rms, v1p["rms_dbfs"]) else "RMS x")
        moved.append("fwd" if dir_ok(m["speechband_forwardness_db"],
                     rask["speechband_forwardness_db"], v1p["speechband_forwardness_db"]) else "fwd x")
        moved.append("bed" if dir_ok(m["bed_floor_under_speech_delta_db"],
                     rask["bed_floor_under_speech_delta_db"], v1p["bed_floor_under_speech_delta_db"]) else "bed x")
        L.append("| %s | %.1f | %.1f | %.1f | %.1f | %s |" % (
            r["name"], m["rms_dbfs"], m["speechband_forwardness_db"],
            m["bed_floor_under_speech_delta_db"], m["active_speech_s"], ", ".join(moved)))
    L += ["", "Intelligibility guard: active speech seconds should stay close to V1 baseline "
          "(%.1fs); a large drop would mean the bed swallowed the dialogue." % v1p["active_speech_s"],
          "", "## Timing variant", "", timing_note, "",
          "## Honest scope note", "",
          "This tests ONLY whether a Rask-like mix/bed/forwardness improves perceived feel. "
          "It does not change the voice or acting. If it helps, mix direction is confirmed and "
          "carried into the dialogue-generation redo; if not, the bottleneck is voice/acting and "
          "mix alone will not fix it.", ""]
    (outdir / "style_apply_report.md").write_text("\n".join(L), encoding="utf-8")

    # listening readme
    R = ["# V11 Phase 5B listening pack (900-960s) - style application, no new voice", "",
         "Listen in order; judge whether the Rask-like mix feels more like a real dub:", "",
         "1. Rask benchmark: `%s`" % args.rask,
         "2. Old V1 900-960 baseline: `%s` (seek 15:00)" % args.video,
         "3. soft variant:     `%s`" % results[0]["mp4"],
         "4. stronger variant: `%s`" % results[1]["mp4"],
         "", "Decision: does soft or stronger feel closer to real dub, or neither? "
         "Voice/acting is unchanged - this only tests mix direction.", ""]
    (outdir / "LISTENING_README.md").write_text("\n".join(R), encoding="utf-8")

    print("report: %s" % (outdir / "style_apply_report.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
