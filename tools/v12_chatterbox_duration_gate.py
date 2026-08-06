#!/usr/bin/env python3
"""CloneDub V12 Direction-2: Chatterbox (Resemble) duration-safe dialogue gate.

Same duration gate as the XTTS tool, but the backend is Chatterbox
Multilingual V3 (Hindi supported via language_id='hi', voice cloning via
audio_prompt_path). Per beat: up to N candidates, trim silence, measure
spoken duration, accept only if ratio in [MIN,MAX]; scene_mix + preview
ONLY if every beat passes. Emits a candidate_report comparing this run's
gate result to the prior XTTS run.

Local model only, no paid APIs. Requires the isolated chatterbox venv.

Refs: https://github.com/resemble-ai/chatterbox
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

TOOL_VERSION = "1.0.0"
OUT_SR = 24000
MAX_CANDIDATES = 3
MIN_RATIO = 0.85
MAX_RATIO = 1.10
BLOCK_RMS_DBFS = -20.0
TRIM_DROP_DB = 35.0
TRIM_PAD_S = 0.04
MILD_TEMPO_MAX = 1.06
# Chatterbox generate() (installed 0.1.7) exposes: exaggeration, cfg_weight, temperature,
# repetition_penalty, min_p, top_p. Candidates vary the pace/steadiness levers.
# (exaggeration, cfg_weight, temperature) - lower temp/exaggeration = steadier/tighter.
CANDIDATE_KNOBS = [(0.5, 0.5, 0.8), (0.4, 0.4, 0.6), (0.3, 0.3, 0.5)]


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("cmd failed (%d): %s\n%s" % (p.returncode, " ".join(map(str, cmd)), p.stderr[-1500:]))
    return p.stdout


def load(np, sf, path):
    x, sr = sf.read(str(path), dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != OUT_SR:
        n = int(round(len(x) * OUT_SR / sr))
        x = np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x)
    return x


def trim(np, x):
    frame = int(0.02 * OUT_SR)
    if len(x) < 2 * frame:
        return x
    n = len(x) // frame
    env = np.sqrt(np.mean(x[:n * frame].reshape(n, frame) ** 2, axis=1))
    pk = 20 * np.log10(env.max() + 1e-12)
    active = 20 * np.log10(env + 1e-12) > pk - TRIM_DROP_DB
    idx = np.where(active)[0]
    if not len(idx):
        return x
    pad = int(TRIM_PAD_S * OUT_SR)
    return x[max(0, idx[0] * frame - pad):min(len(x), (idx[-1] + 1) * frame + pad)]


def set_rms(np, x, db):
    r = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    return x if r <= 0 else x * (10 ** (db / 20.0) / r)


def main():
    p = argparse.ArgumentParser(description="V12 Chatterbox duration-safe dialogue gate (local model, no paid).")
    p.add_argument("--script", required=True, help="duration-safe rewritten script json")
    p.add_argument("--bed", required=True)
    p.add_argument("--lane-ref", action="append", required=True, metavar="LANE=ref.wav")
    p.add_argument("--video")
    p.add_argument("--xtts-report", help="prior XTTS candidate_report.json for comparison")
    p.add_argument("--language", default="hi")
    p.add_argument("--outdir", required=True)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    outdir = Path(args.outdir)
    if outdir.exists() and any(outdir.iterdir()) and not args.force:
        sys.exit("error: outdir non-empty; pass --force")
    outdir.mkdir(parents=True, exist_ok=True)
    acc_dir = outdir / "accepted_line_wavs"; acc_dir.mkdir(exist_ok=True)
    rej_dir = outdir / "rejected_line_wavs"; rej_dir.mkdir(exist_ok=True)

    import numpy as np
    import soundfile as sf
    import torch
    try:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    except ImportError as ex:
        sys.exit("error: chatterbox not importable in this interpreter (%s). Run with the "
                 "chatterbox venv python." % ex)

    lane_ref = dict(kv.split("=", 1) for kv in args.lane_ref)
    if len(set(lane_ref.values())) < len(lane_ref):
        sys.exit("error: lanes must map to DISTINCT refs")

    doc = json.loads(Path(args.script).read_text(encoding="utf-8"))
    lines = doc["lines"]

    import inspect
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # Installed 0.1.7 from_pretrained takes only (device); older-doc t3_model kwarg absent.
    model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    model_sr = getattr(model, "sr", 24000)
    # Verified installed generate() signature:
    #   generate(text, language_id, audio_prompt_path=None, exaggeration=0.5, cfg_weight=0.5,
    #            temperature=0.8, repetition_penalty=2.0, min_p=0.05, top_p=1.0)
    gen_params = set(inspect.signature(model.generate).parameters)
    supports_steer = {"exaggeration", "cfg_weight", "temperature"} <= gen_params
    print("[chatterbox] multilingual model on %s (sr=%d); generate() params: %s"
          % (device, model_sr, sorted(gen_params)))

    def mild_fit(x, target_s, work):
        dur = len(x) / OUT_SR
        if target_s > 0 and dur > target_s and dur / target_s <= MILD_TEMPO_MAX:
            a, b = work / "i.wav", work / "o.wav"
            sf.write(str(a), x, OUT_SR)
            run(["ffmpeg", "-y", "-v", "error", "-i", str(a), "-filter:a",
                 "atempo=%.4f" % (dur / target_s), str(b)])
            x = load(np, sf, b)
        return x

    def gen(text, ref, exaggeration, cfg_weight, temperature):
        kw = {"language_id": args.language, "audio_prompt_path": ref}
        if supports_steer:
            kw["exaggeration"] = exaggeration
            kw["cfg_weight"] = cfg_weight
            kw["temperature"] = temperature
        wav = model.generate(text, **kw)
        arr = wav.squeeze().detach().cpu().numpy().astype(np.float64)
        if model_sr != OUT_SR:
            n = int(round(len(arr) * OUT_SR / model_sr))
            arr = np.interp(np.linspace(0, len(arr), n, endpoint=False), np.arange(len(arr)), arr)
        return arr

    report = {"tool": "v12_chatterbox_duration_gate", "version": TOOL_VERSION,
              "backend": "chatterbox_multilingual_v3", "language": args.language,
              "model_sr": model_sr, "generate_params": sorted(gen_params),
              "exaggeration_cfg_supported": supports_steer,
              "ratio_gate": [MIN_RATIO, MAX_RATIO], "max_candidates": MAX_CANDIDATES,
              "lane_ref": {l: Path(r).name for l, r in lane_ref.items()}, "beats": []}
    accepted = {}
    all_pass = True

    for L in lines:
        lane = L["actor_lane_id"]; text = L["target_text_hi"]
        target_s = L["target_seconds"]; bid = L["line_id"]
        ref = lane_ref[lane]
        cand_rows = []
        best = None
        for ci, (exa, cfg, temp) in enumerate(CANDIDATE_KNOBS[:MAX_CANDIDATES]):
            wav = trim(np, gen(text, ref, exa, cfg, temp))
            wav = mild_fit(wav, target_s, outdir)
            dur = len(wav) / OUT_SR
            ratio = dur / target_s if target_s else 0
            ok = MIN_RATIO <= ratio <= MAX_RATIO
            cand_rows.append({"candidate": ci, "exaggeration": exa, "cfg_weight": cfg,
                              "temperature": temp, "generated_s": round(dur, 2),
                              "ratio": round(ratio, 2), "in_gate": ok})
            if best is None or abs(ratio - 1.0) < abs(best[1] - 1.0):
                best = (wav, ratio, ci)
            if ok:
                best = (wav, ratio, ci)
                break
        wav, ratio, ci = best
        status = "ACCEPTED" if MIN_RATIO <= ratio <= MAX_RATIO else "FAILED"
        dest = (acc_dir if status == "ACCEPTED" else rej_dir) / ("%s.wav" % bid.replace("+", "_"))
        sf.write(str(dest), set_rms(np, wav, BLOCK_RMS_DBFS) if status == "ACCEPTED" else wav, OUT_SR)
        if status == "ACCEPTED":
            accepted[bid] = (L, set_rms(np, wav, BLOCK_RMS_DBFS))
        else:
            all_pass = False
        report["beats"].append({"line_id": bid, "actor_lane_id": lane, "ref": Path(ref).name,
                                "target_s": target_s, "text": text,
                                "chosen_candidate": ci, "generated_s": round(len(wav) / OUT_SR, 2),
                                "ratio": round(ratio, 2), "status": status, "candidates": cand_rows})
        print("[%s] %-9s %-22s tgt=%.1f gen=%.1f r=%.2f (cand %d/%d)"
              % (status, bid, lane.replace("ACTOR_", ""), target_s, len(wav) / OUT_SR, ratio,
                 ci + 1, len(cand_rows)))

    report["all_beats_pass"] = all_pass
    report["accepted"] = sum(1 for b in report["beats"] if b["status"] == "ACCEPTED")
    report["failed"] = [b["line_id"] for b in report["beats"] if b["status"] == "FAILED"]

    # XTTS comparison
    if args.xtts_report and Path(args.xtts_report).is_file():
        xr = json.loads(Path(args.xtts_report).read_text(encoding="utf-8"))
        xacc = {b["line_id"]: b["status"] for b in xr.get("beats", [])}
        report["comparison_vs_xtts"] = {
            "xtts_accepted": sum(1 for v in xacc.values() if v == "ACCEPTED"),
            "xtts_total": len(xacc),
            "chatterbox_accepted": report["accepted"],
            "chatterbox_total": len(report["beats"]),
            "per_beat": [{"line_id": b["line_id"], "xtts": xacc.get(b["line_id"], "?"),
                          "chatterbox": b["status"], "chatterbox_ratio": b["ratio"]}
                         for b in report["beats"]]}

    if all_pass:
        t0 = min(L["abs_start"] for L in lines)
        scene_dur = max(L["abs_end"] for L in lines) - t0
        timeline = np.zeros(int(round(scene_dur * OUT_SR)))
        for bid, (L, wav) in accepted.items():
            pos = int((L["abs_start"] - t0) * OUT_SR)
            end = min(pos + len(wav), len(timeline))
            timeline[pos:end] += wav[:end - pos]
        dpk = np.abs(timeline).max()
        if dpk > 0:
            timeline *= 0.7 / dpk
        sf.write(str(outdir / "dialogue_only.wav"), timeline, OUT_SR)
        bed = load(np, sf, args.bed)
        n = min(len(bed), len(timeline))
        mix = timeline[:n] + bed[:n] * 0.6
        mpk = np.abs(mix).max()
        if mpk > 0.99:
            mix *= 0.99 / mpk
        sf.write(str(outdir / "scene_mix.wav"), mix, OUT_SR)
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
        print("\n%d beat(s) FAILED the gate -> NO scene_mix: %s" % (len(report["failed"]), report["failed"]))

    (outdir / "candidate_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("report: %s" % (outdir / "candidate_report.json"))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
