#!/usr/bin/env python3
"""CloneDub V11 Phase 3: voice/TTS bake-off for one test window.

Synthesizes the approved Phase 2 script blocks with each available
voice provider, assembles a 60s preview (dialogue placed on the block
timeline + existing music/FX stem, mux over the original video), and
runs the Phase 1 evaluator on every candidate.

See CLONEDUB_V11_PRO_DUB_MASTER_PLAN.md, Phase 3.

Providers (skipped gracefully if keys/deps are missing):
    edge_swara    edge-tts hi-IN-SwaraNeural            (free)
    azure_ananya  Azure REST hi-IN-AnanyaNeural         (paid, ~Rs.1 per run)
    eleven_v2     ElevenLabs eleven_multilingual_v2     (paid credits)
    fish_girl     fish.audio clone of F_GirlHindi.mp3   (free-tier model)

Runs under WSL with the SoniTranslate venv. Synthesized blocks are
cached by (provider, text) under the outdir, so re-runs do not re-bill.
Only reads production inputs; all writes stay inside --outdir.
"""

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

TOOL_VERSION = "1.0.0"

SR = 48000
BLOCK_RMS_DBFS = -22.0     # per-block dialogue level before final mix scaling
MAX_TEMPO = 1.08           # plan hard limit: preferred time-stretch ceiling
FIT_TRIGGER = 1.02         # speed up only if block overruns its window by this
OVERRUN_FLAG = 1.10        # still longer than this after fitting -> flag
TRIM_DROP_DB = 35.0        # frame quieter than peak frame by this is silence
TRIM_PAD_S = 0.05

EDGE_VOICE = "hi-IN-SwaraNeural"
AZURE_VOICES = ["hi-IN-AnanyaNeural", "hi-IN-SwaraNeural"]  # fallback order
ELEVEN_VOICE = os.environ.get("ELEVENLABS_FEMALE_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
ELEVEN_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
FISH_SAMPLE = "/mnt/d/FishSamples/F_GirlHindi.mp3"


def run(cmd, **kw):
    proc = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if proc.returncode != 0:
        raise RuntimeError("command failed (%d): %s\n%s"
                           % (proc.returncode, " ".join(map(str, cmd)), proc.stderr[-1500:]))
    return proc


def to_wav(src, dst, sr=SR):
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-vn", "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(dst)])


# ------------------------------------------------------------ providers

def synth_edge(text, out_wav, work):
    import asyncio
    import edge_tts
    mp3 = work.with_suffix(".mp3")
    asyncio.run(edge_tts.Communicate(text, EDGE_VOICE).save(str(mp3)))
    to_wav(mp3, out_wav)
    return {"voice": EDGE_VOICE, "chars": len(text), "cost": "free"}


def synth_azure(text, out_wav, work):
    import requests
    key = os.environ["AZURE_SPEECH_KEY"]
    region = os.environ["AZURE_SPEECH_REGION"]
    last = None
    for voice in AZURE_VOICES:
        ssml = ('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                'xml:lang="hi-IN"><voice name="%s">%s</voice></speak>'
                % (voice, text.replace("&", "&amp;").replace("<", "&lt;")))
        r = requests.post(
            "https://%s.tts.speech.microsoft.com/cognitiveservices/v1" % region,
            data=ssml.encode("utf-8"),
            headers={"Ocp-Apim-Subscription-Key": key,
                     "Content-Type": "application/ssml+xml",
                     "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                     "User-Agent": "clonedub-v11-bakeoff"},
            timeout=60)
        if r.status_code == 200:
            work.write_bytes(r.content)
            to_wav(work, out_wav)
            return {"voice": voice, "chars": len(text), "cost": "~$16/1M chars"}
        last = "%s -> HTTP %s %s" % (voice, r.status_code, r.text[:200])
    raise RuntimeError("azure tts failed: %s" % last)


def synth_eleven(text, out_wav, work):
    import requests
    r = requests.post(
        "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_128" % ELEVEN_VOICE,
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"],
                 "Content-Type": "application/json"},
        json={"text": text, "model_id": ELEVEN_MODEL},
        timeout=120)
    if r.status_code != 200:
        raise RuntimeError("elevenlabs HTTP %s %s" % (r.status_code, r.text[:200]))
    mp3 = work.with_suffix(".mp3")
    mp3.write_bytes(r.content)
    to_wav(mp3, out_wav)
    return {"voice": ELEVEN_VOICE, "model": ELEVEN_MODEL,
            "chars": len(text), "cost": "%d credits" % len(text)}


_fish_ref = {}

def synth_fish(text, out_wav, work, outdir=None):
    sys.path.insert(0, "/home/moin")
    import clonedub as CD
    cache = outdir / "fish_model.json"
    if "id" not in _fish_ref:
        if cache.is_file():
            _fish_ref["id"] = json.loads(cache.read_text())["reference_id"]
        else:
            _fish_ref["id"] = CD.fish_clone([FISH_SAMPLE], "v11_bakeoff_girl_hindi")
            cache.write_text(json.dumps({"reference_id": _fish_ref["id"],
                                         "sample": FISH_SAMPLE}))
    raw = work.with_suffix(".fish.wav")
    CD.fish_tts(text, _fish_ref["id"], str(raw))
    to_wav(raw, out_wav)
    return {"voice": "fish:" + Path(FISH_SAMPLE).name, "chars": len(text),
            "cost": "free-tier model"}


PROVIDERS = {
    "edge_swara": {"synth": synth_edge, "needs_env": []},
    "azure_ananya": {"synth": synth_azure, "needs_env": ["AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"]},
    "eleven_v2": {"synth": synth_eleven, "needs_env": ["ELEVENLABS_API_KEY"]},
    "fish_girl": {"synth": synth_fish, "needs_env": ["FISH_KEY_1"], "wants_outdir": True},
}


# ------------------------------------------------------------ audio ops

def load(np, sf, path):
    x, sr = sf.read(str(path), dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x, sr


def trim_silence(np, x, sr):
    frame = int(0.02 * sr)
    if len(x) < 2 * frame:
        return x
    n = len(x) // frame
    env = np.sqrt(np.mean(x[:n * frame].reshape(n, frame) ** 2, axis=1))
    peak_db = 20 * np.log10(env.max() + 1e-12)
    active = 20 * np.log10(env + 1e-12) > peak_db - TRIM_DROP_DB
    idx = np.where(active)[0]
    if not len(idx):
        return x
    pad = int(TRIM_PAD_S * sr)
    s = max(0, idx[0] * frame - pad)
    e = min(len(x), (idx[-1] + 1) * frame + pad)
    return x[s:e]


def fit_tempo(np, sf, x, target_s, work):
    dur = len(x) / SR
    flags = []
    if dur > target_s * FIT_TRIGGER and target_s > 0:
        tempo = min(dur / target_s, MAX_TEMPO)
        a, b = work / "fit_in.wav", work / "fit_out.wav"
        sf.write(str(a), x, SR)
        run(["ffmpeg", "-y", "-v", "error", "-i", str(a),
             "-filter:a", "atempo=%.4f" % tempo, str(b)])
        x, _ = load(np, sf, b)
        flags.append("tempo=%.3f" % tempo)
        dur = len(x) / SR
    if target_s > 0 and dur > target_s * OVERRUN_FLAG:
        flags.append("OVERRUN: %.2fs into %.2fs window" % (dur, target_s))
    return x, flags


def rms_scale(np, x, target_dbfs):
    rms = np.sqrt(np.mean(x ** 2))
    if rms <= 0:
        return x
    return x * (10 ** (target_dbfs / 20.0) / rms)


# ------------------------------------------------------------ assembly

def build_candidate(name, spec, blocks, args, paths, np, sf):
    cdir = paths["outdir"] / ("candidate_%s" % name)
    bdir = cdir / "blocks"
    bdir.mkdir(parents=True, exist_ok=True)
    t0 = args.window_start
    timeline = np.zeros(int(args.duration * SR))
    notes, meta = [], {}
    for b in blocks:
        wav = bdir / ("%s.wav" % b["id"])
        sig = hashlib.sha256((name + "|" + b["target_text_hi"]).encode()).hexdigest()[:16]
        meta_f = bdir / ("%s.json" % b["id"])
        if not (wav.is_file() and meta_f.is_file()
                and json.loads(meta_f.read_text()).get("sig") == sig):
            kw = {"outdir": cdir} if spec.get("wants_outdir") else {}
            info = spec["synth"](b["target_text_hi"], wav, bdir / ("%s_raw" % b["id"]), **kw)
            info["sig"] = sig
            meta_f.write_text(json.dumps(info, ensure_ascii=False))
        meta[b["id"]] = json.loads(meta_f.read_text())
        x, _ = load(np, sf, wav)
        x = trim_silence(np, x, SR)
        x, flags = fit_tempo(np, sf, x, b["target_seconds"], bdir)
        x = rms_scale(np, x, BLOCK_RMS_DBFS)
        pos = int((b["start"] - t0) * SR)
        end = min(pos + len(x), len(timeline))
        timeline[pos:end] += x[:end - pos]
        spoken = len(x) / SR
        notes.append({"id": b["id"], "target_s": b["target_seconds"],
                      "spoken_s": round(spoken, 2), "flags": flags})
    music, _ = load(np, sf, paths["music_bed"])
    n = min(len(music), len(timeline))
    mix = music[:n] + timeline[:n]
    ref_rms = paths["ref_rms"]
    cur = np.sqrt(np.mean(mix ** 2))
    scale = ref_rms / cur if cur > 0 else 1.0
    peak = np.abs(mix).max() * scale
    if peak > 0.99:
        scale *= 0.99 / peak
        notes.append({"id": "_mix", "flags": ["peak-limited"]})
    mix *= scale
    mix_wav = cdir / "mix.wav"
    sf.write(str(mix_wav), mix, SR)
    preview = cdir / ("preview_%s_900_960.mp4" % name)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(paths["original"]), "-i", str(mix_wav),
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "192k", "-shortest", str(preview)])
    return preview, notes, meta


def run_evaluator(name, preview, args, paths):
    evaluate = Path(__file__).parent / "clonedub_v11_evaluate.py"
    outdir = paths["outdir"] / ("candidate_%s" % name) / "eval"
    proc = subprocess.run(
        [sys.executable, str(evaluate),
         "--original", str(paths["original"]), "--reference", str(paths["reference"]),
         "--candidate", str(preview), "--candidate-start", "0",
         "--duration", str(args.duration), "--outdir", str(outdir)],
        capture_output=True, text=True)
    eval_json = outdir / "eval.json"
    if not eval_json.is_file():
        raise RuntimeError("evaluator produced no eval.json: %s" % proc.stderr[-800:])
    return json.loads(eval_json.read_text(encoding="utf-8"))


# ------------------------------------------------------------ report

def write_report(path, args, results, blocks):
    lines = ["# CloneDub V11 Phase 3: TTS bake-off (%.0f-%.0fs)"
             % (args.window_start, args.window_start + args.duration), "",
             "Script: %s (%d blocks)" % (args.script, len(blocks)),
             "Benchmark: %s" % args.reference, "",
             "| candidate | verdict | active speech (s) | cov vs orig | cov vs Rask | "
             "silent while orig speaks (s) | RMS vs Rask (dB) | fit flags |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        if r.get("error"):
            lines.append("| %s | ERROR | - | - | - | - | - | %s |" % (r["name"], r["error"]))
            continue
        ev, comp = r["eval"], r["eval"]["comparisons"]
        cand = ev["tracks"]["candidate"]
        fit = "; ".join(f for n in r["notes"] for f in n["flags"]) or "none"
        lines.append("| %s | %s | %.2f | %.2f | %.2f | %.2f | %+.1f | %s |" % (
            r["name"], ev["verdict"], cand["active_speech_seconds"],
            comp["coverage_vs_original"], comp["coverage_vs_reference"],
            comp["candidate_silent_while_original_speaking_s"],
            comp["candidate_rms_delta_vs_reference_db"], fit))
    lines += ["", "Reference values: original active speech %.2fs, Rask %.2fs, old V1 35.97s "
              "(coverage 0.68, RMS +9.1 dB, FAIL)." % (
                  results[0]["eval"]["tracks"]["original"]["active_speech_seconds"],
                  results[0]["eval"]["tracks"]["reference"]["active_speech_seconds"])
              if results and not results[0].get("error") else "", ""]
    for r in results:
        if r.get("error"):
            lines += ["## %s" % r["name"], "", "ERROR: %s" % r["error"], ""]
            continue
        lines += ["## %s" % r["name"], "",
                  "- preview: `%s`" % r["preview"],
                  "- voices: %s" % ", ".join(sorted({m.get("voice", "?") for m in r["meta"].values()})),
                  "- cost: %s" % ", ".join(sorted({str(m.get("cost", "?")) for m in r["meta"].values()})),
                  "- per-block spoken vs target:"]
        for n in r["notes"]:
            if n["id"].startswith("_"):
                continue
            lines.append("  - %s: %.2fs into %.2fs window%s" % (
                n["id"], n["spoken_s"], n["target_s"],
                "  [" + "; ".join(n["flags"]) + "]" if n["flags"] else ""))
        lines += ["- subjective notes (fill after listening): _pending_", ""]
    lines += ["## How to listen", "",
              "Play each `candidate_*/preview_*_900_960.mp4` next to the Rask benchmark and old V1.",
              "Judge: robotic feel, stretched words, early cut-offs, external-narration feel.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description="CloneDub V11 Phase 3 voice/TTS bake-off "
                                            "for one test window.")
    p.add_argument("--script", required=True, help="Phase 2 script_blocks.json")
    p.add_argument("--original", required=True, help="original source clip (60s)")
    p.add_argument("--reference", required=True, help="Rask benchmark clip (60s)")
    p.add_argument("--music", required=True, help="music/FX stem of the FULL video")
    p.add_argument("--window-start", type=float, default=900.0)
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--providers", default=",".join(PROVIDERS),
                   help="comma-separated subset of: %s" % ", ".join(PROVIDERS))
    p.add_argument("--outdir", required=True)
    args = p.parse_args()

    import numpy as np
    import soundfile as sf

    doc = json.loads(Path(args.script).read_text(encoding="utf-8"))
    blocks = [b for b in doc["blocks"] if b["target_text_hi"]]
    if not blocks:
        sys.exit("error: script has no authored blocks")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    music_bed = outdir / "music_bed.wav"
    if not music_bed.is_file():
        run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % args.window_start,
             "-i", args.music, "-t", "%.3f" % args.duration,
             "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(music_bed)])
    ref_wav = outdir / "reference_60s.wav"
    if not ref_wav.is_file():
        to_wav(args.reference, ref_wav)
    ref_x, _ = load(np, sf, ref_wav)
    paths = {"outdir": outdir, "music_bed": music_bed,
             "original": Path(args.original), "reference": Path(args.reference),
             "ref_rms": float(np.sqrt(np.mean(ref_x ** 2)))}

    results = []
    for name in [n.strip() for n in args.providers.split(",") if n.strip()]:
        spec = PROVIDERS[name]
        missing = [v for v in spec["needs_env"] if not os.environ.get(v)]
        if missing:
            print("[skip] %s: missing env %s" % (name, missing))
            results.append({"name": name, "error": "missing env %s" % missing})
            continue
        print("[synth] %s ..." % name)
        try:
            preview, notes, meta = build_candidate(name, spec, blocks, args, paths, np, sf)
            ev = run_evaluator(name, preview, args, paths)
            results.append({"name": name, "preview": str(preview), "notes": notes,
                            "meta": meta, "eval": ev})
            print("[done] %s: verdict=%s active=%.2fs rms_delta=%+.1fdB"
                  % (name, ev["verdict"],
                     ev["tracks"]["candidate"]["active_speech_seconds"],
                     ev["comparisons"]["candidate_rms_delta_vs_reference_db"]))
        except Exception as e:
            print("[fail] %s: %s" % (name, e))
            results.append({"name": name, "error": str(e)[:400]})

    write_report(outdir / "phase3_report.md", args, results, blocks)
    print("\nreport: %s" % (outdir / "phase3_report.md"))
    ok = [r for r in results if not r.get("error")]
    print("candidates built: %d/%d" % (len(ok), len(results)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
