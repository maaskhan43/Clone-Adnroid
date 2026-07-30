#!/usr/bin/env python3
"""CloneDub V11 Phase 6B: scene generation test (per-actor-lane voices).

Generates a 60s test dub for one scene from a Phase 6A.1 performance
script, assigning a DISTINCT voice per `actor_lane_id` (never the
source diarization speaker id). Places each beat on its timeline,
mixes with the scene's music/FX bed toward a forward-but-present level,
and muxes over the scene video.

This is a small TEST only - no full video, no LatentSync, no new
provider bake-off. Fish (free-tier) voices are used so 4 distinct lanes
cost nothing. Text is textguard-validated before any synthesis.

See CLONEDUB_V11_PRO_DUB_MASTER_PLAN.md, Phase 6.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

TOOL_VERSION = "1.0.0"
SR = 48000
BLOCK_RMS_DBFS = -20.0     # per-beat dialogue level before final scaling
BED_GAIN_DB = 0.0
MAX_TEMPO = 1.12           # allow a touch more on short reaction beats
FIT_TRIGGER = 1.05
TRIM_DROP_DB = 35.0
TRIM_PAD_S = 0.05


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("cmd failed (%d): %s\n%s" % (p.returncode, " ".join(map(str, cmd)), p.stderr[-1500:]))
    return p


def to_wav(src, dst, sr=SR):
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1",
         "-ar", str(sr), "-c:a", "pcm_s16le", str(dst)])


def load(np, sf, path):
    x, sr = sf.read(str(path), dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != SR:
        n = int(round(len(x) * SR / sr))
        x = np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x)
    return x


def trim_silence(np, x):
    frame = int(0.02 * SR)
    if len(x) < 2 * frame:
        return x
    n = len(x) // frame
    env = np.sqrt(np.mean(x[:n * frame].reshape(n, frame) ** 2, axis=1))
    peak_db = 20 * np.log10(env.max() + 1e-12)
    active = 20 * np.log10(env + 1e-12) > peak_db - TRIM_DROP_DB
    idx = np.where(active)[0]
    if not len(idx):
        return x
    pad = int(TRIM_PAD_S * SR)
    return x[max(0, idx[0] * frame - pad):min(len(x), (idx[-1] + 1) * frame + pad)]


def set_rms(np, x, target_db):
    r = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    return x if r <= 0 else x * (10 ** (target_db / 20.0) / r)


def fit(np, sf, x, target_s, work):
    dur = len(x) / SR
    if target_s > 0 and dur > target_s * FIT_TRIGGER:
        tempo = min(dur / target_s, MAX_TEMPO)
        a, b = work / "in.wav", work / "out.wav"
        sf.write(str(a), x, SR)
        run(["ffmpeg", "-y", "-v", "error", "-i", str(a), "-filter:a",
             "atempo=%.4f" % tempo, str(b)])
        x = load(np, sf, b)
    return x


def main():
    p = argparse.ArgumentParser(description="CloneDub V11 Phase 6B scene generation test "
                                            "(per-actor-lane voices, 60s only).")
    p.add_argument("--script", required=True, help="Phase 6A.1 performance_script.json")
    p.add_argument("--lane-voice", action="append", required=True, metavar="LANE=SAMPLE.mp3",
                   help="repeatable: actor_lane_id -> fish reference sample")
    p.add_argument("--video", required=True, help="scene video to mux over")
    p.add_argument("--bed", required=True, help="music/FX stem (absolute-time full stem)")
    p.add_argument("--window-start", type=float, required=True)
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    import numpy as np
    import soundfile as sf
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from clonedub_v11_textguard import validate_blocks
    sys.path.insert(0, "/home/moin")
    import clonedub as CD

    doc = json.loads(Path(args.script).read_text(encoding="utf-8"))
    lines = doc["lines"]
    lane_voice = dict(kv.split("=", 1) for kv in args.lane_voice)

    # PREFLIGHT: textguard on every line, and every lane must have a voice.
    bad = validate_blocks(lines)
    if bad:
        print("PREFLIGHT REJECT:", bad)
        sys.exit(2)
    used_lanes = sorted({L["actor_lane_id"] for L in lines})
    missing = [l for l in used_lanes if l not in lane_voice]
    if missing:
        sys.exit("error: no voice for lanes %s" % missing)
    if len(set(lane_voice[l] for l in used_lanes)) < len(used_lanes):
        sys.exit("error: lanes must map to DISTINCT voices; got %s" % lane_voice)

    outdir = Path(args.outdir)
    bdir = outdir / "beats"
    bdir.mkdir(parents=True, exist_ok=True)

    # one fish reference per lane (cached)
    lane_ref = {}
    for lane in used_lanes:
        sample = lane_voice[lane]
        cache = outdir / ("ref_%s.json" % lane)
        if cache.is_file():
            lane_ref[lane] = json.loads(cache.read_text())["reference_id"]
        else:
            rid = CD.fish_clone([sample], "v11_6b_%s" % lane.lower())
            cache.write_text(json.dumps({"reference_id": rid, "sample": sample}))
            lane_ref[lane] = rid
        print("[lane] %-24s -> %s" % (lane, Path(sample).name))

    t0 = args.window_start
    timeline = np.zeros(int(args.duration * SR))
    notes = []
    # honor merge_with_next_for_tts: synth merged text once, span both beats
    i = 0
    while i < len(lines):
        L = lines[i]
        text = L["target_text_hi"]
        span_start, span_end = L["abs_start"], L["abs_end"]
        merged_ids = [L["line_id"]]
        if L.get("merge_with_next_for_tts") and i + 1 < len(lines):
            nxt = lines[i + 1]
            text = text + " " + nxt["target_text_hi"]
            span_end = nxt["abs_end"]
            merged_ids.append(nxt["line_id"])
            i += 1
        raw = bdir / ("%s.fish.wav" % L["line_id"])
        wav = bdir / ("%s.wav" % L["line_id"])
        if not wav.is_file():
            CD.fish_tts(text, lane_ref[L["actor_lane_id"]], str(raw))
            to_wav(raw, wav)
        x = trim_silence(np, load(np, sf, wav))
        x = fit(np, sf, x, span_end - span_start, bdir)
        x = set_rms(np, x, BLOCK_RMS_DBFS)
        pos = int((span_start - t0) * SR)
        end = min(pos + len(x), len(timeline))
        timeline[pos:end] += x[:end - pos]
        notes.append({"ids": merged_ids, "lane": L["actor_lane_id"],
                      "span": [round(span_start, 2), round(span_end, 2)],
                      "spoken_s": round(len(x) / SR, 2)})
        print("[beat] %-10s %-24s %.1f-%.1f spoken=%.1fs"
              % ("+".join(merged_ids), L["actor_lane_id"], span_start, span_end, len(x) / SR))
        i += 1

    # music/FX bed for the window
    bed_wav = outdir / "bed.wav"
    run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t0, "-i", args.bed,
         "-t", "%.3f" % args.duration, "-ac", "1", "-ar", str(SR),
         "-c:a", "pcm_s16le", str(bed_wav)])
    bed = load(np, sf, bed_wav) * (10 ** (BED_GAIN_DB / 20.0))
    n = min(len(bed), len(timeline))
    mix = timeline[:n] + bed[:n]
    peak = np.abs(mix).max()
    if peak > 0.99:
        mix *= 0.99 / peak
    mix_wav = outdir / "mix.wav"
    sf.write(str(mix_wav), mix, SR)

    preview = outdir / "scene_6b_1500_1561.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % (t0 - doc.get("local_offset_s", 0)),
         "-i", str(args.video), "-i", str(mix_wav), "-t", "%.3f" % args.duration,
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-shortest", str(preview)])

    (outdir / "gen_report.json").write_text(json.dumps({
        "tool": "clonedub_v11_gen_scene", "version": TOOL_VERSION,
        "scene": doc.get("scene"), "window": [t0, t0 + args.duration],
        "lane_voice": {l: Path(lane_voice[l]).name for l in used_lanes},
        "beats": notes, "preview": str(preview)}, indent=2), encoding="utf-8")
    print("preview: %s" % preview)
    return 0


if __name__ == "__main__":
    sys.exit(main())
