#!/usr/bin/env python3
"""CloneDub V12 Direction-2: per-actor-lane XTTS dialogue scene generation.

Generates ONE dialogue scene from a 6A.1 performance script, giving each
actor lane a DISTINCT original-video voice reference (confirmed by the
user), conditioned with local XTTS-v2. This is the real dialogue-feel
test - a true dialogue scene with visible speakers, not the 900-960
narration.

Local XTTS only (no paid APIs, no Fish/Eleven/Azure). No full-video,
no Android, no Kaggle. Honest per-line timing (no stretch to hide).

See CLONEDUB_V12_RASKLIKE_SYSTEM_PLAN.md (Direction 2).
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

TOOL_VERSION = "1.0.0"
XTTS_SR = 24000
BLOCK_RMS_DBFS = -20.0
FIT_TRIGGER = 1.08
MAX_TEMPO = 1.12
TRIM_DROP_DB = 35.0
TRIM_PAD_S = 0.05
# baseline-B-like params (steadiest read from Phase 1B listening)
XTTS_PARAMS = {"temperature": 0.55, "length_penalty": 1.0, "repetition_penalty": 8.0,
               "top_k": 30, "top_p": 0.75, "speed": 1.0, "enable_text_splitting": False}


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("cmd failed (%d): %s\n%s" % (p.returncode, " ".join(map(str, cmd)), p.stderr[-1500:]))
    return p.stdout


def to_wav(src, dst, sr=XTTS_SR):
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1",
         "-ar", str(sr), "-c:a", "pcm_s16le", str(dst)])


def load(np, sf, path):
    x, sr = sf.read(str(path), dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != XTTS_SR:
        n = int(round(len(x) * XTTS_SR / sr))
        x = np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x)
    return x


def trim(np, x):
    frame = int(0.02 * XTTS_SR)
    if len(x) < 2 * frame:
        return x
    n = len(x) // frame
    env = np.sqrt(np.mean(x[:n * frame].reshape(n, frame) ** 2, axis=1))
    pk = 20 * np.log10(env.max() + 1e-12)
    active = 20 * np.log10(env + 1e-12) > pk - TRIM_DROP_DB
    idx = np.where(active)[0]
    if not len(idx):
        return x
    pad = int(TRIM_PAD_S * XTTS_SR)
    return x[max(0, idx[0] * frame - pad):min(len(x), (idx[-1] + 1) * frame + pad)]


def set_rms(np, x, db):
    r = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    return x if r <= 0 else x * (10 ** (db / 20.0) / r)


def fit(np, sf, x, target_s, work):
    dur = len(x) / XTTS_SR
    if target_s > 0 and dur > target_s * FIT_TRIGGER:
        tempo = min(dur / target_s, MAX_TEMPO)
        a, b = work / "in.wav", work / "out.wav"
        sf.write(str(a), x, XTTS_SR)
        run(["ffmpeg", "-y", "-v", "error", "-i", str(a), "-filter:a", "atempo=%.4f" % tempo, str(b)])
        x = load(np, sf, b)
    return x


def main():
    p = argparse.ArgumentParser(description="V12 Direction-2 per-lane XTTS dialogue scene (local XTTS, no paid).")
    p.add_argument("--script", required=True, help="6A.1 performance_script.json (lines w/ actor_lane_id)")
    p.add_argument("--bed", required=True, help="scene music/FX bed wav")
    p.add_argument("--lane-ref", action="append", required=True, metavar="LANE=ref.wav",
                   help="repeatable: actor_lane_id -> original-video ref wav (distinct per lane)")
    p.add_argument("--video", help="scene video to mux over (optional)")
    p.add_argument("--tts-home", default="/mnt/d/CloneDub/tts_cache")
    p.add_argument("--language", default="hi")
    p.add_argument("--outdir", required=True)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    outdir = Path(args.outdir)
    if outdir.exists() and any(outdir.iterdir()) and not args.force:
        sys.exit("error: outdir non-empty; pass --force")
    outdir.mkdir(parents=True, exist_ok=True)

    import numpy as np
    import soundfile as sf
    import torch
    os.environ["TTS_HOME"] = args.tts_home

    lane_ref = dict(kv.split("=", 1) for kv in args.lane_ref)
    # distinct-voice guard: no two lanes share a ref
    if len(set(lane_ref.values())) < len(lane_ref):
        sys.exit("error: lanes must map to DISTINCT refs; got %s" % lane_ref)

    doc = json.loads(Path(args.script).read_text(encoding="utf-8"))
    lines = doc["lines"]
    used = sorted({L["actor_lane_id"] for L in lines})
    missing = [l for l in used if l not in lane_ref]
    if missing:
        sys.exit("error: no ref for lanes %s" % missing)

    model_dir = Path(args.tts_home) / "tts" / "tts_models--multilingual--multi-dataset--xtts_v2"
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.models.xtts import Xtts
    cfg = XttsConfig()
    cfg.load_json(str(model_dir / "config.json"))
    model = Xtts.init_from_config(cfg)
    model.load_checkpoint(cfg, checkpoint_dir=str(model_dir), eval=True)
    model.to("cuda" if torch.cuda.is_available() else "cpu")
    print("[xtts] loaded; lanes -> refs:")

    # conditioning latents per lane (cached)
    lane_cond = {}
    for lane in used:
        ref = lane_ref[lane]
        gpt_lat, spk = model.get_conditioning_latents(
            audio_path=[ref], gpt_cond_len=int(cfg.gpt_cond_len),
            gpt_cond_chunk_len=int(cfg.gpt_cond_chunk_len),
            max_ref_length=int(cfg.max_ref_len), sound_norm_refs=True)
        lane_cond[lane] = (gpt_lat, spk)
        print("  %-24s -> %s" % (lane, Path(ref).name))

    t0 = min(L["abs_start"] for L in lines)
    scene_end = max(L["abs_end"] for L in lines)
    scene_dur = scene_end - t0
    timeline = np.zeros(int(round(scene_dur * XTTS_SR)))
    bdir = outdir / "line_wavs"
    bdir.mkdir(exist_ok=True)

    rows = []
    i = 0
    while i < len(lines):
        L = lines[i]
        text = L["target_text_hi"]
        s, e = L["abs_start"], L["abs_end"]
        ids = [L["line_id"]]
        if L.get("merge_with_next_for_tts") and i + 1 < len(lines):
            text = text + " " + lines[i + 1]["target_text_hi"]
            e = lines[i + 1]["abs_end"]
            ids.append(lines[i + 1]["line_id"])
            i += 1
        gpt_lat, spk = lane_cond[L["actor_lane_id"]]
        out = model.inference(text, args.language, gpt_lat, spk, **XTTS_PARAMS)
        wav = np.asarray(out["wav"], dtype=np.float64)
        sf.write(str(bdir / ("%s.wav" % "_".join(ids))), wav, XTTS_SR)
        x = trim(np, wav)
        x = fit(np, sf, x, e - s, bdir)
        x = set_rms(np, x, BLOCK_RMS_DBFS)
        pos = int((s - t0) * XTTS_SR)
        end = min(pos + len(x), len(timeline))
        timeline[pos:end] += x[:end - pos]
        ratio = (len(x) / XTTS_SR) / (e - s) if e > s else 0
        warn = [w for w, c in [("too_long", ratio > 1.2), ("too_short", ratio < 0.6)] if c]
        rows.append({"line_ids": ids, "actor_lane_id": L["actor_lane_id"],
                     "ref": Path(lane_ref[L["actor_lane_id"]]).name,
                     "target_s": round(e - s, 2), "generated_s": round(len(x) / XTTS_SR, 2),
                     "ratio": round(ratio, 2), "warnings": warn})
        print("[gen] %-10s %-24s %s tgt=%.1f gen=%.1f r=%.2f %s"
              % ("+".join(ids), L["actor_lane_id"], Path(lane_ref[L["actor_lane_id"]]).stem,
                 e - s, len(x) / XTTS_SR, ratio, ",".join(warn) or "ok"))
        i += 1

    dpk = np.abs(timeline).max()
    if dpk > 0:
        timeline = timeline * (0.7 / dpk)
    sf.write(str(outdir / "dialogue_only.wav"), timeline, XTTS_SR)
    bed = load(np, sf, args.bed)
    n = min(len(bed), len(timeline))
    mix = timeline[:n] + bed[:n] * 0.6
    mpk = np.abs(mix).max()
    if mpk > 0.99:
        mix *= 0.99 / mpk
    sf.write(str(outdir / "scene_mix.wav"), mix, XTTS_SR)

    preview = None
    if args.video:
        mix_wav = outdir / "scene_mix.wav"
        preview = outdir / "scene_dialogue_1500_1561.mp4"
        local_seek = t0 - doc.get("local_offset_s", 0)
        run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % local_seek, "-i", str(args.video),
             "-i", str(mix_wav), "-t", "%.3f" % scene_dur, "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac",
             "-b:a", "192k", "-shortest", str(preview)])

    report = {"tool": "v12_xtts_scene_dialogue", "version": TOOL_VERSION,
              "scene": [t0, scene_end], "language": args.language,
              "xtts_params": XTTS_PARAMS,
              "lane_ref": {l: Path(lane_ref[l]).name for l in used},
              "scene_mix_s": round(len(mix) / XTTS_SR, 2),
              "lines": rows, "preview": str(preview) if preview else None}
    (outdir / "dialogue_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    (outdir / "README_LISTEN.md").write_text("\n".join([
        "# V12 Direction-2 dialogue scene test (1500.25-1561.13)", "",
        "Real dialogue scene, per-character DISTINCT original voice (user-confirmed):",
        "- A concerned girl = SPEAKER_17",
        "- B cake-covered boy = SPEAKER_13 (male)",
        "- C accuser = SPEAKER_09",
        "- D defending girl = SPEAKER_04", "",
        "Listen: `scene_mix.wav` (dialogue+bed). `dialogue_only.wav` = voices only. "
        "`line_wavs/` = per beat.", "",
        "Ask: (1) do characters feel distinct (right voice per person)? (2) does it feel like a "
        "real argument in the scene? (3) better than the earlier Fish 6B attempt? (4) is the issue "
        "now voice-model/acting rather than mapping?", ""]), encoding="utf-8")

    print("\nreport: %s" % (outdir / "dialogue_report.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
