#!/usr/bin/env python3
"""CloneDub V12 Direction-2: duration-safe XTTS dialogue gate.

Generates each beat with up to N XTTS candidates, trims silence, measures
the ACTUAL spoken duration, and accepts a beat only if its spoken/target
ratio is within [MIN_RATIO, MAX_RATIO]. Beats that no candidate can
satisfy are marked FAILED and are NOT mixed. The final scene_mix +
preview are produced ONLY if every beat passes - no heavy time-stretch
is used to hide failure.

This exists because XTTS over-generates short dialogue beats; a duration
gate is mandatory before any scene mix. Local XTTS only, no paid APIs.

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
MAX_CANDIDATES = 5
MIN_RATIO = 0.85
MAX_RATIO = 1.10
BLOCK_RMS_DBFS = -20.0
TRIM_DROP_DB = 35.0
TRIM_PAD_S = 0.04
MILD_TEMPO_MAX = 1.06   # only mild fit allowed; never used to rescue a bad ratio

# baseline-B-like steady params; candidates vary temperature/speed to hit the window
BASE = {"length_penalty": 1.0, "repetition_penalty": 8.0, "top_k": 30, "top_p": 0.75,
        "enable_text_splitting": False}
# (temperature, speed) per candidate attempt - progressively faster/steadier to shorten
CANDIDATE_KNOBS = [(0.55, 1.0), (0.5, 1.08), (0.45, 1.12), (0.5, 1.15), (0.4, 1.18)]


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("cmd failed (%d): %s\n%s" % (p.returncode, " ".join(map(str, cmd)), p.stderr[-1500:]))
    return p.stdout


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


def main():
    p = argparse.ArgumentParser(description="V12 duration-safe XTTS dialogue gate (local XTTS, no paid).")
    p.add_argument("--script", required=True, help="duration-safe rewritten script json")
    p.add_argument("--bed", required=True)
    p.add_argument("--lane-ref", action="append", required=True, metavar="LANE=ref.wav")
    p.add_argument("--video")
    p.add_argument("--tts-home", default="/mnt/d/CloneDub/tts_cache")
    p.add_argument("--language", default="hi")
    p.add_argument("--outdir", required=True)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    outdir = Path(args.outdir)
    if outdir.exists() and any(outdir.iterdir()) and not args.force:
        sys.exit("error: outdir non-empty; pass --force")
    outdir.mkdir(parents=True, exist_ok=True)
    acc_dir = outdir / "accepted_line_wavs"
    rej_dir = outdir / "rejected_line_wavs"
    acc_dir.mkdir(exist_ok=True)
    rej_dir.mkdir(exist_ok=True)

    import numpy as np
    import soundfile as sf
    import torch
    os.environ["TTS_HOME"] = args.tts_home

    lane_ref = dict(kv.split("=", 1) for kv in args.lane_ref)
    if len(set(lane_ref.values())) < len(lane_ref):
        sys.exit("error: lanes must map to DISTINCT refs")

    doc = json.loads(Path(args.script).read_text(encoding="utf-8"))
    lines = doc["lines"]

    model_dir = Path(args.tts_home) / "tts" / "tts_models--multilingual--multi-dataset--xtts_v2"
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.models.xtts import Xtts
    cfg = XttsConfig()
    cfg.load_json(str(model_dir / "config.json"))
    model = Xtts.init_from_config(cfg)
    model.load_checkpoint(cfg, checkpoint_dir=str(model_dir), eval=True)
    model.to("cuda" if torch.cuda.is_available() else "cpu")

    lane_cond = {}
    for lane, ref in lane_ref.items():
        gpt, spk = model.get_conditioning_latents(
            audio_path=[ref], gpt_cond_len=int(cfg.gpt_cond_len),
            gpt_cond_chunk_len=int(cfg.gpt_cond_chunk_len),
            max_ref_length=int(cfg.max_ref_len), sound_norm_refs=True)
        lane_cond[lane] = (gpt, spk)

    def mild_fit(x, target_s, work):
        dur = len(x) / XTTS_SR
        if target_s > 0 and dur > target_s and dur / target_s <= MILD_TEMPO_MAX:
            a, b = work / "i.wav", work / "o.wav"
            sf.write(str(a), x, XTTS_SR)
            run(["ffmpeg", "-y", "-v", "error", "-i", str(a), "-filter:a",
                 "atempo=%.4f" % (dur / target_s), str(b)])
            x = load(np, sf, b)
        return x

    report = {"tool": "v12_xtts_duration_gate", "version": TOOL_VERSION,
              "ratio_gate": [MIN_RATIO, MAX_RATIO], "max_candidates": MAX_CANDIDATES,
              "lane_ref": {l: Path(r).name for l, r in lane_ref.items()}, "beats": []}
    accepted = {}
    all_pass = True

    for L in lines:
        lane = L["actor_lane_id"]; text = L["target_text_hi"]
        target_s = L["target_seconds"]; bid = L["line_id"]
        gpt, spk = lane_cond[lane]
        cand_rows = []
        best = None
        for ci, (temp, speed) in enumerate(CANDIDATE_KNOBS[:MAX_CANDIDATES]):
            out = model.inference(text, args.language, gpt, spk, temperature=temp, speed=speed, **BASE)
            wav = trim(np, np.asarray(out["wav"], dtype=np.float64))
            wav = mild_fit(wav, target_s, outdir)
            dur = len(wav) / XTTS_SR
            ratio = dur / target_s if target_s else 0
            ok = MIN_RATIO <= ratio <= MAX_RATIO
            cand_rows.append({"candidate": ci, "temperature": temp, "speed": speed,
                              "generated_s": round(dur, 2), "ratio": round(ratio, 2), "in_gate": ok})
            # keep the candidate closest to 1.0 for diagnostics; stop early on first pass
            if best is None or abs(ratio - 1.0) < abs(best[1] - 1.0):
                best = (wav, ratio, ci)
            if ok:
                best = (wav, ratio, ci)
                break
        wav, ratio, ci = best
        status = "ACCEPTED" if MIN_RATIO <= ratio <= MAX_RATIO else "FAILED"
        dest = (acc_dir if status == "ACCEPTED" else rej_dir) / ("%s.wav" % bid.replace("+", "_"))
        sf.write(str(dest), set_rms(np, wav, BLOCK_RMS_DBFS) if status == "ACCEPTED" else wav, XTTS_SR)
        if status == "ACCEPTED":
            accepted[bid] = (L, set_rms(np, wav, BLOCK_RMS_DBFS))
        else:
            all_pass = False
        report["beats"].append({"line_id": bid, "actor_lane_id": lane, "ref": Path(lane_ref[lane]).name,
                                "target_s": target_s, "text": text, "words": L.get("words"),
                                "chosen_candidate": ci, "generated_s": round(len(wav) / XTTS_SR, 2),
                                "ratio": round(ratio, 2), "status": status, "candidates": cand_rows})
        print("[%s] %-9s %-22s tgt=%.1f gen=%.1f r=%.2f (cand %d/%d)"
              % (status, bid, lane.replace("ACTOR_", ""), target_s, len(wav) / XTTS_SR, ratio,
                 ci + 1, len(cand_rows)))

    report["all_beats_pass"] = all_pass
    report["accepted"] = sum(1 for b in report["beats"] if b["status"] == "ACCEPTED")
    report["failed"] = [b["line_id"] for b in report["beats"] if b["status"] == "FAILED"]

    # scene_mix + preview ONLY if all pass
    if all_pass:
        t0 = min(L["abs_start"] for L in lines)
        scene_dur = max(L["abs_end"] for L in lines) - t0
        timeline = np.zeros(int(round(scene_dur * XTTS_SR)))
        for bid, (L, wav) in accepted.items():
            pos = int((L["abs_start"] - t0) * XTTS_SR)
            end = min(pos + len(wav), len(timeline))
            timeline[pos:end] += wav[:end - pos]
        dpk = np.abs(timeline).max()
        if dpk > 0:
            timeline *= 0.7 / dpk
        sf.write(str(outdir / "dialogue_only.wav"), timeline, XTTS_SR)
        bed = load(np, sf, args.bed)
        n = min(len(bed), len(timeline))
        mix = timeline[:n] + bed[:n] * 0.6
        mpk = np.abs(mix).max()
        if mpk > 0.99:
            mix *= 0.99 / mpk
        sf.write(str(outdir / "scene_mix.wav"), mix, XTTS_SR)
        if args.video:
            run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % (t0 - doc.get("local_offset_s", 0)),
                 "-i", str(args.video), "-i", str(outdir / "scene_mix.wav"), "-t", "%.3f" % scene_dur,
                 "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-shortest",
                 str(outdir / "scene_dialogue_1500_1561.mp4")])
        report["scene_mix"] = "scene_mix.wav"
        print("\nALL BEATS PASSED -> scene_mix + preview written")
    else:
        report["scene_mix"] = None
        print("\n%d beat(s) FAILED the duration gate -> NO scene_mix (as required): %s"
              % (len(report["failed"]), report["failed"]))

    (outdir / "candidate_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("report: %s" % (outdir / "candidate_report.json"))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
