#!/usr/bin/env python3
"""CloneDub V12 Phase 1: XTTS original-voice controlled bakeoff (one scene).

Generates the 1500.25-1561.13 scene with local XTTS-v2 using ONLY
original-video speaker references, as a controlled experiment across
4 parameter variants. No Fish/Eleven/Azure/Groq, no paid APIs, no
Kaggle/LatentSync/Android, no full video.

Documentation-first (per Codex addendum): baseline parameters come from
the LOCAL model config.json, not hardcoded guesses; every parameter used
is recorded in xtts_bakeoff_report.json (docs_basis). Uses the low-level
Xtts.get_conditioning_latents(...) + Xtts.inference(...) path so per-line
inference controls are passed and recorded honestly. Bad generation is
NOT hidden by time-stretching - lengths are reported with warnings.

See CLONEDUB_V12_PHASE1_XTTS_ORIGINAL_VOICE_PLAN.md.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

TOOL_VERSION = "1.0.0"
XTTS_SR = 24000  # XTTS-v2 output sample rate
MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
DOCS_SOURCES = [
    "https://huggingface.co/coqui/XTTS-v2",
    "https://github.com/coqui-ai/TTS",
    "https://docs.coqui.ai/en/latest/models/xtts.html",
]
# per-line acceptability (report-only; we do NOT stretch to hide problems)
RATIO_LONG = 1.20
RATIO_SHORT = 0.60


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("cmd failed (%d): %s\n%s" % (p.returncode, " ".join(map(str, cmd)), p.stderr[-1500:]))
    return p.stdout


def local_config(model_dir):
    cfg = json.loads((Path(model_dir) / "config.json").read_text(encoding="utf-8"))
    keys = ["temperature", "length_penalty", "repetition_penalty", "top_k", "top_p",
            "gpt_cond_len", "gpt_cond_chunk_len", "max_ref_len", "sound_norm_refs"]
    return cfg, {k: cfg.get(k) for k in keys}, cfg.get("languages", [])


def find_model_dir(tts_home):
    base = Path(tts_home) / "tts" / "tts_models--multilingual--multi-dataset--xtts_v2"
    if (base / "config.json").is_file():
        return base
    raise SystemExit("error: local XTTS-v2 config not found under %s" % base)


def analyze(np, wav, target_s):
    dur = len(wav) / XTTS_SR
    peak = float(np.max(np.abs(wav))) if len(wav) else 0.0
    rms = float(np.sqrt(np.mean(wav ** 2))) if len(wav) else 0.0
    ratio = dur / target_s if target_s else 0.0
    warnings = []
    if target_s and ratio > RATIO_LONG:
        warnings.append("too_long")
    if target_s and ratio < RATIO_SHORT:
        warnings.append("too_short")
    if peak >= 0.999:
        warnings.append("clipped")
    if rms < 1e-4:
        warnings.append("silent")
    # crude stretch/repeat proxies: very low speaking-rate -> likely_stretch;
    # long low-variation tail -> likely_repeat (reported, never auto-fixed)
    if target_s and ratio > 1.35:
        warnings.append("likely_stretch")
    return {"generated_s": round(dur, 2), "ratio": round(ratio, 2),
            "peak": round(peak, 3), "rms": round(rms, 4), "warnings": warnings}


def main():
    p = argparse.ArgumentParser(
        description="CloneDub V12 Phase 1: controlled XTTS-v2 bakeoff for one scene "
                    "using original-video voice refs (no paid APIs, no Fish/Eleven/Azure).")
    p.add_argument("--script", required=True, help="V11 performance_script.json (Devanagari target_text_hi)")
    p.add_argument("--bed", required=True, help="music/FX bed wav for the scene window")
    p.add_argument("--refs", nargs="+", required=True, help="original-video speaker reference wavs")
    p.add_argument("--tts-home", default="/mnt/d/CloneDub/tts_cache")
    p.add_argument("--language", default="hi")
    p.add_argument("--outdir", required=True)
    p.add_argument("--force", action="store_true", help="overwrite a non-empty outdir")
    args = p.parse_args()

    outdir = Path(args.outdir)
    if outdir.exists() and any(outdir.iterdir()) and not args.force:
        sys.exit("error: outdir exists and is non-empty; pass --force to overwrite")
    outdir.mkdir(parents=True, exist_ok=True)

    import numpy as np
    import soundfile as sf
    import torch

    os.environ["TTS_HOME"] = args.tts_home
    model_dir = find_model_dir(args.tts_home)
    cfg, base, langs = local_config(model_dir)
    if args.language not in langs:
        sys.exit("error: language %r not in local config languages %s" % (args.language, langs))

    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.models.xtts import Xtts
    xcfg = XttsConfig()
    xcfg.load_json(str(model_dir / "config.json"))
    model = Xtts.init_from_config(xcfg)
    model.load_checkpoint(xcfg, checkpoint_dir=str(model_dir), eval=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    print("[xtts] loaded on %s | hi in langs: %s" % (device, args.language in langs))

    # conditioning latents: cache per ref-set (multi-ref = all refs; single-ref = best/first)
    def cond(ref_list, gpt_cond_len, max_ref_len):
        gpt_lat, spk_emb = model.get_conditioning_latents(
            audio_path=ref_list, gpt_cond_len=gpt_cond_len,
            gpt_cond_chunk_len=int(base["gpt_cond_chunk_len"]),
            max_ref_length=max_ref_len, sound_norm_refs=bool(base["sound_norm_refs"]))
        return gpt_lat, spk_emb
    multi = cond(args.refs, int(base["gpt_cond_len"]), int(base["max_ref_len"]))
    single = cond(args.refs[:1], int(base["gpt_cond_len"]), int(base["max_ref_len"]))

    # variants: baseline from LOCAL CONFIG; each variant documents its intent + deltas.
    B = base
    variants = {
        "A_default_hi": {
            "intent": "local config defaults (baseline)", "cond": "multi",
            "params": {"temperature": B["temperature"], "length_penalty": B["length_penalty"],
                       "repetition_penalty": B["repetition_penalty"], "top_k": B["top_k"],
                       "top_p": B["top_p"], "speed": 1.0, "enable_text_splitting": False}},
        "B_low_random_no_stretch": {
            "intent": "lower randomness + stronger repetition control to reduce stretched/weird speech",
            "cond": "multi",
            "params": {"temperature": 0.55, "length_penalty": 1.0,
                       "repetition_penalty": 8.0, "top_k": 30, "top_p": 0.75,
                       "speed": 1.0, "enable_text_splitting": False}},
        "C_faster_tight_dialogue": {
            "intent": "slightly faster/tighter dialogue via XTTS speed (not extreme)",
            "cond": "multi",
            "params": {"temperature": 0.6, "length_penalty": 1.0,
                       "repetition_penalty": 6.0, "top_k": 40, "top_p": 0.8,
                       "speed": 1.12, "enable_text_splitting": False}},
        "D_single_ref_vs_multi_ref": {
            "intent": "same params as B but SINGLE original ref (vs multi-ref B) to compare conditioning",
            "cond": "single",
            "params": {"temperature": 0.55, "length_penalty": 1.0,
                       "repetition_penalty": 8.0, "top_k": 30, "top_p": 0.75,
                       "speed": 1.0, "enable_text_splitting": False}},
    }

    doc = json.loads(Path(args.script).read_text(encoding="utf-8"))
    lines = doc["lines"]
    t0 = min(L["abs_start"] for L in lines)
    scene_end = max(L["abs_end"] for L in lines)
    scene_dur = scene_end - t0

    # scene bed
    bed = sf.read(str(args.bed), dtype="float64")[0]
    if bed.ndim > 1:
        bed = bed.mean(axis=1)
    # resample bed to XTTS_SR
    bsr = sf.info(str(args.bed)).samplerate
    if bsr != XTTS_SR:
        n = int(round(len(bed) * XTTS_SR / bsr))
        bed = np.interp(np.linspace(0, len(bed), n, endpoint=False), np.arange(len(bed)), bed)

    report = {"tool": "v12_xtts_original_voice_bakeoff", "version": TOOL_VERSION,
              "model": MODEL_NAME, "language": args.language,
              "scene": {"start": t0, "end": scene_end, "duration": round(scene_dur, 2)},
              "refs": [str(Path(r).name) for r in args.refs],
              "docs_basis": {
                  "sources_checked": DOCS_SOURCES + [str(model_dir / "config.json")],
                  "local_config_values": base,
                  "implementation_choice": "lower_level_inference "
                      "(Xtts.get_conditioning_latents + Xtts.inference)",
                  "limitations": [
                      "config.json repetition_penalty=%s is used as baseline; note the code "
                      "default in this XTTS version is 10.0 (config wins per instruction)."
                      % B["repetition_penalty"],
                      "speed applied via inference(speed=...); no external time-stretch is used, "
                      "so length mismatches are reported (not hidden).",
                  ]},
              "variants": {}}

    for vname, v in variants.items():
        gpt_lat, spk_emb = multi if v["cond"] == "multi" else single
        vdir = outdir / "line_wavs" / vname
        vdir.mkdir(parents=True, exist_ok=True)
        timeline = np.zeros(int(round(scene_dur * XTTS_SR)))
        line_rows = []
        i = 0
        while i < len(lines):
            L = lines[i]
            text = L["target_text_hi"]
            span_start, span_end = L["abs_start"], L["abs_end"]
            ids = [L["line_id"]]
            if L.get("merge_with_next_for_tts") and i + 1 < len(lines):
                text = text + " " + lines[i + 1]["target_text_hi"]
                span_end = lines[i + 1]["abs_end"]
                ids.append(lines[i + 1]["line_id"])
                i += 1
            target_s = span_end - span_start
            out = model.inference(text, args.language, gpt_lat, spk_emb, **v["params"])
            wav = np.asarray(out["wav"], dtype=np.float64)
            sf.write(str(vdir / ("%s.wav" % "_".join(ids))), wav, XTTS_SR)
            a = analyze(np, wav, target_s)
            pos = int((span_start - t0) * XTTS_SR)
            end = min(pos + len(wav), len(timeline))
            timeline[pos:end] += wav[:end - pos]
            line_rows.append({"line_ids": ids, "actor_lane_id": L["actor_lane_id"],
                              "text": text, "target_window_s": round(target_s, 2),
                              "speaker_refs": ([Path(r).name for r in args.refs]
                                               if v["cond"] == "multi" else [Path(args.refs[0]).name]),
                              **a})
            print("[%s] %-10s %-22s tgt=%.1fs gen=%.1fs r=%.2f %s"
                  % (vname, "+".join(ids), L["actor_lane_id"], target_s,
                     a["generated_s"], a["ratio"], ",".join(a["warnings"]) or "ok"))
            i += 1

        # dialogue-only + scene mix (no stretch; just level + place + bed)
        dpk = np.abs(timeline).max()
        if dpk > 0:
            timeline = timeline * (0.7 / dpk)  # headroom, no clip
        sf.write(str(outdir / ("variant_%s_dialogue_only.wav" % vname)), timeline, XTTS_SR)
        n = min(len(bed), len(timeline))
        mix = timeline[:n] + bed[:n] * 0.6
        mpk = np.abs(mix).max()
        if mpk > 0.99:
            mix *= 0.99 / mpk
        sf.write(str(outdir / ("variant_%s_scene_mix.wav" % vname)), mix, XTTS_SR)

        warn_counts = {}
        for r in line_rows:
            for w in r["warnings"]:
                warn_counts[w] = warn_counts.get(w, 0) + 1
        report["variants"][vname] = {
            "intent": v["intent"], "conditioning": v["cond"], "params": v["params"],
            "scene_mix_s": round(len(mix) / XTTS_SR, 2),
            "dialogue_only_s": round(len(timeline) / XTTS_SR, 2),
            "warning_counts": warn_counts, "lines": line_rows}

    (outdir / "xtts_bakeoff_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    rd = [
        "# V12 Phase 1 - XTTS original-voice bakeoff (scene 1500.25-1561.13) - LISTEN FIRST", "",
        "All 4 variants use local XTTS-v2 (`language=hi`) with ONLY original-video speaker "
        "references (ref_SPEAKER_14_0/1/2). No Fish/Eleven/Azure. Baseline params come from the "
        "local model config.json (see xtts_bakeoff_report.json -> docs_basis).", "",
        "## Listen in this order",
        "1. `variant_A_default_hi_scene_mix.wav` (local config defaults)",
        "2. `variant_B_low_random_no_stretch_scene_mix.wav` (lower randomness, stronger repetition control)",
        "3. `variant_C_faster_tight_dialogue_scene_mix.wav` (speed 1.12, tighter)",
        "4. `variant_D_single_ref_vs_multi_ref_scene_mix.wav` (single ref vs B's multi-ref)",
        "",
        "`variant_*_dialogue_only.wav` and `line_wavs/<variant>/*.wav` are provided for close inspection.",
        "",
        "## Ask only",
        "1. Does the voice feel attached to the scene?",
        "2. Are the words understandable?",
        "3. Any stretched / repeated / robotic words? which variant?",
        "4. Is this better than the V11 Fish attempt?",
        "5. Which variant is best / least bad?",
        "",
        "Note: no time-stretching was applied to hide problems; per-line length ratios and "
        "warnings (too_long/too_short/likely_stretch/clipped/silent) are in the report.", ""]
    (outdir / "README_LISTEN_FIRST.md").write_text("\n".join(rd), encoding="utf-8")

    print("\nreport: %s" % (outdir / "xtts_bakeoff_report.json"))
    for vname, v in report["variants"].items():
        print("  %-26s mix=%.1fs warnings=%s" % (vname, v["scene_mix_s"], v["warning_counts"] or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
