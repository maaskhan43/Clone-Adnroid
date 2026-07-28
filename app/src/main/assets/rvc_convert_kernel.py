# CloneCast converter kernel — RVC voice conversion on Kaggle T4.
# Single source of truth: app/src/main/assets/rvc_convert_kernel.py
# Pushed by the app (RvcAssets.kt) with __PLACEHOLDERS__ filled in.
# Gate 0 dry-run pushes this same file manually (see kaggle/README.md).
#
# Inputs:
#   model-dataset/ from the clonecast-rvc-train kernel's output (kernelDataSources)
#     -> model.pth, model.index, hubert_base/, rmvpe.pt
#   /kaggle/input/clonecast-input-audio/ dataset: input audio + job.json
# Output:
#   /kaggle/working/output.mp3           same duration as input
#   /kaggle/working/job_result.json      status + hashes + durations (written even on failure)

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import traceback

RUN_ID = "__RUN_ID__"
RVC_COMMIT = "__RVC_COMMIT__"
EXPECTED_SHA256 = "__INPUT_SHA256__"

AUDIO_DS = "/kaggle/input/clonecast-input-audio"


def find_model_dir():
    """model-dataset comes from the training kernel's mounted output; the exact
    mount folder name can vary, so search /kaggle/input for it."""
    candidates = ["/kaggle/input/clonecast-rvc-train/model-dataset",
                  "/kaggle/input/clonecast-rvc-model"]
    for root in sorted(os.listdir("/kaggle/input")):
        candidates.append(os.path.join("/kaggle/input", root, "model-dataset"))
    for c in candidates:
        if os.path.isfile(os.path.join(c, "model.pth")):
            return c
    raise RuntimeError(
        "Trained voice model not found in kernel inputs — run training first")


MODEL_DS = None  # resolved in validate_inputs()
WORK = "/kaggle/working"
RVC_DIR = os.path.join(WORK, "rvc")
RVC_REPO = "https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI"

# Conversion tuning (Phase 8.4 tunes these)
F0_METHOD = "rmvpe"
INDEX_RATE = 0.66
RMS_MIX_RATE = 0.25
PROTECT = 0.33
# Chunking
SILENCE_DB = -35        # dB threshold for silencedetect
MIN_SILENCE_S = 0.6     # min silence gap to split on
MAX_CHUNK_S = 45.0      # force-split chunks longer than this
EDGE_PAD_S = 0.15       # context padding around speech segments

result = {
    "run_id": RUN_ID,
    "status": "failed",
    "rvc_commit": RVC_COMMIT,
    "warnings": [],
}


def write_result():
    with open(os.path.join(WORK, "job_result.json"), "w") as f:
        json.dump(result, f, indent=2)


def log(msg):
    print("[clonecast] %s" % msg, flush=True)


def run(cmd, **kw):
    log("run: %s" % " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def find_input_audio():
    for name in sorted(os.listdir(AUDIO_DS)):
        if name.lower().endswith((".m4a", ".wav", ".mp3", ".flac", ".ogg", ".opus", ".aac")):
            return os.path.join(AUDIO_DS, name)
    raise RuntimeError("No audio file found in %s" % AUDIO_DS)


def validate_inputs():
    global MODEL_DS
    if not RUN_ID or RUN_ID.startswith("__"):
        raise RuntimeError("RUN_ID placeholder was not filled in")
    if not RVC_COMMIT or RVC_COMMIT.startswith("__"):
        raise RuntimeError("RVC_COMMIT placeholder was not filled in")
    MODEL_DS = find_model_dir()
    log("model dir: %s" % MODEL_DS)
    job_path = os.path.join(AUDIO_DS, "job.json")
    if not os.path.isfile(job_path):
        raise RuntimeError("job.json missing from input dataset")
    with open(job_path) as f:
        job = json.load(f)
    if job.get("run_id") != RUN_ID:
        raise RuntimeError(
            "Stale input dataset: job.json run_id=%s but kernel expects %s"
            % (job.get("run_id"), RUN_ID))
    audio = find_input_audio()
    actual_sha = sha256_of(audio)
    if EXPECTED_SHA256 and not EXPECTED_SHA256.startswith("__"):
        if actual_sha != EXPECTED_SHA256:
            raise RuntimeError("Input SHA-256 mismatch: dataset has a different file")
    if job.get("input_sha256") and job["input_sha256"] != actual_sha:
        raise RuntimeError("job.json SHA-256 does not match the audio file")
    result["input_sha256"] = actual_sha
    for required in ("model.pth", "model.index", "rmvpe.pt"):
        if not os.path.isfile(os.path.join(MODEL_DS, required)):
            raise RuntimeError("Model dataset is missing %s — run training (8.1) first" % required)
    if not os.path.isfile(os.path.join(MODEL_DS, "hubert_base", "config.json")):
        raise RuntimeError("Model dataset is missing hubert_base/ (transformers format)")
    return audio, job


def install_stack():
    t0 = time.time()
    # Torch pair first, pinned <2.8 per RVC requirments_cu128_py312.txt, official index.
    run([sys.executable, "-m", "pip", "install", "-q",
         "torch==2.7.1", "torchaudio==2.7.1",
         "--index-url", "https://download.pytorch.org/whl/cu128"])
    # Kaggle's preinstalled torchvision targets a newer torch; with 2.7.1 it
    # breaks transformers' import (torchvision::nms). RVC never uses it.
    run([sys.executable, "-m", "pip", "uninstall", "-q", "-y", "torchvision"])
    run(["git", "clone", RVC_REPO, RVC_DIR])
    run(["git", "-C", RVC_DIR, "checkout", RVC_COMMIT])
    # RVC's own py312 requirements, minus their mirror index lines; numpy<2 constrained.
    req_src = os.path.join(RVC_DIR, "requirments_cu128_py312.txt")
    req_dst = os.path.join(WORK, "requirements_filtered.txt")
    with open(req_src) as f:
        lines = [ln for ln in f if not ln.strip().startswith("--index-url")]
    with open(req_dst, "w") as f:
        f.writelines(lines)
    constraints = os.path.join(WORK, "constraints.txt")
    with open(constraints, "w") as f:
        f.write("numpy<2\ntorch==2.7.1\ntorchaudio==2.7.1\n")
    run([sys.executable, "-m", "pip", "install", "-q", "-r", req_dst, "-c", constraints])
    log("install done in %.0fs" % (time.time() - t0))


def link_assets():
    hubert_dst = os.path.join(RVC_DIR, "assets", "hubert_base")
    os.makedirs(os.path.join(RVC_DIR, "assets"), exist_ok=True)
    if not os.path.exists(hubert_dst):
        os.symlink(os.path.join(MODEL_DS, "hubert_base"), hubert_dst)
    os.environ["weight_root"] = MODEL_DS
    os.environ["rmvpe_root"] = MODEL_DS
    os.environ["index_root"] = MODEL_DS


def speech_segments(wav_path, total_s):
    """Silence-based segments [(start, end)] covering all speech, padded, max-length split."""
    proc = subprocess.run(
        ["ffmpeg", "-i", wav_path, "-af",
         "silencedetect=noise=%ddB:d=%s" % (SILENCE_DB, MIN_SILENCE_S),
         "-f", "null", "-"],
        capture_output=True, text=True)
    silences = []
    start = None
    for line in proc.stderr.splitlines():
        m = re.search(r"silence_start:\s*([0-9.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(r"silence_end:\s*([0-9.]+)", line)
        if m and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    if start is not None:
        silences.append((start, total_s))

    segments = []
    cursor = 0.0
    for s_start, s_end in silences:
        if s_start > cursor:
            segments.append((cursor, s_start))
        cursor = s_end
    if cursor < total_s:
        segments.append((cursor, total_s))
    if not segments:
        segments = [(0.0, total_s)]

    padded = []
    for seg_start, seg_end in segments:
        seg_start = max(0.0, seg_start - EDGE_PAD_S)
        seg_end = min(total_s, seg_end + EDGE_PAD_S)
        while seg_end - seg_start > MAX_CHUNK_S:
            padded.append((seg_start, seg_start + MAX_CHUNK_S))
            seg_start += MAX_CHUNK_S
        padded.append((seg_start, seg_end))
    return padded


def convert():
    audio_src, job = validate_inputs()
    install_stack()
    link_assets()

    input_wav = os.path.join(WORK, "input.wav")
    run(["ffmpeg", "-y", "-i", audio_src, "-ac", "1", "-ar", "44100",
         "-sample_fmt", "s16", input_wav],
        capture_output=True)
    total_s = ffprobe_duration(input_wav)
    result["input_duration_s"] = total_s
    log("input duration %.2fs" % total_s)

    sys.path.insert(0, RVC_DIR)
    os.chdir(RVC_DIR)
    sys.argv = ["clonecast_convert"]
    import numpy as np
    import soundfile as sf
    import torch
    from configs.config import Config
    from infer.vc.modules import VC

    log("GPU: %s" % (torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NONE"))
    if not torch.cuda.is_available():
        result["warnings"].append("CUDA not available — running on CPU, very slow")

    config = Config()
    vc = VC(config)
    vc.get_vc("model.pth")
    tgt_sr = vc.tgt_sr
    log("model loaded, target sr=%d" % tgt_sr)

    segments = speech_segments(input_wav, total_s)
    log("%d speech segments" % len(segments))

    out_total = int(math.ceil(total_s * tgt_sr))
    timeline = np.zeros(out_total, dtype=np.int16)
    index_path = os.path.join(MODEL_DS, "model.index")
    drift_total = 0.0

    for i, (seg_start, seg_end) in enumerate(segments):
        chunk_path = os.path.join(WORK, "chunk_%04d.wav" % i)
        run(["ffmpeg", "-y", "-i", input_wav, "-ss", "%.3f" % seg_start,
             "-t", "%.3f" % (seg_end - seg_start), chunk_path],
            capture_output=True)
        info, (chunk_sr, converted) = vc.vc_single(
            0, chunk_path, 0, F0_METHOD, index_path, INDEX_RATE,
            0, RMS_MIX_RATE, PROTECT)
        if converted is None:
            raise RuntimeError("RVC failed on segment %d: %s" % (i, info))
        if chunk_sr != tgt_sr:
            raise RuntimeError("Unexpected sample rate %s from RVC" % chunk_sr)
        converted = np.asarray(converted, dtype=np.int16)
        # Place back at the original timeline offset; pad/trim to the slot.
        offset = int(round(seg_start * tgt_sr))
        slot = int(round((seg_end - seg_start) * tgt_sr))
        drift = (len(converted) - slot) / float(tgt_sr)
        drift_total += abs(drift)
        if abs(drift) > 0.25:
            result["warnings"].append(
                "segment %d drift %.3fs (converted %.2fs vs slot %.2fs)"
                % (i, drift, len(converted) / tgt_sr, slot / tgt_sr))
        usable = min(len(converted), slot, out_total - offset)
        timeline[offset:offset + usable] = converted[:usable]
        os.remove(chunk_path)
        log("segment %d/%d done (%.1f-%.1fs, drift %.3fs)"
            % (i + 1, len(segments), seg_start, seg_end, drift))

    out_wav = os.path.join(WORK, "output.wav")
    sf.write(out_wav, timeline, tgt_sr, subtype="PCM_16")
    out_mp3 = os.path.join(WORK, "output.mp3")
    # -t locks output duration exactly to the input duration.
    run(["ffmpeg", "-y", "-i", out_wav, "-ar", "44100", "-b:a", "192k",
         "-t", "%.3f" % total_s, out_mp3],
        capture_output=True)
    os.remove(out_wav)

    out_s = ffprobe_duration(out_mp3)
    result["output_duration_s"] = out_s
    result["duration_delta_s"] = abs(out_s - total_s)
    result["output_sha256"] = sha256_of(out_mp3)
    result["segments"] = len(segments)
    result["total_drift_s"] = drift_total
    if result["duration_delta_s"] > 1.0:
        raise RuntimeError(
            "Duration validation failed: in %.2fs out %.2fs" % (total_s, out_s))
    result["status"] = "ok"
    log("done: %.2fs -> %.2fs (delta %.3fs)" % (total_s, out_s, result["duration_delta_s"]))


try:
    convert()
except Exception:
    result["error"] = traceback.format_exc()
    log("FAILED:\n%s" % result["error"])
    write_result()
    sys.exit(1)
write_result()
